"""Two-pass relevance scorer: keyword pre-filter → LLM scoring pipeline."""

from __future__ import annotations

import json
import logging
import os
import re

from openai import OpenAI

from pubscout.core.models import Domain, LLMConfig, Publication, ScoringConfig
from pubscout.core.query import matches, parse_query

logger = logging.getLogger(__name__)


class RelevanceScorer:
    """Score publications using boolean keyword pre-filter + LLM relevance rating."""

    def __init__(self, llm_config: LLMConfig, scoring_config: ScoringConfig) -> None:
        self.llm_config = llm_config
        self.scoring_config = scoring_config
        self._client: OpenAI | None = None

    # -- public API ----------------------------------------------------------

    def score_publications(
        self,
        publications: list[Publication],
        domains: list[Domain],
        feedback_positive: list[Publication] | None = None,
        feedback_negative: list[Publication] | None = None,
    ) -> list[Publication]:
        """Two-pass scoring pipeline.

        1. Keyword pre-filter via domain boolean queries.
        2. LLM scoring with feedback context.
        3. Hard keyword filters (exclude / include penalty).
        4. Threshold filter + sort by score descending.
        """
        # Pass 1 — keyword pre-filter
        candidates = self._keyword_prefilter(publications, domains)

        positive_titles = [p.title for p in feedback_positive] if feedback_positive else None
        negative_titles = [p.title for p in feedback_negative] if feedback_negative else None

        scored: list[Publication] = []
        for pub in candidates:
            # Pass 2 — LLM scoring
            score = self._llm_score(pub, domains, positive_titles, negative_titles)
            pub.relevance_score = score

            # Pass 3 — hard filters
            result = self._apply_hard_filters(pub)
            if result is not None:
                scored.append(result)

        # Pass 4 — threshold filter + sort
        threshold = self.scoring_config.threshold
        filtered = [p for p in scored if p.relevance_score is not None and p.relevance_score >= threshold]
        filtered.sort(key=lambda p: p.relevance_score or 0.0, reverse=True)
        return filtered

    # -- pass 1: keyword pre-filter ------------------------------------------

    def _keyword_prefilter(
        self, publications: list[Publication], domains: list[Domain]
    ) -> list[Publication]:
        """Evaluate domain boolean queries against title+abstract.

        Publications matching at least one enabled domain pass.
        Sets ``matched_domains`` on each passing publication.
        """
        enabled = [d for d in domains if d.enabled]
        passed: list[Publication] = []

        for pub in publications:
            text = f"{pub.title} {pub.abstract}"
            matched: list[str] = []
            for domain in enabled:
                query = parse_query(domain.query)
                if matches(query, text):
                    matched.append(domain.label)
            if matched:
                pub.matched_domains = matched
                passed.append(pub)

        return passed

    # -- pass 2: LLM scoring -------------------------------------------------

    @property
    def _openai_client(self) -> OpenAI:
        """Lazy-init the OpenAI or AzureOpenAI client."""
        if self._client is None:
            if self.llm_config.provider == "azure":
                from openai import AzureOpenAI

                api_key = (
                    self.llm_config.api_key
                    or os.environ.get("AZURE_OPENAI_API_KEY")
                )
                endpoint = (
                    self.llm_config.endpoint
                    or os.environ.get("AZURE_OPENAI_ENDPOINT")
                )
                api_version = self.llm_config.api_version or "2024-06-01"
                self._client = AzureOpenAI(
                    api_key=api_key,
                    api_version=api_version,
                    azure_endpoint=endpoint or "",
                )
            else:
                kwargs: dict[str, str] = {}
                if self.llm_config.api_key:
                    kwargs["api_key"] = self.llm_config.api_key
                if self.llm_config.endpoint:
                    kwargs["base_url"] = self.llm_config.endpoint
                self._client = OpenAI(**kwargs)
        return self._client

    @_openai_client.setter
    def _openai_client(self, value: OpenAI) -> None:
        self._client = value

    def _llm_score(
        self,
        pub: Publication,
        domains: list[Domain],
        positive_examples: list[str] | None = None,
        negative_examples: list[str] | None = None,
    ) -> float:
        """Call LLM to score a single publication (1-10).

        Falls back to keyword-count heuristic on API error.
        """
        prompt = self._build_scoring_prompt(pub, domains, positive_examples, negative_examples)

        try:
            # Azure uses deployment_name; OpenAI uses model
            model_name = (
                self.llm_config.deployment_name or self.llm_config.model
                if self.llm_config.provider == "azure"
                else self.llm_config.model
            )
            response = self._openai_client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
            )
            content = response.choices[0].message.content or ""
            return self._parse_llm_response(content)
        except Exception:
            logger.warning(
                "LLM scoring failed for '%s'; falling back to keyword heuristic",
                pub.title,
            )
            return min(len(pub.matched_domains) * 2.0, 10.0)

    def _build_scoring_prompt(
        self,
        pub: Publication,
        domains: list[Domain],
        positive_examples: list[str] | None = None,
        negative_examples: list[str] | None = None,
    ) -> str:
        """Build the LLM prompt for relevance scoring."""
        lines = [
            "You are a research relevance scorer. Rate the following publication "
            "on a scale of 1-10 for relevance to the user's research interests.",
            "",
            "USER INTERESTS:",
        ]

        matched_domains = [d for d in domains if d.label in pub.matched_domains]
        for domain in matched_domains:
            lines.append(f"- {domain.label}: {domain.query}")

        if positive_examples:
            lines.append("")
            lines.append("EXAMPLES OF PUBLICATIONS THE USER FOUND RELEVANT:")
            for title in positive_examples:
                lines.append(f"- {title}")

        if negative_examples:
            lines.append("")
            lines.append("EXAMPLES OF PUBLICATIONS THE USER FOUND NOT RELEVANT:")
            for title in negative_examples:
                lines.append(f"- {title}")

        lines.extend([
            "",
            "PUBLICATION TO SCORE:",
            f"Title: {pub.title}",
            f"Authors: {', '.join(pub.authors[:5])}",
            f"Abstract: {pub.abstract[:500]}",
            "",
            'Respond with ONLY a JSON object: {"score": <float 1-10>, "reason": "<one sentence>"}',
        ])

        return "\n".join(lines)

    @staticmethod
    def _parse_llm_response(content: str) -> float:
        """Extract a numeric score from the LLM response text."""
        # Try JSON first
        try:
            data = json.loads(content)
            return float(data["score"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            pass

        # Fallback: extract first number that looks like a score
        m = re.search(r"\b(\d+(?:\.\d+)?)\b", content)
        if m:
            return float(m.group(1))

        return 5.0

    # -- pass 3: hard keyword filters ----------------------------------------

    def _apply_hard_filters(self, pub: Publication) -> Publication | None:
        """Apply include/exclude keyword filters.

        Returns ``None`` if the publication should be excluded.
        """
        text = f"{pub.title} {pub.abstract}".lower()

        # Exclude keywords — instant removal
        for kw in self.scoring_config.exclude_keywords:
            if kw.lower() in text:
                return None

        # Include keywords — penalty if none present
        if self.scoring_config.include_keywords:
            if not any(kw.lower() in text for kw in self.scoring_config.include_keywords):
                if pub.relevance_score is not None:
                    pub.relevance_score -= 3.0

        return pub
