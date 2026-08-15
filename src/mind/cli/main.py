"""MIND command line interface.

Commands:

    mind discover <topic>          Create a project and run the discovery pipeline.
    mind projects                  List projects.
    mind serve                     Start the API server.
    mind status                    Report runtime status (GPU, runtime, model).
    mind sources list              List sources for a project.
    mind sources show <id>         Show a single source.
    mind sources accepted          Show accepted sources.
    mind sources review            Show sources pending review.
    mind sources rejected          Show rejected sources.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from mind import __version__
from mind.config import load_settings
from mind.pipeline import STAGES, DiscoveryPipeline
from mind.storage import Storage, project_stats

app = typer.Typer(name="mind", help="MIND - knowledge mastery platform (Phase 1)")
console = Console()
sources_app = typer.Typer(help="Inspect discovered sources.")
app.add_typer(sources_app, name="sources")


def _storage() -> Storage:
    return Storage(load_settings().paths.data_dir)


@app.command()
def discover(
    topic: str,
    max_sources: int = typer.Option(None, help="Override candidate source cap."),
    offline: bool = typer.Option(
        False, "--offline", help="Use the offline fixture search provider."
    ),
) -> None:
    """Create a project from a topic and run the full Phase 1 pipeline."""
    settings = load_settings()
    if offline:
        settings.search.provider = "offline"
    if max_sources:
        settings.project.max_sources = max_sources
        settings.cli.max_discover_sources = max_sources

    storage = Storage(settings.paths.data_dir)
    try:
        project = storage.create_project(topic)
    except ValueError as exc:
        console.print(f"[yellow]{exc}[/yellow]")
        console.print("Use a distinct topic, or delete the existing project first.")
        raise typer.Exit(code=1) from exc

    console.rule(f"Topic: {topic}")
    pipeline = DiscoveryPipeline(settings)
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold]{task.description}[/bold]"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        total_stages = len(STAGES)
        task = progress.add_task("Discovery", total=total_stages)

        def poll():
            run = storage.get_latest_run(project["id"])
            if not run:
                return
            stages = json.loads(run.get("stages") or "[]")
            done = sum(1 for s in stages if s["status"] in ("completed", "failed", "skipped"))
            label = next((s["label"] for s in stages if s["status"] == "running"), "Working")
            progress.update(task, completed=done, description=label)

        # run in a thread so the progress bar can poll the DB
        import threading

        result: dict = {}

        def runner():
            try:
                result["run"] = pipeline.run(project["slug"])
            except Exception as exc:
                result["error"] = exc

        t = threading.Thread(target=runner, daemon=True)
        t.start()
        while t.is_alive():
            poll()
            progress.refresh()
            t.join(timeout=0.25)
        poll()

    if result.get("error"):
        console.print(f"[red]Discovery failed: {result['error']}[/red]")
        raise typer.Exit(code=1)

    _print_stats(project["id"], storage)


def _print_stats(project_id: int, storage: Storage) -> None:
    stats = project_stats(storage, project_id)
    table = Table(title="Results", show_header=False, pad_edge=False)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="bold")
    for label, value in (
        ("Search results discovered", stats.search_results),
        ("Candidate documents", stats.candidates),
        ("Downloaded", stats.downloaded),
        ("Valid PDFs", stats.valid_pdfs),
        ("Duplicates removed", stats.duplicates_removed),
        ("Text extracted", stats.text_extracted),
        ("OCR required", stats.ocr_required),
        ("Accepted", stats.accepted),
        ("Review", stats.review),
        ("Rejected", stats.rejected),
    ):
        table.add_row(label, str(value))
    console.print(table)


@app.command("projects")
def projects() -> None:
    """List all MIND projects."""
    storage = _storage()
    rows = storage.list_projects()
    if not rows:
        console.print('No projects yet. Run: [bold]mind discover "<topic>"[/bold]')
        return
    table = Table(title="Projects")
    table.add_column("Slug", style="cyan")
    table.add_column("Topic")
    table.add_column("Status")
    table.add_column("Accepted", justify="right")
    table.add_column("Review", justify="right")
    table.add_column("Rejected", justify="right")
    for row in rows:
        stats = project_stats(storage, row["id"])
        table.add_row(
            row["slug"],
            row["topic"],
            row["status"],
            str(stats.accepted),
            str(stats.review),
            str(stats.rejected),
        )
    console.print(table)


@sources_app.command("list")
def sources_list(
    project: str = typer.Option(..., "--project", "-p", help="Project slug."),
    status: str = typer.Option(None, "--status", "-s"),
    decision: str = typer.Option(None, "--decision", "-d"),
    limit: int = typer.Option(100),
) -> None:
    """List sources for a project."""
    storage = _storage()
    proj = storage.get_project_by_slug(project)
    if not proj:
        console.print(f"[red]Unknown project: {project}[/red]")
        raise typer.Exit(code=1)
    rows = storage.list_sources(proj["id"], status=status, decision=decision, limit=limit)
    if not rows:
        console.print("No sources match.")
        return
    table = Table(title=f"Sources - {project}")
    table.add_column("ID", justify="right", style="dim")
    table.add_column("Title")
    table.add_column("Domain", style="dim")
    table.add_column("Status")
    table.add_column("Decision", style="bold")
    table.add_column("Conf", justify="right")
    for row in rows:
        conf = f"{row['ai_confidence']:.2f}" if row["ai_confidence"] is not None else "-"
        table.add_row(
            str(row["id"]),
            (row["title"] or row["url"])[:60],
            row["source_domain"],
            row["status"],
            row["ai_decision"] or "-",
            conf,
        )
    console.print(table)


@sources_app.command("show")
def sources_show(
    project: str = typer.Option(..., "--project", "-p", help="Project slug."),
    source_id: int = typer.Argument(..., help="Source id."),
    content: bool = typer.Option(False, "--content", help="Print extracted Markdown."),
) -> None:
    """Show a single source in detail."""
    storage = _storage()
    proj = storage.get_project_by_slug(project)
    if not proj:
        console.print(f"[red]Unknown project: {project}[/red]")
        raise typer.Exit(code=1)
    src = storage.get_source(source_id)
    if not src or src["project_id"] != proj["id"]:
        console.print(f"[red]Unknown source: {source_id}[/red]")
        raise typer.Exit(code=1)
    console.print(json.dumps(_source_view(src), indent=2, ensure_ascii=False))
    if content and src.get("processed_path"):
        p = Path(src["processed_path"])
        if p.exists():
            console.print(p.read_text(encoding="utf-8")[:4000])


def _source_view(src: dict) -> dict:
    fields = [
        "id",
        "title",
        "url",
        "source_domain",
        "search_query",
        "status",
        "rejection_reason",
        "file_hash",
        "page_count",
        "language",
        "text_chars",
        "extraction_method",
        "similarity",
        "ai_decision",
        "ai_confidence",
        "ai_document_type",
        "ai_topic_match",
        "ai_reason",
        "note",
        "embedding_stage",
    ]
    return {k: src.get(k) for k in fields}


def _print_decision_sources(project: str, decision: str) -> None:
    storage = _storage()
    proj = storage.get_project_by_slug(project)
    if not proj:
        console.print(f"[red]Unknown project: {project}[/red]")
        raise typer.Exit(code=1)
    rows = storage.list_sources(proj["id"], decision=decision)
    if not rows:
        console.print(f"No {decision.lower()} sources.")
        return
    for row in rows:
        conf = f"{row['ai_confidence']:.2f}" if row["ai_confidence"] is not None else "-"
        console.print(f"[cyan]{row['id']:>4}[/cyan]  {conf}  {(row['title'] or row['url'])[:90]}")


@sources_app.command("accepted")
def sources_accepted(project: str = typer.Option(..., "--project", "-p")) -> None:
    """List accepted sources."""
    _print_decision_sources(project, "ACCEPT")


@sources_app.command("review")
def sources_review(project: str = typer.Option(..., "--project", "-p")) -> None:
    """List sources pending review."""
    _print_decision_sources(project, "REVIEW")


@sources_app.command("rejected")
def sources_rejected(project: str = typer.Option(..., "--project", "-p")) -> None:
    """List rejected sources."""
    _print_decision_sources(project, "REJECT")


@app.command("serve")
def serve(
    host: str = typer.Option(None, help="Bind host."),
    port: int = typer.Option(None, help="Bind port."),
    reload: bool = typer.Option(False, "--reload", help="Enable auto-reload."),
) -> None:
    """Start the MIND API server."""
    import uvicorn

    settings = load_settings()
    host = host or settings.api.host
    port = port or settings.api.port
    console.print(f"MIND API server starting at http://{host}:{port}")
    uvicorn.run("mind.api.main:app", host=host, port=port, reload=reload)


@app.command("status")
def status() -> None:
    """Report runtime status: local AI runtime, model, storage."""
    from mind.runtime import runtime_report

    report = runtime_report()
    table = Table(title="MIND Runtime Status")
    for key, value in report.items():
        table.add_row(key, str(value))
    console.print(table)


@app.command("delete")
def delete(project: str) -> None:
    """Delete a project and all its data."""
    storage = _storage()
    if storage.delete_project(project):
        console.print(f"Deleted project '{project}'.")
    else:
        console.print(f"[red]Unknown project: {project}[/red]")
        raise typer.Exit(code=1)


@app.command()
def version() -> None:
    """Show MIND version."""
    console.print(f"MIND {__version__}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
