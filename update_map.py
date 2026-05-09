"""Stop hook: update correlation map with the latest exchange."""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402

from _lib import (  # noqa: E402
    call_model,
    load_map,
    log,
    project_cms_dir,
    prune_low_mass_planets,
    read_hook_payload,
    read_last_exchange,
    save_map,
    should_skip,
    validate_map_schema,
)

UPDATE_SYSTEM_PROMPT = (
    "You output JSON only. The ONLY allowed keys are: "
    "version, suns, id, title, planets, mass, satellites, text. "
    "Forbidden keys (do NOT use): label, name, description, summary, "
    "branches, note, status, project, formula, parameters, definition, "
    "notes, children, items, type, content. "
    "Output starts with `{\"version\":1,\"suns\":[` and is pure JSON. "
    "No prose, no markdown fences, no commentary."
)

USER_PROMPT_TEMPLATE = """\
TASK: update the correlation map below given the new exchange.

ALLOWED KEYS: version, suns, id, title, planets, mass, satellites, text.
NO OTHER KEYS. If you are tempted to add `label`, `description`, `summary`,
`branches`, `note`, `status`, `formula`, `parameters` — DO NOT. Express
that information inside the `text` field of a satellite instead.

UPDATE RULES (apply all that fit):
1. Continuation of existing planet's topic → increment that planet's `mass` by 1.
2. New factual detail under existing planet → add as a new satellite.
3. New subtopic under existing sun → add as a new planet (mass=1).
4. Entirely new top-level domain → add a new sun with one initial planet (mass=1).
5. Trivial exchange (acknowledgment, clarification, off-topic) → return the input map unchanged.
6. Never delete or rename existing nodes. Only ADD or INCREMENT mass.
7. Generate fresh ids: scan existing ids of each type and pick the next integer (sun-N, planet-N, sat-N).

CURRENT MAP:
{map_json}

NEW EXCHANGE:
USER: {user_text}

ASSISTANT: {assistant_text}

Output the complete updated map as pure JSON. Begin with `{{` and end with `}}`.
"""


def find_json_in_response(text: str) -> dict | None:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    blob = text[start : end + 1]
    try:
        return json.loads(blob)
    except Exception:
        return None


def main() -> None:
    payload = read_hook_payload()
    cwd = payload.get("cwd") or ""
    transcript_path = payload.get("transcript_path") or ""
    if not cwd or not transcript_path:
        return

    if should_skip(cwd):
        return

    user_text, assistant_text = read_last_exchange(transcript_path)
    if not user_text and not assistant_text:
        return

    max_chars = config.get("limits", "max_msg_chars", default=4000)
    user_text = user_text[:max_chars]
    assistant_text = assistant_text[:max_chars]

    cms_dir = project_cms_dir(cwd)
    map_data = load_map(cms_dir)

    user_prompt = USER_PROMPT_TEMPLATE.format(
        map_json=json.dumps(map_data, ensure_ascii=False, indent=2),
        user_text=user_text,
        assistant_text=assistant_text,
    )

    response = call_model(
        user_prompt,
        system_prompt=UPDATE_SYSTEM_PROMPT,
        model=config.get("models", "update_model"),
        timeout_sec=config.get("models", "update_timeout_sec"),
        retry_count=config.get("models", "update_retry_count", default=1),
    )
    if not response:
        log("update_map: no response from model")
        return

    updated = find_json_in_response(response)
    if not updated:
        log(f"update_map: unparseable response (first 200 chars): {response[:200]}")
        return

    if not validate_map_schema(updated):
        snippet = json.dumps(updated, ensure_ascii=False)[:300]
        log(f"update_map: schema violation, discarding: {snippet}")
        return

    soft_limit = config.get("size", "soft_planet_limit", default=50)
    pruned = prune_low_mass_planets(updated, soft_limit)
    n_pruned = sum(len(s.get("planets", [])) for s in updated.get("suns", [])) - sum(
        len(s.get("planets", [])) for s in pruned.get("suns", [])
    )

    try:
        save_map(cms_dir, pruned)
        n_suns = len(pruned.get("suns", []))
        n_planets = sum(len(s.get("planets", [])) for s in pruned.get("suns", []))
        log_parts = [f"suns={n_suns}", f"planets={n_planets}"]
        if n_pruned:
            log_parts.append(f"pruned={n_pruned}")
        log(f"update_map: saved {' '.join(log_parts)} cwd={cwd}")
    except Exception as e:
        log(f"update_map: save failed: {e}")


if __name__ == "__main__":
    main()
