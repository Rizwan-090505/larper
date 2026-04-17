from textual.widget import Widget
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from widgets.agent_panel import AgentPanel
from widgets.chat_input import ChatInput
from widgets.todos import TodosPanel
from widgets.events import EventsPanel
from widgets.notes import NotesPanel
from widgets.vim import VimPanel
from widgets.tabs import TabBar


class DefaultLayout(Widget):
    DEFAULT_CSS = """
    DefaultLayout {
        layout: horizontal;
        height: 1fr;
    }
    DefaultLayout #main-col {
        width: 70%;
        layout: vertical;
        height: 1fr;
    }
    DefaultLayout #dash-col {
        width: 30%;
        layout: vertical;
        height: 1fr;
        border-left: solid $primary;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="main-col"):
            yield AgentPanel(id="agent-panel")
            yield ChatInput(id="chat-input")
        with Vertical(id="dash-col"):
            yield TodosPanel(id="todos-panel")
            yield EventsPanel(id="events-panel")
            yield NotesPanel(id="notes-panel")


class VimLayout(Widget):
    DEFAULT_CSS = """
    VimLayout {
        layout: vertical;
        height: 1fr;
    }
    VimLayout #vim-row {
        layout: horizontal;
        height: 1fr;
    }
    VimLayout #vim-col {
        width: 50%;
        layout: vertical;
        height: 1fr;
    }
    VimLayout #main-col {
        width: 25%;
        layout: vertical;
        height: 1fr;
        border-left: solid $primary;
    }
    VimLayout #dash-col {
        width: 25%;
        layout: vertical;
        height: 1fr;
        border-left: solid $primary;
    }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="vim-row"):
            with Vertical(id="vim-col"):
                yield VimPanel(id="vim-panel")
                yield ChatInput(id="chat-input")
            with Vertical(id="main-col"):
                yield AgentPanel(id="agent-panel")
            with Vertical(id="dash-col"):
                yield TodosPanel(id="todos-panel")
                yield EventsPanel(id="events-panel")
                yield NotesPanel(id="notes-panel")
        yield TabBar(id="tab-bar")