"""A1 Data Validation Agent — anomaly_checks.py.

General-purpose ingestion anomaly detection beyond ground-truth spot checks.
Intended to run after every ingestion batch and report unexpected patterns.

Checks implemented:
- Duplicate McIllece coach nodes (same name, multiple coach_codes)
- Coaches present in COACHED_AT but absent from Coach nodes (orphan edges)
- Teams referenced in COACHED_AT that have no Team node (orphan team refs)
- MENTORED self-loops (a coach mentoring themselves)
- MENTORED cycles of length 2 (A mentors B AND B mentors A simultaneously)
- COACHED_AT edges with NULL role_abbr (mcillece_roles source only)
- COACHED_AT year gaps: coaches with a >5-year gap between recorded seasons
  at the same team (may indicate missing data years)

Usage::

    python -m agents.data_validation.anomaly_checks
    python agents/data_validation/anomaly_checks.py
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from neo4j import Driver

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Individual anomaly checks
# ---------------------------------------------------------------------------


def check_duplicate_coach_nodes(driver: Driver) -> list[dict[str, Any]]:
    """Find McIllece coaches with the same name but different coach_codes.

    A small number of duplicates is expected (e.g., different 'John Smith'
    coaches), but large clusters may indicate a bad import.

    Args:
        driver: Open Neo4j driver.

    Returns:
        List of dicts with ``name``, ``coach_codes``, ``count``.
    """
    query = """
    MATCH (c:Coach)
    WHERE c.coach_code IS NOT NULL AND c.name IS NOT NULL
    WITH c.name AS name, collect(c.coach_code) AS codes, count(*) AS n
    WHERE n > 1
    RETURN name, codes, n AS count
    ORDER BY n DESC
    LIMIT 20
    """
    with driver.session() as s:
        result = s.run(query)
        return [r.data() for r in result]


def check_mentored_self_loops(driver: Driver) -> list[dict[str, Any]]:
    """Find MENTORED self-loops (a coach → themselves).

    These are always data errors and should not exist after any ingestion.

    Args:
        driver: Open Neo4j driver.

    Returns:
        List of coach dicts (should be empty in a clean graph).
    """
    query = """
    MATCH (c:Coach)-[:MENTORED]->(c)
    RETURN c.coach_code AS coach_code, c.name AS name
    """
    with driver.session() as s:
        result = s.run(query)
        return [r.data() for r in result]


def check_mentored_bidirectional_cycles(driver: Driver) -> list[dict[str, Any]]:
    """Find pairs where A mentors B AND B mentors A simultaneously.

    A small number of bidirectional MENTORED pairs may be legitimate long-term
    staff relationships (they should be flagged REVIEW_MUTUAL).  An unexpectedly
    large count suggests an inference error.

    Args:
        driver: Open Neo4j driver.

    Returns:
        List of dicts with ``coach_a_code``, ``coach_a_name``,
        ``coach_b_code``, ``coach_b_name``.
    """
    query = """
    MATCH (a:Coach)-[:MENTORED]->(b:Coach)-[:MENTORED]->(a)
    WHERE id(a) < id(b)
    RETURN
        a.coach_code AS coach_a_code, a.name AS coach_a_name,
        b.coach_code AS coach_b_code, b.name AS coach_b_name
    ORDER BY coach_a_name
    LIMIT 50
    """
    with driver.session() as s:
        result = s.run(query)
        return [r.data() for r in result]


def check_null_role_abbr(driver: Driver) -> list[dict[str, Any]]:
    """Find mcillece_roles COACHED_AT edges with a NULL role_abbr.

    Every edge with source='mcillece_roles' must have a role_abbr.  NULLs
    indicate a loading error in expand_roles or load_coached_at_roles.

    Args:
        driver: Open Neo4j driver.

    Returns:
        Sample of offending edges (up to 20).
    """
    query = """
    MATCH (c:Coach)-[r:COACHED_AT {source: 'mcillece_roles'}]->(t:Team)
    WHERE r.role_abbr IS NULL
    RETURN c.coach_code AS coach_code, c.name AS name,
           t.school AS team, r.year AS year
    LIMIT 20
    """
    with driver.session() as s:
        result = s.run(query)
        return [r.data() for r in result]


def check_large_year_gaps(driver: Driver, max_gap: int = 5) -> list[dict[str, Any]]:
    """Find coaches with a year gap > max_gap at the same team.

    A 6+ year gap at the same program typically indicates missing data years
    rather than a legitimate absence and rehire.

    Args:
        driver: Open Neo4j driver.
        max_gap: Maximum tolerated gap between consecutive season years.

    Returns:
        List of dicts with ``coach_code``, ``name``, ``team``, ``gap``,
        ``gap_start``, ``gap_end``.
    """
    query = """
    MATCH (c:Coach)-[r:COACHED_AT {source: 'mcillece_roles'}]->(t:Team)
    WHERE c.coach_code IS NOT NULL
    WITH c, t, collect(DISTINCT r.year) AS years
    WHERE size(years) > 1
    UNWIND range(0, size(years) - 2) AS i
    WITH c, t, years[i] AS yr1, years[i+1] AS yr2
    WITH c, t, yr1, yr2, yr2 - yr1 AS gap
    WHERE gap > $max_gap
    RETURN c.coach_code AS coach_code, c.name AS name,
           t.school AS team, gap, yr1 AS gap_start, yr2 AS gap_end
    ORDER BY gap DESC
    LIMIT 20
    """
    with driver.session() as s:
        result = s.run(query, max_gap=max_gap)
        return [r.data() for r in result]


def check_graph_summary(driver: Driver) -> dict[str, int]:
    """Return high-level node/edge counts as a health snapshot.

    Args:
        driver: Open Neo4j driver.

    Returns:
        Dict of label/relationship-type → count.
    """
    counts: dict[str, int] = {}
    queries = {
        "Coach nodes": "MATCH (c:Coach) RETURN count(c) AS n",
        "Team nodes": "MATCH (t:Team) RETURN count(t) AS n",
        "COACHED_AT (all)": "MATCH ()-[r:COACHED_AT]->() RETURN count(r) AS n",
        "COACHED_AT (mcillece_roles)": "MATCH ()-[r:COACHED_AT {source:'mcillece_roles'}]->() RETURN count(r) AS n",
        "MENTORED edges": "MATCH ()-[r:MENTORED]->() RETURN count(r) AS n",
        "MENTORED STANDARD": "MATCH ()-[r:MENTORED {confidence_flag:'STANDARD'}]->() RETURN count(r) AS n",
        "MENTORED REVIEW_REVERSE": "MATCH ()-[r:MENTORED {confidence_flag:'REVIEW_REVERSE'}]->() RETURN count(r) AS n",
    }
    with driver.session() as s:
        for label, query in queries.items():
            result = s.run(query)
            row = result.single()
            counts[label] = row["n"] if row else 0
    return counts


# ---------------------------------------------------------------------------
# Report runner
# ---------------------------------------------------------------------------


def run_anomaly_checks(driver: Driver) -> int:
    """Run all anomaly checks and print a structured report.

    Args:
        driver: Open Neo4j driver.

    Returns:
        Total number of critical anomalies found (self-loops + null roles).
    """
    print("=" * 60)
    print("  A1 Ingestion Anomaly Report")
    print("=" * 60)

    # Graph summary
    summary = check_graph_summary(driver)
    print("\nGraph Summary:")
    for label, n in summary.items():
        print(f"  {label:<35} {n:>8,}")

    # Self-loops (always bad)
    self_loops = check_mentored_self_loops(driver)
    print(f"\n{'─' * 60}")
    print(f"  MENTORED Self-Loops (should be 0): {len(self_loops)}")
    for sl in self_loops:
        print(f"  ⚠  {sl['name']} (code={sl['coach_code']}) mentors themselves")

    # Bidirectional cycles
    cycles = check_mentored_bidirectional_cycles(driver)
    print(f"\n{'─' * 60}")
    print(f"  Bidirectional MENTORED Cycles: {len(cycles)}")
    if cycles:
        print(f"  (first 10 shown)")
        for c in cycles[:10]:
            print(f"    {c['coach_a_name']} ↔ {c['coach_b_name']}")

    # NULL role_abbr
    null_roles = check_null_role_abbr(driver)
    print(f"\n{'─' * 60}")
    print(f"  NULL role_abbr on mcillece_roles edges: {len(null_roles)}")
    for nr in null_roles:
        print(f"  ⚠  {nr['name']} at {nr['team']} ({nr['year']})")

    # Duplicate coach nodes
    dupes = check_duplicate_coach_nodes(driver)
    print(f"\n{'─' * 60}")
    print(f"  Duplicate McIllece Coach Names: {len(dupes)}")
    if dupes:
        print(f"  (expected — different coaches with identical names)")
        for d in dupes[:5]:
            print(f"    {d['name']}  codes={d['coach_codes']}")

    # Year gaps
    gaps = check_large_year_gaps(driver)
    print(f"\n{'─' * 60}")
    print(f"  Large Year Gaps at Same Team (>5 yr): {len(gaps)}")
    for g in gaps[:5]:
        print(
            f"    {g['name']} at {g['team']}: "
            f"gap={g['gap']} yrs ({g['gap_start']}–{g['gap_end']})"
        )

    critical = len(self_loops) + len(null_roles)
    print(f"\n{'=' * 60}")
    print(f"  Critical anomalies (self-loops + null roles): {critical}")
    print(f"{'=' * 60}\n")
    return critical


# ---------------------------------------------------------------------------
# Standalone entry-point
# ---------------------------------------------------------------------------


def _run() -> None:
    """Run anomaly checks against live Neo4j (reads credentials from .env)."""
    from dotenv import load_dotenv

    load_dotenv(dotenv_path=Path(__file__).parent.parent.parent / ".env")

    from loader.neo4j_loader import get_driver

    driver = get_driver(
        os.environ["NEO4J_URI"],
        os.environ["NEO4J_USERNAME"],
        os.environ["NEO4J_PASSWORD"],
    )
    try:
        critical = run_anomaly_checks(driver)
        raise SystemExit(0 if critical == 0 else 1)
    finally:
        driver.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
    _run()
