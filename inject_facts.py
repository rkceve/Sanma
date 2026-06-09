"""UserPromptSubmit hook: inject a compact topic index of this chat's map.

v0.2 pull architecture — this hook makes NO model call. It renders the
sun/planet titles of the current chat's correlation map (a few hundred
characters, ~0 latency) and embeds the exact command the main model can
run to fetch verbatim facts on demand (search_map.py).

Rationale: this hook runs BEFORE the main model sees the user message,
so it cannot know what the model will need. The model itself — with the
full conversation in context — is the only party that can formulate a
useful query. We give it the table of contents and let it pull.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _lib import (  # noqa: E402
    HOOK_ROOT,
    chat_map_dir,
    emit_additional_context,
    load_map,
    log,
    read_hook_payload,
    should_skip,
)

INDEX_HEADER = "## This chat's memory index (CMS)"

INDEX_FOOTER_TEMPLATE = """\
These are topic titles only — past facts from this conversation are stored
under them verbatim. When earlier decisions, constraints, or numbers would
change your answer, recall them with:
  python "{search_script}" --map "{map_path}" "<what you need to know>"
Do not guess stored facts from the titles; either search or ignore."""


def build_index_text(map_data: dict, map_path: Path) -> str | None:
    """Render the topic index, or None when there is nothing to show."""
    suns = map_data.get("suns", [])
    if not suns:
        return None

    lines = [INDEX_HEADER]
    for sun in suns:
        lines.append(f"SUN: {sun.get('title', '?')}")
        for planet in sun.get("planets", []):
            n_facts = len(planet.get("satellites", []))
            unit = "fact" if n_facts == 1 else "facts"
            lines.append(
                f"  - (mass={planet.get('mass', 0)}, {n_facts} {unit}) "
                f"{planet.get('title', '?')}"
            )
    lines.append("")
    lines.append(
        INDEX_FOOTER_TEMPLATE.format(
            search_script=HOOK_ROOT / "search_map.py",
            map_path=map_path,
        )
    )
    return "\n".join(lines)


def main() -> None:
    payload = read_hook_payload()
    cwd = payload.get("cwd") or ""
    session_id = payload.get("session_id") or ""
    if not cwd or not session_id:
        return

    if should_skip(cwd):
        return

    cms_dir = chat_map_dir(cwd, session_id)
    map_data = load_map(cms_dir)
    index = build_index_text(map_data, cms_dir / "correlation_map.json")
    if index is None:
        return

    emit_additional_context("UserPromptSubmit", index)
    log(f"inject_facts: index {len(index)} chars cwd={cwd} sid={session_id[:8]}")


if __name__ == "__main__":
    main()
