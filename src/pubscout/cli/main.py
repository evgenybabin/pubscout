"""PubScout CLI — entry point for the ``pubscout`` command."""

from __future__ import annotations

import logging
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from pubscout.core.models import Domain, EmailConfig, Source
from pubscout.core.profile import (
    DEFAULT_DOMAINS,
    DEFAULT_SOURCES,
    create_default_profile,
    get_profile_path,
    load_profile,
    save_profile,
)
from pubscout.core.pipeline import ScanPipeline
from pubscout.storage.database import PubScoutDB

console = Console()


# ── Helpers ──────────────────────────────────────────────────────────


def _load_or_exit(profile_opt: str | None) -> tuple:
    """Load profile and return (profile, path) or exit with message."""
    try:
        path = Path(profile_opt) if profile_opt else get_profile_path()
        return load_profile(path), path
    except FileNotFoundError:
        console.print("[red]No profile found. Run 'pubscout init' first.[/red]")
        sys.exit(1)


# ── Top-level CLI ────────────────────────────────────────────────────


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def cli(verbose: bool) -> None:
    """PubScout — AI-powered publication scanner."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


# ── init ─────────────────────────────────────────────────────────────


@cli.command()
@click.option("--non-interactive", is_flag=True, help="Skip interactive prompts")
@click.option("--sources-file", type=click.Path(exists=True), help="Import URLs from file")
def init(non_interactive: bool, sources_file: str | None) -> None:
    """Initialize PubScout with a profile.

    Interactive by default.  Use --non-interactive for automated setup.
    """
    profile_path = get_profile_path()
    if profile_path.exists():
        if non_interactive:
            console.print(f"[yellow]Profile already exists at {profile_path}[/yellow]")
            return
        if not click.confirm("Profile already exists. Overwrite?", default=False):
            return

    if non_interactive:
        profile = create_default_profile()
    else:
        profile = _interactive_init(sources_file)

    save_profile(profile, profile_path)
    console.print(f"\n[green]✓ Profile created at {profile_path}[/green]")
    console.print(f"  Domains: {len(profile.domains)} configured")
    console.print(f"  Sources: {len(profile.sources)} configured")
    console.print("\n[bold]Next: pubscout scan --dry-run[/bold]")


def _interactive_init(sources_file: str | None) -> "UserProfile":
    """Run the interactive init wizard."""
    from pubscout.core.models import LLMConfig, ScoringConfig, UserProfile

    # Step 1: Domains
    console.print("\n[bold]Step 1: Research Domains[/bold]")
    console.print("Default domains:")
    for i, d in enumerate(DEFAULT_DOMAINS, 1):
        console.print(f"  {i}. {d.label}")
    disable_input = click.prompt(
        "Enter numbers to DISABLE (comma-separated, blank to keep all)",
        default="",
        show_default=False,
    )
    disabled_indices = set()
    if disable_input.strip():
        for part in disable_input.split(","):
            try:
                disabled_indices.add(int(part.strip()) - 1)
            except ValueError:
                pass
    domains = []
    for i, d in enumerate(DEFAULT_DOMAINS):
        domains.append(Domain(label=d.label, query=d.query, enabled=i not in disabled_indices))

    # Step 2: Sources
    console.print("\n[bold]Step 2: Publication Sources[/bold]")
    console.print("Default sources:")
    for i, s in enumerate(DEFAULT_SOURCES, 1):
        console.print(f"  {i}. {s.label} ({s.url})")
    src_disable = click.prompt(
        "Enter numbers to DISABLE (comma-separated, blank to keep all)",
        default="",
        show_default=False,
    )
    disabled_src = set()
    if src_disable.strip():
        for part in src_disable.split(","):
            try:
                disabled_src.add(int(part.strip()) - 1)
            except ValueError:
                pass
    sources_list = []
    for i, s in enumerate(DEFAULT_SOURCES):
        src_copy = s.model_copy(update={"enabled": i not in disabled_src})
        sources_list.append(src_copy)

    # Step 3: Custom URLs
    if sources_file:
        file_urls = Path(sources_file).read_text().strip().splitlines()
        for url in file_urls:
            url = url.strip()
            if url and url.startswith("http"):
                sources_list.append(
                    Source(
                        label=url.split("//")[1].split("/")[0],
                        type="rss",
                        url=url,
                        adapter="rss",
                        enabled=True,
                        user_added=True,
                        added_date=datetime.now(timezone.utc).isoformat(),
                    )
                )
    else:
        console.print("\n[bold]Step 3: Custom Sources[/bold]")
        console.print("Enter URLs one at a time (blank to finish):")
        while True:
            url = click.prompt("URL", default="", show_default=False)
            if not url:
                break
            sources_list.append(
                Source(
                    label=url.split("//")[1].split("/")[0] if "//" in url else url,
                    type="rss",
                    url=url,
                    adapter="rss",
                    enabled=True,
                    user_added=True,
                    added_date=datetime.now(timezone.utc).isoformat(),
                )
            )

    # Step 4: Email
    console.print("\n[bold]Step 4: Email Delivery[/bold]")
    email_addr = click.prompt("Email address (blank to skip)", default="", show_default=False)
    if email_addr:
        smtp_host = click.prompt("SMTP host", default="smtp.gmail.com")
        smtp_port = click.prompt("SMTP port", default=587, type=int)
        email_cfg = EmailConfig(
            transport="smtp",
            from_addr=email_addr,
            to_addr=email_addr,
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_use_tls=True,
            smtp_username=email_addr,
            smtp_password_env="PUBSCOUT_SMTP_PASSWORD",
        )
    else:
        email_cfg = EmailConfig()

    # Step 5: LLM
    console.print("\n[bold]Step 5: LLM Configuration[/bold]")
    console.print("Recommended: set OPENAI_API_KEY env var.")
    model = click.prompt("Model name", default="gpt-4o-mini")

    return UserProfile(
        domains=domains,
        sources=sources_list,
        email=email_cfg,
        llm=LLMConfig(provider="openai", model=model),
        scoring=ScoringConfig(threshold=5.0),
        version=2,
    )


# ── scan ─────────────────────────────────────────────────────────────


@cli.command()
@click.option("--dry-run", is_flag=True, help="Save report to file, skip email")
@click.option("--no-email", is_flag=True, help="Skip email delivery")
@click.option("--days", type=int, default=None, help="Scan range in days (default: from profile, typically 7)")
@click.option("--timeout", type=int, default=30, help="HTTP timeout per source (seconds)")
@click.option("--profile", "-p", type=click.Path(exists=True), help="Path to profile.yaml")
def scan(dry_run: bool, no_email: bool, days: int | None, timeout: int, profile: str | None) -> None:
    """Run a publication scan."""
    user_profile, _ = _load_or_exit(profile)

    if not user_profile.llm.api_key:
        console.print(
            "[yellow]Warning: No LLM API key configured. Using keyword-only scoring.[/yellow]"
        )

    effective_days = days if days is not None else user_profile.scan_range_days
    console.print(f"[dim]Scan range: last {effective_days} day(s)[/dim]")

    db = PubScoutDB()
    pipeline = ScanPipeline(user_profile, db)

    console.print("[bold]Starting scan...[/bold]")
    scan_run = pipeline.run(dry_run=dry_run, send_email=not no_email, scan_range_days=days)

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
        console.print(
            "[dim]Rate papers with 👍/👎 in the report, then save & import:[/dim]\n"
            "[dim]  pubscout feedback import feedback.json[/dim]"
        )


# ── sources ──────────────────────────────────────────────────────────


@cli.group(invoke_without_command=True)
@click.option("--profile", "-p", type=click.Path(exists=True), help="Path to profile.yaml")
@click.pass_context
def sources(ctx: click.Context, profile: str | None) -> None:
    """Manage publication sources."""
    ctx.ensure_object(dict)
    ctx.obj["profile_opt"] = profile
    if ctx.invoked_subcommand is None:
        _sources_list(profile)


def _sources_list(profile_opt: str | None) -> None:
    user_profile, _ = _load_or_exit(profile_opt)
    table = Table(title="Configured Sources")
    table.add_column("Label", style="cyan")
    table.add_column("Type", style="green")
    table.add_column("URL")
    table.add_column("Enabled", style="yellow")
    table.add_column("Default")
    for src in user_profile.sources:
        table.add_row(
            src.label, src.type, src.url,
            "✓" if src.enabled else "✗",
            "✓" if src.default else "",
        )
    console.print(table)


@sources.command("add")
@click.argument("url")
@click.option("--name", default=None, help="Display name for the source")
@click.option("--type", "src_type", type=click.Choice(["api", "rss", "web"]), default=None)
@click.option("--no-detect", is_flag=True, help="Skip auto-detection probe")
@click.pass_context
def sources_add(ctx: click.Context, url: str, name: str | None, src_type: str | None, no_detect: bool) -> None:
    """Add a new source URL."""
    user_profile, profile_path = _load_or_exit(ctx.obj.get("profile_opt"))

    # Check duplicate
    if any(s.url == url for s in user_profile.sources):
        console.print(f"[yellow]Source URL already exists: {url}[/yellow]")
        return

    detected_type = src_type or "rss"
    adapter = "rss"
    if not no_detect and not src_type:
        console.print(f"Probing {url}...")
        from pubscout.core.source_detect import detect_source_type
        result = detect_source_type(url)
        detected_type = result.source_type
        adapter = detected_type
        if result.reachable:
            console.print(f"  Detected: {detected_type}")
            if result.feed_title:
                console.print(f"  Feed title: {result.feed_title}")
                if not name:
                    name = result.feed_title
        else:
            console.print(f"  [yellow]URL unreachable: {result.error}[/yellow]")

    if detected_type == "api":
        adapter = "web"  # generic fallback
    elif detected_type == "web":
        adapter = "web"

    label = name or url.split("//")[1].split("/")[0] if "//" in url else url
    new_source = Source(
        label=label,
        type=detected_type,
        url=url,
        adapter=adapter,
        enabled=True,
        user_added=True,
        added_date=datetime.now(timezone.utc).isoformat(),
    )
    user_profile.sources.append(new_source)
    save_profile(user_profile, profile_path)
    console.print(f"[green]✓ Added source: {label}[/green]")


@sources.command("remove")
@click.argument("label")
@click.pass_context
def sources_remove(ctx: click.Context, label: str) -> None:
    """Remove a source by label (case-insensitive, partial match on label or URL)."""
    user_profile, profile_path = _load_or_exit(ctx.obj.get("profile_opt"))
    needle = label.lower()
    matched = [s for s in user_profile.sources if needle in s.label.lower() or needle in s.url.lower()]
    if not matched:
        console.print(f"[red]Source '{label}' not found[/red]")
        labels = [s.label for s in user_profile.sources]
        if labels:
            console.print(f"  Available: {', '.join(labels)}")
        return
    target = matched[0]
    if click.confirm(f"Remove source '{target.label}' ({target.url})?", default=True):
        user_profile.sources = [s for s in user_profile.sources if s is not target]
        save_profile(user_profile, profile_path)
        console.print(f"[green]✓ Removed source: {target.label}[/green]")


@sources.command("test")
@click.argument("url")
def sources_test(url: str) -> None:
    """Probe a URL and display detection results."""
    from pubscout.core.source_detect import detect_source_type
    console.print(f"Probing {url}...")
    result = detect_source_type(url)
    console.print(f"  Type: {result.source_type}")
    console.print(f"  Reachable: {'yes' if result.reachable else 'no'}")
    console.print(f"  Response: {result.response_time_ms}ms")
    if result.feed_title:
        console.print(f"  Feed: {result.feed_title}")
    if result.error:
        console.print(f"  Error: {result.error}")
    if result.sample_items:
        console.print("  Sample items:")
        for item in result.sample_items[:3]:
            console.print(f"    - {item.get('title', 'N/A')}")


@sources.command("enable")
@click.argument("label")
@click.pass_context
def sources_enable(ctx: click.Context, label: str) -> None:
    """Enable a source."""
    user_profile, profile_path = _load_or_exit(ctx.obj.get("profile_opt"))
    for s in user_profile.sources:
        if s.label == label:
            s.enabled = True
            save_profile(user_profile, profile_path)
            console.print(f"[green]✓ Enabled: {label}[/green]")
            return
    console.print(f"[red]Source '{label}' not found[/red]")


@sources.command("disable")
@click.argument("label")
@click.pass_context
def sources_disable(ctx: click.Context, label: str) -> None:
    """Disable a source."""
    user_profile, profile_path = _load_or_exit(ctx.obj.get("profile_opt"))
    for s in user_profile.sources:
        if s.label == label:
            s.enabled = False
            save_profile(user_profile, profile_path)
            console.print(f"[green]✓ Disabled: {label}[/green]")
            return
    console.print(f"[red]Source '{label}' not found[/red]")


@sources.command("import")
@click.argument("file", type=click.Path(exists=True))
@click.pass_context
def sources_import(ctx: click.Context, file: str) -> None:
    """Import source URLs from a file (one per line)."""
    user_profile, profile_path = _load_or_exit(ctx.obj.get("profile_opt"))
    existing_urls = {s.url for s in user_profile.sources}
    urls = Path(file).read_text().strip().splitlines()
    added = 0
    for url in urls:
        url = url.strip()
        if not url or not url.startswith("http") or url in existing_urls:
            continue
        label = url.split("//")[1].split("/")[0] if "//" in url else url
        user_profile.sources.append(
            Source(
                label=label, type="rss", url=url, adapter="rss",
                enabled=True, user_added=True,
                added_date=datetime.now(timezone.utc).isoformat(),
            )
        )
        existing_urls.add(url)
        added += 1
    save_profile(user_profile, profile_path)
    console.print(f"[green]✓ Imported {added} sources (skipped {len(urls) - added} dupes/invalid)[/green]")


@sources.command("export")
@click.pass_context
def sources_export(ctx: click.Context) -> None:
    """Print all source URLs to stdout."""
    user_profile, _ = _load_or_exit(ctx.obj.get("profile_opt"))
    for s in user_profile.sources:
        click.echo(s.url)


@sources.command("catalog")
@click.option("--profile", "-p", type=click.Path(exists=True), help="Path to profile.yaml")
def sources_catalog(profile: str | None) -> None:
    """List built-in source catalog with active/available status."""
    active_urls: set[str] = set()
    try:
        user_profile, _ = _load_or_exit(profile)
        active_urls = {s.url.lower().rstrip("/") for s in user_profile.sources}
    except SystemExit:
        pass  # no profile yet — show catalog without status

    catalog = [
        ("arXiv", "api", "http://export.arxiv.org/api/query", "arxiv"),
        ("Semantic Scholar", "api", "https://api.semanticscholar.org/graph/v1/paper/search", "semantic_scholar"),
        ("OpenReview", "web", "https://openreview.net", "web"),
        ("ACL Anthology", "web", "https://aclanthology.org", "web"),
        ("Papers With Code", "web", "https://paperswithcode.com", "web"),
    ]
    table = Table(title="Source Catalog")
    table.add_column("Status", style="bold")
    table.add_column("Label", style="cyan")
    table.add_column("Type", style="green")
    table.add_column("URL")
    table.add_column("Adapter")
    for label, typ, url, adapter in catalog:
        is_active = url.lower().rstrip("/") in active_urls
        status = "[green]● Active[/green]" if is_active else "[dim]○ Available[/dim]"
        table.add_row(status, label, typ, url, adapter)
    console.print(table)
    console.print("\n[bold]● Active[/bold] = currently in your profile   [dim]○ Available[/dim] = add with [bold]pubscout sources add <url>[/bold]")


# ── domains ──────────────────────────────────────────────────────────


@cli.group(invoke_without_command=True)
@click.option("--profile", "-p", type=click.Path(exists=True), help="Path to profile.yaml")
@click.pass_context
def domains(ctx: click.Context, profile: str | None) -> None:
    """Manage research domain queries."""
    ctx.ensure_object(dict)
    ctx.obj["profile_opt"] = profile
    if ctx.invoked_subcommand is None:
        _domains_list(profile)


def _domains_list(profile_opt: str | None) -> None:
    user_profile, _ = _load_or_exit(profile_opt)
    table = Table(title="Configured Domains")
    table.add_column("#", style="dim")
    table.add_column("Label", style="cyan")
    table.add_column("Enabled", style="yellow")
    table.add_column("Query", max_width=60)
    for i, domain in enumerate(user_profile.domains, 1):
        query_display = domain.query[:57] + "..." if len(domain.query) > 60 else domain.query
        table.add_row(str(i), domain.label, "✓" if domain.enabled else "✗", query_display)
    console.print(table)


@domains.command("add")
@click.argument("label")
@click.argument("query")
@click.pass_context
def domains_add(ctx: click.Context, label: str, query: str) -> None:
    """Add a new domain with a boolean query."""
    from pubscout.core.query import parse_query
    try:
        parse_query(query)
    except ValueError as exc:
        console.print(f"[red]Invalid query syntax: {exc}[/red]")
        return

    user_profile, profile_path = _load_or_exit(ctx.obj.get("profile_opt"))
    if any(d.label == label for d in user_profile.domains):
        console.print(f"[yellow]Domain '{label}' already exists[/yellow]")
        return
    user_profile.domains.append(Domain(label=label, query=query, enabled=True))
    save_profile(user_profile, profile_path)
    console.print(f"[green]✓ Added domain: {label}[/green]")


@domains.command("remove")
@click.argument("label")
@click.pass_context
def domains_remove(ctx: click.Context, label: str) -> None:
    """Remove a domain by label (case-insensitive, partial match)."""
    user_profile, profile_path = _load_or_exit(ctx.obj.get("profile_opt"))
    needle = label.lower()
    matched = [d for d in user_profile.domains if needle in d.label.lower()]
    if not matched:
        console.print(f"[red]Domain '{label}' not found[/red]")
        labels = [d.label for d in user_profile.domains]
        if labels:
            console.print(f"  Available: {', '.join(labels)}")
        return
    target = matched[0]
    if click.confirm(f"Remove domain '{target.label}'?", default=True):
        user_profile.domains = [d for d in user_profile.domains if d is not target]
        save_profile(user_profile, profile_path)
        console.print(f"[green]✓ Removed domain: {target.label}[/green]")


@domains.command("enable")
@click.argument("label")
@click.pass_context
def domains_enable(ctx: click.Context, label: str) -> None:
    """Enable a domain."""
    user_profile, profile_path = _load_or_exit(ctx.obj.get("profile_opt"))
    for d in user_profile.domains:
        if d.label == label:
            d.enabled = True
            save_profile(user_profile, profile_path)
            console.print(f"[green]✓ Enabled: {label}[/green]")
            return
    console.print(f"[red]Domain '{label}' not found[/red]")


@domains.command("disable")
@click.argument("label")
@click.pass_context
def domains_disable(ctx: click.Context, label: str) -> None:
    """Disable a domain."""
    user_profile, profile_path = _load_or_exit(ctx.obj.get("profile_opt"))
    for d in user_profile.domains:
        if d.label == label:
            d.enabled = False
            save_profile(user_profile, profile_path)
            console.print(f"[green]✓ Disabled: {label}[/green]")
            return
    console.print(f"[red]Domain '{label}' not found[/red]")


@domains.command("catalog")
@click.option("--profile", "-p", type=click.Path(exists=True), help="Path to profile.yaml")
def domains_catalog(profile: str | None) -> None:
    """List built-in domain catalog with active/available status."""
    active_labels: set[str] = set()
    try:
        user_profile, _ = _load_or_exit(profile)
        active_labels = {d.label.lower() for d in user_profile.domains}
    except SystemExit:
        pass

    table = Table(title="Domain Catalog")
    table.add_column("Status", style="bold")
    table.add_column("Label", style="cyan")
    table.add_column("Focus")
    for d in DEFAULT_DOMAINS:
        is_active = d.label.lower() in active_labels
        status = "[green]● Active[/green]" if is_active else "[dim]○ Available[/dim]"
        query_display = d.query[:57] + "..." if len(d.query) > 60 else d.query
        table.add_row(status, d.label, query_display)
    console.print(table)
    console.print("\n[bold]● Active[/bold] = in your profile   [dim]○ Available[/dim] = add with [bold]pubscout domains add <label> <query>[/bold]")


# ── config ───────────────────────────────────────────────────────────


@cli.group()
def config() -> None:
    """Manage scoring and LLM configuration."""


@config.command("show")
@click.option("--profile", "-p", type=click.Path(exists=True), help="Path to profile.yaml")
def config_show(profile: str | None) -> None:
    """Display current configuration."""
    user_profile, _ = _load_or_exit(profile)
    console.print(f"[bold]Scanning[/bold]")
    console.print(f"  Scan range: {user_profile.scan_range_days} day(s)")
    console.print(f"\n[bold]Scoring[/bold]")
    console.print(f"  Threshold: {user_profile.scoring.threshold}")
    console.print(f"  Include keywords: {user_profile.scoring.include_keywords or '(none)'}")
    console.print(f"  Exclude keywords: {user_profile.scoring.exclude_keywords or '(none)'}")
    console.print(f"\n[bold]LLM[/bold]")
    console.print(f"  Provider: {user_profile.llm.provider}")
    console.print(f"  Model: {user_profile.llm.model}")
    console.print(f"  API key: {'configured' if user_profile.llm.api_key else 'not set'}")


@config.command("threshold")
@click.argument("value", type=float)
@click.option("--profile", "-p", type=click.Path(exists=True), help="Path to profile.yaml")
def config_threshold(value: float, profile: str | None) -> None:
    """Set the scoring threshold (1.0–10.0)."""
    if not 1.0 <= value <= 10.0:
        console.print("[red]Threshold must be between 1.0 and 10.0[/red]")
        return
    user_profile, profile_path = _load_or_exit(profile)
    user_profile.scoring.threshold = value
    save_profile(user_profile, profile_path)
    console.print(f"[green]✓ Threshold set to {value}[/green]")


@config.command("exclude-add")
@click.argument("keyword")
@click.option("--profile", "-p", type=click.Path(exists=True), help="Path to profile.yaml")
def config_exclude_add(keyword: str, profile: str | None) -> None:
    """Add an exclude keyword."""
    user_profile, profile_path = _load_or_exit(profile)
    if keyword not in user_profile.scoring.exclude_keywords:
        user_profile.scoring.exclude_keywords.append(keyword)
        save_profile(user_profile, profile_path)
    console.print(f"[green]✓ Added exclude keyword: {keyword}[/green]")


@config.command("exclude-remove")
@click.argument("keyword")
@click.option("--profile", "-p", type=click.Path(exists=True), help="Path to profile.yaml")
def config_exclude_remove(keyword: str, profile: str | None) -> None:
    """Remove an exclude keyword."""
    user_profile, profile_path = _load_or_exit(profile)
    if keyword in user_profile.scoring.exclude_keywords:
        user_profile.scoring.exclude_keywords.remove(keyword)
        save_profile(user_profile, profile_path)
        console.print(f"[green]✓ Removed exclude keyword: {keyword}[/green]")
    else:
        console.print(f"[yellow]Keyword '{keyword}' not in exclude list[/yellow]")


@config.command("include-add")
@click.argument("keyword")
@click.option("--profile", "-p", type=click.Path(exists=True), help="Path to profile.yaml")
def config_include_add(keyword: str, profile: str | None) -> None:
    """Add an include keyword."""
    user_profile, profile_path = _load_or_exit(profile)
    if keyword not in user_profile.scoring.include_keywords:
        user_profile.scoring.include_keywords.append(keyword)
        save_profile(user_profile, profile_path)
    console.print(f"[green]✓ Added include keyword: {keyword}[/green]")


@config.command("include-remove")
@click.argument("keyword")
@click.option("--profile", "-p", type=click.Path(exists=True), help="Path to profile.yaml")
def config_include_remove(keyword: str, profile: str | None) -> None:
    """Remove an include keyword."""
    user_profile, profile_path = _load_or_exit(profile)
    if keyword in user_profile.scoring.include_keywords:
        user_profile.scoring.include_keywords.remove(keyword)
        save_profile(user_profile, profile_path)
        console.print(f"[green]✓ Removed include keyword: {keyword}[/green]")
    else:
        console.print(f"[yellow]Keyword '{keyword}' not in include list[/yellow]")


@config.command("model")
@click.argument("name")
@click.option("--profile", "-p", type=click.Path(exists=True), help="Path to profile.yaml")
def config_model(name: str, profile: str | None) -> None:
    """Set the LLM model name."""
    user_profile, profile_path = _load_or_exit(profile)
    user_profile.llm.model = name
    save_profile(user_profile, profile_path)
    console.print(f"[green]✓ Model set to {name}[/green]")


@config.command("scan-range")
@click.argument("days", type=int)
@click.option("--profile", "-p", type=click.Path(exists=True), help="Path to profile.yaml")
def config_scan_range(days: int, profile: str | None) -> None:
    """Set the default scan range in days (1–365). Only papers published within
    this window are included. Default: 7."""
    if not 1 <= days <= 365:
        console.print("[red]Scan range must be between 1 and 365 days[/red]")
        return
    user_profile, profile_path = _load_or_exit(profile)
    user_profile.scan_range_days = days
    save_profile(user_profile, profile_path)
    console.print(f"[green]✓ Scan range set to {days} day(s)[/green]")


# ── feedback ─────────────────────────────────────────────────────────


@cli.group()
def feedback() -> None:
    """Manage publication feedback."""


@feedback.command("record")
@click.argument("pub_id")
@click.argument("signal", type=click.Choice(["up", "down"]))
@click.option("--note", default=None, help="Optional note")
def feedback_record(pub_id: str, signal: str, note: str | None) -> None:
    """Record feedback for a publication (up = positive, down = negative)."""
    from pubscout.core.models import FeedbackSignal

    db = PubScoutDB()
    pub = db.get_publication(pub_id)
    if pub is None:
        console.print(f"[red]Publication '{pub_id}' not found[/red]")
        return
    mapped_signal = "positive" if signal == "up" else "negative"
    fb = FeedbackSignal(publication_id=pub_id, signal=mapped_signal, user_notes=note)
    db.save_feedback(fb)
    console.print(f"[green]✓ Recorded {mapped_signal} feedback for {pub_id}[/green]")


@feedback.command("list")
@click.option("--limit", default=20, help="Max items to show")
@click.option("--signal", type=click.Choice(["positive", "negative"]), default=None)
def feedback_list(limit: int, signal: str | None) -> None:
    """List recent feedback entries."""
    db = PubScoutDB()
    entries = db.get_feedback(limit=limit)
    if signal:
        entries = [e for e in entries if e.signal == signal]

    if not entries:
        console.print("[yellow]No feedback entries found.[/yellow]")
        return

    table = Table(title="Feedback")
    table.add_column("Date", style="dim")
    table.add_column("Publication ID")
    table.add_column("Signal", style="green")
    table.add_column("Notes")
    for e in entries:
        table.add_row(
            e.timestamp.strftime("%Y-%m-%d %H:%M"),
            e.publication_id[:12] + "...",
            e.signal,
            e.user_notes or "",
        )
    console.print(table)


@feedback.command("import")
@click.argument("file", type=click.Path(exists=True))
def feedback_import(file: str) -> None:
    """Import feedback from a JSON file exported from the HTML report.

    The file should contain a JSON array like:
      [{"publication_id": "...", "signal": "positive|negative", "timestamp": "..."}]
    """
    import json
    from pathlib import Path as _Path
    from pubscout.core.models import FeedbackSignal

    data = json.loads(_Path(file).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        console.print("[red]Expected a JSON array of feedback entries.[/red]")
        return

    db = PubScoutDB()
    pos = neg = skipped = 0
    for entry in data:
        pub_id = entry.get("publication_id", "")
        signal = entry.get("signal", "")
        if signal not in ("positive", "negative"):
            skipped += 1
            continue
        pub = db.get_publication(pub_id)
        if pub is None:
            skipped += 1
            continue
        fb = FeedbackSignal(publication_id=pub_id, signal=signal)
        db.save_feedback(fb)
        if signal == "positive":
            pos += 1
        else:
            neg += 1

    console.print(
        f"[green]✓ Imported {pos} positive, {neg} negative "
        f"({skipped} skipped)[/green]"
    )


# ── email ────────────────────────────────────────────────────────────


@cli.group()
def email() -> None:
    """Email delivery management."""


@email.command("test")
@click.option("--profile", "-p", type=click.Path(exists=True), help="Path to profile.yaml")
def email_test(profile: str | None) -> None:
    """Send a test email."""
    user_profile, _ = _load_or_exit(profile)
    from pubscout.core.email import SmtpEmailSender
    sender = SmtpEmailSender()
    html = "<html><body><h1>PubScout Test Email</h1><p>This is a test.</p></body></html>"
    ok = sender.send(html, "PubScout — Test Email", user_profile.email)
    if ok:
        console.print("[green]✓ Test email sent successfully[/green]")
    else:
        console.print("[red]✗ Failed to send test email[/red]")


# ── history ──────────────────────────────────────────────────────────


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


# ── stats ────────────────────────────────────────────────────────────


@cli.command()
@click.option("--since", default=None, help="Filter stats since date (YYYY-MM-DD)")
def stats(since: str | None) -> None:
    """Show aggregate statistics."""
    db = PubScoutDB()
    console.print("[bold]PubScout Statistics[/bold]\n")

    console.print(f"  Total publications: {db.count_publications(since)}")
    console.print(f"  Reported: {db.count_reported_publications(since)}")
    console.print(f"  Total scans: {db.count_scans(since)}")

    fb = db.count_feedback_by_signal(since)
    console.print(f"  Feedback: {fb['positive']} positive, {fb['negative']} negative")

    domain_stats = db.get_domain_stats(since)
    if domain_stats:
        console.print("\n  [bold]By Domain:[/bold]")
        for label, count in domain_stats:
            console.print(f"    {label}: {count}")

    source_stats = db.get_source_stats(since)
    if source_stats:
        console.print("\n  [bold]By Source:[/bold]")
        for label, fetched, reported in source_stats:
            console.print(f"    {label}: {fetched} fetched, {reported} reported")


# ── schedule ─────────────────────────────────────────────────────────


@cli.group()
def schedule() -> None:
    """Scheduling helpers."""


@schedule.command("show")
def schedule_show() -> None:
    """Show recommended scheduler command for your OS."""
    system = platform.system()
    if system == "Windows":
        console.print("[bold]Windows Task Scheduler:[/bold]")
        console.print(
            '  schtasks /create /sc daily /tn "PubScout Scan" '
            '/tr "pubscout scan" /st 08:00'
        )
    else:
        console.print("[bold]Cron (Linux/macOS):[/bold]")
        console.print("  0 8 * * * pubscout scan")
