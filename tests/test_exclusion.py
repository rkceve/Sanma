"""Tests for the skip/exclusion logic: recursion guard, session disable, cwd patterns."""

from __future__ import annotations

import _lib
import config


def test_recursion_guard_off_by_default(clean_env):
    assert _lib.is_recursive_call() is False


def test_recursion_guard_active(monkeypatch):
    monkeypatch.setenv("CMS_HOOK_ACTIVE", "1")
    assert _lib.is_recursive_call() is True


def test_recursion_guard_other_value_treated_as_off(monkeypatch):
    monkeypatch.setenv("CMS_HOOK_ACTIVE", "0")
    assert _lib.is_recursive_call() is False


def test_session_disable_off_by_default(clean_env):
    assert _lib.is_session_disabled() is False


def test_session_disable_active(monkeypatch):
    monkeypatch.setenv("CMS_DISABLE", "1")
    assert _lib.is_session_disabled() is True


def test_is_excluded_empty_patterns(clean_env, monkeypatch):
    monkeypatch.setattr(config, "load", lambda *a, **kw: config.DEFAULTS)
    assert _lib.is_excluded(r"C:\Users\Foo") is False


def test_is_excluded_matches_glob(monkeypatch):
    cfg = {**config.DEFAULTS, "exclusion": {"skip_cwds": ["**/scratch/**"]}}
    monkeypatch.setattr(config, "load", lambda *a, **kw: cfg)
    assert _lib.is_excluded("/home/user/scratch/quick") is True
    assert _lib.is_excluded("/home/user/work/main") is False


def test_is_excluded_normalizes_separators(monkeypatch):
    """Backslash and forward slash should both match the same pattern."""
    cfg = {**config.DEFAULTS, "exclusion": {"skip_cwds": ["**/Temp/**"]}}
    monkeypatch.setattr(config, "load", lambda *a, **kw: cfg)
    assert _lib.is_excluded(r"C:\Temp\foo") is True
    assert _lib.is_excluded("C:/Temp/foo") is True


def test_is_excluded_multiple_patterns_any_match(monkeypatch):
    cfg = {**config.DEFAULTS, "exclusion": {"skip_cwds": ["**/foo/**", "**/bar/**"]}}
    monkeypatch.setattr(config, "load", lambda *a, **kw: cfg)
    assert _lib.is_excluded("/x/foo/y") is True
    assert _lib.is_excluded("/x/bar/y") is True
    assert _lib.is_excluded("/x/baz/y") is False


def test_should_skip_combines_all_signals(monkeypatch, clean_env):
    monkeypatch.setattr(config, "load", lambda *a, **kw: config.DEFAULTS)
    assert _lib.should_skip("/normal") is False

    monkeypatch.setenv("CMS_HOOK_ACTIVE", "1")
    assert _lib.should_skip("/normal") is True
    monkeypatch.delenv("CMS_HOOK_ACTIVE")

    monkeypatch.setenv("CMS_DISABLE", "1")
    assert _lib.should_skip("/normal") is True
    monkeypatch.delenv("CMS_DISABLE")

    cfg = {**config.DEFAULTS, "exclusion": {"skip_cwds": ["**/skip/**"]}}
    monkeypatch.setattr(config, "load", lambda *a, **kw: cfg)
    assert _lib.should_skip("/here/skip/now") is True
    assert _lib.should_skip("/here/work/now") is False
