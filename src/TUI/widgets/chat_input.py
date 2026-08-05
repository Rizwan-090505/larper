from textual.widget import Widget
from textual.app import ComposeResult
from textual.widgets import Input, Static
from textual.message import Message
from textual.events import Key


class CommandInput(Input):
    def on_key(self, event: Key):
        if self.value:
            return

        if event.key in ("/", "slash"):
            event.stop()
            event.prevent_default()
            self.app.action_open_search()
        elif event.key == "h":
            event.stop()
            event.prevent_default()
            self.app.action_move_left()
        elif event.key == "l":
            event.stop()
            event.prevent_default()
            self.app.action_move_right()
        elif event.key == "escape":
            event.stop()
            event.prevent_default()
            self.blur()
            try:
                self.app._set_status("ready - hjkl navigate, i returns to input", 2.0)
            except Exception:
                pass


class ChatInput(Widget):
    DEFAULT_CSS = """
    ChatInput {
        height: 3;
        background: #1e2030;
        border-top: solid #3b4261;
        padding: 0;
        layout: horizontal;
        align: left middle;
    }
    ChatInput #prompt-label {
        width: 4;
        height: 1;
        color: #e0af68;
        padding: 0 1;
        text-style: bold;
        content-align: left middle;
    }
    ChatInput Input {
        background: transparent;
        border: none;
        height: 1;
        color: #c0caf5;
        padding: 0;
        width: 1fr;
    }
    ChatInput Input:focus {
        border: none;
        background: transparent;
    }
    ChatInput #nav-hint {
        width: auto;
        height: 1;
        color: #3b4261;
        padding: 0 1;
        content-align: right middle;
    }
    """

    class Submitted(Message):
        def __init__(self, value: str):
            super().__init__()
            self.value = value

    def compose(self) -> ComposeResult:
        yield Static("›", id="prompt-label")
        yield CommandInput(placeholder="ask, note, or: add task / journal <text>", id="cmd-input")
        yield Static("[dim #3b4261]esc=leave  i=back[/dim #3b4261]", id="nav-hint")

    def on_mount(self):
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted):
        value = event.value.strip()
        if value:
            self.post_message(self.Submitted(value))
            event.input.value = ""
            event.input.focus()

    def focus_input(self):
        self.query_one(Input).focus()
