"""Diagnose Rule 1 (prior-HC) failures for specific coaches.

For each suspect coach, this script:
1. Shows all mcillece_roles COACHED_AT records (team, year, role_abbr)
2. Shows all MENTORED edges pointing TO them (i.e., someone says they are a mentee)
3. For each such edge, shows the earliest overlap year and whether prior HC years exist

Run from project root:
    python scripts/diagnose_rule1.py
"""

import os
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

URI = os.environ["NEO4J_URI"]
USER = os.environ["NEO4J_USERNAME"]
PASSWORD = os.environ["NEO4J_PASSWORD"]

# Coaches the user flagged as prior-HC cases that survived the rebuild
SUSPECT_NAMES = [
    "Dabo Swinney",
    "Al Groh",
    "George O'Leary",
    "Mike Locksley",
    "Steve Sarkisian",
    "Bobby Petrino",
    "Chris Petersen",
    "Dan Mullen",
    "Bret Bielema",
    "Clay Helton",
]


def run(driver):
    with driver.session() as session:

        # ----------------------------------------------------------------
        # 1. Resolve coach_codes for suspect coaches
        # ----------------------------------------------------------------
        print("=" * 70)
        print("STEP 1 — Resolving coach_codes for suspect coaches")
        print("=" * 70)

        code_map: dict[str, int | None] = {}
        for name in SUSPECT_NAMES:
            parts = name.split(None, 1)
            first, last = parts[0], parts[1] if len(parts) > 1 else ""
            result = session.run(
                """
                MATCH (c:Coach)
                WHERE (c.name = $full OR (c.first_name = $first AND c.last_name = $last))
                  AND c.coach_code IS NOT NULL
                RETURN c.coach_code AS code, c.name AS name
                LIMIT 1
                """,
                full=name, first=first, last=last,
            )
            row = result.single()
            if row:
                code_map[name] = row["code"]
                print(f"  {name:<25} coach_code={row['code']}")
            else:
                code_map[name] = None
                print(f"  {name:<25} NOT FOUND in McIllece nodes")

        # ----------------------------------------------------------------
        # 2. For each found coach, show their mcillece_roles HC records
        # ----------------------------------------------------------------
        print("\n" + "=" * 70)
        print("STEP 2 — HC years in mcillece_roles for each suspect coach")
        print("=" * 70)

        for name, code in code_map.items():
            if code is None:
                print(f"\n  {name}: no McIllece node — skipping")
                continue
            result = session.run(
                """
                MATCH (c:Coach {coach_code: $code})-[r:COACHED_AT]->(t:Team)
                WHERE r.source = 'mcillece_roles' AND r.role_abbr = 'HC'
                RETURN t.school AS team, r.year AS year
                ORDER BY year
                """,
                code=code,
            )
            hc_rows = list(result)
            if hc_rows:
                years = sorted({r["year"] for r in hc_rows})
                teams = sorted({r["team"] for r in hc_rows})
                print(f"\n  {name} (code={code}): HC years={years}, teams={teams}")
            else:
                print(f"\n  {name} (code={code}): NO HC records in mcillece_roles")
                # Also check if they exist at all in mcillece_roles
                result2 = session.run(
                    """
                    MATCH (c:Coach {coach_code: $code})-[r:COACHED_AT]->(t:Team)
                    WHERE r.source = 'mcillece_roles'
                    RETURN DISTINCT r.role_abbr AS role, count(*) AS cnt
                    ORDER BY cnt DESC
                    """,
                    code=code,
                )
                roles = [(r["role"], r["cnt"]) for r in result2]
                print(f"    All mcillece_roles roles: {roles}")

        # ----------------------------------------------------------------
        # 3. For each found coach, show MENTORED edges pointing TO them
        #    and the overlap with their supposed mentor
        # ----------------------------------------------------------------
        print("\n" + "=" * 70)
        print("STEP 3 — MENTORED inbound edges and overlap analysis")
        print("=" * 70)

        for name, code in code_map.items():
            if code is None:
                continue
            result = session.run(
                """
                MATCH (mentor:Coach)-[:MENTORED]->(mentee:Coach {coach_code: $code})
                RETURN mentor.name AS mentor_name, mentor.coach_code AS mentor_code
                """,
                code=code,
            )
            edges = list(result)
            if not edges:
                print(f"\n  {name}: no inbound MENTORED edges (already clean)")
                continue

            print(f"\n  {name} (code={code}): {len(edges)} inbound MENTORED edge(s)")
            for edge in edges:
                mentor_name = edge["mentor_name"]
                mentor_code = edge["mentor_code"]
                print(f"    Mentor: {mentor_name} (code={mentor_code})")

                if mentor_code is None:
                    print(f"      mentor has no coach_code — CFBD-only node")
                    continue

                # Find shared programs and earliest overlap year
                result2 = session.run(
                    """
                    MATCH (mentor:Coach {coach_code: $mc})-[rm:COACHED_AT]->(t:Team)<-[rb:COACHED_AT]-(mentee:Coach {coach_code: $bc})
                    WHERE rm.source = 'mcillece_roles' AND rb.source = 'mcillece_roles'
                    RETURN t.school AS team, rm.year AS mentor_year, rb.year AS mentee_year
                    ORDER BY team, rm.year
                    """,
                    mc=mentor_code,
                    bc=code,
                )
                overlap_rows = list(result2)
                if overlap_rows:
                    by_team = defaultdict(list)
                    for r in overlap_rows:
                        if r["mentor_year"] == r["mentee_year"]:
                            by_team[r["team"]].append(r["mentor_year"])
                    for team, years in sorted(by_team.items()):
                        overlap_start = min(years)
                        print(f"      Overlap at {team}: years={sorted(set(years))}, overlap_start={overlap_start}")

                        # Show suspect coach's HC years before overlap_start
                        result3 = session.run(
                            """
                            MATCH (c:Coach {coach_code: $code})-[r:COACHED_AT]->(t:Team)
                            WHERE r.source = 'mcillece_roles' AND r.role_abbr = 'HC'
                              AND r.year < $start
                            RETURN t.school AS hc_team, r.year AS hc_year
                            ORDER BY r.year
                            """,
                            code=code,
                            start=overlap_start,
                        )
                        prior_hc = list(result3)
                        if prior_hc:
                            print(f"      Prior HC years (< {overlap_start}): "
                                  f"{[(r['hc_year'], r['hc_team']) for r in prior_hc]}")
                            print(f"      → Rule 1 SHOULD have fired ← BUG")
                        else:
                            print(f"      Prior HC years (< {overlap_start}): none")
                            print(f"      → Rule 1 correctly did not fire (no prior HC)")
                else:
                    print(f"      No shared mcillece_roles programs found")

        # ----------------------------------------------------------------
        # 4. Summary: current MENTORED count
        # ----------------------------------------------------------------
        print("\n" + "=" * 70)
        result = session.run("MATCH ()-[r:MENTORED]->() RETURN count(r) AS n")
        print(f"Total MENTORED edges in graph: {result.single()['n']}")


def main():
    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    try:
        run(driver)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
