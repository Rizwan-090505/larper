from textual.widget import Widget
from textual.app import ComposeResult
from textual.widgets import Static, RichLog
from textual.reactive import reactive


class AgentPanel(Widget):
    """Main output/content panel — UI container only."""

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
        yield Static("  ⚡ OUTPUT", classes="panel-title")
        yield RichLog(id="output-log", highlight=True, markup=True, wrap=True)

    def on_mount(self):
        log = self.query_one("#output-log", RichLog)
        log.write("[dim]DevWorkspace ready.[/dim]")
        log.write("[dim]Open a note or type a command below.[/dim]")
        log.write("")
        log.write("[bold]Commands:[/bold]")
        log.write("  [green]add task[/green] [white]<text>[/white]")
        log.write("  [yellow]add event[/yellow] [white]<text>[/white] [dim]at HH:MM[/dim]")

    def log_message(self, msg: str):
        log = self.query_one("#output-log", RichLog)
        log.write(msg)

    def log_item_added(self, kind: str, text: str, time: str = ""):
        log = self.query_one("#output-log", RichLog)
        if kind == "task":
            log.write(f"[green]✓ Task added:[/green] {text}")
        elif kind == "event":
            log.write(f"[yellow]◷ Event added:[/yellow] {text} [dim]at {time}[/dim]")
        elif kind == "error":
            log.write(f"[red]✗ {text}[/red]")