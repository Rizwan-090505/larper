#TUI/app.py

from __future__ import annotations
import re
import asyncio
from textual.app import App, ComposeResult
from textual.widgets import Static
from textual.css.query import NoMatches

from layout import DefaultLayout, VimLayout
from widgets.chat_input import ChatInput
from widgets.agent_panel import AgentPanel
from widgets.todos import TodosPanel
from widgets.events import EventsPanel
from widgets.notes import NotesPanel
from widgets.vim import VimPanel
from widgets.tabs import TabBar
from widgets.status_bar import StatusBar
from state.store import store


ADD_TASK_RE = re.compile(r"^add task\s+(.+)$", re.IGNORECASE)
ADD_EVENT_RE = re.compile(r"^add event\s+(.+?)\s+at\s+(\d{1,2}:\d{2})$", re.IGNORECASE)


class FileSelectorScreen(ModalScreen):
    """Modal screen for selecting or creating files before opening vim."""
    
    DEFAULT_CSS = """
    FileSelectorScreen {
        align: center middle;
    }
    
    #file-selector-dialog {
        width: 80;
        height: 32;
        border: thick $accent;
        background: $surface;
        padding: 0;
    }
    
    #file-selector-dialog .dialog-header {
        background: $accent;
        color: $text;
        height: 3;
        padding: 1;
        text-style: bold;
        dock: top;
    }
    
    #file-selector-dialog .dialog-body {
        height: 1fr;
        padding: 1 2;
    }
    
    #file-selector-dialog .file-list-section {
        height: 1fr;
        border: solid $primary;
        margin-bottom: 1;
    }
    
    #file-selector-dialog ListView {
        height: 100%;
        background: $surface;
    }
    
    #file-selector-dialog ListItem {
        padding: 0 1;
    }
    
    #file-selector-dialog ListItem:hover {
        background: $primary-darken-1;
    }
    
    #file-selector-dialog ListItem.--highlight {
        background: $primary;
    }
    
    #file-selector-dialog .input-section {
        height: auto;
        border: solid $accent;
        padding: 1;
        background: $surface-darken-1;
        margin-bottom: 1;
    }
    
    #file-selector-dialog Input {
        width: 100%;
        margin-top: 1;
    }
    
    #file-selector-dialog .dialog-footer {
        height: 3;
        background: $surface-darken-1;
        padding: 1;
        text-align: center;
        color: $text-muted;
        dock: bottom;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+n", "focus_input", "New File"),
    ]

    def __init__(self, subdir: str = "pages"):
        super().__init__()
        self.subdir = subdir
        self._files: list[Path] = []

    def compose(self) -> ComposeResult:
        with Container(id="file-selector-dialog"):
            yield Static(
                f"  📁 Select or Create {self.subdir.title()}",
                classes="dialog-header"
            )
            
            with Vertical(classes="dialog-body"):
                with VerticalScroll(classes="file-list-section"):
                    yield ListView(id="file-list")
                
                with Container(classes="input-section"):
                    yield Label("[bold]New file name:[/bold]")
                    yield Input(
                        placeholder="my_note.md",
                        id="filename-input"
                    )
            
            yield Static(
                "[dim]↑↓[/dim] Navigate  [dim]Enter[/dim] Open/Create  [dim]Ctrl+N[/dim] New  [dim]Esc[/dim] Cancel",
                classes="dialog-footer"
            )

    def on_mount(self):
        self._load_files()
        self._focus_list()

    def _load_files(self):
        """Load existing files from the target directory."""
        target_dir = store.get_active_folder() / self.subdir
        if not target_dir.exists():
            target_dir.mkdir(parents=True, exist_ok=True)
        
        self._files = sorted(
            target_dir.glob("*.md"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )
        
        file_list = self.query_one("#file-list", ListView)
        file_list.clear()
        
        if not self._files:
            file_list.append(
                ListItem(Label("[dim italic]No existing files. Create one below ↓[/dim italic]"))
            )
        else:
            for filepath in self._files:
                mtime = filepath.stat().st_mtime
                from datetime import datetime
                ts = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
                label = f"📄 [bold]{filepath.name}[/bold]  [dim]({ts})[/dim]"
                file_list.append(ListItem(Label(label)))

    def _focus_list(self):
        """Focus the file list."""
        try:
            self.query_one("#file-list", ListView).focus()
        except:
            pass

    def action_focus_input(self):
        """Action to focus the input field."""
        try:
            self.query_one("#filename-input", Input).focus()
        except:
            pass

    def action_cancel(self):
        """Action to cancel and close the dialog."""
        self.dismiss(None)

    def on_list_view_selected(self, event: ListView.Selected):
        """Handle ListView selection (Enter key or mouse click)."""
        event.stop()
        
        # First check if user has typed something in the input
        try:
            input_widget = self.query_one("#filename-input", Input)
            if input_widget.value.strip():
                self._create_new_file(input_widget.value.strip())
                return
        except:
            pass
        
        # Otherwise, open the selected file from the list
        try:
            file_list = self.query_one("#file-list", ListView)
            index = file_list.index
            
            if index is not None and self._files and 0 <= index < len(self._files):
                selected_file = self._files[index]
                self.dismiss((selected_file, False))
            else:
                self.action_focus_input()
        except Exception:
            self.action_focus_input()

    def _create_new_file(self, filename: str):
        """Create a new file with the given name."""
        if not filename.endswith(".md"):
            filename += ".md"
        filepath = store.get_active_folder() / self.subdir / filename
        self.dismiss((filepath, True))

    def on_input_submitted(self, event: Input.Submitted):
        """Handle Enter key in the input field."""
        if event.input.id == "filename-input":
            value = event.input.value.strip()
            if value:
                self._create_new_file(value)


class DevWorkspaceApp(App):
    """Main TUI application for DevWorkspace."""
    
    CSS_PATH = "styles/app.css"
    
    BINDINGS = [
        ("f1", "toggle_mode", "Toggle Vim Mode"),
        ("f2", "focus_input", "Focus Input"),
        ("f10", "quit", "Quit"),
    ]

    def __init__(self):
        super().__init__()
        self._vim_mode = False

    def compose(self) -> ComposeResult:
        # ChatInput lives inside DefaultLayout/VimLayout — NOT here at app level.
        # Having it here AND inside a layout caused the double input box.
        yield DefaultLayout(id="default-layout")
        yield StatusBar(id="status-bar")

    def on_mount(self):
        """Called when app is mounted."""
        self._focus_input()

    # ─── Input Handling ───────────────────────────────────────────────────────

    def on_chat_input_submitted(self, event: ChatInput.Submitted):
        self._handle_input(event.value)

    def _handle_input(self, raw: str):
        raw = raw.strip()
        if not raw:
            return

        # Show user message in chat
        self._log_user(raw)

        # Parse strict commands OR treat as free-form note/query
        task_match = ADD_TASK_RE.match(raw)
        event_match = ADD_EVENT_RE.match(raw)

        if task_match:
            text = task_match.group(1).strip()
            self._add_task(text)
        elif event_match:
            text = event_match.group(1).strip()
            time = event_match.group(2).strip()
            self._add_event(text, time)
        else:
            # Free-form input — store as note content, show agent placeholder
            self._handle_freeform(raw)

        self._focus_input()

    def _handle_freeform(self, text: str):
        """Accept any free-form text — store it, show agent placeholder reply."""
        if store.get_current_file():
            store.add_note_content(text)
            self._update_vim_panel(f"  {text}")

        # Agent placeholder response
        self._log_agent(
            "📝 Note saved. "
            "[dim](Agent will analyze this for tasks, events, and insights.)[/dim]"
        )
        self._set_status("Note saved")

    def _add_task(self, text: str):
        if not store.get_current_file():
            self._log_agent("[yellow]⚠ Open a file first — click any note on the right.[/yellow]")
            return
        item = store.add_item(text)
        if item:
            self._update_todos_panel(item)
            self._update_vim_panel(f"[ ] {text}")
            self._log_agent(f"[green]✓ Task added:[/green] {text}")
            self._set_status(f"Task added: {text}")

    def _add_event(self, text: str, time: str):
        if not store.get_current_file():
            self._log_agent("[yellow]⚠ Open a file first — click any note on the right.[/yellow]")
            return
        item = store.add_item(text, time=time)
        if item:
            self._update_events_panel(item)
            self._update_vim_panel(f"[{time}] {text}")
            self._log_agent(f"[yellow]◷ Event added:[/yellow] {text} at {time}")
            self._set_status(f"Event added: {text} at {time}")

    # ─── Chat Logging ─────────────────────────────────────────────────────────

    def _log_user(self, msg: str):
        try:
            panel = self.query_one("#agent-panel", AgentPanel)
            panel.log_user(msg)
        except NoMatches:
            pass

    def _log_agent(self, msg: str):
        try:
            panel = self.query_one("#agent-panel", AgentPanel)
            panel.log_agent(msg)
        except NoMatches:
            pass

    def _log(self, msg: str):
        try:
            panel = self.query_one("#agent-panel", AgentPanel)
            panel.log_message(msg)
        except NoMatches:
            pass

    def _set_status(self, msg: str):
        try:
            sb = self.query_one("#status-bar", StatusBar)
            sb.set_message(msg)
        except NoMatches:
            pass

    def _focus_input(self):
        try:
            inp = self.query_one("#chat-input", ChatInput)
            inp.focus_input()
        except NoMatches:
            pass

    # ─── Panel Updates ────────────────────────────────────────────────────────

    def _update_todos_panel(self, item):
        try:
            self.query_one("#todos-panel", TodosPanel).add_todo(item)
        except NoMatches:
            pass

    def _update_events_panel(self, item):
        try:
            self.query_one("#events-panel", EventsPanel).add_event(item)
        except NoMatches:
            pass

    def _update_vim_panel(self, line: str):
        try:
            self.query_one("#vim-panel", VimPanel).append_line(line)
        except NoMatches:
            pass

    def on_notes_panel_file_selected(self, event: NotesPanel.FileSelected):
        # FIX: use filepath (full path) instead of filename (bare name)
        self._open_file(event.filepath)

    def on_notes_panel_edit_requested(self, event: NotesPanel.EditRequested):
        # FIX: handle 'e' key edit requests from the notes panel
        self._open_vim_note_at_path(Path(event.filepath))

    def _open_file(self, filepath: str):
        store.set_current_file(filepath)
        if not self._vim_mode:
            self._switch_to_vim_mode()
        else:
            self._refresh_vim_layout(filename)
        try:
            sb = self.query_one("#status-bar", StatusBar)
            sb.current_file = filepath
            sb.set_message(f"Opened {Path(filepath).name}")
        except NoMatches:
            pass
        self._log_agent(f"[cyan]📄 Opened:[/cyan] [bold]{filename}[/bold]")
        self._focus_input()

    def _refresh_vim_layout(self, filename: str):
        try:
            self.query_one("#vim-panel", VimPanel).load_file(filename)
            self.query_one("#tab-bar", TabBar).open_file(filename)
            self.query_one("#todos-panel", TodosPanel).refresh_todos()
            self.query_one("#events-panel", EventsPanel).refresh_events()
        except NoMatches:
            pass

    def _open_vim_note_at_path(self, filepath: Path):
        """Open a specific file path directly in vim (used by EditRequested)."""
        subdir = filepath.parent.name if filepath.parent.name in ("pages", "journals") else "pages"
        is_new = not filepath.exists()
        self._log_agent(f"[cyan]Opening {filepath.name} in vim...[/cyan]")
        self._do_open_vim_note_at_path(filepath, subdir, is_new)

    @work
    async def _do_open_vim_note_at_path(self, filepath: Path, subdir: str, is_new: bool):
        if not self._vim_mode:
            self._switch_to_vim_mode()
            await asyncio.sleep(0.35)
        try:
            vim = self.query_one("#vim-panel", VimPanel)
        except NoMatches:
            self._log_agent("[red]✗ Vim panel not found[/red]")
            return
        try:
            with self.suspend():
                success, saved_path = vim.open_vim_editor(filepath, subdir, is_new)
            if success and saved_path:
                self.on_vim_panel_note_saved_internal(saved_path, subdir)
            else:
                self._log_agent("[yellow]No changes made[/yellow]")
        except Exception as exc:
            self._log_agent(f"[red]✗ Vim error:[/red] {exc}")

    # ── Layout switching ──────────────────────────────────────────────────────

    def _switch_to_vim_mode(self):
        self._vim_mode = True

        async def do_switch():
            try:
                dl = self.query_one("#default-layout", DefaultLayout)
                dl.styles.animate("opacity", value=0.0, duration=0.18)
                await asyncio.sleep(0.2)
                dl.remove()
            except NoMatches:
                pass

            vim_layout = VimLayout(id="vim-layout")
            self.mount(vim_layout, before="#status-bar")
            vim_layout.styles.opacity = 0.0
            await asyncio.sleep(0.03)
            vim_layout.styles.animate("opacity", value=1.0, duration=0.22)
            await asyncio.sleep(0.12)

            if store.get_current_file():
                await self._animate_vim_panels(store.get_current_file())
            self._focus_input()
        asyncio.create_task(do_switch())

    async def _animate_vim_panels(self, filename: str):
        try:
            vim = self.query_one("#vim-panel", VimPanel)
            vim.styles.opacity = 0.0
            vim.load_file(filename)
            vim.styles.animate("opacity", value=1.0, duration=0.28)
            tabs = self.query_one("#tab-bar", TabBar)
            tabs.open_file(filename)
            await asyncio.sleep(0.06)
            for p_id, cls, method in [
                ("#todos-panel", TodosPanel, "refresh_todos"),
                ("#events-panel", EventsPanel, "refresh_events"),
                ("#notes-panel", NotesPanel, "refresh_notes"),
            ]:
                try:
                    p = self.query_one(p_id, cls)
                    p.styles.opacity = 0.0
                    if hasattr(p, method):
                        getattr(p, method)()
                    p.styles.animate("opacity", value=1.0, duration=0.25)
                    await asyncio.sleep(0.06)
                except NoMatches:
                    pass
        except NoMatches:
            pass

            self._focus_input()

        asyncio.get_event_loop().create_task(do_switch())

    def _switch_to_default_mode(self):
        self._vim_mode = False

        async def do_switch():
            try:
                vl = self.query_one("#vim-layout", VimLayout)
                vl.styles.animate("opacity", value=0.0, duration=0.18)
                await asyncio.sleep(0.2)
                vl.remove()
            except NoMatches:
                pass

            dl = DefaultLayout(id="default-layout")
            self.mount(dl, before="#status-bar")
            dl.styles.opacity = 0.0
            await asyncio.sleep(0.03)
            dl.styles.animate("opacity", value=1.0, duration=0.22)
            await asyncio.sleep(0.12)

            for panel_id, cls in [
                ("#notes-panel", NotesPanel),
                ("#todos-panel", TodosPanel),
                ("#events-panel", EventsPanel),
            ]:
                try:
                    w = self.query_one(panel_id, cls)
                    w.styles.opacity = 0.0
                    if hasattr(w, "refresh_notes"):
                        w.refresh_notes()
                    elif hasattr(w, "refresh_todos"):
                        w.refresh_todos()
                    elif hasattr(w, "refresh_events"):
                        w.refresh_events()
                    w.styles.animate("opacity", value=1.0, duration=0.25)
                    await asyncio.sleep(0.06)
                except NoMatches:
                    pass

            self._focus_input()
        asyncio.create_task(do_switch())

    def _open_vim_note(self, subdir: str):
        """Entry point — logs and kicks off the worker."""
        self._log_agent(f"[cyan]Opening file selector for {subdir}...[/cyan]")
        self._do_open_vim_note(subdir)

    @work
    async def _do_open_vim_note(self, subdir: str):
        """
        Textual @work worker — required so push_screen_wait is allowed.
        asyncio.create_task() cannot use push_screen_wait; @work can.
        """
        try:
            result = await self.push_screen_wait(FileSelectorScreen(subdir))
        except Exception as exc:
            self._log_agent(f"[red]✗ Error in file selector:[/red] {exc}")
            return

        if result is None:
            self._log_agent("[yellow]File selection cancelled[/yellow]")
            return

        filepath, is_new = result
        self._log_agent(f"[cyan]Selected: {filepath.name} (new={is_new})[/cyan]")

        if not self._vim_mode:
            self._log_agent("[cyan]Switching to vim mode...[/cyan]")
            self._switch_to_vim_mode()
            await asyncio.sleep(0.35)

        try:
            vim = self.query_one("#vim-panel", VimPanel)
        except NoMatches:
            self._log_agent("[red]✗ Vim panel not found[/red]")
            return

        self._log_agent(f"[cyan]Launching vim editor for {filepath.name}...[/cyan]")
        try:
            with self.suspend():
                success, saved_path = vim.open_vim_editor(filepath, subdir, is_new)

            if success and saved_path:
                self.on_vim_panel_note_saved_internal(saved_path, subdir)
            else:
                self._log_agent("[yellow]No changes made[/yellow]")
        except Exception as exc:
            self._log_agent(f"[red]✗ Vim error:[/red] {exc}")

    def on_vim_panel_note_saved(self, event: VimPanel.NoteSaved):
        self.on_vim_panel_note_saved_internal(event.filepath, event.subdir)

    def on_vim_panel_note_saved_internal(self, filepath, subdir):
        rel = filepath.relative_to(store.get_active_folder())
        self._log_agent(f"[green]✓ Saved[/green] [bold]{rel}[/bold]")
        self._set_status(f"Saved {rel}")
        try:
            self.query_one("#notes-panel", NotesPanel).refresh_notes()
        except NoMatches:
            pass

    # ── Actions ──────────────────────────────────────────────────────────────

    def action_toggle_mode(self):
        if self._vim_mode:
            self._switch_to_default_mode()
        else:
            self._switch_to_vim_mode()

    def action_focus_input(self):
        self._focus_input()

    def action_quit(self):
        self.exit()