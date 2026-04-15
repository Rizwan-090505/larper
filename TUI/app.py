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


class DevWorkspaceApp(App):
    CSS_PATH = "styles/app.css"
    TITLE = "DevWorkspace"
    BINDINGS = [
        ("ctrl+q", "quit", "Quit"),
        ("ctrl+d", "toggle_mode", "Toggle Vim Mode"),
        ("ctrl+f", "focus_input", "Focus Input"),
    ]

    def __init__(self):
        super().__init__()
        self._vim_mode = False

    def compose(self) -> ComposeResult:
        yield Static("  ⚡ DevWorkspace", id="app-header")
        yield DefaultLayout(id="default-layout")
        yield StatusBar(id="status-bar")

    def on_mount(self):
        # Pre-load some demo notes
        store.add_note_file("README.md")
        store.add_note_file("notes.md")
        store.add_note_file("todo.md")
        self._focus_input()

    # ─── Input Handling ──────────────────────────────────────────────────────

    def on_chat_input_submitted(self, event: ChatInput.Submitted):
        self._handle_command(event.value)

    def _handle_command(self, raw: str):
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
            self._show_error("Invalid command. Use: add task <text>  |  add event <text> at HH:MM")

        self._focus_input()

    def _add_task(self, text: str):
        if not store.get_current_file():
            self._show_error("No file open. Click a note to open it first.")
            return
        item = store.add_item(text)
        if item:
            self._update_todos_panel(item)
            self._update_vim_panel(f"[ ] {text}")
            self._log(f"[green]✓ Task added:[/green] {text}")
            self._set_status(f"Task added: {text}")

    def _add_event(self, text: str, time: str):
        if not store.get_current_file():
            self._show_error("No file open. Click a note to open it first.")
            return
        item = store.add_item(text, time=time)
        if item:
            self._update_events_panel(item)
            self._update_vim_panel(f"[{time}] {text}")
            self._log(f"[yellow]◷ Event added:[/yellow] {text} at {time}")
            self._set_status(f"Event added: {text} at {time}")

    def _show_error(self, msg: str):
        self._log(f"[red]✗ {msg}[/red]")
        self._set_status(msg)

    # ─── Panel Updates ───────────────────────────────────────────────────────

    def _update_todos_panel(self, item):
        try:
            panel = self.query_one("#todos-panel", TodosPanel)
            panel.add_todo(item)
        except NoMatches:
            pass

    def _update_events_panel(self, item):
        try:
            panel = self.query_one("#events-panel", EventsPanel)
            panel.add_event(item)
        except NoMatches:
            pass

    def _update_vim_panel(self, line: str):
        try:
            vim = self.query_one("#vim-panel", VimPanel)
            vim.append_line(line)
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

    # ─── Notes Panel ─────────────────────────────────────────────────────────

    def on_notes_panel_file_selected(self, event: NotesPanel.FileSelected):
        self._open_file(event.filename)

    def _open_file(self, filename: str):
        store.set_current_file(filename)
        if not self._vim_mode:
            self._switch_to_vim_mode()
        else:
            try:
                vim = self.query_one("#vim-panel", VimPanel)
                vim.load_file(filename)
                tabs = self.query_one("#tab-bar", TabBar)
                tabs.open_file(filename)
            except NoMatches:
                pass

        try:
            todos = self.query_one("#todos-panel", TodosPanel)
            todos.refresh_todos()
            events = self.query_one("#events-panel", EventsPanel)
            events.refresh_events()
        except NoMatches:
            pass

        try:
            sb = self.query_one("#status-bar", StatusBar)
            sb.current_file = filename
        except NoMatches:
            pass

        self._log(f"[cyan]📄 Opened:[/cyan] {filename}")
        self._focus_input()

    # ─── Layout Switching ────────────────────────────────────────────────────

    def _switch_to_vim_mode(self):
        self._vim_mode = True
        try:
            dl = self.query_one("#default-layout", DefaultLayout)
            dl.remove()
        except NoMatches:
            pass

        vim_layout = VimLayout(id="vim-layout")
        self.mount(vim_layout, before="#status-bar")

        async def post_mount():
            await asyncio.sleep(0.05)
            if store.get_current_file():
                try:
                    vim = self.query_one("#vim-panel", VimPanel)
                    vim.load_file(store.get_current_file())
                    tabs = self.query_one("#tab-bar", TabBar)
                    tabs.open_file(store.get_current_file())
                    todos = self.query_one("#todos-panel", TodosPanel)
                    todos.refresh_todos()
                    events = self.query_one("#events-panel", EventsPanel)
                    events.refresh_events()
                    notes = self.query_one("#notes-panel", NotesPanel)
                    notes.refresh_notes()
                except NoMatches:
                    pass
            self._focus_input()

        asyncio.get_event_loop().create_task(post_mount())

    def _switch_to_default_mode(self):
        self._vim_mode = False
        try:
            vl = self.query_one("#vim-layout", VimLayout)
            vl.remove()
        except NoMatches:
            pass

        dl = DefaultLayout(id="default-layout")
        self.mount(dl, before="#status-bar")

        async def post_mount():
            await asyncio.sleep(0.05)
            try:
                notes = self.query_one("#notes-panel", NotesPanel)
                notes.refresh_notes()
                todos = self.query_one("#todos-panel", TodosPanel)
                todos.refresh_todos()
                events = self.query_one("#events-panel", EventsPanel)
                events.refresh_events()
            except NoMatches:
                pass
            self._focus_input()

        asyncio.get_event_loop().create_task(post_mount())

    # ─── Actions ─────────────────────────────────────────────────────────────

    def action_toggle_mode(self):
        if self._vim_mode:
            self._switch_to_default_mode()
        else:
            self._switch_to_vim_mode()

    def action_focus_input(self):
        self._focus_input()

    def action_quit(self):
        self.exit()