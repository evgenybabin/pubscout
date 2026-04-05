"""Tests for the Semantic Scholar adapter."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from pubscout.adapters.semantic_scholar import (
    SemanticScholarAdapter,
    _extract_search_terms,
)
from pubscout.core.models import Domain, Source


@pytest.fixture()
def s2_source() -> Source:
    return Source(
        label="Semantic Scholar",
        type="api",
        url="https://api.semanticscholar.org/graph/v1/paper/search",
        adapter="semantic_scholar",
        enabled=True,
        config={
            "fields": "title,authors,abstract,url,externalIds,publicationDate",
            "limit": 100,
            "api_key_env": "S2_API_KEY",
        },
    )


@pytest.fixture()
def domain() -> Domain:
    return Domain(label="TestDomain", query="LLM AND inference")


_SAMPLE_RESPONSE = {
    "data": [
        {
            "paperId": "abc123",
            "title": "Test Paper on LLM Inference",
            "authors": [{"name": "Alice"}, {"name": "Bob"}],
            "abstract": "We study LLM inference optimization.",
            "url": "https://api.semanticscholar.org/paper/abc123",
            "externalIds": {"DOI": "10.1234/test", "ArXiv": "2401.00001"},
            "publicationDate": "2024-01-15",
        },
    ]
}


def _mock_get_ok(*args, **kwargs):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = _SAMPLE_RESPONSE
    resp.raise_for_status = MagicMock()
    return resp


def _mock_get_empty(*args, **kwargs):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"data": []}
    resp.raise_for_status = MagicMock()
    return resp


def _mock_get_429(*args, **kwargs):
    resp = MagicMock()
    resp.status_code = 429
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "429", request=MagicMock(), response=resp
    )
    return resp


class TestSemanticScholarAdapter:
    @patch("pubscout.adapters.semantic_scholar.httpx.get", side_effect=_mock_get_ok)
    def test_successful_fetch(self, mock_get, s2_source, domain):
        adapter = SemanticScholarAdapter()
        pubs = adapter.fetch(s2_source, [domain])
        assert len(pubs) == 1
        pub = pubs[0]
        assert pub.title == "Test Paper on LLM Inference"
        assert pub.authors == ["Alice", "Bob"]
        assert pub.doi == "10.1234/test"
        assert pub.arxiv_id == "2401.00001"
        assert "TestDomain" in pub.matched_domains

    @patch("pubscout.adapters.semantic_scholar.httpx.get", side_effect=_mock_get_ok)
    def test_author_format_mapping(self, mock_get, s2_source, domain):
        adapter = SemanticScholarAdapter()
        pubs = adapter.fetch(s2_source, [domain])
        assert pubs[0].authors == ["Alice", "Bob"]

    @patch("pubscout.adapters.semantic_scholar.httpx.get", side_effect=_mock_get_ok)
    def test_doi_extraction(self, mock_get, s2_source, domain):
        adapter = SemanticScholarAdapter()
        pubs = adapter.fetch(s2_source, [domain])
        assert pubs[0].doi == "10.1234/test"

    @patch("pubscout.adapters.semantic_scholar.httpx.get", side_effect=_mock_get_ok)
    def test_api_key_header(self, mock_get, s2_source, domain, monkeypatch):
        monkeypatch.setenv("S2_API_KEY", "my-key")
        adapter = SemanticScholarAdapter()
        adapter.fetch(s2_source, [domain])
        call_kwargs = mock_get.call_args
        assert call_kwargs.kwargs["headers"].get("x-api-key") == "my-key"

    @patch("pubscout.adapters.semantic_scholar.httpx.get", side_effect=_mock_get_empty)
    def test_empty_results(self, mock_get, s2_source, domain):
        adapter = SemanticScholarAdapter()
        pubs = adapter.fetch(s2_source, [domain])
        assert pubs == []

    @patch("pubscout.adapters.semantic_scholar.httpx.get")
    def test_api_error_429_retry(self, mock_get, s2_source, domain):
        """429 triggers one retry; second 429 returns empty."""
        resp_429 = MagicMock()
        resp_429.status_code = 429
        mock_get.return_value = resp_429
        adapter = SemanticScholarAdapter()
        pubs = adapter.fetch(s2_source, [domain])
        assert pubs == []
        assert mock_get.call_count >= 2  # initial + retry

    @patch(
        "pubscout.adapters.semantic_scholar.httpx.get",
        side_effect=httpx.ConnectError("unreachable"),
    )
    def test_network_error(self, mock_get, s2_source, domain):
        adapter = SemanticScholarAdapter()
        pubs = adapter.fetch(s2_source, [domain])
        assert pubs == []

    @patch("pubscout.adapters.semantic_scholar.httpx.get", side_effect=_mock_get_ok)
    def test_publication_date_parsed(self, mock_get, s2_source, domain):
        adapter = SemanticScholarAdapter()
        pubs = adapter.fetch(s2_source, [domain])
        assert pubs[0].publication_date is not None
        assert pubs[0].publication_date.year == 2024


class TestExtractSearchTerms:
    def test_strips_operators(self):
        result = _extract_search_terms('"large language model" AND inference')
        assert "AND" not in result
        assert "large language model" in result
        assert "inference" in result

    def test_strips_parens_and_quotes(self):
        result = _extract_search_terms('("LLM" OR "transformer") AND (serving)')
        assert "(" not in result
        assert '"' not in result
        assert "LLM" in result
