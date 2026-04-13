"""Tests for pubscout.core.profile — profile management functions."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from pubscout.core.profile import (
    create_default_profile,
    load_profile,
    save_profile,
)


class TestCreateDefaultProfile:
    """Validate the factory-default profile."""

    def test_returns_valid_profile_with_six_domains(self) -> None:
        profile = create_default_profile()
        assert len(profile.domains) == 6

    def test_returns_valid_profile_with_default_sources(self) -> None:
        profile = create_default_profile()
        assert len(profile.sources) == 6
        labels = {s.label for s in profile.sources}
        assert "arXiv" in labels
        assert "Semantic Scholar" in labels
        assert "ACL Anthology" in labels
        assert "PapersWithCode" in labels
        assert "OpenReview" in labels
        assert "Microsoft Research Blog" in labels

    def test_all_default_domains_are_enabled(self) -> None:
        profile = create_default_profile()
        for domain in profile.domains:
            assert domain.enabled is True, f"Domain {domain.label!r} should be enabled"

    def test_arxiv_source_has_correct_categories(self) -> None:
        profile = create_default_profile()
        arxiv = profile.sources[0]
        assert arxiv.label == "arXiv"
        expected = ["cs.LG", "cs.AI", "cs.DC", "cs.PF", "cs.AR", "cs.CL"]
        assert arxiv.config is not None
        assert arxiv.config["categories"] == expected

    def test_default_llm_config(self) -> None:
        profile = create_default_profile()
        assert profile.llm.provider == "openai"
        assert profile.llm.model == "gpt-4o-mini"

    def test_default_scoring_threshold(self) -> None:
        profile = create_default_profile()
        assert profile.scoring.threshold == 5.0


class TestSaveAndLoadRoundtrip:
    """Ensure save → load preserves all profile data."""

    def test_roundtrip_preserves_data(self, tmp_path: Path) -> None:
        original = create_default_profile()
        file = tmp_path / "profile.yaml"
        save_profile(original, path=file)
        loaded = load_profile(path=file)
        assert loaded == original

    def test_roundtrip_preserves_domain_queries(self, tmp_path: Path) -> None:
        original = create_default_profile()
        file = tmp_path / "profile.yaml"
        save_profile(original, path=file)
        loaded = load_profile(path=file)
        for orig, loaded_d in zip(original.domains, loaded.domains):
            assert orig.query == loaded_d.query

    def test_roundtrip_preserves_source_config(self, tmp_path: Path) -> None:
        original = create_default_profile()
        file = tmp_path / "profile.yaml"
        save_profile(original, path=file)
        loaded = load_profile(path=file)
        assert loaded.sources[0].config == original.sources[0].config


class TestLoadProfileErrors:
    """Edge-case handling for load_profile."""

    def test_missing_file_raises_file_not_found(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent.yaml"
        with pytest.raises(FileNotFoundError):
            load_profile(path=missing)


class TestYamlReadability:
    """The on-disk YAML must be human-readable (block style)."""

    def test_yaml_is_block_style(self, tmp_path: Path) -> None:
        profile = create_default_profile()
        file = tmp_path / "profile.yaml"
        save_profile(profile, path=file)
        text = file.read_text(encoding="utf-8")
        # Block-style YAML uses newlines and indentation, not braces/brackets
        # for top-level mappings.
        assert "{" not in text.split("\n")[0]
        parsed = yaml.safe_load(text)
        assert isinstance(parsed, dict)

    def test_save_creates_parent_directories(self, tmp_path: Path) -> None:
        profile = create_default_profile()
        nested = tmp_path / "a" / "b" / "profile.yaml"
        save_profile(profile, path=nested)
        assert nested.exists()
