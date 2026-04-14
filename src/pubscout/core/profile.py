"""Profile management — load, save, and bootstrap user configuration."""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

import yaml

from pubscout.core.models import (
    Domain,
    EmailConfig,
    LLMConfig,
    ScoringConfig,
    Source,
    UserProfile,
)

logger = logging.getLogger(__name__)

# ── Defaults ─────────────────────────────────────────────────────────

CURRENT_PROFILE_VERSION = 2

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
    Domain(
        label="Symbolic & Scientific Computing",
        query=(
            '("symbolic regression" OR "symbolic computation" OR "scientific computing") AND '
            '("neural" OR "gradient" OR "machine learning" OR "deep learning" OR LLM OR transformer)'
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
            "categories": ["cs.LG", "cs.AI", "cs.DC", "cs.PF", "cs.AR", "cs.CL", "cs.SC", "cs.NE"],
            "max_results_per_query": 100,
            "rate_limit_seconds": 3,
            "lookback_hours": 24,
        },
    ),
    Source(
        label="Semantic Scholar",
        type="api",
        url="https://api.semanticscholar.org/graph/v1/paper/search",
        adapter="semantic_scholar",
        enabled=True,
        default=True,
        config={
            "fields": "title,authors,abstract,url,externalIds,publicationDate",
            "limit": 100,
            "api_key_env": "S2_API_KEY",
        },
    ),
    Source(
        label="ACL Anthology",
        type="rss",
        url="https://aclanthology.org/papers/index.xml",
        adapter="rss",
        enabled=True,
        default=True,
        config={},
    ),
    Source(
        label="PapersWithCode",
        type="web",
        url="https://paperswithcode.com",
        adapter="web",
        enabled=True,
        default=True,
        config={},
    ),
    Source(
        label="OpenReview",
        type="web",
        url="https://openreview.net",
        adapter="web",
        enabled=True,
        default=True,
        config={},
    ),
    Source(
        label="Microsoft Research Blog",
        type="web",
        url="https://www.microsoft.com/en-us/research/blog/",
        adapter="web",
        enabled=True,
        default=True,
        config={},
    ),
]

_PROFILE_DIR = ".pubscout"
_PROFILE_FILE = "profile.yaml"


# ── Migration ────────────────────────────────────────────────────────


def migrate_profile(raw: dict) -> dict:
    """Auto-migrate a raw profile dict to the current schema version.

    Mutates and returns *raw*.  Creates a backup of the YAML file before
    writing the migrated version (handled by the caller via ``load_profile``).
    """
    version = raw.get("version", 1)

    if version < 2:
        raw = _migrate_v1_to_v2(raw)

    return raw


def _migrate_v1_to_v2(raw: dict) -> dict:
    """Migrate v1 → v2: email string → EmailConfig, add version field."""
    # email: "user@example.com" → email: {transport: file, from_addr: ..., to_addr: ...}
    email_val = raw.get("email")
    if isinstance(email_val, str):
        raw["email"] = {
            "transport": "file",
            "from_addr": email_val,
            "to_addr": email_val,
        }

    # Ensure all sources have v2 fields
    for src in raw.get("sources", []):
        src.setdefault("user_added", False)
        src.setdefault("added_date", None)

    raw["version"] = 2
    logger.info("Migrated profile from v1 → v2")
    return raw


def _backup_profile(path: Path) -> Path:
    """Create a timestamped backup of *path*."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    backup = path.with_suffix(f".bak.{ts}")
    shutil.copy2(path, backup)
    logger.info("Profile backed up to %s", backup)
    return backup


# ── Public API ───────────────────────────────────────────────────────


def get_profile_path() -> Path:
    """Return ``~/.pubscout/profile.yaml``, creating the directory if needed."""
    directory = Path.home() / _PROFILE_DIR
    directory.mkdir(parents=True, exist_ok=True)
    return directory / _PROFILE_FILE


def load_profile(path: Path | None = None) -> UserProfile:
    """Load and validate a profile from *path* (default: ``get_profile_path()``).

    Automatically migrates older profile versions and backs up the original.
    """
    path = path or get_profile_path()
    if not path.exists():
        raise FileNotFoundError(f"Profile not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))

    # Migrate if needed
    version = raw.get("version", 1)
    if version < CURRENT_PROFILE_VERSION:
        _backup_profile(path)
        raw = migrate_profile(raw)
        # Write migrated profile back
        path.write_text(
            yaml.dump(raw, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

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
        email=EmailConfig(),
        llm=LLMConfig(provider="openai", model="gpt-4o-mini"),
        scoring=ScoringConfig(threshold=5.0),
        version=CURRENT_PROFILE_VERSION,
    )
