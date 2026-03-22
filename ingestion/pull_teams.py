"""Fetch all teams from the CFBD API and cache the result to data/raw/teams.json."""

import json
import logging
from pathlib import Path

from ingestion.utils import build_session, get_json

logger = logging.getLogger(__name__)

_RAW_PATH = Path("data/raw/teams.json")


def fetch_teams(api_key: str, raw_path: Path = _RAW_PATH) -> list[dict]:
    """Return all college football teams from the CFBD API.

    On the first call the result is fetched from the API and saved to
    ``data/raw/teams.json``.  Subsequent calls load from that file so the
    API is never hit twice.

    Args:
        api_key: CFBD API key (from the CFBD_API_KEY environment variable).
        raw_path: Path where the raw JSON will be cached.  Defaults to
            ``data/raw/teams.json`` (relative to the project root).

    Returns:
        A list of team dicts as returned by the CFBD ``/teams`` endpoint.
        Each dict contains keys like ``school``, ``conference``,
        ``abbreviation``, ``id``, etc.
    """
    if raw_path.exists():
        logger.info("Loading teams from cache: %s", raw_path)
        return json.loads(raw_path.read_text())

    logger.info("Fetching teams from CFBD API")
    session = build_session(api_key)
    teams = get_json(session, "/teams")

    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(json.dumps(teams, indent=2))
    logger.info("Saved %d teams to %s", len(teams), raw_path)

    return teams
