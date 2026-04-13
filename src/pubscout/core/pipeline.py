"""Pipeline orchestrator — runs the full scan workflow."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pubscout.adapters.arxiv_adapter import ArxivAdapter
from pubscout.adapters.rss_adapter import RssAdapter
from pubscout.adapters.semantic_scholar import SemanticScholarAdapter
from pubscout.adapters.web_adapter import WebAdapter
from pubscout.core.dedup import Deduplicator
from pubscout.core.models import Publication, ScanRun, UserProfile
from pubscout.core.report import ReportGenerator
from pubscout.core.scorer import RelevanceScorer
from pubscout.storage.database import PubScoutDB

logger = logging.getLogger(__name__)


def _aware(dt: datetime) -> datetime:
    """Ensure a datetime is timezone-aware (assume UTC if naive)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ── Adapter Registry ─────────────────────────────────────────────────

ADAPTER_REGISTRY: dict[str, type] = {
    "arxiv": ArxivAdapter,
    "semantic_scholar": SemanticScholarAdapter,
    "rss": RssAdapter,
    "web": WebAdapter,
}


def register_adapter(name: str, adapter_cls: type) -> None:
    """Register a new source adapter by name."""
    ADAPTER_REGISTRY[name] = adapter_cls


# ── Pipeline ─────────────────────────────────────────────────────────


class ScanPipeline:
    """Orchestrates Source → Fetch → Dedup → Score → Report → Store."""

    def __init__(self, profile: UserProfile, db: PubScoutDB) -> None:
        self.profile = profile
        self.db = db
        self.deduplicator = Deduplicator(db)
        self.scorer = RelevanceScorer(profile.llm, profile.scoring)
        self.report_generator = ReportGenerator()

    # ── public API ───────────────────────────────────────────

    def run(
        self,
        dry_run: bool = False,
        send_email: bool = True,
        scan_range_days: int | None = None,
    ) -> ScanRun:
        """Execute the full pipeline and return a :class:`ScanRun` summary.

        Args:
            dry_run: Save report to file, skip email delivery.
            send_email: Whether to send an email digest.
            scan_range_days: Override for the profile's ``scan_range_days``
                (default: use the value from the user profile).
        """
        days = scan_range_days if scan_range_days is not None else self.profile.scan_range_days
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

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

        # Step 1b — Filter by scan range (drop publications older than cutoff)
        before_filter = len(all_publications)
        all_publications = [
            p for p in all_publications
            if p.publication_date is None or _aware(p.publication_date) >= cutoff
        ]
        filtered_out = before_filter - len(all_publications)
        if filtered_out:
            logger.info(
                "Date filter (last %d days): removed %d, kept %d",
                days, filtered_out, len(all_publications),
            )

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

        # Step 7 — Email delivery
        if dry_run:
            logger.info("Dry run — report at %s, no email sent", report_path)
        elif not send_email:
            logger.info("Email disabled — report saved to %s", report_path)
        else:
            self._send_email(html, scored_pubs, scan_run)

        return scan_run

    # ── private helpers ──────────────────────────────────────

    def _get_adapter(self, source: Any) -> Any:
        """Return the adapter instance for *source.adapter* from the registry."""
        adapter_cls = ADAPTER_REGISTRY.get(source.adapter)
        if adapter_cls is None:
            raise ValueError(f"Unknown adapter: {source.adapter!r}")
        return adapter_cls()

    def _send_email(
        self, html: str, publications: list[Publication], scan_run: ScanRun
    ) -> None:
        """Send email digest if email is configured for SMTP transport."""
        from pubscout.core.models import EmailConfig

        email_cfg = self.profile.email
        if not isinstance(email_cfg, EmailConfig) or email_cfg.transport != "smtp":
            logger.info("Email transport is not smtp — report saved to file only")
            return

        try:
            from pubscout.core.email import SmtpEmailSender

            sender = SmtpEmailSender()
            count = len(publications)
            ok = sender.send(html, f"PubScout Digest — {count} papers", email_cfg)
            if ok:
                logger.info("Email sent successfully")
            else:
                logger.warning("Email delivery failed — report still saved to file")
        except Exception as exc:
            logger.warning("Email sending error: %s — report still saved to file", exc)
