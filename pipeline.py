#!/usr/bin/env python3
"""Full ingestion → Neo4j load → verification pipeline for CFB GraphRAG.

Run from the project root:
    python pipeline.py             # ingest + load + verify
    python pipeline.py --validate  # same, plus A1 data validation report

Steps:
    1. Pull raw data from CFBD API (skips files that already exist).
    2. Normalize API payloads to the shape the loaders expect.
    3. Create Neo4j uniqueness constraints for fast MERGE operations.
    4. Load: Teams → Conferences → Coaches → Players → Games.
    5. Run 5 verification Cypher queries and print counts.
    6. (--validate only) Run A1 ground-truth validation + anomaly checks.

Note on load order: Teams must be loaded before Conferences because
``load_conferences`` creates IN_CONFERENCE relationships that require Team
nodes to already exist.  The stated order (Conferences → Teams) is achieved
logically here by loading Teams first, then completing the Conferences step.
"""

import argparse
import os
import sys
import logging
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent / ".env")
sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

from ingestion.pull_teams import fetch_teams
from ingestion.pull_coaches import fetch_coaches
from ingestion.pull_rosters import fetch_rosters
from ingestion.pull_games import fetch_games
from loader.neo4j_loader import (
    get_driver,
    load_conferences,
    load_teams,
    load_coaches,
    load_players,
    load_games,
)

CFBD_KEY = os.environ["CFBD_API_KEY"]
NEO4J_URI = os.environ["NEO4J_URI"]
NEO4J_USER = os.environ["NEO4J_USERNAME"]
NEO4J_PASS = os.environ["NEO4J_PASSWORD"]

_PLAYER_BATCH = 2_000
_GAME_BATCH = 2_000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def section(title: str) -> None:
    """Print a section header."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print("=" * 60)


def normalize_coaches(raw: list[dict]) -> list[dict]:
    """Convert CFBD camelCase coach records to the snake_case shape the loader expects.

    The CFBD /coaches endpoint returns ``firstName`` / ``lastName``; the loader
    (and its MERGE keys) expect ``first_name`` / ``last_name``.

    Args:
        raw: Raw coach records from ``fetch_coaches()``.

    Returns:
        Normalized coach records ready for ``load_coaches()``.
    """
    return [
        {
            "first_name": c.get("firstName", ""),
            "last_name": c.get("lastName", ""),
            "seasons": c.get("seasons", []),
        }
        for c in raw
        if c.get("firstName") and c.get("lastName")
    ]


def normalize_players(raw: list[dict]) -> list[dict]:
    """Convert CFBD camelCase roster records to the snake_case shape the loader expects.

    The CFBD /roster endpoint returns camelCase fields; the loader and the
    Player schema expect ``name`` (full name), ``hometown``, etc.

    Uses ``season_year`` (injected by ``fetch_rosters``) for the PLAYED_FOR
    year, because the CFBD ``year`` field is the player's academic year
    (1 = Freshman), not the calendar season.

    Filters out records that lack an ``id`` or ``team`` (required MERGE fields).

    Args:
        raw: Raw roster records from ``fetch_rosters()`` (with ``season_year`` injected).

    Returns:
        Normalized player records ready for ``load_players()``.
    """
    out = []
    for r in raw:
        pid = r.get("id")
        team = r.get("team")
        if pid is None or not team:
            continue
        city = r.get("homeCity") or ""
        state = r.get("homeState") or ""
        hometown = ", ".join(p for p in [city, state] if p)
        out.append(
            {
                "id": pid,
                "name": f"{r.get('firstName', '')} {r.get('lastName', '')}".strip(),
                "position": r.get("position") or "",
                "hometown": hometown,
                "team": team,
                "year": r.get("season_year"),   # calendar season, not academic year
                "jersey": r.get("jersey"),
            }
        )
    return out


def normalize_games(raw: list[dict]) -> list[dict]:
    """Convert CFBD camelCase game records to the snake_case shape the loader expects.

    The CFBD /games endpoint uses camelCase (``homeTeam``, ``homePoints``, etc.);
    ``load_games`` Cypher accesses ``row.home_team`` / ``row.away_team`` etc.

    Filters out records missing a home or away team name.

    Args:
        raw: Raw game records from ``fetch_games()``.

    Returns:
        Normalized game records ready for ``load_games()``.
    """
    out = []
    for g in raw:
        home = g.get("homeTeam")
        away = g.get("awayTeam")
        if not home or not away:
            continue
        out.append(
            {
                "id": g.get("id"),
                "home_team": home,
                "away_team": away,
                "home_points": g.get("homePoints"),
                "away_points": g.get("awayPoints"),
                "season": g.get("season"),
                "week": g.get("week"),
            }
        )
    return out


def create_constraints(driver) -> None:
    """Create uniqueness constraints so MERGE operations use index lookups.

    Args:
        driver: Open Neo4j driver.
    """
    constraints = [
        "CREATE CONSTRAINT team_id IF NOT EXISTS FOR (t:Team) REQUIRE t.id IS UNIQUE",
        "CREATE CONSTRAINT player_id IF NOT EXISTS FOR (p:Player) REQUIRE p.id IS UNIQUE",
        "CREATE CONSTRAINT conference_name IF NOT EXISTS FOR (c:Conference) REQUIRE c.name IS UNIQUE",
    ]
    with driver.session() as session:
        for q in constraints:
            session.run(q)
    print("  Constraints created/verified.")


def run_query(driver, title: str, query: str) -> list[dict]:
    """Execute a read query, print the title and each row, and return rows.

    Args:
        driver: Open Neo4j driver.
        title: Human-readable label printed before the results.
        query: Cypher read query.

    Returns:
        List of result rows as plain dicts.
    """
    print(f"\n--- {title} ---")
    with driver.session() as session:
        result = session.run(query)
        rows = [dict(r) for r in result]
    for row in rows:
        print(f"  {row}")
    if not rows:
        print("  (no results)")
    return rows


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the full ingestion, load, and verification pipeline."""
    parser = argparse.ArgumentParser(description="CFB GraphRAG ingestion pipeline.")
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Run A1 data validation report after ingestion (ground-truth + anomaly checks).",
    )
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Step 1: Ingestion
    # ------------------------------------------------------------------
    section("STEP 1: INGESTION")

    print("Fetching teams...")
    teams = fetch_teams(CFBD_KEY)
    print(f"  [OK] teams.json  —  {len(teams):,} records")

    print("Fetching coaches...")
    raw_coaches = fetch_coaches(CFBD_KEY)
    print(f"  [OK] coaches.json  —  {len(raw_coaches):,} records")

    print("Fetching rosters 2015–2025...")
    raw_rosters = fetch_rosters(CFBD_KEY)
    print(f"  [OK] roster_YYYY.json files  —  {len(raw_rosters):,} records total")

    print("Fetching games 2015–2025...")
    games = fetch_games(CFBD_KEY)
    print(f"  [OK] games_YYYY.json files  —  {len(games):,} records total")

    # ------------------------------------------------------------------
    # Step 2: Normalize
    # ------------------------------------------------------------------
    section("STEP 2: NORMALIZING PAYLOADS")

    coaches = normalize_coaches(raw_coaches)
    print(f"  Coaches normalized: {len(coaches):,}")

    players = normalize_players(raw_rosters)
    print(f"  Players normalized: {len(players):,}  (filtered from {len(raw_rosters):,} raw records)")

    raw_game_count = len(games)
    games = normalize_games(games)
    print(f"  Games normalized:   {len(games):,}  (filtered from {raw_game_count:,} raw records)")

    # ------------------------------------------------------------------
    # Step 3: Load into Neo4j
    # ------------------------------------------------------------------
    section("STEP 3: LOADING INTO NEO4J")

    driver = get_driver(NEO4J_URI, NEO4J_USER, NEO4J_PASS)

    print("Creating constraints...")
    create_constraints(driver)

    # Teams must come before Conferences so IN_CONFERENCE MATCHes find Team nodes
    print(f"Loading Teams ({len(teams):,})...")
    n = load_teams(driver, teams)
    print(f"  [OK] {n:,} teams")

    print("Loading Conferences (+ IN_CONFERENCE relationships)...")
    n = load_conferences(driver, teams)
    print(f"  [OK] {n:,} unique conferences")

    print(f"Loading Coaches ({len(coaches):,})...")
    n = load_coaches(driver, coaches)
    print(f"  [OK] {n:,} coaches")

    print(f"Loading Players in batches of {_PLAYER_BATCH:,}...")
    loaded = 0
    for i in range(0, len(players), _PLAYER_BATCH):
        batch = players[i : i + _PLAYER_BATCH]
        load_players(driver, batch)
        loaded += len(batch)
    print(f"  [OK] {loaded:,} player-season records")

    print(f"Loading Games in batches of {_GAME_BATCH:,}...")
    loaded_g = 0
    for i in range(0, len(games), _GAME_BATCH):
        batch = games[i : i + _GAME_BATCH]
        load_games(driver, batch)
        loaded_g += len(batch)
    print(f"  [OK] {loaded_g:,} game records")

    # ------------------------------------------------------------------
    # Step 4: Verification queries
    # ------------------------------------------------------------------
    section("STEP 4: VERIFICATION QUERIES")

    # Q1 — Node counts by label
    node_rows = run_query(
        driver,
        "Node counts by label",
        "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS count ORDER BY count DESC",
    )

    # Q2 — Relationship counts by type
    rel_rows = run_query(
        driver,
        "Relationship counts by type",
        "MATCH ()-[r]->() RETURN type(r) AS rel_type, count(*) AS count ORDER BY count DESC",
    )

    # Q3 — 5 coaches with teams and years
    run_query(
        driver,
        "Sample COACHED_AT (5 rows)",
        """
        MATCH (c:Coach)-[r:COACHED_AT]->(t:Team)
        RETURN c.first_name + ' ' + c.last_name AS coach,
               t.school AS team,
               r.start_year AS year
        ORDER BY coach, year
        LIMIT 5
        """,
    )

    # Q4 — 5 players with team and year
    run_query(
        driver,
        "Sample PLAYED_FOR (5 rows)",
        """
        MATCH (p:Player)-[r:PLAYED_FOR]->(t:Team)
        RETURN p.name AS player, t.school AS team, r.year AS year
        ORDER BY team, year
        LIMIT 5
        """,
    )

    # Q5 — All SEC teams
    run_query(
        driver,
        "All teams IN_CONFERENCE SEC",
        """
        MATCH (t:Team)-[:IN_CONFERENCE]->(c:Conference {name: 'SEC'})
        RETURN t.school AS school
        ORDER BY school
        """,
    )

    # ------------------------------------------------------------------
    # Step 5: Sanity check
    # ------------------------------------------------------------------
    section("STEP 5: SANITY CHECK")

    label_counts = {r["label"]: r["count"] for r in node_rows}
    rel_counts = {r["rel_type"]: r["count"] for r in rel_rows}

    issues = []
    for label in ("Team", "Coach", "Player", "Conference"):
        if label_counts.get(label, 0) == 0:
            issues.append(f"  WARN: zero {label} nodes")
    for rel in ("COACHED_AT", "PLAYED_FOR", "IN_CONFERENCE", "PLAYED"):
        if rel_counts.get(rel, 0) == 0:
            issues.append(f"  WARN: zero {rel} relationships")

    if issues:
        print("Issues detected:")
        for msg in issues:
            print(msg)
    else:
        print("  All expected node labels and relationship types are present.")

    driver.close()
    print("\nPipeline complete.")

    # ------------------------------------------------------------------
    # Step 6: A1 validation (--validate flag)
    # ------------------------------------------------------------------
    if args.validate:
        section("STEP 6: A1 DATA VALIDATION")
        driver = get_driver(NEO4J_URI, NEO4J_USER, NEO4J_PASS)
        try:
            from agents.data_validation.validate import run_validation
            from agents.data_validation.anomaly_checks import run_anomaly_checks
            failures = run_validation(driver)
            critical = run_anomaly_checks(driver)
            if failures == 0 and critical == 0:
                print("\n  A1: all checks passed.")
            else:
                print(f"\n  A1: {failures} ground-truth failure(s), {critical} critical anomaly(s).")
                sys.exit(1)
        finally:
            driver.close()


if __name__ == "__main__":
    main()
