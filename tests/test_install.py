"""Tests for install.py: idempotent settings.json injection, status, uninstall."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import install


@pytest.fixture
def stub_settings_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect SETTINGS_PATH so each test runs against a temp file."""
    p = tmp_path / "settings.json"
    monkeypatch.setattr(install, "SETTINGS_PATH", p)
    return p


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_install_creates_settings_file(stub_settings_path: Path):
    assert not stub_settings_path.exists()
    install.install()
    assert stub_settings_path.exists()
    data = _read(stub_settings_path)
    assert "UserPromptSubmit" in data["hooks"]
    assert "Stop" in data["hooks"]


def test_install_preserves_existing_unrelated_keys(stub_settings_path: Path):
    stub_settings_path.write_text(json.dumps({
        "model": "opus",
        "permissions": {"allow": ["Bash(*)"]},
    }), encoding="utf-8")
    install.install()
    data = _read(stub_settings_path)
    assert data["model"] == "opus"
    assert data["permissions"] == {"allow": ["Bash(*)"]}
    assert "UserPromptSubmit" in data["hooks"]


def test_install_preserves_existing_unrelated_hooks(stub_settings_path: Path):
    stub_settings_path.write_text(json.dumps({
        "hooks": {
            "PostToolUse": [
                {"matcher": "Write|Edit", "hooks": [
                    {"type": "command", "command": "ruff check %s"}]},
            ]
        }
    }), encoding="utf-8")
    install.install()
    data = _read(stub_settings_path)
    assert "PostToolUse" in data["hooks"]
    assert "ruff check" in data["hooks"]["PostToolUse"][0]["hooks"][0]["command"]


def test_install_idempotent(stub_settings_path: Path):
    install.install()
    first = _read(stub_settings_path)
    install.install()  # second call should be a no-op
    second = _read(stub_settings_path)
    assert first == second
    # Each event has exactly one entry, not duplicated
    for event in ("UserPromptSubmit", "Stop"):
        assert len(second["hooks"][event]) == 1


def test_uninstall_removes_only_cms_hooks(stub_settings_path: Path):
    stub_settings_path.write_text(json.dumps({
        "hooks": {
            "PostToolUse": [
                {"matcher": "Write|Edit", "hooks": [
                    {"type": "command", "command": "ruff check x"}]},
            ]
        }
    }), encoding="utf-8")
    install.install()
    install.uninstall()
    data = _read(stub_settings_path)
    # PostToolUse ruff hook still there
    assert "PostToolUse" in data["hooks"]
    # CMS hook events removed
    assert "UserPromptSubmit" not in data["hooks"]
    assert "Stop" not in data["hooks"]


def test_uninstall_when_no_settings_is_safe(stub_settings_path: Path):
    """uninstall on a missing settings.json must not crash."""
    install.uninstall()
    # File still doesn't exist; no exception raised
    assert not stub_settings_path.exists()


def test_uninstall_when_no_cms_hooks_is_noop(stub_settings_path: Path):
    stub_settings_path.write_text(json.dumps({
        "hooks": {"PostToolUse": [{"hooks": [
            {"type": "command", "command": "echo unrelated"}]}]}
    }), encoding="utf-8")
    before = _read(stub_settings_path)
    install.uninstall()
    after = _read(stub_settings_path)
    assert before == after


def test_install_then_status(stub_settings_path: Path, capsys):
    install.install()
    install.status()
    output = capsys.readouterr().out
    assert "UserPromptSubmit" in output
    assert "inject_facts.py" in output
    assert "Stop" in output
    assert "update_map.py" in output


def test_status_when_not_installed(stub_settings_path: Path, capsys):
    install.status()
    assert "Not installed" in capsys.readouterr().out


def test_hook_command_quotes_paths_with_spaces():
    """Paths with spaces must round-trip through the hook command."""
    p = Path("/path with/spaces/script.py")
    cmd = install._hook_command(p)
    # Both python and script paths should be inside double quotes
    assert cmd.count('"') >= 4
    assert "script.py" in cmd
