"""Shared utilities for the GraphRAG pipeline."""

import json
import re
from typing import Any

# ---------------------------------------------------------------------------
# Semantic role vocabulary — abbreviation → human-readable name
# ---------------------------------------------------------------------------
# Mirrors ingestion/expand_roles.py ROLE_LEGEND but lives here so graphrag/
# modules can map raw role_abbr values to semantic display names without
# importing from ingestion/.

ROLE_DISPLAY_NAMES: dict[str, str] = {
    "AC": "Assistant Head Coach",
    "CB": "Cornerbacks Coach",
    "DB": "Defensive Backs Coach",
    "DC": "Defensive Coordinator",
    "DE": "Defensive Ends Coach",
    "DF": "Defensive Assistant",
    "DL": "Defensive Line Coach",
    "DT": "Defensive Tackles Coach",
    "FB": "Fullbacks Coach",
    "FG": "Field Goal Coach",
    "GC": "Guards/Centers Coach",
    "HC": "Head Coach",
    "IB": "Inside Linebackers Coach",
    "IR": "Inside Receivers Coach",
    "KO": "Kickoff Specialist Coach",
    "KR": "Kick Return Coach",
    "LB": "Linebackers Coach",
    "NB": "Nickel Backs Coach",
    "OB": "Outside Linebackers Coach",
    "OC": "Offensive Coordinator",
    "OF": "Offensive Assistant",
    "OL": "Offensive Line Coach",
    "OR": "Outside Receivers Coach",
    "OT": "Offensive Tackles Coach",
    "PD": "Pass Defense Coordinator",
    "PG": "Pass Offense Coordinator",
    "PK": "Placekicking Coach",
    "PR": "Punt Return Coach",
    "PT": "Punting Coach",
    "QB": "Quarterbacks Coach",
    "RB": "Running Backs Coach",
    "RC": "Recruiting Coordinator",
    "RD": "Rush Defense Coordinator",
    "RG": "Rush Offense Coordinator",
    "SF": "Safeties Coach",
    "ST": "Special Teams Coordinator",
    "TE": "Tight Ends Coach",
    "WR": "Wide Receivers Coach",
}


def role_display_name(abbr: str | None) -> str:
    """Map a role abbreviation to its semantic display name.

    Args:
        abbr: Role abbreviation (e.g. ``"OC"``, ``"DC"``, ``"WR"``),
            or ``None``.

    Returns:
        Human-readable role name (e.g. ``"Offensive Coordinator"``).
        Returns the raw abbreviation unchanged if not in the lookup table,
        or ``"Coach"`` when *abbr* is ``None``.
    """
    if abbr is None:
        return "Coach"
    return ROLE_DISPLAY_NAMES.get(abbr, abbr)


def parse_gemini_json(raw: str) -> dict[str, Any]:
    """Parse a JSON string that may be wrapped in Gemini markdown code fences.

    Gemini 2.5 Flash sometimes wraps JSON responses in markdown code fences
    (e.g. ```json ... ``` or ``` ... ```) even when instructed to return plain
    JSON.  This function strips those fences before parsing so callers do not
    need to handle the inconsistency themselves.

    Args:
        raw: Raw text returned by a Gemini model call (already ``.strip()``ed
            is fine, but not required).

    Returns:
        Parsed JSON as a dict.

    Raises:
        json.JSONDecodeError: If the text — after fence-stripping — is not
            valid JSON.
    """
    text = raw.strip()

    # Strip ```json ... ``` or ``` ... ``` fences
    fence_match = re.match(r"^```(?:json)?\s*\n?(.*?)\n?```$", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    return json.loads(text)
