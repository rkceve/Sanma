"""On-demand fact lookup over a correlation map (v0.2 pull architecture).

Invoked by the MAIN model mid-turn (the injected index embeds the exact
command line), not by a hook:

    python search_map.py --map <path/to/correlation_map.json> "<query>"

Flow: render the map with a number on every satellite, ask the selector
model (inject_model, Haiku) which numbers answer the query, then print
the chosen satellite texts VERBATIM. The model only ever emits numbers —
it cannot rephrase, editorialize, or invent facts. If the model call
fails or returns garbage, fall back to a deterministic token match so
the command always succeeds (exit 0).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402
from _lib import (  # noqa: E402
    call_model,
    load_map,
    load_prompt,
    log,
    map_to_indexed_text,
)

NO_RESULTS_MSG = "(no stored facts matched this query)"

FALLBACK_SYSTEM_PROMPT = """\
You select entries from a numbered list of stored facts.

Input: an INDEXED MAP (tree of topics; every fact line starts with [N])
and a QUERY from an assistant that needs specific past facts.

Output ONLY a JSON array of the numbers whose facts answer the query,
most relevant first, at most {n_max} numbers. Example: [3, 17]
If nothing is relevant, output exactly: []

Rules:
- Select facts that answer the query, not facts that merely share words with it.
- If two facts on the same topic contradict each other, prefer the one
  with the HIGHER number (entries are appended in time order; later = newer).
- No prose, no keys, no quotes around numbers.
"""


def parse_selection(response: str, n_max: int, n_items: int) -> list[int]:
    """Extract the first JSON int array; drop out-of-range ids and dupes."""
    if not response:
        return []
    m = re.search(r"\[[^\[\]]*\]", response)
    if not m:
        return []
    try:
        raw = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []
    picks: list[int] = []
    for item in raw:
        if isinstance(item, bool) or not isinstance(item, int):
            continue
        if not 1 <= item <= n_items:
            continue
        if item in picks:
            continue
        picks.append(item)
        if len(picks) >= n_max:
            break
    return picks


def render_results(flat: list[dict], picks: list[int]) -> str:
    """Render picked satellites verbatim — the model never touches the text."""
    lines = [f"- [{flat[i - 1]['planet_title']}] {flat[i - 1]['text']}" for i in picks]
    return "\n".join(lines)


def _query_tokens(query: str) -> list[str]:
    """Tokens for the deterministic fallback: words plus CJK bigrams."""
    tokens = [t.lower() for t in re.findall(r"[^\W_]+", query) if len(t) >= 2]
    out: list[str] = []
    for t in tokens:
        if re.search(r"[぀-ヿ一-鿿]", t):
            out.extend(t[i : i + 2] for i in range(len(t) - 1))
        else:
            out.append(t)
    return list(dict.fromkeys(out))


def fallback_search(flat: list[dict], query: str, n_max: int) -> list[int]:
    """Deterministic token-overlap search used when the model is unavailable."""
    tokens = _query_tokens(query)
    if not tokens:
        return []
    scored: list[tuple[int, int]] = []
    for i, sat in enumerate(flat, start=1):
        haystack = f"{sat['planet_title']} {sat['text']}".lower()
        score = sum(1 for t in tokens if t in haystack)
        if score > 0:
            scored.append((score, i))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [i for _, i in scored[:n_max]]


def run_search(map_data: dict, query: str) -> str:
    text, flat = map_to_indexed_text(map_data)
    if not flat:
        return NO_RESULTS_MSG

    n_max = config.get("limits", "max_search_results", default=8)
    system_prompt = load_prompt(
        "search", fallback=FALLBACK_SYSTEM_PROMPT
    ).format(n_max=n_max)
    user_prompt = f"INDEXED MAP:\n{text}\n\nQUERY:\n{query}\n\nOutput the JSON array."

    response = call_model(
        user_prompt,
        system_prompt=system_prompt,
        model=config.get("models", "inject_model"),
        timeout_sec=config.get("models", "inject_timeout_sec"),
        retry_count=0,
    )

    picks = parse_selection(response or "", n_max=n_max, n_items=len(flat))
    used_fallback = False
    if response is None:
        picks = fallback_search(flat, query, n_max=n_max)
        used_fallback = True

    log(
        f"search_map: picks={picks} fallback={used_fallback} "
        f"sats={len(flat)} query={query[:60]!r}"
    )
    return render_results(flat, picks) if picks else NO_RESULTS_MSG


def main() -> int:
    parser = argparse.ArgumentParser(description="Search a CMS correlation map.")
    parser.add_argument("--map", required=True, help="Path to correlation_map.json")
    parser.add_argument("query", help="What you need to know")
    args = parser.parse_args()

    map_path = Path(args.map)
    map_data = load_map(map_path.parent)
    out = run_search(map_data, args.query)
    sys.stdout.buffer.write((out + "\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
