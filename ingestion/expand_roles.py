"""Unpivot McIllece staff records into per-role records.

Takes cleaned staff records (one dict per coach-season from
``pull_mcillece_staff.load_mcillece_file``) and expands each into one
record per role abbreviation.  Each output record carries the full role
name, role tier, and a coordinator flag for downstream use.

Legend source: CFB-Coaches-Database-Legend-1.xlsx
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Role legend — abbreviation → full name (from McIllece legend sheet)
# ---------------------------------------------------------------------------

ROLE_LEGEND: dict[str, str] = {
    "AC": "Assistant Head Coach",
    "CB": "Cornerbacks",
    "DB": "Defensive Backs",
    "DC": "Defensive Coordinator",
    "DE": "Defensive Ends",
    "DF": "Defensive Assistant",
    "DL": "Defensive Line",
    "DT": "Defensive Tackles",
    "FB": "Fullbacks",
    "FG": "Field Goal Kickers",
    "GC": "Guards/Centers",
    "HC": "Head Coach",
    "IB": "Inside Linebackers",
    "IR": "Inside Receivers",
    "KO": "Kickoff Specialists",
    "KR": "Kick Returners",
    "LB": "Linebackers",
    "NB": "Nickel Backs",
    "OB": "Outside Linebackers",
    "OC": "Offensive Coordinator",
    "OF": "Offensive Assistant",
    "OL": "Offensive Line",
    "OR": "Outside Receivers",
    "OT": "Offensive Tackles",
    "PD": "Pass Defense Coordinator",
    "PG": "Pass Offense Coordinator",
    "PK": "Placekickers",
    "PR": "Punt Returners",
    "PT": "Punters",
    "QB": "Quarterbacks",
    "RB": "Running Backs",
    "RC": "Recruiting Coordinator",
    "RD": "Rush Defense Coordinator",
    "RG": "Rush Offense Coordinator",
    "SF": "Safeties",
    "ST": "Special Teams",
    "TE": "Tight Ends",
    "WR": "Wide Receivers",
}

# ---------------------------------------------------------------------------
# Tier classification
# ---------------------------------------------------------------------------

TIER_COORDINATOR = "COORDINATOR"
TIER_POSITION_COACH = "POSITION_COACH"
TIER_SUPPORT = "SUPPORT"
TIER_UNKNOWN = "UNKNOWN"

_COORDINATOR_ABBRS: frozenset[str] = frozenset({"HC", "AC", "OC", "DC", "PG", "PD", "RG", "RD"})
_POSITION_COACH_ABBRS: frozenset[str] = frozenset({
    "QB", "RB", "WR", "OL", "DL", "DB", "LB", "TE",
    "DE", "DT", "CB", "SF", "IB", "OB", "IR", "GC", "OT",
    "FB", "OR",   # in legend but not listed in task spec; both are position roles
})
_SUPPORT_ABBRS: frozenset[str] = frozenset({
    "ST", "RC", "OF", "DF", "KO", "KR", "PR", "PK", "PT", "NB", "FG",
})

# Primary coordinator roles flagged separately for downstream coaching-tree work
COORDINATOR_FLAG_ABBRS: frozenset[str] = frozenset({"HC", "OC", "DC"})

# Known dirty variants in the raw data → canonical abbreviation
_ABBR_NORMALIZATIONS: dict[str, str] = {
    "RC?": "RC",
}


def _classify_tier(abbr: str) -> str:
    """Return the tier string for a role abbreviation.

    Args:
        abbr: Uppercase role abbreviation (e.g. ``"HC"``, ``"WR"``).

    Returns:
        One of ``TIER_COORDINATOR``, ``TIER_POSITION_COACH``,
        ``TIER_SUPPORT``, or ``TIER_UNKNOWN``.
    """
    if abbr in _COORDINATOR_ABBRS:
        return TIER_COORDINATOR
    if abbr in _POSITION_COACH_ABBRS:
        return TIER_POSITION_COACH
    if abbr in _SUPPORT_ABBRS:
        return TIER_SUPPORT
    return TIER_UNKNOWN


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def expand_to_role_records(
    staff: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Unpivot staff records into one record per role per coach-season.

    Each input record's ``roles`` list (from pos1–pos5) is exploded so that
    downstream Neo4j loading can create a distinct COACHED_AT edge per role.

    Abbreviations not found in ``ROLE_LEGEND`` are flagged in the returned
    list and included in the output with ``role_tier="UNKNOWN"`` so no data
    is silently dropped.

    Args:
        staff: Cleaned staff records as returned by
            ``ingestion.pull_mcillece_staff.load_mcillece_file()``.

    Returns:
        A 2-tuple of:
        - ``role_records``: list of dicts, one per (coach, season, role).
          Each dict has keys: ``coach_code``, ``team_code``, ``year``,
          ``team``, ``coach_name``, ``role_abbr``, ``role``, ``role_tier``,
          ``is_coordinator``.
        - ``unmapped_abbrs``: sorted list of abbreviations that were not
          found in ``ROLE_LEGEND``.
    """
    role_records: list[dict[str, Any]] = []
    unmapped: set[str] = set()

    for rec in staff:
        for raw_abbr in rec["roles"]:
            abbr = _ABBR_NORMALIZATIONS.get(raw_abbr, raw_abbr)
            full_name = ROLE_LEGEND.get(abbr)
            if full_name is None:
                unmapped.add(abbr)
                logger.warning(
                    "Unknown role abbreviation %r for coach_code=%s year=%s",
                    abbr,
                    rec.get("coach_code"),
                    rec.get("year"),
                )
                full_name = abbr  # fall back to raw abbreviation so no data is lost

            role_records.append(
                {
                    "coach_code": rec["coach_code"],
                    "team_code": rec["team_code"],
                    "year": rec["year"],
                    "team": rec["team"],
                    "coach_name": rec["coach_name"],
                    "role_abbr": abbr,  # canonical (normalized) abbreviation
                    "role": full_name,
                    "role_tier": _classify_tier(abbr),
                    "is_coordinator": abbr in COORDINATOR_FLAG_ABBRS,
                }
            )

    logger.info(
        "Expanded %d staff records into %d role records (%d unmapped abbrs)",
        len(staff),
        len(role_records),
        len(unmapped),
    )
    return role_records, sorted(unmapped)


def print_summary(
    role_records: list[dict[str, Any]],
    unmapped_abbrs: list[str],
) -> None:
    """Print a human-readable summary of the expand results to stdout.

    Args:
        role_records: Output from ``expand_to_role_records``.
        unmapped_abbrs: Second return value of ``expand_to_role_records``.
    """
    from collections import Counter

    total = len(role_records)
    tier_counts: Counter[str] = Counter(r["role_tier"] for r in role_records)
    year_counts: Counter[int] = Counter(r["year"] for r in role_records)

    print(f"\nTotal role records:  {total:,}")

    print("\nBy tier:")
    for tier in (TIER_COORDINATOR, TIER_POSITION_COACH, TIER_SUPPORT, TIER_UNKNOWN):
        if tier_counts[tier]:
            print(f"  {tier:<20} {tier_counts[tier]:>7,}")

    print("\nBy year:")
    for year in sorted(year_counts):
        print(f"  {year}  {year_counts[year]:>6,}")

    if unmapped_abbrs:
        print(f"\nUnmapped abbreviations ({len(unmapped_abbrs)}):")
        for abbr in unmapped_abbrs:
            count = sum(1 for r in role_records if r["role_abbr"] == abbr)
            print(f"  {abbr!r:10s}  {count} occurrences")
    else:
        print("\nUnmapped abbreviations: none")
