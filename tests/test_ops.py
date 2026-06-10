"""Tests for ensure_ids() and apply_ops() — the v0.2 diff-operation layer."""

from __future__ import annotations

import _lib

# ---------------------------------------------------------------------------
# ensure_ids
# ---------------------------------------------------------------------------


def test_ensure_ids_fills_missing_ids():
    data = {
        "version": 1,
        "suns": [
            {
                "title": "A",
                "planets": [
                    {
                        "title": "P",
                        "mass": 1,
                        "satellites": [{"text": "fact one"}, {"text": "fact two"}],
                    }
                ],
            }
        ],
    }
    out = _lib.ensure_ids(data)
    assert out["suns"][0]["id"] == "sun-1"
    assert out["suns"][0]["planets"][0]["id"] == "planet-1"
    sats = out["suns"][0]["planets"][0]["satellites"]
    assert sats[0]["id"] == "sat-1"
    assert sats[1]["id"] == "sat-2"


def test_ensure_ids_preserves_existing_and_avoids_collisions(sample_map):
    out = _lib.ensure_ids(sample_map)
    # Existing ids untouched
    assert out["suns"][0]["id"] == "sun-1"
    assert out["suns"][0]["planets"][0]["satellites"][0]["id"] == "sat-1"
    # New node without id gets the next free integer, not a duplicate
    out["suns"][0]["planets"][0]["satellites"].append({"text": "new fact"})
    out2 = _lib.ensure_ids(out)
    new_id = out2["suns"][0]["planets"][0]["satellites"][2]["id"]
    assert new_id == "sat-4"  # sat-1..3 already exist in sample_map


# ---------------------------------------------------------------------------
# apply_ops
# ---------------------------------------------------------------------------


def test_apply_add_sat(sample_map):
    ops = [{"op": "add_sat", "planet": "planet-2", "text": "Use frame pacing"}]
    new_map, applied, rejected = _lib.apply_ops(sample_map, ops)
    assert len(applied) == 1 and not rejected
    sats = new_map["suns"][0]["planets"][1]["satellites"]
    assert sats[-1]["text"] == "Use frame pacing"
    assert sats[-1]["id"] == "sat-4"  # code-generated, next free integer


def test_apply_replace_sat(sample_map):
    ops = [{"op": "replace_sat", "sat": "sat-3", "text": "End-to-end <15ms"}]
    new_map, applied, rejected = _lib.apply_ops(sample_map, ops)
    assert len(applied) == 1 and not rejected
    assert new_map["suns"][0]["planets"][1]["satellites"][0]["text"] == "End-to-end <15ms"


def test_apply_delete_sat(sample_map):
    ops = [{"op": "delete_sat", "sat": "sat-2"}]
    new_map, applied, rejected = _lib.apply_ops(sample_map, ops)
    assert len(applied) == 1 and not rejected
    texts = [s["text"] for s in new_map["suns"][0]["planets"][0]["satellites"]]
    assert texts == ["Replace OpenGL with WebGL2"]


def test_apply_add_planet_and_inc_mass(sample_map):
    ops = [
        {"op": "add_planet", "sun": "sun-1", "title": "Input handling"},
        {"op": "inc_mass", "planet": "planet-1"},
    ]
    new_map, applied, rejected = _lib.apply_ops(sample_map, ops)
    assert len(applied) == 2 and not rejected
    planets = new_map["suns"][0]["planets"]
    assert planets[-1]["title"] == "Input handling"
    assert planets[-1]["mass"] == 1
    assert planets[-1]["id"] == "planet-3"
    assert planets[0]["mass"] == 5  # was 4


def test_apply_add_sun(sample_map):
    ops = [{"op": "add_sun", "title": "Compression", "planet_title": "Run 6"}]
    new_map, applied, rejected = _lib.apply_ops(sample_map, ops)
    assert len(applied) == 1 and not rejected
    sun = new_map["suns"][-1]
    assert sun["title"] == "Compression" and sun["id"] == "sun-2"
    assert sun["planets"][0]["title"] == "Run 6"
    assert sun["planets"][0]["mass"] == 1


def test_reject_unknown_op_and_missing_ref(sample_map):
    ops = [
        {"op": "rename_sat", "sat": "sat-1", "text": "x"},
        {"op": "delete_sat", "sat": "sat-99"},
        {"op": "add_sat", "planet": "planet-99", "text": "orphan"},
    ]
    new_map, applied, rejected = _lib.apply_ops(sample_map, ops)
    assert not applied
    assert len(rejected) == 3
    # Map unchanged
    assert new_map == _lib.ensure_ids(sample_map)


def test_reject_overlong_text(sample_map):
    ops = [{"op": "add_sat", "planet": "planet-1", "text": "x" * 201}]
    _, applied, rejected = _lib.apply_ops(sample_map, ops)
    assert not applied and len(rejected) == 1


def test_reject_ops_beyond_limit(sample_map):
    ops = [
        {"op": "add_sat", "planet": "planet-1", "text": f"fact {i}"} for i in range(12)
    ]
    _, applied, rejected = _lib.apply_ops(sample_map, ops)
    assert len(applied) == 10
    assert len(rejected) == 2


def test_apply_ops_does_not_mutate_input(sample_map):
    import copy

    original = copy.deepcopy(sample_map)
    ops = [{"op": "delete_sat", "sat": "sat-1"}]
    _lib.apply_ops(sample_map, ops)
    assert sample_map == original


def test_add_planet_with_inline_sats(sample_map):
    """Batch-reference fix: a new planet's initial facts ride along in `sats`,
    because the model cannot know the id of a node created in the same batch."""
    ops = [
        {
            "op": "add_planet",
            "sun": "sun-1",
            "title": "Input handling",
            "sats": ["Polling rate fixed at 500Hz", "Use raw HID, not driver events"],
        }
    ]
    new_map, applied, rejected = _lib.apply_ops(sample_map, ops)
    assert len(applied) == 1 and not rejected
    planet = new_map["suns"][0]["planets"][-1]
    assert planet["title"] == "Input handling"
    texts = [s["text"] for s in planet["satellites"]]
    assert texts == ["Polling rate fixed at 500Hz", "Use raw HID, not driver events"]
    ids = [s["id"] for s in planet["satellites"]]
    assert ids == ["sat-4", "sat-5"]  # code-assigned, collision-free


def test_add_sun_with_inline_sats(sample_map):
    ops = [
        {
            "op": "add_sun",
            "title": "Compression",
            "planet_title": "Run 6",
            "sats": ["Run 6 uses 500K params"],
        }
    ]
    new_map, applied, rejected = _lib.apply_ops(sample_map, ops)
    assert len(applied) == 1 and not rejected
    sun = new_map["suns"][-1]
    assert sun["planets"][0]["satellites"][0]["text"] == "Run 6 uses 500K params"


def test_inline_sats_validated_individually(sample_map):
    """A bad inline text is rejected alone; the planet and valid texts survive."""
    ops = [
        {
            "op": "add_planet",
            "sun": "sun-1",
            "title": "Input handling",
            "sats": ["valid fact", "x" * 201, ""],
        }
    ]
    new_map, applied, rejected = _lib.apply_ops(sample_map, ops)
    assert len(applied) == 1
    assert len(rejected) == 2  # the overlong and the empty text
    planet = new_map["suns"][0]["planets"][-1]
    assert [s["text"] for s in planet["satellites"]] == ["valid fact"]


def test_inline_sats_list_too_long_rejected(sample_map):
    ops = [
        {
            "op": "add_planet",
            "sun": "sun-1",
            "title": "Bulk",
            "sats": [f"fact {i}" for i in range(11)],
        }
    ]
    new_map, applied, rejected = _lib.apply_ops(sample_map, ops)
    assert not applied and len(rejected) == 1
    assert len(new_map["suns"][0]["planets"]) == 2  # nothing added


def test_reject_non_dict_and_empty_text(sample_map):
    ops = [
        "not a dict",
        {"op": "add_sat", "planet": "planet-1", "text": ""},
        {"op": "add_planet", "sun": "sun-1", "title": ""},
    ]
    _, applied, rejected = _lib.apply_ops(sample_map, ops)
    assert not applied and len(rejected) == 3
