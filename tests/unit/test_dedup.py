"""Tests for pubscout.core.dedup — FR-004 deduplication engine."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from pubscout.core.dedup import Deduplicator
from pubscout.core.models import Publication
from pubscout.storage.database import PubScoutDB


# ── Helpers ──────────────────────────────────────────────────────────


def _make_pub(**overrides) -> Publication:
    """Create a Publication with sensible defaults, accepting overrides."""
    defaults: dict = {
        "title": "A Novel Approach to Neural Architecture Search",
        "authors": ["Alice"],
        "abstract": "We present…",
        "url": "https://example.com/paper",
        "source_label": "arxiv",
        "fetch_date": datetime(2025, 1, 1, tzinfo=timezone.utc),
    }
    defaults.update(overrides)
    return Publication(**defaults)


@pytest.fixture()
def db(tmp_path: Path) -> PubScoutDB:
    """Return a fresh SQLite-backed PubScoutDB in a temp directory."""
    return PubScoutDB(db_path=tmp_path / "test.db")


@pytest.fixture()
def dedup(db: PubScoutDB) -> Deduplicator:
    return Deduplicator(db)


# ── Intra-batch deduplication ────────────────────────────────────────


def test_dedup_by_arxiv_id(dedup: Deduplicator) -> None:
    pubs = [
        _make_pub(arxiv_id="2401.00001", matched_domains=["D1"]),
        _make_pub(arxiv_id="2401.00001", matched_domains=["D2"]),
    ]
    result = dedup.deduplicate(pubs)
    assert len(result) == 1
    assert set(result[0].matched_domains) == {"D1", "D2"}


def test_dedup_by_doi(dedup: Deduplicator) -> None:
    pubs = [
        _make_pub(doi="10.1234/foo", arxiv_id="a1", matched_domains=["D1"]),
        _make_pub(doi="10.1234/foo", arxiv_id="a2", matched_domains=["D2"]),
    ]
    result = dedup.deduplicate(pubs)
    assert len(result) == 1
    assert set(result[0].matched_domains) == {"D1", "D2"}


def test_dedup_by_title_similarity(dedup: Deduplicator) -> None:
    pubs = [
        _make_pub(
            title="A Novel Approach to Neural Architecture Search",
            matched_domains=["D1"],
        ),
        _make_pub(
            title="A Novel Approach to Neural Architecture Searching",
            matched_domains=["D2"],
        ),
    ]
    result = dedup.deduplicate(pubs)
    assert len(result) == 1
    assert set(result[0].matched_domains) == {"D1", "D2"}


def test_no_dedup_different_titles(dedup: Deduplicator) -> None:
    pubs = [
        _make_pub(title="Quantum Computing Basics"),
        _make_pub(title="Advanced Rocket Propulsion"),
    ]
    result = dedup.deduplicate(pubs)
    assert len(result) == 2


# ── Database deduplication ───────────────────────────────────────────


def test_dedup_against_database(db: PubScoutDB, dedup: Deduplicator) -> None:
    existing = _make_pub(arxiv_id="2401.99999")
    db.save_publication(existing)

    incoming = [
        _make_pub(arxiv_id="2401.99999"),
        _make_pub(arxiv_id="2401.00002", title="Unrelated Paper"),
    ]
    result = dedup.deduplicate(incoming)
    assert len(result) == 1
    assert result[0].arxiv_id == "2401.00002"


# ── Order preservation ───────────────────────────────────────────────


def test_preserves_order(dedup: Deduplicator) -> None:
    pubs = [
        _make_pub(title="Paper Alpha", arxiv_id="a1"),
        _make_pub(title="Paper Beta", arxiv_id="a2"),
        _make_pub(title="Paper Gamma", arxiv_id="a3"),
    ]
    result = dedup.deduplicate(pubs)
    assert [p.title for p in result] == ["Paper Alpha", "Paper Beta", "Paper Gamma"]


# ── Edge cases ───────────────────────────────────────────────────────


def test_empty_input(dedup: Deduplicator) -> None:
    assert dedup.deduplicate([]) == []


# ── Merge behaviour ──────────────────────────────────────────────────


def test_merge_combines_domains(dedup: Deduplicator) -> None:
    pubs = [
        _make_pub(arxiv_id="2401.00001", matched_domains=["D1"]),
        _make_pub(arxiv_id="2401.00001", matched_domains=["D2"]),
    ]
    result = dedup.deduplicate(pubs)
    assert result[0].matched_domains == ["D1", "D2"]


def test_no_duplicate_domains_after_merge(dedup: Deduplicator) -> None:
    pubs = [
        _make_pub(arxiv_id="2401.00001", matched_domains=["D1"]),
        _make_pub(arxiv_id="2401.00001", matched_domains=["D1"]),
    ]
    result = dedup.deduplicate(pubs)
    assert result[0].matched_domains == ["D1"]
