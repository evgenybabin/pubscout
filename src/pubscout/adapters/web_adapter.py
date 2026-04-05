"""Generic web scraper adapter for PubScout (experimental)."""

from __future__ import annotations

import json
import logging
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from pubscout.core.models import Domain, Publication, Source

logger = logging.getLogger(__name__)


class WebAdapter:
    """Extract publications from HTML pages.  Experimental — results may be incomplete."""

    def fetch(self, source: Source, domains: list[Domain]) -> list[Publication]:
        url = source.url

        # robots.txt check
        if not self._robots_allowed(url):
            logger.warning("robots.txt disallows access to %s — skipping", url)
            return []

        try:
            resp = httpx.get(url, timeout=30.0, follow_redirects=True)
            resp.raise_for_status()
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            logger.error("Web fetch failed for %s: %s", url, exc)
            return []

        html = resp.text
        publications = self._extract(html, url, source.label)
        if publications:
            logger.info(
                "Web scraper extracted %d items from %s", len(publications), url
            )
        else:
            logger.warning("Web scraper found no recognizable items at %s", url)
        return publications

    def _extract(
        self, html: str, base_url: str, source_label: str
    ) -> list[Publication]:
        """Try extraction strategies in order: JSON-LD → <article> → heading+link."""
        pubs = self._try_json_ld(html, base_url, source_label)
        if pubs:
            return pubs

        pubs = self._try_articles(html, base_url, source_label)
        if pubs:
            return pubs

        pubs = self._try_heading_links(html, base_url, source_label)
        return pubs

    # ── Strategy 1: JSON-LD ──────────────────────────────────

    @staticmethod
    def _try_json_ld(
        html: str, base_url: str, source_label: str
    ) -> list[Publication]:
        soup = BeautifulSoup(html, "html.parser")
        scripts = soup.find_all("script", attrs={"type": "application/ld+json"})
        pubs: list[Publication] = []
        for script in scripts:
            try:
                data = json.loads(script.string or "")
            except (json.JSONDecodeError, TypeError):
                continue
            items = data if isinstance(data, list) else [data]
            for item in items:
                item_type = item.get("@type", "")
                if item_type in ("ScholarlyArticle", "Article", "TechArticle"):
                    title = item.get("name") or item.get("headline", "")
                    if not title:
                        continue
                    url = item.get("url") or base_url
                    if not url.startswith("http"):
                        url = urljoin(base_url, url)
                    authors = []
                    for a in item.get("author", []):
                        if isinstance(a, dict):
                            authors.append(a.get("name", ""))
                        elif isinstance(a, str):
                            authors.append(a)
                    pubs.append(
                        Publication(
                            title=title,
                            authors=authors,
                            abstract=item.get("description", ""),
                            url=url,
                            source_label=source_label,
                        )
                    )
        return pubs

    # ── Strategy 2: <article> elements ───────────────────────

    @staticmethod
    def _try_articles(
        html: str, base_url: str, source_label: str
    ) -> list[Publication]:
        soup = BeautifulSoup(html, "html.parser")
        articles = soup.find_all("article")
        pubs: list[Publication] = []
        for article in articles:
            heading = article.find(["h1", "h2", "h3", "h4"])
            if not heading:
                continue
            title = heading.get_text(strip=True)
            link_el = heading.find("a") or article.find("a")
            url = base_url
            if link_el and link_el.get("href"):
                href = link_el["href"]
                url = href if href.startswith("http") else urljoin(base_url, href)
            pubs.append(
                Publication(
                    title=title,
                    authors=[],
                    abstract="",
                    url=url,
                    source_label=source_label,
                )
            )
        return pubs

    # ── Strategy 3: heading + link pattern ───────────────────

    @staticmethod
    def _try_heading_links(
        html: str, base_url: str, source_label: str
    ) -> list[Publication]:
        soup = BeautifulSoup(html, "html.parser")
        pubs: list[Publication] = []
        for heading in soup.find_all(["h2", "h3"]):
            link = heading.find("a")
            if not link or not link.get("href"):
                continue
            title = link.get_text(strip=True)
            if not title:
                continue
            href = link["href"]
            url = href if href.startswith("http") else urljoin(base_url, href)
            pubs.append(
                Publication(
                    title=title,
                    authors=[],
                    abstract="",
                    url=url,
                    source_label=source_label,
                )
            )
        return pubs

    # ── robots.txt ───────────────────────────────────────────

    @staticmethod
    def _robots_allowed(url: str) -> bool:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        rp = RobotFileParser()
        try:
            rp.set_url(robots_url)
            rp.read()
            return rp.can_fetch("PubScout", url)
        except Exception:
            # If we can't read robots.txt, assume allowed
            return True
