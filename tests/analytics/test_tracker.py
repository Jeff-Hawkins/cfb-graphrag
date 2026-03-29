"""Tests for analytics.tracker — F3 event logging."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from analytics.tracker import log_event, _log_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_events(path: Path) -> list[dict]:
    """Read all JSON-lines events from *path*."""
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


# ---------------------------------------------------------------------------
# _log_path
# ---------------------------------------------------------------------------


def test_log_path_default():
    """_log_path() returns the default path when env var is unset."""
    os.environ.pop("CFB_EVENT_LOG", None)
    path = _log_path()
    assert path.name == "query_events.jsonl"
    assert "logs" in path.parts


def test_log_path_env_override(tmp_path, monkeypatch):
    """CFB_EVENT_LOG env var overrides the default path."""
    custom = tmp_path / "custom.jsonl"
    monkeypatch.setenv("CFB_EVENT_LOG", str(custom))
    assert _log_path() == custom


# ---------------------------------------------------------------------------
# log_event — happy path
# ---------------------------------------------------------------------------


def test_log_event_writes_jsonl(tmp_path, monkeypatch):
    """log_event appends a valid JSON line to the log file."""
    log_file = tmp_path / "events.jsonl"
    monkeypatch.setenv("CFB_EVENT_LOG", str(log_file))

    log_event(
        query_text="Show Saban tree",
        query_type="freeform",
        result_count=42,
        failure=False,
        duration_ms=150,
        session_id="test-session",
    )

    events = _read_events(log_file)
    assert len(events) == 1
    e = events[0]
    assert e["query_text"] == "Show Saban tree"
    assert e["query_type"] == "freeform"
    assert e["result_count"] == 42
    assert e["failure"] is False
    assert e["duration_ms"] == 150
    assert e["session_id"] == "test-session"
    assert "timestamp" in e


def test_log_event_appends_multiple(tmp_path, monkeypatch):
    """Multiple log_event calls append separate lines."""
    log_file = tmp_path / "events.jsonl"
    monkeypatch.setenv("CFB_EVENT_LOG", str(log_file))

    log_event(query_text="q1", query_type="freeform")
    log_event(query_text="q2", query_type="preset", preset_id="coaching_tree")

    events = _read_events(log_file)
    assert len(events) == 2
    assert events[0]["query_text"] == "q1"
    assert events[1]["preset_id"] == "coaching_tree"


def test_log_event_preset_fields(tmp_path, monkeypatch):
    """Preset events include preset_id and segment."""
    log_file = tmp_path / "events.jsonl"
    monkeypatch.setenv("CFB_EVENT_LOG", str(log_file))

    log_event(
        query_text="SEC Defensive Coordinators",
        query_type="preset",
        preset_id="sec_defensive_coordinators",
        segment="Media",
        result_count=12,
        failure=False,
        duration_ms=88,
        session_id="s1",
    )

    events = _read_events(log_file)
    e = events[0]
    assert e["preset_id"] == "sec_defensive_coordinators"
    assert e["segment"] == "Media"


def test_log_event_creates_parent_dir(tmp_path, monkeypatch):
    """log_event creates missing parent directories."""
    log_file = tmp_path / "deep" / "nested" / "events.jsonl"
    monkeypatch.setenv("CFB_EVENT_LOG", str(log_file))

    log_event(query_text="x", query_type="freeform")

    assert log_file.exists()


def test_log_event_optional_fields_none(tmp_path, monkeypatch):
    """Optional fields default to None and are still present in output."""
    log_file = tmp_path / "events.jsonl"
    monkeypatch.setenv("CFB_EVENT_LOG", str(log_file))

    log_event(query_text="minimal", query_type="freeform")

    events = _read_events(log_file)
    e = events[0]
    assert e["preset_id"] is None
    assert e["segment"] is None
    assert e["session_id"] is None
    assert e["exported"] is False


def test_log_event_failure_flag(tmp_path, monkeypatch):
    """failure=True is recorded correctly."""
    log_file = tmp_path / "events.jsonl"
    monkeypatch.setenv("CFB_EVENT_LOG", str(log_file))

    log_event(query_text="bad query", query_type="freeform", failure=True)

    events = _read_events(log_file)
    assert events[0]["failure"] is True


def test_log_event_os_error_does_not_raise(monkeypatch):
    """log_event swallows OSError and does not propagate."""
    monkeypatch.setenv("CFB_EVENT_LOG", "/dev/null/impossible/path/events.jsonl")
    # Should not raise even though the path is invalid.
    log_event(query_text="x", query_type="freeform")
