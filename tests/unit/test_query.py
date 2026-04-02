"""Tests for pubscout.core.query — boolean query parser, matcher, and arXiv translator."""

import pytest

from pubscout.core.query import (
    AndNode,
    OrNode,
    TermNode,
    matches,
    parse_query,
    to_arxiv_query,
)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


class TestParseQuery:
    def test_simple_term(self):
        assert parse_query("LLM") == TermNode("llm")

    def test_or(self):
        result = parse_query("LLM OR transformer")
        assert result == OrNode([TermNode("llm"), TermNode("transformer")])

    def test_and(self):
        result = parse_query("inference AND serving")
        assert result == AndNode([TermNode("inference"), TermNode("serving")])

    def test_quoted_phrase(self):
        result = parse_query('"KV cache"')
        assert result == TermNode("kv cache")

    def test_complex_nested(self):
        result = parse_query('("large language model" OR LLM) AND (inference OR serving)')
        expected = AndNode(
            [
                OrNode([TermNode("large language model"), TermNode("llm")]),
                OrNode([TermNode("inference"), TermNode("serving")]),
            ]
        )
        assert result == expected

    def test_and_binds_tighter_than_or(self):
        # A OR B AND C  →  OR(A, AND(B, C))
        result = parse_query("A OR B AND C")
        expected = OrNode([TermNode("a"), AndNode([TermNode("b"), TermNode("c")])])
        assert result == expected

    def test_empty_query_raises(self):
        with pytest.raises(ValueError, match="Empty query"):
            parse_query("")

    def test_missing_closing_paren_raises(self):
        with pytest.raises(ValueError, match="Missing closing parenthesis"):
            parse_query("(LLM OR transformer")


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


class TestMatches:
    def test_simple_term_present(self):
        assert matches(parse_query("LLM"), "This paper studies LLM inference") is True

    def test_simple_term_absent(self):
        assert matches(parse_query("GPU"), "This paper studies LLM inference") is False

    def test_quoted_phrase_present(self):
        assert matches(parse_query('"KV cache"'), "We optimize the KV cache") is True

    def test_quoted_phrase_absent(self):
        assert matches(parse_query('"KV cache"'), "We optimize the cache") is False

    def test_and_both_present(self):
        q = parse_query("inference AND serving")
        assert matches(q, "LLM inference and model serving at scale") is True

    def test_and_one_missing(self):
        q = parse_query("inference AND serving")
        assert matches(q, "LLM inference performance benchmarks") is False

    def test_or_either_matches(self):
        q = parse_query("LLM OR transformer")
        assert matches(q, "This transformer model is powerful") is True
        assert matches(q, "LLM inference is fast") is True

    def test_or_neither_matches(self):
        q = parse_query("LLM OR transformer")
        assert matches(q, "Convolutional neural network results") is False

    def test_full_domain_query_matches(self):
        """Domain query D1 from PubScout spec matches relevant abstract."""
        query_str = (
            '("large language model" OR LLM OR transformer) '
            "AND (inference OR serving) "
            'AND ("disaggregated inference" OR "prefill" OR "decode" OR "KV cache")'
        )
        abstract = (
            "We present a novel approach to disaggregated inference for large language models. "
            "Our system separates the prefill and decode phases, enabling efficient KV cache "
            "management and improved serving throughput for transformer architectures."
        )
        assert matches(parse_query(query_str), abstract) is True

    def test_full_domain_query_no_match(self):
        """Domain query D1 does NOT match unrelated abstract."""
        query_str = (
            '("large language model" OR LLM OR transformer) '
            "AND (inference OR serving) "
            'AND ("disaggregated inference" OR "prefill" OR "decode" OR "KV cache")'
        )
        abstract = (
            "This paper proposes a new convolutional architecture for image classification. "
            "The approach uses residual connections and achieves state-of-the-art accuracy "
            "on ImageNet benchmarks."
        )
        assert matches(parse_query(query_str), abstract) is False


# ---------------------------------------------------------------------------
# arXiv translator
# ---------------------------------------------------------------------------


class TestToArxivQuery:
    def test_single_term(self):
        result = to_arxiv_query(parse_query("LLM"))
        assert result == "(ti:llm OR abs:llm)"

    def test_quoted_phrase(self):
        result = to_arxiv_query(parse_query('"KV cache"'))
        assert result == '(ti:"kv cache" OR abs:"kv cache")'

    def test_and_expression(self):
        result = to_arxiv_query(parse_query("inference AND serving"))
        assert "AND" in result
        assert "(ti:inference OR abs:inference)" in result
        assert "(ti:serving OR abs:serving)" in result

    def test_or_expression(self):
        result = to_arxiv_query(parse_query("LLM OR transformer"))
        assert result.startswith("(")
        assert result.endswith(")")
        assert " OR " in result

    def test_with_categories(self):
        result = to_arxiv_query(parse_query("LLM"), categories=["cs.AI", "cs.CL"])
        assert result.startswith("(cat:cs.AI OR cat:cs.CL) AND ")
        assert "(ti:llm OR abs:llm)" in result

    def test_complex_produces_valid_syntax(self):
        query_str = '("large language model" OR LLM) AND inference'
        result = to_arxiv_query(parse_query(query_str))
        # Should contain both ti: and abs: prefixes
        assert "ti:" in result
        assert "abs:" in result
        assert "AND" in result
