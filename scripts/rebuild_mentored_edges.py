"""Rebuild MENTORED edges in Neo4j from McIllece role data.

Steps:
1. Delete all existing MENTORED edges (clean slate — aborts if delete fails).
2. Fetch COACHED_AT records (source='mcillece_roles') from Neo4j.
3. Infer edges via infer_mentored_edges_v2() — same-unit filter active.
4. Load via load_mentored_edges_mcillece().
5. Print and return final edge count.

Expected post-load count: 14,403 (validated dry run 2026-03-24).

Usage:
    python scripts/rebuild_mentored_edges.py
"""

import logging
import os
import sys
from pathlib import Path

# Ensure project root is on sys.path so imports work from scripts/.
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

from ingestion.build_mentored_edges import (
    fetch_coached_at_mcillece_roles,
    infer_mentored_edges_v2,
)
from loader.load_mentored_edges import load_mentored_edges_mcillece
from loader.neo4j_loader import get_driver

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

_EXPECTED_COUNT = 14_219


def delete_all_mentored(driver) -> int:
    """Delete all MENTORED edges from Neo4j.

    Uses batched deletes (10,000 at a time) to avoid memory pressure on
    large graphs.  Returns the total number of edges deleted.

    Args:
        driver: Open Neo4j driver.

    Returns:
        Total number of MENTORED edges deleted.

    Raises:
        RuntimeError: If the deletion query fails.
    """
    total_deleted = 0
    batch_size = 10_000
    while True:
        with driver.session() as session:
            result = session.run(
                f"MATCH ()-[r:MENTORED]->() "
                f"WITH r LIMIT {batch_size} "
                f"DELETE r "
                f"RETURN count(*) AS deleted"
            )
            deleted: int = result.single()["deleted"]
        total_deleted += deleted
        logger.info("  Deleted %d MENTORED edges (cumulative: %d) …", deleted, total_deleted)
        if deleted < batch_size:
            break
    return total_deleted


def verify_count(driver) -> int:
    """Query the current MENTORED edge count in Neo4j.

    Args:
        driver: Open Neo4j driver.

    Returns:
        Total number of MENTORED edges in the graph.
    """
    with driver.session() as session:
        result = session.run("MATCH ()-[r:MENTORED]->() RETURN count(r) AS total")
        return result.single()["total"]


def main() -> None:
    """Run the full MENTORED edge rebuild pipeline."""
    uri = os.environ.get("NEO4J_URI", "")
    username = os.environ.get("NEO4J_USERNAME", "")
    password = os.environ.get("NEO4J_PASSWORD", "")
    if not all([uri, username, password]):
        logger.error("NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD must be set in .env")
        sys.exit(1)

    driver = get_driver(uri, username, password)
    try:
        # ── Step 1: Delete all existing MENTORED edges ────────────────────
        print("\n[1/4] Deleting all existing MENTORED edges …")
        pre_count = verify_count(driver)
        print(f"  Pre-delete count: {pre_count:,}")
        try:
            deleted = delete_all_mentored(driver)
        except Exception as exc:
            logger.error("Delete step failed: %s", exc)
            print("\nABORTED — pre-load delete failed. No edges were loaded.")
            sys.exit(1)

        post_delete_count = verify_count(driver)
        if post_delete_count != 0:
            logger.error(
                "Delete incomplete — %d MENTORED edges still present.", post_delete_count
            )
            print("\nABORTED — delete did not reach zero. No edges were loaded.")
            sys.exit(1)

        print(f"  Deleted {deleted:,} edges. Graph now has 0 MENTORED edges. ✓")

        # ── Step 2: Fetch McIllece role records ───────────────────────────
        print("\n[2/4] Fetching COACHED_AT records (source='mcillece_roles') …")
        records = fetch_coached_at_mcillece_roles(driver)
        print(f"  {len(records):,} role-season records fetched")

        # ── Step 3: Infer edges (same-unit filter active) ─────────────────
        print("\n[3/4] Inferring MENTORED edges (infer_mentored_edges_v2) …")
        suppressed: list[dict] = []
        edges = infer_mentored_edges_v2(records, _suppressed_unit_edges=suppressed)
        before_filter = len(edges) + len(suppressed)
        print(f"  {before_filter:,} candidates before same-unit filter")
        print(f"  {len(suppressed):,} suppressed by same-unit filter")
        print(f"  {len(edges):,} edges inferred after filter")

        # ── Step 4: Load edges into Neo4j ─────────────────────────────────
        print("\n[4/4] Loading MENTORED edges into Neo4j …")
        # Convert v2 edge dicts → (mentor_dict, mentee_dict) pairs
        pairs = [
            (
                {"coach_code": e["mentor_code"]},
                {"coach_code": e["mentee_code"]},
            )
            for e in edges
        ]
        final_count = load_mentored_edges_mcillece(driver, pairs)

        # ── Verification ──────────────────────────────────────────────────
        print("\n" + "=" * 60)
        print(f"  Final MENTORED edge count in Neo4j: {final_count:,}")
        if final_count == _EXPECTED_COUNT:
            print(f"  ✓ Matches expected count ({_EXPECTED_COUNT:,})")
        else:
            print(
                f"  ✗ COUNT MISMATCH — expected {_EXPECTED_COUNT:,}, "
                f"got {final_count:,}"
            )
        print("=" * 60)

    finally:
        driver.close()


if __name__ == "__main__":
    main()
