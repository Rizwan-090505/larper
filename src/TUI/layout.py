from textual.widget import Widget
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from .widgets.agent_panel import AgentPanel
from .widgets.chat_input import ChatInput
from .widgets.sidebar import SidebarPanel
from .widgets.notes import NotesPanel
from .widgets.todos import TodosPanel


class MainLayout(Widget):
    """
    Single-screen layout:
      [ sidebar 18% ] [ agent chat 57% ] [ notes+todos 25% ]
    No preview. nvim takes over the full terminal via suspend().
    """

    DEFAULT_CSS = """
    MainLayout {
        layout: horizontal;
        height: 1fr;
        background: transparent;
    }
    MainLayout #sidebar-col {
        width: 18;
        layout: vertical;
        height: 1fr;
        background: transparent;
        border-right: tall $foreground 20%;
    }
    MainLayout #chat-col {
        width: 1fr;
        layout: vertical;
        height: 1fr;
        background: transparent;
    }
    MainLayout #right-col {
        width: 28;
        layout: vertical;
        height: 1fr;
        background: transparent;
        border-left: tall $foreground 20%;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="sidebar-col"):
            yield SidebarPanel(id="sidebar-panel")
        with Vertical(id="chat-col"):
            yield AgentPanel(id="agent-panel")
            yield ChatInput(id="chat-input")
        with Vertical(id="right-col"):
            yield NotesPanel(id="notes-panel")
            yield TodosPanel(id="todos-panel")
