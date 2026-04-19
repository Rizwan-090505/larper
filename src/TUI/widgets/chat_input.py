from textual.widget import Widget
from textual.app import ComposeResult
from textual.widgets import Input
from textual.message import Message


class ChatInput(Widget):
    DEFAULT_CSS = """
    ChatInput {
        height: 3;
        border: solid $accent;
        background: $surface;
        padding: 0 1;
    }
    ChatInput Input {
        background: transparent;
        border: none;
        height: 1;
        color: $text;
        padding: 0;
    }
    ChatInput Input:focus {
        border: none;
        background: transparent;
    }
    """

    class Submitted(Message):
        def __init__(self, value: str):
            super().__init__()
            self.value = value

    def compose(self) -> ComposeResult:
        yield Input(
            placeholder="  Type a note, question, or: add task / add event <text> at HH:MM",
            id="cmd-input"
        )

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