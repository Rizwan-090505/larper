from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.widgets import Static, Input, Button, Label
from textual.message import Message
from textual.screen import ModalScreen


class FilenameInputDialog(ModalScreen):
    """Modal dialog to input a filename."""
    
    DEFAULT_CSS = """
    FilenameInputDialog {
        align: center middle;
    }
    
    FilenameInputDialog > Vertical {
        width: 60;
        height: 11;
        border: solid $accent;
        background: $surface;
        padding: 1;
    }
    
    FilenameInputDialog .dialog-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    
    FilenameInputDialog .dialog-label {
        color: $text;
        margin-bottom: 0;
    }
    
    FilenameInputDialog Input {
        margin-bottom: 1;
        width: 100%;
    }
    
    FilenameInputDialog .buttons {
        height: 1;
        width: 100%;
        layout: horizontal;
        margin-top: 1;
    }
    
    FilenameInputDialog Button {
        margin-right: 1;
    }
    """
    
    class Submitted(Message):
        def __init__(self, filename: str):
            super().__init__()
            self.filename = filename

    class Cancelled(Message):
        pass

    def __init__(self, title: str = "Enter filename", default: str = "", **kwargs):
        super().__init__(**kwargs)
        self.title_text = title
        self.default_value = default

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self.title_text, classes="dialog-title")
            yield Label("(include .md extension)", classes="dialog-label")
            yield Input(value=self.default_value, id="filename-input")
            with Horizontal(classes="buttons"):
                yield Button("Save", id="btn-save", variant="primary")
                yield Button("Cancel", id="btn-cancel")

    def on_mount(self):
        self.query_one("#filename-input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-save":
            filename = self.query_one("#filename-input", Input).value.strip()
            if filename:
                self.post_message(self.Submitted(filename))
                self.app.pop_screen()
            else:
                self.query_one("#filename-input", Input).focus()
        elif event.button.id == "btn-cancel":
            self.post_message(self.Cancelled())
            self.app.pop_screen()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        filename = event.value.strip()
        if filename:
            self.post_message(self.Submitted(filename))
            self.app.pop_screen()
