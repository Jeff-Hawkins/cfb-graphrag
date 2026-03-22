"""Load inferred MENTORED coaching-tree edges into Neo4j.

Uses MERGE so the loader is fully idempotent — safe to run multiple times
without creating duplicate relationships.

Usage (standalone):
    python -m loader.load_mentored_edges
"""

import logging
import os
from pathlib import Path
from typing import Any

from neo4j import Driver

from loader import schema

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_mentored_edges(
    driver: Driver,
    pairs: list[tuple[dict[str, str], dict[str, str]]],
) -> int:
    """MERGE MENTORED relationships for each inferred mentor/mentee pair.

    Builds a single UNWIND batch query so that all pairs are loaded in one
    round-trip.  After loading, queries the total MENTORED edge count and
    prints it to stdout.

    Args:
        driver: Open Neo4j driver.
        pairs: List of ``(mentor_dict, mentee_dict)`` tuples as returned by
            ``infer_mentored_pairs()``.  Each dict must have ``first_name``
            and ``last_name`` keys.

    Returns:
        Total number of MENTORED edges now present in the graph.
    """
    if not pairs:
        logger.info("No pairs to load — skipping MERGE")
        with driver.session() as session:
            result = session.run(
                f"MATCH ()-[:{schema.MENTORED}]->() RETURN count(*) AS total"
            )
            total: int = result.single()["total"]
        print(f"Total MENTORED edges in graph: {total:,}")
        return total

    merge_query = f"""
    UNWIND $rows AS row
    MATCH (mentor:{schema.COACH} {{first_name: row.mentor_first, last_name: row.mentor_last}})
    MATCH (mentee:{schema.COACH} {{first_name: row.mentee_first, last_name: row.mentee_last}})
    MERGE (mentor)-[:{schema.MENTORED}]->(mentee)
    """

    rows: list[dict[str, Any]] = [
        {
            "mentor_first": mentor["first_name"],
            "mentor_last":  mentor["last_name"],
            "mentee_first": mentee["first_name"],
            "mentee_last":  mentee["last_name"],
        }
        for mentor, mentee in pairs
    ]

    with driver.session() as session:
        session.run(merge_query, rows=rows)

    logger.info("Merged %d MENTORED pairs", len(pairs))

    count_query = f"MATCH ()-[:{schema.MENTORED}]->() RETURN count(*) AS total"
    with driver.session() as session:
        result = session.run(count_query)
        total = result.single()["total"]

    print(f"Total MENTORED edges in graph: {total:,}")
    return total


# ---------------------------------------------------------------------------
# Standalone entry-point
# ---------------------------------------------------------------------------


def _run() -> None:
    """Infer MENTORED pairs from live Neo4j data and load them back in."""
    from dotenv import load_dotenv

    load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

    from loader.neo4j_loader import get_driver
    from ingestion.build_mentored_edges import fetch_coached_at_records, infer_mentored_pairs

    driver = get_driver(
        os.environ["NEO4J_URI"],
        os.environ["NEO4J_USERNAME"],
        os.environ["NEO4J_PASSWORD"],
    )
    try:
        records = fetch_coached_at_records(driver)
        print(f"COACHED_AT records fetched: {len(records):,}")
        pairs = infer_mentored_pairs(records)
        print(f"MENTORED pairs inferred:    {len(pairs):,}")
        load_mentored_edges(driver, pairs)
    finally:
        driver.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    _run()
