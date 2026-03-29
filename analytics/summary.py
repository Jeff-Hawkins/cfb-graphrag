"""F3 — Weekly query observability summary.

Reads ``logs/query_events.jsonl`` and prints a report covering:

- Total queries, failure rate, freeform vs. preset split
- Top 10 queries by frequency
- Segment breakdown
- Per-preset stats with a FLAGGED marker when failure rate > 10% over the
  rolling 7-day window (the review threshold defined in the F3 spec)

Usage::

    python -m analytics.summary
    python -m analytics.summary --days 14
    python -m analytics.summary --log path/to/custom.jsonl

Exit codes:
    0 — success (even if presets are flagged)
    1 — log file not found or unreadable
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_DEFAULT_LOG_PATH = Path(__file__).parent.parent / "logs" / "query_events.jsonl"
_FAILURE_THRESHOLD = 0.10  # 10 % — flag preset for rewrite above this


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_events(log_path: Path) -> list[dict[str, Any]]:
    """Load all events from a JSON lines log file.

    Args:
        log_path: Path to the ``.jsonl`` file produced by :mod:`analytics.tracker`.

    Returns:
        List of event dicts; malformed lines are skipped with a warning.
    """
    events: list[dict] = []
    with log_path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                print(f"  [warn] skipping malformed line {lineno}", file=sys.stderr)
    return events


def _parse_ts(ts: str) -> datetime:
    """Parse an ISO-8601 timestamp string to an aware UTC datetime.

    Args:
        ts: ISO-8601 string, e.g. ``"2026-03-28T14:00:00+00:00"``.

    Returns:
        Timezone-aware :class:`~datetime.datetime` in UTC.
    """
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------


def build_report(events: list[dict], days: int = 7) -> str:
    """Build a plain-text observability report from a list of events.

    Args:
        events: Event dicts loaded by :func:`load_events`.
        days: Rolling window in days for the preset failure-rate check.

    Returns:
        Multi-line string suitable for printing to stdout.
    """
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=days)

    lines: list[str] = []
    sep = "─" * 60

    # ── Overall stats ────────────────────────────────────────────────────
    total = len(events)
    failures = sum(1 for e in events if e.get("failure"))
    freeform = sum(1 for e in events if e.get("query_type") == "freeform")
    preset = sum(1 for e in events if e.get("query_type") == "preset")
    failure_pct = (failures / total * 100) if total else 0.0

    lines += [
        sep,
        "CFB IQ — Query Observability Report",
        f"Generated: {now.strftime('%Y-%m-%d %H:%M UTC')}  |  Window: {days} days",
        sep,
        "",
        "OVERALL",
        f"  Total queries : {total}",
        f"  Failures      : {failures}  ({failure_pct:.1f}%)",
        f"  Freeform      : {freeform}",
        f"  Preset        : {preset}",
    ]

    # Average duration (exclude failures for cleaner signal)
    durations = [e.get("duration_ms", 0) for e in events if not e.get("failure")]
    if durations:
        avg_ms = sum(durations) / len(durations)
        lines.append(f"  Avg duration  : {avg_ms:.0f} ms  (successful queries)")

    lines.append("")

    # ── Top queries ──────────────────────────────────────────────────────
    query_counts: Counter = Counter(
        e.get("query_text", "") for e in events if e.get("query_text")
    )
    lines += ["TOP 10 QUERIES"]
    for text, count in query_counts.most_common(10):
        truncated = text[:55] + "…" if len(text) > 55 else text
        lines.append(f"  {count:>4}×  {truncated}")
    if not query_counts:
        lines.append("  (no queries logged)")
    lines.append("")

    # ── Segment breakdown ────────────────────────────────────────────────
    seg_counts: Counter = Counter(
        e.get("segment") or "Unknown" for e in events
    )
    lines += ["SEGMENT BREAKDOWN"]
    for seg, count in seg_counts.most_common():
        lines.append(f"  {count:>4}×  {seg}")
    if not seg_counts:
        lines.append("  (no segment data)")
    lines.append("")

    # ── Preset stats + failure-rate flags ────────────────────────────────
    preset_events = [e for e in events if e.get("query_type") == "preset"]
    window_preset_events = [
        e for e in preset_events
        if e.get("timestamp") and _parse_ts(e["timestamp"]) >= window_start
    ]

    # Aggregate per preset_id for all-time stats.
    all_time: dict[str, dict] = defaultdict(lambda: {"total": 0, "failures": 0})
    for e in preset_events:
        pid = e.get("preset_id") or "unknown"
        all_time[pid]["total"] += 1
        if e.get("failure"):
            all_time[pid]["failures"] += 1

    # Aggregate per preset_id for rolling window (failure rate check).
    window_stats: dict[str, dict] = defaultdict(lambda: {"total": 0, "failures": 0})
    for e in window_preset_events:
        pid = e.get("preset_id") or "unknown"
        window_stats[pid]["total"] += 1
        if e.get("failure"):
            window_stats[pid]["failures"] += 1

    lines += [f"PRESET STATS  (⚠ = failure rate > {_FAILURE_THRESHOLD:.0%} last {days}d)"]
    if not all_time:
        lines.append("  (no preset queries logged)")
    else:
        for pid, stats in sorted(all_time.items()):
            t = stats["total"]
            f = stats["failures"]
            pct = f / t * 100 if t else 0.0
            # Check rolling-window failure rate for flag.
            ws = window_stats.get(pid, {"total": 0, "failures": 0})
            wt = ws["total"]
            wf = ws["failures"]
            wrate = wf / wt if wt else 0.0
            flag = "  ⚠  FLAGGED — rewrite candidate" if wrate > _FAILURE_THRESHOLD else ""
            lines.append(
                f"  {pid:<30}  {t:>4} runs  {f:>3} fail ({pct:.0f}%){flag}"
            )

    lines += ["", sep, ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Run the summary report from the command line.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Exit code: ``0`` on success, ``1`` on file error.
    """
    parser = argparse.ArgumentParser(
        description="Print CFB IQ query observability summary."
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=_DEFAULT_LOG_PATH,
        help="Path to query_events.jsonl (default: logs/query_events.jsonl)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Rolling window in days for preset failure-rate check (default: 7)",
    )
    args = parser.parse_args(argv)

    if not args.log.exists():
        print(f"Error: log file not found: {args.log}", file=sys.stderr)
        return 1

    try:
        events = load_events(args.log)
    except OSError as exc:
        print(f"Error reading log: {exc}", file=sys.stderr)
        return 1

    print(build_report(events, days=args.days))
    return 0


if __name__ == "__main__":
    sys.exit(main())
