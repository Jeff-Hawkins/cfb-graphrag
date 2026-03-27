"""A1 Data Validation Agent — validate.py.

Checks Neo4j graph data against ground_truth.yaml and flags structural anomalies:

1. Ground-truth tenure checks: verifies known COACHED_AT edges exist with expected
   role/year ranges.
2. Ground-truth MENTORED checks: verifies expected MENTORED edges are present and
   expected non-edges are absent.
3. Structural anomaly: flags coaches with <2 or >25 COACHED_AT edges (suspicious
   data sparsity or duplication).
4. MENTORED overlap sanity: flags MENTORED edges where the McIllece-sourced
   COACHED_AT overlap is <2 seasons.

Usage::

    python -m agents.data_validation.validate
    python agents/data_validation/validate.py

Output: prints a structured validation report to stdout.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml
from neo4j import Driver

logger = logging.getLogger(__name__)

_HERE = Path(__file__).parent
_GROUND_TRUTH_PATH = _HERE / "ground_truth.yaml"


# ---------------------------------------------------------------------------
# Ground-truth helpers
# ---------------------------------------------------------------------------


def _load_ground_truth() -> dict[str, list[dict[str, Any]]]:
    """Load and return ground_truth.yaml as a dict.

    Returns:
        Dict with keys ``tenures``, ``mentored``, ``not_mentored``.
    """
    with open(_GROUND_TRUTH_PATH, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return {
        "tenures": data.get("tenures", []),
        "mentored": data.get("mentored", []),
        "not_mentored": data.get("not_mentored", []),
    }


def check_tenure(driver: Driver, entry: dict[str, Any]) -> dict[str, Any]:
    """Check that a known coaching tenure exists in the graph.

    Matches by coach name (case-insensitive contains on Coach.name or
    Coach.first_name/last_name), team school, and year range.

    Args:
        driver: Open Neo4j driver.
        entry: Tenure entry dict from ground_truth.yaml.

    Returns:
        Result dict with keys ``ok`` (bool), ``entry``, and ``detail`` (str).
    """
    coach_name = entry["coach"]
    team = entry["team"]
    start_year = entry.get("start_year")
    end_year = entry.get("end_year")
    role = entry.get("role")

    name_tokens = coach_name.strip().split()
    name_conditions = " AND ".join(
        f"(toLower(coalesce(c.name,'')) CONTAINS toLower($tok{i}) "
        f"OR toLower(coalesce(c.first_name,'') + ' ' + coalesce(c.last_name,'')) CONTAINS toLower($tok{i}))"
        for i in range(len(name_tokens))
    )
    params: dict[str, Any] = {f"tok{i}": tok for i, tok in enumerate(name_tokens)}
    params["team"] = team

    role_filter = "AND r.role_abbr = $role " if role else ""
    if role:
        params["role"] = role

    year_filter = ""
    if start_year and end_year:
        year_filter = "AND r.year >= $start_year AND r.year <= $end_year "
        params["start_year"] = start_year
        params["end_year"] = end_year

    query = f"""
    MATCH (c:Coach)-[r:COACHED_AT {{source: 'mcillece_roles'}}]->(t:Team {{school: $team}})
    WHERE {name_conditions}
    {role_filter}
    {year_filter}
    RETURN count(r) AS n, collect(DISTINCT r.year)[..5] AS sample_years
    """

    with driver.session() as s:
        result = s.run(query, **params)
        row = result.single()

    n = row["n"] if row else 0
    if n > 0:
        return {"ok": True, "entry": entry, "detail": f"Found {n} matching COACHED_AT edges."}
    return {
        "ok": False,
        "entry": entry,
        "detail": f"No COACHED_AT edges found for {coach_name} at {team} "
                  f"(role={role or 'any'}, years={start_year}-{end_year}).",
    }


def check_mentored(driver: Driver, entry: dict[str, Any], *, expect_edge: bool) -> dict[str, Any]:
    """Check whether a MENTORED edge exists (or does not exist) between two coaches.

    Args:
        driver: Open Neo4j driver.
        entry: MENTORED entry dict from ground_truth.yaml.
        expect_edge: True if the edge should exist, False if it should be absent.

    Returns:
        Result dict with ``ok``, ``entry``, ``detail``.
    """
    mentor_name = entry["mentor"]
    mentee_name = entry["mentee"]

    def _name_clause(prefix: str, name: str, params: dict) -> str:
        tokens = name.strip().split()
        conditions = " AND ".join(
            f"(toLower(coalesce({prefix}.name,'')) CONTAINS toLower(${prefix}_tok{i}) "
            f"OR toLower(coalesce({prefix}.first_name,'') + ' ' + coalesce({prefix}.last_name,'')) CONTAINS toLower(${prefix}_tok{i}))"
            for i in range(len(tokens))
        )
        for i, tok in enumerate(tokens):
            params[f"{prefix}_tok{i}"] = tok
        return conditions

    params: dict[str, Any] = {}
    mentor_clause = _name_clause("mentor", mentor_name, params)
    mentee_clause = _name_clause("mentee", mentee_name, params)

    query = f"""
    MATCH (mentor:Coach)-[m:MENTORED]->(mentee:Coach)
    WHERE {mentor_clause} AND {mentee_clause}
    RETURN count(m) AS n, m.confidence_flag AS flag
    LIMIT 1
    """

    with driver.session() as s:
        result = s.run(query, **params)
        row = result.single()

    n = row["n"] if row else 0
    edge_present = n > 0

    if expect_edge and edge_present:
        flag = row["flag"] if row else "unknown"
        return {"ok": True, "entry": entry, "detail": f"Edge present (confidence_flag={flag})."}
    if expect_edge and not edge_present:
        return {
            "ok": False,
            "entry": entry,
            "detail": f"Expected MENTORED edge {mentor_name} → {mentee_name} is MISSING.",
        }
    if not expect_edge and not edge_present:
        return {"ok": True, "entry": entry, "detail": "Edge correctly absent."}
    # not expect_edge and edge_present
    return {
        "ok": False,
        "entry": entry,
        "detail": f"MENTORED edge {mentor_name} → {mentee_name} should NOT exist (prior HC rule).",
    }


# ---------------------------------------------------------------------------
# Structural anomaly checks
# ---------------------------------------------------------------------------


def check_coached_at_edge_counts(driver: Driver) -> list[dict[str, Any]]:
    """Flag McIllece coaches with <2 or >25 COACHED_AT edges.

    Very low counts suggest an incomplete import; very high counts may indicate
    a duplicate coach node or runaway MERGE.

    Args:
        driver: Open Neo4j driver.

    Returns:
        List of anomaly dicts with keys ``coach_code``, ``name``, ``edge_count``,
        ``type`` (``"sparse"`` or ``"dense"``).
    """
    query = """
    MATCH (c:Coach)-[r:COACHED_AT {source: 'mcillece_roles'}]->(t:Team)
    WHERE c.coach_code IS NOT NULL
    WITH c, count(r) AS n
    WHERE n < 2 OR n > 25
    RETURN c.coach_code AS coach_code, c.name AS name, n AS edge_count
    ORDER BY n
    """
    with driver.session() as s:
        result = s.run(query)
        rows = [r.data() for r in result]

    anomalies = []
    for row in rows:
        atype = "sparse" if row["edge_count"] < 2 else "dense"
        anomalies.append({
            "coach_code": row["coach_code"],
            "name": row["name"],
            "edge_count": row["edge_count"],
            "type": atype,
        })
    return anomalies


def check_mentored_overlap_sanity(driver: Driver, min_overlap: int = 2) -> list[dict[str, Any]]:
    """Flag MENTORED edges where the McIllece-sourced overlap is <min_overlap seasons.

    These may have slipped through if the inference ran against non-mcillece_roles
    COACHED_AT edges.

    Args:
        driver: Open Neo4j driver.
        min_overlap: Minimum expected overlap (default 2).

    Returns:
        List of suspicious edge dicts.
    """
    query = """
    MATCH (mentor:Coach)-[:MENTORED]->(mentee:Coach)
    WHERE mentor.coach_code IS NOT NULL AND mentee.coach_code IS NOT NULL
    MATCH (mentor)-[r1:COACHED_AT {source: 'mcillece_roles'}]->(t:Team)
    MATCH (mentee)-[r2:COACHED_AT {source: 'mcillece_roles'}]->(t)
    WHERE r1.year = r2.year
    WITH mentor, mentee, count(DISTINCT r1.year) AS shared_years
    WHERE shared_years < $min_overlap
    RETURN
        mentor.coach_code AS mentor_code,
        mentor.name       AS mentor_name,
        mentee.coach_code AS mentee_code,
        mentee.name       AS mentee_name,
        shared_years
    ORDER BY shared_years, mentor_name
    LIMIT 100
    """
    with driver.session() as s:
        result = s.run(query, min_overlap=min_overlap)
        return [r.data() for r in result]


# ---------------------------------------------------------------------------
# Report printer
# ---------------------------------------------------------------------------


def _print_section(title: str, items: list[dict[str, Any]], ok_key: str = "ok") -> int:
    """Print a labelled section of check results.  Returns failure count."""
    failures = [x for x in items if not x.get(ok_key, True)]
    passes = len(items) - len(failures)
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"  PASS: {passes}  |  FAIL: {len(failures)}")
    print(f"{'─' * 60}")
    for item in items:
        ok = item.get(ok_key, True)
        prefix = "  ✓" if ok else "  ✗"
        entry = item.get("entry", {})
        label = (
            f"{entry.get('coach', entry.get('mentor', '?'))} "
            f"@ {entry.get('team', entry.get('mentee', '?'))}"
        )
        print(f"{prefix}  {label:<45}  {item.get('detail', '')}")
    return len(failures)


def run_validation(driver: Driver) -> int:
    """Run all validation checks and print a structured report.

    Args:
        driver: Open Neo4j driver.

    Returns:
        Total failure count across all checks.
    """
    ground_truth = _load_ground_truth()
    total_failures = 0

    print("=" * 60)
    print("  A1 Data Validation Report")
    print("=" * 60)

    # 1. Tenure checks
    tenure_results = [check_tenure(driver, e) for e in ground_truth["tenures"]]
    total_failures += _print_section("Tenure Checks", tenure_results)

    # 2. Mentored edge checks (expect present)
    mentored_results = [check_mentored(driver, e, expect_edge=True) for e in ground_truth["mentored"]]
    total_failures += _print_section("Expected MENTORED Edges", mentored_results)

    # 3. Not-mentored edge checks (expect absent)
    not_mentored_results = [check_mentored(driver, e, expect_edge=False) for e in ground_truth["not_mentored"]]
    total_failures += _print_section("Expected Absent MENTORED Edges", not_mentored_results)

    # 4. Structural: coached_at count anomalies
    anomalies = check_coached_at_edge_counts(driver)
    sparse = [a for a in anomalies if a["type"] == "sparse"]
    dense = [a for a in anomalies if a["type"] == "dense"]
    print(f"\n{'─' * 60}")
    print(f"  Structural: COACHED_AT Edge Count Anomalies")
    print(f"  Sparse (<2 edges): {len(sparse)}  |  Dense (>25 edges): {len(dense)}")
    print(f"{'─' * 60}")
    if sparse:
        print(f"  Sparse coaches (first 10):")
        for a in sparse[:10]:
            print(f"    coach_code={a['coach_code']}  name={a['name']}  edges={a['edge_count']}")
    if dense:
        print(f"  Dense coaches (first 10):")
        for a in dense[:10]:
            print(f"    coach_code={a['coach_code']}  name={a['name']}  edges={a['edge_count']}")

    # 5. MENTORED overlap sanity
    overlap_issues = check_mentored_overlap_sanity(driver)
    print(f"\n{'─' * 60}")
    print(f"  MENTORED Overlap Sanity (<2 shared seasons)")
    print(f"  Issues found: {len(overlap_issues)}")
    print(f"{'─' * 60}")
    if overlap_issues:
        for issue in overlap_issues[:10]:
            print(
                f"  mentor={issue['mentor_name']} → mentee={issue['mentee_name']}  "
                f"shared_years={issue['shared_years']}"
            )
        if len(overlap_issues) > 10:
            print(f"  ... and {len(overlap_issues) - 10} more")

    print(f"\n{'=' * 60}")
    print(f"  Total ground-truth failures: {total_failures}")
    print(f"  Structural anomalies (coached_at): {len(anomalies)}")
    print(f"  MENTORED overlap issues: {len(overlap_issues)}")
    print(f"{'=' * 60}\n")

    return total_failures


# ---------------------------------------------------------------------------
# Standalone entry-point
# ---------------------------------------------------------------------------


def _run() -> None:
    """Run validation against live Neo4j (reads credentials from .env)."""
    from dotenv import load_dotenv

    load_dotenv(dotenv_path=Path(__file__).parent.parent.parent / ".env")

    from loader.neo4j_loader import get_driver

    driver = get_driver(
        os.environ["NEO4J_URI"],
        os.environ["NEO4J_USERNAME"],
        os.environ["NEO4J_PASSWORD"],
    )
    try:
        failures = run_validation(driver)
        raise SystemExit(0 if failures == 0 else 1)
    finally:
        driver.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
    _run()
