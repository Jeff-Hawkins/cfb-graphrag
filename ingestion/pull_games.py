"""Fetch game results from the CFBD API for a range of seasons.

Games are fetched year-by-year (regular season + postseason) and cached
individually as ``data/raw/games_{year}.json``.
"""

import json
import logging
from pathlib import Path

from ingestion.utils import build_session, get_json

logger = logging.getLogger(__name__)

_DEFAULT_YEARS = list(range(2015, 2026))  # 2015–2025 inclusive


def fetch_games(
    api_key: str,
    years: list[int] | None = None,
    raw_dir: Path = Path("data/raw"),
) -> list[dict]:
    """Return game records for every season in the requested range.

    Fetches both regular-season (``seasonType=regular``) and postseason
    (``seasonType=postseason``) games and merges them.  Each season's
    combined data is cached to ``data/raw/games_{year}.json``; existing
    files are never re-fetched.

    Args:
        api_key: CFBD API key (from the CFBD_API_KEY environment variable).
        years: List of integer seasons to fetch.  Defaults to 2015–2025.
        raw_dir: Directory where per-year JSON files are stored.

    Returns:
        Flat list of game dicts across all requested years.  Each dict
        contains keys like ``id``, ``season``, ``home_team``, ``away_team``,
        ``home_points``, ``away_points``, ``week``, etc.
    """
    if years is None:
        years = _DEFAULT_YEARS

    session = build_session(api_key)
    raw_dir.mkdir(parents=True, exist_ok=True)
    all_games: list[dict] = []

    for year in years:
        file_path = raw_dir / f"games_{year}.json"

        if file_path.exists():
            logger.info("Loading games %d from cache: %s", year, file_path)
            games = json.loads(file_path.read_text())
        else:
            logger.info("Fetching games for year %d", year)
            regular = get_json(
                session, "/games", params={"year": year, "seasonType": "regular"}
            )
            postseason = get_json(
                session, "/games", params={"year": year, "seasonType": "postseason"}
            )
            games = regular + postseason
            file_path.write_text(json.dumps(games, indent=2))
            logger.info("Saved %d games for %d", len(games), year)

        all_games.extend(games)

    return all_games
