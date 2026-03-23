"""Match CFBD Coach nodes to McIllece Coach nodes by name.

Outputs two CSVs to data/audits/:
  coach_identity_matches.csv    — confirmed matches
  coach_identity_unmatched.csv  — coaches on either side with no match

Exact matches (ratio 1.0) are safe to load automatically.
Fuzzy matches (0.92 < ratio < 1.0) are printed for manual review.
"""

import csv
import logging
import os
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from neo4j import Driver, GraphDatabase

load_dotenv()

logger = logging.getLogger(__name__)

_SUFFIXES = re.compile(
    r"\b(jr\.?|sr\.?|ii|iii|iv)\s*$",
    re.IGNORECASE,
)

FUZZY_THRESHOLD = 0.92
FUZZY_REVIEW_CAP = 0.99  # ratio in [0.92, 0.99) → print for review


def normalize_name(name: str) -> str:
    """Lowercase, strip whitespace and common name suffixes.

    Args:
        name: Raw name string (e.g. ``"Nick Saban Jr."``).

    Returns:
        Normalized name (e.g. ``"nick saban"``).
    """
    name = name.strip().lower()
    name = _SUFFIXES.sub("", name).strip()
    return name


def pull_cfbd_coaches(driver: Driver) -> list[dict[str, Any]]:
    """Fetch CFBD Coach nodes (have first_name property) from Neo4j.

    Args:
        driver: Open Neo4j driver.

    Returns:
        List of dicts with keys ``cfbd_id``, ``first_name``, ``last_name``,
        and ``full_name``.
    """
    query = """
    MATCH (c:Coach)
    WHERE c.first_name IS NOT NULL
    RETURN elementId(c) AS cfbd_id,
           c.first_name AS first_name,
           c.last_name  AS last_name
    """
    with driver.session() as session:
        result = session.run(query)
        rows = []
        for record in result:
            first = record["first_name"] or ""
            last = record["last_name"] or ""
            rows.append(
                {
                    "cfbd_id": record["cfbd_id"],
                    "first_name": first,
                    "last_name": last,
                    "full_name": f"{first} {last}".strip(),
                }
            )
        return rows


def pull_mcillece_coaches(driver: Driver) -> list[dict[str, Any]]:
    """Fetch McIllece Coach nodes (have coach_code property) from Neo4j.

    Args:
        driver: Open Neo4j driver.

    Returns:
        List of dicts with keys ``mc_id``, ``coach_code``, ``name``.
    """
    query = """
    MATCH (c:Coach)
    WHERE c.coach_code IS NOT NULL
    RETURN elementId(c) AS mc_id,
           c.coach_code AS coach_code,
           c.name       AS name
    """
    with driver.session() as session:
        result = session.run(query)
        rows = []
        for record in result:
            rows.append(
                {
                    "mc_id": record["mc_id"],
                    "coach_code": record["coach_code"],
                    "name": record["name"] or "",
                }
            )
        return rows


def match_coaches(
    cfbd_coaches: list[dict[str, Any]],
    mc_coaches: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Match CFBD coaches to McIllece coaches by normalized name.

    Strategy:
    1. Exact match on normalized full name.
    2. Fuzzy match (SequenceMatcher ratio > FUZZY_THRESHOLD) for remainder.

    Fuzzy candidates in [FUZZY_THRESHOLD, FUZZY_REVIEW_CAP) are printed to
    console for manual review and NOT included in the returned match list.

    Args:
        cfbd_coaches: Output of :func:`pull_cfbd_coaches`.
        mc_coaches:   Output of :func:`pull_mcillece_coaches`.

    Returns:
        Tuple of:
        - ``matches``: list of match dicts with keys cfbd_id, mc_id,
          cfbd_name, mc_name, match_type, confidence.
        - ``unmatched``: list of unmatched coach dicts with keys source,
          id, name.
    """
    # Build McIllece lookup: normalized_name → coach dict
    mc_by_norm: dict[str, dict[str, Any]] = {}
    for mc in mc_coaches:
        norm = normalize_name(mc["name"])
        if norm:
            mc_by_norm[norm] = mc

    matched_mc_codes: set[int] = set()
    matches: list[dict[str, Any]] = []
    cfbd_unmatched: list[dict[str, Any]] = []
    fuzzy_review: list[dict[str, Any]] = []

    for cfbd in cfbd_coaches:
        norm_cfbd = normalize_name(cfbd["full_name"])

        # 1. Exact match
        if norm_cfbd in mc_by_norm:
            mc = mc_by_norm[norm_cfbd]
            matches.append(
                {
                    "cfbd_id": cfbd["cfbd_id"],
                    "mc_id": mc["mc_id"],
                    "cfbd_name": cfbd["full_name"],
                    "mc_name": mc["name"],
                    "match_type": "exact",
                    "confidence": 1.0,
                }
            )
            matched_mc_codes.add(mc["coach_code"])
            continue

        # 2. Fuzzy match
        best_ratio = 0.0
        best_mc: dict[str, Any] | None = None
        for norm_mc, mc in mc_by_norm.items():
            ratio = SequenceMatcher(None, norm_cfbd, norm_mc).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_mc = mc

        if best_mc is not None and best_ratio >= FUZZY_THRESHOLD:
            if best_ratio >= FUZZY_REVIEW_CAP:
                # High confidence fuzzy — include as auto match
                matches.append(
                    {
                        "cfbd_id": cfbd["cfbd_id"],
                        "mc_id": best_mc["mc_id"],
                        "cfbd_name": cfbd["full_name"],
                        "mc_name": best_mc["name"],
                        "match_type": "fuzzy",
                        "confidence": round(best_ratio, 4),
                    }
                )
                matched_mc_codes.add(best_mc["coach_code"])
            else:
                # In review band — collect for printing, do NOT load
                fuzzy_review.append(
                    {
                        "cfbd_id": cfbd["cfbd_id"],
                        "mc_id": best_mc["mc_id"],
                        "cfbd_name": cfbd["full_name"],
                        "mc_name": best_mc["name"],
                        "ratio": round(best_ratio, 4),
                    }
                )
                cfbd_unmatched.append(
                    {"source": "cfbd", "id": cfbd["cfbd_id"], "name": cfbd["full_name"]}
                )
        else:
            cfbd_unmatched.append(
                {"source": "cfbd", "id": cfbd["cfbd_id"], "name": cfbd["full_name"]}
            )

    # Collect unmatched McIllece coaches
    mc_unmatched = [
        {"source": "mcillece", "id": mc["mc_id"], "name": mc["name"]}
        for mc in mc_coaches
        if mc["coach_code"] not in matched_mc_codes
    ]

    # Print fuzzy review candidates to console
    if fuzzy_review:
        print(
            f"\n--- Fuzzy Match Review ({len(fuzzy_review)} candidates in "
            f"[{FUZZY_THRESHOLD}, {FUZZY_REVIEW_CAP}) band) ---"
        )
        print(
            f"{'CFBD Name':<30} {'McIllece Name':<30} {'Ratio':>6}  "
            f"{'CFBD ID':<40} {'MC ID'}"
        )
        print("-" * 120)
        for item in fuzzy_review:
            print(
                f"{item['cfbd_name']:<30} {item['mc_name']:<30} "
                f"{item['ratio']:>6.4f}  {item['cfbd_id']:<40} {item['mc_id']}"
            )
        print(
            "--- These have NOT been included in the match output. "
            "Review and add manually. ---\n"
        )

    unmatched = cfbd_unmatched + mc_unmatched
    return matches, unmatched


def write_csvs(
    matches: list[dict[str, Any]],
    unmatched: list[dict[str, Any]],
    output_dir: Path,
) -> None:
    """Write match and unmatched results to CSVs in output_dir.

    Args:
        matches:    List of match dicts from :func:`match_coaches`.
        unmatched:  List of unmatched coach dicts from :func:`match_coaches`.
        output_dir: Directory path where CSVs will be written.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    match_path = output_dir / "coach_identity_matches.csv"
    with open(match_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["cfbd_id", "mc_id", "cfbd_name", "mc_name", "match_type", "confidence"],
        )
        writer.writeheader()
        writer.writerows(matches)
    print(f"Wrote {len(matches)} matches → {match_path}")

    unmatch_path = output_dir / "coach_identity_unmatched.csv"
    with open(unmatch_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["source", "id", "name"])
        writer.writeheader()
        writer.writerows(unmatched)
    print(f"Wrote {len(unmatched)} unmatched → {unmatch_path}")


def run(driver: Driver | None = None, output_dir: Path | None = None) -> tuple[list, list]:
    """Main entry point: pull, match, print review candidates, write CSVs.

    Args:
        driver:     Optional open Neo4j driver (created from env if None).
        output_dir: Optional output path (defaults to data/audits/).

    Returns:
        Tuple of (matches, unmatched) lists.
    """
    if driver is None:
        driver = GraphDatabase.driver(
            os.environ["NEO4J_URI"],
            auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
        )

    if output_dir is None:
        output_dir = Path(__file__).resolve().parent.parent / "data" / "audits"

    print("Pulling CFBD coaches from Neo4j…")
    cfbd = pull_cfbd_coaches(driver)
    print(f"  Found {len(cfbd)} CFBD Coach nodes")

    print("Pulling McIllece coaches from Neo4j…")
    mc = pull_mcillece_coaches(driver)
    print(f"  Found {len(mc)} McIllece Coach nodes")

    print("Matching…")
    matches, unmatched = match_coaches(cfbd, mc)
    print(
        f"  Exact+fuzzy matches: {len(matches)}  |  Unmatched (both sides): {len(unmatched)}"
    )

    write_csvs(matches, unmatched, output_dir)
    return matches, unmatched


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
