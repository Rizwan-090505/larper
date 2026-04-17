from textual.widget import Widget
from textual.app import ComposeResult
from textual.widgets import Static, ListView, ListItem, Label
from state.store import store, Item
import asyncio


class EventItem(ListItem):
    DEFAULT_CSS = """
    EventItem {
        padding: 0 1;
        height: auto;
        background: transparent;
        color: $text;
    }
    EventItem.highlighted {
        background: $warning 30%;
    }
    """

    def __init__(self, item: Item):
        super().__init__()
        self._item = item

    def compose(self) -> ComposeResult:
        yield Label(f"  ◷  {self._item.time}  →  {self._item.text}")

    def on_mount(self):
        async def highlight():
            self.add_class("highlighted")
            await asyncio.sleep(0.6)
            self.remove_class("highlighted")

        asyncio.get_event_loop().create_task(highlight())


class EventsPanel(Widget):
    DEFAULT_CSS = """
    EventsPanel {
        height: 1fr;
        border: solid $warning;
        background: $surface;
    }
    EventsPanel .panel-title {
        background: $warning;
        color: $background;
        padding: 0 1;
        height: 1;
        text-style: bold;
    }
    EventsPanel ListView {
        background: transparent;
        border: none;
        height: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("  ◷ EVENTS", classes="panel-title")
        yield ListView(id="events-list")

    def refresh_events(self):
        lv = self.query_one("#events-list", ListView)
        lv.clear()
        for item in store.get_events():
            lv.append(EventItem(item))

    def add_event(self, item: Item):
        lv = self.query_one("#events-list", ListView)
        lv.append(EventItem(item))