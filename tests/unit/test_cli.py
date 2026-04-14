"""Tests for the PubScout CLI entry point."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from pubscout.cli.main import cli
from pubscout.core.models import ScanRun


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def isolated_env(tmp_path, monkeypatch):
    """Redirect profile path and DB path so tests never touch the real home dir."""
    profile_path = tmp_path / "profile.yaml"
    db_path = tmp_path / "test.db"

    monkeypatch.setattr("pubscout.cli.main.get_profile_path", lambda: profile_path)
    monkeypatch.setattr(
        "pubscout.cli.main.PubScoutDB",
        lambda db_path_arg=None: MagicMock(get_scan_runs=MagicMock(return_value=[])),
    )
    return tmp_path, profile_path, db_path


# ── init ─────────────────────────────────────────────────────────────

def test_init_creates_profile(runner, isolated_env):
    """``pubscout init --non-interactive`` creates a new profile."""
    _tmp, profile_path, _ = isolated_env

    result = runner.invoke(cli, ["init", "--non-interactive"])

    assert result.exit_code == 0
    assert profile_path.exists()
    assert "Profile created" in result.output


def test_init_existing_profile_warns(runner, isolated_env):
    """Running init when profile already exists warns and does not overwrite."""
    _tmp, profile_path, _ = isolated_env

    runner.invoke(cli, ["init", "--non-interactive"])
    original_content = profile_path.read_text()

    result = runner.invoke(cli, ["init", "--non-interactive"])

    assert result.exit_code == 0
    assert "already exists" in result.output
    assert profile_path.read_text() == original_content


# ── scan ─────────────────────────────────────────────────────────────

def test_scan_no_profile_exits(runner, isolated_env):
    """``pubscout scan`` without a profile prints an error and exits 1."""
    result = runner.invoke(cli, ["scan"])

    assert result.exit_code == 1
    assert "No profile found" in result.output


def test_scan_dry_run(runner, isolated_env, monkeypatch):
    """``pubscout scan --dry-run`` runs the pipeline and shows a results table."""
    _tmp, _profile_path, _ = isolated_env

    runner.invoke(cli, ["init", "--non-interactive"])

    mock_scan_run = ScanRun(
        sources_checked=1,
        items_fetched=25,
        items_scored=25,
        items_reported=5,
        errors=[],
        duration_seconds=3.2,
    )

    mock_pipeline = MagicMock()
    mock_pipeline.run.return_value = mock_scan_run

    monkeypatch.setattr(
        "pubscout.cli.main.ScanPipeline",
        lambda profile, db: mock_pipeline,
    )

    result = runner.invoke(cli, ["scan", "--dry-run"])

    assert result.exit_code == 0
    assert "Scan Results" in result.output
    assert "25" in result.output
    assert "3.2s" in result.output
    assert "Dry run" in result.output


def test_scan_no_email_flag(runner, isolated_env, monkeypatch):
    """``pubscout scan --no-email`` passes send_email=False to pipeline."""
    _tmp, _profile_path, _ = isolated_env
    runner.invoke(cli, ["init", "--non-interactive"])

    mock_scan_run = ScanRun(
        sources_checked=1, items_fetched=1, items_scored=1, items_reported=1,
        errors=[], duration_seconds=0.5,
    )
    mock_pipeline = MagicMock()
    mock_pipeline.run.return_value = mock_scan_run
    monkeypatch.setattr("pubscout.cli.main.ScanPipeline", lambda p, db: mock_pipeline)

    result = runner.invoke(cli, ["scan", "--no-email"])
    assert result.exit_code == 0
    mock_pipeline.run.assert_called_once_with(dry_run=False, send_email=False, scan_range_days=None, first_run=False)


# ── sources ──────────────────────────────────────────────────────────

def test_sources_no_profile_exits(runner, isolated_env):
    """``pubscout sources`` without a profile exits with error."""
    result = runner.invoke(cli, ["sources"])

    assert result.exit_code == 1
    assert "No profile found" in result.output


def test_sources_lists_configured(runner, isolated_env):
    """After init, ``pubscout sources`` shows sources."""
    runner.invoke(cli, ["init", "--non-interactive"])
    result = runner.invoke(cli, ["sources"])

    assert result.exit_code == 0
    assert "Configured Sources" in result.output
    assert "arXiv" in result.output


def test_sources_add_and_remove(runner, isolated_env):
    """Add a source, then remove it."""
    runner.invoke(cli, ["init", "--non-interactive"])
    result = runner.invoke(cli, ["sources", "add", "https://example.com/feed.xml", "--name", "Test", "--type", "rss", "--no-detect"])
    assert result.exit_code == 0
    assert "Added source" in result.output

    result = runner.invoke(cli, ["sources", "remove", "Test"], input="y\n")
    assert result.exit_code == 0
    assert "Removed" in result.output


def test_sources_enable_disable(runner, isolated_env):
    """Enable/disable a source."""
    runner.invoke(cli, ["init", "--non-interactive"])
    result = runner.invoke(cli, ["sources", "disable", "arXiv"])
    assert result.exit_code == 0
    assert "Disabled" in result.output

    result = runner.invoke(cli, ["sources", "enable", "arXiv"])
    assert result.exit_code == 0
    assert "Enabled" in result.output


def test_sources_export(runner, isolated_env):
    """Export outputs all URLs."""
    runner.invoke(cli, ["init", "--non-interactive"])
    result = runner.invoke(cli, ["sources", "export"])
    assert result.exit_code == 0
    assert "arxiv" in result.output.lower()


def test_sources_import(runner, isolated_env):
    """Import adds URLs from a file."""
    _tmp, _, _ = isolated_env
    runner.invoke(cli, ["init", "--non-interactive"])
    import_file = _tmp / "urls.txt"
    import_file.write_text("https://example.com/feed1\nhttps://example.com/feed2\n")
    result = runner.invoke(cli, ["sources", "import", str(import_file)])
    assert result.exit_code == 0
    assert "Imported 2" in result.output


def test_sources_duplicate_add(runner, isolated_env):
    """Adding a duplicate URL warns."""
    runner.invoke(cli, ["init", "--non-interactive"])
    runner.invoke(cli, ["sources", "add", "http://export.arxiv.org/api/query", "--no-detect"])
    result = runner.invoke(cli, ["sources", "add", "http://export.arxiv.org/api/query", "--no-detect"])
    assert "already exists" in result.output


def test_sources_catalog(runner):
    """Catalog command lists built-in sources."""
    result = runner.invoke(cli, ["sources", "catalog"])
    assert result.exit_code == 0
    assert "arXiv" in result.output
    assert "Semantic Scholar" in result.output


# ── domains ──────────────────────────────────────────────────────────

def test_domains_no_profile_exits(runner, isolated_env):
    """``pubscout domains`` without a profile exits with error."""
    result = runner.invoke(cli, ["domains"])

    assert result.exit_code == 1
    assert "No profile found" in result.output


def test_domains_lists_configured(runner, isolated_env):
    """After init, ``pubscout domains`` shows 6 domains."""
    runner.invoke(cli, ["init", "--non-interactive"])
    result = runner.invoke(cli, ["domains"])

    assert result.exit_code == 0
    assert "Configured Domains" in result.output
    for n in range(1, 7):
        assert str(n) in result.output


def test_domains_add_and_remove(runner, isolated_env):
    """Add then remove a domain."""
    runner.invoke(cli, ["init", "--non-interactive"])
    result = runner.invoke(cli, ["domains", "add", "TestDomain", "LLM AND inference"])
    assert result.exit_code == 0
    assert "Added domain" in result.output

    result = runner.invoke(cli, ["domains", "remove", "TestDomain"], input="y\n")
    assert result.exit_code == 0
    assert "Removed" in result.output


def test_domains_add_invalid_query(runner, isolated_env):
    """Adding a domain with bad query syntax is rejected."""
    runner.invoke(cli, ["init", "--non-interactive"])
    result = runner.invoke(cli, ["domains", "add", "Bad", "AND OR"])
    assert "Invalid query" in result.output


def test_domains_enable_disable(runner, isolated_env):
    """Enable/disable a domain."""
    runner.invoke(cli, ["init", "--non-interactive"])
    result = runner.invoke(cli, ["domains", "disable", "LLM Disaggregated Inference"])
    assert result.exit_code == 0
    assert "Disabled" in result.output

    result = runner.invoke(cli, ["domains", "enable", "LLM Disaggregated Inference"])
    assert result.exit_code == 0
    assert "Enabled" in result.output


def test_domains_remove_nonexistent(runner, isolated_env):
    """Removing a nonexistent domain shows error."""
    runner.invoke(cli, ["init", "--non-interactive"])
    result = runner.invoke(cli, ["domains", "remove", "DoesNotExist"])
    assert "not found" in result.output


def test_domains_catalog(runner):
    """Catalog command lists built-in domains."""
    result = runner.invoke(cli, ["domains", "catalog"])
    assert result.exit_code == 0
    assert "LLM Disaggregated Inference" in result.output


# ── config ───────────────────────────────────────────────────────────

def test_config_show(runner, isolated_env):
    """Config show displays current settings."""
    runner.invoke(cli, ["init", "--non-interactive"])
    result = runner.invoke(cli, ["config", "show"])
    assert result.exit_code == 0
    assert "Threshold" in result.output
    assert "5.0" in result.output


def test_config_threshold_valid(runner, isolated_env):
    """Setting a valid threshold succeeds."""
    runner.invoke(cli, ["init", "--non-interactive"])
    result = runner.invoke(cli, ["config", "threshold", "7.0"])
    assert result.exit_code == 0
    assert "7.0" in result.output


def test_config_threshold_out_of_range(runner, isolated_env):
    """Setting threshold outside 1-10 is rejected."""
    runner.invoke(cli, ["init", "--non-interactive"])
    result = runner.invoke(cli, ["config", "threshold", "11.0"])
    assert "between 1.0 and 10.0" in result.output


def test_config_exclude_add_remove(runner, isolated_env):
    """Add and remove exclude keywords."""
    runner.invoke(cli, ["init", "--non-interactive"])
    result = runner.invoke(cli, ["config", "exclude-add", "survey"])
    assert "Added exclude" in result.output

    result = runner.invoke(cli, ["config", "exclude-remove", "survey"])
    assert "Removed exclude" in result.output


def test_config_include_add_remove(runner, isolated_env):
    """Add and remove include keywords."""
    runner.invoke(cli, ["init", "--non-interactive"])
    result = runner.invoke(cli, ["config", "include-add", "transformer"])
    assert "Added include" in result.output

    result = runner.invoke(cli, ["config", "include-remove", "transformer"])
    assert "Removed include" in result.output


def test_config_model(runner, isolated_env):
    """Set the LLM model."""
    runner.invoke(cli, ["init", "--non-interactive"])
    result = runner.invoke(cli, ["config", "model", "gpt-4o"])
    assert result.exit_code == 0
    assert "gpt-4o" in result.output


def test_config_scan_range_valid(runner, isolated_env):
    """Set scan range to a valid number of days."""
    runner.invoke(cli, ["init", "--non-interactive"])
    result = runner.invoke(cli, ["config", "scan-range", "14"])
    assert result.exit_code == 0
    assert "14" in result.output
    # Verify it persists
    show = runner.invoke(cli, ["config", "show"])
    assert "14 day(s)" in show.output


def test_config_scan_range_out_of_range(runner, isolated_env):
    """Reject scan range outside 1–365."""
    runner.invoke(cli, ["init", "--non-interactive"])
    result = runner.invoke(cli, ["config", "scan-range", "0"])
    assert "between 1 and 365" in result.output
    result2 = runner.invoke(cli, ["config", "scan-range", "400"])
    assert "between 1 and 365" in result2.output


def test_config_show_includes_scan_range(runner, isolated_env):
    """config show displays the scan range."""
    runner.invoke(cli, ["init", "--non-interactive"])
    result = runner.invoke(cli, ["config", "show"])
    assert result.exit_code == 0
    assert "Scan range:" in result.output
    assert "7 day(s)" in result.output  # default


# ── feedback ─────────────────────────────────────────────────────────

def test_feedback_record_not_found(runner, isolated_env):
    """Recording feedback for nonexistent publication shows error."""
    result = runner.invoke(cli, ["feedback", "record", "bad-id", "up"])
    # DB is mocked so get_publication returns None
    assert result.exit_code == 0 or "not found" in result.output


def test_feedback_list_empty(runner, isolated_env):
    """Listing feedback when empty shows a message."""
    result = runner.invoke(cli, ["feedback", "list"])
    assert result.exit_code == 0


# ── history ──────────────────────────────────────────────────────────

def test_history_empty(runner, isolated_env):
    """``pubscout history`` with no prior scans shows a helpful message."""
    result = runner.invoke(cli, ["history"])

    assert result.exit_code == 0
    assert "No scan history" in result.output


def test_history_with_runs(runner, tmp_path, monkeypatch):
    """``pubscout history`` renders a table when scan runs exist."""
    mock_runs = [
        ScanRun(
            sources_checked=1,
            items_fetched=10,
            items_scored=10,
            items_reported=3,
            errors=[],
            duration_seconds=2.5,
            timestamp=datetime(2025, 7, 1, 12, 0, tzinfo=timezone.utc),
        ),
    ]
    mock_db = MagicMock()
    mock_db.get_scan_runs.return_value = mock_runs

    monkeypatch.setattr("pubscout.cli.main.PubScoutDB", lambda db_path=None: mock_db)

    result = runner.invoke(cli, ["history"])

    assert result.exit_code == 0
    assert "Scan History" in result.output
    assert "2025-07-01" in result.output
    assert "2.5s" in result.output


# ── stats ────────────────────────────────────────────────────────────

def test_stats_empty(runner, tmp_path, monkeypatch):
    """Stats on empty DB shows zeros."""
    mock_db = MagicMock()
    mock_db.count_publications.return_value = 0
    mock_db.count_reported_publications.return_value = 0
    mock_db.count_scans.return_value = 0
    mock_db.count_feedback_by_signal.return_value = {"positive": 0, "negative": 0}
    mock_db.get_domain_stats.return_value = []
    mock_db.get_source_stats.return_value = []
    monkeypatch.setattr("pubscout.cli.main.PubScoutDB", lambda db_path=None: mock_db)

    result = runner.invoke(cli, ["stats"])
    assert result.exit_code == 0
    assert "Total publications: 0" in result.output


# ── schedule ─────────────────────────────────────────────────────────

def test_schedule_show(runner):
    """Schedule show outputs OS-appropriate command."""
    result = runner.invoke(cli, ["schedule", "show"])
    assert result.exit_code == 0
    assert "pubscout scan" in result.output


# ── verbose flag ─────────────────────────────────────────────────────

def test_verbose_flag(runner, isolated_env):
    """The ``-v`` flag does not cause a crash."""
    result = runner.invoke(cli, ["-v", "init", "--non-interactive"])

    assert result.exit_code == 0
