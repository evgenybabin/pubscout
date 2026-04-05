"""Tests for the generic web scraper adapter."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from pubscout.adapters.web_adapter import WebAdapter
from pubscout.core.models import Domain, Source


@pytest.fixture()
def web_source() -> Source:
    return Source(
        label="Test Site",
        type="web",
        url="https://example.com/papers",
        adapter="web",
        enabled=True,
    )


@pytest.fixture()
def domains() -> list[Domain]:
    return [Domain(label="TestDomain", query="LLM AND inference")]


_HTML_JSON_LD = """\
<!DOCTYPE html><html><head>
<script type="application/ld+json">
{"@type": "ScholarlyArticle", "name": "Test Paper", "url": "https://example.com/paper1",
 "author": [{"name": "Alice"}], "description": "A test abstract."}
</script>
</head><body></body></html>"""

_HTML_ARTICLES = """\
<!DOCTYPE html><html><body>
<article><h2><a href="/paper1">Article One</a></h2></article>
<article><h2><a href="/paper2">Article Two</a></h2></article>
</body></html>"""

_HTML_HEADINGS = """\
<!DOCTYPE html><html><body>
<h2><a href="https://example.com/p1">Heading Paper 1</a></h2>
<h3><a href="https://example.com/p2">Heading Paper 2</a></h3>
</body></html>"""

_HTML_EMPTY = "<!DOCTYPE html><html><body><p>No papers here.</p></body></html>"


def _mock_get(url, **kwargs):
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    if "jsonld" in url:
        resp.text = _HTML_JSON_LD
    elif "articles" in url:
        resp.text = _HTML_ARTICLES
    elif "headings" in url:
        resp.text = _HTML_HEADINGS
    else:
        resp.text = _HTML_EMPTY
    return resp


class TestWebAdapter:
    @patch("pubscout.adapters.web_adapter.WebAdapter._robots_allowed", return_value=True)
    @patch("pubscout.adapters.web_adapter.httpx.get", side_effect=_mock_get)
    def test_json_ld_extraction(self, mock_get, mock_robots, domains):
        source = Source(label="Test", type="web", url="https://example.com/jsonld", adapter="web")
        adapter = WebAdapter()
        pubs = adapter.fetch(source, domains)
        assert len(pubs) == 1
        assert pubs[0].title == "Test Paper"
        assert pubs[0].authors == ["Alice"]
        assert pubs[0].abstract == "A test abstract."

    @patch("pubscout.adapters.web_adapter.WebAdapter._robots_allowed", return_value=True)
    @patch("pubscout.adapters.web_adapter.httpx.get", side_effect=_mock_get)
    def test_article_extraction(self, mock_get, mock_robots, domains):
        source = Source(label="Test", type="web", url="https://example.com/articles", adapter="web")
        adapter = WebAdapter()
        pubs = adapter.fetch(source, domains)
        assert len(pubs) == 2
        assert pubs[0].title == "Article One"
        assert pubs[1].title == "Article Two"

    @patch("pubscout.adapters.web_adapter.WebAdapter._robots_allowed", return_value=True)
    @patch("pubscout.adapters.web_adapter.httpx.get", side_effect=_mock_get)
    def test_heading_link_extraction(self, mock_get, mock_robots, domains):
        source = Source(label="Test", type="web", url="https://example.com/headings", adapter="web")
        adapter = WebAdapter()
        pubs = adapter.fetch(source, domains)
        assert len(pubs) == 2
        assert pubs[0].title == "Heading Paper 1"

    @patch("pubscout.adapters.web_adapter.WebAdapter._robots_allowed", return_value=True)
    @patch("pubscout.adapters.web_adapter.httpx.get", side_effect=_mock_get)
    def test_no_structure_returns_empty(self, mock_get, mock_robots, domains):
        source = Source(label="Test", type="web", url="https://example.com/empty", adapter="web")
        adapter = WebAdapter()
        pubs = adapter.fetch(source, domains)
        assert pubs == []

    @patch("pubscout.adapters.web_adapter.WebAdapter._robots_allowed", return_value=False)
    def test_robots_disallowed_returns_empty(self, mock_robots, web_source, domains):
        adapter = WebAdapter()
        pubs = adapter.fetch(web_source, domains)
        assert pubs == []

    @patch("pubscout.adapters.web_adapter.WebAdapter._robots_allowed", return_value=True)
    @patch(
        "pubscout.adapters.web_adapter.httpx.get",
        side_effect=httpx.ConnectError("refused"),
    )
    def test_connection_error_returns_empty(self, mock_get, mock_robots, web_source, domains):
        adapter = WebAdapter()
        pubs = adapter.fetch(web_source, domains)
        assert pubs == []

    @patch("pubscout.adapters.web_adapter.WebAdapter._robots_allowed", return_value=True)
    @patch("pubscout.adapters.web_adapter.httpx.get", side_effect=_mock_get)
    def test_url_resolution(self, mock_get, mock_robots, domains):
        """Relative URLs are resolved against the base URL."""
        source = Source(label="Test", type="web", url="https://example.com/articles", adapter="web")
        adapter = WebAdapter()
        pubs = adapter.fetch(source, domains)
        assert pubs[0].url.startswith("https://example.com")
