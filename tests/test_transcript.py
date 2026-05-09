"""Tests for read_last_exchange and extract_message_text — JSONL parsing."""

from __future__ import annotations

import json
from pathlib import Path

import _lib


def _write_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def test_extract_text_from_string():
    assert _lib.extract_message_text("hello") == "hello"


def test_extract_text_from_content_block_list():
    blocks = [{"type": "text", "text": "first"}, {"type": "text", "text": "second"}]
    assert _lib.extract_message_text(blocks) == "first\nsecond"


def test_extract_text_skips_non_text_blocks():
    blocks = [
        {"type": "text", "text": "keep"},
        {"type": "tool_use", "input": {}},
    ]
    assert _lib.extract_message_text(blocks) == "keep"


def test_extract_text_from_dict_with_text_key():
    assert _lib.extract_message_text({"text": "x"}) == "x"


def test_extract_text_handles_none():
    assert _lib.extract_message_text(None) == ""


def test_read_last_exchange_basic(tmp_path: Path):
    p = tmp_path / "transcript.jsonl"
    _write_jsonl(p, [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": [{"type": "text", "text": "hi"}]},
    ])
    user, asst = _lib.read_last_exchange(str(p))
    assert user == "hello"
    assert asst == "hi"


def test_read_last_exchange_returns_most_recent(tmp_path: Path):
    p = tmp_path / "transcript.jsonl"
    _write_jsonl(p, [
        {"role": "user", "content": "first user"},
        {"role": "assistant", "content": [{"type": "text", "text": "first asst"}]},
        {"role": "user", "content": "second user"},
        {"role": "assistant", "content": [{"type": "text", "text": "second asst"}]},
    ])
    user, asst = _lib.read_last_exchange(str(p))
    assert user == "second user"
    assert asst == "second asst"


def test_read_last_exchange_handles_message_wrapper(tmp_path: Path):
    """Some Claude Code transcript variants nest under 'message'."""
    p = tmp_path / "transcript.jsonl"
    _write_jsonl(p, [
        {"type": "user", "message": {"role": "user", "content": "wrapped user"}},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "wrapped asst"}]}},
    ])
    user, asst = _lib.read_last_exchange(str(p))
    assert user == "wrapped user"
    assert asst == "wrapped asst"


def test_read_last_exchange_skips_malformed_lines(tmp_path: Path):
    p = tmp_path / "transcript.jsonl"
    p.write_text(
        "not json\n"
        + json.dumps({"role": "user", "content": "ok"}) + "\n"
        + "{broken\n"
        + json.dumps({"role": "assistant", "content": [{"type": "text", "text": "ok-a"}]}) + "\n",
        encoding="utf-8",
    )
    user, asst = _lib.read_last_exchange(str(p))
    assert user == "ok"
    assert asst == "ok-a"


def test_read_last_exchange_missing_file(tmp_path: Path):
    user, asst = _lib.read_last_exchange(str(tmp_path / "absent.jsonl"))
    assert user == ""
    assert asst == ""


def test_read_last_exchange_empty_path():
    user, asst = _lib.read_last_exchange("")
    assert user == ""
    assert asst == ""


def test_read_last_exchange_empty_transcript(tmp_path: Path):
    p = tmp_path / "empty.jsonl"
    p.write_text("", encoding="utf-8")
    user, asst = _lib.read_last_exchange(str(p))
    assert user == ""
    assert asst == ""


def test_read_last_exchange_only_user_no_assistant(tmp_path: Path):
    p = tmp_path / "transcript.jsonl"
    _write_jsonl(p, [{"role": "user", "content": "lone user"}])
    user, asst = _lib.read_last_exchange(str(p))
    assert user == "lone user"
    assert asst == ""


def test_read_last_exchange_japanese_content(tmp_path: Path):
    p = tmp_path / "transcript.jsonl"
    _write_jsonl(p, [
        {"role": "user", "content": "日本語のメッセージ"},
        {"role": "assistant", "content": [{"type": "text", "text": "返答です"}]},
    ])
    user, asst = _lib.read_last_exchange(str(p))
    assert user == "日本語のメッセージ"
    assert asst == "返答です"
