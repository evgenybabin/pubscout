"""Unit tests for PubScout SQLite storage layer."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from pubscout.core.models import FeedbackSignal, Publication, ScanRun
from pubscout.storage.database import PubScoutDB


@pytest.fixture()
def db(tmp_path):
    """Yield a PubScoutDB backed by a temp file, then close it."""
    instance = PubScoutDB(db_path=tmp_path / "test.db")
    yield instance
    instance.close()


def _make_pub(**overrides) -> Publication:
    defaults = dict(
        title="Test Paper",
        authors=["Alice", "Bob"],
        abstract="An abstract about ML.",
        url="https://arxiv.org/abs/2401.00001",
        source_label="arXiv",
        arxiv_id="2401.00001",
        doi="10.1234/test",
        relevance_score=7.5,
        matched_domains=["ML", "AI"],
    )
    defaults.update(overrides)
    return Publication(**defaults)


# ── Schema ───────────────────────────────────────────────────────────


class TestSchema:
    def test_schema_created_on_init(self, db: PubScoutDB):
        tables = {
            row[0]
            for row in db._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "publications" in tables
        assert "scan_runs" in tables
        assert "feedback" in tables


# ── Publications ─────────────────────────────────────────────────────


class TestPublications:
    def test_save_and_retrieve(self, db: PubScoutDB):
        pub = _make_pub()
        db.save_publication(pub)

        loaded = db.get_publication(pub.id)
        assert loaded is not None
        assert loaded.id == pub.id
        assert loaded.title == "Test Paper"
        assert loaded.authors == ["Alice", "Bob"]
        assert loaded.arxiv_id == "2401.00001"
        assert loaded.doi == "10.1234/test"
        assert loaded.relevance_score == 7.5
        assert loaded.matched_domains == ["ML", "AI"]
        assert loaded.reported is False

    def test_get_nonexistent_returns_none(self, db: PubScoutDB):
        assert db.get_publication("no-such-id") is None

    def test_publication_exists_by_arxiv_id(self, db: PubScoutDB):
        pub = _make_pub()
        db.save_publication(pub)

        assert db.publication_exists(arxiv_id="2401.00001") is True

    def test_publication_exists_by_doi(self, db: PubScoutDB):
        pub = _make_pub(arxiv_id=None)
        db.save_publication(pub)

        assert db.publication_exists(doi="10.1234/test") is True

    def test_publication_exists_by_title(self, db: PubScoutDB):
        pub = _make_pub(arxiv_id=None, doi=None)
        db.save_publication(pub)

        assert db.publication_exists(title="Test Paper") is True

    def test_publication_exists_unknown_returns_false(self, db: PubScoutDB):
        assert db.publication_exists(arxiv_id="nope") is False
        assert db.publication_exists(doi="nope") is False
        assert db.publication_exists(title="nope") is False

    def test_publication_exists_no_args_returns_false(self, db: PubScoutDB):
        assert db.publication_exists() is False

    def test_get_unreported_filters_by_score_and_reported(self, db: PubScoutDB):
        high = _make_pub(relevance_score=9.0, arxiv_id="2401.00010", doi="10.1234/high")
        low = _make_pub(relevance_score=2.0, arxiv_id="2401.00020", doi="10.1234/low")
        already_reported = _make_pub(
            relevance_score=8.0, reported=True, arxiv_id="2401.00030", doi="10.1234/rep"
        )
        no_score = _make_pub(relevance_score=None, arxiv_id="2401.99999", doi=None)

        for p in (high, low, already_reported, no_score):
            db.save_publication(p)

        result = db.get_unreported_publications(min_score=5.0)
        ids = [p.id for p in result]
        assert high.id in ids
        assert low.id not in ids
        assert already_reported.id not in ids
        assert no_score.id not in ids

    def test_mark_reported(self, db: PubScoutDB):
        pub = _make_pub()
        db.save_publication(pub)

        db.mark_reported([pub.id])
        loaded = db.get_publication(pub.id)
        assert loaded is not None
        assert loaded.reported is True

    def test_mark_reported_empty_list(self, db: PubScoutDB):
        db.mark_reported([])  # should not raise


# ── Scan Runs ────────────────────────────────────────────────────────


class TestScanRuns:
    def test_save_and_retrieve(self, db: PubScoutDB):
        run = ScanRun(
            sources_checked=3,
            items_fetched=100,
            items_scored=80,
            items_reported=10,
            errors=["timeout on source X"],
            duration_seconds=12.5,
        )
        db.save_scan_run(run)

        runs = db.get_scan_runs(limit=5)
        assert len(runs) == 1
        assert runs[0].id == run.id
        assert runs[0].sources_checked == 3
        assert runs[0].errors == ["timeout on source X"]
        assert runs[0].duration_seconds == 12.5

    def test_get_last_scan_time(self, db: PubScoutDB):
        r1 = ScanRun(
            sources_checked=1, items_fetched=0, items_scored=0, items_reported=0
        )
        r2 = ScanRun(
            sources_checked=2, items_fetched=0, items_scored=0, items_reported=0
        )
        db.save_scan_run(r1)
        db.save_scan_run(r2)

        last = db.get_last_scan_time()
        assert last is not None
        # Should be the later of the two timestamps
        assert last >= r1.timestamp

    def test_get_last_scan_time_empty(self, db: PubScoutDB):
        assert db.get_last_scan_time() is None


# ── Feedback ─────────────────────────────────────────────────────────


class TestFeedback:
    def test_save_and_retrieve_feedback(self, db: PubScoutDB):
        pub = _make_pub()
        db.save_publication(pub)

        fb = FeedbackSignal(
            publication_id=pub.id, signal="positive", user_notes="Great paper"
        )
        db.save_feedback(fb)

        results = db.get_feedback(limit=10)
        assert len(results) == 1
        assert results[0].signal == "positive"
        assert results[0].user_notes == "Great paper"

    def test_get_positive_examples(self, db: PubScoutDB):
        good = _make_pub(title="Good Paper")
        bad = _make_pub(title="Bad Paper", arxiv_id="2401.00002", doi="10.1234/bad")
        db.save_publication(good)
        db.save_publication(bad)

        db.save_feedback(FeedbackSignal(publication_id=good.id, signal="positive"))
        db.save_feedback(FeedbackSignal(publication_id=bad.id, signal="negative"))

        positives = db.get_positive_examples()
        assert len(positives) == 1
        assert positives[0].title == "Good Paper"

    def test_get_negative_examples(self, db: PubScoutDB):
        good = _make_pub(title="Good Paper")
        bad = _make_pub(title="Bad Paper", arxiv_id="2401.00002", doi="10.1234/bad")
        db.save_publication(good)
        db.save_publication(bad)

        db.save_feedback(FeedbackSignal(publication_id=good.id, signal="positive"))
        db.save_feedback(FeedbackSignal(publication_id=bad.id, signal="negative"))

        negatives = db.get_negative_examples()
        assert len(negatives) == 1
        assert negatives[0].title == "Bad Paper"
