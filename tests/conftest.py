"""Shared pytest fixtures for the CFB GraphRAG test suite."""

import json
import pytest


# ---------------------------------------------------------------------------
# Sample data fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_teams() -> list[dict]:
    """Two minimal team dicts matching the CFBD /teams response shape."""
    return [
        {"id": 1, "school": "Alabama", "conference": "SEC", "abbreviation": "ALA"},
        {"id": 2, "school": "Ohio State", "conference": "Big Ten", "abbreviation": "OSU"},
    ]


@pytest.fixture
def sample_coaches() -> list[dict]:
    """Minimal coach records with nested seasons list."""
    return [
        {
            "first_name": "Nick",
            "last_name": "Saban",
            "seasons": [
                {"school": "Alabama", "year": 2007, "title": "Head Coach", "games": 12},
                {"school": "Alabama", "year": 2023, "title": "Head Coach", "games": 13},
            ],
        },
        {
            "first_name": "Kirby",
            "last_name": "Smart",
            "seasons": [
                {"school": "Alabama", "year": 2015, "title": "Defensive Coordinator", "games": 14},
                {"school": "Georgia", "year": 2016, "title": "Head Coach", "games": 13},
            ],
        },
    ]


@pytest.fixture
def sample_teams_json(sample_teams) -> str:
    """JSON-serialized sample teams list."""
    return json.dumps(sample_teams)
