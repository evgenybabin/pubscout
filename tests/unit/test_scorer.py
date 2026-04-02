"""Tests for pubscout.core.scorer — two-pass relevance scoring pipeline."""

from unittest.mock import MagicMock, patch

import pytest

from pubscout.core.models import Domain, LLMConfig, Publication, ScoringConfig
from pubscout.core.scorer import RelevanceScorer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pub(
    title: str = "Test Publication",
    abstract: str = "A generic abstract about research.",
    authors: list[str] | None = None,
    **kwargs,
) -> Publication:
    return Publication(
        title=title,
        abstract=abstract,
        authors=authors or ["Author A"],
        url="https://example.com",
        source_label="test",
        **kwargs,
    )


def _make_scorer(
    threshold: float = 5.0,
    include_keywords: list[str] | None = None,
    exclude_keywords: list[str] | None = None,
) -> RelevanceScorer:
    return RelevanceScorer(
        llm_config=LLMConfig(api_key="test-key"),
        scoring_config=ScoringConfig(
            threshold=threshold,
            include_keywords=include_keywords or [],
            exclude_keywords=exclude_keywords or [],
        ),
    )


def _mock_openai_response(content: str) -> MagicMock:
    """Build a mock OpenAI chat completion response."""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = content
    return response


# ---------------------------------------------------------------------------
# Pass 1 — keyword pre-filter
# ---------------------------------------------------------------------------


class TestKeywordPrefilter:
    def test_keyword_prefilter_passes_matching(self):
        scorer = _make_scorer()
        domains = [Domain(label="D1", query="transformer AND inference")]
        matching = _make_pub(title="Transformer Inference Optimization")
        non_matching = _make_pub(title="Unrelated Biology Paper")

        result = scorer._keyword_prefilter([matching, non_matching], domains)

        assert len(result) == 1
        assert result[0].title == matching.title

    def test_keyword_prefilter_sets_matched_domains(self):
        scorer = _make_scorer()
        domains = [
            Domain(label="LLM", query="transformer"),
            Domain(label="Vision", query="convolution"),
            Domain(label="NLP", query="transformer AND language"),
        ]
        pub = _make_pub(
            title="Transformer Language Model",
            abstract="A large transformer for language understanding.",
        )

        result = scorer._keyword_prefilter([pub], domains)

        assert len(result) == 1
        assert "LLM" in result[0].matched_domains
        assert "NLP" in result[0].matched_domains
        assert "Vision" not in result[0].matched_domains


# ---------------------------------------------------------------------------
# Pass 2 — LLM scoring
# ---------------------------------------------------------------------------


class TestLLMScore:
    def test_llm_score_parses_json_response(self):
        scorer = _make_scorer()
        pub = _make_pub(matched_domains=["D1"])
        domains = [Domain(label="D1", query="test")]

        mock_resp = _mock_openai_response('{"score": 8.5, "reason": "relevant"}')
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_resp
        scorer._openai_client = mock_client

        score = scorer._llm_score(pub, domains)

        assert score == 8.5

    def test_llm_score_fallback_on_api_error(self):
        scorer = _make_scorer()
        pub = _make_pub(matched_domains=["D1", "D2"])
        domains = [Domain(label="D1", query="test"), Domain(label="D2", query="test2")]

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = RuntimeError("API down")
        scorer._openai_client = mock_client

        score = scorer._llm_score(pub, domains)

        # fallback: len(matched_domains) * 2 = 4.0
        assert score == 4.0

    def test_llm_score_extracts_number_from_bad_json(self):
        scorer = _make_scorer()
        pub = _make_pub(matched_domains=["D1"])
        domains = [Domain(label="D1", query="test")]

        mock_resp = _mock_openai_response("I'd rate this 7 out of 10")
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_resp
        scorer._openai_client = mock_client

        score = scorer._llm_score(pub, domains)

        assert score == 7.0


# ---------------------------------------------------------------------------
# Pass 3 — hard keyword filters
# ---------------------------------------------------------------------------


class TestHardFilters:
    def test_exclude_keyword_filters_publication(self):
        scorer = _make_scorer(exclude_keywords=["biology"])
        pub = _make_pub(
            title="Biology of Cells",
            abstract="A study in biology.",
            relevance_score=9.0,
        )

        result = scorer._apply_hard_filters(pub)

        assert result is None

    def test_include_keyword_penalty(self):
        scorer = _make_scorer(include_keywords=["neural", "deep learning"])
        pub = _make_pub(
            title="Classical Statistics Method",
            abstract="No neural or deep learning here.",
            relevance_score=8.0,
        )
        # abstract *does* contain "neural" → no penalty
        result = scorer._apply_hard_filters(pub)
        assert result is not None
        assert result.relevance_score == 8.0

        pub2 = _make_pub(
            title="Classical Statistics Method",
            abstract="Purely frequentist approach.",
            relevance_score=8.0,
        )
        # neither keyword present → -3 penalty
        result2 = scorer._apply_hard_filters(pub2)
        assert result2 is not None
        assert result2.relevance_score == 5.0


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


class TestPromptBuilding:
    def test_scoring_prompt_includes_domain_context(self):
        scorer = _make_scorer()
        pub = _make_pub(matched_domains=["D1", "D2"])
        domains = [
            Domain(label="D1", query="transformer AND inference"),
            Domain(label="D2", query="GPU optimization"),
        ]

        prompt = scorer._build_scoring_prompt(pub, domains)

        assert "D1: transformer AND inference" in prompt
        assert "D2: GPU optimization" in prompt

    def test_scoring_prompt_includes_feedback(self):
        scorer = _make_scorer()
        pub = _make_pub(matched_domains=["D1"])
        domains = [Domain(label="D1", query="test")]

        prompt = scorer._build_scoring_prompt(
            pub,
            domains,
            positive_examples=["Good Paper A", "Good Paper B"],
            negative_examples=["Bad Paper X"],
        )

        assert "EXAMPLES OF PUBLICATIONS THE USER FOUND RELEVANT:" in prompt
        assert "Good Paper A" in prompt
        assert "Good Paper B" in prompt
        assert "EXAMPLES OF PUBLICATIONS THE USER FOUND NOT RELEVANT:" in prompt
        assert "Bad Paper X" in prompt


# ---------------------------------------------------------------------------
# End-to-end pipeline
# ---------------------------------------------------------------------------


class TestScorePublicationsEndToEnd:
    def test_threshold_filtering(self):
        scorer = _make_scorer(threshold=6.0)
        domains = [Domain(label="D1", query="research")]

        high = _make_pub(title="Research paper high", abstract="Great research topic")
        low = _make_pub(title="Research paper low", abstract="Another research topic")

        mock_client = MagicMock()
        high_resp = _mock_openai_response('{"score": 8.0, "reason": "good"}')
        low_resp = _mock_openai_response('{"score": 4.0, "reason": "meh"}')
        mock_client.chat.completions.create.side_effect = [high_resp, low_resp]
        scorer._openai_client = mock_client

        result = scorer.score_publications([high, low], domains)

        assert len(result) == 1
        assert result[0].title == "Research paper high"

    def test_results_sorted_by_score_descending(self):
        scorer = _make_scorer(threshold=1.0)
        domains = [Domain(label="D1", query="research")]

        pubs = [
            _make_pub(title="Research A", abstract="research"),
            _make_pub(title="Research B", abstract="research"),
            _make_pub(title="Research C", abstract="research"),
        ]

        mock_client = MagicMock()
        responses = [
            _mock_openai_response('{"score": 5.0, "reason": "ok"}'),
            _mock_openai_response('{"score": 9.0, "reason": "great"}'),
            _mock_openai_response('{"score": 7.0, "reason": "good"}'),
        ]
        mock_client.chat.completions.create.side_effect = responses
        scorer._openai_client = mock_client

        result = scorer.score_publications(pubs, domains)

        scores = [p.relevance_score for p in result]
        assert scores == [9.0, 7.0, 5.0]

    def test_score_publications_end_to_end(self):
        """Full pipeline: 5 pubs in, keyword filter + LLM + hard filters + threshold."""
        scorer = _make_scorer(
            threshold=5.0,
            exclude_keywords=["biology"],
            include_keywords=["neural"],
        )
        domains = [
            Domain(label="AI", query="neural OR transformer"),
            Domain(label="Bio", query="biology"),
        ]

        pubs = [
            _make_pub(title="Neural Transformer Advances", abstract="neural network transformer"),
            _make_pub(title="Biology of Transformers", abstract="biology transformer cells"),
            _make_pub(title="Pure Neural Study", abstract="neural architecture search"),
            _make_pub(title="Unrelated Finance Paper", abstract="stock market analysis"),
            _make_pub(title="Transformer Scaling", abstract="scaling laws for transformers"),
        ]

        mock_client = MagicMock()
        # Pub 1 (Neural Transformer) → matches AI, scored 8.0
        # Pub 2 (Biology of Transformers) → matches AI + Bio, scored 7.0 → excluded by "biology"
        # Pub 3 (Pure Neural Study) → matches AI, scored 6.0
        # Pub 4 (Unrelated Finance) → no domain match → dropped in prefilter
        # Pub 5 (Transformer Scaling) → matches AI, scored 5.0 → has "neural"? No → -3 → 2.0 → below threshold
        responses = [
            _mock_openai_response('{"score": 8.0, "reason": "highly relevant"}'),
            _mock_openai_response('{"score": 7.0, "reason": "relevant"}'),
            _mock_openai_response('{"score": 6.0, "reason": "relevant"}'),
            _mock_openai_response('{"score": 5.0, "reason": "somewhat"}'),
        ]
        mock_client.chat.completions.create.side_effect = responses
        scorer._openai_client = mock_client

        result = scorer.score_publications(pubs, domains)

        titles = [p.title for p in result]
        # Pub 1: 8.0, has "neural" → passes
        # Pub 2: excluded (biology keyword)
        # Pub 3: 6.0, has "neural" → passes
        # Pub 4: dropped in prefilter
        # Pub 5: 5.0 - 3 = 2.0 → below threshold
        assert "Neural Transformer Advances" in titles
        assert "Pure Neural Study" in titles
        assert "Biology of Transformers" not in titles
        assert "Unrelated Finance Paper" not in titles
        assert "Transformer Scaling" not in titles
        assert len(result) == 2
        # Sorted descending
        assert result[0].relevance_score >= result[1].relevance_score
