"""Load per-role COACHED_AT edges from McIllece expand_roles output into Neo4j.

Each role record from ``ingestion.expand_roles.expand_to_role_records``
becomes one COACHED_AT relationship.  The MERGE key is
``(coach_code, year, team_code, role_abbr)`` so a coach with two roles in
one season (e.g. OC + QB) gets two distinct edges.

All writes use MERGE — the loader is fully idempotent.
"""

import logging
from typing import Any

from neo4j import Driver

from loader import schema

logger = logging.getLogger(__name__)

# Batch size for UNWIND queries — large enough to be efficient without
# overwhelming Neo4j's transaction memory.
_BATCH_SIZE = 2_000


def load_coached_at_roles(
    driver: Driver,
    role_records: list[dict[str, Any]],
) -> int:
    """MERGE one COACHED_AT edge per role record.

    The MERGE key ``(coach_code, year, team_code, role_abbr)`` uniquely
    identifies a coaching role within a season.  The loader is safe to
    re-run; duplicate MERGE calls are no-ops.

    Args:
        driver: Open Neo4j driver.
        role_records: Expanded role records from
            ``ingestion.expand_roles.expand_to_role_records()``.

    Returns:
        Number of role records submitted (each maps to one MERGE).
    """
    if not role_records:
        logger.info("No role records to load — skipping")
        return 0

    query = f"""
    UNWIND $rows AS row
    MATCH  (c:{schema.COACH} {{coach_code: row.coach_code}})
    MATCH  (t:{schema.TEAM}  {{school:     row.team}})
    MERGE  (c)-[r:{schema.COACHED_AT} {{
        coach_code: row.coach_code,
        year:       row.year,
        team_code:  row.team_code,
        role_abbr:  row.role_abbr
    }}]->(t)
    SET r.role           = row.role,
        r.role_tier      = row.role_tier,
        r.is_coordinator = row.is_coordinator,
        r.coach_name     = row.coach_name,
        r.source         = "mcillece_roles"
    """

    total = 0
    for batch_start in range(0, len(role_records), _BATCH_SIZE):
        batch = role_records[batch_start : batch_start + _BATCH_SIZE]
        with driver.session() as session:
            session.run(query, rows=batch)
        total += len(batch)
        logger.debug("Loaded batch %d–%d", batch_start, batch_start + len(batch))

    logger.info("Merged %d COACHED_AT role edges (source=mcillece_roles)", total)
    return total


def print_load_summary(
    role_records: list[dict[str, Any]],
    unmapped_abbrs: list[str],
) -> None:
    """Print total edges, tier breakdown, year breakdown, and unmapped flags.

    Args:
        role_records: Expanded role records.
        unmapped_abbrs: Abbreviations not found in the role legend.
    """
    from collections import Counter
    from ingestion.expand_roles import (
        TIER_COORDINATOR,
        TIER_POSITION_COACH,
        TIER_SUPPORT,
        TIER_UNKNOWN,
    )

    total = len(role_records)
    tier_counts: Counter[str] = Counter(r["role_tier"] for r in role_records)
    year_counts: Counter[int] = Counter(r["year"] for r in role_records)

    print(f"\n{'=' * 48}")
    print(f"  McIllece COACHED_AT roles — load summary")
    print(f"{'=' * 48}")
    print(f"\nTotal edges created:  {total:,}")

    print("\nBreakdown by role_tier:")
    for tier in (TIER_COORDINATOR, TIER_POSITION_COACH, TIER_SUPPORT, TIER_UNKNOWN):
        count = tier_counts[tier]
        if count:
            pct = count / total * 100 if total else 0
            print(f"  {tier:<20} {count:>7,}  ({pct:.1f}%)")

    print("\nBreakdown by year:")
    for year in sorted(year_counts):
        print(f"  {year}  {year_counts[year]:>6,}")

    if unmapped_abbrs:
        print(f"\nUnmapped abbreviations ({len(unmapped_abbrs)}) — check legend:")
        for abbr in unmapped_abbrs:
            count = sum(1 for r in role_records if r["role_abbr"] == abbr)
            print(f"  {abbr!r:12s}  {count} occurrence(s)")
    else:
        print("\nUnmapped abbreviations: none")
