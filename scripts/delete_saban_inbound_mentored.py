"""Task 0 — Audit and delete inbound MENTORED edges pointing at Nick Saban (coach_code=1457).

Run from project root:
    python scripts/delete_saban_inbound_mentored.py
"""

import os
import sys

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

URI = os.environ["NEO4J_URI"]
USER = os.environ["NEO4J_USERNAME"]
PASSWORD = os.environ["NEO4J_PASSWORD"]

SABAN_CODE = 1457


def run(driver):
    with driver.session() as session:

        # --- Step 1: bidirectional cycle check ---
        print("=== Step 1: Bidirectional cycle check (any coach X where X→Saban and Saban→X) ===")
        result = session.run(
            """
            MATCH (a:Coach {coach_code: $code})<-[r:MENTORED]-(b:Coach)-[:MENTORED]->(a)
            RETURN b.name AS name, b.coach_code AS coach_code, type(r) AS rel_type
            """,
            code=SABAN_CODE,
        )
        rows = list(result)
        if rows:
            for row in rows:
                print(f"  CYCLE: {row['name']} (coach_code={row['coach_code']}) ← {row['rel_type']} → Saban AND Saban → them")
        else:
            print("  (none found)")

        # --- Step 2: all coaches with MENTORED → Saban ---
        print("\n=== Step 2: All inbound MENTORED edges to Saban (coach_code=1457) ===")
        result = session.run(
            """
            MATCH (x:Coach)-[r:MENTORED]->(saban:Coach {coach_code: $code})
            RETURN x.name AS name, x.coach_code AS coach_code
            """,
            code=SABAN_CODE,
        )
        inbound = list(result)
        if inbound:
            for row in inbound:
                print(f"  {row['name']} (coach_code={row['coach_code']}) -[MENTORED]-> Saban  ← SUSPECT")
        else:
            print("  (none found — no deletion needed)")
            return

        # --- Step 3: confirm before deleting ---
        print(f"\n  {len(inbound)} inbound edge(s) found. Deleting...")
        result = session.run(
            """
            MATCH (x:Coach)-[r:MENTORED]->(saban:Coach {coach_code: $code})
            DELETE r
            """,
            code=SABAN_CODE,
        )
        summary = result.consume()
        print(f"  Deleted {summary.counters.relationships_deleted} relationship(s).")

        # --- Step 4: confirm zero remain ---
        print("\n=== Step 4: Confirm zero inbound MENTORED edges remain ===")
        result = session.run(
            """
            MATCH (x:Coach)-[r:MENTORED]->(saban:Coach {coach_code: $code})
            RETURN count(r) AS remaining
            """,
            code=SABAN_CODE,
        )
        row = result.single()
        remaining = row["remaining"] if row else 0
        print(f"  Inbound MENTORED edges remaining: {remaining}")
        if remaining == 0:
            print("  OK — Saban has no inbound MENTORED edges.")
        else:
            print("  ERROR — edges still present after deletion!", file=sys.stderr)
            sys.exit(1)

        # --- Step 5: total MENTORED count sanity check ---
        print("\n=== Step 5: Total MENTORED edge count (sanity) ===")
        result = session.run("MATCH ()-[r:MENTORED]->() RETURN count(r) AS total")
        row = result.single()
        print(f"  Total MENTORED edges in graph: {row['total']}")


def main():
    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    try:
        run(driver)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
