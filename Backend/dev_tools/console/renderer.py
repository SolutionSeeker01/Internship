# Backend/dev_tools/console/renderer.py
"""
Console Renderer — Pure Rich Layout Builder

Takes a snapshot of ConsoleState and constructs a beautiful, flicker-free
Rich Layout tree matching the canonical DVC design specification.
"""

from datetime import datetime
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.align import Align


def make_layout(snapshot: dict) -> Layout:
    """
    Constructs the 6-panel Rich Layout tree from a ConsoleState snapshot.
    """
    layout = Layout()

    # Split main layout vertically into Header, Body, and Footer/Logs
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="waiting", size=3),
        Layout(name="main_body", ratio=2),
        Layout(name="recent_logs", size=8)
    )

    # Split main body horizontally into Timeline (Left) and Trade/Exceptions (Right)
    layout["main_body"].split_row(
        Layout(name="timeline", ratio=3),
        Layout(name="side_panel", ratio=2)
    )

    layout["side_panel"].split_column(
        Layout(name="active_trade", ratio=1),
        Layout(name="exceptions", ratio=1)
    )

    # 1. Header Panel
    uptime = snapshot["uptime"]
    total_events = snapshot["total_events"]
    clock = datetime.now().strftime("%H:%M:%S IST")
    header_text = f"[bold green]ENGINE:[/bold green] ACTIVE  |  [bold green]ZERODHA:[/bold green] OK  |  [bold cyan]EVENTS PROCESSED:[/bold cyan] {total_events}  |  [bold yellow]UPTIME:[/bold yellow] {uptime}  |  [bold white]{clock}[/bold white]"
    layout["header"].update(Panel(Align.center(Text.from_markup(header_text)), style="bold white on blue"))

    # 2. Waiting Banner
    waiting_msg = snapshot["waiting_state"]
    if "❌" in waiting_msg or "HALTED" in waiting_msg:
        banner_style = "bold white on red"
    elif "COMPLETED" in waiting_msg:
        banner_style = "bold white on green"
    else:
        banner_style = "bold black on yellow"
    layout["waiting"].update(Panel(Align.center(Text(waiting_msg, style="bold")), style=banner_style))

    # 3. Persistent 11-Stage Timeline
    timeline_table = Table(box=None, expand=True, show_header=True, header_style="bold cyan")
    timeline_table.add_column("State", width=3, justify="center")
    timeline_table.add_column("Stage / Milestone", ratio=2)
    timeline_table.add_column("Time", width=12, justify="right")
    timeline_table.add_column("Details", ratio=2)

    for item in snapshot["timeline"]:
        status = item["status"]
        if status == "COMPLETED":
            icon = "[bold green]✅[/bold green]"
            style = "green"
        elif status == "RUNNING":
            icon = "[bold yellow]🔄[/bold yellow]"
            style = "yellow"
        elif status == "FAILED":
            icon = "[bold red]❌[/bold red]"
            style = "bold red"
        else:
            icon = "[bold dim]⏳[/bold dim]"
            style = "dim"

        timeline_table.add_row(
            Text.from_markup(icon),
            Text(item["label"], style=style),
            Text(item["timestamp"], style="dim"),
            Text(item["detail"], style="italic " + style)
        )
    layout["timeline"].update(Panel(timeline_table, title="[bold white]PERSISTENT EXECUTION TIMELINE[/bold white]", border_style="cyan"))

    # 4. Active Trade Panel
    trade = snapshot["active_trade"]
    if trade:
        trade_table = Table.grid(padding=(0, 1))
        trade_table.add_column(style="bold white")
        trade_table.add_column(style="cyan")
        trade_table.add_row("Symbol:", trade.get("symbol", "-"))
        trade_table.add_row("Action:", trade.get("action", "-"))
        trade_table.add_row("Intended Entry:", f"₹{trade.get('entry', 0.0):.2f}")
        trade_table.add_row("Stop Loss:", f"₹{trade.get('sl', 0.0):.2f}")
        trade_table.add_row("Sized Quantity:", f"{trade.get('quantity', 0)} shares")
        trade_table.add_row("Broker Order ID:", trade.get("broker_order_id", "-"))
        trade_table.add_row("Trade Status:", f"[yellow]{trade.get('status', '-')}[/yellow]")
        layout["active_trade"].update(Panel(trade_table, title="[bold white]ACTIVE TRADE METRICS[/bold white]", border_style="green"))
    else:
        layout["active_trade"].update(Panel(Align.center(Text("No Active Trade", style="dim")), title="[bold white]ACTIVE TRADE METRICS[/bold white]", border_style="dim"))

    # 5. Exception Panel
    exceptions = snapshot["exceptions"]
    if exceptions:
        err_table = Table(box=None, expand=True, show_header=False)
        err_table.add_column("Time", width=10, style="dim")
        err_table.add_column("Details", style="bold red")
        for err in exceptions:
            err_table.add_row(err["timestamp"], f"{err['event_type']} ({err['reason']})")
        layout["exceptions"].update(Panel(err_table, title="[bold red]EXCEPTION & REJECTION HISTORY[/bold red]", border_style="red"))
    else:
        layout["exceptions"].update(Panel(Align.center(Text("No Exceptions / Rejections", style="dim green")), title="[bold white]EXCEPTION HISTORY[/bold white]", border_style="green"))

    # 6. Recent Logs Stream
    logs_table = Table(box=None, expand=True, show_header=True, header_style="bold yellow")
    logs_table.add_column("Timestamp", width=12, style="dim")
    logs_table.add_column("Component", width=18, style="cyan")
    logs_table.add_column("Event Type", width=26, style="bold white")
    logs_table.add_column("Payload Summary", ratio=1)

    for log in snapshot["recent_logs"]:
        sev = log["severity"]
        evt_style = "bold red" if sev == "ERROR" else "white"
        logs_table.add_row(
            log["timestamp"],
            log["component"],
            Text(log["event_type"], style=evt_style),
            Text(str(log["payload"]), style="dim")
        )
    layout["recent_logs"].update(Panel(logs_table, title="[bold white]RECENT TELEMETRY EVENT STREAM[/bold white]", border_style="yellow"))

    return layout
