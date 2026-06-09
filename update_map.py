"""Stop hook: update the correlation map with diff operations (v0.2).

The model no longer outputs the whole map. It reads the current map plus
the latest exchange and emits a small list of operations:

    {"ops": [{"op": "add_sat", "planet": "planet-2", "text": "..."},
             {"op": "replace_sat", "sat": "sat-7", "text": "..."},
             {"op": "delete_sat", "sat": "sat-7"}, ...]}

The map itself is assembled by code (_lib.apply_ops), which generates
fresh ids and rejects anything violating the invariants — forbidden
keys, overlong texts, and unknown references cannot reach the file. If
the response is unparseable or every op is rejected, we retry once with
the validation errors appended, then leave the map untouched.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402
from _lib import (  # noqa: E402
    apply_ops,
    call_model,
    chat_map_dir,
    ensure_ids,
    load_map,
    load_prompt,
    log,
    prune_low_mass_planets,
    read_hook_payload,
    read_last_exchange,
    save_map,
    should_skip,
    validate_map_schema,
)

# Fallback system prompt used only when prompts/update.md is missing.
# The shipped default lives in prompts/update.md — edit that to tune
# the model's behavior without changing code.
FALLBACK_SYSTEM_PROMPT = """\
You maintain a tree-structured memory of one conversation by emitting
JSON diff operations. You never output the map itself.

A FACT is something that would still be true if the conversation ended
right now: a decision made, a constraint stated, a number measured, a
path that exists, a failure that happened. Proposals, option menus,
questions, and analysis opinions are NOT facts until the user adopts
them.

Output exactly one JSON object: {"ops": [...]} — no prose, no fences.
Allowed operations:
  {"op": "add_sat", "planet": "<planet-id>", "text": "<fact, <=200 chars>"}
  {"op": "replace_sat", "sat": "<sat-id>", "text": "<corrected fact>"}
  {"op": "delete_sat", "sat": "<sat-id>"}
  {"op": "add_planet", "sun": "<sun-id>", "title": "<subtopic>"}
  {"op": "add_sun", "title": "<new domain>", "planet_title": "<first subtopic>"}
  {"op": "inc_mass", "planet": "<planet-id>"}
If the exchange changes nothing, output {"ops": []}.

Rules:
1. If the new exchange contradicts or supersedes an existing satellite,
   replace_sat it (or delete_sat if simply cancelled). Do not keep both.
2. When the user pivots direction, supersede the old-direction satellites.
3. Store only FACTS as defined above. Never store the assistant's
   suggestions or questions.
4. Each text must be one atomic fact, 200 characters or fewer.
5. Reference only ids that appear in CURRENT MAP.
"""

USER_PROMPT_TEMPLATE = """\
CURRENT MAP:
{map_json}

NEW EXCHANGE:
USER: {user_text}

ASSISTANT: {assistant_text}

Output the JSON ops object now. The ONLY valid values for "op" are:
add_sat, replace_sat, delete_sat, add_planet, add_sun, inc_mass.
Do not invent other op names (no "update", "add_satellite", "edit_satellite").
Reference satellites as "sat": "<sat-id>" and planets as "planet": "<planet-id>".

Store only FACTS: things that would still be true if the conversation
ended right now (decisions made, constraints stated, numbers measured,
failures hit). The assistant's proposals, option lists, recommendations,
and questions are NOT facts — when the exchange is only discussion,
output {{"ops": []}}.
"""

RETRY_SUFFIX_TEMPLATE = """

YOUR PREVIOUS ATTEMPT FAILED validation:
{errors}
Re-emit a corrected {{"ops": [...]}} object. Reference only existing ids.
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


def extract_ops(response: str) -> tuple[list | None, str]:
    """Return (ops, error). ops is None when the response is unusable."""
    parsed = find_json_in_response(response)
    if parsed is None:
        return None, "response was not parseable JSON"
    ops = parsed.get("ops")
    if not isinstance(ops, list):
        return None, 'response JSON has no "ops" array'
    return ops, ""


def map_json_with_ids(map_data: dict) -> str:
    """Compact JSON of the map for the prompt — ids included, indent kept small."""
    return json.dumps(map_data, ensure_ascii=False, indent=1)


def main() -> None:
    payload = read_hook_payload()
    cwd = payload.get("cwd") or ""
    transcript_path = payload.get("transcript_path") or ""
    session_id = payload.get("session_id") or ""
    if not cwd or not transcript_path or not session_id:
        return

    if should_skip(cwd):
        return

    user_text, assistant_text = read_last_exchange(transcript_path)
    if not user_text and not assistant_text:
        return

    max_chars = config.get("limits", "max_msg_chars", default=4000)
    user_text = user_text[:max_chars]
    assistant_text = assistant_text[:max_chars]

    cms_dir = chat_map_dir(cwd, session_id)
    map_data = ensure_ids(load_map(cms_dir))

    base_prompt = USER_PROMPT_TEMPLATE.format(
        map_json=map_json_with_ids(map_data),
        user_text=user_text,
        assistant_text=assistant_text,
    )
    system_prompt = load_prompt("update", fallback=FALLBACK_SYSTEM_PROMPT)
    model = config.get("models", "update_model")
    timeout_sec = config.get("models", "update_timeout_sec")

    new_map = None
    applied: list = []
    prompt = base_prompt
    for attempt in range(2):
        response = call_model(
            prompt,
            system_prompt=system_prompt,
            model=model,
            timeout_sec=timeout_sec,
            retry_count=0,
        )
        if not response:
            log(f"update_map: no response from model (attempt {attempt + 1})")
            continue

        ops, err = extract_ops(response)
        if ops is None:
            log(f"update_map: {err} (attempt {attempt + 1}): {response[:200]}")
            prompt = base_prompt + RETRY_SUFFIX_TEMPLATE.format(errors=err)
            continue

        if not ops:
            log(f"update_map: no-op turn sid={session_id[:8]}")
            return

        candidate, applied, rejected = apply_ops(map_data, ops)
        if rejected:
            reasons = "; ".join(f"{json.dumps(op, ensure_ascii=False)[:120]}: {why}"
                                for op, why in rejected[:5])
            log(f"update_map: rejected {len(rejected)} ops: {reasons}")
        if applied:
            new_map = candidate
            break
        prompt = base_prompt + RETRY_SUFFIX_TEMPLATE.format(
            errors="; ".join(why for _, why in rejected[:5]) or "no valid ops"
        )

    if new_map is None:
        log(f"update_map: giving up, map untouched sid={session_id[:8]}")
        return

    if not validate_map_schema(new_map):
        log("update_map: post-apply schema violation, discarding (bug?)")
        return

    soft_limit = config.get("size", "soft_planet_limit", default=50)
    pruned = prune_low_mass_planets(new_map, soft_limit)

    try:
        save_map(cms_dir, pruned)
        n_suns = len(pruned.get("suns", []))
        n_planets = sum(len(s.get("planets", [])) for s in pruned.get("suns", []))
        n_sats = sum(
            len(p.get("satellites", []))
            for s in pruned.get("suns", [])
            for p in s.get("planets", [])
        )
        log(
            f"update_map: applied={len(applied)} suns={n_suns} planets={n_planets} "
            f"sats={n_sats} cwd={cwd} sid={session_id[:8]}"
        )
    except Exception as e:
        log(f"update_map: save failed: {e}")


if __name__ == "__main__":
    main()
