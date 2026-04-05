"""Tests for URL source type auto-detection."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import httpx
import pytest

from pubscout.core.source_detect import detect_source_type


_RSS_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item><title>Article 1</title><link>https://example.com/1</link></item>
    <item><title>Article 2</title><link>https://example.com/2</link></item>
    <item><title>Article 3</title><link>https://example.com/3</link></item>
  </channel>
</rss>"""

_ATOM_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Feed</title>
  <entry><title>Entry 1</title><link href="https://example.com/1"/></entry>
</feed>"""

_HTML_WITH_RSS = """\
<!DOCTYPE html><html><head>
<link rel="alternate" type="application/rss+xml" href="/feed.xml">
</head><body>Page</body></html>"""

_HTML_WITHOUT_RSS = """\
<!DOCTYPE html><html><head><title>No RSS</title></head>
<body><h1>Regular page</h1></body></html>"""


def _mock_get(url, **kwargs):
    """Factory for mock httpx.get responses."""
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {}

    if "feed.xml" in url or url.endswith("/rss"):
        resp.text = _RSS_XML
        resp.headers["content-type"] = "application/rss+xml"
    elif "atom" in url:
        resp.text = _ATOM_XML
        resp.headers["content-type"] = "application/atom+xml"
    elif "withrss" in url:
        resp.text = _HTML_WITH_RSS
        resp.headers["content-type"] = "text/html"
    else:
        resp.text = _HTML_WITHOUT_RSS
        resp.headers["content-type"] = "text/html"
    return resp


class TestDetectSourceType:
    @patch("pubscout.core.source_detect.httpx.get", side_effect=_mock_get)
    def test_rss_feed_detected(self, mock_get):
        result = detect_source_type("https://example.com/feed.xml")
        assert result.source_type == "rss"
        assert result.reachable is True
        assert result.feed_title == "Test Feed"
        assert len(result.sample_items) == 3

    @patch("pubscout.core.source_detect.httpx.get", side_effect=_mock_get)
    def test_atom_feed_detected(self, mock_get):
        result = detect_source_type("https://example.com/atom")
        assert result.source_type == "rss"
        assert result.reachable is True

    @patch("pubscout.core.source_detect.httpx.get", side_effect=_mock_get)
    def test_html_with_rss_link(self, mock_get):
        result = detect_source_type("https://example.com/withrss")
        assert result.source_type == "rss"
        assert result.reachable is True

    @patch("pubscout.core.source_detect.httpx.get", side_effect=_mock_get)
    def test_html_without_rss(self, mock_get):
        result = detect_source_type("https://example.com/plain")
        assert result.source_type == "web"
        assert result.reachable is True

    @patch(
        "pubscout.core.source_detect.httpx.get",
        side_effect=httpx.ConnectError("Connection refused"),
    )
    def test_unreachable_url(self, mock_get):
        result = detect_source_type("https://unreachable.example.com")
        assert result.reachable is False
        assert result.error is not None

    @patch(
        "pubscout.core.source_detect.httpx.get",
        side_effect=httpx.TimeoutException("timeout"),
    )
    def test_timeout(self, mock_get):
        result = detect_source_type("https://slow.example.com")
        assert result.reachable is False
        assert result.error is not None

    @patch("pubscout.core.source_detect.httpx.get", side_effect=_mock_get)
    def test_response_time_tracked(self, mock_get):
        result = detect_source_type("https://example.com/feed.xml")
        assert result.response_time_ms >= 0
