from __future__ import annotations

import asyncio
import os
from pathlib import Path

from textual.widget import Widget
from textual.app import ComposeResult
from textual.widgets import Static, ListView, ListItem, Label, Input
from textual.message import Message
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.containers import Vertical

# Import store based on how the module is being imported
try:
    from ..state.store import store
except ImportError:
    from state.store import store


class ConfirmDelete(ModalScreen):
    """Tiny modal: press y to confirm delete, any other key to cancel."""
    can_focus = True

    DEFAULT_CSS = """
    ConfirmDelete {
        align: center middle;
        background: #000000 60%;
    }
    #confirm-box {
        width: 60;
        height: 9;
        border: solid #f7768e;
        background: #1e2030;
        padding: 1 2;
        layout: vertical;
    }
    #confirm-box Static {
        height: 1;
        color: #c0caf5;
    }
    #confirm-title {
        color: #f7768e;
        text-style: bold;
    }
    #confirm-question {
        color: #c0caf5;
    }
    #confirm-hint-yes,
    #confirm-hint-no {
        color: #565f89;
    }
    """

    BINDINGS = [
        Binding("y", "confirm", "Yes", priority=True),
        Binding("n", "cancel", "No", priority=True),
        Binding("escape", "cancel", "Cancel", priority=True),
    ]

    def __init__(self, filename: str):
        super().__init__()
        self._filename = filename

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Static("Delete note", id="confirm-title")
            yield Static(f"{self._filename}", id="confirm-question")
            yield Static("")
            yield Static("Y  delete it", id="confirm-hint-yes")
            yield Static("N / Esc  cancel", id="confirm-hint-no")

    def on_mount(self):
        self.focus()

    def on_key(self, event):
        key = event.key.lower()
        if key == "y":
            event.stop()
            event.prevent_default()
            self.action_confirm()
        elif key in ("n", "escape"):
            event.stop()
            event.prevent_default()
            self.action_cancel()

    def action_confirm(self):
        self.dismiss(True)

    def action_cancel(self):
        self.dismiss(False)


class NoteItem(ListItem):
    DEFAULT_CSS = """
    NoteItem {
        padding: 0 1;
        height: 1;
        background: transparent;
        color: $text-muted;
    }
    NoteItem:hover { background: $accent 14%; color: ansi_default; }
    NoteItem.-highlight { background: $accent 24%; color: $accent; }
    """

    def __init__(self, filename: str, filepath: str = "", subdir: str = ""):
        super().__init__()
        self._filename = filename
        self._filepath = filepath or filename
        self._subdir = subdir

    def compose(self) -> ComposeResult:
        icon = "◆" if self._subdir == "journals" else "□"
        name = self._filename.replace(".md", "")
        yield Label(f" {icon} {name}")

    @property
    def filename(self) -> str:
        return self._filename

    @property
    def filepath(self) -> str:
        return self._filepath

    @property
    def subdir(self) -> str:
        return self._subdir


class NotesPanel(Widget):
    """File list — open in nvim (Enter/click), delete (d), filter (/)."""
    can_focus = True

    DEFAULT_CSS = """
    NotesPanel {
        height: 2fr;
        background: transparent;
        layout: vertical;
        border-bottom: tall $foreground 20%;
    }
    NotesPanel.hidden {
        display: none;
    }
    NotesPanel .panel-title {
        color: $text-muted;
        padding: 0 2;
        height: 1;
        background: transparent;
        border-bottom: tall $foreground 10%;
    }
    NotesPanel #notes-filter {
        height: 1;
        border: none;
        background: $accent 14%;
        color: ansi_default;
        padding: 0 2;
        display: none;
    }
    NotesPanel #notes-filter.visible {
        display: block;
    }
    NotesPanel ListView {
        background: transparent;
        border: none;
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("enter", "open_in_nvim", "Open",   show=False),
        Binding("d",     "delete_note",  "Delete", show=False),
        Binding("f",     "start_filter", "Filter", show=False),
        Binding("escape","clear_filter", "Clear",  show=False),
        Binding("j",     "move_down",    "↓",      show=False),
        Binding("k",     "move_up",      "↑",      show=False),
        Binding("g",     "g_prefix",     "Go",     show=False),
        Binding("G",     "go_bottom",    "Bottom", show=False),
        Binding("x",     "toggle_minimize", "Minimize", show=False),
        Binding("m",     "move_note",    "Move",   show=False),
    ]

    # ── Messages ──────────────────────────────────────────────────────────────

    class OpenInNvim(Message):
        def __init__(self, filepath: str, subdir: str):
            super().__init__()
            self.filepath = filepath
            self.subdir = subdir

    class FileSelected(Message):
        def __init__(self, filename: str, filepath: str = ""):
            super().__init__()
            self.filename = filename
            self.filepath = filepath or filename

    class EditRequested(Message):
        def __init__(self, filepath: str):
            super().__init__()
            self.filepath = filepath

    class NoteDeleted(Message):
        def __init__(self, filepath: str):
            super().__init__()
            self.filepath = filepath

    # ── Init ──────────────────────────────────────────────────────────────────

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._all_notes: list[tuple[str, str, str, str]] = []
        self._filter_active = False
        self._mode = "hidden"
        self._g_prefix = False
        self.add_class("hidden")

    def set_mode(self, mode: str):
        self._mode = mode
        if mode in ("pages", "journals"):
            self.remove_class("hidden")
            title = "notes" if mode == "pages" else "journals"
            self.query_one(".panel-title", Static).update(
                f"  {title}  [dim #3b4261]jk=nav  gg/G=top/bottom  enter=open  d=delete  f=filter  /=search[/dim #3b4261]"
            )
        else:
            self.add_class("hidden")
        self.refresh_notes()

    def compose(self) -> ComposeResult:
        yield Static(
            "  notes  [dim #3b4261]jk=nav  gg/G=top/bottom  enter=open  d=delete  f=filter  /=search[/dim #3b4261]",
            classes="panel-title",
        )
        yield Input(placeholder=" filter…", id="notes-filter")
        yield ListView(id="notes-list")

    def on_mount(self):
        self.refresh_notes()

    # ── Loading ───────────────────────────────────────────────────────────────

    async def _load_notes(self) -> list[tuple[str, str, str, str]]:
        try:
            active_folder = store.get_active_folder()
            rows: list[tuple[float, str, str, str, str]] = []
            
            # Search recursively for .md files
            for fp in active_folder.rglob("*.md"):
                try:
                    # Skip files in .git or other hidden directories
                    if any(part.startswith('.') for part in fp.relative_to(active_folder).parts):
                        continue
                    
                    content = fp.read_text(errors="replace")
                    rel_path = str(fp.relative_to(active_folder))
                    
                    # Determine subdirectory type based on path
                    if "journals" in rel_path.lower() or "journal" in rel_path.lower():
                        subdir = "journals"
                    else:
                        subdir = "pages"
                    
                    rows.append((fp.stat().st_mtime, fp.name, rel_path, subdir, content))
                except Exception:
                    pass
            
            rows.sort(key=lambda x: x[0], reverse=True)
            return [(fname, fpath, sub, content) for _, fname, fpath, sub, content in rows]
        except Exception:
            return []

    def refresh_notes(self):
        async def _load():
            self._all_notes = await self._load_notes()
            existing = {n[1] for n in self._all_notes}
            for fname in store.get_notes():
                if fname not in existing:
                    self._all_notes.append((fname, fname, "", ""))
            self._render_list(self._all_notes)
        try:
            asyncio.create_task(_load())
        except Exception:
            pass

    def _render_list(self, notes: list[tuple[str, str, str, str]]):
        lv = self.query_one("#notes-list", ListView)
        lv.clear()
        for filename, filepath, subdir, _ in notes:
            if self._mode in ("pages", "journals"):
                if subdir and subdir != self._mode:
                    continue
            lv.append(NoteItem(filename, filepath, subdir))
        if lv.children and lv.index is None:
            lv.index = 0

    # ── Current selected item ─────────────────────────────────────────────────

    def _selected_item(self) -> NoteItem | None:
        lv = self.query_one("#notes-list", ListView)
        highlighted = getattr(lv, "highlighted_child", None)
        if isinstance(highlighted, NoteItem):
            return highlighted
        if lv.index is None:
            return None
        children = [c for c in lv.children if isinstance(c, NoteItem)]
        if not children or lv.index >= len(children):
            return None
        return children[lv.index]

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_open_in_nvim(self):
        item = self._selected_item()
        if item:
            self.post_message(self.OpenInNvim(item.filepath, item.subdir))

    def action_delete_note(self):
        item = self._selected_item()
        if not item:
            return

        def _handle(confirmed: bool | None):
            if confirmed:
                asyncio.create_task(self._delete_note_item(item))

        self.app.push_screen(ConfirmDelete(item.filename), _handle)

    async def _delete_note_item(self, item: NoteItem):
        try:
            filepath = store.find_note_path(item.filepath)
            rel_path = filepath.relative_to(store.get_active_folder()).as_posix()
            abs_path = str(filepath.resolve())
            block_ids: list[int] = []

            try:
                from src.ingestion.db.connection import get_connection
                async with get_connection() as conn:
                    cursor = await conn.execute(
                        "SELECT id FROM notes WHERE file_path IN (?, ?, ?) AND deleted_at IS NULL",
                        (item.filepath, rel_path, abs_path)
                    )
                    row = await cursor.fetchone()
                    if row:
                        note_id = row[0]
                        cursor = await conn.execute(
                            "SELECT id FROM blocks WHERE note_id = ?", (note_id,)
                        )
                        block_ids = [r[0] for r in await cursor.fetchall()]

                if block_ids:
                    try:
                        from src.rag.vector_db import _get_vector_db
                        _get_vector_db().remove_by_block_ids(block_ids)
                    except Exception as exc:
                        print(f"Error removing note embeddings: {exc}")

                async with get_connection() as conn:
                    cursor = await conn.execute(
                        "SELECT id FROM notes WHERE file_path IN (?, ?, ?)",
                        (item.filepath, rel_path, abs_path)
                    )
                    row = await cursor.fetchone()
                    if row:
                        note_id = row[0]
                        cursor = await conn.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'"
                        )
                        tables = {r[0] for r in await cursor.fetchall()}
                        for table in ("embeddings", "block_tags", "block_references", "tasks", "events", "blocks"):
                            if table not in tables:
                                continue
                            col_cursor = await conn.execute(f"PRAGMA table_info({table})")
                            columns = {r[1] for r in await col_cursor.fetchall()}
                            if table == "block_tags":
                                await conn.execute(
                                    "DELETE FROM block_tags WHERE block_id IN (SELECT id FROM blocks WHERE note_id = ?)",
                                    (note_id,)
                                )
                            elif table == "block_references":
                                await conn.execute(
                                    "DELETE FROM block_references WHERE source_block_id IN (SELECT id FROM blocks WHERE note_id = ?) OR target_note_id = ?",
                                    (note_id, note_id)
                                )
                            elif "note_id" in columns:
                                await conn.execute(
                                    f"DELETE FROM {table} WHERE note_id = ?", (note_id,)
                                )
                        if "notes" in tables:
                            await conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
                        await conn.commit()
            except Exception as exc:
                print(f"Error deleting note from database: {exc}")

            if filepath.exists():
                filepath.unlink()

            store.remove_note_file(rel_path)
            self.post_message(self.NoteDeleted(item.filepath))
            self.refresh_notes()
        except Exception as exc:
            print(f"Error deleting note: {exc}")

    def action_start_filter(self):
        self._filter_active = True
        fi = self.query_one("#notes-filter", Input)
        fi.add_class("visible")
        fi.focus()

    def action_clear_filter(self):
        fi = self.query_one("#notes-filter", Input)
        fi.value = ""
        fi.remove_class("visible")
        self._filter_active = False
        self._render_list(self._all_notes)
        self.query_one("#notes-list", ListView).focus()

    def action_move_down(self):
        if self._consume_g_prefix():
            return
        lv = self.query_one("#notes-list", ListView)
        if lv.children:
            lv.index = min(len(lv.children) - 1, (lv.index or 0) + 1)

    def action_move_up(self):
        lv = self.query_one("#notes-list", ListView)
        if lv.children:
            lv.index = max(0, (lv.index or 0) - 1)

    def action_go_top(self):
        lv = self.query_one("#notes-list", ListView)
        lv.index = 0 if lv.children else None

    def action_g_prefix(self):
        if self._consume_g_prefix():
            self.action_go_top()
            return
        self._g_prefix = True
        self.set_timer(1.0, self._clear_g_prefix)

    def action_go_bottom(self):
        lv = self.query_one("#notes-list", ListView)
        if lv.children:
            lv.index = len(lv.children) - 1

    def action_toggle_minimize(self):
        # Toggle between hidden and current mode
        if self._mode == "hidden":
            self.set_mode("pages")
        else:
            self.set_mode("hidden")

    def action_move_note(self):
        # TODO: Implement moving notes between directories
        pass

    def _consume_g_prefix(self) -> bool:
        if not self._g_prefix:
            return False
        self._g_prefix = False
        return True

    def _clear_g_prefix(self):
        self._g_prefix = False

    # ── Input events ──────────────────────────────────────────────────────────

    def on_input_changed(self, event: Input.Changed):
        if event.input.id != "notes-filter":
            return
        q = event.value.strip().lower()
        filtered = [
            (fname, fpath, sub, content)
            for fname, fpath, sub, content in self._all_notes
            if not q or q in fname.lower() or q in content.lower()
        ]
        self._render_list(filtered)

    def on_input_submitted(self, event: Input.Submitted):
        if event.input.id != "notes-filter":
            return
        lv = self.query_one("#notes-list", ListView)
        if lv.children:
            lv.index = 0
            self.action_open_in_nvim()
        self.action_clear_filter()

    def on_list_view_selected(self, event: ListView.Selected):
        if isinstance(event.item, NoteItem):
            self.post_message(self.OpenInNvim(event.item.filepath, event.item.subdir))
