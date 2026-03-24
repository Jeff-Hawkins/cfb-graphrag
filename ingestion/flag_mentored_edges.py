"""Flag MENTORED edges where the inferred direction may be semantically reversed.

The MENTORED edge inference uses ROLE_PRIORITY (HC > OC/DC > position coach)
to assign direction during staff overlap periods.  This works correctly in
most cases but fails when a coach who previously held a higher-career-trajectory
role later joins a younger coach's staff in a supporting capacity.

Canonical example: Ruffin McNeill was HC at ECU (2010-2015) and hired Lincoln
Riley as his OC.  He later joined Riley's Oklahoma staff (2017-2021) as
assistant HC.  The graph correctly infers Riley as mentor for the OU overlap,
but McNeill's prior HC career makes this semantically suspect.

Two detection paths are used:

1. **Automated detection** — queries all McIllece-sourced MENTORED edges
   where the mentee held any HC or coordinator-tier role at *any* program
   *before* the earliest shared year with their inferred mentor.

2. **KNOWN_REVERSE** — hardcoded pairs confirmed by domain knowledge,
   applied regardless of the automated check result.

Note on FCS filter
------------------
The task spec asks to skip flagging when the mentee's prior HC/coordinator
role was at an FCS or lower program and the mentor is at a P4 program (standard
career progression).  This filter is **not applied** because ``Team`` nodes
do not carry a ``division`` property that would reliably distinguish FBS/FCS.
Every flagged edge should be reviewed manually; the report records this
limitation explicitly.

Usage (standalone)::

    python -m ingestion.flag_mentored_edges
"""

from __future__ import annotations

import logging
import os
from datetime import date
from pathlib import Path
from typing import Any

from neo4j import Driver

# Import coordinator-tier abbreviations from the canonical role constants file.
# COORDINATOR_ROLES covers HC, OC, DC, plus ST and RC as coordinator-level titles,
# and the pass/rush coordinator variants (PG, PD, RG, RD).  AC is excluded because
# it is often a courtesy title rather than an independent coordinator responsibility.
from ingestion.role_constants import COORDINATOR_ROLES

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONFIDENCE_STANDARD = "STANDARD"
CONFIDENCE_REVIEW_REVERSE = "REVIEW_REVERSE"
CONFIDENCE_REVIEW_MUTUAL = "REVIEW_MUTUAL"

# Role abbreviations that qualify as "significant prior career experience"
# when held by a mentee *before* the overlap period that generated the edge.
# Sourced from role_constants.COORDINATOR_ROLES — do not hardcode here.
_PRIOR_ROLE_ABBRS: frozenset[str] = frozenset(COORDINATOR_ROLES)

# Default report path (relative to project root)
_PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_REPORT_PATH = _PROJECT_ROOT / "reports" / "mentored_flag_report.md"

# ---------------------------------------------------------------------------
# Known reverse pairs — confirmed by domain knowledge
# ---------------------------------------------------------------------------

# Each tuple: (mentee_name_tokens, mentor_name_tokens, rationale)
# Name tokens are matched with AND logic against the Neo4j Coach.name property.
# coach_codes are resolved from Neo4j at runtime — never hardcoded.
_KNOWN_REVERSE_SPECS: list[tuple[str, str, str]] = [
    (
        "Ruffin McNeill",  # mentee: was HC at ECU before joining Riley's OU staff
        "Lincoln Riley",   # mentor: inferred mentor for OU overlap (2017-2021)
        (
            "McNeill was HC at East Carolina (2010-2015) and hired Lincoln Riley "
            "as his OC.  He later joined Riley's Oklahoma staff (2017-2021) as "
            "assistant HC.  The graph correctly infers Riley as mentor for the OU "
            "overlap, but McNeill's prior HC career makes this semantically suspect."
        ),
    ),
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _lookup_coach_code(driver: Driver, name_contains: str) -> int | None:
    """Return the McIllece ``coach_code`` for a coach whose name contains all tokens.

    Splits *name_contains* on whitespace and requires every token to appear
    (case-insensitive) in the coach's ``name`` property.  When multiple coaches
    match, logs a warning and returns the one with the smallest ``coach_code``.

    Args:
        driver: Open Neo4j driver.
        name_contains: Space-separated name tokens (e.g. ``"Ruffin McNeill"``).

    Returns:
        Integer ``coach_code``, or ``None`` when no match is found.
    """
    tokens = name_contains.strip().split()
    if not tokens:
        return None

    conditions = " AND ".join(
        f"toLower(c.name) CONTAINS toLower($tok{i})" for i in range(len(tokens))
    )
    query = f"""
    MATCH (c:Coach)
    WHERE {conditions} AND c.coach_code IS NOT NULL
    RETURN c.coach_code AS code, c.name AS name
    ORDER BY c.coach_code
    """
    params = {f"tok{i}": tok for i, tok in enumerate(tokens)}

    with driver.session() as session:
        result = session.run(query, **params)
        records = [r.data() for r in result]

    if not records:
        logger.warning("KNOWN_REVERSE lookup: no McIllece coach matches %r", name_contains)
        return None
    if len(records) > 1:
        logger.warning(
            "KNOWN_REVERSE lookup: multiple coaches match %r: %s — using coach_code=%s",
            name_contains,
            [r["name"] for r in records],
            records[0]["code"],
        )
    return int(records[0]["code"])


def _resolve_known_reverse(driver: Driver) -> dict[tuple[int, int], str]:
    """Resolve ``_KNOWN_REVERSE_SPECS`` into ``(mentee_code, mentor_code)`` → rationale.

    Looks up ``coach_code`` from Neo4j for each entry.  Entries where either
    coach cannot be found are skipped with a warning.

    Args:
        driver: Open Neo4j driver.

    Returns:
        Dict mapping ``(mentee_code, mentor_code)`` → rationale string.
    """
    known: dict[tuple[int, int], str] = {}
    for mentee_name, mentor_name, rationale in _KNOWN_REVERSE_SPECS:
        mentee_code = _lookup_coach_code(driver, mentee_name)
        mentor_code = _lookup_coach_code(driver, mentor_name)
        if mentee_code is None or mentor_code is None:
            logger.warning(
                "KNOWN_REVERSE: skipping %r / %r — could not resolve coach_code(s)",
                mentee_name,
                mentor_name,
            )
            continue
        known[(mentee_code, mentor_code)] = rationale
        logger.info(
            "KNOWN_REVERSE resolved: mentee=%r (code=%d), mentor=%r (code=%d)",
            mentee_name,
            mentee_code,
            mentor_name,
            mentor_code,
        )
    return known


def _detect_automated_flags(
    driver: Driver,
    coord_abbrs: frozenset[str],
) -> list[dict[str, Any]]:
    """Query MENTORED edges where the mentee held a prior HC/coordinator role.

    For each McIllece-sourced MENTORED edge (mentor → mentee), determines the
    earliest shared calendar year across all teams where both coaches appear in
    ``source='mcillece_roles'`` COACHED_AT edges.  If the mentee held any
    HC or coordinator-tier role at *any* program *before* that shared year, the
    edge is returned for flagging.

    **FCS filter not applied** — Team nodes lack a ``division`` property; all
    prior coordinator roles are included regardless of program level.

    Args:
        driver: Open Neo4j driver.
        coord_abbrs: Role abbreviations that qualify as coordinator-tier prior
            experience (passed as a list to the Cypher ``IN`` clause).

    Returns:
        List of dicts, one per flagged edge, with keys:
        ``mentor_code``, ``mentor_name``, ``mentee_code``, ``mentee_name``,
        ``overlap_start`` (earliest shared year int), ``prior_roles`` (list of
        ``{year, role, team}`` dicts).
    """
    query = """
    MATCH (mentor:Coach)-[m:MENTORED]->(mentee:Coach)
    WHERE mentor.coach_code IS NOT NULL AND mentee.coach_code IS NOT NULL
    MATCH (mentor)-[r1:COACHED_AT {source: 'mcillece_roles'}]->(t:Team)
    MATCH (mentee)-[r2:COACHED_AT {source: 'mcillece_roles'}]->(t)
    WHERE r1.year = r2.year
    WITH mentor, mentee, min(r1.year) AS overlap_start
    MATCH (mentee)-[r3:COACHED_AT {source: 'mcillece_roles'}]->(prior_prog:Team)
    WHERE r3.role_abbr IN $coord_abbrs AND r3.year < overlap_start
    RETURN
        mentor.coach_code  AS mentor_code,
        mentor.name        AS mentor_name,
        mentee.coach_code  AS mentee_code,
        mentee.name        AS mentee_name,
        overlap_start,
        collect(DISTINCT {year: r3.year, role: r3.role_abbr, team: prior_prog.school})
            AS prior_roles
    ORDER BY mentee_name, mentor_name
    """
    with driver.session() as session:
        result = session.run(query, coord_abbrs=list(coord_abbrs))
        records = [r.data() for r in result]

    logger.info(
        "Automated detection: %d MENTORED edge(s) flagged for %s",
        len(records),
        CONFIDENCE_REVIEW_REVERSE,
    )
    return records


def _fetch_coach_names(driver: Driver, coach_codes: list[int]) -> dict[int, str]:
    """Fetch display names for the given McIllece coach_codes.

    Args:
        driver: Open Neo4j driver.
        coach_codes: List of integer coach_codes to look up.

    Returns:
        Dict mapping ``coach_code`` → ``name`` string.
    """
    if not coach_codes:
        return {}
    query = """
    UNWIND $codes AS code
    MATCH (c:Coach {coach_code: code})
    RETURN c.coach_code AS code, c.name AS name
    """
    with driver.session() as session:
        result = session.run(query, codes=coach_codes)
        return {r.data()["code"]: r.data()["name"] for r in result}


def _apply_flags(driver: Driver, flagged_edges: list[dict[str, Any]]) -> int:
    """Set ``confidence_flag = 'REVIEW_REVERSE'`` on the given MENTORED edges.

    Matches each edge by ``(mentor_code, mentee_code)``.  Idempotent — setting
    the same flag value on an already-flagged edge has no effect.

    Args:
        driver: Open Neo4j driver.
        flagged_edges: Edge dicts, each with ``mentor_code`` and ``mentee_code``
            keys (as returned by ``_detect_automated_flags`` or combined with
            KNOWN_REVERSE entries).

    Returns:
        Number of SET operations issued (equals ``len(flagged_edges)``).
    """
    if not flagged_edges:
        return 0

    rows = [
        {"mentor_code": int(e["mentor_code"]), "mentee_code": int(e["mentee_code"])}
        for e in flagged_edges
    ]
    query = """
    UNWIND $rows AS row
    MATCH (mentor:Coach {coach_code: row.mentor_code})
          -[m:MENTORED]->
          (mentee:Coach {coach_code: row.mentee_code})
    SET m.confidence_flag = $flag
    """
    with driver.session() as session:
        session.run(query, rows=rows, flag=CONFIDENCE_REVIEW_REVERSE)

    logger.info(
        "Applied confidence_flag='%s' to %d MENTORED edge(s)",
        CONFIDENCE_REVIEW_REVERSE,
        len(rows),
    )
    return len(rows)


def _generate_report(
    flagged_edges: list[dict[str, Any]],
    known_reverse: dict[tuple[int, int], str],
    report_path: Path,
) -> None:
    """Write a structured Markdown report of all flagged MENTORED edges.

    Args:
        flagged_edges: Combined list of automated + KNOWN_REVERSE flagged edges.
        known_reverse: Resolved ``(mentee_code, mentor_code)`` → rationale.
        report_path: Output file path.  Parent directory is created if needed.
    """
    report_path.parent.mkdir(parents=True, exist_ok=True)

    known_pairs: set[tuple[int, int]] = set(known_reverse.keys())
    automated_count = sum(1 for e in flagged_edges if e.get("_automated"))
    known_only_count = sum(
        1
        for e in flagged_edges
        if e.get("_known_reverse") and not e.get("_automated")
    )

    lines = [
        "# MENTORED Edge Confidence Flag Report",
        "",
        f"Generated: {date.today().isoformat()}",
        "",
        "## Configuration",
        "",
        f"- Role abbreviations used for prior-career check: "
        f"`{sorted(_PRIOR_ROLE_ABBRS)}`",
        "- **FCS division filter: NOT APPLIED** — `Team` nodes do not carry a "
        "`division` property.",
        "  All prior HC/coordinator roles are included regardless of program level.",
        "  Some flagged entries may represent standard FCS→FBS career progressions;",
        "  these should be reviewed manually and retained as `STANDARD` if appropriate.",
        "",
        "## Summary",
        "",
        f"- Total edges flagged as `{CONFIDENCE_REVIEW_REVERSE}`: "
        f"**{len(flagged_edges)}**",
        f"- Automated detections: **{automated_count}**",
        f"- KNOWN_REVERSE only (domain knowledge, not caught by automation): "
        f"**{known_only_count}**",
        "",
        "## Flagged Edges",
        "",
    ]

    if not flagged_edges:
        lines.append("_No edges flagged._")
    else:
        for i, edge in enumerate(flagged_edges, 1):
            mentor_code = edge.get("mentor_code")
            mentee_code = edge.get("mentee_code")
            mentor_name = edge.get("mentor_name") or f"coach_code={mentor_code}"
            mentee_name = edge.get("mentee_name") or f"coach_code={mentee_code}"
            overlap_start = edge.get("overlap_start", "unknown")
            prior_roles: list[dict[str, Any]] = edge.get("prior_roles") or []
            is_known = (mentee_code, mentor_code) in known_pairs

            lines.append(
                f"### {i}. Mentee: {mentee_name} | Mentor: {mentor_name}"
            )
            lines.append("")

            source_parts = []
            if edge.get("_automated"):
                source_parts.append("automated detection")
            if edge.get("_known_reverse"):
                source_parts.append("KNOWN_REVERSE (domain knowledge)")
            lines.append(f"**Source:** {', '.join(source_parts) or 'unknown'}")

            if is_known:
                rationale = known_reverse.get((mentee_code, mentor_code), "")
                lines.append(f"**Rationale:** {rationale}")

            lines.append(f"**Earliest overlap year with mentor:** {overlap_start}")

            if prior_roles:
                lines.append(
                    "**Mentee's prior HC/coordinator role(s) before overlap:**"
                )
                for pr in sorted(prior_roles, key=lambda x: x.get("year", 0)):
                    lines.append(
                        f"  - `{pr.get('role', '?')}` at "
                        f"{pr.get('team', '?')} ({pr.get('year', '?')})"
                    )

            lines.append("")

    report_path.write_text("\n".join(lines))
    logger.info("Report written to %s (%d edge(s))", report_path, len(flagged_edges))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def flag_suspicious_mentored_edges(
    driver: Driver,
    known_reverse: dict[tuple[int, int], str] | None = None,
    report_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Flag MENTORED edges where the inferred direction may be semantically reversed.

    Steps:

    1. **Automated detection** — query MENTORED edges (McIllece-sourced) where
       the mentee held any HC or coordinator-tier role before the earliest
       shared year with their inferred mentor.
    2. **KNOWN_REVERSE** — apply hardcoded pairs confirmed by domain knowledge,
       regardless of the automated check result.
    3. **SET** ``confidence_flag = 'REVIEW_REVERSE'`` on all flagged edges.
    4. **Report** — write a structured Markdown report to *report_path*.

    **FCS division filter not applied**: the ``Team`` schema lacks a
    ``division`` property.  All prior coordinator roles are checked regardless
    of program level.  A note is included in the report.

    Args:
        driver: Open Neo4j driver.
        known_reverse: Optional pre-resolved ``(mentee_code, mentor_code)`` →
            rationale dict.  When ``None``, ``_resolve_known_reverse(driver)``
            is called to look up coach_codes from Neo4j.  Pass an explicit dict
            in tests to bypass live lookups.
        report_path: Destination for the Markdown report.  Defaults to
            ``reports/mentored_flag_report.md`` relative to the project root.

    Returns:
        Combined list of flagged edge dicts (automated + KNOWN_REVERSE),
        deduplicated by ``(mentor_code, mentee_code)``.  Each dict has at
        minimum ``mentor_code``, ``mentor_name``, ``mentee_code``,
        ``mentee_name``, ``overlap_start``, and ``prior_roles`` keys.
    """
    if report_path is None:
        report_path = DEFAULT_REPORT_PATH

    # 1. Automated detection.
    automated = _detect_automated_flags(driver, _PRIOR_ROLE_ABBRS)
    # Key: (mentor_code, mentee_code) — the edge direction in the graph.
    combined: dict[tuple[int, int], dict[str, Any]] = {}
    for edge in automated:
        key = (int(edge["mentor_code"]), int(edge["mentee_code"]))
        edge["_automated"] = True
        combined[key] = edge
        logger.info(
            "REVIEW_REVERSE (auto): mentee=%s (code=%s) | mentor=%s (code=%s) | "
            "overlap_start=%s | prior_roles=%s",
            edge.get("mentee_name", edge["mentee_code"]),
            edge["mentee_code"],
            edge.get("mentor_name", edge["mentor_code"]),
            edge["mentor_code"],
            edge.get("overlap_start"),
            [
                f"{r.get('role')}@{r.get('team')}({r.get('year')})"
                for r in (edge.get("prior_roles") or [])[:3]
            ],
        )

    # 2. Resolve KNOWN_REVERSE.
    if known_reverse is None:
        known_reverse = _resolve_known_reverse(driver)

    for (mentee_code, mentor_code), rationale in known_reverse.items():
        key = (int(mentor_code), int(mentee_code))  # (mentor, mentee) = edge direction
        if key not in combined:
            # Fetch names so the report is readable.
            names = _fetch_coach_names(driver, [mentor_code, mentee_code])
            combined[key] = {
                "mentor_code": int(mentor_code),
                "mentor_name": names.get(mentor_code, ""),
                "mentee_code": int(mentee_code),
                "mentee_name": names.get(mentee_code, ""),
                "overlap_start": None,
                "prior_roles": [],
                "_automated": False,
            }
        combined[key]["_known_reverse"] = True
        combined[key]["_rationale"] = rationale
        logger.info(
            "REVIEW_REVERSE (known): mentee=%s (code=%s) | mentor=%s (code=%s) | %s",
            combined[key].get("mentee_name") or mentee_code,
            mentee_code,
            combined[key].get("mentor_name") or mentor_code,
            mentor_code,
            rationale[:80],
        )

    all_flagged = list(combined.values())

    # 3. Apply flags to Neo4j.
    _apply_flags(driver, all_flagged)

    # 4. Generate report.
    _generate_report(all_flagged, known_reverse, report_path)

    return all_flagged


# ---------------------------------------------------------------------------
# Standalone entry-point
# ---------------------------------------------------------------------------


def _run() -> None:
    """Run edge flagging against live Neo4j (reads credentials from .env)."""
    from dotenv import load_dotenv

    load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

    from loader.neo4j_loader import get_driver

    driver = get_driver(
        os.environ["NEO4J_URI"],
        os.environ["NEO4J_USERNAME"],
        os.environ["NEO4J_PASSWORD"],
    )
    try:
        flagged = flag_suspicious_mentored_edges(driver)
        print(f"Flagged {len(flagged):,} MENTORED edge(s) as REVIEW_REVERSE.")
        print(f"Report: {DEFAULT_REPORT_PATH}")
    finally:
        driver.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    _run()
