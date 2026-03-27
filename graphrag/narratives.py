"""Precomputed coaching tree narratives — F4b.

Stores and retrieves manually reviewed narrative strings on Coach nodes in
Neo4j.  The GraphRAG retriever checks for these before running the full
F4 pipeline, providing faster and more consistent responses for high-traffic
tree queries (e.g. the Nick Saban coaching tree).

Narrative properties on Coach nodes
-------------------------------------
- ``narrative``            — polished prose string, manually reviewed.
- ``narrative_updated_at`` — ISO-8601 timestamp of last write.

Narratives are keyed by the McIllece ``coach_code`` integer because those
nodes carry the full staff history used to build coaching trees.  The
:func:`get_coach_narrative_by_name` helper resolves a display name to a
``coach_code`` via the SAME_PERSON edge before reading the property, so
callers that only know a name do not need to manage coach_codes themselves.

Typical usage — authoring workflow::

    from graphrag.narratives import (
        get_head_coach_tree_summary,
        set_coach_narrative,
    )

    summary = get_head_coach_tree_summary(coach_code=1457, driver=driver)
    # … write narrative prose based on summary, then store …
    set_coach_narrative(coach_code=1457, narrative="…", driver=driver)

Typical usage — retriever fast-path::

    from graphrag.narratives import get_coach_narrative_by_name

    narrative = get_coach_narrative_by_name("Nick Saban", driver=driver)
    if narrative:
        return precomputed_result(narrative)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from neo4j import Driver

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class TreeMenteeRow:
    """A single mentee entry in a :class:`TreeSummary`.

    Attributes:
        name:        Display name of the mentee coach.
        coach_code:  McIllece coach_code, or ``None`` for CFBD-only nodes.
        depth:       Hop distance from the root (1 = direct mentee).
        path_coaches: Coach names from root to this node (feeds narrative authoring).
    """

    name: str
    coach_code: int | None
    depth: int
    path_coaches: list[str] = field(default_factory=list)


@dataclass
class TreeSummary:
    """Structured coaching tree data for narrative authoring support.

    Not generated prose — just the structured facts needed to write a
    high-quality narrative outside the code.  Run
    :func:`get_head_coach_tree_summary` and use the output as reference
    material when authoring the narrative manually.

    Attributes:
        root_name:     Display name of the root coach.
        root_coach_code: McIllece coach_code of the root coach.
        hc_mentees:    Mentees who became head coaches (depth-sorted).
        all_mentees:   All mentees at any depth (depth-sorted).
        total_mentees: Total unique mentee count (all roles).
        hc_mentee_count: Count of HC mentees only.
    """

    root_name: str
    root_coach_code: int
    hc_mentees: list[TreeMenteeRow] = field(default_factory=list)
    all_mentees: list[TreeMenteeRow] = field(default_factory=list)
    total_mentees: int = 0
    hc_mentee_count: int = 0


# ---------------------------------------------------------------------------
# Read / write helpers (keyed by coach_code)
# ---------------------------------------------------------------------------


def set_coach_narrative(
    coach_code: int,
    narrative: str,
    driver: Driver,
) -> None:
    """Store a precomputed narrative on a McIllece Coach node.

    Uses ``MATCH`` (not ``MERGE``) so the node must already exist.  The
    ``narrative_updated_at`` property is set to the current UTC timestamp.

    Args:
        coach_code: McIllece ``coach_code`` integer identifying the coach.
        narrative:  Polished narrative string to store.
        driver:     Open Neo4j driver connected to the loaded graph.

    Raises:
        ValueError: If no Coach node with the given ``coach_code`` is found.
    """
    updated_at = datetime.now(tz=timezone.utc).isoformat()
    query = """
    MATCH (c:Coach {coach_code: $coach_code})
    SET c.narrative = $narrative,
        c.narrative_updated_at = $updated_at
    RETURN c.coach_code AS confirmed_code
    """
    with driver.session() as session:
        result = session.run(
            query,
            coach_code=coach_code,
            narrative=narrative,
            updated_at=updated_at,
        )
        record = result.single()

    if record is None:
        raise ValueError(
            f"No Coach node found with coach_code={coach_code!r}. "
            "Narrative was not stored."
        )

    logger.info(
        "Stored narrative for coach_code=%s (%d chars).",
        coach_code,
        len(narrative),
    )


def get_coach_narrative(
    coach_code: int,
    driver: Driver,
) -> str | None:
    """Retrieve a precomputed narrative from a McIllece Coach node.

    Args:
        coach_code: McIllece ``coach_code`` integer.
        driver:     Open Neo4j driver.

    Returns:
        The narrative string if present, or ``None`` when the property is
        absent or the Coach node does not exist.
    """
    query = """
    MATCH (c:Coach {coach_code: $coach_code})
    RETURN c.narrative AS narrative
    LIMIT 1
    """
    with driver.session() as session:
        result = session.run(query, coach_code=coach_code)
        record = result.single()

    if record is None:
        return None
    return record["narrative"]  # may be None if property not set


# ---------------------------------------------------------------------------
# Name-based lookup (used by the retriever)
# ---------------------------------------------------------------------------


def get_coach_narrative_by_name(
    coach_name: str,
    driver: Driver,
) -> str | None:
    """Retrieve a precomputed narrative by coach display name.

    Resolves the display name to a graph node via:

    1. CFBD ``Coach`` node matched by ``first_name`` + ``last_name``.
       Follows any ``SAME_PERSON`` edge to the McIllece node and reads the
       narrative from the McIllece node first.
    2. Falls back to a McIllece ``Coach`` node matched by ``name`` property.

    Returns ``None`` when no narrative is found via either path, or when the
    name cannot be split into exactly two tokens.

    Args:
        coach_name: Full display name (e.g. ``"Nick Saban"``).
        driver:     Open Neo4j driver.

    Returns:
        Narrative string, or ``None``.
    """
    parts = coach_name.strip().split(None, 1)
    if len(parts) != 2:
        logger.debug("get_coach_narrative_by_name: cannot split %r", coach_name)
        return None

    first, last = parts[0], parts[1]

    # Single query: try CFBD→McIllece path first, then McIllece direct.
    query = """
    OPTIONAL MATCH (cfbd:Coach {first_name: $first, last_name: $last})
    OPTIONAL MATCH (cfbd)-[:SAME_PERSON]->(mc_via_cfbd:Coach)
    WHERE mc_via_cfbd.coach_code IS NOT NULL
    OPTIONAL MATCH (mc_direct:Coach {name: $full_name})
    WHERE mc_direct.coach_code IS NOT NULL
    WITH
        coalesce(mc_via_cfbd.narrative, cfbd.narrative, mc_direct.narrative) AS narrative
    RETURN narrative
    LIMIT 1
    """
    with driver.session() as session:
        result = session.run(
            query,
            first=first,
            last=last,
            full_name=coach_name.strip(),
        )
        record = result.single()

    if record is None:
        return None
    return record["narrative"]


# ---------------------------------------------------------------------------
# Authoring support — tree summary (no prose generation)
# ---------------------------------------------------------------------------


def get_head_coach_tree_summary(
    coach_code: int,
    driver: Driver,
    max_depth: int = 4,
) -> TreeSummary:
    """Fetch structured coaching tree data to support manual narrative authoring.

    Returns the full mentee list and the HC-filtered mentee list for the
    given root coach.  Does NOT generate any prose — the intent is to give
    the author the raw facts needed to write a polished narrative by hand.

    Args:
        coach_code: McIllece ``coach_code`` of the root coach.
        driver:     Open Neo4j driver.
        max_depth:  Maximum traversal depth (1–4, clamped).

    Returns:
        :class:`TreeSummary` with ``hc_mentees``, ``all_mentees``,
        and aggregate counts.

    Example::

        summary = get_head_coach_tree_summary(coach_code=1457, driver=driver)
        print(f"Root: {summary.root_name}")
        for row in summary.hc_mentees:
            print(f"  HC mentee (depth {row.depth}): {row.name}")
    """
    depth = max(1, min(int(max_depth), 4))

    # --- resolve root coach display name ---
    root_query = """
    MATCH (c:Coach {coach_code: $coach_code})
    RETURN coalesce(c.name, c.first_name + ' ' + c.last_name) AS name
    LIMIT 1
    """
    with driver.session() as session:
        result = session.run(root_query, coach_code=coach_code)
        root_record = result.single()

    root_name: str = root_record["name"] if root_record else f"coach_code={coach_code}"

    # Neo4j does not accept parameters in variable-length relationship ranges
    # ([:MENTORED*1..$depth]), so the clamped depth is interpolated directly
    # into the query string.  The value is safe: clamped to 1–4 above.
    #
    # Each query deduplicates by mentee: WITH + min(length(path)) keeps only
    # the shallowest path per unique mentee coach.

    # --- all mentees (any role) ---
    # ORDER BY length(path) before the aggregation ensures head(collect(...))
    # always picks the shortest path for each unique mentee.
    all_query = f"""
    MATCH path = (root:Coach {{coach_code: $coach_code}})-[:MENTORED*1..{depth}]->(mentee:Coach)
    WITH mentee, path
    ORDER BY length(path)
    WITH mentee,
         min(length(path)) AS min_depth,
         head(collect(
             [n IN nodes(path) | coalesce(n.name, n.first_name + ' ' + n.last_name)]
         )) AS path_coaches
    RETURN mentee.name       AS name,
           mentee.coach_code AS coach_code,
           min_depth         AS depth,
           path_coaches
    ORDER BY depth, name
    """
    with driver.session() as session:
        result = session.run(all_query, coach_code=coach_code)
        all_rows: list[dict[str, Any]] = [dict(r) for r in result]

    # Post-query cycle filter: exclude any row where the mentee is the root
    # coach itself.  Bidirectional MENTORED cycles (e.g. A→B→A at depth 2)
    # cause Cypher to return the root as a mentee.
    all_rows = [r for r in all_rows if r.get("coach_code") != coach_code]

    # --- HC-only mentees ---
    hc_query = f"""
    MATCH path = (root:Coach {{coach_code: $coach_code}})-[:MENTORED*1..{depth}]->(mentee:Coach)
    WHERE EXISTS {{
        MATCH (mentee)-[r:COACHED_AT]->(:Team)
        WHERE r.role_abbr = 'HC' AND r.source = 'mcillece_roles'
    }}
    WITH mentee, path
    ORDER BY length(path)
    WITH mentee,
         min(length(path)) AS min_depth,
         head(collect(
             [n IN nodes(path) | coalesce(n.name, n.first_name + ' ' + n.last_name)]
         )) AS path_coaches
    RETURN mentee.name       AS name,
           mentee.coach_code AS coach_code,
           min_depth         AS depth,
           path_coaches
    ORDER BY depth, name
    """
    with driver.session() as session:
        result = session.run(hc_query, coach_code=coach_code)
        hc_rows: list[dict[str, Any]] = [dict(r) for r in result]

    hc_rows = [r for r in hc_rows if r.get("coach_code") != coach_code]

    def _to_mentee(row: dict[str, Any]) -> TreeMenteeRow:
        return TreeMenteeRow(
            name=row.get("name") or "",
            coach_code=row.get("coach_code"),
            depth=int(row.get("depth", 1)),
            path_coaches=list(row.get("path_coaches") or []),
        )

    all_mentees = [_to_mentee(r) for r in all_rows]
    hc_mentees = [_to_mentee(r) for r in hc_rows]

    return TreeSummary(
        root_name=root_name,
        root_coach_code=coach_code,
        hc_mentees=hc_mentees,
        all_mentees=all_mentees,
        total_mentees=len(all_mentees),
        hc_mentee_count=len(hc_mentees),
    )
