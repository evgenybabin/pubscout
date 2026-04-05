"""URL type auto-detection for PubScout source management."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import feedparser
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass
class SourceDetectionResult:
    """Result of probing a URL to determine its source type."""

    source_type: str  # "rss", "web", "api"
    feed_title: str | None = None
    sample_items: list[dict] = field(default_factory=list)
    reachable: bool = False
    response_time_ms: int = 0
    error: str | None = None


def detect_source_type(url: str, timeout: float = 15.0) -> SourceDetectionResult:
    """Probe *url* and return a :class:`SourceDetectionResult`.

    Detection strategy (per spec-v2 S3 heuristics):
    1. HTTP GET with RSS Accept headers.
    2. If XML content-type → parse with feedparser → if entries → "rss".
    3. If HTML → scan for ``<link rel="alternate" type="application/rss+xml">`` → follow → retry.
    4. If HTML with no RSS link → "web".
    """
    start = time.monotonic()
    try:
        resp = httpx.get(
            url,
            headers={"Accept": "application/rss+xml, application/atom+xml, text/xml, */*"},
            timeout=timeout,
            follow_redirects=True,
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)
    except (httpx.ConnectError, httpx.TimeoutException, httpx.RequestError) as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return SourceDetectionResult(
            source_type="web",
            reachable=False,
            response_time_ms=elapsed_ms,
            error=str(exc),
        )

    content_type = resp.headers.get("content-type", "")

    # XML-ish content type → try as feed
    if any(ct in content_type for ct in ("xml", "rss", "atom")):
        return _try_parse_feed(url, resp.text, elapsed_ms)

    # HTML → look for RSS <link> or fall back to "web"
    if "html" in content_type:
        rss_url = _find_rss_link(resp.text, url)
        if rss_url:
            return _follow_rss_link(rss_url, elapsed_ms)
        return SourceDetectionResult(
            source_type="web",
            reachable=True,
            response_time_ms=elapsed_ms,
        )

    # Fallback: try parsing as feed anyway
    result = _try_parse_feed(url, resp.text, elapsed_ms)
    if result.source_type == "rss":
        return result

    return SourceDetectionResult(
        source_type="web",
        reachable=True,
        response_time_ms=elapsed_ms,
    )


# ── helpers ─────────────────────────────────────────────────────────


def _try_parse_feed(url: str, text: str, elapsed_ms: int) -> SourceDetectionResult:
    """Attempt to parse *text* as an RSS/Atom feed."""
    feed = feedparser.parse(text)
    if feed.entries:
        samples = [
            {"title": e.get("title", ""), "link": e.get("link", "")}
            for e in feed.entries[:3]
        ]
        return SourceDetectionResult(
            source_type="rss",
            feed_title=feed.feed.get("title"),
            sample_items=samples,
            reachable=True,
            response_time_ms=elapsed_ms,
        )
    return SourceDetectionResult(
        source_type="web",
        reachable=True,
        response_time_ms=elapsed_ms,
    )


def _find_rss_link(html: str, base_url: str) -> str | None:
    """Search HTML for ``<link rel="alternate" type="application/rss+xml">``."""
    soup = BeautifulSoup(html, "html.parser")
    link = soup.find("link", attrs={"type": "application/rss+xml"})
    if link and link.get("href"):
        href = link["href"]
        if href.startswith("http"):
            return href
        # Relative URL
        from urllib.parse import urljoin

        return urljoin(base_url, href)
    return None


def _follow_rss_link(rss_url: str, parent_elapsed_ms: int) -> SourceDetectionResult:
    """Fetch the discovered RSS URL and parse it."""
    try:
        start = time.monotonic()
        resp = httpx.get(rss_url, timeout=10.0, follow_redirects=True)
        elapsed_ms = int((time.monotonic() - start) * 1000) + parent_elapsed_ms
        return _try_parse_feed(rss_url, resp.text, elapsed_ms)
    except Exception as exc:
        return SourceDetectionResult(
            source_type="rss",
            reachable=False,
            response_time_ms=parent_elapsed_ms,
            error=f"RSS link found but unreachable: {exc}",
        )
