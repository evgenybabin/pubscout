"""Tests for pubscout.core.report — HTML digest generation."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from pubscout.core.models import Publication, ScanRun
from pubscout.core.report import ReportGenerator, _format_authors, _score_color, _truncate_abstract


# ── Fixtures ─────────────────────────────────────────────────────────


def _pub(
    title: str = "Efficient KV-Cache Compression for LLM Inference",
    authors: list[str] | None = None,
    abstract: str = "We propose a novel method for compressing key-value caches in transformer models.",
    url: str = "https://arxiv.org/abs/2401.00001",
    source_label: str = "arXiv",
    relevance_score: float = 8.5,
    matched_domains: list[str] | None = None,
    publication_date: datetime | None = None,
    **kwargs,
) -> Publication:
    return Publication(
        title=title,
        authors=authors or ["Alice Zhang", "Bob Lee", "Carol Wang"],
        abstract=abstract,
        url=url,
        source_label=source_label,
        relevance_score=relevance_score,
        matched_domains=matched_domains or ["LLM Inference"],
        publication_date=publication_date or datetime(2025, 6, 15, tzinfo=timezone.utc),
        **kwargs,
    )


def _scan_run(**overrides) -> ScanRun:
    defaults = dict(sources_checked=4, items_fetched=120, items_scored=120, items_reported=5)
    defaults.update(overrides)
    return ScanRun(**defaults)


SAMPLE_PUBLICATIONS = [
    _pub(
        title="Efficient KV-Cache Compression for LLM Inference",
        relevance_score=9.2,
        matched_domains=["LLM Inference", "Memory Optimization"],
    ),
    _pub(
        title="FlashAttention-3: Fast Exact Attention with IO-Awareness",
        authors=["Tri Dao", "Daniel Y. Fu"],
        url="https://arxiv.org/abs/2401.00002",
        relevance_score=8.7,
        matched_domains=["Attention Mechanisms"],
    ),
    _pub(
        title="Speculative Decoding for Large Language Models",
        url="https://arxiv.org/abs/2401.00003",
        relevance_score=7.1,
        matched_domains=["LLM Inference"],
    ),
    _pub(
        title="Benchmarking GPU Inference Throughput Across Frameworks",
        url="https://arxiv.org/abs/2401.00004",
        relevance_score=5.5,
        source_label="Semantic Scholar",
    ),
    _pub(
        title="Sparse Mixture-of-Experts at Scale: Lessons Learned",
        url="https://arxiv.org/abs/2401.00005",
        relevance_score=3.8,
        matched_domains=["Model Architecture"],
    ),
]


@pytest.fixture
def generator() -> ReportGenerator:
    return ReportGenerator(feedback_base_url="http://test-server:9000")


@pytest.fixture
def scan_run() -> ScanRun:
    return _scan_run()


# ── Tests ────────────────────────────────────────────────────────────


class TestGenerateHTML:
    def test_generate_html_contains_all_publications(self, generator: ReportGenerator, scan_run: ScanRun):
        html = generator.generate_html(SAMPLE_PUBLICATIONS, scan_run)
        for pub in SAMPLE_PUBLICATIONS:
            assert pub.title in html

    def test_publication_has_required_fields(self, generator: ReportGenerator, scan_run: ScanRun):
        pub = _pub(
            title="Attention Is All You Need Revisited",
            authors=["Ada Lovelace", "Grace Hopper"],
            abstract="A comprehensive revisit of the transformer architecture.",
            url="https://arxiv.org/abs/2401.99999",
            relevance_score=9.0,
            source_label="arXiv",
            matched_domains=["Transformers"],
        )
        html = generator.generate_html([pub], scan_run)

        # Title as clickable link
        assert 'href="https://arxiv.org/abs/2401.99999"' in html
        assert "Attention Is All You Need Revisited" in html
        # Authors
        assert "Ada Lovelace" in html
        assert "Grace Hopper" in html
        # Abstract
        assert "A comprehensive revisit" in html
        # Score
        assert "9.0" in html
        # Source
        assert "arXiv" in html
        # Date
        assert "2025-06-15" in html
        # Domain
        assert "Transformers" in html

    def test_authors_truncated(self, generator: ReportGenerator, scan_run: ScanRun):
        pub = _pub(
            authors=[
                "Author A", "Author B", "Author C",
                "Author D", "Author E", "Author F",
            ],
        )
        html = generator.generate_html([pub], scan_run)
        assert "Author A" in html
        assert "Author B" in html
        assert "Author C" in html
        assert "+ 3 more" in html
        assert "Author D" not in html

    def test_abstract_truncated(self, generator: ReportGenerator, scan_run: ScanRun):
        long_abstract = "A" * 300
        pub = _pub(abstract=long_abstract)
        html = generator.generate_html([pub], scan_run)
        # Should contain the truncated version, not the full 300-char string
        assert ("A" * 200 + "...") in html
        assert ("A" * 201) not in html

    def test_feedback_links(self, generator: ReportGenerator, scan_run: ScanRun):
        pub = _pub()
        html = generator.generate_html([pub], scan_run)
        # Links are now JS-driven data attributes
        assert f'data-pub-id="{pub.id}"' in html
        assert 'data-signal="positive"' in html
        assert 'data-signal="negative"' in html
        # JS handler references the feedback base URL
        assert "http://test-server:9000" in html

    def test_score_color_coding(self, generator: ReportGenerator, scan_run: ScanRun):
        green_pub = _pub(title="Green Paper", relevance_score=8.5)
        yellow_pub = _pub(title="Yellow Paper", relevance_score=6.0)
        red_pub = _pub(title="Red Paper", relevance_score=3.0)

        html = generator.generate_html([green_pub, yellow_pub, red_pub], scan_run)

        # Verify colour helper directly and that colours appear in output
        assert _score_color(8.5) == "#27ae60"
        assert _score_color(6.0) == "#f39c12"
        assert _score_color(3.0) == "#e74c3c"
        assert "#27ae60" in html
        assert "#f39c12" in html
        assert "#e74c3c" in html

    def test_matched_domains_shown(self, generator: ReportGenerator, scan_run: ScanRun):
        pub = _pub(matched_domains=["LLM Inference", "KV Cache", "Hardware Acceleration"])
        html = generator.generate_html([pub], scan_run)
        assert "LLM Inference" in html
        assert "KV Cache" in html
        assert "Hardware Acceleration" in html

    def test_header_contains_date_and_stats(self, generator: ReportGenerator, scan_run: ScanRun):
        html = generator.generate_html(SAMPLE_PUBLICATIONS, scan_run)
        assert "PubScout Daily Digest" in html
        assert "4 sources checked" in html
        assert "120 items found" in html
        assert "5 reported" in html


class TestEmptySummary:
    def test_empty_summary(self, generator: ReportGenerator):
        run = _scan_run(sources_checked=3, items_fetched=80, items_reported=0)
        html = generator.generate_empty_summary(run)
        assert "3 sources" in html
        assert "80 items" in html
        assert "none met the relevance threshold" in html
        assert "adjusting your keywords" in html


class TestSaveReport:
    def test_save_report(self, generator: ReportGenerator, scan_run: ScanRun, tmp_path):
        html = generator.generate_html(SAMPLE_PUBLICATIONS, scan_run)
        path = generator.save_report(html, output_dir=tmp_path)
        assert path.exists()
        assert path.suffix == ".html"
        assert path.parent == tmp_path
        content = path.read_text(encoding="utf-8")
        assert "PubScout Daily Digest" in content


class TestHelpers:
    def test_format_authors_short_list(self):
        assert _format_authors(["A", "B"]) == "A, B"

    def test_format_authors_exact_limit(self):
        assert _format_authors(["A", "B", "C"]) == "A, B, C"

    def test_format_authors_over_limit(self):
        assert _format_authors(["A", "B", "C", "D", "E"]) == "A, B, C + 2 more"

    def test_truncate_abstract_short(self):
        assert _truncate_abstract("Short text") == "Short text"

    def test_truncate_abstract_long(self):
        result = _truncate_abstract("X" * 250)
        assert len(result) == 203  # 200 + "..."
        assert result.endswith("...")

    def test_score_color_none(self):
        assert _score_color(None) == "#aaa"

    def test_score_color_boundaries(self):
        assert _score_color(8.0) == "#27ae60"
        assert _score_color(7.9) == "#f39c12"
        assert _score_color(5.0) == "#f39c12"
        assert _score_color(4.9) == "#e74c3c"
