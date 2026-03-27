#!/usr/bin/env python3
"""Authoring helper for the Nick Saban precomputed coaching tree narrative (F4b).

This script does TWO things depending on which flags you pass:

**Fetch mode (default)** — print a structured summary of Saban's coaching
tree so you can write a polished narrative by hand::

    python scripts/author_narrative_saban.py

**Save mode** — store a manually authored narrative file into Neo4j::

    python scripts/author_narrative_saban.py --save narratives/saban.txt

The narrative is stored as a ``narrative`` property on the McIllece Coach
node in Neo4j (keyed by ``coach_code``).  Once stored, the GraphRAG
retriever will use it automatically for any TREE_QUERY about Nick Saban.

For other coaches, supply ``--coach-code`` and optionally ``--coach-name``::

    python scripts/author_narrative_saban.py --coach-code 2345 --coach-name "Urban Meyer"
    python scripts/author_narrative_saban.py --coach-code 2345 --save narratives/meyer.txt

Requirements:
    .env file in the project root with NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD.
"""

import argparse
import os
import sys
import textwrap

# Ensure the project root is on sys.path when run as a script.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from dotenv import load_dotenv
from neo4j import GraphDatabase

from graphrag.entity_extractor import resolve_coach_entity
from graphrag.narratives import (
    get_coach_narrative,
    get_head_coach_tree_summary,
    set_coach_narrative,
)

load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))

# ---------------------------------------------------------------------------
# Default: Nick Saban.  Override via --coach-code / --coach-name.
# ---------------------------------------------------------------------------
_DEFAULT_COACH_NAME = "Nick Saban"


def _resolve_coach_code(coach_name: str, driver) -> int | None:
    """Return the McIllece coach_code for a display name, or None.

    Resolution order:
    1. CFBD node (first_name / last_name) → SAME_PERSON → McIllece node.
       Works only after load_identity_edges.py has been run.
    2. Direct McIllece ``name`` property match (case-insensitive contains).
       Fallback for when SAME_PERSON edges aren't loaded yet.
    """
    # 1. Try CFBD → SAME_PERSON → McIllece path.
    resolved = resolve_coach_entity(coach_name, driver=driver)
    mc_code = resolved.get("mc_coach_code")
    if mc_code is not None:
        return mc_code

    # 2. Fallback: search McIllece nodes by name property.
    parts = coach_name.strip().split()
    last_name = parts[-1] if parts else coach_name
    query = """
    MATCH (c:Coach)
    WHERE c.coach_code IS NOT NULL
      AND toLower(c.name) CONTAINS toLower($last_name)
    RETURN c.coach_code AS coach_code, c.name AS name
    ORDER BY c.name
    LIMIT 10
    """
    with driver.session() as session:
        result = session.run(query, last_name=last_name)
        rows = [{"coach_code": r["coach_code"], "name": r["name"]} for r in result]

    if not rows:
        return None

    if len(rows) == 1:
        print(f"Resolved via McIllece name search: {rows[0]['name']} (coach_code={rows[0]['coach_code']})")
        return rows[0]["coach_code"]

    # Multiple matches — show the list and let the user pick via --coach-code.
    print(f"Multiple McIllece matches for {last_name!r}:")
    for r in rows:
        print(f"  coach_code={r['coach_code']}  name={r['name']}")
    print("Re-run with --coach-code <code> to select the correct one.")
    return None


def _print_summary(coach_code: int, coach_name: str, driver) -> None:
    """Fetch and pretty-print the coaching tree summary."""
    print(f"\n{'='*70}")
    print(f"Coaching tree summary for: {coach_name} (coach_code={coach_code})")
    print(f"{'='*70}\n")

    summary = get_head_coach_tree_summary(coach_code=coach_code, driver=driver)

    # Build depth-grouped dicts for both HC and all mentees.
    hc_by_depth: dict[int, list] = {}
    for row in summary.hc_mentees:
        hc_by_depth.setdefault(row.depth, []).append(row)

    all_by_depth: dict[int, list] = {}
    for row in summary.all_mentees:
        all_by_depth.setdefault(row.depth, []).append(row.name)

    # --- headline counts ---
    depth_breakdown = "  |  ".join(
        f"d{d}: {len(all_by_depth[d])}" for d in sorted(all_by_depth)
    )
    print(
        f"Total mentees (all roles, depth 1–4): {summary.total_mentees}"
        f"  ({depth_breakdown})\n"
        f"Head coach (HC) mentees:              {summary.hc_mentee_count}"
    )
    hc_depth_breakdown = "  |  ".join(
        f"d{d}: {len(hc_by_depth[d])}" for d in sorted(hc_by_depth)
    )
    if hc_depth_breakdown:
        print(f"  HC by depth:                          {hc_depth_breakdown}")
    print()

    if summary.hc_mentees:
        print("Head coach mentees (depth-sorted):")
        for row in summary.hc_mentees:
            path_str = " → ".join(row.path_coaches)
            print(f"  depth {row.depth}  {row.name:<30}  path: {path_str}")
    else:
        print("No HC mentees found.")

    print(f"\n{'='*70}")
    print("All mentees (any role):")
    for depth in sorted(all_by_depth):
        names = ", ".join(sorted(all_by_depth[depth]))
        count = len(all_by_depth[depth])
        wrapped = textwrap.fill(names, width=66, subsequent_indent="          ")
        print(f"  depth {depth} ({count}): {wrapped}")

    print(f"\n{'='*70}")
    print("NEXT STEP: write a polished narrative and save it to a .txt file,")
    print("then run:")
    print(
        f"  python scripts/author_narrative_saban.py "
        f"--coach-code {coach_code} --save <narrative_file.txt>"
    )
    print(f"{'='*70}\n")


def _save_narrative(coach_code: int, narrative_path: str, driver) -> None:
    """Read narrative from file and store it on the Coach node."""
    if not os.path.isfile(narrative_path):
        print(f"ERROR: file not found: {narrative_path}", file=sys.stderr)
        sys.exit(1)

    with open(narrative_path, encoding="utf-8") as fh:
        narrative = fh.read().strip()

    if not narrative:
        print("ERROR: narrative file is empty.", file=sys.stderr)
        sys.exit(1)

    print(f"Storing narrative ({len(narrative)} chars) for coach_code={coach_code} …")
    try:
        set_coach_narrative(coach_code=coach_code, narrative=narrative, driver=driver)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    # Verify round-trip.
    stored = get_coach_narrative(coach_code=coach_code, driver=driver)
    if stored and stored.strip() == narrative:
        print("Narrative stored and verified successfully.")
    else:
        print("WARNING: stored narrative does not match input — check Neo4j.", file=sys.stderr)


def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="Author and store a precomputed coaching tree narrative (F4b).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--coach-code",
        type=int,
        default=None,
        help=(
            "McIllece coach_code for the target coach.  "
            "If omitted, the script resolves Nick Saban automatically."
        ),
    )
    parser.add_argument(
        "--coach-name",
        default=_DEFAULT_COACH_NAME,
        help=f"Display name used for coach_code resolution (default: {_DEFAULT_COACH_NAME!r}).",
    )
    parser.add_argument(
        "--save",
        metavar="NARRATIVE_FILE",
        default=None,
        help=(
            "Path to a plain-text file containing the manually authored narrative. "
            "When supplied, the narrative is stored in Neo4j instead of printing the summary."
        ),
    )
    args = parser.parse_args()

    # --- connect to Neo4j ---
    uri = os.environ.get("NEO4J_URI")
    user = os.environ.get("NEO4J_USERNAME")
    password = os.environ.get("NEO4J_PASSWORD")
    if not all([uri, user, password]):
        print(
            "ERROR: NEO4J_URI, NEO4J_USERNAME, and NEO4J_PASSWORD must be set in .env.",
            file=sys.stderr,
        )
        sys.exit(1)

    driver = GraphDatabase.driver(uri, auth=(user, password))

    try:
        # --- resolve coach_code ---
        coach_code = args.coach_code
        if coach_code is None:
            coach_code = _resolve_coach_code(args.coach_name, driver)
            if coach_code is None:
                print(
                    f"ERROR: Could not resolve McIllece coach_code for {args.coach_name!r}.\n"
                    "Check that the SAME_PERSON identity edges are loaded "
                    "(run loader/load_identity_edges.py) or supply --coach-code directly.",
                    file=sys.stderr,
                )
                sys.exit(1)
            print(f"Resolved {args.coach_name!r} → coach_code={coach_code}")

        if args.save:
            _save_narrative(
                coach_code=coach_code,
                narrative_path=args.save,
                driver=driver,
            )
        else:
            _print_summary(
                coach_code=coach_code,
                coach_name=args.coach_name,
                driver=driver,
            )
    finally:
        driver.close()


if __name__ == "__main__":
    main()
