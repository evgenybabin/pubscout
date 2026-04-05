"""Tests for the RSS/Atom feed adapter."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from pubscout.adapters.rss_adapter import RssAdapter, _strip_html
from pubscout.core.models import Domain, Publication, Source


@pytest.fixture()
def rss_source() -> Source:
    return Source(
        label="Test RSS",
        type="rss",
        url="https://example.com/feed.xml",
        adapter="rss",
        enabled=True,
    )


@pytest.fixture()
def domains() -> list[Domain]:
    return [Domain(label="TestDomain", query="LLM AND inference")]


_RSS_FEED = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>Paper One</title>
      <link>https://example.com/paper1</link>
      <description>&lt;p&gt;This is about &lt;b&gt;LLM inference&lt;/b&gt;.&lt;/p&gt;</description>
      <author>Alice</author>
      <pubDate>Mon, 15 Jan 2024 00:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Paper Two</title>
      <link>https://example.com/paper2</link>
      <description>Plain text abstract.</description>
    </item>
  </channel>
</rss>"""

_ATOM_FEED = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Feed</title>
  <entry>
    <title>Atom Paper</title>
    <link href="https://example.com/atom1"/>
    <summary>Atom summary</summary>
    <author><name>Bob</name></author>
    <published>2024-02-01T00:00:00Z</published>
  </entry>
</feed>"""

_EMPTY_FEED = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Empty</title></channel></rss>"""

_MALFORMED_XML = "This is not XML at all <><><<"

# Parse fixtures BEFORE any patches — feedparser is a real import here
import feedparser as _fp

_PARSED_RSS = _fp.parse(_RSS_FEED)
_PARSED_ATOM = _fp.parse(_ATOM_FEED)
_PARSED_EMPTY = _fp.parse(_EMPTY_FEED)
_PARSED_MALFORMED = _fp.parse(_MALFORMED_XML)


class TestRssAdapter:
    @patch("pubscout.adapters.rss_adapter.feedparser.parse")
    def test_rss_feed_parsed(self, mock_parse, rss_source, domains):
        mock_parse.return_value = _PARSED_RSS
        adapter = RssAdapter()
        pubs = adapter.fetch(rss_source, domains)
        assert len(pubs) == 2
        assert pubs[0].title == "Paper One"
        assert pubs[1].title == "Paper Two"

    @patch("pubscout.adapters.rss_adapter.feedparser.parse")
    def test_atom_feed_parsed(self, mock_parse, rss_source, domains):
        mock_parse.return_value = _PARSED_ATOM
        adapter = RssAdapter()
        pubs = adapter.fetch(rss_source, domains)
        assert len(pubs) == 1
        assert pubs[0].title == "Atom Paper"
        assert pubs[0].authors == ["Bob"]

    @patch("pubscout.adapters.rss_adapter.feedparser.parse")
    def test_html_content_stripped(self, mock_parse, rss_source, domains):
        mock_parse.return_value = _PARSED_RSS
        adapter = RssAdapter()
        pubs = adapter.fetch(rss_source, domains)
        assert len(pubs) >= 1
        assert "<p>" not in pubs[0].abstract
        assert "<b>" not in pubs[0].abstract
        assert "LLM inference" in pubs[0].abstract

    @patch("pubscout.adapters.rss_adapter.feedparser.parse")
    def test_missing_author(self, mock_parse, rss_source, domains):
        mock_parse.return_value = _PARSED_RSS
        adapter = RssAdapter()
        pubs = adapter.fetch(rss_source, domains)
        assert isinstance(pubs[1].authors, list)

    @patch("pubscout.adapters.rss_adapter.feedparser.parse")
    def test_empty_feed(self, mock_parse, rss_source, domains):
        mock_parse.return_value = _PARSED_EMPTY
        adapter = RssAdapter()
        pubs = adapter.fetch(rss_source, domains)
        assert pubs == []

    @patch("pubscout.adapters.rss_adapter.feedparser.parse")
    def test_malformed_xml(self, mock_parse, rss_source, domains):
        mock_parse.return_value = _PARSED_MALFORMED
        adapter = RssAdapter()
        pubs = adapter.fetch(rss_source, domains)
        assert pubs == []

    @patch("pubscout.adapters.rss_adapter.feedparser.parse")
    def test_multiple_entries_order_preserved(self, mock_parse, rss_source, domains):
        mock_parse.return_value = _PARSED_RSS
        adapter = RssAdapter()
        pubs = adapter.fetch(rss_source, domains)
        assert pubs[0].title == "Paper One"
        assert pubs[1].title == "Paper Two"

    @patch("pubscout.adapters.rss_adapter.feedparser.parse")
    def test_publication_date_parsed(self, mock_parse, rss_source, domains):
        mock_parse.return_value = _PARSED_RSS
        adapter = RssAdapter()
        pubs = adapter.fetch(rss_source, domains)
        assert pubs[0].publication_date is not None


class TestStripHtml:
    def test_strips_tags(self):
        assert _strip_html("<p>Hello <b>world</b></p>") == "Hello world"

    def test_unescapes_entities(self):
        assert _strip_html("&amp; &lt;") == "& <"

    def test_empty_string(self):
        assert _strip_html("") == ""
