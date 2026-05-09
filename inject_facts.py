"""UserPromptSubmit hook: inject relevant facts from the correlation map."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402

from _lib import (  # noqa: E402
    call_model,
    emit_additional_context,
    load_map,
    log,
    map_to_text,
    project_cms_dir,
    read_hook_payload,
    should_skip,
)

INJECT_SYSTEM_PROMPT = """\
You retrieve relevant context from a tree-structured project memory.

Input has two parts:
- CORRELATION MAP: tree of suns (top-level topics), planets (subtopics with `mass` indicating depth of past discussion), and satellites (details).
- USER MESSAGE: the user's latest input to the assistant.

Output 3-5 short bullet points (each under 25 words) of facts the assistant should remember before responding.

Selection priority:
1. Past decisions or constraints directly relevant to the new message.
2. Planets with mass >= 3 (deeply discussed) even if tangential.
3. Sun-level commitments or scope boundaries.

Format: bare bullets each starting with "- ". No preamble, no header, no closing.
If the map has nothing relevant, output exactly: NO_RELEVANT_CONTEXT
"""


def main() -> None:
    payload = read_hook_payload()
    cwd = payload.get("cwd") or ""
    user_prompt = payload.get("prompt") or ""
    if not cwd or not user_prompt:
        return

    if should_skip(cwd):
        return

    cms_dir = project_cms_dir(cwd)
    map_data = load_map(cms_dir)
    if not map_data.get("suns"):
        return

    map_text = map_to_text(map_data)
    haiku_input = (
        f"CORRELATION MAP:\n{map_text}\n\n"
        f"USER MESSAGE:\n{user_prompt}\n\n"
        f"Output 3-5 bullet facts, or NO_RELEVANT_CONTEXT."
    )

    response = call_model(
        haiku_input,
        system_prompt=INJECT_SYSTEM_PROMPT,
        model=config.get("models", "inject_model"),
        timeout_sec=config.get("models", "inject_timeout_sec"),
    )
    if not response or response.strip() == "NO_RELEVANT_CONTEXT":
        return

    context = (
        "## Project context (from correlation map)\n"
        "Facts surfaced from accumulated project discussion:\n\n"
        f"{response.strip()}"
    )
    emit_additional_context("UserPromptSubmit", context)
    log(f"inject_facts: injected {len(context)} chars cwd={cwd}")


if __name__ == "__main__":
    main()
