"""Pipeline orchestrator — runs the full scan workflow."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from pubscout.adapters.arxiv_adapter import ArxivAdapter
from pubscout.core.dedup import Deduplicator
from pubscout.core.models import Publication, ScanRun, UserProfile
from pubscout.core.report import ReportGenerator
from pubscout.core.scorer import RelevanceScorer
from pubscout.storage.database import PubScoutDB

logger = logging.getLogger(__name__)


class ScanPipeline:
    """Orchestrates Source → Fetch → Dedup → Score → Report → Store."""

    def __init__(self, profile: UserProfile, db: PubScoutDB) -> None:
        self.profile = profile
        self.db = db
        self.deduplicator = Deduplicator(db)
        self.scorer = RelevanceScorer(profile.llm, profile.scoring)
        self.report_generator = ReportGenerator()

    # ── public API ───────────────────────────────────────────

    def run(self, dry_run: bool = False) -> ScanRun:
        """Execute the full pipeline and return a :class:`ScanRun` summary.

        Steps:
        1. Fetch from all enabled sources (currently arXiv only).
        2. Deduplicate within batch and against the database.
        3. Score via keyword pre-filter + LLM.
        4. Generate an HTML report.
        5. Save results to the database.
        6. *dry_run* skips email delivery (not yet implemented anyway).
        """
        start_time = time.time()
        errors: list[str] = []
        all_publications: list[Publication] = []
        sources_checked = 0

        # Step 1 — Fetch from every enabled source
        enabled_domains = [d for d in self.profile.domains if d.enabled]
        for source in self.profile.sources:
            if not source.enabled:
                continue
            sources_checked += 1
            try:
                adapter = self._get_adapter(source)
                pubs = adapter.fetch(source, enabled_domains)
                logger.info("Fetched %d publications from %s", len(pubs), source.label)
                all_publications.extend(pubs)
            except Exception as exc:
                error_msg = f"Error fetching from {source.label}: {exc}"
                logger.error(error_msg)
                errors.append(error_msg)

        items_fetched = len(all_publications)
        logger.info("Total fetched: %d from %d sources", items_fetched, sources_checked)

        # Step 2 — Deduplicate
        unique_pubs = self.deduplicator.deduplicate(all_publications)
        logger.info("After dedup: %d unique publications", len(unique_pubs))

        # Step 3 — Score
        positive_examples = self.db.get_positive_examples(limit=20)
        negative_examples = self.db.get_negative_examples(limit=20)
        scored_pubs = self.scorer.score_publications(
            unique_pubs,
            enabled_domains,
            feedback_positive=positive_examples,
            feedback_negative=negative_examples,
        )
        items_scored = len(scored_pubs)
        logger.info("After scoring: %d publications above threshold", items_scored)

        # Step 4 — Generate report
        duration = time.time() - start_time
        scan_run = ScanRun(
            sources_checked=sources_checked,
            items_fetched=items_fetched,
            items_scored=items_scored,
            items_reported=len(scored_pubs),
            errors=errors,
            duration_seconds=round(duration, 2),
        )

        if scored_pubs:
            html = self.report_generator.generate_html(scored_pubs, scan_run)
        else:
            html = self.report_generator.generate_empty_summary(scan_run)

        # Step 5 — Save report file
        report_path = self.report_generator.save_report(html)
        logger.info("Report saved to %s", report_path)

        # Step 6 — Persist to database
        for pub in scored_pubs:
            self.db.save_publication(pub)
        self.db.mark_reported([p.id for p in scored_pubs])
        self.db.save_scan_run(scan_run)

        if dry_run:
            logger.info("Dry run — report at %s, no email sent", report_path)
        else:
            logger.info("Email sending not yet implemented — report saved to file")

        return scan_run

    # ── private helpers ──────────────────────────────────────

    def _get_adapter(self, source):
        """Return the adapter instance for *source.adapter*."""
        if source.adapter == "arxiv":
            return ArxivAdapter()
        raise ValueError(f"Unknown adapter: {source.adapter}")
