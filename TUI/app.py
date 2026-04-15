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
        ("f1", "toggle_mode", "Toggle Vim Mode"),
        ("f2", "focus_input", "Focus Input"),
        ("f10", "quit", "Quit"),
    ]

    def __init__(self):
        super().__init__()
        self._vim_mode = False

    def compose(self) -> ComposeResult:
        yield Static(
            "  ⚡ DevWorkspace    [dim]F1[/dim] Toggle Vim   [dim]F2[/dim] Focus Input   [dim]F10[/dim] Quit",
            id="app-header"
        )
        yield DefaultLayout(id="default-layout")
        yield StatusBar(id="status-bar")

    def on_mount(self):
        store.add_note_file("README.md")
        store.add_note_file("notes.md")
        store.add_note_file("todo.md")
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

    # ─── File Open ────────────────────────────────────────────────────────────

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
                self.query_one("#todos-panel", TodosPanel).refresh_todos()
                self.query_one("#events-panel", EventsPanel).refresh_events()
            except NoMatches:
                pass

        try:
            sb = self.query_one("#status-bar", StatusBar)
            sb.current_file = filename
            sb.set_message(f"Opened {filename}")
        except NoMatches:
            pass

        self._log_agent(f"[cyan]📄 Opened:[/cyan] [bold]{filename}[/bold]  — start typing to add notes.")
        self._focus_input()

    # ─── Layout Switch with Animations ───────────────────────────────────────

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
                try:
                    vim = self.query_one("#vim-panel", VimPanel)
                    vim.styles.opacity = 0.0
                    vim.load_file(store.get_current_file())
                    vim.styles.animate("opacity", value=1.0, duration=0.28)

                    tabs = self.query_one("#tab-bar", TabBar)
                    tabs.open_file(store.get_current_file())

                    await asyncio.sleep(0.06)

                    for panel_id, cls in [
                        ("#todos-panel", TodosPanel),
                        ("#events-panel", EventsPanel),
                        ("#notes-panel", NotesPanel),
                    ]:
                        try:
                            w = self.query_one(panel_id, cls)
                            w.styles.opacity = 0.0
                            if hasattr(w, "refresh_todos"):
                                w.refresh_todos()
                            elif hasattr(w, "refresh_events"):
                                w.refresh_events()
                            elif hasattr(w, "refresh_notes"):
                                w.refresh_notes()
                            w.styles.animate("opacity", value=1.0, duration=0.25)
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

        asyncio.get_event_loop().create_task(do_switch())

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