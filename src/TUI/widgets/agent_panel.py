from __future__ import annotations
import re
import subprocess
from pathlib import Path
from textual.widget import Widget
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Static, Button
from textual.message import Message
from datetime import datetime
from rich.text import Text
from rich.style import Style

_NOTE_RE = re.compile(r"(?<![\w/.-])((?:~?/|/)?[\w.-]+(?:/[\w.-]+)*\.md)(?![\w/.-])")
_BOLD_RE = re.compile(r"\*\*(.*?)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)")
_CODE_RE = re.compile(r"`([^`]+)`")
_H3_RE = re.compile(r"^###\s+(.+)$")
_H2_RE = re.compile(r"^##\s+(.+)$")
_H1_RE = re.compile(r"^#\s+(.+)$")
_BULLET_RE = re.compile(r"^(\s*)([-*+]|\d+\.)\s+(.+)$")
_HR_RE = re.compile(r"^---+$")

# ── Palette (Tokyo Night) ─────────────────────────────────────────────────────
_BASE = Style.parse("#a9b1d6")
_DIM = Style.parse("#565f89")
_H1 = Style.parse("#7aa2f7 bold")
_H2 = Style.parse("#7dcfff bold")
_H3 = Style.parse("#e0af68 bold")
_LINK = Style.parse("#7aa2f7 underline")
_BULLET = Style.parse("#3b4261")
_CODE = Style.parse("#bb9af7 on #1e2030")
_RULE = Style.parse("#3b4261")


# ── Inline markdown renderer ──────────────────────────────────────────────────
def _render_inline(raw: str, base: Style = _BASE) -> Text:
    """
    Render **bold**, *italic*, and `code` spans.
    Overlapping spans: earliest start wins; ties go to the longest span.
    """
    candidates: list[tuple[int, int, str, Style]] = []

    for m in _BOLD_RE.finditer(raw):
        candidates.append((m.start(), m.end(), m.group(1), base + Style(bold=True)))
    for m in _ITALIC_RE.finditer(raw):
        candidates.append((m.start(), m.end(), m.group(1), base + Style(italic=True)))
    for m in _CODE_RE.finditer(raw):
        candidates.append((m.start(), m.end(), m.group(1), _CODE))

    candidates.sort(key=lambda x: (x[0], -(x[1] - x[0])))

    result = Text(end="")
    cur = 0
    for start, end, val, sty in candidates:
        if start < cur:
            continue
        if start > cur:
            result.append(raw[cur:start], style=base)
        result.append(val, style=sty)
        cur = end

    if cur < len(raw):
        result.append(raw[cur:], style=base)
    return result


def _linkify(text: str, base: Style = _BASE) -> Text:
    result = Text(end="")
    last = 0
    for m in _NOTE_RE.finditer(text):
        s, e = m.span()
        if s > last:
            result.append_text(_render_inline(text[last:s], base))
        display = Path(m.group(1)).name.replace(".md", "")
        click_sty = _LINK + Style.from_meta(
            {"@click": f"app.open_note('{m.group(1)}')"}
        )
        result.append(display, style=click_sty)
        last = e
    if last < len(text):
        result.append_text(_render_inline(text[last:], base))
    return result


def _render_markdown(msg: str) -> list[Text]:
    """Render markdown to a list of Rich Text lines."""
    lines = msg.splitlines()
    out: list[Text] = []
    in_fence = False
    code_buf: list[str] = []

    def flush_code():
        for cl in code_buf:
            out.append(Text(" " + cl, style=_CODE))
        code_buf.clear()

    for line in lines:
        if line.startswith("```"):
            if not in_fence:
                in_fence = True
                code_buf.clear()
            else:
                in_fence = False
                flush_code()
            continue
        if in_fence:
            code_buf.append(line)
            continue

        if m := _H3_RE.match(line):
            t = Text(" ")
            t.append(m.group(1), style=_H3)
            out.append(t)
            continue
        if m := _H2_RE.match(line):
            t = Text(" ")
            t.append(m.group(1), style=_H2)
            out.append(t)
            continue
        if m := _H1_RE.match(line):
            t = Text(" ")
            t.append(m.group(1), style=_H1)
            out.append(t)
            continue
        if _HR_RE.match(line):
            out.append(Text(" " + "─" * 38, style=_RULE))
            continue
        if m := _BULLET_RE.match(line):
            depth = len(m.group(1)) // 2
            glyph = "◦" if depth else "•"
            prefix = Text(" " + "  " * depth + glyph + " ", style=_BULLET)
            out.append(prefix + _linkify(m.group(3)))
            continue
        if not line.strip():
            out.append(Text(""))
            continue

        t = Text(" ")
        t.append_text(_linkify(line))
        out.append(t)

    if in_fence:
        flush_code()

    return out


def _lines_to_text(lines: list[Text]) -> Text:
    if not lines:
        return Text("")
    return Text("\n").join(lines)


def _subprocess_copy(text: str) -> bool:
    """Best-effort subprocess clipboard fallback (local sessions only)."""
    for cmd in (
        ["wl-copy"],
        ["xclip", "-selection", "clipboard"],
        ["xsel", "--clipboard", "--input"],
        ["pbcopy"],
        ["clip"],
    ):
        try:
            p = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            p.communicate(input=text.encode("utf-8"))
            if p.returncode == 0:
                return True
        except FileNotFoundError:
            continue
        except Exception:
            continue
    return False


# ── Per-message body widget (handles note-link clicks) ─────────────────────
class _BodyStatic(Static):
    """Static that resolves Rich `meta` under the mouse for @click actions."""

    def on_click(self, event) -> None:
        style = self.get_style_at(event.x, event.y)
        meta = style.meta if style else None
        if not meta:
            return
        action = meta.get("@click")
        if not action:
            return
        event.stop()
        if action.startswith("app."):
            try:
                self.app.run_action(action[len("app.") :])
            except Exception:
                pass
        else:
            try:
                self.run_action(action)
            except Exception:
                pass


# ── Per-message widget (header + body + optional real copy button) ─────────
class ChatMessage(Widget):
    """One chat bubble: header row (role, timestamp, optional copy button) + body."""

    can_focus = False

    DEFAULT_CSS = """
    ChatMessage {
        height: auto;
        margin: 0 0 1 0;
    }
    ChatMessage .msg-header {
        height: 1;
        layout: horizontal;
    }
    ChatMessage .msg-role {
        width: 1fr;
    }
    ChatMessage .msg-copy-btn {
        min-width: 10;
        width: auto;
        height: 1;
        min-height: 1;
        border: none;
        padding: 0 1;
        background: #1e2030;
        color: #3d59a1;
        content-align: center middle;
    }
    ChatMessage .msg-copy-btn:hover {
        background: #3b4261;
        color: #c0caf5;
    }
    ChatMessage .msg-body {
        padding: 0 0;
        height: auto;
    }
    """

    def __init__(
        self,
        role: str,
        ts: str,
        text: str,
        msg_id: int | None = None,
        show_copy: bool = False,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.role = role
        self.ts = ts
        self.text = text
        self.msg_id = msg_id
        self.show_copy = show_copy

    def compose(self) -> ComposeResult:
        with Horizontal(classes="msg-header"):
            h = Text()
            role_style = (
                Style.parse("#c0caf5 bold")
                if self.role == "you"
                else Style.parse("#7aa2f7 bold")
            )
            h.append(self.role, style=role_style)
            h.append(f" {self.ts}", style=_DIM)
            yield Static(h, classes="msg-role")
            if self.show_copy:
                yield Button(
                    "⎘ copy", id=f"copy-msg-{self.msg_id}", classes="msg-copy-btn"
                )
        yield _BodyStatic(self._render_body(), classes="msg-body")

    def _render_body(self) -> Text:
        return _lines_to_text(_render_markdown(self.text))

    def update_text(self, text: str) -> None:
        self.text = text
        try:
            body = self.query_one(_BodyStatic)
            body.update(self._render_body())
        except Exception:
            pass


# ── AgentPanel ────────────────────────────────────────────────────────────────
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
        padding: 0 1;
        height: 1;
    }
    AgentPanel .title-bar {
        background: #1e2030;
        height: 1;
        layout: horizontal;
    }
    AgentPanel .title-bar .panel-title {
        width: 1fr;
    }
    AgentPanel #copy-last-btn {
        min-width: 12;
        width: auto;
        height: 1;
        min-height: 1;
        border: none;
        padding: 0 1;
        background: #1e2030;
        color: #7aa2f7;
        content-align: center middle;
    }
    AgentPanel #copy-last-btn:hover {
        background: #3b4261;
        color: #c0caf5;
    }
    AgentPanel #output-log {
        background: transparent;
        border: none;
        height: 1fr;
        padding: 0 1;
        scrollbar-color: #3b4261;
        scrollbar-size: 1 1;
    }
    """

    class NoteLinkClicked(Message):
        def __init__(self, filepath: str):
            super().__init__()
            self.filepath = filepath

    _THINK = ["· · ·", "· · ·", "· ·  ", "·    "]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._msg_store: dict[int, str] = {}
        self._msg_counter = 0
        self._think_timer = None
        self._think_frame = 0
        self._think_widget: Static | None = None
        self._live_tools: list[tuple[str, str]] = []
        self._live_tools_widget: Static | None = None
        self._stream_widget: ChatMessage | None = None
        self._stream_idx: int | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(classes="title-bar"):
            yield Static(
                " agent  [dim #3b4261]i=input · h/l=panels · c=copy[/]",
                classes="panel-title",
            )
            yield Button("⎘ copy last", id="copy-last-btn", variant="default")
        yield VerticalScroll(id="output-log")

    # ── keyboard ──────────────────────────────────────────────────────────────
    def on_key(self, event) -> None:
        if event.key == "c" and self._msg_store:
            self._do_copy(max(self._msg_store))

    # ── button routing: copy-last AND per-message copy buttons ────────────────
    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if btn_id == "copy-last-btn":
            event.stop()
            if self._msg_store:
                self._do_copy(max(self._msg_store))
            else:
                self._flash_status("nothing to copy")
            return
        if btn_id.startswith("copy-msg-"):
            event.stop()
            try:
                idx = int(btn_id[len("copy-msg-") :])
            except ValueError:
                return
            self._do_copy(idx)

    def _do_copy(self, idx: int) -> None:
        text = self._msg_store.get(idx, "")
        if not text:
            self._flash_status("nothing to copy")
            return

        ok = _subprocess_copy(text)
        try:
            self.app.copy_to_clipboard(text)
            ok = True
        except Exception:
            pass

        self._flash_status("✓ copied" if ok else "✗ copy failed")

    # ── user message ──────────────────────────────────────────────────────────
    def log_user(self, msg: str) -> None:
        log = self.query_one("#output-log", VerticalScroll)
        ts = datetime.now().strftime("%H:%M")
        log.mount(ChatMessage(role="you", ts=ts, text=msg))
        log.scroll_end(animate=False)

    # ── agent message (non-streaming) ─────────────────────────────────────────
    def log_agent(self, msg: str) -> None:
        self._stop_thinking()
        self._clear_live_tools()
        log = self.query_one("#output-log", VerticalScroll)
        idx = self._next_idx()
        self._msg_store[idx] = msg
        ts = datetime.now().strftime("%H:%M")
        log.mount(
            ChatMessage(role="agent", ts=ts, text=msg, msg_id=idx, show_copy=True)
        )
        log.scroll_end(animate=False)

    # ── thinking loader ───────────────────────────────────────────────────────
    def log_thinking_start(self) -> None:
        log = self.query_one("#output-log", VerticalScroll)
        self._think_frame = 0
        self._think_widget = Static(Text(" " + self._THINK[0], style=_DIM))
        log.mount(self._think_widget)
        log.scroll_end(animate=False)
        self._think_timer = self.set_interval(0.35, self._tick_think)

    def _tick_think(self) -> None:
        if self._think_widget is None:
            return
        self._think_frame = (self._think_frame + 1) % len(self._THINK)
        self._think_widget.update(
            Text(" " + self._THINK[self._think_frame], style=_DIM)
        )

    def _stop_thinking(self) -> None:
        if self._think_timer:
            self._think_timer.stop()
            self._think_timer = None
        if self._think_widget is not None:
            try:
                self._think_widget.remove()
            except Exception:
                pass
            self._think_widget = None

    # ── live tool-call block ──────────────────────────────────────────────────
    def log_tool_call(self, tool_name: str, args: dict) -> None:
        self._stop_thinking()
        self._live_tools.append((tool_name, "…"))
        self._redraw_live_tools()

    def log_tool_result(self, tool_name: str, ok: bool = True) -> None:
        for i in range(len(self._live_tools) - 1, -1, -1):
            if self._live_tools[i][0] == tool_name and self._live_tools[i][1] == "…":
                self._live_tools[i] = (tool_name, "✓" if ok else "✗")
                break
        self._redraw_live_tools()

    def _redraw_live_tools(self) -> None:
        log = self.query_one("#output-log", VerticalScroll)
        lines: list[Text] = []
        for name, status in self._live_tools:
            if status == "…":
                glyph_sty = Style.parse("#e0af68")
            elif status == "✓":
                glyph_sty = Style.parse("#9ece6a")
            else:
                glyph_sty = Style.parse("#f7768e")
            t = Text(" ")
            t.append(status + " ", style=glyph_sty)
            t.append(name, style=_DIM)
            lines.append(t)
        combined = _lines_to_text(lines)
        if self._live_tools_widget is None:
            self._live_tools_widget = Static(combined)
            log.mount(self._live_tools_widget)
        else:
            self._live_tools_widget.update(combined)
        log.scroll_end(animate=False)

    def _clear_live_tools(self) -> None:
        if self._live_tools_widget is not None:
            try:
                self._live_tools_widget.remove()
            except Exception:
                pass
            self._live_tools_widget = None
        self._live_tools.clear()

    def log_tool_calls(self, tool_calls: list[dict]) -> None:
        for tc in tool_calls:
            self.log_tool_call(tc.get("tool", "?"), tc.get("args", {}))

    # ── streaming ─────────────────────────────────────────────────────────────
    def log_stream_start(self) -> None:
        self._stop_thinking()
        self._clear_live_tools()
        log = self.query_one("#output-log", VerticalScroll)
        ts = datetime.now().strftime("%H:%M")
        idx = self._next_idx()
        self._stream_idx = idx
        self._msg_store[idx] = ""
        self._stream_widget = ChatMessage(
            role="agent", ts=ts, text="", msg_id=idx, show_copy=True
        )
        log.mount(self._stream_widget)
        log.scroll_end(animate=False)

    def log_stream_chunk(self, chunk: str) -> None:
        if self._stream_widget is None or self._stream_idx is None:
            return
        self._msg_store[self._stream_idx] += chunk
        self._stream_widget.update_text(self._msg_store[self._stream_idx])
        log = self.query_one("#output-log", VerticalScroll)
        log.scroll_end(animate=False)

    def log_stream_end(self) -> None:
        self._stream_widget = None
        self._stream_idx = None

    # ── misc ──────────────────────────────────────────────────────────────────
    def log_status(self, msg: str) -> None:
        log = self.query_one("#output-log", VerticalScroll)
        log.mount(Static(Text("  " + msg, style=_DIM)))
        log.scroll_end(animate=False)

    def log_message(self, msg: str) -> None:
        log = self.query_one("#output-log", VerticalScroll)
        log.mount(Static(Text(" " + msg)))
        log.scroll_end(animate=False)

    # ── internals ─────────────────────────────────────────────────────────────
    def _next_idx(self) -> int:
        i = self._msg_counter
        self._msg_counter += 1
        return i

    def _flash_status(self, msg: str) -> None:
        log = self.query_one("#output-log", VerticalScroll)
        w = Static(Text("  " + msg, style=Style.parse("#73daca dim")))
        log.mount(w)
        log.scroll_end(animate=False)

        def _erase():
            try:
                w.remove()
            except Exception:
                pass

        self.set_timer(1.5, _erase)
