from textual.widget import Widget
from textual.app import ComposeResult
from textual.widgets import Static, RichLog
from datetime import datetime
import asyncio


class AgentPanel(Widget):
    """Chat-style panel — user messages + agent replies."""
    can_focus = True

    DEFAULT_CSS = """
    AgentPanel {
        height: 1fr;
        border: solid $primary;
        background: $surface;
    }
    AgentPanel .panel-title {
        background: $primary;
        color: $text;
        padding: 0 1;
        height: 1;
        text-style: bold;
    }
    AgentPanel RichLog {
        background: transparent;
        border: none;
        height: 1fr;
        padding: 0 1;
        scrollbar-color: $accent;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("  AGENT", classes="panel-title")
        yield RichLog(id="output-log", highlight=True, markup=True, wrap=True)

    def on_mount(self):
        log = self.query_one("#output-log", RichLog)
        log.write("")
        log.write("[bold cyan]  Personal manager ready[/bold cyan]")
        log.write("[dim]  ─────────────────────────────────────[/dim]")
        log.write("")
        log.write("  Type naturally to capture notes, tasks, events, or ask local questions.")
        log.write("")
        log.write("  [green]remind me to renew passport tomorrow #admin[/green]")
        log.write("  [yellow]meeting with Sam Friday at 14:00 #work[/yellow]")
        log.write("  [cyan]what do I know about the migration plan?[/cyan]")
        log.write("")
        log.write("  [dim]Esc[/dim] workspace  [dim]hjkl[/dim] panes  [dim]Shift-H/L[/dim] tabs  [dim]x[/dim] close  [dim]m[/dim] minimize")
        log.write("  [dim]g n[/dim] new page  [dim]g j[/dim] journal  [dim]Ctrl-I[/dim] input")
        log.write("")
        log.write("[dim]  ─────────────────────────────────────[/dim]")
        log.write("")

    def log_user(self, msg: str):
        log = self.query_one("#output-log", RichLog)
        ts = datetime.now().strftime("%H:%M")
        log.write(f"  [bold white]You[/bold white] [dim]{ts}[/dim]")
        log.write(f"  [white]  {msg}[/white]")
        log.write("")

    def log_agent(self, msg: str):
        log = self.query_one("#output-log", RichLog)
        ts = datetime.now().strftime("%H:%M")
        log.write(f"  [bold cyan]Agent[/bold cyan] [dim]{ts}[/dim]")
        log.write(f"  [cyan]  {msg}[/cyan]")
        log.write("")

    def log_message(self, msg: str):
        log = self.query_one("#output-log", RichLog)
        log.write(f"  {msg}")
        log.write("")
