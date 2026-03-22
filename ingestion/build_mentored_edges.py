"""Infer MENTORED coaching-tree edges from COACHED_AT relationships in Neo4j.

Two coaches are considered to have a mentor/mentee relationship if they
overlapped on the same staff — same school, at least one shared season.
The more senior coach (earlier first year at that school) is the mentor.
If both coaches first joined that school in the same year the direction
cannot be determined and the pair is skipped.

Usage (standalone):
    python -m ingestion.build_mentored_edges
"""

import logging
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from neo4j import Driver

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_coached_at_records(driver: Driver) -> list[dict[str, Any]]:
    """Query Neo4j for every COACHED_AT season-stint.

    Returns one dict per (coach, school, year) combination with keys:
    ``first_name``, ``last_name``, ``school``, ``year``.

    Args:
        driver: Open Neo4j driver.

    Returns:
        List of stint dicts, ordered by school then year.
    """
    query = """
    MATCH (c:Coach)-[r:COACHED_AT]->(t:Team)
    RETURN c.first_name AS first_name,
           c.last_name  AS last_name,
           t.school     AS school,
           r.start_year AS year
    ORDER BY school, year
    """
    with driver.session() as session:
        result = session.run(query)
        return [r.data() for r in result]


def infer_mentored_pairs(
    records: list[dict[str, Any]],
) -> list[tuple[dict[str, str], dict[str, str]]]:
    """Infer MENTORED pairs from a flat list of COACHED_AT stint records.

    Algorithm:
    1. Group stints by school.
    2. For each school, build a map of ``(first_name, last_name)`` →
       ``set[year]`` for every coach present at that school.
    3. For every unique pair of coaches at that school, check whether their
       year-sets intersect (overlap of ≥ 1 season).
    4. If they overlap, the coach with the lower minimum year is the mentor.
       If minimum years are equal the direction is ambiguous — skip.
    5. Collect unique ``(mentor, mentee)`` pairs across all schools
       (a pair is deduplicated even if coaches shared multiple schools).

    Args:
        records: List of stint dicts with keys
            ``first_name``, ``last_name``, ``school``, ``year``.

    Returns:
        Deduplicated list of ``(mentor_dict, mentee_dict)`` tuples where
        each dict has ``first_name`` and ``last_name`` keys.
    """
    # {school: {(first, last): {year, ...}}}
    school_coach_years: dict[str, dict[tuple[str, str], set[int]]] = defaultdict(
        lambda: defaultdict(set)
    )
    for rec in records:
        key = (rec["first_name"], rec["last_name"])
        school_coach_years[rec["school"]][key].add(rec["year"])

    seen: set[tuple[tuple[str, str], tuple[str, str]]] = set()

    for school, coach_years in school_coach_years.items():
        coaches = list(coach_years.keys())
        for i in range(len(coaches)):
            for j in range(i + 1, len(coaches)):
                c1, c2 = coaches[i], coaches[j]

                # Must share at least one season
                if not (coach_years[c1] & coach_years[c2]):
                    continue

                c1_start = min(coach_years[c1])
                c2_start = min(coach_years[c2])

                if c1_start == c2_start:
                    logger.debug(
                        "Skipping %s %s / %s %s at %s — equal start years (%d)",
                        c1[0], c1[1], c2[0], c2[1], school, c1_start,
                    )
                    continue

                mentor, mentee = (c1, c2) if c1_start < c2_start else (c2, c1)
                seen.add((mentor, mentee))

    logger.info("Inferred %d unique MENTORED pairs", len(seen))

    return [
        (
            {"first_name": mentor[0], "last_name": mentor[1]},
            {"first_name": mentee[0], "last_name": mentee[1]},
        )
        for mentor, mentee in seen
    ]


# ---------------------------------------------------------------------------
# Standalone entry-point
# ---------------------------------------------------------------------------


def _run() -> None:
    """Fetch COACHED_AT records from Neo4j and print inferred pair count."""
    from dotenv import load_dotenv

    load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

    from loader.neo4j_loader import get_driver

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
    finally:
        driver.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    _run()
