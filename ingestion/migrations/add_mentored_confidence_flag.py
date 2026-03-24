"""Migration: add confidence_flag = 'STANDARD' to all existing MENTORED edges.

Idempotent — the ``WHERE r.confidence_flag IS NULL`` guard means that edges
already carrying any non-NULL flag (e.g. ``'REVIEW_REVERSE'`` set by
``flag_mentored_edges.py``) are never overwritten.  Re-running after the
first successful pass is a safe no-op.

Valid confidence_flag values
-----------------------------
``"STANDARD"``
    Inference direction is reliable.

``"REVIEW_REVERSE"``
    Mentee's prior career suggests real influence may flow the opposite
    direction.

``"REVIEW_MUTUAL"``
    Coaches have a long bidirectional relationship; direction is ambiguous.

Usage (standalone)::

    python -m ingestion.migrations.add_mentored_confidence_flag
"""

import logging
import os
from pathlib import Path

from neo4j import Driver

logger = logging.getLogger(__name__)

MIGRATION_NAME = "add_mentored_confidence_flag"
DEFAULT_FLAG = "STANDARD"


def run_migration(driver: Driver) -> int:
    """Set ``confidence_flag = 'STANDARD'`` on every MENTORED edge that lacks it.

    Idempotent: edges that already have a non-NULL ``confidence_flag`` (set
    by ``flag_mentored_edges.py`` or a previous run) are untouched.

    Args:
        driver: Open Neo4j driver.

    Returns:
        Number of MENTORED edges updated in this run.  Returns ``0`` when
        all edges already have a flag (safe re-run).
    """
    query = """
    MATCH ()-[r:MENTORED]->()
    WHERE r.confidence_flag IS NULL
    SET r.confidence_flag = $flag
    RETURN count(r) AS updated
    """
    with driver.session() as session:
        result = session.run(query, flag=DEFAULT_FLAG)
        record = result.single()
        updated: int = record["updated"] if record else 0

    logger.info(
        "%s: set confidence_flag='%s' on %d MENTORED edge(s)",
        MIGRATION_NAME,
        DEFAULT_FLAG,
        updated,
    )
    return updated


# ---------------------------------------------------------------------------
# Standalone entry-point
# ---------------------------------------------------------------------------


def _run() -> None:
    """Run migration against live Neo4j (reads credentials from .env)."""
    from dotenv import load_dotenv

    load_dotenv(dotenv_path=Path(__file__).parent.parent.parent / ".env")

    from loader.neo4j_loader import get_driver

    driver = get_driver(
        os.environ["NEO4J_URI"],
        os.environ["NEO4J_USERNAME"],
        os.environ["NEO4J_PASSWORD"],
    )
    try:
        updated = run_migration(driver)
        print(f"Migration '{MIGRATION_NAME}': {updated:,} edge(s) updated.")
    finally:
        driver.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    _run()
