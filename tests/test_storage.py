"""Tests for cwd_to_slug, load_map, save_map."""

from __future__ import annotations

import json
from pathlib import Path

import _lib


def test_cwd_to_slug_windows_path():
    assert _lib.cwd_to_slug(r"C:\Users\Foo") == "C--Users-Foo"


def test_cwd_to_slug_path_with_spaces():
    assert _lib.cwd_to_slug(r"C:\Users\Ryosuke Kawai") == "C--Users-Ryosuke-Kawai"


def test_cwd_to_slug_unix_path():
    assert _lib.cwd_to_slug("/home/user/project") == "-home-user-project"


def test_cwd_to_slug_unicode_preserved():
    assert _lib.cwd_to_slug(r"C:\Users\日本語") == "C--Users-日本語"


def test_cwd_to_slug_collapses_long_dash_runs():
    """Multiple consecutive separators collapse to at most three dashes."""
    out = _lib.cwd_to_slug(r"C:\\\\foo\\\\bar")
    assert "----" not in out


def test_load_map_returns_empty_when_absent(tmp_cms_dir: Path):
    m = _lib.load_map(tmp_cms_dir)
    assert m == {"version": 1, "suns": []}


def test_load_map_returns_empty_when_corrupt(tmp_cms_dir: Path):
    (tmp_cms_dir / "correlation_map.json").write_text("{not valid json", encoding="utf-8")
    assert _lib.load_map(tmp_cms_dir) == {"version": 1, "suns": []}


def test_load_map_returns_empty_when_wrong_shape(tmp_cms_dir: Path):
    (tmp_cms_dir / "correlation_map.json").write_text(
        json.dumps([1, 2, 3]), encoding="utf-8"
    )
    assert _lib.load_map(tmp_cms_dir) == {"version": 1, "suns": []}


def test_save_load_roundtrip(tmp_cms_dir: Path, sample_map: dict):
    _lib.save_map(tmp_cms_dir, sample_map)
    loaded = _lib.load_map(tmp_cms_dir)
    assert loaded == sample_map


def test_save_map_atomic_no_partial_file(tmp_cms_dir: Path, sample_map: dict):
    """save_map should leave only correlation_map.json (no .tmp residue)."""
    _lib.save_map(tmp_cms_dir, sample_map)
    files = sorted(p.name for p in tmp_cms_dir.iterdir())
    assert files == ["correlation_map.json"]


def test_save_map_overwrites(tmp_cms_dir: Path, sample_map: dict):
    _lib.save_map(tmp_cms_dir, sample_map)
    new_map = {"version": 1, "suns": []}
    _lib.save_map(tmp_cms_dir, new_map)
    assert _lib.load_map(tmp_cms_dir) == new_map


def test_save_map_unicode(tmp_cms_dir: Path):
    m = {"version": 1, "suns": [{"id": "s-1", "title": "日本語タイトル",
            "planets": [{"id": "p-1", "title": "輪郭", "mass": 1,
                         "satellites": [{"id": "sat-1", "text": "Canny → NURBS"}]}]}]}
    _lib.save_map(tmp_cms_dir, m)
    text = (tmp_cms_dir / "correlation_map.json").read_text(encoding="utf-8")
    assert "日本語タイトル" in text  # ensure_ascii=False respected
