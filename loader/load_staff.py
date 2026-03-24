"""Load McIllece staff records into Neo4j.

Merges Coach nodes (keyed on ``coach_code``) and COACHED_AT relationships
(tagged ``source="mcillece"``).  All writes use MERGE so the loader is
fully idempotent — safe to re-run without creating duplicate nodes or edges.

Usage (standalone):
    python -m loader.load_staff path/to/file.xlsx
    python -m loader.load_staff path/to/file.xlsx --dry-run
"""

import logging
import os
import sys
from pathlib import Path
from typing import Any

from neo4j import Driver

from ingestion.role_constants import validate_role
from loader import schema

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_staff(driver: Driver, staff: list[dict[str, Any]]) -> tuple[int, int]:
    """MERGE Coach nodes and COACHED_AT edges from McIllece staff records.

    Coach nodes are keyed by ``coach_code`` — the primary unique identifier
    introduced by the McIllece dataset.  Each COACHED_AT relationship carries
    ``year``, ``roles`` (list), and ``source="mcillece"`` so it can be
    distinguished from CFBD-sourced edges.

    Args:
        driver: Open Neo4j driver.
        staff: Cleaned staff records as returned by
            ``ingestion.pull_mcillece_staff.load_mcillece_file()``.

    Returns:
        ``(coaches_merged, edges_merged)`` where *coaches_merged* is the
        number of unique coach_code values processed and *edges_merged* is
        the total number of COACHED_AT rows submitted.
    """
    if not staff:
        logger.info("No staff records to load — skipping")
        print("Coaches merged:         0")
        print("COACHED_AT edges merged: 0")
        return 0, 0

    # Validate role codes against the McIllece legend.  Unknown codes are
    # ingested unchanged — the warning is informational only.
    for rec in staff:
        for role in (rec.get("roles") or []):
            if not validate_role(role):
                logger.warning(
                    "Unknown role code %r for coach_code=%s year=%s — ingesting anyway",
                    role,
                    rec.get("coach_code"),
                    rec.get("year"),
                )

    coach_query = f"""
    UNWIND $rows AS row
    MERGE (c:{schema.COACH} {{coach_code: row.coach_code}})
    SET c.name       = row.coach_name,
        c.coach_code = row.coach_code
    """

    # COACHED_AT MERGE key: (coach_code, year, team_code) — one row per
    # coach-season.  A coach_code + year pair uniquely identifies a season
    # within a single team; team_code disambiguates if a coach had two stints
    # at different schools in the same year (rare but possible).
    stint_query = f"""
    UNWIND $rows AS row
    MATCH  (c:{schema.COACH} {{coach_code: row.coach_code}})
    MATCH  (t:{schema.TEAM}  {{school: row.team}})
    MERGE  (c)-[r:{schema.COACHED_AT} {{
        coach_code: row.coach_code,
        year:       row.year,
        team_code:  row.team_code
    }}]->(t)
    SET r.roles  = row.roles,
        r.source = "mcillece"
    """

    with driver.session() as session:
        session.run(coach_query, rows=staff)
        session.run(stint_query, rows=staff)

    coaches_merged = len({r["coach_code"] for r in staff})
    edges_merged = len(staff)

    print(f"Coaches merged:         {coaches_merged:,}")
    print(f"COACHED_AT edges merged: {edges_merged:,}")
    logger.info(
        "Merged %d unique coaches, %d COACHED_AT edges (source=mcillece)",
        coaches_merged,
        edges_merged,
    )
    return coaches_merged, edges_merged


def dry_run_staff(staff: list[dict[str, Any]]) -> None:
    """Print what *would* be loaded without touching Neo4j.

    Useful for verifying a new file before committing to the database.

    Args:
        staff: Cleaned staff records as returned by
            ``ingestion.pull_mcillece_staff.load_mcillece_file()``.
    """
    unique_coaches = {r["coach_code"]: r["coach_name"] for r in staff}

    print("=" * 60)
    print(f"  DRY RUN — McIllece staff ingestion")
    print("=" * 60)
    print(f"\nCoaches that would be merged: {len(unique_coaches):,}")
    for code, name in sorted(unique_coaches.items()):
        print(f"  [{code:>6}] {name}")

    print(f"\nCOACHED_AT edges that would be merged: {len(staff):,}")
    for r in sorted(staff, key=lambda x: (x["team"], x["year"], x["coach_name"])):
        roles_str = ", ".join(r["roles"]) if r["roles"] else "(no role)"
        print(
            f"  [{r['coach_code']:>6}] {r['coach_name']:<30} "
            f"{r['team']:<20} {r['year']}  roles={roles_str}"
        )
    print()


# ---------------------------------------------------------------------------
# Standalone entry-point
# ---------------------------------------------------------------------------


def _run(file_path: str, *, dry_run: bool = False) -> None:
    from ingestion.pull_mcillece_staff import load_mcillece_file

    staff = load_mcillece_file(file_path)
    print(f"Parsed {len(staff):,} staff records from '{file_path}'")

    if dry_run:
        dry_run_staff(staff)
        return

    from dotenv import load_dotenv
    load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

    from loader.neo4j_loader import get_driver

    driver = get_driver(
        os.environ["NEO4J_URI"],
        os.environ["NEO4J_USERNAME"],
        os.environ["NEO4J_PASSWORD"],
    )
    try:
        load_staff(driver, staff)
    finally:
        driver.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print("Usage: python -m loader.load_staff <file_path> [--dry-run]")
        sys.exit(0 if args else 1)
    _run(args[0], dry_run="--dry-run" in args)
