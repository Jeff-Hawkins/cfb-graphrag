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

        - ``name``            — mentee's display name.
        - ``coach_code``      — mentee's McIllece coach_code.
        - ``depth``           — hop distance from root.
        - ``path_coaches``    — list of coach names from root to this node
          (feeds F1 provenance strings).
        - ``confidence_flag`` — ``confidence_flag`` property of the last
          MENTORED edge in the path (the direct mentor → mentee hop).
          ``None`` when the property has not been set (pre-migration edges).
    """
    depth = max(1, min(int(max_depth), 4))

    # Neo4j does not accept parameters in variable-length relationship ranges
    # ([:MENTORED*1..$depth]), so the clamped depth is interpolated directly
    # into the query string.  The value is safe: clamped to 1–4 above.
    if role_filter:
        query = f"""
        MATCH path = (root:Coach {{coach_code: $coach_code}})-[:MENTORED*1..{depth}]->(mentee:Coach)
        WHERE EXISTS {{
            MATCH (mentee)-[r:COACHED_AT]->(:Team)
            WHERE r.role_abbr = $role_filter AND r.source = 'mcillece_roles'
        }}
        RETURN mentee.name          AS name,
               mentee.coach_code    AS coach_code,
               length(path)         AS depth,
               [n IN nodes(path) | coalesce(n.name, n.first_name + ' ' + n.last_name)]
                   AS path_coaches,
               last(relationships(path)).confidence_flag AS confidence_flag
        ORDER BY depth, name
        """
        params: dict[str, Any] = {
            "coach_code": coach_code,
            "role_filter": role_filter,
        }
    else:
        query = f"""
        MATCH path = (root:Coach {{coach_code: $coach_code}})-[:MENTORED*1..{depth}]->(mentee:Coach)
        RETURN mentee.name          AS name,
               mentee.coach_code    AS coach_code,
               length(path)         AS depth,
               [n IN nodes(path) | coalesce(n.name, n.first_name + ' ' + n.last_name)]
                   AS path_coaches,
               last(relationships(path)).confidence_flag AS confidence_flag
        ORDER BY depth, name
        """
        params = {"coach_code": coach_code}

    with driver.session() as session:
        result = session.run(query, **params)
        rows = [dict(record) for record in result]

    # Post-query cycle filter (Rule 4): exclude any row where the root coach
    # appears as the mentee.  Cypher variable-length paths can traverse
    # bidirectional MENTORED cycles back to the root (e.g. A→B→A at depth 2).
    before = len(rows)
    rows = [r for r in rows if r.get("coach_code") != coach_code]
    suppressed = before - len(rows)
    if suppressed:
        logger.debug(
            "get_coaching_tree: filtered %d self-referential path(s) for root coach_code=%d",
            suppressed,
            coach_code,
        )

    return rows


def get_best_roles(
    coach_codes: list[int],
    driver: Driver,
) -> dict[int, str]:
    """Batch-fetch the highest-priority role for each coach.

    Looks up ``mcillece_roles`` COACHED_AT edges and returns the most
    senior role abbreviation per coach using the priority order
    HC > OC > DC > everything else (mapped to ``"POS"``).

    Args:
        coach_codes: List of McIllece ``coach_code`` integers.
        driver: Open Neo4j driver.

    Returns:
        Dict mapping ``coach_code`` → role abbreviation string
        (``"HC"``, ``"OC"``, ``"DC"``, or ``"POS"``).  Coaches with
        no ``mcillece_roles`` edges are omitted from the result.
    """
    if not coach_codes:
        return {}

    query = """
    UNWIND $codes AS code
    MATCH (c:Coach {coach_code: code})-[r:COACHED_AT]->(:Team)
    WHERE r.source = 'mcillece_roles'
    WITH c.coach_code AS cc, r.role_abbr AS ra,
         CASE r.role_abbr
           WHEN 'HC' THEN 1
           WHEN 'OC' THEN 2
           WHEN 'DC' THEN 3
           ELSE 4
         END AS priority
    ORDER BY priority
    WITH cc, head(collect(ra)) AS best_role
    RETURN cc AS coach_code, best_role AS role
    """
    with driver.session() as session:
        result = session.run(query, codes=coach_codes)
        role_map: dict[int, str] = {}
        for record in result:
            role_abbr = record["role"]
            # Collapse position-level roles to "POS" for UI display.
            if role_abbr not in ("HC", "OC", "DC"):
                role_abbr = "POS"
            role_map[record["coach_code"]] = role_abbr
        return role_map


def get_mentee_stints(
    mentee_mentor_pairs: list[tuple[int, int]],
    driver: Driver,
) -> dict[int, dict[str, Any]]:
    """Batch-fetch the coaching stint context for each mentee-mentor pair.

    For each (mentee_code, mentor_code) pair, finds the team where both
    coaches had overlapping ``mcillece`` COACHED_AT edges and returns the
    mentee's highest-priority role at that team during the overlap, plus
    the year range.

    Args:
        mentee_mentor_pairs: List of ``(mentee_coach_code, mentor_coach_code)``
            tuples.
        driver: Open Neo4j driver.

    Returns:
        Dict mapping ``mentee_coach_code`` → dict with keys:

        - ``role_abbr`` — highest-priority role abbreviation at the overlap
          team (HC > OC > DC > others).
        - ``team`` — school name where the overlap occurred.
        - ``start_year`` — first overlapping season year.
        - ``end_year`` — last overlapping season year.

        Mentees with no overlapping stints are omitted.
    """
    if not mentee_mentor_pairs:
        return {}

    pairs_param = [
        {"mentee": m, "mentor": p} for m, p in mentee_mentor_pairs
    ]

    query = """
    UNWIND $pairs AS pair
    MATCH (mentor:Coach {coach_code: pair.mentor})-[rm:COACHED_AT]->(t:Team)
          <-[rp:COACHED_AT]-(mentee:Coach {coach_code: pair.mentee})
    WHERE rm.source = 'mcillece' AND rp.source = 'mcillece'
      AND rm.year = rp.year
    WITH mentee.coach_code AS mentee_code, t.school AS team,
         collect(DISTINCT rp.year) AS overlap_years
    WHERE size(overlap_years) > 0
    WITH mentee_code, team, overlap_years,
         reduce(mn = 9999, y IN overlap_years | CASE WHEN y < mn THEN y ELSE mn END) AS start_year,
         reduce(mx = 0, y IN overlap_years | CASE WHEN y > mx THEN y ELSE mx END) AS end_year
    ORDER BY mentee_code, size(overlap_years) DESC
    WITH mentee_code, head(collect({team: team, start_year: start_year, end_year: end_year})) AS best
    RETURN mentee_code, best.team AS team, best.start_year AS start_year, best.end_year AS end_year
    """

    # Second query: get the mentee's best role at the overlap team.
    role_query = """
    UNWIND $stints AS s
    MATCH (c:Coach {coach_code: s.mentee_code})-[r:COACHED_AT]->(t:Team {school: s.team})
    WHERE r.source = 'mcillece_roles'
      AND r.year >= s.start_year AND r.year <= s.end_year
    WITH c.coach_code AS cc, r.role_abbr AS ra,
         CASE r.role_abbr
           WHEN 'HC' THEN 1
           WHEN 'OC' THEN 2
           WHEN 'DC' THEN 3
           ELSE 4
         END AS priority
    ORDER BY priority
    WITH cc, head(collect(ra)) AS best_role
    RETURN cc AS mentee_code, best_role AS role_abbr
    """

    with driver.session() as session:
        result = session.run(query, pairs=pairs_param)
        stints: dict[int, dict[str, Any]] = {}
        stint_params: list[dict[str, Any]] = []
        for record in result:
            mc = record["mentee_code"]
            stints[mc] = {
                "team": record["team"],
                "start_year": record["start_year"],
                "end_year": record["end_year"],
                "role_abbr": None,
            }
            stint_params.append({
                "mentee_code": mc,
                "team": record["team"],
                "start_year": record["start_year"],
                "end_year": record["end_year"],
            })

        # Enrich with role if we got stint data.
        if stint_params:
            role_result = session.run(role_query, stints=stint_params)
            for record in role_result:
                mc = record["mentee_code"]
                if mc in stints:
                    stints[mc]["role_abbr"] = record["role_abbr"]

    return stints


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
