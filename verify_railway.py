"""Verify Railway Neo4j import matches AuraDB source counts.

Runs node count, relationship count, and spot-check queries against
the Railway Neo4j instance and prints a pass/fail summary.

Usage:
    python verify_railway.py

Requires in .env:
    RAILWAY_NEO4J_URI
    RAILWAY_NEO4J_USER
    RAILWAY_NEO4J_PASSWORD

Expected counts (from AuraDB export 2026-03-22):
    Nodes:  Player=97,765  Team=1,902  Coach=6,002  Conference=74
    Rels:   PLAYED_FOR=231,540  COACHED_AT=77,813  PLAYED=26,918
            IN_CONFERENCE=702   MENTORED=163
    Total:  337,136 relationships
"""

from __future__ import annotations

import logging
from typing import Any
import os
import sys

from dotenv import load_dotenv
from neo4j import Driver

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Expected counts — update if AuraDB state changes before migration
# ---------------------------------------------------------------------------

EXPECTED_NODES: dict[str, int] = {
    "Player":     97_765,
    "Team":        1_902,  # 1,862 FBS/FCS unique schools + 40 duplicate non-FBS entries
    "Coach":       6_002,  # 4,216 CFBD + 1,786 McIllece-only coaches
    "Conference":     74,
}

EXPECTED_RELS: dict[str, int] = {
    "PLAYED_FOR":    231_540,
    "COACHED_AT":     77_813,  # 12,414 CFBD + 26,368 mcillece + 39,031 mcillece_roles
    "PLAYED":         26_918,
    "IN_CONFERENCE":     702,
    "MENTORED":          163,
}


# ---------------------------------------------------------------------------
# Verification queries
# ---------------------------------------------------------------------------


def check_node_counts(driver: Driver) -> dict[str, int]:
    """Return actual node counts per label.

    Args:
        driver: Open Neo4j driver.

    Returns:
        ``{label: count}`` dict.
    """
    with driver.session() as session:
        result = session.run(
            "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS cnt"
        )
        return {r["label"]: r["cnt"] for r in result}


def check_rel_counts(driver: Driver) -> dict[str, int]:
    """Return actual relationship counts per type.

    Args:
        driver: Open Neo4j driver.

    Returns:
        ``{rel_type: count}`` dict.
    """
    with driver.session() as session:
        result = session.run(
            "MATCH ()-[r]->() RETURN type(r) AS rel_type, count(r) AS cnt"
        )
        return {r["rel_type"]: r["cnt"] for r in result}


def spot_check_saban(driver: Driver) -> list[dict]:
    """Return Nick Saban COACHED_AT records for spot-checking.

    Args:
        driver: Open Neo4j driver.

    Returns:
        List of record dicts with name, school, year, role/title.
    """
    with driver.session() as session:
        result = session.run(
            """
            MATCH (c:Coach {first_name: 'Nick', last_name: 'Saban'})-[r:COACHED_AT]->(t:Team)
            RETURN c.first_name + ' ' + c.last_name AS name,
                   t.school  AS school,
                   r.year    AS year,
                   coalesce(r.title, r.role) AS role
            ORDER BY r.year
            """
        )
        return [dict(r) for r in result]


def spot_check_alabama_2015(driver: Driver) -> list[dict]:
    """Return Alabama 2015 staff for spot-checking coordinator presence.

    Args:
        driver: Open Neo4j driver.

    Returns:
        List of record dicts with coach name, role, role_tier.
    """
    with driver.session() as session:
        result = session.run(
            """
            MATCH (c:Coach)-[r:COACHED_AT]->(t:Team)
            WHERE t.school = 'Alabama' AND r.year = 2015
            RETURN c.first_name + ' ' + coalesce(c.last_name, '') AS name,
                   coalesce(r.role, r.title) AS role,
                   r.role_tier AS role_tier
            ORDER BY r.role_tier, name
            """
        )
        return [dict(r) for r in result]


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run_verification(driver: Driver) -> dict[str, Any]:
    """Run all verification checks and return a results dict.

    Args:
        driver: Open Neo4j driver pointing at Railway.

    Returns:
        Dict with keys ``nodes``, ``rels``, ``saban``, ``alabama_2015``,
        ``passed`` (bool), ``failures`` (list of str).
    """
    node_counts = check_node_counts(driver)
    rel_counts = check_rel_counts(driver)
    saban = spot_check_saban(driver)
    alabama_2015 = spot_check_alabama_2015(driver)

    failures: list[str] = []

    # Node count checks
    for label, expected in EXPECTED_NODES.items():
        actual = node_counts.get(label, 0)
        if actual != expected:
            failures.append(
                f"FAIL nodes {label}: expected {expected:,}, got {actual:,}"
            )

    # Relationship count checks
    for rel_type, expected in EXPECTED_RELS.items():
        actual = rel_counts.get(rel_type, 0)
        if actual != expected:
            failures.append(
                f"FAIL rels  {rel_type}: expected {expected:,}, got {actual:,}"
            )

    # Saban spot-check: must have at least one record
    if not saban:
        failures.append("FAIL spot-check: Nick Saban has no COACHED_AT records")

    return {
        "nodes":        node_counts,
        "rels":         rel_counts,
        "saban":        saban,
        "alabama_2015": alabama_2015,
        "passed":       len(failures) == 0,
        "failures":     failures,
    }


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run verification against the Railway Neo4j instance."""
    uri = os.environ.get("RAILWAY_NEO4J_URI", "")
    user = os.environ.get("RAILWAY_NEO4J_USER", "")
    password = os.environ.get("RAILWAY_NEO4J_PASSWORD", "")
    if not all([uri, user, password]):
        raise EnvironmentError(
            "RAILWAY_NEO4J_URI, RAILWAY_NEO4J_USER, and RAILWAY_NEO4J_PASSWORD "
            "must be set in .env"
        )

    from loader.neo4j_loader import get_driver

    driver = get_driver(uri, user, password)
    try:
        results = run_verification(driver)
    finally:
        driver.close()

    # ── Node counts ───────────────────────────────────────────────────────
    print("\n=== Node Counts ===")
    for label, expected in EXPECTED_NODES.items():
        actual = results["nodes"].get(label, 0)
        status = "PASS" if actual == expected else "FAIL"
        print(f"  [{status}] {label:<15} expected={expected:>8,}  actual={actual:>8,}")

    # ── Relationship counts ───────────────────────────────────────────────
    print("\n=== Relationship Counts ===")
    for rel_type, expected in EXPECTED_RELS.items():
        actual = results["rels"].get(rel_type, 0)
        status = "PASS" if actual == expected else "FAIL"
        print(f"  [{status}] {rel_type:<20} expected={expected:>8,}  actual={actual:>8,}")

    # ── Saban spot-check ─────────────────────────────────────────────────
    print("\n=== Spot-check: Nick Saban COACHED_AT ===")
    for row in results["saban"][:10]:
        print(f"  {row.get('name') or '':<25} {row.get('school') or '':<20} {row.get('year') or ''}  {row.get('role') or ''}")
    if not results["saban"]:
        print("  [FAIL] No records found!")

    # ── Alabama 2015 spot-check ───────────────────────────────────────────
    print("\n=== Spot-check: Alabama 2015 staff ===")
    for row in results["alabama_2015"][:10]:
        print(
            f"  {row.get('name') or '':<30} "
            f"role={row.get('role') or '':<25} "
            f"tier={row.get('role_tier') or ''}"
        )
    if not results["alabama_2015"]:
        print("  [WARN] No per-role records found (mcillece_roles may not be loaded yet)")

    # ── Final verdict ─────────────────────────────────────────────────────
    print("\n=== Verification Result ===")
    if results["passed"]:
        print("  ALL CHECKS PASSED — Railway Neo4j matches AuraDB counts exactly.")
    else:
        print("  FAILURES DETECTED:")
        for f in results["failures"]:
            print(f"    {f}")
        sys.exit(1)


if __name__ == "__main__":
    main()
