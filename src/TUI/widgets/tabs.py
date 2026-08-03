from textual.widget import Widget
from textual.app import ComposeResult
from textual.widgets import Static
from textual.reactive import reactive


class TabBar(Widget):
    can_focus = True

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
    TabBar .tab.minimized {
        color: $text-muted;
        text-style: italic;
    }
    """

    active_file: reactive[str] = reactive("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._open_files: list[str] = []
        self._minimized_files: set[str] = set()

    def compose(self) -> ComposeResult:
        yield Static("  No tabs", id="tab-placeholder", classes="tab")

    @property
    def open_files(self) -> list[str]:
        return list(self._open_files)

    def open_file(self, filename: str):
        if filename not in self._open_files:
            self._open_files.append(filename)
        self._minimized_files.discard(filename)
        self.active_file = filename
        self._render_tabs()

    def next_file(self) -> str | None:
        return self._move(1)

    def previous_file(self) -> str | None:
        return self._move(-1)

    def close_active(self) -> str | None:
        if not self.active_file:
            return None
        try:
            idx = self._open_files.index(self.active_file)
        except ValueError:
            return None

        closed = self._open_files.pop(idx)
        self._minimized_files.discard(closed)

        visible = self._visible_files()
        if visible:
            self.active_file = visible[min(idx, len(visible) - 1)]
        elif self._open_files:
            self.active_file = self._open_files[min(idx, len(self._open_files) - 1)]
        else:
            self.active_file = ""
        self._render_tabs()
        return self.active_file or None

    def toggle_minimize_active(self) -> str | None:
        if not self.active_file:
            return None
        current = self.active_file
        if current in self._minimized_files:
            self._minimized_files.remove(current)
            self._render_tabs()
            return current

        self._minimized_files.add(current)
        visible = self._visible_files()
        self.active_file = visible[0] if visible else ""
        self._render_tabs()
        return self.active_file or None

    def restore_last_minimized(self) -> str | None:
        if not self._minimized_files:
            return None
        for filename in reversed(self._open_files):
            if filename in self._minimized_files:
                self._minimized_files.remove(filename)
                self.active_file = filename
                self._render_tabs()
                return filename
        return None

    def _move(self, step: int) -> str | None:
        visible = self._visible_files()
        if not visible:
            return None
        if self.active_file not in visible:
            self.active_file = visible[0]
        else:
            idx = visible.index(self.active_file)
            self.active_file = visible[(idx + step) % len(visible)]
        self._render_tabs()
        return self.active_file

    def _visible_files(self) -> list[str]:
        return [filename for filename in self._open_files if filename not in self._minimized_files]

    def _render_tabs(self):
        # Remove all existing tab statics
        for child in self.query(".tab"):
            child.remove()

        if not self._open_files:
            self.mount(Static("  No tabs", classes="tab"))
            return

        for fname in self._open_files:
            is_active = fname == self.active_file
            is_minimized = fname in self._minimized_files
            classes = ["tab"]
            if is_active:
                classes.append("active")
            if is_minimized:
                classes.append("minimized")
            prefix = "● " if is_active else ("▣ " if is_minimized else "○ ")
            suffix = " -" if is_minimized else " x"
            self.mount(Static(f" {prefix}{fname}{suffix} ", classes=" ".join(classes)))
