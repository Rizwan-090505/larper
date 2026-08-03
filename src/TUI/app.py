from __future__ import annotations
import re
import asyncio
from datetime import datetime
from pathlib import Path
from textual.app import App, ComposeResult
from textual.widgets import Static, ListView, ListItem, Label, Input
from textual.containers import Container, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.css.query import NoMatches
from textual import work

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
from src.agent import PersonalManagerAgent, AgentResult

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
        ("ctrl+q", "quit", "Quit"),
        ("ctrl+t", "toggle_mode", "Toggle Mode"),
        ("f3", "new_page", "New Page"),
        ("f4", "new_journal", "New Journal"),
        ("ctrl+i", "focus_input", "Focus Input"),
        ("escape", "focus_workspace", "Workspace"),
        ("h", "focus_previous_pane", "Pane Left"),
        ("j", "focus_next_pane", "Pane Down"),
        ("k", "focus_previous_pane", "Pane Up"),
        ("l", "focus_next_pane", "Pane Right"),
        ("shift+h", "previous_tab", "Prev Tab"),
        ("shift+l", "next_tab", "Next Tab"),
        ("H", "previous_tab", "Prev Tab"),
        ("L", "next_tab", "Next Tab"),
        ("g,n", "new_page", "New Page"),
        ("g,j", "new_journal", "New Journal"),
        ("x", "close_tab", "Close Tab"),
        ("m", "toggle_minimize_tab", "Minimize Tab"),
    ]

    def __init__(self):
        super().__init__()
        self._vim_mode = False
        self._agent = PersonalManagerAgent()
        self._active_pane_id = "agent-panel"

    def compose(self) -> ComposeResult:
        # ChatInput lives inside DefaultLayout/VimLayout — NOT here at app level.
        # Having it here AND inside a layout caused the double input box.
        yield DefaultLayout(id="default-layout")
        yield StatusBar(id="status-bar")

    def on_mount(self):
        """Called when app is mounted."""
        self._focus_input()
        self._log_agent("[cyan]Ready. Press F3 for pages, F4 for journals, Ctrl+T for nvim.[/cyan]")

    def on_chat_input_submitted(self, event: ChatInput.Submitted):
        """Handle chat input submission — bubbles up from inside layouts."""
        asyncio.create_task(self._handle_input(event.value))

    async def _handle_input(self, raw: str):
        raw = raw.strip()
        if not raw:
            return
        self._log_user(raw)
        self._set_status("Agent is reading local context...")
        try:
            result = await self._agent.run(raw)
        except Exception as exc:
            self._log_agent(f"[red]Agent error:[/red] {exc}")
            self._focus_input()
            return

        self._apply_agent_result(result)
        self._focus_input()

    def _apply_agent_result(self, result: AgentResult):
        action = result.action
        if action.intent == "task":
            self._add_task(action.text, due_date=action.date, tags=action.tags)
        elif action.intent == "event":
            self._add_event(action.text, time=action.time, date=action.date, tags=action.tags)
        elif action.intent == "question":
            self._log_agent(result.reply)
            self._set_status("Answered from local RAG")
        else:
            self._handle_freeform(action.text, tags=action.tags)

    def _ensure_capture_file(self) -> str:
        current = store.get_current_file()
        if current:
            return current
        filename = f"journals/{datetime.now().date().isoformat()}.md"
        store.set_current_file(filename)
        path = store.get_active_folder() / filename
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"# {datetime.now().date().isoformat()}\n\n", encoding="utf-8")
        try:
            self.query_one("#notes-panel", NotesPanel).refresh_notes()
        except NoMatches:
            pass
        return filename

    def _handle_freeform(self, text: str, tags: list[str] | None = None):
        self._ensure_capture_file()
        tag_text = " ".join(f"#{tag}" for tag in tags or [] if f"#{tag}" not in text)
        line = f"- {text}" + (f" {tag_text}" if tag_text else "")
        store.add_note_content(text)
        store.append_line_to_current_file(line)
        self._update_vim_panel(line)
        self._log_agent("Note saved.")
        self._set_status("Note saved")

    def _add_task(
        self,
        text: str,
        due_date: str | None = None,
        tags: list[str] | None = None,
    ):
        self._ensure_capture_file()
        item = store.add_item(text, date=due_date)
        if item:
            self._update_todos_panel(item)
            tag_text = " ".join(f"#{tag}" for tag in tags or [] if f"#{tag}" not in text)
            due_text = f" @due {due_date}" if due_date else ""
            line = f"- [ ] {text}{due_text}" + (f" {tag_text}" if tag_text else "")
            store.append_line_to_current_file(line)
            self._update_vim_panel(line)
            self._log_agent(f"[green]Task added:[/green] {text}")
            self._set_status(f"Task added: {text}")

    def _add_event(
        self,
        text: str,
        time: str | None = None,
        date: str | None = None,
        tags: list[str] | None = None,
    ):
        self._ensure_capture_file()
        item = store.add_item(text, time=time, date=date)
        if item:
            self._update_events_panel(item)
            tag_text = " ".join(f"#{tag}" for tag in tags or [] if f"#{tag}" not in text)
            when = " ".join(part for part in [date, time] if part)
            line = f"- [{when}] {text}" if when else f"- {text}"
            if tag_text:
                line = f"{line} {tag_text}"
            store.append_line_to_current_file(line)
            self._update_vim_panel(line)
            self._log_agent(f"[yellow]Event added:[/yellow] {text}" + (f" at {when}" if when else ""))
            self._set_status(f"Event added: {text}")

    def _log_user(self, msg: str):
        try:
            self.query_one("#agent-panel", AgentPanel).log_user(msg)
        except NoMatches:
            pass

    def _log_agent(self, msg: str):
        try:
            self.query_one("#agent-panel", AgentPanel).log_agent(msg)
        except NoMatches:
            pass

    def _set_status(self, msg: str):
        try:
            self.query_one("#status-bar", StatusBar).set_message(msg)
        except NoMatches:
            pass

    def _focus_input(self):
        try:
            self._clear_active_pane()
            self.query_one("#chat-input", ChatInput).focus_input()
            self._active_pane_id = "chat-input"
            self._set_status("Insert")
        except NoMatches:
            pass

    def _input_is_focused(self) -> bool:
        focused = self.focused
        if focused is None:
            return False
        if isinstance(focused, Input):
            return True
        return focused.id == "chat-input"

    def _pane_ids(self) -> list[str]:
        if self._vim_mode:
            return [
                "vim-panel",
                "agent-panel",
                "todos-panel",
                "events-panel",
                "notes-panel",
                "tab-bar",
                "chat-input",
            ]
        return ["agent-panel", "todos-panel", "events-panel", "notes-panel", "chat-input"]

    def _focus_pane(self, pane_id: str):
        try:
            self._clear_active_pane()
            if pane_id == "chat-input":
                self.query_one("#chat-input", ChatInput).focus_input()
            else:
                pane = self.query_one(f"#{pane_id}")
                pane.focus()
                pane.add_class("active-pane")
            self._active_pane_id = pane_id
            self._set_status(f"Pane: {pane_id.replace('-', ' ')}")
        except NoMatches:
            self._focus_first_available_pane()

    def _focus_first_available_pane(self):
        for pane_id in self._pane_ids():
            try:
                self.query_one(f"#{pane_id}")
                self._focus_pane(pane_id)
                return
            except NoMatches:
                continue

    def _clear_active_pane(self):
        for pane_id in self._pane_ids():
            try:
                self.query_one(f"#{pane_id}").remove_class("active-pane")
            except NoMatches:
                pass

    def _move_pane(self, step: int):
        panes = self._pane_ids()
        available = []
        for pane_id in panes:
            try:
                self.query_one(f"#{pane_id}")
                available.append(pane_id)
            except NoMatches:
                pass
        if not available:
            return
        if self._active_pane_id not in available:
            next_id = available[0]
        else:
            idx = available.index(self._active_pane_id)
            next_id = available[(idx + step) % len(available)]
        self._focus_pane(next_id)

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
        self._open_file(event.filepath)

    def on_notes_panel_edit_requested(self, event: NotesPanel.EditRequested):
        filepath = Path(event.filepath)
        if not filepath.is_absolute():
            filepath = store.get_active_folder() / filepath
        subdir = filepath.parent.name
        self._log_agent(f"[cyan]Opening nvim for {filepath.name}...[/cyan]")
        self._do_open_existing_note(filepath, subdir)

    def _open_file(self, filename: str):
        store.set_current_file(filename)
        if not self._vim_mode:
            self._switch_to_vim_mode()
        else:
            self._refresh_vim_layout(filename)
        try:
            sb = self.query_one("#status-bar", StatusBar)
            sb.current_file = filename
            sb.set_message(f"Opened {filename}")
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
            self._focus_pane("vim-panel" if store.get_current_file() else "agent-panel")
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
            for p_id, cls, method in [
                ("#notes-panel", NotesPanel, "refresh_notes"),
                ("#todos-panel", TodosPanel, "refresh_todos"),
                ("#events-panel", EventsPanel, "refresh_events"),
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
            self._focus_input()
        asyncio.create_task(do_switch())

    def _open_vim_note(self, subdir: str):
        """Entry point — logs and kicks off the worker."""
        self._log_agent(f"[cyan]Opening file selector for {subdir}...[/cyan]")
        self._do_open_vim_note(subdir)

    @work
    async def _do_open_existing_note(self, filepath: Path, subdir: str):
        if not self._vim_mode:
            self._switch_to_vim_mode()
            await asyncio.sleep(0.35)

        try:
            vim = self.query_one("#vim-panel", VimPanel)
        except NoMatches:
            self._log_agent("[red]✗ Editor panel not found[/red]")
            return

        try:
            with self.suspend():
                success, saved_path = vim.open_vim_editor(filepath, subdir, is_new=False)
            if success and saved_path:
                self.on_vim_panel_note_saved_internal(saved_path, subdir)
        except Exception as exc:
            self._log_agent(f"[red]✗ Editor error:[/red] {exc}")

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
            self._log_agent("[red]✗ Editor panel not found[/red]")
            return

        self._log_agent(f"[cyan]Launching nvim editor for {filepath.name}...[/cyan]")
        try:
            with self.suspend():
                success, saved_path = vim.open_vim_editor(filepath, subdir, is_new)

            if success and saved_path:
                self.on_vim_panel_note_saved_internal(saved_path, subdir)
            else:
                self._log_agent("[yellow]No changes made[/yellow]")
        except Exception as exc:
            self._log_agent(f"[red]✗ Editor error:[/red] {exc}")

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
        self._switch_to_default_mode() if self._vim_mode else self._switch_to_vim_mode()

    def action_focus_input(self):
        self._focus_input()

    def action_focus_workspace(self):
        self._focus_pane("vim-panel" if self._vim_mode else "agent-panel")

    def action_focus_next_pane(self):
        if self._input_is_focused():
            return
        self._move_pane(1)

    def action_focus_previous_pane(self):
        if self._input_is_focused():
            return
        self._move_pane(-1)

    def action_next_tab(self):
        if self._input_is_focused():
            return
        try:
            tab_bar = self.query_one("#tab-bar", TabBar)
            filename = tab_bar.next_file()
        except NoMatches:
            filename = None
        if filename:
            store.set_current_file(filename)
            self._refresh_vim_layout(filename)
            self._set_status(f"Tab: {filename}")

    def action_previous_tab(self):
        if self._input_is_focused():
            return
        try:
            tab_bar = self.query_one("#tab-bar", TabBar)
            filename = tab_bar.previous_file()
        except NoMatches:
            filename = None
        if filename:
            store.set_current_file(filename)
            self._refresh_vim_layout(filename)
            self._set_status(f"Tab: {filename}")

    def action_close_tab(self):
        if self._input_is_focused():
            return
        try:
            tab_bar = self.query_one("#tab-bar", TabBar)
            filename = tab_bar.close_active()
        except NoMatches:
            self._set_status("No tab bar")
            return
        if filename:
            store.set_current_file(filename)
            self._refresh_vim_layout(filename)
            self._set_status(f"Closed tab, now {filename}")
        else:
            store.clear_current_file()
            self._set_status("Closed last tab")

    def action_toggle_minimize_tab(self):
        if self._input_is_focused():
            return
        try:
            tab_bar = self.query_one("#tab-bar", TabBar)
            filename = tab_bar.toggle_minimize_active() or tab_bar.restore_last_minimized()
        except NoMatches:
            self._set_status("No tab bar")
            return
        if filename:
            store.set_current_file(filename)
            self._refresh_vim_layout(filename)
            self._set_status(f"Tab: {filename}")
        else:
            self._set_status("Tabs minimized")

    def action_quit(self):
        self.exit()

    def action_new_page(self):
        self._log_agent("[cyan]Opening new page...[/cyan]")
        self._open_vim_note("pages")

    def action_new_journal(self):
        self._log_agent("[cyan]Opening new journal...[/cyan]")
        self._open_vim_note("journals")
