from __future__ import annotations

from textual.widget import Widget
from textual.app import ComposeResult
from textual.widgets import Static
from textual.message import Message
from textual.binding import Binding


# Ordered list of navigable nav items: (id-suffix, label-text)
_NAV_ITEMS: list[tuple[str, str]] = [
    ("home",     " △  Home"),
    ("tasks",    " ✓  Tasks"),
    ("notes",    " ≡  Notes"),
    ("journals", " ◆  Journals"),
    ("archive",  " □  Archive"),
    ("tags",     " #  Tags"),
]


class SidebarPanel(Widget):
    """
    Sidebar with keyboard-navigable nav items.

    j / k    → move selection up/down
    Enter    → activate selected item (posts NavSelected)
    click    → activate clicked item
    """

    can_focus = True

    DEFAULT_CSS = """
    SidebarPanel {
        height: 1fr;
        background: #1e2030;
        padding: 1 0;
        layout: vertical;
    }
    SidebarPanel .logo {
        color: #e0af68;
        text-style: bold;
        padding: 0 2;
        height: 2;
    }
    SidebarPanel .divider {
        color: #3b4261;
        height: 1;
        padding: 0 1;
    }
    SidebarPanel .nav-item {
        padding: 0 2;
        height: 1;
        color: #565f89;
    }
    SidebarPanel .nav-item:hover {
        color: #c0caf5;
        background: #292e42;
    }
    SidebarPanel .nav-item.active {
        color: #7aa2f7;
        text-style: bold;
        background: #292e42;
    }
    SidebarPanel .nav-item.focused-cursor {
        color: #c0caf5;
        background: #2f3549;
    }
    SidebarPanel .nav-item.active.focused-cursor {
        color: #7aa2f7;
        background: #2f3549;
        text-style: bold;
    }
    SidebarPanel .nav-label {
        color: #3b4261;
        padding: 1 2 0 2;
        height: 2;
        text-style: italic;
    }
    SidebarPanel .hint {
        color: #3b4261;
        padding: 0 2;
        height: 1;
    }
    """

    BINDINGS = [
        Binding("j", "move_down", "Down",  show=False),
        Binding("k", "move_up",   "Up",    show=False),
        Binding("enter", "select", "Select", show=False),
    ]

    class NavSelected(Message):
        def __init__(self, target: str):
            super().__init__()
            self.target = target

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Index into _NAV_ITEMS for the keyboard cursor (-1 = no cursor yet)
        self._cursor: int = -1
        # Index of the *activated* item (highlighted in blue)
        self._active: int = 0  # default: Home

    # ── Compose ───────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Static("  ◈ LARPer", classes="logo")
        yield Static("─" * 16, classes="divider")
        yield Static("", classes="hint")
        for suffix, label in _NAV_ITEMS:
            yield Static(label, classes="nav-item", id=f"nav-{suffix}")
        yield Static("", classes="hint")
        yield Static("─" * 16, classes="divider")
        yield Static("", classes="nav-label")
        yield Static(" gp  new page",    classes="hint")
        yield Static(" gj  new journal", classes="hint")
        yield Static(" /   search",      classes="hint")
        yield Static(" q   quit",        classes="hint")

    def on_mount(self):
        # Apply initial active highlight to Home
        self._apply_styles()

    # ── Keyboard ──────────────────────────────────────────────────────────────

    def on_focus(self):
        """When the sidebar gains focus, place cursor on the active item."""
        if self._cursor == -1:
            self._cursor = self._active
        self._apply_styles()

    def on_blur(self):
        """Remove the keyboard cursor indicator when focus leaves."""
        self._apply_styles()

    def action_move_down(self):
        if self._cursor == -1:
            self._cursor = self._active
        self._cursor = min(len(_NAV_ITEMS) - 1, self._cursor + 1)
        self._apply_styles()

    def action_move_up(self):
        if self._cursor == -1:
            self._cursor = self._active
        self._cursor = max(0, self._cursor - 1)
        self._apply_styles()

    def action_select(self):
        idx = self._cursor if self._cursor != -1 else self._active
        self._activate(idx)

    # ── Mouse ─────────────────────────────────────────────────────────────────

    def on_static_click(self, event: Static.Clicked) -> None:
        widget_id = event.widget.id or ""
        if widget_id.startswith("nav-"):
            suffix = widget_id[4:]
            idx = next(
                (i for i, (s, _) in enumerate(_NAV_ITEMS) if s == suffix),
                None,
            )
            if idx is not None:
                self._cursor = idx
                self._activate(idx)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _activate(self, idx: int):
        """Mark idx as the active item and post NavSelected."""
        self._active = idx
        self._apply_styles()
        suffix = _NAV_ITEMS[idx][0]
        self.post_message(self.NavSelected(suffix))

    def _apply_styles(self):
        """Refresh CSS classes on all nav items to reflect current state."""
        focused = self.has_focus
        for i, (suffix, _) in enumerate(_NAV_ITEMS):
            try:
                widget = self.query_one(f"#nav-{suffix}", Static)
            except Exception:
                continue

            widget.remove_class("active", "focused-cursor")

            if i == self._active:
                widget.add_class("active")
            if focused and i == self._cursor:
                widget.add_class("focused-cursor")
