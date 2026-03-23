"""Export all AuraDB data to JSON files for Railway migration.

Creates data/migrations/auradb_export_YYYYMMDD/ with one file per
node label and relationship type:

    nodes_Player.json
    nodes_Team.json
    nodes_Coach.json
    nodes_Conference.json
    rels_PLAYED_FOR.json
    rels_COACHED_AT_cfbd.json
    rels_COACHED_AT_mcillece.json
    rels_COACHED_AT_mcillece_roles.json
    rels_PLAYED.json
    rels_IN_CONFERENCE.json
    rels_MENTORED.json

Usage:
    python export_auradb.py [--dry-run]

--dry-run prints what *would* happen without connecting to AuraDB.

Requires NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD in .env.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from neo4j import Driver

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

_BATCH_SIZE = 5_000  # records per streaming pull


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_query(driver: Driver, query: str, label: str) -> list[dict[str, Any]]:
    """Execute *query*, return all records as a list of plain dicts.

    Args:
        driver: Open Neo4j driver.
        query: Cypher read query.
        label: Human-readable label for log output.

    Returns:
        List of record dicts (one per result row).
    """
    with driver.session() as session:
        result = session.run(query)
        rows = [dict(r) for r in result]
    logger.info("Exported %10d  %s", len(rows), label)
    return rows


def _save_json(out_dir: Path, filename: str, data: list[dict[str, Any]]) -> None:
    """Serialize *data* to *out_dir/filename* as a JSON array.

    Args:
        out_dir: Target directory (must exist).
        filename: Output filename (e.g. ``"nodes_Player.json"``).
        data: Records to serialise.
    """
    path = out_dir / filename
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, default=str)
    logger.info("Saved %s (%d records)", path.name, len(data))


# ---------------------------------------------------------------------------
# Core export logic
# ---------------------------------------------------------------------------


def export_all(driver: Driver, out_dir: Path) -> dict[str, int]:
    """Export every node and relationship from the connected database.

    Writes one JSON file per label / relationship type to *out_dir*.
    COACHED_AT edges are split into three files by their ``source``
    property to preserve the correct MERGE key on import.

    Args:
        driver: Open Neo4j driver pointing at AuraDB.
        out_dir: Directory that already exists; files are written here.

    Returns:
        ``{filename_stem: record_count}`` for every file written.
    """
    counts: dict[str, int] = {}

    # ── Nodes ─────────────────────────────────────────────────────────────
    for label in ("Player", "Team", "Coach", "Conference"):
        rows = _run_query(
            driver,
            f"MATCH (n:{label}) RETURN properties(n) AS props",
            f"{label} nodes",
        )
        data = [r["props"] for r in rows]
        key = f"nodes_{label}"
        _save_json(out_dir, f"{key}.json", data)
        counts[key] = len(data)

    # ── PLAYED_FOR ────────────────────────────────────────────────────────
    # MERGE key on import: (Player.id, Team.school, year)
    rows = _run_query(
        driver,
        """
        MATCH (p:Player)-[r:PLAYED_FOR]->(t:Team)
        RETURN p.id AS player_id,
               r.year   AS year,
               r.jersey AS jersey,
               t.school AS team_school
        """,
        "PLAYED_FOR rels",
    )
    _save_json(out_dir, "rels_PLAYED_FOR.json", rows)
    counts["rels_PLAYED_FOR"] = len(rows)

    # ── COACHED_AT — CFBD (source IS NULL) ───────────────────────────────
    # MERGE key on import: (Coach.first_name, Coach.last_name, Team.school,
    #                        title, start_year)
    rows = _run_query(
        driver,
        """
        MATCH (c:Coach)-[r:COACHED_AT]->(t:Team)
        WHERE r.source IS NULL
        RETURN c.first_name AS first_name,
               c.last_name  AS last_name,
               t.school     AS team_school,
               r.title      AS title,
               r.start_year AS start_year,
               r.end_year   AS end_year
        """,
        "COACHED_AT (cfbd) rels",
    )
    _save_json(out_dir, "rels_COACHED_AT_cfbd.json", rows)
    counts["rels_COACHED_AT_cfbd"] = len(rows)

    # ── COACHED_AT — McIllece season-level (source='mcillece') ───────────
    # MERGE key on import: (Coach.coach_code, year, team_code)
    rows = _run_query(
        driver,
        """
        MATCH (c:Coach)-[r:COACHED_AT]->(t:Team)
        WHERE r.source = 'mcillece'
        RETURN c.coach_code AS coach_code,
               t.school     AS team_school,
               r.year       AS year,
               r.team_code  AS team_code,
               r.roles      AS roles,
               r.source     AS source
        """,
        "COACHED_AT (mcillece) rels",
    )
    _save_json(out_dir, "rels_COACHED_AT_mcillece.json", rows)
    counts["rels_COACHED_AT_mcillece"] = len(rows)

    # ── COACHED_AT — McIllece per-role (source='mcillece_roles') ─────────
    # MERGE key on import: (Coach.coach_code, year, team_code, role_abbr)
    rows = _run_query(
        driver,
        """
        MATCH (c:Coach)-[r:COACHED_AT]->(t:Team)
        WHERE r.source = 'mcillece_roles'
        RETURN c.coach_code AS coach_code,
               t.school     AS team_school,
               properties(r) AS rel_props
        """,
        "COACHED_AT (mcillece_roles) rels",
    )
    _save_json(out_dir, "rels_COACHED_AT_mcillece_roles.json", rows)
    counts["rels_COACHED_AT_mcillece_roles"] = len(rows)

    # ── PLAYED ────────────────────────────────────────────────────────────
    # MERGE key on import: game_id on the relationship
    rows = _run_query(
        driver,
        """
        MATCH (home:Team)-[r:PLAYED]->(away:Team)
        RETURN home.school AS home_school,
               away.school AS away_school,
               properties(r) AS rel_props
        """,
        "PLAYED rels",
    )
    _save_json(out_dir, "rels_PLAYED.json", rows)
    counts["rels_PLAYED"] = len(rows)

    # ── IN_CONFERENCE ─────────────────────────────────────────────────────
    rows = _run_query(
        driver,
        """
        MATCH (t:Team)-[:IN_CONFERENCE]->(c:Conference)
        RETURN t.school AS team_school,
               c.name   AS conference_name
        """,
        "IN_CONFERENCE rels",
    )
    _save_json(out_dir, "rels_IN_CONFERENCE.json", rows)
    counts["rels_IN_CONFERENCE"] = len(rows)

    # ── MENTORED ─────────────────────────────────────────────────────────
    # Coaches may be identified by first/last (CFBD) or coach_code (McIllece).
    # Export both; import will use whichever is non-null.
    rows = _run_query(
        driver,
        """
        MATCH (mentor:Coach)-[:MENTORED]->(mentee:Coach)
        RETURN mentor.first_name AS mentor_first,
               mentor.last_name  AS mentor_last,
               mentor.coach_code AS mentor_code,
               mentee.first_name AS mentee_first,
               mentee.last_name  AS mentee_last,
               mentee.coach_code AS mentee_code
        """,
        "MENTORED rels",
    )
    _save_json(out_dir, "rels_MENTORED.json", rows)
    counts["rels_MENTORED"] = len(rows)

    return counts


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------


def main(*, dry_run: bool = False) -> None:
    """Run the full AuraDB export.

    Args:
        dry_run: If True, log what would happen without connecting.
    """
    out_dir = (
        Path("data/migrations")
        / f"auradb_export_{date.today().strftime('%Y%m%d')}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    if dry_run:
        logger.info("[dry-run] Would export AuraDB → %s", out_dir)
        logger.info("[dry-run] No Neo4j connection made — exiting")
        return

    uri = os.environ.get("NEO4J_URI", "")
    username = os.environ.get("NEO4J_USERNAME", "")
    password = os.environ.get("NEO4J_PASSWORD", "")
    if not all([uri, username, password]):
        raise EnvironmentError(
            "NEO4J_URI, NEO4J_USERNAME, and NEO4J_PASSWORD must be set in .env"
        )

    from loader.neo4j_loader import get_driver

    driver = get_driver(uri, username, password)
    try:
        counts = export_all(driver, out_dir)
    finally:
        driver.close()

    total_nodes = sum(v for k, v in counts.items() if k.startswith("nodes_"))
    total_rels = sum(v for k, v in counts.items() if k.startswith("rels_"))

    print("\n=== AuraDB Export Summary ===")
    for key in sorted(counts):
        print(f"  {key:<40} {counts[key]:>10,}")
    print(f"\n  Total nodes         {total_nodes:>10,}")
    print(f"  Total relationships {total_rels:>10,}")
    print(f"\nExport written to: {out_dir.resolve()}")


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
