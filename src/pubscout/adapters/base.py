"""Base adapter protocol for PubScout source adapters."""

from __future__ import annotations

from typing import Protocol

from pubscout.core.models import Domain, Publication, Source


class SourceAdapter(Protocol):
    """Protocol that all source adapters must satisfy."""

    def fetch(self, source: Source, domains: list[Domain]) -> list[Publication]:
        """Fetch publications from the source, filtered by domains."""
        ...
