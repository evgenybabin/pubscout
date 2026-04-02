"""PubScout domain models — Pydantic v2 data classes for the scanning pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


# ── Configuration Models ─────────────────────────────────────────────


class Domain(BaseModel):
    """A research domain defined by a boolean query string."""

    label: str
    query: str
    enabled: bool = True


class Source(BaseModel):
    """An upstream publication source (API, RSS feed, or web scraper)."""

    label: str
    type: Literal["api", "rss", "web"]
    url: str
    adapter: str
    enabled: bool = True
    default: bool = False
    config: dict[str, Any] | None = None


class LLMConfig(BaseModel):
    """LLM provider settings for relevance scoring."""

    provider: str = "openai"
    model: str = "gpt-4o-mini"
    api_key: str | None = None
    endpoint: str | None = None


class ScoringConfig(BaseModel):
    """Relevance-scoring knobs and keyword filters."""

    threshold: float = Field(default=5.0, ge=1.0, le=10.0)
    include_keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)


class UserProfile(BaseModel):
    """Top-level user configuration combining domains, sources, and settings."""

    domains: list[Domain]
    sources: list[Source]
    email: str
    llm: LLMConfig = Field(default_factory=LLMConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)


# ── Runtime / Pipeline Models ────────────────────────────────────────


class Publication(BaseModel):
    """A single fetched publication with optional scoring metadata."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    authors: list[str]
    abstract: str
    url: str
    doi: str | None = None
    arxiv_id: str | None = None
    source_label: str
    publication_date: datetime | None = None
    fetch_date: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    relevance_score: float | None = None
    matched_domains: list[str] = Field(default_factory=list)
    reported: bool = False


class FeedbackSignal(BaseModel):
    """User feedback on a scored publication."""

    publication_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    signal: Literal["positive", "negative"]
    user_notes: str | None = None


class ScanRun(BaseModel):
    """Metadata for a single scan execution."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    sources_checked: int
    items_fetched: int
    items_scored: int
    items_reported: int
    errors: list[str] = Field(default_factory=list)
    duration_seconds: float | None = None
