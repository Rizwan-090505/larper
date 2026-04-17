from textual.widget import Widget
from textual.app import ComposeResult
from textual.widgets import Static, ListView, ListItem, Label
from textual.message import Message
from state.store import store


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

    def __init__(self, filename: str):
        super().__init__()
        self._filename = filename

    def compose(self) -> ComposeResult:
        yield Label(f"  📄  {self._filename}")

    @property
    def filename(self) -> str:
        return self._filename


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

    class FileSelected(Message):
        def __init__(self, filename: str):
            super().__init__()
            self.filename = filename

    def compose(self) -> ComposeResult:
        yield Static("  📁 NOTES", classes="panel-title")
        yield ListView(id="notes-list")

    def on_mount(self):
        self.refresh_notes()

    def refresh_notes(self):
        lv = self.query_one("#notes-list", ListView)
        lv.clear()
        for fname in store.get_notes():
            lv.append(NoteItem(fname))

    def on_list_view_selected(self, event: ListView.Selected):
        if isinstance(event.item, NoteItem):
            self.post_message(self.FileSelected(event.item.filename))