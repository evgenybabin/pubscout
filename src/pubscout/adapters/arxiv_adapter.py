"""arXiv source adapter — fetches publications via the arxiv PyPI client."""

from __future__ import annotations

import logging
import time

import arxiv

from pubscout.adapters.base import SourceAdapter  # noqa: F401 (protocol reference)
from pubscout.core.models import Domain, Publication, Source
from pubscout.core.query import parse_query, to_arxiv_query

logger = logging.getLogger(__name__)


class ArxivAdapter:
    """Fetches publications from arXiv API using domain queries."""

    def fetch(self, source: Source, domains: list[Domain]) -> list[Publication]:
        """Fetch and deduplicate publications across all enabled domains.

        For each enabled domain the adapter parses the boolean query, translates
        it to arXiv API syntax (with optional category filters), fetches results,
        and converts them to :class:`Publication` objects.  Duplicate arXiv IDs
        across domains are merged by appending domain labels.
        """
        config = source.config or {}
        max_results = config.get("max_results_per_query", 100)
        rate_limit = config.get("rate_limit_seconds", 3)
        categories: list[str] = config.get("categories", [])

        seen: dict[str, Publication] = {}  # arxiv_id -> Publication
        client = arxiv.Client()

        enabled_domains = [d for d in domains if d.enabled]

        for idx, domain in enumerate(enabled_domains):
            try:
                query_str = self._build_query(domain, categories)
                search = arxiv.Search(
                    query=query_str,
                    max_results=max_results,
                    sort_by=arxiv.SortCriterion.SubmittedDate,
                )

                count = 0
                for result in client.results(search):
                    pub = self._result_to_publication(result, source.label, domain.label)
                    aid = pub.arxiv_id
                    if aid and aid in seen:
                        if domain.label not in seen[aid].matched_domains:
                            seen[aid].matched_domains.append(domain.label)
                    else:
                        seen[aid or pub.id] = pub
                    count += 1

                logger.info("Domain '%s': fetched %d results from arXiv", domain.label, count)

            except Exception:
                logger.warning(
                    "arXiv query failed for domain '%s'; skipping.", domain.label, exc_info=True
                )

            # Rate-limit between domain queries (skip after the last one)
            if idx < len(enabled_domains) - 1:
                time.sleep(rate_limit)

        publications = list(seen.values())
        logger.info("Total unique publications from arXiv: %d", len(publications))
        return publications

    # -- internal helpers ----------------------------------------------------

    def _build_query(self, domain: Domain, categories: list[str]) -> str:
        """Parse *domain.query* and translate to arXiv API syntax."""
        tree = parse_query(domain.query)
        return to_arxiv_query(tree, categories or None)

    def _result_to_publication(
        self, result: arxiv.Result, source_label: str, domain_label: str
    ) -> Publication:
        """Convert an :class:`arxiv.Result` to a :class:`Publication`."""
        arxiv_id = result.get_short_id()
        return Publication(
            title=result.title,
            authors=[a.name for a in result.authors],
            abstract=result.summary,
            url=result.entry_id,
            arxiv_id=arxiv_id,
            doi=result.doi,
            source_label=source_label,
            publication_date=result.published,
            matched_domains=[domain_label],
        )
