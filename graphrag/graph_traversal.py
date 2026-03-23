"""Neo4j Cypher traversal logic for common GraphRAG query patterns."""

import logging
from typing import Any

from neo4j import Driver

logger = logging.getLogger(__name__)


def get_coach_tree(driver: Driver, coach_name: str) -> list[dict[str, Any]]:
    """Return the coaching tree rooted at a given coach.

    Finds everyone who worked under ``coach_name`` at the same program
    and all coaches they subsequently mentored (one hop of MENTORED edges
    plus shared COACHED_AT tenures as a proxy).

    Args:
        driver: Open Neo4j driver.
        coach_name: Full name of the root coach (e.g. ``"Nick Saban"``).

    Returns:
        List of record dicts with keys ``root``, ``protege``, ``team``,
        and ``years`` describing each coaching relationship.
    """
    query = """
    MATCH (root:Coach)
    WHERE (root.first_name + ' ' + root.last_name) = $name
    OPTIONAL MATCH (root)-[r:COACHED_AT]->(t:Team)<-[r2:COACHED_AT]-(protege:Coach)
    WHERE protege <> root
      AND r2.start_year >= r.start_year
      AND r2.start_year <= coalesce(r.end_year, 9999)
    RETURN root.first_name + ' ' + root.last_name AS root,
           protege.first_name + ' ' + protege.last_name AS protege,
           t.school AS team,
           r2.start_year AS years
    ORDER BY team, years
    """
    with driver.session() as session:
        result = session.run(query, name=coach_name)
        return [dict(record) for record in result]


def get_coaches_in_conferences(
    driver: Driver, conferences: list[str]
) -> list[dict[str, Any]]:
    """Find coaches who worked at programs in all of the specified conferences.

    Args:
        driver: Open Neo4j driver.
        conferences: List of conference names (e.g. ``["SEC", "Big Ten"]``).

    Returns:
        List of record dicts with ``coach`` name and ``schools`` list.
    """
    query = """
    UNWIND $conferences AS conf
    MATCH (c:Coach)-[:COACHED_AT]->(t:Team)-[:IN_CONFERENCE]->(cn:Conference {name: conf})
    WITH c, collect(DISTINCT cn.name) AS coached_in
    WHERE all(conf IN $conferences WHERE conf IN coached_in)
    RETURN c.first_name + ' ' + c.last_name AS coach,
           coached_in AS conferences
    ORDER BY coach
    """
    with driver.session() as session:
        result = session.run(query, conferences=conferences)
        return [dict(record) for record in result]


def get_coaching_tree(
    coach_code: int,
    max_depth: int,
    driver: Driver,
    role_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Return the coaching tree rooted at a McIllece coach node.

    Traverses MENTORED edges up to ``max_depth`` hops from the root node
    identified by ``coach_code``.  When ``role_filter`` is ``"HC"``, only
    mentees who have at least one mcillece_roles COACHED_AT edge with
    ``role_abbr = "HC"`` are returned.

    Args:
        coach_code:  McIllece coach_code integer for the root coach.
        max_depth:   Maximum traversal depth (1–4; values > 4 are clamped to 4).
        driver:      Open Neo4j driver.
        role_filter: Optional role abbreviation filter (e.g. ``"HC"``).
            When provided, only mentees who held that role are included.

    Returns:
        List of dicts with keys:

        - ``name``         — mentee's display name.
        - ``coach_code``   — mentee's McIllece coach_code.
        - ``depth``        — hop distance from root.
        - ``path_coaches`` — list of coach names from root to this node
          (feeds F1 provenance strings).
    """
    depth = max(1, min(int(max_depth), 4))

    if role_filter:
        query = """
        MATCH path = (root:Coach {coach_code: $coach_code})-[:MENTORED*1..$depth]->(mentee:Coach)
        WHERE EXISTS {
            MATCH (mentee)-[r:COACHED_AT]->(:Team)
            WHERE r.role_abbr = $role_filter AND r.source = 'mcillece_roles'
        }
        RETURN mentee.name          AS name,
               mentee.coach_code    AS coach_code,
               length(path)         AS depth,
               [n IN nodes(path) | coalesce(n.name, n.first_name + ' ' + n.last_name)]
                   AS path_coaches
        ORDER BY depth, name
        """
        params: dict[str, Any] = {
            "coach_code": coach_code,
            "depth": depth,
            "role_filter": role_filter,
        }
    else:
        query = """
        MATCH path = (root:Coach {coach_code: $coach_code})-[:MENTORED*1..$depth]->(mentee:Coach)
        RETURN mentee.name          AS name,
               mentee.coach_code    AS coach_code,
               length(path)         AS depth,
               [n IN nodes(path) | coalesce(n.name, n.first_name + ' ' + n.last_name)]
                   AS path_coaches
        ORDER BY depth, name
        """
        params = {"coach_code": coach_code, "depth": depth}

    with driver.session() as session:
        result = session.run(query, **params)
        return [dict(record) for record in result]


def shortest_path_between_coaches(
    driver: Driver, coach_a: str, coach_b: str
) -> list[dict[str, Any]]:
    """Find the shortest relationship path between two coaches in the graph.

    Uses the COACHED_AT relationships to find a chain of shared programs.

    Args:
        driver: Open Neo4j driver.
        coach_a: Full name of the first coach.
        coach_b: Full name of the second coach.

    Returns:
        List of node/relationship dicts representing each hop in the path,
        or an empty list if no path exists.
    """
    query = """
    MATCH (a:Coach), (b:Coach)
    WHERE (a.first_name + ' ' + a.last_name) = $coach_a
      AND (b.first_name + ' ' + b.last_name) = $coach_b
    MATCH path = shortestPath((a)-[:COACHED_AT*..10]-(b))
    RETURN [node IN nodes(path) | coalesce(
        node.school,
        node.first_name + ' ' + node.last_name
    )] AS path_nodes,
    length(path) AS hops
    """
    with driver.session() as session:
        result = session.run(query, coach_a=coach_a, coach_b=coach_b)
        return [dict(record) for record in result]
