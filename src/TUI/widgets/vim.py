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
        from state.store import store
        # This function seems unused, but let's point it to the Active Folder just in case
        filepath = store.get_active_folder() / filename
        if not filepath.exists():
            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text(f"# {filename}\n")
        subprocess.run(["vim", str(filepath)])

    def _timestamp_filename(self, subdir: str) -> str:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        prefix = "page" if subdir == "pages" else "journal"
        return f"{prefix}_{ts}.md"

    async def open_vim_and_save(self, subdir: str = "pages", filename: str = None):
        from state.store import store

        if not filename:
            filename = self._timestamp_filename(subdir)
        
        target_dir = store.get_active_folder() / subdir
        target_dir.mkdir(parents=True, exist_ok=True)
        filepath = target_dir / filename

        if not filepath.exists():
            template = (
                f"# {filename}\n"
                f"# subdir: {subdir}\n"
                f"# date: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
            )
            filepath.write_text(template, encoding="utf-8")

        try:
            title = self.query_one("#vim-title", Static)
            title.update(f"  ✎  Opening vim → {subdir}/{filename} …")
        except Exception:
            pass

        # Suspend the app and let vim take over the terminal
        await self._suspend_app_for_vim(str(filepath))

        # Because we're editing the real file, watchdog handles DB ingestion,
        # but we still want to update our local TUI state and store tracking
        content = ""
        if filepath.exists():
            content = filepath.read_text(encoding="utf-8")

        if content.strip():
            # Add to store file tracking array manually since we skipped save_note_to_disk logic
            store.add_note_file(str(Path(subdir) / filename))
            self._content_lines = [line for line in content.splitlines() if line]
            self._render_content()
            try:
                title = self.query_one("#vim-title", Static)
                title.update(f"  ✎  {subdir}/{filename}  [saved ✓]")
            except Exception:
                pass
            self.post_message(self.NoteSaved(filepath=filepath, subdir=subdir))
        else:
            try:
                title = self.query_one("#vim-title", Static)
                title.update("  ✎  VIM EDITOR  [no text]")
            except Exception:
                pass

    async def _suspend_app_for_vim(self, filepath: str):
        """Suspend the textual app, let vim take over terminal, then resume."""
        with self.app.suspend():
            subprocess.run(["vim", filepath])

    async def open_vim_edit_file(self, filepath: str):
        """Open an existing file in vim for editing, taking over terminal."""
        try:
            title = self.query_one("#vim-title", Static)
            title.update(f"  ✎  Opening vim for {Path(filepath).name} …")
        except Exception:
            pass

        # Suspend app and let vim take over
        await self._suspend_app_for_vim(filepath)

        try:
            title = self.query_one("#vim-title", Static)
            title.update(f"  ✎  {Path(filepath).name}  [edited ✓]")
        except Exception:
            pass