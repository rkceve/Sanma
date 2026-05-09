"""Shared utilities for the CMS (Correlation Map System) hooks.

The CMS maintains a per-project tree-structured discussion memory inspired
by Embodiment 1 of patent JP2026-054521. The tree is updated after each
turn and injected into context before the next turn.

Architecture
------------
Two hooks are installed in ``~/.claude/settings.json``:

- ``UserPromptSubmit`` → ``inject_facts.py`` (lightweight model)
- ``Stop``             → ``update_map.py``   (structural model)

Both call into ``call_model()`` here. Two provider modes are supported:

- ``claude_code_cli``  (default): spawns ``claude -p`` headless. Uses the
  user's existing OAuth session via the Claude Code CLI. Requires the
  sandbox-cwd workaround documented below.
- ``anthropic_sdk``     : uses the ``anthropic`` Python SDK directly.
  Requires ``ANTHROPIC_API_KEY``. No transcript files, no tab pollution.

Sandbox cwd workaround (claude_code_cli mode)
---------------------------------------------
The Claude Code CLI has a bug where ``--no-session-persistence`` is silently
ignored when the system prompt is non-trivial in size: the inner session
writes a transcript file to the project folder of the current cwd anyway.
Those transcripts surface as visible chat tabs in the VS Code Claude Code
extension, polluting the user's workspace.

Workaround: spawn ``claude -p`` with cwd set to a dedicated sandbox
directory under ``~/.claude/hooks/cms/_sandbox``. Transcripts then land in
a sandbox-specific project folder which the user is unlikely to have open
as a workspace, so no tabs appear. We additionally wipe the sandbox project
folder before each call and delete the just-written transcript file by
``session_id`` after the call returns.

This workaround is unnecessary when running in ``anthropic_sdk`` mode.
"""

from __future__ import annotations

import fnmatch
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import config

# ---------------------------------------------------------------------------
# Paths and module-level constants
# ---------------------------------------------------------------------------

CLAUDE_HOME = Path(os.path.expanduser("~")) / ".claude"
PROJECTS_DIR = CLAUDE_HOME / "projects"
HOOK_ROOT = CLAUDE_HOME / "hooks" / "cms"
LOG_PATH = HOOK_ROOT / "cms.log"
SANDBOX_DIR = HOOK_ROOT / "_sandbox"

RECURSION_GUARD_ENV = "CMS_HOOK_ACTIVE"
SESSION_DISABLE_ENV = "CMS_DISABLE"

# Convenience constants pulled from config at import time. These are kept
# for back-compat with existing call sites; new code should call
# ``config.get(...)`` directly.
HAIKU_MODEL = config.get("models", "inject_model")
SONNET_MODEL = config.get("models", "update_model")
HAIKU_TIMEOUT_SEC = config.get("models", "inject_timeout_sec")
SONNET_TIMEOUT_SEC = config.get("models", "update_timeout_sec")

# Resolve the claude CLI binary at import time. Cross-platform: Windows
# needs the .cmd/.exe wrapper, Linux/Mac use a plain `claude`.
CLAUDE_BIN = (
    shutil.which("claude.cmd")
    or shutil.which("claude.exe")
    or shutil.which("claude")
    or "claude"
)


# ---------------------------------------------------------------------------
# Recursion guard and session-level disable
# ---------------------------------------------------------------------------


def is_recursive_call() -> bool:
    """Return True if invoked from inside a CMS-spawned subprocess."""
    return os.environ.get(RECURSION_GUARD_ENV) == "1"


def is_session_disabled() -> bool:
    """Return True if the user disabled CMS for this shell session."""
    return os.environ.get(SESSION_DISABLE_ENV) == "1"


def is_excluded(cwd: str) -> bool:
    """Check if cwd matches any pattern in ``config.exclusion.skip_cwds``."""
    patterns = config.get("exclusion", "skip_cwds", default=[])
    if not patterns:
        return False
    cwd_norm = cwd.replace("\\", "/")
    for pattern in patterns:
        pat_norm = str(pattern).replace("\\", "/")
        if fnmatch.fnmatch(cwd_norm, pat_norm):
            return True
    return False


def should_skip(cwd: str) -> bool:
    """Single entry-point for all skip conditions."""
    return is_recursive_call() or is_session_disabled() or is_excluded(cwd)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def log(msg: str) -> None:
    """Append a timestamped line to the CMS log (best-effort, never raises)."""
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        max_bytes = config.get("limits", "max_log_bytes", default=1_000_000)
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > max_bytes:
            LOG_PATH.write_text("", encoding="utf-8")
        with LOG_PATH.open("a", encoding="utf-8") as f:
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Path helpers — cwd to project slug, project CMS dir, sandbox helpers
# ---------------------------------------------------------------------------


def cwd_to_slug(cwd: str) -> str:
    """Convert a cwd to a filesystem-safe slug.

    Mirrors the convention Claude Code uses for its project folders, but
    we only need this to be deterministic for our sandbox bookkeeping.
    """
    s = cwd.replace(":", "-").replace("\\", "-").replace("/", "-").replace(" ", "-")
    while "----" in s:
        s = s.replace("----", "---")
    return s


def project_cms_dir(cwd: str) -> Path:
    """Return the per-project CMS data directory, creating it if absent.

    Legacy v0.1.0 layout — used to hold a single correlation_map.json shared
    by every session in the cwd. Kept for backward-compat tools and as the
    parent directory of chat_map_dir().
    """
    slug = cwd_to_slug(cwd)
    d = PROJECTS_DIR / slug / "memory" / "cms"
    d.mkdir(parents=True, exist_ok=True)
    return d


def chat_map_dir(cwd: str, session_id: str) -> Path:
    """Per-chat correlation map directory.

    Each Claude Code session gets its own correlation_map.json under
    ``<project_cms_dir>/chats/<session_id>/``. This prevents the map from
    bloating across unrelated conversations and keeps the prompt size
    bounded for the lightweight model that updates it.
    """
    d = project_cms_dir(cwd) / "chats" / session_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sandbox_project_dir() -> Path:
    """Project folder where the inner ``claude -p`` writes transcripts."""
    return PROJECTS_DIR / cwd_to_slug(str(SANDBOX_DIR))


def _wipe_sandbox_transcripts() -> None:
    """Delete any leftover transcripts from prior sandbox calls."""
    sbox = _sandbox_project_dir()
    if not sbox.exists():
        return
    for f in sbox.glob("*.jsonl"):
        try:
            f.unlink()
        except Exception:
            pass


def _delete_sandbox_transcript(session_id: str) -> None:
    """Delete the transcript the inner session wrote for ``session_id``."""
    if not session_id:
        return
    target = _sandbox_project_dir() / f"{session_id}.jsonl"
    try:
        if target.exists():
            target.unlink()
    except Exception as e:
        log(f"sandbox cleanup failed for {session_id[:8]}: {e}")


# ---------------------------------------------------------------------------
# Correlation map storage and schema
# ---------------------------------------------------------------------------


def empty_map() -> dict[str, Any]:
    return {"version": 1, "suns": []}


def load_map(cms_dir: Path) -> dict[str, Any]:
    path = cms_dir / "correlation_map.json"
    if not path.is_file():
        return empty_map()
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or "suns" not in data:
            return empty_map()
        return data
    except Exception as e:
        log(f"load_map failed: {e}")
        return empty_map()


def save_map(cms_dir: Path, data: dict[str, Any]) -> None:
    """Atomically write correlation_map.json (temp-file + rename)."""
    path = cms_dir / "correlation_map.json"
    fd, tmp = tempfile.mkstemp(prefix="cmap_", suffix=".tmp", dir=str(cms_dir))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def validate_map_schema(data: Any) -> bool:
    """Strict check that data follows the canonical CMS schema."""
    if not isinstance(data, dict):
        return False
    if "suns" not in data or not isinstance(data["suns"], list):
        return False
    for sun in data["suns"]:
        if not isinstance(sun, dict):
            return False
        if "title" not in sun or "planets" not in sun:
            return False
        if not isinstance(sun["planets"], list):
            return False
        for planet in sun["planets"]:
            if not isinstance(planet, dict):
                return False
            if "title" not in planet or "mass" not in planet:
                return False
            if not isinstance(planet["mass"], int):
                return False
            sats = planet.get("satellites", [])
            if not isinstance(sats, list):
                return False
            for sat in sats:
                if not isinstance(sat, dict) or "text" not in sat:
                    return False
    return True


def map_to_text(map_data: dict[str, Any]) -> str:
    """Render the map as a compact textual outline for prompt inclusion."""
    lines: list[str] = []
    for sun in map_data.get("suns", []):
        lines.append(f"SUN: {sun.get('title', '?')}")
        for planet in sun.get("planets", []):
            mass = planet.get("mass", 0)
            lines.append(f"  PLANET (mass={mass}): {planet.get('title', '?')}")
            for sat in planet.get("satellites", []):
                lines.append(f"    SAT: {sat.get('text', '?')}")
    return "\n".join(lines) if lines else "(empty)"


def prune_low_mass_planets(
    map_data: dict[str, Any], soft_limit: int
) -> dict[str, Any]:
    """If total planet count exceeds ``soft_limit``, drop the lowest-mass planets.

    Suns themselves (and their high-mass planets) are preserved. Used at
    update time to bound the prompt size as the map grows.
    """
    suns = map_data.get("suns", [])
    total_planets = sum(len(s.get("planets", [])) for s in suns)
    if total_planets <= soft_limit:
        return map_data

    # Collect (mass, sun_idx, planet_idx) tuples
    candidates: list[tuple[int, int, int]] = []
    for si, sun in enumerate(suns):
        for pi, planet in enumerate(sun.get("planets", [])):
            mass = planet.get("mass", 0)
            mass = mass if isinstance(mass, int) else 0
            candidates.append((mass, si, pi))

    candidates.sort()  # ascending by mass
    n_to_drop = total_planets - soft_limit
    to_drop = {(si, pi) for _, si, pi in candidates[:n_to_drop]}

    new_suns: list[dict[str, Any]] = []
    for si, sun in enumerate(suns):
        kept = [p for pi, p in enumerate(sun.get("planets", [])) if (si, pi) not in to_drop]
        new_suns.append({**sun, "planets": kept})

    return {**map_data, "suns": new_suns}


# ---------------------------------------------------------------------------
# Provider: Claude Code CLI subprocess (with sandbox)
# ---------------------------------------------------------------------------


def _call_via_cli(
    prompt: str, system_prompt: str, model: str, timeout_sec: int
) -> str | None:
    SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
    _wipe_sandbox_transcripts()

    env = os.environ.copy()
    env[RECURSION_GUARD_ENV] = "1"

    cmd = [
        CLAUDE_BIN,
        "-p",
        "--model",
        model,
        "--output-format",
        "json",
        "--system-prompt",
        system_prompt,
        "--tools",
        "",
        "--disable-slash-commands",
        "--setting-sources",
        "",
        "--no-session-persistence",
    ]

    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            cwd=str(SANDBOX_DIR),
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired:
        log(f"_call_via_cli({model}): timeout")
        return None
    except Exception as e:
        log(f"_call_via_cli({model}): spawn failed: {e}")
        return None

    if result.returncode != 0:
        log(f"_call_via_cli({model}): exit {result.returncode}: {result.stderr[:300]}")
        return None

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        log(f"_call_via_cli({model}): malformed JSON: {result.stdout[:300]}")
        return None

    _delete_sandbox_transcript(data.get("session_id") or "")

    if data.get("is_error"):
        log(f"_call_via_cli({model}): api error: {str(data)[:300]}")
        return None

    text = (data.get("result") or "").strip()
    return text or None


# ---------------------------------------------------------------------------
# Provider: Anthropic SDK (requires ANTHROPIC_API_KEY)
# ---------------------------------------------------------------------------


def _call_via_sdk(
    prompt: str, system_prompt: str, model: str, timeout_sec: int
) -> str | None:
    try:
        import anthropic  # type: ignore[import-not-found]
    except ImportError:
        log("anthropic SDK not installed; run: pip install anthropic")
        return None

    api_key_env = config.get("provider", "api_key_env", default="ANTHROPIC_API_KEY")
    api_key = os.environ.get(api_key_env)
    if not api_key:
        log(f"_call_via_sdk: {api_key_env} not set")
        return None

    try:
        client = anthropic.Anthropic(api_key=api_key, timeout=float(timeout_sec))
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        log(f"_call_via_sdk({model}): API call failed: {e}")
        return None

    parts: list[str] = []
    for block in response.content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    text = "".join(parts).strip()
    return text or None


# ---------------------------------------------------------------------------
# Public model invocation with retry + provider routing
# ---------------------------------------------------------------------------


def call_model(
    prompt: str,
    system_prompt: str,
    model: str | None = None,
    timeout_sec: int | None = None,
    retry_count: int | None = None,
) -> str | None:
    """Invoke the configured provider with retry on transient failures.

    Returns the model's text output, or None on permanent failure.
    """
    if model is None:
        model = HAIKU_MODEL
    if timeout_sec is None:
        timeout_sec = HAIKU_TIMEOUT_SEC
    if retry_count is None:
        retry_count = config.get("models", "update_retry_count", default=0)

    mode = config.get("provider", "mode", default="claude_code_cli")
    backend = _call_via_sdk if mode == "anthropic_sdk" else _call_via_cli

    for attempt in range(retry_count + 1):
        result = backend(prompt, system_prompt, model, timeout_sec)
        if result is not None:
            return result
        if attempt < retry_count:
            log(f"call_model({model}): attempt {attempt + 1} failed, retrying")

    return None


# ---------------------------------------------------------------------------
# Hook I/O — read JSON payload from stdin, emit additionalContext to stdout
# ---------------------------------------------------------------------------


def read_hook_payload() -> dict[str, Any]:
    """Decode the hook payload Claude Code provides on stdin (UTF-8)."""
    try:
        raw = sys.stdin.buffer.read()
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return {}


def emit_additional_context(event_name: str, text: str) -> None:
    """Emit a hookSpecificOutput JSON for additionalContext injection.

    Writes UTF-8 bytes directly to bypass Windows cp932 default encoding.
    """
    payload = {
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "additionalContext": text,
        }
    }
    sys.stdout.buffer.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    sys.stdout.buffer.flush()


# ---------------------------------------------------------------------------
# Transcript parsing — extract the most recent user/assistant exchange
# ---------------------------------------------------------------------------


def extract_message_text(content: Any) -> str:
    """Flatten a Claude Code message content field into plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "\n".join(parts)
    if isinstance(content, dict):
        return content.get("text", "")
    return ""


def read_last_exchange(transcript_path: str) -> tuple[str, str]:
    """Return (last_user_text, last_assistant_text) from a JSONL transcript."""
    last_user = ""
    last_assistant = ""

    if not transcript_path or not os.path.isfile(transcript_path):
        return last_user, last_assistant

    try:
        with open(transcript_path, encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        log(f"read_last_exchange: cannot read {transcript_path}: {e}")
        return last_user, last_assistant

    for line in reversed(lines):
        if last_user and last_assistant:
            break
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue

        role = obj.get("role")
        content = obj.get("content")
        if not role and isinstance(obj.get("message"), dict):
            role = obj["message"].get("role")
            content = obj["message"].get("content")
        if not role:
            role = obj.get("type")

        text = extract_message_text(content)
        if not text:
            continue
        if role == "assistant" and not last_assistant:
            last_assistant = text
        elif role == "user" and not last_user:
            last_user = text

    return last_user, last_assistant
