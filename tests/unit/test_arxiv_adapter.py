"""Unit tests for ArxivAdapter — all arXiv API calls are mocked."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from pubscout.adapters.arxiv_adapter import ArxivAdapter
from pubscout.core.models import Domain, Source


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_source(**overrides) -> Source:
    defaults = {
        "label": "arxiv",
        "type": "api",
        "url": "https://arxiv.org",
        "adapter": "arxiv",
        "config": {"max_results_per_query": 50, "rate_limit_seconds": 0, "categories": ["cs.AI"]},
    }
    defaults.update(overrides)
    return Source(**defaults)


def _make_domain(label: str = "ML", query: str = '"machine learning"', enabled: bool = True) -> Domain:
    return Domain(label=label, query=query, enabled=enabled)


def _fake_result(
    entry_id: str = "http://arxiv.org/abs/2401.12345v1",
    title: str = "Test Paper",
    summary: str = "An abstract about ML.",
    authors: list[str] | None = None,
    published: datetime | None = None,
    doi: str | None = None,
) -> MagicMock:
    """Build a mock that quacks like :class:`arxiv.Result`."""
    r = MagicMock()
    r.title = title
    r.summary = summary
    r.entry_id = entry_id
    r.published = published or datetime(2024, 1, 15, tzinfo=timezone.utc)
    r.doi = doi

    author_names = authors or ["Alice Author", "Bob Researcher"]
    author_mocks = []
    for aname in author_names:
        a = MagicMock()
        a.name = aname
        author_mocks.append(a)
    r.authors = author_mocks

    r.get_short_id.return_value = entry_id.split("/")[-1]
    return r


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestArxivAdapter:
    """Tests for :class:`ArxivAdapter`."""

    @patch("pubscout.adapters.arxiv_adapter.arxiv")
    def test_fetch_converts_results_to_publications(self, mock_arxiv):
        """Three mock results should produce three Publication objects."""
        results = [
            _fake_result(entry_id=f"http://arxiv.org/abs/2401.{i:05d}v1", title=f"Paper {i}")
            for i in range(3)
        ]
        mock_client = MagicMock()
        mock_client.results.return_value = iter(results)
        mock_arxiv.Client.return_value = mock_client
        mock_arxiv.Search = MagicMock()
        mock_arxiv.SortCriterion.SubmittedDate = "submittedDate"

        adapter = ArxivAdapter()
        pubs = adapter.fetch(_make_source(), [_make_domain()])

        assert len(pubs) == 3
        assert pubs[0].title == "Paper 0"
        assert pubs[0].source_label == "arxiv"
        assert pubs[0].matched_domains == ["ML"]

    @patch("pubscout.adapters.arxiv_adapter.arxiv")
    def test_fetch_deduplicates_across_domains(self, mock_arxiv):
        """Same arxiv_id from two domains → one publication with both labels."""
        shared = _fake_result(entry_id="http://arxiv.org/abs/2401.99999v1")

        call_count = 0

        def _results_side_effect(search):
            nonlocal call_count
            call_count += 1
            return iter([shared])

        mock_client = MagicMock()
        mock_client.results.side_effect = _results_side_effect
        mock_arxiv.Client.return_value = mock_client
        mock_arxiv.Search = MagicMock()
        mock_arxiv.SortCriterion.SubmittedDate = "submittedDate"

        domains = [_make_domain(label="ML"), _make_domain(label="NLP", query='"natural language"')]
        adapter = ArxivAdapter()
        pubs = adapter.fetch(_make_source(), domains)

        assert len(pubs) == 1
        assert set(pubs[0].matched_domains) == {"ML", "NLP"}

    @patch("pubscout.adapters.arxiv_adapter.arxiv")
    def test_fetch_skips_disabled_domains(self, mock_arxiv):
        """Disabled domains must not trigger any API calls."""
        mock_client = MagicMock()
        mock_client.results.return_value = iter([])
        mock_arxiv.Client.return_value = mock_client
        mock_arxiv.Search = MagicMock()
        mock_arxiv.SortCriterion.SubmittedDate = "submittedDate"

        domains = [
            _make_domain(label="active"),
            _make_domain(label="disabled", enabled=False),
        ]
        adapter = ArxivAdapter()
        adapter.fetch(_make_source(), domains)

        # Only one Search should have been constructed (for the active domain)
        assert mock_arxiv.Search.call_count == 1

    @patch("pubscout.adapters.arxiv_adapter.arxiv")
    def test_fetch_handles_api_error_gracefully(self, mock_arxiv):
        """An exception in one domain should not prevent others from returning results."""
        good_result = _fake_result(entry_id="http://arxiv.org/abs/2401.00001v1", title="Good")

        call_count = 0

        def _results_side_effect(search):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("network blip")
            return iter([good_result])

        mock_client = MagicMock()
        mock_client.results.side_effect = _results_side_effect
        mock_arxiv.Client.return_value = mock_client
        mock_arxiv.Search = MagicMock()
        mock_arxiv.SortCriterion.SubmittedDate = "submittedDate"

        domains = [_make_domain(label="failing"), _make_domain(label="ok", query='"deep learning"')]
        adapter = ArxivAdapter()
        pubs = adapter.fetch(_make_source(), domains)

        assert len(pubs) == 1
        assert pubs[0].title == "Good"

    def test_build_query_includes_categories(self):
        """Categories should appear as 'cat:' clauses in the generated query."""
        adapter = ArxivAdapter()
        query_str = adapter._build_query(_make_domain(query="transformers"), ["cs.AI", "cs.LG"])

        assert "cat:cs.AI" in query_str
        assert "cat:cs.LG" in query_str

    @patch("pubscout.adapters.arxiv_adapter.arxiv")
    def test_result_to_publication_maps_fields(self, mock_arxiv):
        """All arxiv.Result fields should map to the correct Publication fields."""
        result = _fake_result(
            entry_id="http://arxiv.org/abs/2401.56789v1",
            title="Attention Is All You Need",
            summary="We propose the Transformer architecture.",
            authors=["Ashish Vaswani", "Noam Shazeer"],
            published=datetime(2024, 6, 1, tzinfo=timezone.utc),
            doi="10.1234/fake.doi",
        )

        adapter = ArxivAdapter()
        pub = adapter._result_to_publication(result, "arxiv-source", "NLP")

        assert pub.title == "Attention Is All You Need"
        assert pub.authors == ["Ashish Vaswani", "Noam Shazeer"]
        assert pub.abstract == "We propose the Transformer architecture."
        assert pub.url == "http://arxiv.org/abs/2401.56789v1"
        assert pub.arxiv_id == "2401.56789v1"
        assert pub.doi == "10.1234/fake.doi"
        assert pub.source_label == "arxiv-source"
        assert pub.publication_date == datetime(2024, 6, 1, tzinfo=timezone.utc)
        assert pub.matched_domains == ["NLP"]

    @patch("pubscout.adapters.arxiv_adapter.arxiv")
    def test_fetch_respects_max_results(self, mock_arxiv):
        """max_results from source config must be forwarded to arxiv.Search."""
        mock_client = MagicMock()
        mock_client.results.return_value = iter([])
        mock_arxiv.Client.return_value = mock_client
        mock_arxiv.Search = MagicMock()
        mock_arxiv.SortCriterion.SubmittedDate = "submittedDate"

        source = _make_source(config={"max_results_per_query": 42, "rate_limit_seconds": 0})
        adapter = ArxivAdapter()
        adapter.fetch(source, [_make_domain()])

        _, kwargs = mock_arxiv.Search.call_args
        assert kwargs["max_results"] == 42
