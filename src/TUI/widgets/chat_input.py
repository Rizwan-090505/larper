from textual.widget import Widget
from textual.app import ComposeResult
from textual.widgets import TextArea, Static
from textual.message import Message
from textual.events import Key


class CommandInput(TextArea):
    """A soft-wrapping, auto-growing input for the chat bar.

    Behaves like a single-line Input (Enter submits, empty-field vim-nav
    shortcuts still work) but wraps long text onto the next line instead of
    scrolling horizontally. Once the text grows past `max-height` (set in
    CSS), the widget scrolls internally like any other TextArea.
    """

    def __init__(self, placeholder: str = "", **kwargs):
        super().__init__(
            "",
            soft_wrap=True,
            show_line_numbers=False,
            tab_behavior="focus",
            placeholder=placeholder,
            **kwargs,
        )

    async def _on_key(self, event: Key) -> None:
        # Enter submits (no newline insertion) — mirrors the old Input widget.
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            value = self.text.strip()
            if value:
                self.post_message(ChatInput.Submitted(value))
                self.text = ""
            return

        # Vim-style nav shortcuts, only when the box is empty — matches the
        # previous CommandInput behavior on the single-line Input.
        if not self.text:
            if event.key in ("/", "slash"):
                event.stop()
                event.prevent_default()
                self.app.action_open_search()
                return
            elif event.key == "h":
                event.stop()
                event.prevent_default()
                self.app.action_move_left()
                return
            elif event.key == "l":
                event.stop()
                event.prevent_default()
                self.app.action_move_right()
                return
            elif event.key == "escape":
                event.stop()
                event.prevent_default()
                self.blur()
                try:
                    self.app._set_status(
                        "ready - hjkl navigate, i returns to input", 2.0
                    )
                except Exception:
                    pass
                return

        await super()._on_key(event)


class ChatInput(Widget):
    DEFAULT_CSS = """
    ChatInput {
        height: auto;
        max-height: 8;
        background: #1e2030;
        border-top: solid #3b4261;
        padding: 0;
        layout: horizontal;
        align: left top;
    }
    ChatInput #prompt-label {
        width: 4;
        height: 3;
        color: #e0af68;
        padding: 1 1 0 1;
        text-style: bold;
        content-align: left top;
    }
    ChatInput TextArea {
        background: transparent;
        border: none;
        height: auto;
        max-height: 8;
        min-height: 3;
        color: #c0caf5;
        padding: 1 0;
        width: 1fr;
        scrollbar-color: #3b4261;
        scrollbar-size: 1 1;
    }
    ChatInput TextArea:focus {
        border: none;
        background: transparent;
    }
    ChatInput #nav-hint {
        width: auto;
        height: 3;
        color: #3b4261;
        padding: 1 1 0 1;
        content-align: right top;
    }
    """

    class Submitted(Message):
        def __init__(self, value: str):
            super().__init__()
            self.value = value

    def compose(self) -> ComposeResult:
        yield Static("›", id="prompt-label")
        yield CommandInput(
            placeholder="ask, note, or: add task / journal <text>", id="cmd-input"
        )
        yield Static("[dim #3b4261]esc=leave  i=back[/dim #3b4261]", id="nav-hint")

    def on_mount(self):
        self.query_one(CommandInput).focus()

    def focus_input(self):
        self.query_one(CommandInput).focus()
