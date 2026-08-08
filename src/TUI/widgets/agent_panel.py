from __future__ import annotations

import re
from pathlib import Path
from textual.widget import Widget
from textual.app import ComposeResult
from textual.widgets import Static, RichLog
from textual.message import Message
from datetime import datetime
from rich.text import Text
from rich.style import Style


_NOTE_RE = re.compile(r"(?<![\w/.-])((?:~?/|/)?[\w.-]+(?:/[\w.-]+)*\.md)(?![\w/.-])")


class AgentPanel(Widget):
    """Primary conversational chat panel."""

    can_focus = True

    DEFAULT_CSS = """
    AgentPanel {
        height: 1fr;
        background: #1a1b26;
        border: none;
    }
    AgentPanel .panel-title {
        background: #1e2030;
        color: #565f89;
        padding: 0 2;
        height: 1;
        text-style: none;
    }
    AgentPanel RichLog {
        background: transparent;
        border: none;
        height: 1fr;
        padding: 0 2;
        scrollbar-color: #3b4261;
        scrollbar-size: 1 1;
    }
    """

    class NoteLinkClicked(Message):
        def __init__(self, filepath: str):
            super().__init__()
            self.filepath = filepath

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._stream_started = False
        self._stream_buffer = ""
        self._stream_body_lines = 0

    def compose(self) -> ComposeResult:
        yield Static(
            "  agent chat  [dim #3b4261]i=focus input  hl=switch panels[/dim #3b4261]",
            classes="panel-title",
        )
        yield RichLog(
            id="output-log", highlight=True, markup=True, wrap=True, min_width=1
        )

    def on_mount(self):
        log = self.query_one("#output-log", RichLog)

    def log_user(self, msg: str):
        log = self.query_one("#output-log", RichLog)
        ts = datetime.now().strftime("%H:%M")
        log.write(
            f"  [bold #c0caf5]you[/bold #c0caf5]  [dim #565f89]{ts}[/dim #565f89]"
        )
        log.write(f"  [#c0caf5]{msg}[/#c0caf5]")
        log.write("")

    def log_agent(self, msg: str):
        log = self.query_one("#output-log", RichLog)
        ts = datetime.now().strftime("%H:%M")
        log.write(
            f"  [bold #7aa2f7]agent[/bold #7aa2f7]  [dim #565f89]{ts}[/dim #565f89]"
        )
        rich_text = self._linkify_notes(msg)
        log.write(rich_text)
        log.write("")

    # ── Streaming helpers ─────────────────────────────────────────────────────

    def log_stream_start(self) -> None:
        """Write the 'agent HH:MM' header once before the first chunk arrives."""
        log = self.query_one("#output-log", RichLog)
        ts = datetime.now().strftime("%H:%M")
        log.write(
            f"  [bold #7aa2f7]agent[/bold #7aa2f7]  [dim #565f89]{ts}[/dim #565f89]"
        )
        self._stream_started = True
        self._stream_buffer = ""
        self._stream_body_lines = 0

    def log_stream_chunk(self, chunk: str) -> None:
        """Append a streamed chunk and re-render the reply-so-far as one block.

        RichLog.write() always appends brand-new line(s) to the log — it has
        no "update the last line" API. Writing each incoming chunk directly
        (as the old code did) therefore split the reply across one RichLog
        line per chunk instead of a normal flowing paragraph. Instead, we
        accumulate the full text seen so far, drop the lines we rendered for
        the previous (shorter) version of it, and re-write the whole thing —
        giving a properly wrapped, continuously-updating paragraph.
        """
        log = self.query_one("#output-log", RichLog)
        self._stream_buffer += chunk

        if self._stream_body_lines and log.lines:
            del log.lines[-self._stream_body_lines :]

        rich_text = self._linkify_notes(self._stream_buffer)
        lines_before = len(log.lines)
        log.write(rich_text)
        self._stream_body_lines = len(log.lines) - lines_before

    def log_stream_end(self) -> None:
        """Write a trailing blank line to visually close the streamed reply."""
        if self._stream_started:
            self.query_one("#output-log", RichLog).write("")
            self._stream_started = False
            self._stream_buffer = ""
            self._stream_body_lines = 0

    # ── Tool-call logging ─────────────────────────────────────────────────────

    def log_tool_call(self, tool_name: str, args: dict):
        log = self.query_one("#output-log", RichLog)
        args_str = ", ".join(f"{k}={repr(v)}" for k, v in args.items())
        log.write(f"  [dim #3b4261]  ⚙ {tool_name}({args_str})[/dim #3b4261]")

    def log_tool_calls(self, tool_calls: list[dict]):
        for tc in tool_calls:
            self.log_tool_call(tc.get("tool", "?"), tc.get("args", {}))

    def log_status(self, msg: str):
        log = self.query_one("#output-log", RichLog)
        log.write(f"  [dim #565f89 italic]  {msg}[/dim #565f89 italic]")

    def log_message(self, msg: str):
        log = self.query_one("#output-log", RichLog)
        log.write(f"  {msg}")
        log.write("")

    def _linkify_notes(self, msg: str) -> Text:
        """
        Build a Rich Text object where note path references become clickable.

        Textual dispatches clicks by inspecting Rich Style metadata. When the
        style on a span contains {"@click": "action_name(args)"}, clicking that
        span runs the named action on the widget's namespace.  We use
        "app.open_note('<path>')" so the app-level action_open_note handles it.
        """
        base_style = Style.parse("#a9b1d6")
        link_style = Style.parse("#7aa2f7 underline")

        result = Text("  ", style=base_style, end="")

        last_end = 0
        for m in _NOTE_RE.finditer(msg):
            start, end = m.span()
            # Plain text before this match
            if start > last_end:
                result.append(msg[last_end:start], style=base_style)
            # Clickable note link
            path = m.group(1)
            display = Path(path).name.replace(".md", "")
            action = f"app.open_note('{path}')"
            click_style = link_style + Style.from_meta({"@click": action})
            result.append(display, style=click_style)
            last_end = end

        # Remaining plain text
        if last_end < len(msg):
            result.append(msg[last_end:], style=base_style)

        return result
