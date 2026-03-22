"""Node labels, relationship types, and property keys used across the graph.

Keeping these as module-level constants prevents typos and makes schema
changes a single-location edit.
"""

# ---------------------------------------------------------------------------
# Node labels
# ---------------------------------------------------------------------------

TEAM = "Team"
COACH = "Coach"
PLAYER = "Player"
CONFERENCE = "Conference"
SEASON = "Season"

# ---------------------------------------------------------------------------
# Relationship types
# ---------------------------------------------------------------------------

COACHED_AT = "COACHED_AT"      # (:Coach)-[:COACHED_AT {title, start_year, end_year}]->(:Team)
PLAYED_FOR = "PLAYED_FOR"      # (:Player)-[:PLAYED_FOR {year, jersey}]->(:Team)
IN_CONFERENCE = "IN_CONFERENCE"  # (:Team)-[:IN_CONFERENCE]->(:Conference)
PLAYED = "PLAYED"              # (:Team)-[:PLAYED {home_score, away_score, season}]->(:Team)
MENTORED = "MENTORED"          # (:Coach)-[:MENTORED]->(:Coach)

# ---------------------------------------------------------------------------
# Required property keys
# ---------------------------------------------------------------------------

TEAM_PROPS = ("id", "school", "conference", "abbreviation")
COACH_PROPS = ("first_name", "last_name")
PLAYER_PROPS = ("id", "name", "position", "hometown")
CONFERENCE_PROPS = ("name",)
SEASON_PROPS = ("year",)
