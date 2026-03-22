"""Tests for loader/neo4j_loader.py using a mock Neo4j driver."""

from unittest.mock import MagicMock, patch

import pytest

from loader.neo4j_loader import load_teams, load_coaches, load_conferences, load_players, load_games


@pytest.fixture
def mock_driver():
    """Minimal mock of a neo4j.Driver that records session.run calls."""
    driver = MagicMock()
    session = MagicMock()
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)
    driver._session = session
    return driver


@pytest.fixture
def sample_teams():
    return [
        {"id": 1, "school": "Alabama", "conference": "SEC", "abbreviation": "ALA"},
        {"id": 2, "school": "Ohio State", "conference": "Big Ten", "abbreviation": "OSU"},
    ]


@pytest.fixture
def sample_coaches():
    return [
        {
            "first_name": "Nick",
            "last_name": "Saban",
            "seasons": [{"school": "Alabama", "year": 2007, "title": "Head Coach", "games": 12}],
        }
    ]


def test_load_teams_calls_session_run(mock_driver, sample_teams):
    """load_teams must call session.run at least once."""
    result = load_teams(mock_driver, sample_teams)
    mock_driver.session().__enter__().run.assert_called()
    assert result == len(sample_teams)


def test_load_coaches_returns_count(mock_driver, sample_coaches):
    """load_coaches must return the number of coach records processed."""
    result = load_coaches(mock_driver, sample_coaches)
    assert result == len(sample_coaches)


def test_load_conferences_returns_unique_count(mock_driver, sample_teams):
    """load_conferences must return the number of unique conferences."""
    result = load_conferences(mock_driver, sample_teams)
    assert result == 2  # SEC and Big Ten


def test_load_games_calls_session_run(mock_driver):
    """load_games must call session.run and return game count."""
    games = [
        {"id": 1, "home_team": "Alabama", "away_team": "Ohio State",
         "home_points": 42, "away_points": 35, "season": 2023, "week": 1}
    ]
    result = load_games(mock_driver, games)
    mock_driver.session().__enter__().run.assert_called()
    assert result == 1
