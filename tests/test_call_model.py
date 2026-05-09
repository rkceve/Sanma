"""Tests for call_model: provider routing, retry on transient failure."""

from __future__ import annotations

from typing import Any

import _lib
import config


def test_call_model_uses_cli_by_default(monkeypatch):
    monkeypatch.setattr(config, "load", lambda *a, **kw: config.DEFAULTS)
    seen: dict[str, Any] = {}

    def fake_cli(prompt, system_prompt, model, timeout):
        seen["called"] = "cli"
        return "from-cli"

    def fake_sdk(prompt, system_prompt, model, timeout):
        seen["called"] = "sdk"
        return "from-sdk"

    monkeypatch.setattr(_lib, "_call_via_cli", fake_cli)
    monkeypatch.setattr(_lib, "_call_via_sdk", fake_sdk)

    result = _lib.call_model("p", "s", model="x", timeout_sec=10, retry_count=0)
    assert result == "from-cli"
    assert seen["called"] == "cli"


def test_call_model_routes_to_sdk_when_configured(monkeypatch):
    cfg = {**config.DEFAULTS, "provider": {**config.DEFAULTS["provider"],
                                              "mode": "anthropic_sdk"}}
    monkeypatch.setattr(config, "load", lambda *a, **kw: cfg)

    def fake_sdk(prompt, system_prompt, model, timeout):
        return "from-sdk"

    monkeypatch.setattr(_lib, "_call_via_sdk", fake_sdk)
    monkeypatch.setattr(_lib, "_call_via_cli",
                        lambda *a, **kw: pytest_fail_unexpected())

    result = _lib.call_model("p", "s", model="x", timeout_sec=10, retry_count=0)
    assert result == "from-sdk"


def pytest_fail_unexpected():
    raise AssertionError("unexpected backend used")


def test_call_model_retries_once_on_failure(monkeypatch):
    monkeypatch.setattr(config, "load", lambda *a, **kw: config.DEFAULTS)

    attempts = {"n": 0}

    def fake_cli(prompt, system_prompt, model, timeout):
        attempts["n"] += 1
        if attempts["n"] == 1:
            return None  # first attempt fails
        return "ok-on-retry"

    monkeypatch.setattr(_lib, "_call_via_cli", fake_cli)

    result = _lib.call_model("p", "s", model="x", timeout_sec=10, retry_count=1)
    assert result == "ok-on-retry"
    assert attempts["n"] == 2


def test_call_model_returns_none_when_all_retries_fail(monkeypatch):
    monkeypatch.setattr(config, "load", lambda *a, **kw: config.DEFAULTS)
    monkeypatch.setattr(_lib, "_call_via_cli", lambda *a, **kw: None)

    result = _lib.call_model("p", "s", model="x", timeout_sec=10, retry_count=2)
    assert result is None


def test_call_model_no_retry_when_count_zero(monkeypatch):
    monkeypatch.setattr(config, "load", lambda *a, **kw: config.DEFAULTS)
    attempts = {"n": 0}

    def fake_cli(*a, **kw):
        attempts["n"] += 1
        return None

    monkeypatch.setattr(_lib, "_call_via_cli", fake_cli)
    _lib.call_model("p", "s", model="x", timeout_sec=10, retry_count=0)
    assert attempts["n"] == 1


def test_call_model_succeeds_immediately_no_retry(monkeypatch):
    monkeypatch.setattr(config, "load", lambda *a, **kw: config.DEFAULTS)
    attempts = {"n": 0}

    def fake_cli(*a, **kw):
        attempts["n"] += 1
        return "ok"

    monkeypatch.setattr(_lib, "_call_via_cli", fake_cli)
    result = _lib.call_model("p", "s", model="x", timeout_sec=10, retry_count=3)
    assert result == "ok"
    assert attempts["n"] == 1  # no unnecessary retries


def test_call_model_uses_config_defaults_when_args_omitted(monkeypatch):
    monkeypatch.setattr(config, "load", lambda *a, **kw: config.DEFAULTS)
    seen: dict[str, Any] = {}

    def fake_cli(prompt, system_prompt, model, timeout):
        seen["model"] = model
        seen["timeout"] = timeout
        return "ok"

    monkeypatch.setattr(_lib, "_call_via_cli", fake_cli)
    _lib.call_model("p", "s")
    assert seen["model"] == config.DEFAULTS["models"]["inject_model"]
    assert seen["timeout"] == config.DEFAULTS["models"]["inject_timeout_sec"]


def test_sdk_path_returns_none_without_api_key(monkeypatch, clean_env):
    """When ANTHROPIC_API_KEY is unset, the SDK path bails out cleanly."""
    monkeypatch.setattr(config, "load", lambda *a, **kw: config.DEFAULTS)
    # Simulate the anthropic package being importable but unused (api key missing)

    class _FakeAnthropicModule:
        class Anthropic:
            def __init__(self, **kw):
                raise AssertionError("should not be reached without API key")

    import sys

    monkeypatch.setitem(sys.modules, "anthropic", _FakeAnthropicModule())
    result = _lib._call_via_sdk("p", "s", "model-x", 10)
    assert result is None
