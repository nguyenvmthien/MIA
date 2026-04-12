"""CLI entrypoint — batch process a meeting audio file directly (no API/Celery needed)."""

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from meeting_agent.pipeline.run import run_pipeline
from meeting_agent.schemas.worker import Worker, WorkerRoster

app = typer.Typer(help="Meeting AI Agent — extract action items from meeting audio")
console = Console()


@app.command()
def process(
    audio: Path = typer.Argument(..., help="Path to audio/video file", exists=True),
    roster: Path = typer.Option(
        None,
        "--roster",
        "-r",
        help="Path to worker roster JSON file",
    ),
    output: Path = typer.Option(
        None,
        "--output",
        "-o",
        help="Save MeetingSummary JSON to this file",
    ),
    meeting_id: str = typer.Option(None, "--id", help="Optional meeting ID (generated if omitted)"),
):
    """Process a meeting audio file and print extracted action items."""
    # Load roster
    if roster and roster.exists():
        with roster.open() as f:
            roster_data = json.load(f)
        worker_roster = WorkerRoster.model_validate(roster_data)
    else:
        console.print("[yellow]No roster provided — assignee resolution will be limited.[/yellow]")
        worker_roster = WorkerRoster()

    console.print(f"[bold cyan]Processing:[/bold cyan] {audio}")
    console.print(f"[dim]Workers in roster: {len(worker_roster.workers)}[/dim]")

    with console.status("[bold green]Running pipeline..."):
        summary = run_pipeline(audio, worker_roster, meeting_id=meeting_id)

    # ── Print summary ─────────────────────────────────────────────────────────
    console.print(f"\n[bold]Meeting ID:[/bold] {summary.meeting_id}")
    console.print(f"[bold]Status:[/bold] {summary.job_status}")
    console.print(f"[bold]Participants:[/bold] {', '.join(summary.participants)}")
    if summary.duration_ms:
        console.print(f"[bold]Duration:[/bold] {summary.duration_ms // 60000} min")

    if summary.summary_text:
        console.print("\n[bold underline]Summary[/bold underline]")
        console.print(summary.summary_text)

    # ── Print action items table ──────────────────────────────────────────────
    all_tasks = summary.action_items + summary.unresolved_items + summary.human_review_items
    if all_tasks:
        table = Table(title="\nExtracted Action Items", show_lines=True)
        table.add_column("#", style="dim", width=3)
        table.add_column("Description")
        table.add_column("Assignee", style="cyan")
        table.add_column("Due Date", style="green")
        table.add_column("Priority", style="yellow")
        table.add_column("Status", style="magenta")

        for i, task in enumerate(all_tasks, 1):
            table.add_row(
                str(i),
                task.description,
                task.assignee or "[dim]unassigned[/dim]",
                str(task.due_date) if task.due_date else "[dim]none[/dim]",
                task.priority.value,
                task.status.value,
            )
        console.print(table)
    else:
        console.print("\n[dim]No action items extracted.[/dim]")

    # ── Metrics ───────────────────────────────────────────────────────────────
    m = summary.run_metrics
    console.print(
        f"\n[dim]Tokens used: {m.total_tokens_used} | "
        f"Tasks: {m.tasks_extracted} | "
        f"Unresolved: {m.tasks_unresolved} | "
        f"Human review: {m.tasks_human_review} | "
        f"Total time: {m.stage_timings.total_ms // 1000}s[/dim]"
    )

    # ── Save output ───────────────────────────────────────────────────────────
    if output:
        output.write_text(summary.model_dump_json(indent=2))
        console.print(f"\n[green]Saved to {output}[/green]")


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Bind host"),
    port: int = typer.Option(8000, help="Bind port"),
    reload: bool = typer.Option(False, help="Enable auto-reload (dev mode)"),
):
    """Start the FastAPI server."""
    import uvicorn
    uvicorn.run(
        "meeting_agent.api.main:app",
        host=host,
        port=port,
        reload=reload,
    )


if __name__ == "__main__":
    app()
