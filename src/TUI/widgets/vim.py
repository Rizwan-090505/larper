from __future__ import annotations
import subprocess
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

    def compose(self) -> ComposeResult:
        yield Static("  VIM EDITOR", id="vim-title", classes="vim-title")
        yield Static(id="vim-content")

    def load_file(self, filename: str):
        """Load a file into the vim panel display."""
        self.current_file = filename
        self._update_title(f"  ✎  {filename}  [vim]")
        
        from state.store import store
        path = store.get_active_folder() / filename
        
        if path.exists():
            try:
                content = path.read_text(encoding="utf-8")
                self._content_lines = content.splitlines()
            except Exception as e:
                self._content_lines = [f"Error reading file: {e}"]
        else:
            self._content_lines = []
        
        self._render_content()

    def append_line(self, text: str):
        """Append a line to the content display."""
        self._content_lines.append(text)
        self._render_content()

    def _update_title(self, text: str):
        try:
            title = self.query_one("#vim-title", Static)
            title.update(text)
        except Exception:
            pass

    def _render_content(self):
        """Render content lines with line numbers."""
        content_widget = self.query_one("#vim-content", Static)
        
        if not self._content_lines:
            placeholder = "\n".join(f"[dim]{i+1:>3}[/dim]  ~" for i in range(20))
            content_widget.update(placeholder)
            return
        
        lines = [f"[dim]{i:>3}[/dim]  {line}" for i, line in enumerate(self._content_lines, 1)]
        content_widget.update("\n".join(lines))

    def _create_template(self, filename: str, subdir: str) -> str:
        """Create initial file template."""
        return (
            f"# {filename}\n"
            f"# subdir: {subdir}\n"
            f"# date: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        )

    def open_vim_editor(
        self,
        filepath: Path,
        subdir: str = "pages",
        is_new: bool = True
    ) -> tuple[bool, Path | None]:
        """
        Open vim in raw terminal mode (TUI is suspended by caller).

        Returns:
            (success, filepath) — success is True if file was saved with changes
        """
        from state.store import store

        filepath.parent.mkdir(parents=True, exist_ok=True)

        if is_new or not filepath.exists():
            template = self._create_template(filepath.name, subdir)
            filepath.write_text(template, encoding="utf-8")
            initial_content = template
        else:
            try:
                initial_content = filepath.read_text(encoding="utf-8")
            except Exception as e:
                self._update_title(f"  ✎  Error reading file: {e}")
                return False, None

        action = "Creating" if is_new else "Editing"
        self._update_title(f"  ✎  {action} {filepath.name} …")

        try:
            result = subprocess.run(
                ["vim", str(filepath)],
                stdin=None,  # inherit stdin so vim is interactive
            )
        except FileNotFoundError:
            self._update_title("  ✎  VIM EDITOR  [vim not found - install vim]")
            return False, None
        except Exception as e:
            self._update_title(f"  ✎  VIM EDITOR  [error: {e}]")
            return False, None

        if result.returncode != 0:
            self._update_title("  ✎  VIM EDITOR  [vim failed]")
            return False, None

        try:
            content = filepath.read_text(encoding="utf-8").strip()
        except Exception as e:
            self._update_title(f"  ✎  Error reading saved file: {e}")
            return False, None

        if not content or content == initial_content.strip():
            self._update_title("  ✎  VIM EDITOR  [no changes]")
            return False, None

        try:
            rel_path = filepath.relative_to(store.get_active_folder())
            store.add_note_file(str(rel_path))
        except Exception as e:
            self._update_title(f"  ✎  Warning: Could not register file - {e}")

        self._content_lines = content.splitlines()
        self._render_content()
        self._update_title(f"  ✎  {filepath.name}  [saved ✓]")

        self.post_message(self.NoteSaved(filepath=filepath, subdir=subdir))

        return True, filepaths