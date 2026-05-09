"""Configuration loader for the CMS Hook System.

Defaults are defined here and may be overridden by a TOML file at
`~/.claude/hooks/cms/cms.toml`. Missing keys fall back to the defaults so
partial overrides are safe.

Example user config:

    [models]
    update_model = "claude-sonnet-4-6"
    update_retry_count = 2

    [exclusion]
    skip_cwds = ["**/scratch/**", "/tmp/**"]
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

CLAUDE_HOME = Path(os.path.expanduser("~")) / ".claude"
CONFIG_PATH = CLAUDE_HOME / "hooks" / "cms" / "cms.toml"


# Hardcoded defaults. User overrides via cms.toml are merged on top.
DEFAULTS: dict[str, Any] = {
    "models": {
        "inject_model": "claude-haiku-4-5-20251001",
        "update_model": "claude-sonnet-4-6",
        "inject_timeout_sec": 30,
        "update_timeout_sec": 45,
        "update_retry_count": 1,
    },
    "schema": {
        "forbidden_keys": [
            "label",
            "name",
            "description",
            "summary",
            "branches",
            "note",
            "status",
            "project",
            "formula",
            "parameters",
            "definition",
            "notes",
            "children",
            "items",
            "type",
            "content",
        ],
    },
    "exclusion": {
        # Glob patterns matched against the absolute cwd. If any pattern
        # matches, hooks skip that session entirely.
        "skip_cwds": [],
    },
    "size": {
        # When a project's planet count exceeds this number, we drop the
        # lowest-mass planets at update time to keep the prompt bounded.
        "soft_planet_limit": 50,
    },
    "provider": {
        # "claude_code_cli" — current default; spawns `claude -p`.
        # "anthropic_sdk"   — uses the `anthropic` Python package directly
        #                     (requires ANTHROPIC_API_KEY).
        "mode": "claude_code_cli",
        "api_key_env": "ANTHROPIC_API_KEY",
    },
    "limits": {
        "max_log_bytes": 1_000_000,
        "max_msg_chars": 4000,
    },
}


def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in overrides.items():
        if isinstance(out.get(k), dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _load_tomllib():
    if sys.version_info >= (3, 11):
        import tomllib

        return tomllib
    try:
        import tomli  # type: ignore[import-not-found]

        return tomli
    except ImportError:
        return None


def load(path: Path | None = None) -> dict[str, Any]:
    """Return the merged config dict (defaults + user overrides)."""
    if path is None:
        path = CONFIG_PATH
    if not path.is_file():
        return DEFAULTS
    tomllib = _load_tomllib()
    if tomllib is None:
        return DEFAULTS
    try:
        with open(path, "rb") as f:
            user_cfg = tomllib.load(f)
        return _deep_merge(DEFAULTS, user_cfg)
    except Exception:
        return DEFAULTS


def get(*keys: str, default: Any = None) -> Any:
    """Convenience accessor: ``get('models', 'inject_model')``."""
    cfg: Any = load()
    for k in keys:
        if isinstance(cfg, dict) and k in cfg:
            cfg = cfg[k]
        else:
            return default
    return cfg
