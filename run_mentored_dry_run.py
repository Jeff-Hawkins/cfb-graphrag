"""Dry run: count projected MENTORED edges from McIllece data in Neo4j.

Reads only COACHED_AT edges with source='mcillece_roles'.
Does NOT write anything to Neo4j.
Saves the full projected edge list to data/audits/mentored_dry_run.csv.

Usage:
    python run_mentored_dry_run.py
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root before importing any loader modules.
load_dotenv(dotenv_path=Path(__file__).parent / ".env")
sys.path.insert(0, str(Path(__file__).parent))

from ingestion.build_mentored_edges import (
    compute_dry_run_stats,
    fetch_coached_at_mcillece_roles,
    infer_mentored_edges_v2,
    save_dry_run_csv,
)
from loader.neo4j_loader import get_driver

_OUT_PATH = Path(__file__).parent / "data" / "audits" / "mentored_dry_run.csv"


def main() -> None:
    """Fetch McIllece role edges, infer MENTORED pairs, print stats, save CSV."""
    driver = get_driver(
        os.environ["NEO4J_URI"],
        os.environ["NEO4J_USERNAME"],
        os.environ["NEO4J_PASSWORD"],
    )
    try:
        print("Fetching COACHED_AT records (source='mcillece_roles') from Neo4j …")
        records = fetch_coached_at_mcillece_roles(driver)
        print(f"  {len(records):,} role-season records fetched")

        print("\nInferring MENTORED edges (COORDINATOR mentor, 2+ consecutive yrs) …")
        edges = infer_mentored_edges_v2(records)
        print(f"  {len(edges):,} projected MENTORED edges")

        stats = compute_dry_run_stats(edges)

        print("\n" + "=" * 52)
        print("  MENTORED Dry Run — Summary")
        print("=" * 52)

        print(f"\nTotal projected MENTORED edges: {stats['total']:,}")

        print("\nBy overlap length:")
        for bucket in ("2yr", "3yr", "4yr", "5yr+"):
            count = stats["by_overlap"].get(bucket, 0)
            print(f"  {bucket:<6} {count:>6,}")

        print("\nBy mentor role tier:")
        for role, count in sorted(
            stats["by_mentor_role"].items(), key=lambda x: -x[1]
        ):
            print(f"  {role:<6} {count:>6,}")

        print("\nTop 10 coaches by mentee count (most connected mentors):")
        for (code, name), mentees in stats["top_mentors"]:
            print(f"  {name:<35}  code={code:<6}  mentees={len(mentees)}")

        print("\nTop 10 coaches by mentor count (most mentored by others):")
        for (code, name), mentors in stats["top_mentees"]:
            print(f"  {name:<35}  code={code:<6}  mentors={len(mentors)}")

        save_dry_run_csv(edges, _OUT_PATH)
        print(f"\nSaved: {_OUT_PATH}  ({len(edges):,} rows)")

    finally:
        driver.close()


if __name__ == "__main__":
    main()
