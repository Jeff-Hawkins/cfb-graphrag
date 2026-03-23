"""Load SAME_PERSON edges into Neo4j from coach_identity_matches.csv.

Reads data/audits/coach_identity_matches.csv and MERGEs
  (cfbd_node)-[:SAME_PERSON {match_type, confidence}]->(mc_node)
for exact matches only on first run (match_type == "exact").

Idempotent — safe to run multiple times.
"""

import csv
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from neo4j import Driver, GraphDatabase

load_dotenv()

logger = logging.getLogger(__name__)

DEFAULT_CSV = (
    Path(__file__).resolve().parent.parent / "data" / "audits" / "coach_identity_matches.csv"
)


def load_identity_edges(
    driver: Driver,
    csv_path: Path = DEFAULT_CSV,
    exact_only: bool = True,
) -> int:
    """MERGE SAME_PERSON edges from a match CSV into Neo4j.

    Args:
        driver:     Open Neo4j driver.
        csv_path:   Path to coach_identity_matches.csv.
        exact_only: If True, only load rows where match_type == "exact".
                    Set to False to also load fuzzy rows after manual review.

    Returns:
        Number of SAME_PERSON edges created or confirmed.
    """
    if not csv_path.exists():
        raise FileNotFoundError(
            f"Match CSV not found at {csv_path}. "
            "Run ingestion/match_coach_identity.py first."
        )

    rows: list[dict] = []
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if exact_only and row["match_type"] != "exact":
                continue
            rows.append(row)

    if not rows:
        print("No rows to load (check exact_only flag and CSV contents).")
        return 0

    query = """
    UNWIND $rows AS row
    MATCH (cfbd:Coach) WHERE elementId(cfbd) = row.cfbd_id
    MATCH (mc:Coach)   WHERE elementId(mc) = row.mc_id
    MERGE (cfbd)-[r:SAME_PERSON]->(mc)
    SET r.match_type  = row.match_type,
        r.confidence  = toFloat(row.confidence)
    RETURN count(r) AS merged
    """

    with driver.session() as session:
        result = session.run(query, rows=rows)
        record = result.single()
        count = record["merged"] if record else 0

    filter_desc = "exact" if exact_only else "all"
    print(
        f"SAME_PERSON edges loaded ({filter_desc} matches): {count} "
        f"(from {len(rows)} CSV rows)"
    )
    return count


def verify_edges(driver: Driver) -> None:
    """Print verification queries to confirm SAME_PERSON edges loaded correctly.

    Args:
        driver: Open Neo4j driver.
    """
    with driver.session() as session:
        # 1. Total SAME_PERSON edges
        r = session.run("MATCH ()-[r:SAME_PERSON]->() RETURN count(r) AS total")
        total = r.single()["total"]
        print(f"\n[Verify] Total SAME_PERSON edges: {total}")

        # 2. Nick Saban resolved (CFBD first_name/last_name → McIllece coach_code 1457)
        r = session.run(
            """
            MATCH (cfbd:Coach {first_name: "Nick", last_name: "Saban"})
                  -[:SAME_PERSON]->(mc:Coach {coach_code: 1457})
            RETURN cfbd.first_name + ' ' + cfbd.last_name AS cfbd_name,
                   mc.coach_code AS mc_code
            """
        )
        saban = r.single()
        if saban:
            print(
                f"[Verify] Nick Saban resolved: "
                f"CFBD '{saban['cfbd_name']}' → McIllece code {saban['mc_code']}"
            )
        else:
            print("[Verify] WARNING: Nick Saban SAME_PERSON edge not found!")

        # 3. Kirby Smart resolved
        r = session.run(
            """
            MATCH (cfbd:Coach {first_name: "Kirby", last_name: "Smart"})
                  -[:SAME_PERSON]->(mc:Coach)
            RETURN cfbd.first_name + ' ' + cfbd.last_name AS cfbd_name,
                   mc.coach_code AS mc_code
            """
        )
        smart = r.single()
        if smart:
            print(
                f"[Verify] Kirby Smart resolved: "
                f"CFBD '{smart['cfbd_name']}' → McIllece code {smart['mc_code']}"
            )
        else:
            print("[Verify] WARNING: Kirby Smart SAME_PERSON edge not found!")


def run(
    driver: Driver | None = None,
    csv_path: Path = DEFAULT_CSV,
    exact_only: bool = True,
) -> int:
    """Main entry point: load SAME_PERSON edges and verify.

    Args:
        driver:     Optional open Neo4j driver (created from env if None).
        csv_path:   Path to match CSV.
        exact_only: Only load exact matches on first run.

    Returns:
        Number of edges loaded.
    """
    if driver is None:
        driver = GraphDatabase.driver(
            os.environ["NEO4J_URI"],
            auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
        )

    count = load_identity_edges(driver, csv_path=csv_path, exact_only=exact_only)
    verify_edges(driver)
    return count


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
