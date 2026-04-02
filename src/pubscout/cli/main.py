"""PubScout CLI — entry point for the ``pubscout`` command."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from pubscout.core.profile import (
    create_default_profile,
    get_profile_path,
    load_profile,
    save_profile,
)
from pubscout.core.pipeline import ScanPipeline
from pubscout.storage.database import PubScoutDB

console = Console()


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def cli(verbose: bool) -> None:
    """PubScout — AI-powered publication scanner."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


@cli.command()
def init() -> None:
    """Initialize PubScout with default profile.

    Creates ~/.pubscout/profile.yaml with:
    - 6 default domain queries (LLM inference research)
    - arXiv as default source
    - Default LLM config (gpt-4o-mini)
    - Default scoring threshold (5.0)

    For v1, this is a non-interactive setup.  User can edit profile.yaml
    directly.  Future: interactive wizard (User Story 1).
    """
    profile_path = get_profile_path()
    if profile_path.exists():
        console.print(f"[yellow]Profile already exists at {profile_path}[/yellow]")
        console.print("Edit it directly or delete and re-run init.")
        return

    profile = create_default_profile()
    save_profile(profile, profile_path)
    console.print(f"[green]✓ Profile created at {profile_path}[/green]")
    console.print(f"  Domains: {len(profile.domains)} configured")
    console.print(f"  Sources: {len(profile.sources)} configured")
    console.print("\nEdit the profile to customize domains, add API keys, etc.")
    console.print("[bold]Then run: pubscout scan --dry-run[/bold]")


@cli.command()
@click.option("--dry-run", is_flag=True, help="Save report to file instead of sending email")
@click.option("--profile", "-p", type=click.Path(exists=True), help="Path to profile.yaml")
def scan(dry_run: bool, profile: str | None) -> None:
    """Run a publication scan.

    Fetches publications from configured sources, scores for relevance,
    and generates an HTML report.
    """
    try:
        profile_path = Path(profile) if profile else get_profile_path()
        user_profile = load_profile(profile_path)
    except FileNotFoundError:
        console.print("[red]No profile found. Run 'pubscout init' first.[/red]")
        sys.exit(1)

    if not user_profile.llm.api_key:
        console.print(
            "[yellow]Warning: No LLM API key configured. Using keyword-only scoring.[/yellow]"
        )

    db = PubScoutDB()
    pipeline = ScanPipeline(user_profile, db)

    console.print("[bold]Starting scan...[/bold]")
    scan_run = pipeline.run(dry_run=dry_run)

    # Display results
    console.print()
    table = Table(title="Scan Results")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Sources checked", str(scan_run.sources_checked))
    table.add_row("Items fetched", str(scan_run.items_fetched))
    table.add_row("Items scored", str(scan_run.items_scored))
    table.add_row("Items reported", str(scan_run.items_reported))
    table.add_row("Duration", f"{scan_run.duration_seconds:.1f}s")
    if scan_run.errors:
        table.add_row("Errors", str(len(scan_run.errors)))
    console.print(table)

    if dry_run:
        console.print("\n[yellow]Dry run — report saved to ~/.pubscout/reports/[/yellow]")


@cli.command()
@click.option("--profile", "-p", type=click.Path(exists=True), help="Path to profile.yaml")
def sources(profile: str | None) -> None:
    """List configured sources."""
    try:
        profile_path = Path(profile) if profile else get_profile_path()
        user_profile = load_profile(profile_path)
    except FileNotFoundError:
        console.print("[red]No profile found. Run 'pubscout init' first.[/red]")
        sys.exit(1)

    table = Table(title="Configured Sources")
    table.add_column("Label", style="cyan")
    table.add_column("Type", style="green")
    table.add_column("URL")
    table.add_column("Enabled", style="yellow")
    table.add_column("Default")

    for src in user_profile.sources:
        table.add_row(
            src.label,
            src.type,
            src.url,
            "✓" if src.enabled else "✗",
            "✓" if src.default else "",
        )
    console.print(table)


@cli.command()
@click.option("--profile", "-p", type=click.Path(exists=True), help="Path to profile.yaml")
def domains(profile: str | None) -> None:
    """List configured domain queries."""
    try:
        profile_path = Path(profile) if profile else get_profile_path()
        user_profile = load_profile(profile_path)
    except FileNotFoundError:
        console.print("[red]No profile found. Run 'pubscout init' first.[/red]")
        sys.exit(1)

    table = Table(title="Configured Domains")
    table.add_column("#", style="dim")
    table.add_column("Label", style="cyan")
    table.add_column("Enabled", style="yellow")
    table.add_column("Query", max_width=60)

    for i, domain in enumerate(user_profile.domains, 1):
        query_display = (
            domain.query[:57] + "..." if len(domain.query) > 60 else domain.query
        )
        table.add_row(str(i), domain.label, "✓" if domain.enabled else "✗", query_display)
    console.print(table)


@cli.command()
def history() -> None:
    """Show scan history."""
    db = PubScoutDB()
    runs = db.get_scan_runs(limit=10)

    if not runs:
        console.print("[yellow]No scan history yet. Run 'pubscout scan' first.[/yellow]")
        return

    table = Table(title="Scan History (last 10)")
    table.add_column("Date", style="cyan")
    table.add_column("Sources")
    table.add_column("Fetched")
    table.add_column("Scored")
    table.add_column("Reported", style="green")
    table.add_column("Duration")
    table.add_column("Errors", style="red")

    for run in runs:
        table.add_row(
            run.timestamp.strftime("%Y-%m-%d %H:%M"),
            str(run.sources_checked),
            str(run.items_fetched),
            str(run.items_scored),
            str(run.items_reported),
            f"{run.duration_seconds:.1f}s" if run.duration_seconds else "—",
            str(len(run.errors)) if run.errors else "0",
        )
    console.print(table)
