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
    """``pubscout init`` creates a new profile.yaml and prints success."""
    _tmp, profile_path, _ = isolated_env

    result = runner.invoke(cli, ["init"])

    assert result.exit_code == 0
    assert profile_path.exists()
    assert "Profile created" in result.output


def test_init_existing_profile_warns(runner, isolated_env):
    """Running init when profile already exists warns and does not overwrite."""
    _tmp, profile_path, _ = isolated_env

    # First init — create the profile
    runner.invoke(cli, ["init"])
    original_content = profile_path.read_text()

    # Second init — should warn
    result = runner.invoke(cli, ["init"])

    assert result.exit_code == 0
    assert "already exists" in result.output
    # Content unchanged
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

    # Create profile first
    runner.invoke(cli, ["init"])

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
    assert "25" in result.output  # items_fetched
    assert "3.2s" in result.output  # duration
    assert "Dry run" in result.output


# ── sources ──────────────────────────────────────────────────────────

def test_sources_no_profile_exits(runner, isolated_env):
    """``pubscout sources`` without a profile exits with error."""
    result = runner.invoke(cli, ["sources"])

    assert result.exit_code == 1
    assert "No profile found" in result.output


def test_sources_lists_configured(runner, isolated_env):
    """After init, ``pubscout sources`` shows the arXiv source."""
    runner.invoke(cli, ["init"])
    result = runner.invoke(cli, ["sources"])

    assert result.exit_code == 0
    assert "Configured Sources" in result.output
    assert "arXiv" in result.output


# ── domains ──────────────────────────────────────────────────────────

def test_domains_no_profile_exits(runner, isolated_env):
    """``pubscout domains`` without a profile exits with error."""
    result = runner.invoke(cli, ["domains"])

    assert result.exit_code == 1
    assert "No profile found" in result.output


def test_domains_lists_configured(runner, isolated_env):
    """After init, ``pubscout domains`` shows 6 domains."""
    runner.invoke(cli, ["init"])
    result = runner.invoke(cli, ["domains"])

    assert result.exit_code == 0
    assert "Configured Domains" in result.output
    # Default profile has 6 domains — verify rows numbered 1..6
    for n in range(1, 7):
        assert str(n) in result.output


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


# ── verbose flag ─────────────────────────────────────────────────────

def test_verbose_flag(runner, isolated_env):
    """The ``-v`` flag does not cause a crash."""
    result = runner.invoke(cli, ["-v", "init"])

    assert result.exit_code == 0
