from textual.widget import Widget
from textual.app import ComposeResult
from textual.widgets import Static
from textual.reactive import reactive
from textual.message import Message


class TabBar(Widget):
    DEFAULT_CSS = """
    TabBar {
        height: 1;
        background: $surface;
        border-top: solid $primary;
        layout: horizontal;
        overflow-x: auto;
        padding: 0 1;
    }
    TabBar .tab {
        padding: 0 2;
        height: 1;
        background: $surface;
        color: $text-muted;
    }
    TabBar .tab.active {
        background: $accent;
        color: $text;
        text-style: bold;
    }
    """

    active_file: reactive[str] = reactive("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._open_files: list[str] = []

    def compose(self) -> ComposeResult:
        yield Static("  No files open", id="tab-placeholder", classes="tab")

    def open_file(self, filename: str):
        if filename not in self._open_files:
            self._open_files.append(filename)
        self.active_file = filename
        self._render_tabs()

    def _render_tabs(self):
        # Remove all existing tab statics
        for child in self.query(".tab"):
            child.remove()

        if not self._open_files:
            self.mount(Static("  No files open", classes="tab"))
            return

        for fname in self._open_files:
            is_active = fname == self.active_file
            css_class = "tab active" if is_active else "tab"
            prefix = "● " if is_active else "○ "
            self.mount(Static(f" {prefix}{fname} ", classes=css_class))