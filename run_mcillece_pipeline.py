"""McIllece ingestion pipeline entrypoint.

Loads all McIllece XLSX files from data/mcillece/, expands pos1-pos5 into
per-role records, and creates enriched COACHED_AT edges in Neo4j.

Run from the project root:

    python run_mcillece_pipeline.py [--dry-run]

Options:
    --dry-run   Print what would be loaded without writing to Neo4j.

Requires CFBD_API_KEY, NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD in .env.
"""

import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from ingestion.expand_roles import expand_to_role_records, print_summary
from ingestion.pull_mcillece_staff import load_mcillece_file
from loader.load_coached_at_roles import load_coached_at_roles, print_load_summary
from loader.load_staff import load_staff

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()

_MCILLECE_DIR = Path("data/mcillece")
# Only the main data file — skip the legend workbook
_DATA_GLOB = "CFB-Coaches-Database-*.xlsx"
_LEGEND_PATTERN = "Legend"


def _find_data_files() -> list[Path]:
    """Return all McIllece data XLSX files (excluding the legend)."""
    return sorted(
        p for p in _MCILLECE_DIR.glob(_DATA_GLOB)
        if _LEGEND_PATTERN not in p.name
    )


def main(*, dry_run: bool = False) -> None:
    """Run the full McIllece ingestion pipeline.

    Args:
        dry_run: If True, print expanded records and exit without writing
            to Neo4j.
    """
    files = _find_data_files()
    if not files:
        logger.error("No McIllece data files found in %s", _MCILLECE_DIR)
        sys.exit(1)

    # ── Step 1: Load all files ────────────────────────────────────────────
    all_staff: list[dict] = []
    for path in files:
        logger.info("Loading %s", path.name)
        records = load_mcillece_file(path)
        logger.info("  → %d staff records", len(records))
        all_staff.extend(records)

    logger.info("Total staff records loaded: %d", len(all_staff))

    # ── Step 2: Expand pos1–pos5 into per-role records ────────────────────
    role_records, unmapped_abbrs = expand_to_role_records(all_staff)

    if dry_run:
        print_summary(role_records, unmapped_abbrs)
        print("\n[dry-run] No changes written to Neo4j.")
        return

    # ── Step 3: Load Coach nodes + season-level COACHED_AT (existing) ─────
    uri = os.environ.get("NEO4J_URI", "")
    username = os.environ.get("NEO4J_USERNAME", "")
    password = os.environ.get("NEO4J_PASSWORD", "")
    if not all([uri, username, password]):
        raise EnvironmentError(
            "NEO4J_URI, NEO4J_USERNAME, and NEO4J_PASSWORD must be set in .env"
        )

    from loader.neo4j_loader import get_driver

    driver = get_driver(uri, username, password)
    try:
        # Merge Coach nodes and season-level COACHED_AT edges
        coaches_merged, season_edges = load_staff(driver, all_staff)
        logger.info(
            "load_staff: %d coaches, %d season-level edges", coaches_merged, season_edges
        )

        # ── Step 4: Load per-role COACHED_AT edges ─────────────────────────
        edges_total = load_coached_at_roles(driver, role_records)
        print_load_summary(role_records, unmapped_abbrs)
        logger.info("load_coached_at_roles: %d role edges merged", edges_total)
    finally:
        driver.close()


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
