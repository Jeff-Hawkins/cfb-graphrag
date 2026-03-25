"""Role abbreviation constants derived from the McIllece CFB Coaches Database legend.

Legend source: CFB-Coaches-Database-Legend-1.xlsx (38 abbreviations).

Purpose-specific sets are defined here so downstream modules import named
constants rather than hardcoding strings:

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

``OFFENSIVE_ROLES``
    Roles associated with the offensive unit (coordinators and position coaches).

``DEFENSIVE_ROLES``
    Roles associated with the defensive unit (coordinators and position coaches).

``NEUTRAL_ROLES``
    Roles that span both units or the whole program — treated as unit-neutral
    for the purpose of MENTORED edge same-unit filtering.

``ALL_ROLES``
    Every valid role abbreviation recognised by the McIllece legend.  Use for
    ingestion validation — any role code not in this set should be logged as a
    warning and passed through unchanged.

``COORDINATOR_ROLES``, ``ASSISTANT_ROLES``, ``OFFENSIVE_ROLES``,
``DEFENSIVE_ROLES``, and ``NEUTRAL_ROLES`` are all guaranteed subsets of
``ALL_ROLES``, and ``OFFENSIVE_ROLES`` and ``DEFENSIVE_ROLES`` are guaranteed
disjoint (enforced by module-level assertions at the bottom of this file).
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

# ---------------------------------------------------------------------------
# Unit-based role groupings — used for same-unit MENTORED edge filtering
# ---------------------------------------------------------------------------

OFFENSIVE_ROLES: frozenset[str] = frozenset({
    "OC",  # Offensive Coordinator
    "PG",  # Pass Offense Coordinator
    "RG",  # Rush Offense Coordinator
    "QB",  # Quarterbacks
    "RB",  # Running Backs
    "WR",  # Wide Receivers
    "TE",  # Tight Ends
    "OL",  # Offensive Line
    "OT",  # Offensive Tackles
    "GC",  # Guards/Centers
    "FB",  # Fullbacks
    "IR",  # Inside Receivers
    "OR",  # Outside Receivers
    "OF",  # Offensive Assistant / Analyst
})
"""Roles associated with the offensive unit.

Offensive coordinators, all offensive position coaches, and the offensive
analyst role.  Used by ``same_unit()`` to decide whether a potential
MENTORED edge crosses unit lines.
"""

DEFENSIVE_ROLES: frozenset[str] = frozenset({
    "DC",  # Defensive Coordinator
    "PD",  # Pass Defense Coordinator
    "RD",  # Rush Defense Coordinator
    "CB",  # Cornerbacks
    "DB",  # Defensive Backs
    "DE",  # Defensive Ends
    "DL",  # Defensive Line
    "DT",  # Defensive Tackles
    "IB",  # Inside Linebackers
    "LB",  # Linebackers
    "NB",  # Nickel Backs
    "OB",  # Outside Linebackers
    "SF",  # Safeties
    "DF",  # Defensive Assistant / Analyst
})
"""Roles associated with the defensive unit.

Defensive coordinators, all defensive position coaches, and the defensive
analyst role.  Used by ``same_unit()`` to decide whether a potential
MENTORED edge crosses unit lines.
"""

NEUTRAL_ROLES: frozenset[str] = frozenset({
    "HC",  # Head Coach
    "AC",  # Assistant Head Coach
    "RC",  # Recruiting Coordinator
    "ST",  # Special Teams Coordinator
    "FG",  # Field Goal Kickers
    "KO",  # Kickoff Specialists
    "KR",  # Kick Returners
    "PK",  # Placekickers
    "PR",  # Punt Returners
    "PT",  # Punters
})
"""Roles that work across both units — treated as unit-neutral.

A mentor in a neutral role may mentor any mentee regardless of unit.
A mentee in a neutral role may be mentored by any mentor regardless of unit.
"""

# Invariants — fail fast at import time if the sets are accidentally broken.
assert COORDINATOR_ROLES <= ALL_ROLES, "COORDINATOR_ROLES must be a subset of ALL_ROLES"
assert ASSISTANT_ROLES <= ALL_ROLES, "ASSISTANT_ROLES must be a subset of ALL_ROLES"
assert not (COORDINATOR_ROLES & ASSISTANT_ROLES), (
    "COORDINATOR_ROLES and ASSISTANT_ROLES must be disjoint"
)
assert not (OFFENSIVE_ROLES & DEFENSIVE_ROLES), (
    "OFFENSIVE_ROLES and DEFENSIVE_ROLES must be disjoint"
)
assert OFFENSIVE_ROLES <= ALL_ROLES, "OFFENSIVE_ROLES must be a subset of ALL_ROLES"
assert DEFENSIVE_ROLES <= ALL_ROLES, "DEFENSIVE_ROLES must be a subset of ALL_ROLES"
assert NEUTRAL_ROLES <= ALL_ROLES, "NEUTRAL_ROLES must be a subset of ALL_ROLES"


# ---------------------------------------------------------------------------
# Unit-compatibility helper
# ---------------------------------------------------------------------------


def same_unit(mentor_role: str | None, mentee_role: str | None) -> bool:
    """Return ``True`` if *mentor_role* and *mentee_role* are on compatible units.

    Used to filter out cross-unit MENTORED edges (e.g. a DC should not be
    inferred as a mentor to an offensive position coach).

    Rules (applied in order):

    1. If either role is ``None`` or not in ``ALL_ROLES`` → ``True``
       (permissive fallback — do not suppress edges we cannot classify).
    2. A mentor in ``NEUTRAL_ROLES`` (HC, AC, RC, ST, special-teams) →
       compatible with any mentee unit.
    3. An offensive mentor (``OFFENSIVE_ROLES``) → compatible only with
       offensive or neutral mentees.
    4. A defensive mentor (``DEFENSIVE_ROLES``) → compatible only with
       defensive or neutral mentees.

    Args:
        mentor_role: Role abbreviation for the potential mentor, or ``None``.
        mentee_role: Role abbreviation for the potential mentee, or ``None``.

    Returns:
        ``True`` when the pair is unit-compatible (edge should be kept),
        ``False`` when the pair crosses unit lines (edge should be suppressed).

    Examples::

        >>> same_unit("HC", "DC")       # HC mentor → anyone
        True
        >>> same_unit("OC", "WR")       # offensive mentor → offensive mentee
        True
        >>> same_unit("OC", "DC")       # offensive mentor → defensive mentor
        False
        >>> same_unit("DC", "LB")       # defensive mentor → defensive mentee
        True
        >>> same_unit("WR", "CB")       # offensive mentee → defensive mentee
        False
        >>> same_unit("ST", "OC")       # neutral mentor → anyone
        True
        >>> same_unit(None, "OC")       # unknown mentor → permissive
        True
    """
    # Permissive fallback for unclassifiable roles
    if mentor_role is None or mentor_role not in ALL_ROLES:
        return True
    if mentee_role is None or mentee_role not in ALL_ROLES:
        return True

    # Neutral mentor → any mentee
    if mentor_role in NEUTRAL_ROLES:
        return True

    # Offensive mentor → offensive or neutral mentee only
    if mentor_role in OFFENSIVE_ROLES:
        return mentee_role in OFFENSIVE_ROLES or mentee_role in NEUTRAL_ROLES

    # Defensive mentor → defensive or neutral mentee only
    if mentor_role in DEFENSIVE_ROLES:
        return mentee_role in DEFENSIVE_ROLES or mentee_role in NEUTRAL_ROLES

    # Should not be reachable given the partition covers ALL_ROLES,
    # but be permissive rather than suppressive on unexpected input.
    return True


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
