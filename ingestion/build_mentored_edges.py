"""Infer MENTORED coaching-tree edges from COACHED_AT relationships in Neo4j.

Two coaches are considered to have a mentor/mentee relationship if they
overlapped on the same staff — same school, at least one shared season.
The more senior coach (earlier first year at that school) is the mentor.
If both coaches first joined that school in the same year the direction
cannot be determined and the pair is skipped.

For McIllece data (which includes per-season roles), seniority is
determined first by role priority (HC > OC > DC > all others) and falls
back to earlier first appearance year when role priorities are tied.

Usage (standalone):
    python -m ingestion.build_mentored_edges
"""

import csv
import logging
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from neo4j import Driver

from ingestion.role_constants import same_unit

logger = logging.getLogger(__name__)

# Role priority for McIllece data: higher number = more senior.
# Any role not listed here gets priority 0 (position coach).
ROLE_PRIORITY: dict[str, int] = {
    "HC": 3,
    "OC": 2,
    "DC": 2,
}

# ---------------------------------------------------------------------------
# Constants for v2 MENTORED inference (mcillece_roles source)
# ---------------------------------------------------------------------------

# Role abbreviations that qualify a coach to be a mentor (COORDINATOR tier).
# Mirrors expand_roles._COORDINATOR_ABBRS.
_MENTOR_ABBRS: frozenset[str] = frozenset({"HC", "AC", "OC", "DC", "PG", "PD", "RG", "RD"})

# Priority for picking the "best" coordinator role label when a coach held
# multiple coordinator roles during the overlap window.  HC is always best.
_MENTOR_ROLE_PRIORITY: dict[str, int] = {
    "HC": 4,
    "AC": 3,
    "OC": 2,
    "DC": 2,
    "PG": 1,
    "PD": 1,
    "RG": 1,
    "RD": 1,
}

# Role abbreviations that qualify as "same-level coordinator peers" for Rule 2.
# If both the potential mentor AND mentee held any of these roles at the same
# program in the same year, the pair is considered peers — no MENTORED edge.
_COORD_PEER_ROLES: frozenset[str] = frozenset({"OC", "DC"})


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
# McIllece-specific inference (role-aware)
# ---------------------------------------------------------------------------


def infer_mentored_pairs_mcillece(
    staff: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Infer MENTORED pairs from McIllece staff records using role priority.

    Algorithm:
    1. Group stints by ``team`` (school name).
    2. For each school, build a map of ``coach_code`` → ``{year: [roles]}``.
    3. For every unique pair of coaches at that school, check whether their
       year-sets intersect (≥ 2 shared seasons).
    4. If they overlap, determine the mentor:
       a. Compute each coach's *best* role priority across the overlapping
          seasons (HC=3, OC=DC=2, everything else=0).
       b. The coach with the higher priority is the mentor.
       c. If priorities are equal, the coach with the earlier first year at
          that school is the mentor.
       d. If priorities *and* first years are equal, direction is ambiguous
          — skip the pair.
    5. Deduplicate ``(mentor_code, mentee_code)`` across all schools.

    Args:
        staff: Cleaned staff records as returned by
            ``ingestion.pull_mcillece_staff.load_mcillece_file()``.

    Returns:
        Deduplicated list of ``(mentor_dict, mentee_dict)`` tuples where
        each dict has ``coach_code`` and ``coach_name`` keys.
    """
    # {school: {coach_code: {year: [roles]}}}
    school_coach_data: dict[str, dict[int, dict[int, list[str]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
    # {coach_code: coach_name}  (last write wins — names are stable)
    code_to_name: dict[int, str] = {}

    for rec in staff:
        code = rec["coach_code"]
        code_to_name[code] = rec["coach_name"]
        school_coach_data[rec["team"]][code][rec["year"]].extend(rec["roles"])

    seen: set[tuple[int, int]] = set()

    for school, coach_data in school_coach_data.items():
        codes = list(coach_data.keys())
        for i in range(len(codes)):
            for j in range(i + 1, len(codes)):
                c1, c2 = codes[i], codes[j]
                years1 = set(coach_data[c1])
                years2 = set(coach_data[c2])

                overlap_years = years1 & years2
                if len(overlap_years) < 2:
                    continue

                # Best role priority for each coach across the overlap
                def _best_priority(code: int, years: set[int]) -> int:
                    best = 0
                    for yr in years:
                        for role in coach_data[code].get(yr, []):
                            best = max(best, ROLE_PRIORITY.get(role.upper(), 0))
                    return best

                p1 = _best_priority(c1, overlap_years)
                p2 = _best_priority(c2, overlap_years)

                if p1 != p2:
                    mentor, mentee = (c1, c2) if p1 > p2 else (c2, c1)
                else:
                    # Fall back to earlier first year at this school
                    start1 = min(years1)
                    start2 = min(years2)
                    if start1 == start2:
                        logger.debug(
                            "Skipping %s / %s at %s — equal priority and start year",
                            code_to_name.get(c1, c1),
                            code_to_name.get(c2, c2),
                            school,
                        )
                        continue
                    mentor, mentee = (c1, c2) if start1 < start2 else (c2, c1)

                pair_key = (mentor, mentee)
                seen.add(pair_key)

    logger.info("Inferred %d unique MENTORED pairs (McIllece)", len(seen))

    return [
        (
            {"coach_code": mentor, "coach_name": code_to_name.get(mentor, "")},
            {"coach_code": mentee, "coach_name": code_to_name.get(mentee, "")},
        )
        for mentor, mentee in seen
    ]


# ---------------------------------------------------------------------------
# McIllece v2 inference — role-tier aware, 2+ consecutive years
# ---------------------------------------------------------------------------


def fetch_coached_at_mcillece_roles(driver: Driver) -> list[dict[str, Any]]:
    """Query Neo4j for every COACHED_AT edge with source='mcillece_roles'.

    Returns one dict per (coach, team, year, role) combination with keys:
    ``coach_code``, ``coach_name``, ``team``, ``year``, ``role_abbr``.

    Args:
        driver: Open Neo4j driver.

    Returns:
        List of role-season dicts, ordered by team then year.
    """
    query = """
    MATCH (c:Coach)-[r:COACHED_AT]->(t:Team)
    WHERE r.source = 'mcillece_roles'
    RETURN c.coach_code AS coach_code,
           r.coach_name  AS coach_name,
           t.school      AS team,
           r.year        AS year,
           r.role_abbr   AS role_abbr
    ORDER BY team, year
    """
    with driver.session() as session:
        result = session.run(query)
        return [rec.data() for rec in result]


def _max_consecutive(years: set[int]) -> int:
    """Return the length of the longest run of consecutive integers in *years*.

    Args:
        years: Set of integer year values.

    Returns:
        Length of the longest consecutive run (0 if *years* is empty,
        1 if no two years are adjacent).
    """
    if not years:
        return 0
    sorted_years = sorted(years)
    max_run = cur_run = 1
    for i in range(1, len(sorted_years)):
        if sorted_years[i] == sorted_years[i - 1] + 1:
            cur_run += 1
            max_run = max(max_run, cur_run)
        else:
            cur_run = 1
    return max_run


def _best_mentor_role(abbrs: set[str]) -> str:
    """Return the highest-priority coordinator role abbreviation from *abbrs*.

    Args:
        abbrs: Set of coordinator role abbreviations held by a mentor.

    Returns:
        The abbreviation with the highest ``_MENTOR_ROLE_PRIORITY`` score.
    """
    return max(abbrs, key=lambda a: _MENTOR_ROLE_PRIORITY.get(a, 0))


def _best_role_all(abbrs: set[str]) -> str | None:
    """Return the most representative role abbreviation from *abbrs*.

    Uses coordinator priority for known coordinator roles (HC highest), then
    falls back to 1 for any other position/support role.  Returns ``None``
    for an empty set.  Used to determine a coach's primary role for
    same-unit classification when they may hold multiple roles.

    Args:
        abbrs: Set of role abbreviations held by a coach.

    Returns:
        The abbreviation with the highest representative priority, or ``None``.
    """
    if not abbrs:
        return None

    def _priority(a: str) -> int:
        if a == "HC":
            return 10
        return _MENTOR_ROLE_PRIORITY.get(a, 1)

    return max(abbrs, key=_priority)


def infer_mentored_edges_v2(
    records: list[dict[str, Any]],
    *,
    _suppressed_unit_edges: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Infer MENTORED edges from mcillece_roles COACHED_AT records.

    Rules applied (in order):
    - **Rule 4 — No self-referential edges**: A coach cannot mentor themselves
      (``mentor_code == mentee_code``).  Enforced by the inner loop guard.
    - **Coordinator filter**: Coach A must hold a COORDINATOR-tier role
      (HC/OC/DC/AC/PG/PD/RG/RD) in at least one year of the overlap window.
    - **Rule 3 — Minimum overlap**: The overlap between A and B at the same
      team must contain at least **2 consecutive years**.
    - **Rule 1 — Prior HC**: If mentee (B) held any HC role at *any* program
      before the earliest shared year with A, no MENTORED edge is created.
      These are career-peer relationships, not mentor/mentee.
    - **Rule 2 — Same-level coordinator**: If both A and B held OC or DC roles
      at the same program in the same year, no MENTORED edge is created in
      either direction.  Coordinators on the same staff are peers.
    - **Same-unit filter**: If the mentor's primary role is on one side of the
      ball (offensive or defensive) and the mentee's primary role is on the
      opposite side, no MENTORED edge is created.  Roles that are unit-neutral
      (HC, AC, ST, RC, special-teams) are compatible with any mentee.
      Unknown roles fall back to permissive (edge kept).
    - **Per-team dedup**: One edge per unique ``(mentor_code, mentee_code, team)``
      triple (different teams produce separate edges).

    Args:
        records: Flat list of role-season dicts as returned by
            ``fetch_coached_at_mcillece_roles()``.  Each dict must have
            keys ``coach_code``, ``coach_name``, ``team``, ``year``,
            ``role_abbr``.
        _suppressed_unit_edges: Optional list to collect edges suppressed by
            the same-unit filter (for dry-run reporting).  Each appended dict
            has keys ``mentor_role``, ``mentee_role``, ``mentor_name``,
            ``mentee_name``, ``team``.

    Returns:
        List of edge dicts with keys:
        ``mentor_code``, ``mentor_name``, ``mentee_code``, ``mentee_name``,
        ``team``, ``overlap_years``, ``mentor_role_abbr``.
    """
    # team → coach_code → year → set(role_abbr)
    school_roles: dict[str, dict[int, dict[int, set[str]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(set))
    )
    code_to_name: dict[int, str] = {}

    for rec in records:
        school_roles[rec["team"]][rec["coach_code"]][rec["year"]].add(rec["role_abbr"])
        code_to_name[rec["coach_code"]] = rec["coach_name"]

    # Rule 1 pre-pass: build global map of coach_code → set of years they held HC
    # at ANY team.  Used to detect mentees with prior head-coaching experience.
    coach_hc_years: dict[int, set[int]] = defaultdict(set)
    for _team, coach_data in school_roles.items():
        for code, year_roles in coach_data.items():
            for yr, abbrs in year_roles.items():
                if "HC" in abbrs:
                    coach_hc_years[code].add(yr)

    seen: set[tuple[int, int, str]] = set()
    edges: list[dict[str, Any]] = []

    # Suppression counters for logging
    rule1_suppressed = 0
    rule2_suppressed = 0
    rule3_suppressed = 0
    rule4_suppressed = 0
    same_unit_suppressed = 0

    for team, coaches in school_roles.items():
        coach_list = list(coaches.keys())
        for a in coach_list:
            years_a = set(coaches[a])
            for b in coach_list:
                # Rule 4 — No self-referential edges: a coach cannot mentor themselves.
                if a == b:
                    rule4_suppressed += 1
                    continue
                key = (a, b, team)
                if key in seen:
                    continue

                years_b = set(coaches[b])
                overlap = years_a & years_b
                if not overlap:
                    continue

                # Coordinator filter: A must hold a coordinator role in at least
                # one overlap year to qualify as a potential mentor.
                a_coord_abbrs: set[str] = {
                    abbr
                    for yr in overlap
                    for abbr in coaches[a][yr]
                    if abbr in _MENTOR_ABBRS
                }
                if not a_coord_abbrs:
                    continue

                # Rule 3 — minimum 2 consecutive shared years
                if _max_consecutive(overlap) < 2:
                    rule3_suppressed += 1
                    continue

                # Rule 1 — Prior HC (two-part check):
                # Part A — mentee was HC at THIS team during any overlap year.
                #   Prevents inverting the hierarchy: if B was HC at this school
                #   during the overlap, B is the senior figure, not A's mentee.
                b_hc_at_team: set[int] = {
                    yr for yr in overlap
                    if "HC" in coaches[b].get(yr, set())
                }
                # Part B — mentee was HC at ANY program strictly before the
                #   earliest shared year (global prior-HC career check).
                overlap_start = min(overlap)
                b_prior_hc_global: set[int] = {
                    y for y in coach_hc_years.get(b, set()) if y < overlap_start
                }
                if b_hc_at_team or b_prior_hc_global:
                    rule1_suppressed += 1
                    logger.debug(
                        "Rule 1 suppressed: mentee %s (code=%d) — "
                        "HC at %s during overlap years=%s, "
                        "prior global HC (<%d)=%s",
                        code_to_name.get(b, ""),
                        b,
                        team,
                        sorted(b_hc_at_team),
                        overlap_start,
                        sorted(b_prior_hc_global),
                    )
                    continue

                # Rule 2 — Same-level coordinator: if both A and B held OC or DC
                # at this team in the same overlap year, they are peers — skip.
                same_level_years = {
                    yr
                    for yr in overlap
                    if (coaches[a][yr] & _COORD_PEER_ROLES)
                    and (coaches[b][yr] & _COORD_PEER_ROLES)
                }
                if same_level_years:
                    rule2_suppressed += 1
                    logger.debug(
                        "Rule 2 suppressed: %s (code=%d) and %s (code=%d) both held "
                        "OC/DC at %s in years %s",
                        code_to_name.get(a, ""),
                        a,
                        code_to_name.get(b, ""),
                        b,
                        team,
                        sorted(same_level_years),
                    )
                    continue

                # Same-unit filter: mentor and mentee must be on compatible units.
                mentor_role_abbr = _best_mentor_role(a_coord_abbrs)
                b_overlap_abbrs: set[str] = {
                    abbr
                    for yr in overlap
                    for abbr in coaches[b].get(yr, set())
                }
                mentee_role_abbr = _best_role_all(b_overlap_abbrs)
                if not same_unit(mentor_role_abbr, mentee_role_abbr):
                    same_unit_suppressed += 1
                    logger.debug(
                        "Same-unit suppressed: mentor %s (%s, code=%d) → "
                        "mentee %s (%s, code=%d) at %s",
                        code_to_name.get(a, ""),
                        mentor_role_abbr,
                        a,
                        code_to_name.get(b, ""),
                        mentee_role_abbr,
                        b,
                        team,
                    )
                    if _suppressed_unit_edges is not None:
                        _suppressed_unit_edges.append(
                            {
                                "mentor_role": mentor_role_abbr,
                                "mentee_role": mentee_role_abbr or "?",
                                "mentor_name": code_to_name.get(a, ""),
                                "mentee_name": code_to_name.get(b, ""),
                                "team": team,
                            }
                        )
                    continue

                seen.add(key)
                edges.append(
                    {
                        "mentor_code": a,
                        "mentor_name": code_to_name.get(a, ""),
                        "mentee_code": b,
                        "mentee_name": code_to_name.get(b, ""),
                        "team": team,
                        "overlap_years": _max_consecutive(overlap),
                        "mentor_role_abbr": mentor_role_abbr,
                    }
                )

    logger.info(
        "Inferred %d projected MENTORED edges (v2, mcillece_roles) | "
        "suppressed: Rule1(prior-HC)=%d, Rule2(same-coord)=%d, "
        "Rule3(min-overlap)=%d, Rule4(self-ref)=%d, same-unit=%d",
        len(edges),
        rule1_suppressed,
        rule2_suppressed,
        rule3_suppressed,
        rule4_suppressed,
        same_unit_suppressed,
    )
    return edges


def compute_dry_run_stats(
    edges: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute summary statistics for a projected MENTORED edge list.

    Args:
        edges: Edge dicts as returned by ``infer_mentored_edges_v2()``.

    Returns:
        Dict with keys:
        - ``total``: int — total projected edge count.
        - ``by_overlap``: dict mapping bucket label → count.
          Buckets: ``"2yr"``, ``"3yr"``, ``"4yr"``, ``"5yr+"``.
        - ``by_mentor_role``: dict mapping role_abbr → count.
        - ``top_mentors``: list of ``((code, name), mentee_count)`` tuples,
          sorted descending, up to 10 entries.
        - ``top_mentees``: list of ``((code, name), mentor_count)`` tuples,
          sorted descending, up to 10 entries.
    """
    total = len(edges)

    # Overlap bucket counts
    overlap_counts: Counter[str] = Counter()
    for e in edges:
        yr = e["overlap_years"]
        bucket = f"{yr}yr" if yr <= 4 else "5yr+"
        overlap_counts[bucket] += 1

    # Mentor role breakdown
    role_counts: Counter[str] = Counter(e["mentor_role_abbr"] for e in edges)

    # Unique mentees per mentor (across all teams)
    mentor_mentees: dict[tuple[int, str], set[int]] = defaultdict(set)
    mentee_mentors: dict[tuple[int, str], set[int]] = defaultdict(set)
    for e in edges:
        mk = (e["mentor_code"], e["mentor_name"])
        bk = (e["mentee_code"], e["mentee_name"])
        mentor_mentees[mk].add(e["mentee_code"])
        mentee_mentors[bk].add(e["mentor_code"])

    top_mentors = sorted(
        mentor_mentees.items(), key=lambda x: len(x[1]), reverse=True
    )[:10]
    top_mentees = sorted(
        mentee_mentors.items(), key=lambda x: len(x[1]), reverse=True
    )[:10]

    return {
        "total": total,
        "by_overlap": dict(overlap_counts),
        "by_mentor_role": dict(role_counts),
        "top_mentors": top_mentors,
        "top_mentees": top_mentees,
    }


def save_dry_run_csv(edges: list[dict[str, Any]], path: Path) -> None:
    """Write projected MENTORED edge list to a CSV file.

    Creates parent directories if they do not already exist.  The file is
    always overwritten so re-runs stay idempotent.

    Args:
        edges: Edge dicts as returned by ``infer_mentored_edges_v2()``.
        path: Destination file path.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "mentor_code",
        "mentor_name",
        "mentee_code",
        "mentee_name",
        "team",
        "overlap_years",
        "mentor_role_abbr",
    ]
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(edges)
    logger.info("Saved %d projected edges to %s", len(edges), path)


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
