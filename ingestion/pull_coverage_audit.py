"""Audit CFBD API data coverage by year for key endpoints.

Loops years 2005–2025 across four endpoints, counts records per year,
prints a coverage table, flags gaps, and saves results to
data/audits/cfbd_coverage_audit.csv.
"""

import csv
import logging
from pathlib import Path
from typing import Any

from ingestion.utils import build_session, get_json

logger = logging.getLogger(__name__)

AUDIT_YEARS = list(range(2005, 2026))  # 2005–2025 inclusive

# Endpoint definitions: (label, path, year_param_name)
ENDPOINTS: list[tuple[str, str, str]] = [
    ("recruiting_players", "/recruiting/players", "year"),
    ("draft_picks", "/draft/picks", "year"),
    ("stats_season_advanced", "/stats/season/advanced", "year"),
    ("ratings_sp", "/ratings/sp", "year"),
]

# Minimum record counts below which a year is flagged as suspicious.
# SP+ and advanced stats are team-level (~130 FBS teams); recruiting/draft are player-level.
LOW_COUNT_THRESHOLDS: dict[str, int] = {
    "recruiting_players": 100,
    "draft_picks": 50,
    "stats_season_advanced": 20,
    "ratings_sp": 20,
}

_DEFAULT_AUDIT_PATH = Path("data/audits/cfbd_coverage_audit.csv")


def fetch_record_count(
    session: Any,
    endpoint: str,
    year_param: str,
    year: int,
) -> int:
    """Fetch one year of data from an endpoint and return the record count.

    Args:
        session: Authenticated requests.Session from build_session().
        endpoint: CFBD path, e.g. ``"/recruiting/players"``.
        year_param: Query parameter name for year (always ``"year"`` on CFBD).
        year: Calendar year to request.

    Returns:
        Number of records returned by the API, or 0 on a non-fatal error.
    """
    try:
        data = get_json(session, endpoint, params={year_param: year})
        return len(data) if isinstance(data, list) else 0
    except Exception as exc:  # noqa: BLE001
        logger.warning("Error fetching %s year=%d: %s", endpoint, year, exc)
        return 0


def run_coverage_audit(
    api_key: str,
    years: list[int] = AUDIT_YEARS,
    audit_path: Path = _DEFAULT_AUDIT_PATH,
) -> list[dict[str, Any]]:
    """Pull record counts for all endpoints × years and save results to CSV.

    Prints a formatted coverage table to stdout. Years with counts below the
    threshold defined in LOW_COUNT_THRESHOLDS are flagged with ``[LOW]``.

    Args:
        api_key: CFBD API key.
        years: List of calendar years to audit (default 2005–2025).
        audit_path: Destination CSV path (parent dirs created automatically).

    Returns:
        List of result dicts, one per (endpoint, year) combination, with keys:
        ``endpoint``, ``year``, ``record_count``, ``flagged``.
    """
    session = build_session(api_key)
    results: list[dict[str, Any]] = []

    for label, path, year_param in ENDPOINTS:
        threshold = LOW_COUNT_THRESHOLDS[label]
        logger.info("Auditing %s ...", label)
        counts: list[tuple[int, int]] = []

        for year in years:
            count = fetch_record_count(session, path, year_param, year)
            flagged = count == 0 or count < threshold
            results.append(
                {
                    "endpoint": label,
                    "year": year,
                    "record_count": count,
                    "flagged": flagged,
                }
            )
            counts.append((year, count))

        _print_endpoint_table(label, counts, threshold)

    _save_csv(results, audit_path)
    logger.info("Audit saved to %s", audit_path)
    return results


def _print_endpoint_table(
    label: str,
    counts: list[tuple[int, int]],
    threshold: int,
) -> None:
    """Print a formatted year-vs-count table for one endpoint.

    Args:
        label: Short endpoint name used as the table header.
        counts: List of (year, record_count) tuples in order.
        threshold: Count below which a row is flagged as low.
    """
    print(f"\n{'=' * 42}")
    print(f"  {label}  (flag threshold: < {threshold})")
    print(f"{'=' * 42}")
    print(f"  {'Year':<8} {'Records':>10}  Flag")
    print(f"  {'-' * 6}  {'-' * 10}  ----")
    for year, count in counts:
        flag = " [LOW]" if count == 0 or count < threshold else ""
        print(f"  {year:<8} {count:>10}{flag}")


def _save_csv(results: list[dict[str, Any]], path: Path) -> None:
    """Write audit results to a CSV file.

    Args:
        results: List of result dicts from run_coverage_audit().
        path: Destination file path (parent dirs created if absent).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["endpoint", "year", "record_count", "flagged"]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
