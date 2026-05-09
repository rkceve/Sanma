"""Tests for config.load() — defaults, TOML overrides, deep merge."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import config


def test_defaults_when_no_config_file(isolated_config: Path):
    """When cms.toml is absent, return DEFAULTS verbatim."""
    cfg = config.load()
    assert cfg == config.DEFAULTS


def test_partial_override_merges(isolated_config: Path, toml_writer):
    toml_writer(isolated_config, """
[models]
inject_timeout_sec = 99
""")
    cfg = config.load()
    # Override applied
    assert cfg["models"]["inject_timeout_sec"] == 99
    # Other keys in [models] preserved from defaults
    assert cfg["models"]["inject_model"] == config.DEFAULTS["models"]["inject_model"]
    # Other top-level sections preserved
    assert cfg["schema"] == config.DEFAULTS["schema"]


def test_full_section_override(isolated_config: Path, toml_writer):
    toml_writer(isolated_config, """
[exclusion]
skip_cwds = ["/tmp/**", "**/scratch/**"]
""")
    cfg = config.load()
    assert cfg["exclusion"]["skip_cwds"] == ["/tmp/**", "**/scratch/**"]


def test_malformed_toml_falls_back_to_defaults(isolated_config: Path, toml_writer):
    toml_writer(isolated_config, "this is not valid TOML [[[")
    cfg = config.load()
    assert cfg == config.DEFAULTS


def test_get_accessor_traverses(isolated_config: Path):
    assert config.get("models", "inject_model") == \
        config.DEFAULTS["models"]["inject_model"]


def test_get_accessor_returns_default_for_missing_key(isolated_config: Path):
    assert config.get("nonexistent", "key", default="fallback") == "fallback"


def test_get_accessor_returns_section(isolated_config: Path):
    assert config.get("models") == config.DEFAULTS["models"]


def test_provider_mode_defaults_to_cli():
    assert config.DEFAULTS["provider"]["mode"] == "claude_code_cli"


def test_provider_mode_overridable(isolated_config: Path, toml_writer):
    toml_writer(isolated_config, """
[provider]
mode = "anthropic_sdk"
""")
    assert config.get("provider", "mode") == "anthropic_sdk"
    assert config.get("provider", "api_key_env") == \
        config.DEFAULTS["provider"]["api_key_env"]


def test_deep_merge_preserves_other_subsections(isolated_config: Path, toml_writer):
    """Override in [models] must not wipe [exclusion] etc."""
    toml_writer(isolated_config, """
[models]
update_retry_count = 3
""")
    cfg = config.load()
    assert cfg["models"]["update_retry_count"] == 3
    assert cfg["exclusion"] == config.DEFAULTS["exclusion"]
    assert cfg["size"] == config.DEFAULTS["size"]
    assert cfg["limits"] == config.DEFAULTS["limits"]


@pytest.mark.skipif(sys.version_info < (3, 11), reason="tomllib stdlib is 3.11+")
def test_tomllib_available_on_modern_python():
    """The installed Python is new enough for stdlib tomllib (no tomli needed)."""
    import tomllib  # noqa: F401
