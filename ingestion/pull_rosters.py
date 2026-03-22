"""Fetch team rosters from the CFBD API for a range of seasons.

Rosters are fetched year-by-year and cached individually as
``data/raw/roster_{year}.json`` to allow incremental updates.
"""

import json
import logging
from pathlib import Path

from ingestion.utils import build_session, get_json

logger = logging.getLogger(__name__)

_DEFAULT_YEARS = list(range(2015, 2026))  # 2015–2025 inclusive


def fetch_rosters(
    api_key: str,
    years: list[int] | None = None,
    raw_dir: Path = Path("data/raw"),
) -> list[dict]:
    """Return roster records for every team across the requested seasons.

    Each season's data is cached to ``data/raw/roster_{year}.json``.
    If the file already exists for a given year the API is skipped for
    that year.

    Args:
        api_key: CFBD API key (from the CFBD_API_KEY environment variable).
        years: List of integer seasons to fetch.  Defaults to 2015–2025.
        raw_dir: Directory where per-year JSON files are stored.

    Returns:
        Flat list of player-roster dicts across all requested years.
        Each dict contains keys like ``athleteId``, ``firstName``,
        ``lastName``, ``position``, ``hometown``, ``team``, ``year``.
    """
    if years is None:
        years = _DEFAULT_YEARS

    session = build_session(api_key)
    raw_dir.mkdir(parents=True, exist_ok=True)
    all_records: list[dict] = []

    for year in years:
        file_path = raw_dir / f"roster_{year}.json"

        if file_path.exists():
            logger.info("Loading roster %d from cache: %s", year, file_path)
            records = json.loads(file_path.read_text())
        else:
            logger.info("Fetching roster for year %d", year)
            records = get_json(session, "/roster", params={"year": year})
            file_path.write_text(json.dumps(records, indent=2))
            logger.info("Saved %d roster records for %d", len(records), year)

        # Inject season_year so downstream consumers know which season each
        # record belongs to.  The CFBD ``year`` field is the player's
        # academic year (1 = Freshman), not the calendar season.
        for r in records:
            r["season_year"] = year

        all_records.extend(records)

    return all_records
