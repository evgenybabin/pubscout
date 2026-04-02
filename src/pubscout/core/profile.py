"""Profile management — load, save, and bootstrap user configuration."""

from __future__ import annotations

from pathlib import Path

import yaml

from pubscout.core.models import Domain, LLMConfig, ScoringConfig, Source, UserProfile

# ── Defaults ─────────────────────────────────────────────────────────

DEFAULT_DOMAINS = [
    Domain(
        label="LLM Disaggregated Inference",
        query=(
            '("large language model" OR LLM OR transformer) AND '
            '(inference OR serving) AND '
            '("disaggregated inference" OR "prefill" OR "decode" OR "KV cache")'
        ),
    ),
    Domain(
        label="Inference Performance Modeling",
        query=(
            '("large language model" OR LLM OR transformer) AND '
            '(inference OR serving) AND '
            '("performance modeling" OR "analytical model" OR roofline)'
        ),
    ),
    Domain(
        label="Inference Cost Efficiency",
        query=(
            '("large language model" OR LLM OR transformer) AND '
            '(inference OR serving) AND '
            '("performance per dollar" OR "cost efficiency" OR TCO OR "efficiency")'
        ),
    ),
    Domain(
        label="Low-Precision & Quantization",
        query=(
            '("large language model" OR LLM OR transformer) AND '
            '(inference OR serving) AND '
            '("low precision" OR FP8 OR BF16 OR INT8 OR quantization)'
        ),
    ),
    Domain(
        label="Efficient Compute Kernels",
        query=(
            '("large language model" OR LLM OR transformer) AND '
            '(inference OR serving) AND '
            '("efficient kernels" OR "attention kernels" OR GEMM)'
        ),
    ),
    Domain(
        label="RL-Based Code & Kernel Generation",
        query=(
            '("large language model" OR LLM OR transformer) AND '
            '("reinforcement learning" OR "RL-based" OR "learned code generation")'
        ),
    ),
]

DEFAULT_SOURCES = [
    Source(
        label="arXiv",
        type="api",
        url="http://export.arxiv.org/api/query",
        adapter="arxiv",
        enabled=True,
        default=True,
        config={
            "categories": ["cs.LG", "cs.AI", "cs.DC", "cs.PF", "cs.AR", "cs.CL"],
            "max_results_per_query": 100,
            "rate_limit_seconds": 3,
            "lookback_hours": 24,
        },
    ),
]

_PROFILE_DIR = ".pubscout"
_PROFILE_FILE = "profile.yaml"


# ── Public API ───────────────────────────────────────────────────────


def get_profile_path() -> Path:
    """Return ``~/.pubscout/profile.yaml``, creating the directory if needed."""
    directory = Path.home() / _PROFILE_DIR
    directory.mkdir(parents=True, exist_ok=True)
    return directory / _PROFILE_FILE


def load_profile(path: Path | None = None) -> UserProfile:
    """Load and validate a profile from *path* (default: ``get_profile_path()``)."""
    path = path or get_profile_path()
    if not path.exists():
        raise FileNotFoundError(f"Profile not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return UserProfile.model_validate(raw)


def save_profile(profile: UserProfile, path: Path | None = None) -> None:
    """Serialize *profile* to YAML and write to *path*."""
    path = path or get_profile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = profile.model_dump(mode="python")
    path.write_text(
        yaml.dump(data, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def create_default_profile() -> UserProfile:
    """Return a new :class:`UserProfile` populated with spec defaults."""
    return UserProfile(
        domains=list(DEFAULT_DOMAINS),
        sources=list(DEFAULT_SOURCES),
        email="user@example.com",
        llm=LLMConfig(provider="openai", model="gpt-4o-mini"),
        scoring=ScoringConfig(threshold=5.0),
    )
