"""Tests for prune_low_mass_planets (map size management)."""

from __future__ import annotations

import _lib


def _build_map(planet_specs: list[tuple[str, int]]) -> dict:
    """Build a map under one sun with the given (title, mass) planets."""
    planets = [
        {"id": f"planet-{i}", "title": title, "mass": mass, "satellites": []}
        for i, (title, mass) in enumerate(planet_specs, 1)
    ]
    return {"version": 1, "suns": [{"id": "sun-1", "title": "S",
                                     "planets": planets}]}


def test_prune_below_limit_unchanged():
    m = _build_map([("a", 5), ("b", 3)])
    assert _lib.prune_low_mass_planets(m, soft_limit=10) == m


def test_prune_at_limit_unchanged():
    m = _build_map([("a", 5), ("b", 3)])
    assert _lib.prune_low_mass_planets(m, soft_limit=2) == m


def test_prune_drops_lowest_mass():
    m = _build_map([("keep-high", 5), ("drop-low", 1), ("keep-mid", 3)])
    result = _lib.prune_low_mass_planets(m, soft_limit=2)
    titles = [p["title"] for s in result["suns"] for p in s["planets"]]
    assert "drop-low" not in titles
    assert "keep-high" in titles
    assert "keep-mid" in titles


def test_prune_preserves_sun_even_if_all_planets_dropped():
    m = _build_map([("a", 1), ("b", 1)])
    result = _lib.prune_low_mass_planets(m, soft_limit=0)
    assert len(result["suns"]) == 1
    assert result["suns"][0]["planets"] == []


def test_prune_across_multiple_suns():
    m = {"version": 1, "suns": [
        {"id": "sun-1", "title": "S1", "planets": [
            {"id": "p1", "title": "low", "mass": 1, "satellites": []},
            {"id": "p2", "title": "high", "mass": 5, "satellites": []},
        ]},
        {"id": "sun-2", "title": "S2", "planets": [
            {"id": "p3", "title": "mid", "mass": 3, "satellites": []},
        ]},
    ]}
    result = _lib.prune_low_mass_planets(m, soft_limit=2)
    titles = sorted(p["title"] for s in result["suns"] for p in s["planets"])
    assert titles == ["high", "mid"]


def test_prune_handles_non_int_mass_gracefully():
    """A malformed planet with non-int mass shouldn't crash the prune step."""
    m = _build_map([("bad", 0), ("ok", 3)])
    m["suns"][0]["planets"][0]["mass"] = "not-an-int"  # type: ignore[assignment]
    # Expectation: doesn't raise; the bad mass is treated as 0 → dropped first
    result = _lib.prune_low_mass_planets(m, soft_limit=1)
    assert all(isinstance(p, dict) for s in result["suns"] for p in s["planets"])


def test_prune_preserves_satellites_of_kept_planets():
    m = {"version": 1, "suns": [{"id": "sun-1", "title": "S", "planets": [
        {"id": "p1", "title": "drop", "mass": 1, "satellites": [
            {"id": "sat-x", "text": "lost"}
        ]},
        {"id": "p2", "title": "keep", "mass": 5, "satellites": [
            {"id": "sat-y", "text": "kept"}
        ]},
    ]}]}
    result = _lib.prune_low_mass_planets(m, soft_limit=1)
    surviving_sats = [
        sat["text"] for s in result["suns"] for p in s["planets"] for sat in p["satellites"]
    ]
    assert surviving_sats == ["kept"]


def test_prune_noop_when_no_suns():
    m = {"version": 1, "suns": []}
    assert _lib.prune_low_mass_planets(m, soft_limit=10) == m
