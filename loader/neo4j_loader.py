"""Neo4j loader — idempotent MERGE operations for all node and edge types.

All writes use MERGE so the loader is safe to run multiple times without
creating duplicate nodes or relationships.
"""

import logging
from typing import Any

from neo4j import GraphDatabase, Driver

from loader import schema

logger = logging.getLogger(__name__)


def get_driver(uri: str, username: str, password: str) -> Driver:
    """Create and return an authenticated Neo4j driver.

    Args:
        uri: Bolt or neo4j+s URI for the AuraDB instance.
        username: Neo4j username (usually ``"neo4j"``).
        password: Neo4j password from the AuraDB console.

    Returns:
        An open neo4j.Driver.  Call ``.close()`` when finished.
    """
    return GraphDatabase.driver(uri, auth=(username, password))


# ---------------------------------------------------------------------------
# Node loaders
# ---------------------------------------------------------------------------


def load_teams(driver: Driver, teams: list[dict[str, Any]]) -> int:
    """MERGE Team nodes from a list of CFBD team dicts.

    Args:
        driver: Open Neo4j driver.
        teams: Raw team records as returned by ``fetch_teams()``.

    Returns:
        Number of teams processed.
    """
    query = f"""
    UNWIND $rows AS row
    MERGE (t:{schema.TEAM} {{id: row.id}})
    SET t.school       = row.school,
        t.conference   = row.conference,
        t.abbreviation = row.abbreviation
    """
    with driver.session() as session:
        session.run(query, rows=teams)
    logger.info("Loaded %d teams", len(teams))
    return len(teams)


def load_conferences(driver: Driver, teams: list[dict[str, Any]]) -> int:
    """MERGE Conference nodes derived from the team list.

    Args:
        driver: Open Neo4j driver.
        teams: Raw team records (used to extract unique conference names).

    Returns:
        Number of unique conferences processed.
    """
    conferences = [
        {"name": t["conference"]}
        for t in teams
        if t.get("conference")
    ]
    unique = list({c["name"]: c for c in conferences}.values())

    query = f"""
    UNWIND $rows AS row
    MERGE (c:{schema.CONFERENCE} {{name: row.name}})
    """
    link_query = f"""
    UNWIND $rows AS row
    MATCH (t:{schema.TEAM} {{school: row.school}})
    MATCH (c:{schema.CONFERENCE} {{name: row.conference}})
    MERGE (t)-[:{schema.IN_CONFERENCE}]->(c)
    """
    with driver.session() as session:
        session.run(query, rows=unique)
        session.run(link_query, rows=[t for t in teams if t.get("conference")])

    logger.info("Loaded %d conferences", len(unique))
    return len(unique)


def load_coaches(driver: Driver, coaches: list[dict[str, Any]]) -> int:
    """MERGE Coach nodes and COACHED_AT relationships from CFBD coach records.

    Each coach record contains a ``seasons`` list; each season entry
    becomes a ``COACHED_AT`` relationship to the relevant Team node.

    Args:
        driver: Open Neo4j driver.
        coaches: Raw coach records as returned by ``fetch_coaches()``.

    Returns:
        Number of coach records processed.
    """
    coach_query = f"""
    UNWIND $rows AS row
    MERGE (c:{schema.COACH} {{first_name: row.first_name, last_name: row.last_name}})
    """
    stint_query = f"""
    UNWIND $stints AS s
    MATCH (c:{schema.COACH} {{first_name: s.first_name, last_name: s.last_name}})
    MATCH (t:{schema.TEAM} {{school: s.school}})
    MERGE (c)-[r:{schema.COACHED_AT} {{title: s.title, start_year: s.year}}]->(t)
    SET r.end_year = s.year
    """
    stints = [
        {
            "first_name": coach["first_name"],
            "last_name": coach["last_name"],
            "school": season["school"],
            "title": season.get("games", {}) and season.get("title", ""),
            "year": season["year"],
        }
        for coach in coaches
        for season in coach.get("seasons", [])
        if season.get("school")
    ]

    with driver.session() as session:
        session.run(coach_query, rows=coaches)
        if stints:
            session.run(stint_query, stints=stints)

    logger.info("Loaded %d coaches with %d stints", len(coaches), len(stints))
    return len(coaches)


def load_players(driver: Driver, roster_records: list[dict[str, Any]]) -> int:
    """MERGE Player nodes and PLAYED_FOR relationships from roster records.

    Args:
        driver: Open Neo4j driver.
        roster_records: Raw roster records as returned by ``fetch_rosters()``.

    Returns:
        Number of roster records processed.
    """
    query = f"""
    UNWIND $rows AS row
    MERGE (p:{schema.PLAYER} {{id: row.id}})
    SET p.name     = row.name,
        p.position = row.position,
        p.hometown = row.hometown
    WITH p, row
    MATCH (t:{schema.TEAM} {{school: row.team}})
    MERGE (p)-[r:{schema.PLAYED_FOR} {{year: row.year}}]->(t)
    SET r.jersey = row.jersey
    """
    with driver.session() as session:
        session.run(query, rows=roster_records)
    logger.info("Loaded %d player-season records", len(roster_records))
    return len(roster_records)


def load_games(driver: Driver, games: list[dict[str, Any]]) -> int:
    """MERGE PLAYED relationships between Team nodes from game records.

    Args:
        driver: Open Neo4j driver.
        games: Raw game records as returned by ``fetch_games()``.

    Returns:
        Number of game records processed.
    """
    query = f"""
    UNWIND $rows AS row
    MATCH (home:{schema.TEAM} {{school: row.home_team}})
    MATCH (away:{schema.TEAM} {{school: row.away_team}})
    MERGE (home)-[r:{schema.PLAYED} {{game_id: row.id}}]->(away)
    SET r.home_score = row.home_points,
        r.away_score = row.away_points,
        r.season     = row.season,
        r.week       = row.week
    """
    with driver.session() as session:
        session.run(query, rows=games)
    logger.info("Loaded %d games", len(games))
    return len(games)
