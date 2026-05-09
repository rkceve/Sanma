"""Shared pytest fixtures for the CMS test suite."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Make the parent dir importable so tests can `import _lib, config`.
HOOK_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HOOK_DIR))


@pytest.fixture
def tmp_cms_dir(tmp_path: Path) -> Path:
    """Per-test temp directory for correlation_map.json and friends."""
    d = tmp_path / "cms"
    d.mkdir()
    return d


@pytest.fixture
def sample_map() -> dict:
    """A small but structurally complete map for tests."""
    return {
        "version": 1,
        "suns": [
            {
                "id": "sun-1",
                "title": "VR demo",
                "planets": [
                    {
                        "id": "planet-1",
                        "title": "WebGL renderer",
                        "mass": 4,
                        "satellites": [
                            {"id": "sat-1", "text": "Replace OpenGL with WebGL2"},
                            {"id": "sat-2", "text": "Reuse 3DGS code via Emscripten"},
                        ],
                    },
                    {
                        "id": "planet-2",
                        "title": "Latency budget",
                        "mass": 2,
                        "satellites": [
                            {"id": "sat-3", "text": "End-to-end <20ms"},
                        ],
                    },
                ],
            }
        ],
    }


@pytest.fixture
def fake_transcript(tmp_path: Path) -> Path:
    """A minimal JSONL transcript with one user/assistant exchange."""
    import json

    p = tmp_path / "transcript.jsonl"
    with p.open("w", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {"role": "user", "content": "Hello, what is the latency target?"}
            )
            + "\n"
        )
        f.write(
            json.dumps(
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": "End-to-end target is below 20ms.",
                        }
                    ],
                }
            )
            + "\n"
        )
    return p


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear CMS-relevant env vars so tests start from a known state."""
    for var in ("CMS_HOOK_ACTIVE", "CMS_DISABLE", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def isolated_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point config.CONFIG_PATH at a per-test toml file (initially absent)."""
    import config

    cfg_path = tmp_path / "cms.toml"
    monkeypatch.setattr(config, "CONFIG_PATH", cfg_path)
    return cfg_path


def write_toml(path: Path, content: str) -> None:
    """Helper for tests that need a custom cms.toml."""
    path.write_text(content, encoding="utf-8")


# Make the helper accessible via fixture name too.
@pytest.fixture
def toml_writer():
    return write_toml


@pytest.fixture(autouse=True)
def _no_real_subprocess(monkeypatch: pytest.MonkeyPatch):
    """Safety net: prevent any test from accidentally spawning claude.cmd.

    Tests that need to exercise call_model should monkeypatch the
    ``_call_via_cli`` / ``_call_via_sdk`` functions directly.
    """
    import _lib

    def _refuse(*args, **kwargs):
        raise RuntimeError(
            "subprocess.run was invoked unexpectedly during tests; "
            "patch _call_via_cli/_call_via_sdk instead."
        )

    monkeypatch.setattr(_lib.subprocess, "run", _refuse)


@pytest.fixture
def reset_log(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect the CMS log to a per-test file."""
    import _lib

    log_path = tmp_path / "cms.log"
    monkeypatch.setattr(_lib, "LOG_PATH", log_path)
    return log_path


@pytest.fixture
def isolated_sandbox(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect SANDBOX_DIR + PROJECTS_DIR to a per-test layout."""
    import _lib

    sbox = tmp_path / "sandbox"
    sbox.mkdir()
    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setattr(_lib, "SANDBOX_DIR", sbox)
    monkeypatch.setattr(_lib, "PROJECTS_DIR", projects)
    monkeypatch.setattr(_lib, "CLAUDE_HOME", tmp_path)
    return sbox


@pytest.fixture
def project_root() -> Path:
    return HOOK_DIR


@pytest.fixture
def settings_path_factory(tmp_path: Path):
    """Factory returning a fresh settings.json path under tmp_path."""

    def _make(name: str = "settings.json") -> Path:
        return tmp_path / name

    return _make


# Avoid logging noise during tests.
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
