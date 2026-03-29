"""F3 — Event tracker: appends query events as JSON lines to logs/query_events.jsonl.

Each call to :func:`log_event` is a single append — no locking, no SQLite, no
over-engineering.  The log file is safe to read while the app is running
(readers see complete lines).

Usage::

    from analytics.tracker import log_event

    log_event(
        query_text="Show me Nick Saban's coaching tree",
        query_type="preset",
        preset_id="coaching_tree",
        segment="General",
        result_count=42,
        failure=False,
        duration_ms=312,
        session_id="abc123",
    )
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Default log path — relative to project root, overridable via env var.
_DEFAULT_LOG_PATH = Path(__file__).parent.parent / "logs" / "query_events.jsonl"


def _log_path() -> Path:
    """Return the resolved path to the event log file.

    Reads ``CFB_EVENT_LOG`` from the environment, falling back to
    ``logs/query_events.jsonl`` in the project root.

    Returns:
        Resolved :class:`~pathlib.Path` to the log file.
    """
    raw = os.environ.get("CFB_EVENT_LOG", "")
    return Path(raw) if raw else _DEFAULT_LOG_PATH


def log_event(
    *,
    query_text: str,
    query_type: str,
    preset_id: Optional[str] = None,
    segment: Optional[str] = None,
    result_count: int = 0,
    failure: bool = False,
    duration_ms: int = 0,
    exported: bool = False,
    session_id: Optional[str] = None,
) -> None:
    """Append one query event to the JSON lines log file.

    The log file is created (along with its parent directory) if it does not
    exist.  Each line is a valid JSON object followed by a newline, making the
    file readable by ``jq``, pandas, and the :mod:`analytics.summary` script.

    Args:
        query_text: The raw NL query string or preset display name.
        query_type: ``"preset"`` or ``"freeform"``.
        preset_id: YAML ``id`` of the preset, or ``None`` for freeform queries.
        segment: User segment label from the sidebar (e.g. ``"General"``).
        result_count: Number of rows/nodes returned by the query.
        failure: ``True`` if the query raised an exception or returned an error.
        duration_ms: Wall-clock time from query start to result, in milliseconds.
        exported: ``True`` if the user exported or screenshotted the result.
        session_id: Opaque session identifier (UUID string).
    """
    event: dict = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "query_text": query_text,
        "query_type": query_type,
        "preset_id": preset_id,
        "segment": segment,
        "result_count": result_count,
        "failure": failure,
        "duration_ms": duration_ms,
        "exported": exported,
        "session_id": session_id,
    }
    path = _log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event) + "\n")
    except OSError:
        logger.exception("F3: failed to write event log to %s", path)
