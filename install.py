"""Idempotent installer for the CMS Hook System.

Adds the two hook entries to ``~/.claude/settings.json`` without clobbering
existing hooks set up by the user or other tools. Cross-platform: detects
the Python interpreter and claude CLI binary at install time.

Usage::

    python install.py             # install
    python install.py --uninstall # remove only the CMS hook entries
    python install.py --status    # show current state
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

CLAUDE_HOME = Path(os.path.expanduser("~")) / ".claude"
SETTINGS_PATH = CLAUDE_HOME / "settings.json"
HOOK_DIR = CLAUDE_HOME / "hooks" / "cms"
INJECT_SCRIPT = HOOK_DIR / "inject_facts.py"
UPDATE_SCRIPT = HOOK_DIR / "update_map.py"

INJECT_TIMEOUT = 30
UPDATE_TIMEOUT = 180

CMS_SCRIPT_NAMES = ("inject_facts.py", "update_map.py")


def _hook_command(script_path: Path) -> str:
    """Build a cross-platform command string for a hook entry."""
    py = sys.executable or ("python" if os.name == "nt" else "python3")
    script = str(script_path).replace("\\", "/")
    return f'"{py}" "{script}"'


def _read_settings() -> dict[str, Any]:
    if not SETTINGS_PATH.is_file():
        return {}
    with SETTINGS_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _write_settings(data: dict[str, Any]) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, SETTINGS_PATH)


def _has_cms_hook(entries: list[dict[str, Any]], script_basename: str) -> bool:
    for entry in entries:
        for hook in entry.get("hooks", []):
            if script_basename in hook.get("command", ""):
                return True
    return False


def _ensure_hook(
    settings: dict[str, Any],
    event: str,
    script_path: Path,
    timeout: int,
) -> bool:
    settings.setdefault("hooks", {})
    settings["hooks"].setdefault(event, [])
    entries: list[dict[str, Any]] = settings["hooks"][event]
    if _has_cms_hook(entries, script_path.name):
        return False
    entries.append(
        {
            "hooks": [
                {
                    "type": "command",
                    "command": _hook_command(script_path),
                    "timeout": timeout,
                }
            ]
        }
    )
    return True


def _remove_cms_hooks(settings: dict[str, Any]) -> int:
    if "hooks" not in settings:
        return 0
    removed = 0
    for event, entries in list(settings["hooks"].items()):
        new_entries = []
        for entry in entries:
            kept = [
                h
                for h in entry.get("hooks", [])
                if not any(name in h.get("command", "") for name in CMS_SCRIPT_NAMES)
            ]
            if len(kept) != len(entry.get("hooks", [])):
                removed += 1
            if kept:
                new_entries.append({**entry, "hooks": kept})
        if new_entries:
            settings["hooks"][event] = new_entries
        else:
            del settings["hooks"][event]
    return removed


def install() -> int:
    print("=== CMS Hook System installer ===\n")

    print("Environment:")
    if not INJECT_SCRIPT.is_file():
        print(f"  ERROR: missing {INJECT_SCRIPT}")
        return 1
    if not UPDATE_SCRIPT.is_file():
        print(f"  ERROR: missing {UPDATE_SCRIPT}")
        return 1

    claude_bin = (
        shutil.which("claude.cmd")
        or shutil.which("claude.exe")
        or shutil.which("claude")
    )
    if claude_bin:
        print(f"  claude binary : {claude_bin}")
    else:
        print(
            "  WARNING: claude CLI not on PATH. Install Claude Code, "
            "or switch to provider.mode='anthropic_sdk' in cms.toml."
        )
    print(f"  python        : {sys.executable}")
    print(f"  hooks dir     : {HOOK_DIR}")
    print(f"  settings.json : {SETTINGS_PATH}")

    print("\nUpdating settings.json...")
    settings = _read_settings()
    changed_inject = _ensure_hook(
        settings, "UserPromptSubmit", INJECT_SCRIPT, INJECT_TIMEOUT
    )
    changed_update = _ensure_hook(settings, "Stop", UPDATE_SCRIPT, UPDATE_TIMEOUT)

    if not (changed_inject or changed_update):
        print("  Already installed — no changes.")
        return 0

    _write_settings(settings)
    print("  Done.")
    if changed_inject:
        print(f"    + UserPromptSubmit -> {INJECT_SCRIPT.name}")
    if changed_update:
        print(f"    + Stop -> {UPDATE_SCRIPT.name}")
    print("\nHooks will fire on next Claude Code session.")
    return 0


def uninstall() -> int:
    print("=== CMS Hook System uninstaller ===\n")
    settings = _read_settings()
    if not settings:
        print("  settings.json not found.")
        return 0
    removed = _remove_cms_hooks(settings)
    if removed == 0:
        print("  No CMS hooks found.")
        return 0
    _write_settings(settings)
    print(f"  Removed {removed} hook entry/entries.")
    return 0


def status() -> int:
    print("=== CMS Hook System status ===\n")
    settings = _read_settings()
    found: list[tuple[str, str, Any]] = []
    for event, entries in (settings.get("hooks") or {}).items():
        for entry in entries:
            for hook in entry.get("hooks", []):
                cmd = hook.get("command", "")
                for script in CMS_SCRIPT_NAMES:
                    if script in cmd:
                        found.append((event, script, hook.get("timeout")))
    if not found:
        print("  Not installed.")
    else:
        for event, script, timeout in found:
            print(f"  {event} -> {script} (timeout={timeout}s)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="CMS Hook System installer")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--uninstall", action="store_true", help="Remove CMS hook entries")
    group.add_argument("--status", action="store_true", help="Show current state")
    args = parser.parse_args()

    if args.uninstall:
        return uninstall()
    if args.status:
        return status()
    return install()


if __name__ == "__main__":
    sys.exit(main())
