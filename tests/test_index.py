"""Tests for the v0.2 index-only injection (inject_facts.build_index_text)."""

from __future__ import annotations

from pathlib import Path

import inject_facts


def test_index_contains_titles_but_no_satellite_texts(sample_map):
    text = inject_facts.build_index_text(sample_map, Path("C:/maps/correlation_map.json"))
    assert "VR demo" in text
    assert "WebGL renderer" in text
    assert "Latency budget" in text
    # Satellite bodies must NOT be in the index
    assert "Replace OpenGL with WebGL2" not in text
    assert "End-to-end <20ms" not in text


def test_index_shows_mass_and_fact_counts(sample_map):
    text = inject_facts.build_index_text(sample_map, Path("C:/maps/correlation_map.json"))
    assert "mass=4" in text
    assert "2 facts" in text
    assert "1 fact" in text


def test_index_embeds_search_command_with_map_path(sample_map):
    map_path = Path("C:/Users/Ryo/.claude/projects/x/memory/cms/chats/abc/correlation_map.json")
    text = inject_facts.build_index_text(sample_map, map_path)
    assert "search_map.py" in text
    assert str(map_path) in text


def test_index_empty_map_returns_none():
    assert inject_facts.build_index_text({"version": 1, "suns": []}, Path("x.json")) is None


def test_index_is_compact(sample_map):
    """The whole point of v0.2: per-turn injection must stay tiny."""
    text = inject_facts.build_index_text(sample_map, Path("x.json"))
    assert len(text) < 800
