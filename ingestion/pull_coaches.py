"""Fetch full coaching career histories from the CFBD API.

The /coaches endpoint returns every coach record across all seasons,
so one call captures the complete career history without year-looping.
"""

import json
import logging
from pathlib import Path

from ingestion.utils import build_session, get_json

logger = logging.getLogger(__name__)

_RAW_PATH = Path("data/raw/coaches.json")


def fetch_coaches(api_key: str, raw_path: Path = _RAW_PATH) -> list[dict]:
    """Return all coach career records from the CFBD API.

    Each record contains ``first_name``, ``last_name``, and a ``seasons``
    list with per-season stint details (school, year, wins, losses, title).

    The full result is cached to ``data/raw/coaches.json`` so the API is
    never contacted a second time.

    Args:
        api_key: CFBD API key (from the CFBD_API_KEY environment variable).
        raw_path: Destination for the cached JSON file.

    Returns:
        A list of coach dicts as returned by the CFBD ``/coaches`` endpoint.
    """
    if raw_path.exists():
        logger.info("Loading coaches from cache: %s", raw_path)
        return json.loads(raw_path.read_text())

    logger.info("Fetching coaches from CFBD API")
    session = build_session(api_key)
    coaches = get_json(session, "/coaches")

    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(json.dumps(coaches, indent=2))
    logger.info("Saved %d coaches to %s", len(coaches), raw_path)

    return coaches
