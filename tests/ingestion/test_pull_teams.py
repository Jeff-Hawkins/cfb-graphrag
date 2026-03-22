"""Tests for ingestion/pull_teams.py."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ingestion.pull_teams import fetch_teams


@pytest.fixture
def teams_payload() -> list[dict]:
    """Minimal CFBD /teams response payload."""
    return [
        {"id": 1, "school": "Alabama", "conference": "SEC", "abbreviation": "ALA"},
        {"id": 2, "school": "Ohio State", "conference": "Big Ten", "abbreviation": "OSU"},
    ]


# ---------------------------------------------------------------------------
# Test: file does NOT exist → API is called, file is created
# ---------------------------------------------------------------------------


def test_fetch_teams_calls_api_when_no_cache(tmp_path, teams_payload):
    """When no cache file exists, fetch_teams should hit the API and save the result."""
    raw_path = tmp_path / "teams.json"

    with patch("ingestion.pull_teams.build_session") as mock_build, \
         patch("ingestion.pull_teams.get_json") as mock_get:
        mock_get.return_value = teams_payload

        result = fetch_teams(api_key="test-key", raw_path=raw_path)

    # API was called
    mock_build.assert_called_once_with("test-key")
    mock_get.assert_called_once()

    # Return value is correct
    assert result == teams_payload

    # File was written
    assert raw_path.exists()
    saved = json.loads(raw_path.read_text())
    assert saved == teams_payload


# ---------------------------------------------------------------------------
# Test: file exists → API is NOT called, cached data is returned
# ---------------------------------------------------------------------------


def test_fetch_teams_uses_cache_when_file_exists(tmp_path, teams_payload):
    """When cache file already exists, fetch_teams must NOT call the API."""
    raw_path = tmp_path / "teams.json"
    raw_path.write_text(json.dumps(teams_payload))

    with patch("ingestion.pull_teams.build_session") as mock_build, \
         patch("ingestion.pull_teams.get_json") as mock_get:

        result = fetch_teams(api_key="test-key", raw_path=raw_path)

    # API was NOT called
    mock_build.assert_not_called()
    mock_get.assert_not_called()

    # Cached data returned
    assert result == teams_payload


# ---------------------------------------------------------------------------
# Test: returned list has expected structure
# ---------------------------------------------------------------------------


def test_fetch_teams_returns_list_of_dicts(tmp_path, teams_payload):
    """fetch_teams must return a list of dicts."""
    raw_path = tmp_path / "teams.json"

    with patch("ingestion.pull_teams.build_session"), \
         patch("ingestion.pull_teams.get_json", return_value=teams_payload):
        result = fetch_teams(api_key="test-key", raw_path=raw_path)

    assert isinstance(result, list)
    assert all(isinstance(t, dict) for t in result)
    assert result[0]["school"] == "Alabama"


# ---------------------------------------------------------------------------
# Test: parent directories are created if missing
# ---------------------------------------------------------------------------


def test_fetch_teams_creates_parent_dirs(tmp_path, teams_payload):
    """fetch_teams must create data/raw/ if it does not exist."""
    raw_path = tmp_path / "nested" / "dir" / "teams.json"

    with patch("ingestion.pull_teams.build_session"), \
         patch("ingestion.pull_teams.get_json", return_value=teams_payload):
        fetch_teams(api_key="test-key", raw_path=raw_path)

    assert raw_path.exists()
