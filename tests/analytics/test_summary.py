"""Tests for analytics.summary — F3 weekly observability report."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from analytics.summary import build_report, load_events, main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime.now(timezone.utc)


def _event(
    query_text: str = "test query",
    query_type: str = "freeform",
    preset_id: str | None = None,
    segment: str | None = "General",
    result_count: int = 5,
    failure: bool = False,
    duration_ms: int = 100,
    session_id: str = "s1",
    days_ago: float = 0,
) -> dict:
    """Build a minimal event dict."""
    ts = (_NOW - timedelta(days=days_ago)).isoformat()
    return {
        "timestamp": ts,
        "query_text": query_text,
        "query_type": query_type,
        "preset_id": preset_id,
        "segment": segment,
        "result_count": result_count,
        "failure": failure,
        "duration_ms": duration_ms,
        "exported": False,
        "session_id": session_id,
    }


def _write_jsonl(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(e) + "\n")


# ---------------------------------------------------------------------------
# load_events
# ---------------------------------------------------------------------------


def test_load_events_reads_all(tmp_path):
    """load_events returns all valid lines."""
    log = tmp_path / "events.jsonl"
    events = [_event("q1"), _event("q2"), _event("q3")]
    _write_jsonl(log, events)
    loaded = load_events(log)
    assert len(loaded) == 3
    assert loaded[0]["query_text"] == "q1"


def test_load_events_skips_malformed_lines(tmp_path, capsys):
    """Malformed JSON lines are skipped; valid lines are returned."""
    log = tmp_path / "events.jsonl"
    log.write_text(
        json.dumps(_event("good")) + "\n" + "NOT JSON\n" + json.dumps(_event("also good")) + "\n",
        encoding="utf-8",
    )
    loaded = load_events(log)
    assert len(loaded) == 2
    captured = capsys.readouterr()
    assert "malformed" in captured.err


def test_load_events_empty_file(tmp_path):
    """Empty log file returns empty list."""
    log = tmp_path / "events.jsonl"
    log.write_text("", encoding="utf-8")
    assert load_events(log) == []


# ---------------------------------------------------------------------------
# build_report — overall stats
# ---------------------------------------------------------------------------


def test_build_report_total_count():
    """Report includes total query count."""
    events = [_event() for _ in range(5)]
    report = build_report(events)
    assert "Total queries :  5" in report or "Total queries : 5" in report


def test_build_report_failure_rate():
    """Failure rate is computed correctly."""
    events = [_event(failure=True)] * 2 + [_event(failure=False)] * 8
    report = build_report(events)
    assert "20.0%" in report


def test_build_report_freeform_preset_split():
    """Freeform and preset counts appear in the report."""
    events = [_event(query_type="freeform")] * 3 + [
        _event(query_type="preset", preset_id="coaching_tree")
    ] * 2
    report = build_report(events)
    assert "Freeform" in report
    assert "Preset" in report


# ---------------------------------------------------------------------------
# build_report — top queries
# ---------------------------------------------------------------------------


def test_build_report_top_queries():
    """Most frequent query appears near the top of the list."""
    events = [_event("popular query")] * 5 + [_event("rare query")] * 1
    report = build_report(events)
    assert "popular query" in report
    # popular should appear before rare in the report
    assert report.index("popular query") < report.index("rare query")


# ---------------------------------------------------------------------------
# build_report — segment breakdown
# ---------------------------------------------------------------------------


def test_build_report_segment_breakdown():
    """Segment counts are listed."""
    events = [
        _event(segment="Media"),
        _event(segment="Media"),
        _event(segment="Agents"),
    ]
    report = build_report(events)
    assert "Media" in report
    assert "Agents" in report


# ---------------------------------------------------------------------------
# build_report — preset flagging
# ---------------------------------------------------------------------------


def test_build_report_flags_high_failure_preset():
    """Preset with >10% rolling failure rate is flagged."""
    # 3 failures out of 5 runs in the last 7 days = 60% → should flag
    events = [
        _event(query_type="preset", preset_id="bad_preset", failure=True, days_ago=1)
    ] * 3 + [
        _event(query_type="preset", preset_id="bad_preset", failure=False, days_ago=1)
    ] * 2
    report = build_report(events, days=7)
    assert "FLAGGED" in report
    assert "bad_preset" in report


def test_build_report_does_not_flag_low_failure_preset():
    """Preset with ≤10% failure rate is not flagged."""
    # 1 failure out of 20 = 5% → should not flag
    events = [
        _event(query_type="preset", preset_id="good_preset", failure=True, days_ago=1)
    ] + [
        _event(query_type="preset", preset_id="good_preset", failure=False, days_ago=1)
    ] * 19
    report = build_report(events, days=7)
    assert "FLAGGED" not in report


def test_build_report_old_failures_outside_window_not_flagged():
    """Failures older than the rolling window don't trigger the flag."""
    # 10 failures, but all 30 days ago (outside 7-day window)
    events = [
        _event(query_type="preset", preset_id="old_preset", failure=True, days_ago=30)
    ] * 10
    report = build_report(events, days=7)
    assert "FLAGGED" not in report


def test_build_report_no_presets():
    """Report handles zero preset events gracefully."""
    events = [_event(query_type="freeform")] * 3
    report = build_report(events)
    assert "no preset queries logged" in report


# ---------------------------------------------------------------------------
# build_report — empty
# ---------------------------------------------------------------------------


def test_build_report_empty_events():
    """build_report handles empty event list without crashing."""
    report = build_report([])
    assert "Total queries" in report


# ---------------------------------------------------------------------------
# main() CLI
# ---------------------------------------------------------------------------


def test_main_missing_log(tmp_path):
    """main() returns exit code 1 when log file does not exist."""
    missing = tmp_path / "no_such.jsonl"
    result = main(["--log", str(missing)])
    assert result == 1


def test_main_success(tmp_path, capsys):
    """main() returns 0 and prints a report for a valid log."""
    log = tmp_path / "events.jsonl"
    _write_jsonl(log, [_event("hello world")])
    result = main(["--log", str(log), "--days", "7"])
    assert result == 0
    captured = capsys.readouterr()
    assert "hello world" in captured.out


def test_main_custom_days(tmp_path, capsys):
    """--days flag is passed through to the report."""
    log = tmp_path / "events.jsonl"
    _write_jsonl(log, [_event()])
    main(["--log", str(log), "--days", "14"])
    out = capsys.readouterr().out
    assert "14 days" in out
