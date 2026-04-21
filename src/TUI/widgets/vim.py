from __future__ import annotations
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
    """Panel that displays vim content and manages vim subprocess."""
    
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
    """

    current_file: reactive[str] = reactive("")

    class NoteSaved(Message):
        """Posted when a note is saved from vim."""
        def __init__(self, filepath: Path, subdir: str):
            super().__init__()
            self.filepath = filepath
            self.subdir = subdir

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._content_lines: list[str] = []
<<<<<<< HEAD
=======
        self._tmpdir = Path(tempfile.mkdtemp())
>>>>>>> 7c2c78e (inserting worked)

    def compose(self) -> ComposeResult:
        yield Static("  VIM EDITOR", id="vim-title", classes="vim-title")
        yield Static(id="vim-content")

    def load_file(self, filename: str):
        """Load a file into the vim panel display."""
        self.current_file = filename
        self._update_title(f"  ✎  {filename}  [vim]")
        self._render_content()

    def append_line(self, text: str):
        """Append a line to the content display."""
        self._content_lines.append(text)
        self._render_content()

    def _update_title(self, text: str):
        """Update the vim panel title."""
        try:
            title = self.query_one("#vim-title", Static)
            title.update(text)
        except Exception:
            pass

    def _render_content(self):
        """Render content lines with line numbers."""
        content_widget = self.query_one("#vim-content", Static)
        
        if not self._content_lines:
            # Show empty vim-style placeholder
            placeholder = "\n".join(f"[dim]{i+1:>3}[/dim]  ~" for i in range(20))
            content_widget.update(placeholder)
            return
        
        # Render actual content with line numbers
        lines = [f"[dim]{i:>3}[/dim]  {line}" for i, line in enumerate(self._content_lines, 1)]
        content_widget.update("\n".join(lines))

<<<<<<< HEAD
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
=======
    def _generate_filename(self, subdir: str) -> str:
        """Generate timestamped filename."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
>>>>>>> 7c2c78e (inserting worked)
        prefix = "page" if subdir == "pages" else "journal"
        return f"{prefix}_{timestamp}.md"

<<<<<<< HEAD
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
=======
    def _create_template(self, filename: str, subdir: str) -> str:
        """Create initial file template."""
        return (
            f"# {filename}\n"
            f"# subdir: {subdir}\n"
            f"# date: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        )

    def open_vim_editor(self, subdir: str = "pages") -> tuple[bool, Path | None]:
        """
        Open vim in raw terminal mode (suspends TUI).
        
        Returns:
            (success: bool, filepath: Path | None)
        """
        from state.store import store

        filename = self._generate_filename(subdir)
        tmp_path = self._tmpdir / filename
        
        # Create initial template
        template = self._create_template(filename, subdir)
        tmp_path.write_text(template, encoding="utf-8")
        
        # Update UI before launching
        self._update_title(f"  ✎  Opening vim → {subdir}/{filename} …")

        # Launch vim - this will be called when TUI is suspended
        result = subprocess.run(
            ["vim", str(tmp_path)],
            stdin=subprocess.DEVNULL,  # Don't interfere with terminal
        )

        # Check if vim exited successfully
        if result.returncode != 0:
            self._update_title("  ✎  VIM EDITOR  [vim failed]")
            return False, None

        # Read the edited content
        content = tmp_path.read_text(encoding="utf-8").strip()
        
        if not content or content == template.strip():
            # No changes made
            self._update_title("  ✎  VIM EDITOR  [no changes]")
            return False, None

        # Save to disk
        saved_path = store.save_note_to_disk(content, subdir, filename)
        
        # Update display
        self._content_lines = [line for line in content.splitlines() if line]
        self._render_content()
        self._update_title(f"  ✎  {subdir}/{filename}  [saved ✓]")
        
        # Notify app
        self.post_message(self.NoteSaved(filepath=saved_path, subdir=subdir))
        
        return True, saved_path
>>>>>>> 7c2c78e (inserting worked)
