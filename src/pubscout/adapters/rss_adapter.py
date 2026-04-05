"""RSS/Atom feed adapter for PubScout."""

from __future__ import annotations

import html as html_module
import logging
import re
from datetime import datetime

import feedparser

from pubscout.core.models import Domain, Publication, Source

logger = logging.getLogger(__name__)

_HTML_TAG_RE = re.compile(r"<[^>]+>")


class RssAdapter:
    """Fetch publications from RSS/Atom feeds via feedparser."""

    def fetch(self, source: Source, domains: list[Domain]) -> list[Publication]:
        try:
            feed = feedparser.parse(source.url)
        except Exception:
            logger.warning("Failed to parse feed at %s", source.url, exc_info=True)
            return []

        if feed.bozo and not feed.entries:
            logger.warning(
                "Malformed feed at %s: %s", source.url, feed.bozo_exception
            )
            return []

        publications: list[Publication] = []
        for entry in feed.entries:
            pub = self._entry_to_publication(entry, source.label)
            if pub:
                publications.append(pub)

        logger.info(
            "Fetched %d entries from RSS feed '%s'",
            len(publications),
            source.label,
        )
        return publications

    @staticmethod
    def _entry_to_publication(entry: dict, source_label: str) -> Publication | None:
        title = entry.get("title", "").strip()
        if not title:
            return None

        link = entry.get("link", "")

        # Extract abstract / summary (strip HTML)
        summary = entry.get("summary", "") or entry.get("description", "")
        summary = _strip_html(summary)

        # Authors
        authors: list[str] = []
        if "authors" in entry:
            authors = [a.get("name", "") for a in entry["authors"] if a.get("name")]
        elif "author" in entry:
            authors = [entry["author"]]

        # Publication date
        pub_date = None
        for date_field in ("published_parsed", "updated_parsed"):
            tp = entry.get(date_field)
            if tp:
                try:
                    pub_date = datetime(*tp[:6])
                except Exception:
                    pass
                break

        return Publication(
            title=title,
            authors=authors,
            abstract=summary,
            url=link,
            doi=None,
            source_label=source_label,
            publication_date=pub_date,
        )


def _strip_html(text: str) -> str:
    """Remove HTML tags and unescape entities."""
    stripped = _HTML_TAG_RE.sub("", text)
    return html_module.unescape(stripped).strip()
