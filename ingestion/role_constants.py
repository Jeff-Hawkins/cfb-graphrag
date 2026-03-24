"""Role abbreviation constants derived from the McIllece CFB Coaches Database legend.

Legend source: CFB-Coaches-Database-Legend-1.xlsx (38 abbreviations).

Three purpose-specific sets are defined here so downstream modules import
named constants rather than hardcoding strings:

``COORDINATOR_ROLES``
    Roles at coordinator-level or above.  A mentee holding one of these
    *before* the overlap period that generated their MENTORED edge is a signal
    that the inferred mentor/mentee direction may be reversed.

``ASSISTANT_ROLES``
    Roles indicating an analyst or non-player-coaching assistant capacity.
    When a coach who previously held a ``COORDINATOR_ROLES`` role later appears
    in the overlap window as one of these, it is an additional reverse-career
    signal (the former coordinator is now in a supporting role under a younger
    mentor).

``ALL_ROLES``
    Every valid role abbreviation recognised by the McIllece legend.  Use for
    ingestion validation — any role code not in this set should be logged as a
    warning and passed through unchanged.

Both ``COORDINATOR_ROLES`` and ``ASSISTANT_ROLES`` are guaranteed subsets of
``ALL_ROLES`` (enforced by the module-level assertion at the bottom of this file).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Coordinator-level roles — trigger reverse-career check
# ---------------------------------------------------------------------------

COORDINATOR_ROLES: frozenset[str] = frozenset({
    "HC",  # Head Coach
    "OC",  # Offensive Coordinator
    "DC",  # Defensive Coordinator
    "PD",  # Pass Defense Coordinator
    "PG",  # Pass Offense Coordinator
    "RD",  # Rush Defense Coordinator
    "RG",  # Rush Offense Coordinator
    "ST",  # Special Teams Coordinator
    "RC",  # Recruiting Coordinator
})
"""Roles at coordinator level or above.

A mentee who held any of these at *any* program *before* the earliest shared
season with their inferred mentor is a candidate for ``confidence_flag =
'REVIEW_REVERSE'``.  The set intentionally excludes ``AC`` (Assistant Head
Coach) because that title is frequently a courtesy designation rather than an
independent coordinator responsibility.
"""

# ---------------------------------------------------------------------------
# Assistant / analyst roles — secondary reverse-career signal
# ---------------------------------------------------------------------------

ASSISTANT_ROLES: frozenset[str] = frozenset({
    "DF",  # Defensive Assistant / Analyst
    "OF",  # Offensive Assistant / Analyst
})
"""Roles indicating analyst or non-player-coaching assistant capacity.

When a coach who previously held a ``COORDINATOR_ROLES`` role later appears in
the overlap window with one of these roles, it suggests the former coordinator
is now in a reduced, supporting capacity under the inferred mentor — an
additional reverse-career signal.

Note: detection logic using ``ASSISTANT_ROLES`` is defined separately in
``ingestion/flag_mentored_edges.py`` and is independent of the prior-career
check that uses ``COORDINATOR_ROLES``.
"""

# ---------------------------------------------------------------------------
# All valid McIllece role codes — use for ingestion validation
# ---------------------------------------------------------------------------

ALL_ROLES: frozenset[str] = frozenset({
    "AC",  # Assistant Head Coach
    "CB",  # Cornerbacks
    "DB",  # Defensive Backs
    "DC",  # Defensive Coordinator
    "DE",  # Defensive Ends
    "DF",  # Defensive Assistant / Analyst
    "DL",  # Defensive Line
    "DT",  # Defensive Tackles
    "FB",  # Fullbacks
    "FG",  # Field Goal Kickers
    "GC",  # Guards/Centers
    "HC",  # Head Coach
    "IB",  # Inside Linebackers
    "IR",  # Inside Receivers
    "KO",  # Kickoff Specialists
    "KR",  # Kick Returners
    "LB",  # Linebackers
    "NB",  # Nickel Backs
    "OB",  # Outside Linebackers
    "OC",  # Offensive Coordinator
    "OF",  # Offensive Assistant / Analyst
    "OL",  # Offensive Line
    "OR",  # Outside Receivers
    "OT",  # Offensive Tackles
    "PD",  # Pass Defense Coordinator
    "PG",  # Pass Offense Coordinator
    "PK",  # Placekickers
    "PR",  # Punt Returners
    "PT",  # Punters
    "QB",  # Quarterbacks
    "RB",  # Running Backs
    "RC",  # Recruiting Coordinator
    "RD",  # Rush Defense Coordinator
    "RG",  # Rush Offense Coordinator
    "SF",  # Safeties
    "ST",  # Special Teams Coordinator
    "TE",  # Tight Ends
    "WR",  # Wide Receivers
})
"""All 38 role abbreviations recognised by the McIllece CFB Coaches Database legend.

Use ``validate_role()`` to check a single code, or compare against this set
directly when processing batches.  Role codes not present here should be logged
as warnings and passed through unchanged — unknown roles may reflect legend
updates or data entry variants.
"""

# Invariants — fail fast at import time if the sets are accidentally broken.
assert COORDINATOR_ROLES <= ALL_ROLES, "COORDINATOR_ROLES must be a subset of ALL_ROLES"
assert ASSISTANT_ROLES <= ALL_ROLES, "ASSISTANT_ROLES must be a subset of ALL_ROLES"
assert not (COORDINATOR_ROLES & ASSISTANT_ROLES), (
    "COORDINATOR_ROLES and ASSISTANT_ROLES must be disjoint"
)


# ---------------------------------------------------------------------------
# Validation helper
# ---------------------------------------------------------------------------


def validate_role(role_code: str) -> bool:
    """Return ``True`` if *role_code* is a recognised McIllece legend abbreviation.

    Case-sensitive — the McIllece data uses uppercase abbreviations throughout.
    An unknown code is not an error; it may reflect a legend update or a data
    entry variant.  Callers should log a warning rather than raising.

    Args:
        role_code: Role abbreviation string to check (e.g. ``"HC"``, ``"OC"``).

    Returns:
        ``True`` when *role_code* is in ``ALL_ROLES``, ``False`` otherwise.

    Example::

        >>> validate_role("HC")
        True
        >>> validate_role("XX")
        False
    """
    return role_code in ALL_ROLES
