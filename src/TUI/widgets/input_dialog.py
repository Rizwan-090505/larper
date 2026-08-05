from __future__ import annotations

import asyncio
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static, Input, Label, ListView, ListItem
from textual.message import Message
from textual.screen import ModalScreen
from textual.binding import Binding


class NotePickerItem(ListItem):
    """A row in the existing-notes list."""

    DEFAULT_CSS = """
    NotePickerItem {
        padding: 0 1;
        height: 1;
        background: transparent;
        color: #565f89;
    }
    NotePickerItem:hover { background: #292e42; color: #c0caf5; }
    NotePickerItem.-highlight { background: #292e42; color: #7aa2f7; }
    """

    def __init__(self, filepath: str, display: str):
        super().__init__()
        self._filepath = filepath
        self._display = display

    def compose(self) -> ComposeResult:
        yield Label(f" □ {self._display}")

    @property
    def filepath(self) -> str:
        return self._filepath

    @property
    def display(self) -> str:
        return self._display


class FilenameInputDialog(ModalScreen):
    """
    Modal dialog for naming a new note.
    Shows existing notes filtered as you type.
    Clicking an existing note opens it instead of creating a new file.
    """

    DEFAULT_CSS = """
    FilenameInputDialog {
        align: center middle;
    }

    FilenameInputDialog > Vertical {
        width: 64;
        height: 28;
        border: solid #7aa2f7;
        background: #1e2030;
        padding: 1 2;
        layout: vertical;
    }

    FilenameInputDialog .dialog-title {
        text-style: bold;
        color: #7aa2f7;
        height: 1;
        margin-bottom: 1;
    }

    FilenameInputDialog .dialog-hint {
        color: #565f89;
        height: 1;
        margin-bottom: 0;
    }

    FilenameInputDialog Input {
        background: #292e42;
        border: none;
        color: #c0caf5;
        height: 1;
        padding: 0 1;
        width: 100%;
        margin-bottom: 1;
    }

    FilenameInputDialog Input:focus {
        border: none;
        background: #2f3549;
    }

    FilenameInputDialog .section-label {
        color: #3b4261;
        height: 1;
        text-style: italic;
        margin-bottom: 0;
    }

    FilenameInputDialog ListView {
        background: transparent;
        border: none;
        height: 1fr;
    }

    FilenameInputDialog .empty-hint {
        color: #3b4261;
        height: 1;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("enter",  "confirm", "Open/Create", show=False),
    ]

    def __init__(self, title: str = "Open or create note", default: str = "", **kwargs):
        super().__init__(**kwargs)
        self.title_text = title
        self.default_value = default
        self._all_notes: list[tuple[str, str]] = []  # [(filepath, display_name), …]

    # ── Compose ───────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self.title_text, classes="dialog-title")
            yield Label(
                "Type to filter existing notes — press Enter to open or create",
                classes="dialog-hint",
            )
            yield Input(
                value=self.default_value,
                placeholder="note name (without .md)…",
                id="filename-input",
            )
            yield Label("  existing notes", classes="section-label")
            yield ListView(id="notes-picker")

    def on_mount(self):
        self.query_one("#filename-input", Input).focus()
        asyncio.create_task(self._load_notes())

    # ── Note loading ──────────────────────────────────────────────────────────

    async def _load_notes(self):
        try:
            try:
                from ..state.store import store
            except ImportError:
                from state.store import store

            folder = store.get_active_folder()
            rows: list[tuple[float, str, str]] = []
            for fp in folder.rglob("*.md"):
                try:
                    rel = fp.relative_to(folder)
                except ValueError:
                    continue
                if any(part.startswith(".") for part in rel.parts):
                    continue
                rows.append((fp.stat().st_mtime, rel.as_posix(), rel.as_posix()))
            rows.sort(key=lambda x: x[0], reverse=True)
            self._all_notes = [(fpath, fname) for _, fpath, fname in rows]
        except Exception:
            self._all_notes = []

        self._render_list(self._all_notes)

    def _render_list(self, notes: list[tuple[str, str]]):
        lv = self.query_one("#notes-picker", ListView)
        lv.clear()
        for filepath, display in notes:
            lv.append(NotePickerItem(filepath, display.replace(".md", "")))

    # ── Events ────────────────────────────────────────────────────────────────

    def on_input_changed(self, event: Input.Changed):
        if event.input.id != "filename-input":
            return
        q = event.value.strip().lower()
        if not q:
            self._render_list(self._all_notes)
            return
        filtered = [
            (fp, disp)
            for fp, disp in self._all_notes
            if q in disp.lower() or q in fp.lower()
        ]
        self._render_list(filtered)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter in the text box: open highlighted note or create new one."""
        lv = self.query_one("#notes-picker", ListView)
        if lv.highlighted_child and isinstance(lv.highlighted_child, NotePickerItem):
            self.dismiss(lv.highlighted_child.filepath)
        else:
            filename = event.value.strip()
            if filename:
                if not filename.endswith(".md"):
                    filename += ".md"
                self.dismiss(filename)

    def on_list_view_selected(self, event: ListView.Selected):
        """Clicking (or pressing Enter on) a list item opens that existing note."""
        if isinstance(event.item, NotePickerItem):
            self.dismiss(event.item.filepath)

    def action_confirm(self):
        """Enter pressed from outside the input — open highlighted or create."""
        lv = self.query_one("#notes-picker", ListView)
        if lv.highlighted_child and isinstance(lv.highlighted_child, NotePickerItem):
            self.dismiss(lv.highlighted_child.filepath)
        else:
            filename = self.query_one("#filename-input", Input).value.strip()
            if filename:
                if not filename.endswith(".md"):
                    filename += ".md"
                self.dismiss(filename)

    def action_cancel(self):
        self.dismiss(None)
