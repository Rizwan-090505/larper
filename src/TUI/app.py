from __future__ import annotations
import asyncio
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import Input
from textual.widget import Widget
from textual.css.query import NoMatches
from textual.binding import Binding
from textual import work

from .layout import MainLayout
from .widgets.sidebar import SidebarPanel
from .widgets.chat_input import ChatInput
from .widgets.agent_panel import AgentPanel
from .widgets.todos import TodosPanel
from .widgets.notes import NotesPanel
from .widgets.status_bar import StatusBar
from .widgets.search_modal import SearchModal

# Import store based on how the module is being imported
try:
    from .state.store import store
except ImportError:
    from state.store import store

from src.agent import PersonalManagerAgent, AgentResult


class DevWorkspaceApp(App):
    """Single-screen personal knowledge manager. nvim via suspend()."""

    CSS_PATH = "styles/app.css"

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("i", "focus_input", "Input"),
        Binding("g", "g_prefix", "Go", priority=True, show=False),
        Binding("n", "g_prefix_notes", "Notes", priority=True, show=False),
        Binding("b", "g_prefix_sidebar", "Sidebar", priority=True, show=False),
        Binding("p", "g_prefix_page", "New Page", priority=True, show=False),
        ("/", "open_search", "Search"),
        ("escape", "escape_back", "Back"),
        ("h", "move_left", "Left"),
        ("j", "move_down", "Down"),
        ("k", "move_up", "Up"),
        ("l", "move_right", "Right"),
        ("G", "go_bottom", "Bottom"),
        ("x", "close_tab", "Close"),
        ("m", "minimize", "Minimize"),
        ("ctrl+t", "toggle_vim_mode", "Toggle Vim"),
    ]

    def __init__(self):
        super().__init__()
        self._agent = PersonalManagerAgent()
        self._g_prefix = False

    # ── Compose ───────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield MainLayout(id="main-layout")
        yield StatusBar(id="status-bar")

    def on_mount(self):
        # Show API key status on startup
        key = self._agent._api_key
        if key:
            self._log_agent(
                "ready. I can search your notes and chat — ask me anything, "
                "add a task, or press gj to open today's journal."
            )
            self._set_status("ready — claude online")
        else:
            self._log_agent(
                "[yellow]no GEMINI_API_KEY found.[/yellow] "
                "Add it to .env for full AI responses. "
                "Local search still works — try asking about your notes."
            )
            self._set_status("ready — local mode (no API key)")
        self._focus_input()
        
        # Start file watcher for auto-refresh
        self.run_worker(self._watch_file_changes(), exclusive=False, name="file-watcher")

    # ── Input ─────────────────────────────────────────────────────────────────

    def on_chat_input_submitted(self, event: ChatInput.Submitted):
        asyncio.create_task(self._handle_input(event.value))

    async def _handle_input(self, raw: str):
        raw = raw.strip()
        if not raw:
            return
        self._log_user(raw)
        self._set_status("thinking…", duration=0)
        try:
            result = await self._agent.run(raw)
        except Exception as exc:
            self._log_agent(f"[red]error:[/red] {exc}")
            self._focus_input()
            return
        self._apply_result(result)
        self._focus_input()

    def _apply_result(self, result: AgentResult):
        # Show tool traces (dim)
        try:
            self.query_one("#agent-panel", AgentPanel).log_tool_calls(result.tool_calls)
        except Exception:
            pass

        action = result.action
        if action.intent == "task":
            self._add_task(
                action.text, due_date=action.date, tags=action.tags, reply=result.reply
            )
        elif action.intent == "event":
            self._add_event(
                action.text,
                time=action.time,
                date=action.date,
                tags=action.tags,
                reply=result.reply,
            )
        elif action.intent in ("question", "chat"):
            self._log_agent(result.reply)
            self._set_status("done")
        else:
            self._handle_note(action.text, result.reply, tags=action.tags)

    # ── Note / task helpers ───────────────────────────────────────────────────

    def _ensure_capture_file(self) -> str:
        current = store.get_current_file()
        if current:
            return current
        filename = f"journals/{datetime.now().date().isoformat()}.md"
        store.set_current_file(filename)
        path = store.get_active_folder() / filename
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                f"# {datetime.now().date().isoformat()}\n\n", encoding="utf-8"
            )
        self._refresh_notes()
        return filename

    def _handle_note(self, text: str, reply: str, tags: list[str] | None = None):
        self._ensure_capture_file()
        tag_text = " ".join(f"#{t}" for t in tags or [] if f"#{t}" not in text)
        line = f"- {text}" + (f" {tag_text}" if tag_text else "")
        store.add_note_content(text)
        store.append_line_to_current_file(line)
        self._log_agent(reply or "saved.")
        self._set_status("note saved")
        self._refresh_notes()

    def _add_task(
        self,
        text: str,
        due_date: str | None = None,
        tags: list[str] | None = None,
        reply: str = "",
    ):
        self._ensure_capture_file()
        item = store.add_item(text, date=due_date)
        if item:
            try:
                self.query_one("#todos-panel", TodosPanel).add_todo(item)
            except NoMatches:
                pass
            tag_text = " ".join(f"#{t}" for t in tags or [] if f"#{t}" not in text)
            due_text = f" @due {due_date}" if due_date else ""
            line = f"- [ ] {text}{due_text}" + (f" {tag_text}" if tag_text else "")
            path = store.append_line_to_current_file(line)
            self._log_agent(reply or f"Task captured: {text}")
            self._set_status(f"task: {text[:40]}")
            if path:
                asyncio.create_task(self._parse_note_now(path))
        else:
            # No capture file yet — still show the reply
            self._log_agent(reply or f"Task captured: {text}")
            self._set_status(f"task: {text[:40]}")

    def _add_event(
        self,
        text: str,
        time: str | None = None,
        date: str | None = None,
        tags: list[str] | None = None,
        reply: str = "",
    ):
        self._ensure_capture_file()
        item = store.add_item(text, time=time, date=date)
        if item:
            tag_text = " ".join(f"#{t}" for t in tags or [] if f"#{t}" not in text)
            when = " ".join(p for p in [date, time] if p)
            line = (f"- [{when}] {text}" if when else f"- {text}") + (
                f" {tag_text}" if tag_text else ""
            )
            store.append_line_to_current_file(line)
            self._log_agent(reply or f"Event noted: {text}")
            self._set_status(f"event: {text[:40]}")
        else:
            self._log_agent(reply or f"Event noted: {text}")
            self._set_status(f"event: {text[:40]}")

    # ── nvim ──────────────────────────────────────────────────────────────────

    @work
    async def _open_nvim(
        self, filepath: Path, subdir: str = "pages", is_new: bool = False
    ):
        filepath.parent.mkdir(parents=True, exist_ok=True)
        if is_new and not filepath.exists():
            filepath.write_text(f"# {filepath.stem}\n\n", encoding="utf-8")

        editor = shutil.which("nvim") or shutil.which("vim")
        if not editor:
            self._log_agent("[red]nvim not found in PATH[/red]")
            return

        initial_mtime = filepath.stat().st_mtime if filepath.exists() else 0
        self._set_status(f"nvim: {filepath.name}", duration=0)

        try:
            with self.suspend():
                subprocess.run([editor, str(filepath)])
        except Exception as exc:
            self._log_agent(f"[red]editor error:[/red] {exc}")
            return

        try:
            new_mtime = filepath.stat().st_mtime
        except Exception:
            new_mtime = 0

        if new_mtime > initial_mtime:
            rel = str(filepath.relative_to(store.get_active_folder()))
            store.add_note_file(rel)
            store.set_current_file(rel)
            self._log_agent(f"saved [#7aa2f7]{filepath.name}[/#7aa2f7].")
            self._set_status(f"saved {filepath.name}")
            self._refresh_notes()
        else:
            self._set_status("back")

        self._focus_input()

    def _open_path(self, filepath_str: str):
        try:
            fp = store.find_note_path(filepath_str)
        except ValueError as exc:
            self._log_agent(f"[red]cannot open note:[/red] {exc}")
            return
        self._open_nvim(fp, fp.parent.name or "pages", is_new=False)

    # ── Event handlers ────────────────────────────────────────────────────────

    def on_notes_panel_open_in_nvim(self, event: NotesPanel.OpenInNvim):
        self._open_path(event.filepath)

    def on_notes_panel_file_selected(self, event: NotesPanel.FileSelected):
        self._open_path(event.filepath)

    def on_notes_panel_edit_requested(self, event: NotesPanel.EditRequested):
        self._open_path(event.filepath)

    def on_notes_panel_note_deleted(self, event: NotesPanel.NoteDeleted):
        name = Path(event.filepath).name
        self._log_agent(f"deleted [dim]{name}[/dim].")
        self._set_status(f"deleted {name}")

    def on_agent_panel_note_link_clicked(self, event: AgentPanel.NoteLinkClicked):
        self._open_path(event.filepath)

    def on_sidebar_panel_nav_selected(self, event: SidebarPanel.NavSelected):
        target = event.target
        try:
            np = self.query_one("#notes-panel", NotesPanel)
            if target == "notes":
                np.set_mode("pages")
            elif target == "journals":
                np.set_mode("journals")
            else:
                np.set_mode("hidden")
        except NoMatches:
            pass

    # ── Helpers ───────────────────────────────────────────────────────────────

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

    def _set_status(self, msg: str, duration: float = 3.0):
        try:
            self.query_one("#status-bar", StatusBar).set_message(msg, duration=duration)
        except NoMatches:
            pass

    def _focus_input(self):
        try:
            self.query_one("#chat-input", ChatInput).focus_input()
        except NoMatches:
            pass

    def _refresh_notes(self):
        try:
            self.query_one("#notes-panel", NotesPanel).refresh_notes()
        except NoMatches:
            pass

    async def _watch_file_changes(self):
        """Background worker that monitors file changes and refreshes UI."""
        from src.core.queue import ui_update_queue
        
        while True:
            try:
                # Wait for UI update events after parser ingestion completes
                event = await asyncio.wait_for(ui_update_queue.get(), timeout=1.0)
                
                # Check if it's a markdown file
                if event.path.suffix == ".md":
                    # Refresh todos panel to pick up parsed tasks
                    try:
                        todos = self.query_one("#todos-panel", TodosPanel)
                        todos.refresh_todos()
                    except NoMatches:
                        pass
                    
                    # Refresh notes panel to show updated files
                    self._refresh_notes()
                    
            except asyncio.TimeoutError:
                # No events in the last second, continue waiting
                continue
            except Exception:
                # Continue on any error
                await asyncio.sleep(1)
                continue

    def _refresh_todos(self):
        try:
            self.query_one("#todos-panel", TodosPanel).refresh_todos()
        except NoMatches:
            pass

    async def _parse_note_now(self, path: Path):
        """Fast task/index metadata update for UI; vector embeddings stay async."""
        try:
            from src.ingestion.parser.core import parse_markdown
            from src.ingestion.db.notes import upsert_note
            from src.ingestion.db.blocks import insert_blocks
            from src.ingestion.db.tasks import insert_tasks
            from src.ingestion.db.tags import insert_block_tags

            raw_content = path.read_text(encoding="utf-8")
            note_type = "journal" if "journals" in path.parts else "page"
            title, blocks, tasks, _references, block_tags = parse_markdown(path, raw_content)
            note_id = await upsert_note(path, title, note_type, raw_content, "modified")
            if note_id < 0:
                return

            block_ids = await insert_blocks(note_id, blocks)
            local_to_db = {local_idx: db_id for local_idx, db_id in enumerate(block_ids)}
            for task in tasks:
                task["block_id"] = local_to_db.get(task["block_id"])
            for tag in block_tags:
                tag["block_id"] = local_to_db.get(tag["block_id"])

            await insert_block_tags(block_ids, block_tags)
            await insert_tasks(note_id, tasks)
            self._refresh_todos()
        except Exception as exc:
            self._log_agent(f"[red]quick parse failed:[/red] {exc}")

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_quit(self):
        self.exit()

    def action_focus_input(self):
        self._focus_input()

    def action_escape_back(self):
        """Escape unfocuses current widget, allowing app-level navigation."""
        focused = self.focused
        
        if focused:
            # If something has focus, unfocus it
            if isinstance(focused, ChatInput):
                # From chat input, unfocus to allow navigation
                focused.blur()
                self._set_status("ready — press i for input, hjkl to navigate", 2.0)
            elif isinstance(focused, (NotesPanel, TodosPanel, SidebarPanel)):
                # From a panel, unfocus to allow app navigation
                focused.blur()
                self._set_status("ready — press i for input, hjkl to navigate", 2.0)
            else:
                # From any other widget, unfocus
                focused.blur()
        else:
            # Nothing focused, focus input
            self._focus_input()

    def action_focus_sidebar(self):
        try:
            self.query_one("#sidebar-panel", SidebarPanel).focus()
        except NoMatches:
            pass

    def action_focus_notes(self):
        try:
            self.query_one("#notes-panel", NotesPanel).focus()
        except NoMatches:
            pass

    def action_new_page(self):
        from .widgets.input_dialog import FilenameInputDialog

        def _handle(result: str | None):
            if not result:
                return

            try:
                rel = store.normalize_note_path(result, default_dir="pages")
                rel_path = Path(rel)
                if not rel_path.parts or rel_path.parts[0] != "pages":
                    rel = (Path("pages") / rel_path).as_posix()
                fp = store.get_active_folder() / rel
            except ValueError as exc:
                self._log_agent(f"[red]invalid note path:[/red] {exc}")
                return

            rel_path = Path(rel)
            subdir = rel_path.parts[0] if len(rel_path.parts) > 1 else "pages"

            self._open_nvim(fp, subdir, is_new=True)

        self.push_screen(
            FilenameInputDialog(title="Open or create note", default=""), _handle
        )

    def action_new_journal(self):
        filename = f"journals/{datetime.now().date().isoformat()}.md"
        self._open_nvim(store.get_active_folder() / filename, "journals", is_new=True)

    def action_open_search(self, query: str = ""):
        def _handle(result):
            if result and isinstance(result, dict):
                fp = result.get("filepath", "")
                if fp:
                    self._open_path(fp)

        try:
            self.push_screen(SearchModal(query=query), _handle)
        except Exception:
            pass

    def action_move_left(self):
        """Move focus left (vim-style): notes → sidebar → input."""
        pane = self._focused_pane()
        if pane == "right":
            # From notes, go to sidebar
            try:
                self.query_one("#sidebar-panel", SidebarPanel).focus()
            except NoMatches:
                pass
        elif pane == "sidebar":
            # From sidebar, go to input
            self._focus_input()
        else:
            # From anywhere else, go to sidebar
            try:
                self.query_one("#sidebar-panel", SidebarPanel).focus()
            except NoMatches:
                pass

    def action_move_right(self):
        """Move focus right (vim-style): input/sidebar → notes."""
        pane = self._focused_pane()
        if pane in ("chat", "sidebar"):
            # From input or sidebar, go to notes
            try:
                self.query_one("#notes-panel", NotesPanel).focus()
            except NoMatches:
                pass
        # If already in notes or other panels, stay there

    def action_move_down(self):
        """Move focus down (vim-style)."""
        if self._consume_g_prefix():
            self.action_new_journal()
            return
        # Delegate to focused widget if it has move_down action
        focused = self.focused
        if focused and hasattr(focused, "action_move_down"):
            focused.action_move_down()

    def action_move_up(self):
        """Move focus up (vim-style)."""
        # Delegate to focused widget if it has move_up action
        focused = self.focused
        if focused and hasattr(focused, "action_move_up"):
            focused.action_move_up()

    def action_go_top(self):
        """Go to top of list (vim-style)."""
        if self._consume_g_prefix():
            focused = self.focused
            if focused and hasattr(focused, "action_go_top"):
                focused.action_go_top()
            return
        focused = self.focused
        if focused and hasattr(focused, "action_go_top"):
            focused.action_go_top()
        elif hasattr(focused, "index"):
            focused.index = 0

    def action_go_bottom(self):
        """Go to bottom of list (vim-style)."""
        focused = self.focused
        if focused and hasattr(focused, "action_go_bottom"):
            focused.action_go_bottom()
        elif hasattr(focused, "index") and focused.children:
            focused.index = len(focused.children) - 1

    def action_close_tab(self):
        """Close current tab (vim-style)."""
        # This would be implemented if there are tabs
        pass

    def action_minimize(self):
        """Minimize current panel (vim-style)."""
        # This would hide/show panels
        pass

    def action_toggle_vim_mode(self):
        """Toggle vim mode on/off."""
        # For future implementation
        pass

    def action_open_note(self, filepath: str):
        """Handle note link clicks from the agent panel."""
        self._open_path(filepath)

    def action_g_prefix(self):
        focused = self.focused
        if isinstance(focused, Input):
            return
        if self._consume_g_prefix():
            self.action_go_top()
            return
        self._g_prefix = True
        self.set_timer(1.0, self._clear_g_prefix)
        self._set_status("g…", duration=1.0)

    def action_g_prefix_page(self):
        if self._consume_g_prefix():
            self.action_new_page()

    def action_g_prefix_notes(self):
        if self._consume_g_prefix():
            self.action_focus_notes()

    def action_g_prefix_sidebar(self):
        if self._consume_g_prefix():
            self.action_focus_sidebar()

    def _consume_g_prefix(self) -> bool:
        if not self._g_prefix:
            return False
        self._g_prefix = False
        return True

    def _clear_g_prefix(self):
        self._g_prefix = False

    def _focused_pane(self) -> str:
        node: Widget | None = self.focused
        while node is not None:
            node_id = getattr(node, "id", None)
            if node_id in ("sidebar-panel", "sidebar-col"):
                return "sidebar"
            if node_id in ("agent-panel", "chat-input", "cmd-input", "chat-col"):
                return "chat"
            if node_id in ("notes-panel", "todos-panel", "notes-list", "todos-list", "right-col"):
                return "right"
            node = getattr(node, "parent", None)
        return ""
