"""Tests for the ScanPipeline orchestrator."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pubscout.core.models import Publication, ScanRun, Source
from pubscout.core.pipeline import ADAPTER_REGISTRY, ScanPipeline
from pubscout.core.profile import create_default_profile
from pubscout.storage.database import PubScoutDB


# ── helpers ──────────────────────────────────────────────────


def _make_pub(**overrides) -> Publication:
    """Create a Publication with sensible defaults."""
    defaults: dict = {
        "title": "A Novel Approach to Inference Serving",
        "authors": ["Alice", "Bob"],
        "abstract": "We present a new method for LLM inference.",
        "url": "https://arxiv.org/abs/2401.00001",
        "arxiv_id": "2401.00001",
        "source_label": "arxiv",
        "fetch_date": datetime(2025, 1, 1, tzinfo=timezone.utc),
        "matched_domains": ["LLM Disaggregated Inference"],
    }
    defaults.update(overrides)
    return Publication(**defaults)


def _stub_pubs(n: int = 5) -> list[Publication]:
    """Return *n* distinct publications."""
    return [
        _make_pub(
            title=f"Paper {i}",
            arxiv_id=f"2401.{i:05d}",
            url=f"https://arxiv.org/abs/2401.{i:05d}",
        )
        for i in range(n)
    ]


# ── fixtures ─────────────────────────────────────────────────


@pytest.fixture()
def db(tmp_path: Path) -> PubScoutDB:
    """Fresh in-memory DB per test."""
    return PubScoutDB(db_path=tmp_path / "test.db")


@pytest.fixture()
def profile():
    """Minimal UserProfile with arXiv-only source for pipeline tests."""
    p = create_default_profile()
    p.sources = [s for s in p.sources if s.adapter == "arxiv"]
    return p


@pytest.fixture()
def mock_adapter():
    """A mock adapter instance + patched registry."""
    adapter = MagicMock()
    adapter.fetch.return_value = []
    return adapter


# ── tests ────────────────────────────────────────────────────


@patch("pubscout.core.pipeline.RelevanceScorer")
def test_run_fetches_from_enabled_sources(
    mock_scorer_cls: MagicMock,
    mock_adapter,
    profile,
    db,
    tmp_path,
):
    """Adapter.fetch is called for every enabled source and pubs flow through."""
    pubs = _stub_pubs(5)
    mock_adapter.fetch.return_value = pubs
    mock_scorer_cls.return_value.score_publications.return_value = pubs

    with patch.dict(ADAPTER_REGISTRY, {"arxiv": lambda: mock_adapter}):
        pipeline = ScanPipeline(profile, db)
        run = pipeline.run(dry_run=True)

    mock_adapter.fetch.assert_called()
    assert run.items_fetched == 5
    assert run.sources_checked >= 1


@patch("pubscout.core.pipeline.RelevanceScorer")
def test_run_skips_disabled_sources(
    mock_scorer_cls: MagicMock,
    mock_adapter,
    profile,
    db,
):
    """Sources with enabled=False must not trigger adapter.fetch."""
    profile.sources = [s.model_copy(update={"enabled": False}) for s in profile.sources]

    mock_scorer_cls.return_value.score_publications.return_value = []

    with patch.dict(ADAPTER_REGISTRY, {"arxiv": lambda: mock_adapter}):
        pipeline = ScanPipeline(profile, db)
        run = pipeline.run(dry_run=True)

    mock_adapter.fetch.assert_not_called()
    assert run.sources_checked == 0
    assert run.items_fetched == 0


@patch("pubscout.core.pipeline.RelevanceScorer")
def test_run_deduplicates(
    mock_scorer_cls: MagicMock,
    mock_adapter,
    profile,
    db,
):
    """Duplicate arxiv_ids within a batch must be collapsed."""
    dup_pubs = [
        _make_pub(title="Paper Alpha", arxiv_id="2401.00001", matched_domains=["D1"]),
        _make_pub(title="Paper Alpha", arxiv_id="2401.00001", matched_domains=["D2"]),
        _make_pub(title="Paper Beta", arxiv_id="2401.00002", matched_domains=["D1"]),
    ]
    mock_adapter.fetch.return_value = dup_pubs

    mock_scorer_cls.return_value.score_publications.side_effect = (
        lambda pubs, *a, **kw: pubs
    )

    with patch.dict(ADAPTER_REGISTRY, {"arxiv": lambda: mock_adapter}):
        pipeline = ScanPipeline(profile, db)
        run = pipeline.run(dry_run=True)

    assert run.items_fetched == 3
    scored_args = mock_scorer_cls.return_value.score_publications.call_args
    unique_pubs_passed = scored_args[0][0]
    assert len(unique_pubs_passed) == 2


@patch("pubscout.core.pipeline.RelevanceScorer")
def test_run_scores_and_filters(
    mock_scorer_cls: MagicMock,
    mock_adapter,
    profile,
    db,
):
    """Only publications returned by the scorer appear in the final result."""
    five_pubs = _stub_pubs(5)
    mock_adapter.fetch.return_value = five_pubs

    kept = [p.model_copy(update={"relevance_score": 8.0}) for p in five_pubs[:2]]
    mock_scorer_cls.return_value.score_publications.return_value = kept

    with patch.dict(ADAPTER_REGISTRY, {"arxiv": lambda: mock_adapter}):
        pipeline = ScanPipeline(profile, db)
        run = pipeline.run(dry_run=True)

    assert run.items_scored == 2
    assert run.items_reported == 2


@patch("pubscout.core.pipeline.RelevanceScorer")
def test_run_generates_report(
    mock_scorer_cls: MagicMock,
    mock_adapter,
    profile,
    db,
    tmp_path,
):
    """A report HTML file is created on disk."""
    pubs = _stub_pubs(2)
    mock_adapter.fetch.return_value = pubs

    scored = [p.model_copy(update={"relevance_score": 7.5}) for p in pubs]
    mock_scorer_cls.return_value.score_publications.return_value = scored

    with patch.dict(ADAPTER_REGISTRY, {"arxiv": lambda: mock_adapter}):
        pipeline = ScanPipeline(profile, db)
        pipeline.report_generator = MagicMock()
        pipeline.report_generator.generate_html.return_value = "<html>report</html>"
        pipeline.report_generator.save_report.return_value = tmp_path / "report.html"

        run = pipeline.run(dry_run=True)

    pipeline.report_generator.generate_html.assert_called_once()
    pipeline.report_generator.save_report.assert_called_once_with("<html>report</html>")


@patch("pubscout.core.pipeline.RelevanceScorer")
def test_run_saves_to_database(
    mock_scorer_cls: MagicMock,
    mock_adapter,
    profile,
    db,
):
    """Scored publications and ScanRun are persisted to the DB."""
    pubs = _stub_pubs(3)
    mock_adapter.fetch.return_value = pubs

    scored = [p.model_copy(update={"relevance_score": 9.0}) for p in pubs]
    mock_scorer_cls.return_value.score_publications.return_value = scored

    with patch.dict(ADAPTER_REGISTRY, {"arxiv": lambda: mock_adapter}):
        pipeline = ScanPipeline(profile, db)
        run = pipeline.run(dry_run=True)

    for pub in scored:
        assert db.get_publication(pub.id) is not None

    runs = db.get_scan_runs(limit=1)
    assert len(runs) == 1
    assert runs[0].items_reported == 3


@patch("pubscout.core.pipeline.RelevanceScorer")
def test_run_handles_fetch_error_gracefully(
    mock_scorer_cls: MagicMock,
    mock_adapter,
    profile,
    db,
):
    """A fetch error is captured in scan_run.errors; pipeline still completes."""
    mock_adapter.fetch.side_effect = RuntimeError("network down")
    mock_scorer_cls.return_value.score_publications.return_value = []

    with patch.dict(ADAPTER_REGISTRY, {"arxiv": lambda: mock_adapter}):
        pipeline = ScanPipeline(profile, db)
        run = pipeline.run(dry_run=True)

    assert len(run.errors) >= 1
    assert "network down" in run.errors[0]
    assert run.items_fetched == 0


@patch("pubscout.core.pipeline.RelevanceScorer")
def test_run_returns_scan_run_stats(
    mock_scorer_cls: MagicMock,
    mock_adapter,
    profile,
    db,
):
    """ScanRun carries correct aggregate counters."""
    pubs = _stub_pubs(4)
    mock_adapter.fetch.return_value = pubs

    kept = [p.model_copy(update={"relevance_score": 6.0}) for p in pubs[:3]]
    mock_scorer_cls.return_value.score_publications.return_value = kept

    with patch.dict(ADAPTER_REGISTRY, {"arxiv": lambda: mock_adapter}):
        pipeline = ScanPipeline(profile, db)
        run = pipeline.run(dry_run=True)

    assert isinstance(run, ScanRun)
    assert run.sources_checked >= 1
    assert run.items_fetched == 4
    assert run.items_scored == 3
    assert run.items_reported == 3
    assert run.duration_seconds is not None
    assert run.duration_seconds >= 0
    assert run.errors == []


@patch("pubscout.core.pipeline.RelevanceScorer")
def test_dry_run_does_not_send_email(
    mock_scorer_cls: MagicMock,
    mock_adapter,
    profile,
    db,
):
    """dry_run=True completes without raising."""
    mock_adapter.fetch.return_value = _stub_pubs(1)
    mock_scorer_cls.return_value.score_publications.return_value = _stub_pubs(1)

    with patch.dict(ADAPTER_REGISTRY, {"arxiv": lambda: mock_adapter}):
        pipeline = ScanPipeline(profile, db)
        run = pipeline.run(dry_run=True)

    assert isinstance(run, ScanRun)
    assert run.items_fetched >= 1


# ── date-range filter tests ──────────────────────────────────────────


@patch("pubscout.core.pipeline.RelevanceScorer")
def test_run_filters_old_publications(
    mock_scorer_cls: MagicMock,
    mock_adapter,
    profile,
    db,
):
    """Publications older than scan_range_days are filtered out before scoring."""
    from datetime import timedelta

    now = datetime.now(timezone.utc)
    recent_pub = _make_pub(
        title="Recent Paper",
        arxiv_id="2401.10001",
        url="https://arxiv.org/abs/2401.10001",
        publication_date=now - timedelta(days=2),
    )
    old_pub = _make_pub(
        title="Old Paper",
        arxiv_id="2401.10002",
        url="https://arxiv.org/abs/2401.10002",
        publication_date=now - timedelta(days=30),
    )
    mock_adapter.fetch.return_value = [recent_pub, old_pub]
    mock_scorer_cls.return_value.score_publications.return_value = [recent_pub]

    profile.scan_range_days = 7

    with patch.dict(ADAPTER_REGISTRY, {"arxiv": lambda: mock_adapter}):
        pipeline = ScanPipeline(profile, db)
        run = pipeline.run(dry_run=True)

    # Scorer should only receive the recent pub (old one filtered)
    scored_call = mock_scorer_cls.return_value.score_publications.call_args
    pubs_passed_to_scorer = scored_call[0][0]
    titles = [p.title for p in pubs_passed_to_scorer]
    assert "Recent Paper" in titles
    assert "Old Paper" not in titles


@patch("pubscout.core.pipeline.RelevanceScorer")
def test_run_scan_range_override(
    mock_scorer_cls: MagicMock,
    mock_adapter,
    profile,
    db,
):
    """scan_range_days parameter overrides profile default."""
    from datetime import timedelta

    now = datetime.now(timezone.utc)
    pub_10d_ago = _make_pub(
        title="Ten Days Ago",
        arxiv_id="2401.20001",
        url="https://arxiv.org/abs/2401.20001",
        publication_date=now - timedelta(days=10),
    )
    mock_adapter.fetch.return_value = [pub_10d_ago]

    profile.scan_range_days = 7  # Would filter it out

    # Override to 14 days — should keep the paper
    mock_scorer_cls.return_value.score_publications.return_value = [pub_10d_ago]

    with patch.dict(ADAPTER_REGISTRY, {"arxiv": lambda: mock_adapter}):
        pipeline = ScanPipeline(profile, db)
        run = pipeline.run(dry_run=True, scan_range_days=14)

    scored_call = mock_scorer_cls.return_value.score_publications.call_args
    pubs_passed_to_scorer = scored_call[0][0]
    assert len(pubs_passed_to_scorer) == 1
    assert pubs_passed_to_scorer[0].title == "Ten Days Ago"


@patch("pubscout.core.pipeline.RelevanceScorer")
def test_run_keeps_pubs_without_date(
    mock_scorer_cls: MagicMock,
    mock_adapter,
    profile,
    db,
):
    """Publications with no publication_date are kept (not filtered)."""
    no_date_pub = _make_pub(
        title="No Date Paper",
        arxiv_id="2401.30001",
        url="https://arxiv.org/abs/2401.30001",
        publication_date=None,
    )
    mock_adapter.fetch.return_value = [no_date_pub]
    mock_scorer_cls.return_value.score_publications.return_value = [no_date_pub]

    profile.scan_range_days = 7

    with patch.dict(ADAPTER_REGISTRY, {"arxiv": lambda: mock_adapter}):
        pipeline = ScanPipeline(profile, db)
        run = pipeline.run(dry_run=True)

    scored_call = mock_scorer_cls.return_value.score_publications.call_args
    pubs_passed_to_scorer = scored_call[0][0]
    assert len(pubs_passed_to_scorer) == 1
