from textual.widget import Widget
from textual.reactive import reactive
from textual.app import ComposeResult
from textual.widgets import Static
from datetime import datetime
import asyncio


class StatusBar(Widget):
    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        background: $accent;
        color: $text;
        padding: 0 1;
        dock: bottom;
    }
    StatusBar Static {
        background: transparent;
        color: $text;
        width: 1fr;
    }
    """

    message: reactive[str] = reactive("Ready")
    current_file: reactive[str] = reactive("No file open")

    def compose(self) -> ComposeResult:
        yield Static(id="status-left")
        yield Static(id="status-right")

    def on_mount(self):
        self.update_display()
        self.set_interval(1, self.tick)

    def tick(self):
        self.update_display()

    def update_display(self):
        now = datetime.now().strftime("%H:%M:%S")
        left = self.query_one("#status-left", Static)
        right = self.query_one("#status-right", Static)
        left.update(f" ⚡ DevWorkspace  |  {self.message}  |  File: {self.current_file}")
        right.update(f"{now} ")

    def set_message(self, msg: str, duration: float = 3.0):
        self.message = msg
        self.update_display()
        if duration > 0:
            asyncio.get_event_loop().call_later(duration, self._clear_message)

    def _clear_message(self):
        self.message = "Ready"
        self.update_display()