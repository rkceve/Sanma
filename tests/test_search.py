"""Tests for search_map.py — query-driven verbatim fact lookup."""

from __future__ import annotations

import _lib
import search_map

# ---------------------------------------------------------------------------
# map_to_indexed_text (_lib)
# ---------------------------------------------------------------------------


def test_indexed_text_numbers_every_satellite(sample_map):
    text, flat = _lib.map_to_indexed_text(sample_map)
    assert "[1]" in text and "[2]" in text and "[3]" in text
    assert len(flat) == 3
    assert flat[0]["text"] == "Replace OpenGL with WebGL2"
    assert flat[2]["text"] == "End-to-end <20ms"
    assert flat[2]["planet_title"] == "Latency budget"


def test_indexed_text_empty_map():
    text, flat = _lib.map_to_indexed_text({"version": 1, "suns": []})
    assert flat == []


# ---------------------------------------------------------------------------
# parse_selection
# ---------------------------------------------------------------------------


def test_parse_selection_plain_array():
    assert search_map.parse_selection("[1, 3]", n_max=8, n_items=3) == [1, 3]


def test_parse_selection_with_surrounding_prose():
    resp = "Here are the relevant entries:\n[2, 3]\nHope this helps."
    assert search_map.parse_selection(resp, n_max=8, n_items=3) == [2, 3]


def test_parse_selection_filters_out_of_range_and_dupes():
    assert search_map.parse_selection("[3, 99, 0, 3, 1]", n_max=8, n_items=3) == [3, 1]


def test_parse_selection_caps_at_n_max():
    resp = "[1, 2, 3, 4, 5, 6]"
    assert search_map.parse_selection(resp, n_max=2, n_items=6) == [1, 2]


def test_parse_selection_garbage_returns_empty():
    assert search_map.parse_selection("no array here", n_max=8, n_items=3) == []
    assert search_map.parse_selection('["a", "b"]', n_max=8, n_items=3) == []
    assert search_map.parse_selection("", n_max=8, n_items=3) == []


# ---------------------------------------------------------------------------
# render_results — verbatim guarantee
# ---------------------------------------------------------------------------


def test_render_results_verbatim(sample_map):
    _, flat = _lib.map_to_indexed_text(sample_map)
    out = search_map.render_results(flat, [3, 1])
    lines = out.splitlines()
    assert lines[0] == "- [Latency budget] End-to-end <20ms"
    assert lines[1] == "- [WebGL renderer] Replace OpenGL with WebGL2"


def test_render_results_empty_picks(sample_map):
    _, flat = _lib.map_to_indexed_text(sample_map)
    assert search_map.render_results(flat, []) == ""


# ---------------------------------------------------------------------------
# fallback_search — deterministic, used when the model call fails
# ---------------------------------------------------------------------------


def test_fallback_search_matches_tokens(sample_map):
    _, flat = _lib.map_to_indexed_text(sample_map)
    picks = search_map.fallback_search(flat, "what is the latency target 20ms", n_max=8)
    assert 3 in picks


def test_fallback_search_japanese_substring(sample_map):
    sample_map["suns"][0]["planets"][0]["satellites"].append(
        {"id": "sat-9", "text": "レンダリングは WebGL2 で行う決定"}
    )
    _, flat = _lib.map_to_indexed_text(sample_map)
    # Appended to planet-1 (2 existing sats) → global index 3; planet-2's
    # satellite shifts to 4.
    picks = search_map.fallback_search(flat, "レンダリングの決定事項は？", n_max=8)
    assert 3 in picks


def test_fallback_search_no_match_returns_empty(sample_map):
    _, flat = _lib.map_to_indexed_text(sample_map)
    assert search_map.fallback_search(flat, "completely unrelated zebra topic", n_max=8) == []


# ---------------------------------------------------------------------------
# run_search — model path with fallback wiring
# ---------------------------------------------------------------------------


def test_run_search_uses_model_selection(sample_map, monkeypatch, reset_log):
    monkeypatch.setattr(search_map, "call_model", lambda *a, **k: "[3]")
    out = search_map.run_search(sample_map, "latency target?")
    assert out == "- [Latency budget] End-to-end <20ms"


def test_run_search_falls_back_when_model_fails(sample_map, monkeypatch, reset_log):
    monkeypatch.setattr(search_map, "call_model", lambda *a, **k: None)
    out = search_map.run_search(sample_map, "latency 20ms")
    assert "End-to-end <20ms" in out


def test_run_search_empty_map_returns_message(monkeypatch, reset_log):
    out = search_map.run_search({"version": 1, "suns": []}, "anything")
    assert out == search_map.NO_RESULTS_MSG
