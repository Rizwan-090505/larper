from textual.widget import Widget
from textual.app import ComposeResult
from textual.widgets import Static, ListView, ListItem, Label
from textual.message import Message
from textual.binding import Binding
from state.store import store
import asyncio


class NoteItem(ListItem):
    DEFAULT_CSS = """
    NoteItem {
        padding: 0 1;
        height: auto;
        background: transparent;
        color: $text;
    }
    NoteItem:hover {
        background: $accent 20%;
    }
    NoteItem.-highlight {
        background: $accent 40%;
    }
    """

    def __init__(self, filename: str, filepath: str = None):
        super().__init__()
        self._filename = filename
        self._filepath = filepath or filename

    def compose(self) -> ComposeResult:
        yield Label(f"  📄  {self._filename}")

    @property
    def filename(self) -> str:
        return self._filename

    @property
    def filepath(self) -> str:
        return self._filepath


class NotesPanel(Widget):
    DEFAULT_CSS = """
    NotesPanel {
        height: 1fr;
        border: solid $success;
        background: $surface;
    }
    NotesPanel .panel-title {
        background: $success;
        color: $background;
        padding: 0 1;
        height: 1;
        text-style: bold;
    }
    NotesPanel ListView {
        background: transparent;
        border: none;
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("e", "edit_note", "Edit (vim)", show=True),
        Binding("enter", "open_note", "Open", show=True),
    ]

    class FileSelected(Message):
        def __init__(self, filename: str, filepath: str = None):
            super().__init__()
            self.filename = filename
            self.filepath = filepath or filename

    class EditRequested(Message):
        def __init__(self, filepath: str):
            super().__init__()
            self.filepath = filepath

    def compose(self) -> ComposeResult:
        yield Static("  📁 NOTES", classes="panel-title")
        yield ListView(id="notes-list")

    def on_mount(self):
        self.refresh_notes()

    async def _load_notes_from_directory(self):
        """Load all notes from the directory based on most recent edits."""
        try:
            from state.store import store
            
            active_folder = store.get_active_folder()
            file_stats = []
            
            for subdir in ["pages", "journals"]:
                dir_path = active_folder / subdir
                if dir_path.exists() and dir_path.is_dir():
                    for filepath in dir_path.glob("*.md"):
                        try:
                            mtime = filepath.stat().st_mtime
                            file_stats.append((mtime, filepath.name, str(filepath)))
                        except Exception:
                            pass
                            
            # Sort by modification time descending (most recent first)
            file_stats.sort(key=lambda x: x[0], reverse=True)
            
            return [(fname, fpath) for _, fname, fpath in file_stats]
        except Exception as e:
            print(f"Error loading notes from directory: {e}")
            return []

    def refresh_notes(self):
        """Refresh notes list from directory."""
        async def load_and_display():
            dir_notes = await self._load_notes_from_directory()
            lv = self.query_one("#notes-list", ListView)
            lv.clear()
            
            # Add directory notes
            for filename, filepath in dir_notes:
                lv.append(NoteItem(filename, filepath))
            
            # Also add in-memory notes from store
            for fname in store.get_notes():
                # Check if not already in list
                if not any(item.filename == fname for item in lv.children if isinstance(item, NoteItem)):
                    lv.append(NoteItem(fname))
        
        # Schedule the async load
        try:
            asyncio.create_task(load_and_display())
        except Exception:
            # Fallback to store if db not available
            lv = self.query_one("#notes-list", ListView)
            lv.clear()
            for fname in store.get_notes():
                lv.append(NoteItem(fname))

    def on_list_view_selected(self, event: ListView.Selected):
        if isinstance(event.item, NoteItem):
            self.post_message(self.FileSelected(event.item.filename, event.item.filepath))

    def action_edit_note(self):
        """Edit the selected note in vim."""
        lv = self.query_one("#notes-list", ListView)
        if lv.index is not None:
            item = lv.children[lv.index]
            if isinstance(item, NoteItem):
                self.post_message(self.EditRequested(item.filepath))

    def action_open_note(self):
        """Open the selected note."""
        lv = self.query_one("#notes-list", ListView)
        if lv.index is not None:
            item = lv.children[lv.index]
            if isinstance(item, NoteItem):
                self.post_message(self.FileSelected(item.filename, item.filepath))