"""Semantic Scholar API adapter for PubScout."""

from __future__ import annotations

import logging
import os
import re
import time

import httpx

from pubscout.core.models import Domain, Publication, Source

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
_RATE_WINDOW = 300  # 5 minutes
_RATE_LIMIT = 10  # max requests per window (unauthenticated)


class SemanticScholarAdapter:
    """Fetch publications from the Semantic Scholar API."""

    def __init__(self) -> None:
        self._request_times: list[float] = []

    def fetch(self, source: Source, domains: list[Domain]) -> list[Publication]:
        config = source.config or {}
        fields = config.get(
            "fields",
            "title,authors,abstract,url,externalIds,publicationDate",
        )
        limit = config.get("limit", 100)
        api_key = self._resolve_api_key(config)

        seen: dict[str, Publication] = {}
        enabled_domains = [d for d in domains if d.enabled]

        for domain in enabled_domains:
            terms = _extract_search_terms(domain.query)
            if not terms:
                continue
            try:
                data = self._search(terms, fields, limit, api_key)
                for paper in data:
                    pub = self._paper_to_publication(paper, source.label, domain.label)
                    key = pub.doi or pub.id
                    if key in seen:
                        if domain.label not in seen[key].matched_domains:
                            seen[key].matched_domains.append(domain.label)
                    else:
                        seen[key] = pub
            except Exception:
                logger.warning(
                    "S2 search failed for domain '%s'; skipping.",
                    domain.label,
                    exc_info=True,
                )

        publications = list(seen.values())
        logger.info(
            "Total unique publications from Semantic Scholar: %d", len(publications)
        )
        return publications

    # ── private helpers ──────────────────────────────────────

    def _resolve_api_key(self, config: dict) -> str | None:
        env_var = config.get("api_key_env", "S2_API_KEY")
        return os.environ.get(env_var)

    def _search(
        self, query: str, fields: str, limit: int, api_key: str | None
    ) -> list[dict]:
        self._enforce_rate_limit()

        headers: dict[str, str] = {}
        if api_key:
            headers["x-api-key"] = api_key

        params = {"query": query, "fields": fields, "limit": min(limit, 100)}

        try:
            resp = httpx.get(
                _BASE_URL,
                params=params,
                headers=headers,
                timeout=30.0,
            )
            if resp.status_code == 429:
                logger.warning("S2 rate limited (429) — retrying once after 5s")
                time.sleep(5)
                resp = httpx.get(
                    _BASE_URL,
                    params=params,
                    headers=headers,
                    timeout=30.0,
                )
                if resp.status_code == 429:
                    logger.warning("S2 still rate limited — returning empty")
                    return []

            resp.raise_for_status()
            data = resp.json()
            return data.get("data", [])
        except httpx.HTTPStatusError:
            logger.warning("S2 API error for query '%s'", query, exc_info=True)
            return []
        except (httpx.RequestError, Exception):
            logger.warning("S2 request error for query '%s'", query, exc_info=True)
            return []

    def _enforce_rate_limit(self) -> None:
        now = time.time()
        self._request_times = [t for t in self._request_times if now - t < _RATE_WINDOW]
        if len(self._request_times) >= _RATE_LIMIT:
            wait = _RATE_WINDOW - (now - self._request_times[0]) + 1
            logger.info("S2 rate limit: sleeping %.1fs", wait)
            time.sleep(wait)
        self._request_times.append(time.time())

    @staticmethod
    def _paper_to_publication(
        paper: dict, source_label: str, domain_label: str
    ) -> Publication:
        authors = [a.get("name", "") for a in (paper.get("authors") or [])]
        external_ids = paper.get("externalIds") or {}
        doi = external_ids.get("DOI")
        arxiv_id = external_ids.get("ArXiv")

        pub_date = None
        if paper.get("publicationDate"):
            from datetime import datetime

            try:
                pub_date = datetime.fromisoformat(paper["publicationDate"])
            except ValueError:
                pass

        return Publication(
            title=paper.get("title", ""),
            authors=authors,
            abstract=paper.get("abstract") or "",
            url=paper.get("url") or f"https://api.semanticscholar.org/paper/{paper.get('paperId', '')}",
            doi=doi,
            arxiv_id=arxiv_id,
            source_label=source_label,
            publication_date=pub_date,
            matched_domains=[domain_label],
        )


def _extract_search_terms(query: str) -> str:
    """Extract meaningful terms from a boolean query string.

    Strips AND/OR operators, quotes, and parentheses to produce a
    space-separated list of terms suitable for the S2 search API.
    """
    # Remove parentheses
    cleaned = query.replace("(", " ").replace(")", " ")
    # Remove boolean operators
    cleaned = re.sub(r"\b(AND|OR)\b", " ", cleaned, flags=re.IGNORECASE)
    # Remove quotes
    cleaned = cleaned.replace('"', "")
    # Collapse whitespace
    terms = " ".join(cleaned.split())
    return terms
