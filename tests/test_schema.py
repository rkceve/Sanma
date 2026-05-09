"""Tests for validate_map_schema and map_to_text."""

from __future__ import annotations

import _lib


def test_canonical_empty_passes():
    assert _lib.validate_map_schema({"version": 1, "suns": []}) is True


def test_canonical_full_passes(sample_map):
    assert _lib.validate_map_schema(sample_map) is True


def test_none_rejected():
    assert _lib.validate_map_schema(None) is False


def test_non_dict_rejected():
    assert _lib.validate_map_schema([1, 2, 3]) is False


def test_missing_suns_rejected():
    assert _lib.validate_map_schema({"version": 1}) is False


def test_suns_not_list_rejected():
    assert _lib.validate_map_schema({"version": 1, "suns": "x"}) is False


def test_planet_missing_title_rejected():
    bad = {"version": 1, "suns": [{"id": "s", "title": "t",
            "planets": [{"id": "p", "mass": 1}]}]}
    assert _lib.validate_map_schema(bad) is False


def test_planet_mass_not_int_rejected():
    bad = {"version": 1, "suns": [{"id": "s", "title": "t",
            "planets": [{"id": "p", "title": "p", "mass": "1", "satellites": []}]}]}
    assert _lib.validate_map_schema(bad) is False


def test_satellite_missing_text_rejected():
    bad = {"version": 1, "suns": [{"id": "s", "title": "t",
            "planets": [{"id": "p", "title": "p", "mass": 1,
                         "satellites": [{"id": "x"}]}]}]}
    assert _lib.validate_map_schema(bad) is False


def test_extra_keys_at_planet_level_allowed():
    """Extra unknown keys are tolerated (validator is shape-positive)."""
    ok = {"version": 1, "suns": [{"id": "s", "title": "t",
           "planets": [{"id": "p", "title": "p", "mass": 1,
                        "satellites": [], "extra_field": "x"}]}]}
    assert _lib.validate_map_schema(ok) is True


def test_sonnet_bad_output_rejected():
    """The exact failure mode we observed: label/branches instead of title/planets."""
    bad = {"version": 1, "suns": [{"id": "s", "label": "t", "branches": []}]}
    assert _lib.validate_map_schema(bad) is False


def test_map_to_text_empty():
    assert _lib.map_to_text({"version": 1, "suns": []}) == "(empty)"


def test_map_to_text_japanese_and_code():
    m = {"version": 1, "suns": [
        {"id": "s-1", "title": "幾何学的構造データ",
         "planets": [{"id": "p-1", "title": "輪郭ベクトル化", "mass": 3,
                      "satellites": [
                          {"id": "sat-1", "text": "Canny → 制御点として把握"},
                          {"id": "sat-2", "text": "`from scipy.interpolate import BSpline`"},
                      ]}]}
    ]}
    text = _lib.map_to_text(m)
    assert "幾何学的構造データ" in text
    assert "Canny" in text
    assert "BSpline" in text
    assert "(mass=3)" in text


def test_map_to_text_handles_missing_fields():
    m = {"version": 1, "suns": [{"planets": [{"satellites": []}]}]}
    out = _lib.map_to_text(m)
    assert "?" in out  # graceful fallback for missing title
