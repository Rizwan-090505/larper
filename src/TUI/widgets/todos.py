from textual.widget import Widget
from textual.app import ComposeResult
from textual.widgets import Static, ListView, ListItem, Label
from textual.reactive import reactive
from textual.css.query import NoMatches
from state.store import store, Item
import asyncio


class TodoItem(ListItem):
    DEFAULT_CSS = """
    TodoItem {
        padding: 0 1;
        height: auto;
        background: transparent;
        color: $text;
        opacity: 0.0;
    }
    TodoItem.visible {
        opacity: 1.0;
    }
    TodoItem.highlighted {
        background: $accent 30%;
    }
    """

    def __init__(self, item: Item):
        super().__init__()
        self.item = item

    def compose(self) -> ComposeResult:
        ts = item.created_at.strftime("%H:%M")
        yield Label(f"  ☐  {self.item.text}  [{ts}]")

    def on_mount(self):
        async def fade_in():
            await asyncio.sleep(0.05)
            self.add_class("visible")
            self.add_class("highlighted")
            await asyncio.sleep(0.5)
            self.remove_class("highlighted")

        asyncio.get_event_loop().create_task(fade_in())


# fix variable reference inside compose
class TodoItem(ListItem):
    DEFAULT_CSS = """
    TodoItem {
        padding: 0 1;
        height: auto;
        background: transparent;
        color: $text;
    }
    TodoItem.highlighted {
        background: $accent 30%;
        color: $text-muted;
    }
    """

    def __init__(self, item: Item):
        super().__init__()
        self._item = item

    def compose(self) -> ComposeResult:
        ts = self._item.created_at.strftime("%H:%M")
        yield Label(f"  ☐  {self._item.text}  [{ts}]")

    def on_mount(self):
        async def highlight():
            self.add_class("highlighted")
            await asyncio.sleep(0.6)
            self.remove_class("highlighted")

        asyncio.get_event_loop().create_task(highlight())


class TodosPanel(Widget):
    DEFAULT_CSS = """
    TodosPanel {
        height: 1fr;
        border: solid $primary;
        background: $surface;
    }
    TodosPanel .panel-title {
        background: $primary;
        color: $text;
        padding: 0 1;
        height: 1;
        text-style: bold;
    }
    TodosPanel ListView {
        background: transparent;
        border: none;
        height: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("  ✓ TODOS", classes="panel-title")
        yield ListView(id="todos-list")

    def refresh_todos(self):
        lv = self.query_one("#todos-list", ListView)
        lv.clear()
        for item in store.get_todos():
            lv.append(TodoItem(item))

    def add_todo(self, item: Item):
        lv = self.query_one("#todos-list", ListView)
        lv.append(TodoItem(item))