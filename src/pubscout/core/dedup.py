"""Deduplication engine for PubScout (FR-004).

Removes duplicates within a publication batch and against the database
using exact identifier matching (arxiv_id, DOI) and fuzzy title comparison.
"""

from __future__ import annotations

import logging

from rapidfuzz import fuzz

from pubscout.core.models import Publication
from pubscout.storage.database import PubScoutDB

logger = logging.getLogger(__name__)


class Deduplicator:
    """Batch and database deduplication for fetched publications."""

    TITLE_SIMILARITY_THRESHOLD = 90  # percent

    def __init__(self, db: PubScoutDB) -> None:
        self.db = db

    # ── Public API ───────────────────────────────────────────────────

    def deduplicate(self, publications: list[Publication]) -> list[Publication]:
        """Remove duplicates from a batch of publications.

        Dedup strategy (spec: FR-004):
        1. Remove duplicates within the batch (same arxiv_id, same DOI,
           or title similarity > 90%).
        2. Remove publications already in the database.

        When merging duplicates, combine ``matched_domains`` lists.
        Returns a deduplicated list preserving the original order.
        """
        if not publications:
            return []

        initial_count = len(publications)

        # Stage 1 – intra-batch dedup
        batch_deduped = self._deduplicate_batch(publications)
        batch_removed = initial_count - len(batch_deduped)
        if batch_removed:
            logger.info("Batch dedup removed %d duplicate(s)", batch_removed)

        # Stage 2 – database dedup
        result = [pub for pub in batch_deduped if not self._is_duplicate_in_db(pub)]
        db_removed = len(batch_deduped) - len(result)
        if db_removed:
            logger.info("Database dedup removed %d duplicate(s)", db_removed)

        logger.info(
            "Deduplication complete: %d → %d publications (%d removed)",
            initial_count,
            len(result),
            initial_count - len(result),
        )
        return result

    # ── Internal helpers ─────────────────────────────────────────────

    def _deduplicate_batch(self, publications: list[Publication]) -> list[Publication]:
        """Remove duplicates within the current batch.

        Iterates in order; for each publication checks whether an earlier
        entry is a duplicate (by arxiv_id, DOI, or fuzzy title).  When a
        duplicate is found the earlier entry is updated via ``_merge_publications``.
        """
        unique: list[Publication] = []

        for pub in publications:
            merged = False
            for idx, existing in enumerate(unique):
                if self._is_same_publication(existing, pub):
                    unique[idx] = self._merge_publications(existing, pub)
                    merged = True
                    break
            if not merged:
                unique.append(pub)

        return unique

    def _is_same_publication(self, a: Publication, b: Publication) -> bool:
        """Return *True* when *a* and *b* represent the same paper."""
        # Exact arxiv_id match
        if a.arxiv_id and b.arxiv_id and a.arxiv_id == b.arxiv_id:
            return True
        # Exact DOI match
        if a.doi and b.doi and a.doi == b.doi:
            return True
        # Fuzzy title match
        if self._titles_match(a.title, b.title):
            return True
        return False

    def _is_duplicate_in_db(self, pub: Publication) -> bool:
        """Check if a publication already exists in the database."""
        return self.db.publication_exists(
            arxiv_id=pub.arxiv_id,
            doi=pub.doi,
            title=pub.title,
        )

    def _titles_match(self, title1: str, title2: str) -> bool:
        """Check if two titles are similar enough to be considered the same paper."""
        score = fuzz.ratio(title1.lower(), title2.lower())
        return score >= self.TITLE_SIMILARITY_THRESHOLD

    def _merge_publications(
        self, existing: Publication, new: Publication
    ) -> Publication:
        """Merge ``matched_domains`` from *new* into *existing* (no duplicates)."""
        combined = list(dict.fromkeys(existing.matched_domains + new.matched_domains))
        return existing.model_copy(update={"matched_domains": combined})
