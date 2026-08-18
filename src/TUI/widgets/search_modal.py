"""Full-screen search modal — searches notes via hybrid RAG, opens result in nvim."""
from __future__ import annotations

import asyncio
from pathlib import Path

from textual.screen import ModalScreen
from textual.widgets import Input, ListView, ListItem, Label, Static
from textual.app import ComposeResult
from textual.message import Message
from textual.binding import Binding


class SearchModal(ModalScreen):
    """
    Fuzzy/hybrid search across all notes.
    Enter on a result → opens it in nvim and dismisses.
    Esc → dismiss without action.
    """

    DEFAULT_CSS = """
    SearchModal {
        align: center middle;
        background: transparent;
    }
    SearchModal #search-dialog {
        width: 70;
        height: 24;
        border: tall $foreground 10%;
        background: ansi_default;
    }
    SearchModal #search-header {
        background: $accent 24%;
        color: ansi_default;
        height: 1;
        padding: 0 1;
        text-style: bold;
    }
    SearchModal #search-input {
        height: 3;
        border: tall $foreground 20%;
        background: transparent;
        color: ansi_default;
        margin: 1 1 0 1;
    }
    SearchModal #search-input:focus {
        border: tall $accent 100%;
    }
    SearchModal #search-count {
        height: 1;
        padding: 0 2;
        color: $text-muted;
        text-style: dim;
    }
    SearchModal #search-results {
        height: 1fr;
        border: tall $foreground 10%;
        background: transparent;
        margin: 0 1;
    }
    SearchModal #search-footer {
        height: 1;
        padding: 0 2;
        color: $text-muted;
        text-style: dim;
        margin: 0 1 1 1;
    }
    SearchModal SearchResultItem {
        padding: 0 1;
        height: auto;
        min-height: 1;
    }
    SearchModal SearchResultItem:hover { background: $accent 20%; }
    SearchModal SearchResultItem.-highlight { background: $accent 40%; }
    """

    BINDINGS = [
        Binding("escape", "cancel",      "Cancel",  show=True),
        Binding("enter",  "open_result", "Open",    show=True),
        Binding("j",      "move_down",   "↓",       show=False),
        Binding("k",      "move_up",     "↑",       show=False),
    ]

    # ── Message ───────────────────────────────────────────────────────────────

    class ResultSelected(Message):
        def __init__(self, filepath: str, subdir: str):
            super().__init__()
            self.filepath = filepath
            self.subdir = subdir

    # ── Init ─────────────────────────────────────────────────────────────────

    def __init__(self, query: str = ""):
        super().__init__()
        self._initial_query = query
        self._results: list[dict] = []

    # ── Compose ───────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        from textual.containers import Vertical
        with Vertical(id="search-dialog"):
            yield Static("  🔎  Search Notes", id="search-header")
            yield Input(
                placeholder="  Type to search… (Enter to open, Esc to close)",
                id="search-input",
            )
            yield Static("", id="search-count")
            yield ListView(id="search-results")
            yield Static(
                " [dim]↑↓[/dim] navigate  [dim]Enter[/dim] open in nvim  [dim]Esc[/dim] cancel",
                id="search-footer",
            )

    def on_mount(self):
        inp = self.query_one("#search-input", Input)
        if self._initial_query:
            inp.value = self._initial_query
        inp.focus()
        if self._initial_query:
            asyncio.create_task(self._do_search(self._initial_query))

    # ── Search ────────────────────────────────────────────────────────────────

    def on_input_changed(self, event: Input.Changed):
        if event.input.id != "search-input":
            return
        q = event.value.strip()
        if q:
            asyncio.create_task(self._do_search(q))
        else:
            self._results = []
            self._render_results([])

    def on_input_submitted(self, event: Input.Submitted):
        if event.input.id == "search-input":
            self.action_open_result()

    async def _do_search(self, text: str):
        try:
            from src.rag.search_tools import hybrid_search, fzf_search
            results = await fzf_search(text, 12)
            if not results:
                results = await hybrid_search(text, 12)
            self._results = results or []
            self._render_results(self._results)
        except Exception:
            self._results = []
            self._render_results([])

    def _render_results(self, results: list[dict]):
        lv = self.query_one("#search-results", ListView)
        count = self.query_one("#search-count", Static)
        lv.clear()
        if not results:
            count.update("  No results")
            return
        count.update(f"  {len(results)} result{'s' if len(results) != 1 else ''}")
        for r in results:
            title = r.get("title") or r.get("target_title") or "untitled"
            fp = r.get("file_path", "")
            snippet = (r.get("content") or "")[:80].replace("\n", " ").strip()
            score = r.get("hybrid_score") or r.get("similarity_score") or 0
            score_str = f"[dim]{score:.2f}[/dim]" if score else ""
            lv.append(_SearchResultItem(title, fp, snippet, score_str, r))
        lv.index = 0

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_cancel(self):
        self.dismiss(None)

    def action_open_result(self):
        lv = self.query_one("#search-results", ListView)
        if lv.index is None:
            return
        children = [c for c in lv.children if isinstance(c, _SearchResultItem)]
        if not children or lv.index >= len(children):
            return
        item = children[lv.index]
        self.dismiss({"filepath": item.filepath, "subdir": item.subdir})

    def action_move_down(self):
        lv = self.query_one("#search-results", ListView)
        if lv.children:
            lv.index = min(len(lv.children) - 1, (lv.index or 0) + 1)

    def action_move_up(self):
        lv = self.query_one("#search-results", ListView)
        if lv.children:
            lv.index = max(0, (lv.index or 0) - 1)

    def on_list_view_selected(self, event: ListView.Selected):
        if isinstance(event.item, _SearchResultItem):
            self.dismiss({"filepath": event.item.filepath, "subdir": event.item.subdir})


class _SearchResultItem(ListItem):
    DEFAULT_CSS = """
    _SearchResultItem {
        padding: 0 1;
        height: auto;
        min-height: 2;
        background: transparent;
    }
    _SearchResultItem:hover { background: $accent 20%; }
    _SearchResultItem.-highlight { background: $accent 40%; }
    """

    def __init__(self, title: str, filepath: str, snippet: str, score_str: str, raw: dict):
        super().__init__()
        self._title = title
        self._filepath = filepath
        self._snippet = snippet
        self._score_str = score_str
        self._raw = raw

    @property
    def filepath(self) -> str:
        return self._filepath

    @property
    def subdir(self) -> str:
        p = Path(self._filepath)
        return p.parent.name if self._filepath else "pages"

    def compose(self) -> ComposeResult:
        fp_short = self._filepath or ""
        yield Label(
            f" [bold]{self._title}[/bold]  {self._score_str}  [dim]{fp_short}[/dim]"
        )
        if self._snippet:
            yield Label(f"   [dim]{self._snippet}…[/dim]")
