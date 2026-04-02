"""Unit tests for PubScout Pydantic models."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from pubscout.core.models import (
    Domain,
    FeedbackSignal,
    LLMConfig,
    Publication,
    ScanRun,
    ScoringConfig,
    Source,
    UserProfile,
)


# ── Domain ───────────────────────────────────────────────────────────


class TestDomain:
    def test_create_minimal(self):
        d = Domain(label="ML", query="machine learning")
        assert d.label == "ML"
        assert d.query == "machine learning"
        assert d.enabled is True  # default

    def test_disabled(self):
        d = Domain(label="Bio", query="genomics", enabled=False)
        assert d.enabled is False


# ── Source ───────────────────────────────────────────────────────────


class TestSource:
    def test_create_api_source(self):
        s = Source(
            label="arXiv",
            type="api",
            url="https://arxiv.org",
            adapter="arxiv",
        )
        assert s.type == "api"
        assert s.enabled is True
        assert s.default is False
        assert s.config is None

    def test_with_config(self):
        s = Source(
            label="PubMed",
            type="api",
            url="https://pubmed.ncbi.nlm.nih.gov",
            adapter="pubmed",
            default=True,
            config={"max_results": 50, "rate_limit_seconds": 1},
        )
        assert s.default is True
        assert s.config["max_results"] == 50

    def test_invalid_type_rejected(self):
        with pytest.raises(ValidationError):
            Source(label="Bad", type="ftp", url="ftp://x", adapter="x")


# ── LLMConfig ────────────────────────────────────────────────────────


class TestLLMConfig:
    def test_defaults(self):
        c = LLMConfig()
        assert c.provider == "openai"
        assert c.model == "gpt-4o-mini"
        assert c.api_key is None


# ── ScoringConfig ────────────────────────────────────────────────────


class TestScoringConfig:
    def test_defaults(self):
        sc = ScoringConfig()
        assert sc.threshold == 5.0
        assert sc.include_keywords == []
        assert sc.exclude_keywords == []

    def test_valid_threshold_boundaries(self):
        assert ScoringConfig(threshold=1.0).threshold == 1.0
        assert ScoringConfig(threshold=10.0).threshold == 10.0

    def test_threshold_below_range(self):
        with pytest.raises(ValidationError):
            ScoringConfig(threshold=0.5)

    def test_threshold_above_range(self):
        with pytest.raises(ValidationError):
            ScoringConfig(threshold=10.1)


# ── UserProfile ──────────────────────────────────────────────────────


class TestUserProfile:
    def test_create_profile(self):
        p = UserProfile(
            domains=[Domain(label="AI", query="artificial intelligence")],
            sources=[Source(label="arXiv", type="api", url="https://arxiv.org", adapter="arxiv")],
            email="user@example.com",
        )
        assert len(p.domains) == 1
        assert p.llm.provider == "openai"
        assert p.scoring.threshold == 5.0


# ── Publication ──────────────────────────────────────────────────────


class TestPublication:
    def test_auto_id_and_fetch_date(self):
        pub = Publication(
            title="Test Paper",
            authors=["Alice"],
            abstract="An abstract.",
            url="https://example.com/paper",
            source_label="arXiv",
        )
        # id is a valid UUID
        UUID(pub.id)
        assert isinstance(pub.fetch_date, datetime)
        assert pub.fetch_date.tzinfo is not None

    def test_two_publications_get_unique_ids(self):
        kwargs = dict(
            title="P", authors=[], abstract="A", url="https://x.com", source_label="src"
        )
        p1 = Publication(**kwargs)
        p2 = Publication(**kwargs)
        assert p1.id != p2.id

    def test_defaults(self):
        pub = Publication(
            title="T", authors=[], abstract="A", url="https://x.com", source_label="s"
        )
        assert pub.doi is None
        assert pub.relevance_score is None
        assert pub.matched_domains == []
        assert pub.reported is False

    def test_optional_fields(self):
        pub = Publication(
            title="T",
            authors=["Bob"],
            abstract="A",
            url="https://x.com",
            source_label="s",
            doi="10.1234/test",
            arxiv_id="2401.00001",
            relevance_score=8.5,
            matched_domains=["ML"],
        )
        assert pub.doi == "10.1234/test"
        assert pub.relevance_score == 8.5


# ── FeedbackSignal ───────────────────────────────────────────────────


class TestFeedbackSignal:
    def test_create(self):
        fb = FeedbackSignal(publication_id="abc-123", signal="positive")
        assert fb.signal == "positive"
        assert isinstance(fb.timestamp, datetime)

    def test_invalid_signal_rejected(self):
        with pytest.raises(ValidationError):
            FeedbackSignal(publication_id="x", signal="neutral")


# ── ScanRun ──────────────────────────────────────────────────────────


class TestScanRun:
    def test_auto_fields(self):
        run = ScanRun(
            sources_checked=3, items_fetched=100, items_scored=80, items_reported=10
        )
        UUID(run.id)
        assert isinstance(run.timestamp, datetime)
        assert run.errors == []
        assert run.duration_seconds is None

    def test_with_errors(self):
        run = ScanRun(
            sources_checked=1,
            items_fetched=0,
            items_scored=0,
            items_reported=0,
            errors=["Timeout on source X"],
            duration_seconds=12.5,
        )
        assert len(run.errors) == 1
        assert run.duration_seconds == 12.5
