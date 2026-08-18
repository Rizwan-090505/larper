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
        background: transparent;
        color: $text-muted;
        padding: 0 1;
        dock: bottom;
        border-top: tall $foreground 20%;
        layout: horizontal;
    }
    StatusBar .status-left {
        background: transparent;
        color: $text-muted;
        width: 1fr;
        height: 1;
    }
    StatusBar .status-right {
        background: transparent;
        color: $text-muted;
        text-style: dim;
        width: auto;
        height: 1;
    }
    """

    message: reactive[str] = reactive("ready")
    current_file: reactive[str] = reactive("")

    def compose(self) -> ComposeResult:
        yield Static(id="status-left", classes="status-left")
        yield Static(id="status-right", classes="status-right")

    def on_mount(self):
        self.update_display()
        self.set_interval(1, self.tick)

    def tick(self):
        self.update_display()

    def update_display(self):
        now = datetime.now().strftime("%H:%M")
        left = self.query_one("#status-left", Static)
        right = self.query_one("#status-right", Static)
        file_part = f"  {self.current_file}" if self.current_file else ""
        left.update(f" {self.message}{file_part}")
        right.update(f"{now} ")

    def set_message(self, msg: str, duration: float = 3.0):
        self.message = msg
        self.update_display()
        if duration > 0:
            asyncio.get_event_loop().call_later(duration, self._clear_message)

    def _clear_message(self):
        self.message = "ready"
        self.update_display()
