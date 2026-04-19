from __future__ import annotations
import asyncio
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from textual.widget import Widget
from textual.app import ComposeResult
from textual.widgets import Static
from textual.reactive import reactive
from textual.message import Message


class VimPanel(Widget):
    DEFAULT_CSS = """
    VimPanel {
        height: 1fr;
        border: solid $accent;
        background: $surface;
    }
    VimPanel .vim-title {
        background: $accent;
        color: $text;
        padding: 0 1;
        height: 1;
        text-style: bold;
    }
    VimPanel #vim-content {
        height: 1fr;
        overflow-y: auto;
        padding: 1;
        color: $text;
    }
    VimPanel .vim-line {
        color: $text-muted;
    }
    VimPanel .vim-line-number {
        color: $accent 70%;
    }
    """

    current_file: reactive[str] = reactive("")
    _lines: reactive[list] = reactive([])

    class OpenedFile(Message):
        def __init__(self, filename: str):
            super().__init__()
            self.filename = filename

    class NoteSaved(Message):
        def __init__(self, filepath: Path, subdir: str):
            super().__init__()
            self.filepath = filepath
            self.subdir = subdir

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._content_lines: list[str] = []
        self._tmpdir = tempfile.mkdtemp()

    def compose(self) -> ComposeResult:
        yield Static("  VIM EDITOR", id="vim-title", classes="vim-title")
        yield Static(id="vim-content")

    def load_file(self, filename: str):
        self.current_file = filename
        title = self.query_one("#vim-title", Static)
        title.update(f"  ✎  {filename}  [vim]")
        self._render_content()

    def append_line(self, text: str):
        self._content_lines.append(text)
        self._render_content()

    def _render_content(self):
        content_widget = self.query_one("#vim-content", Static)
        if not self._content_lines:
            placeholder = "\n".join(
                f"[dim]{i+1:>3}[/dim]  ~" for i in range(20)
            )
            content_widget.update(placeholder)
            return
        lines = []
        for i, line in enumerate(self._content_lines, 1):
            lines.append(f"[dim]{i:>3}[/dim]  {line}")
        content_widget.update("\n".join(lines))

    def open_in_real_vim(self, filename: str):
        filepath = Path(self._tmpdir) / filename
        if not filepath.exists():
            filepath.write_text(f"# {filename}\n")
        subprocess.run(["vim", str(filepath)])

    def _timestamp_filename(self, subdir: str) -> str:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        prefix = "page" if subdir == "pages" else "journal"
        return f"{prefix}_{ts}.md"

    async def open_vim_and_save(self, subdir: str = "pages"):
        from state.store import store

        filename = self._timestamp_filename(subdir)
        tmp_path = Path(self._tmpdir) / filename
        template = (
            f"# {filename}\n"
            f"# subdir: {subdir}\n"
            f"# date: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        )
        tmp_path.write_text(template, encoding="utf-8")

        try:
            title = self.query_one("#vim-title", Static)
            title.update(f"  ✎  Launching vim → {subdir}/{filename} …")
        except Exception:
            pass

        await asyncio.get_event_loop().run_in_executor(
            None, lambda: subprocess.run(
                ["vim", str(tmp_path)],
                stdin=open("/dev/tty"),
                stdout=open("/dev/tty", "w")
            )
        )

        content = tmp_path.read_text(encoding="utf-8")

        if content.strip():
            saved_path = store.save_note_to_disk(content, subdir, filename)
            self._content_lines = [line for line in content.splitlines() if line]
            self._render_content()
            try:
                title = self.query_one("#vim-title", Static)
                title.update(f"  ✎  {subdir}/{filename}  [saved ✓]")
            except Exception:
                pass
            self.post_message(self.NoteSaved(filepath=saved_path, subdir=subdir))
        else:
            try:
                title = self.query_one("#vim-title", Static)
                title.update("  ✎  VIM EDITOR  [no changes]")
            except Exception:
                pass