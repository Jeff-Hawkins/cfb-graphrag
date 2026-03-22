"""Tests for ingestion/pull_coaches.py."""

import json
from unittest.mock import patch

import pytest

from ingestion.pull_coaches import fetch_coaches


@pytest.fixture
def coaches_payload() -> list[dict]:
    """Minimal CFBD /coaches response payload."""
    return [
        {
            "first_name": "Nick",
            "last_name": "Saban",
            "seasons": [
                {"school": "Alabama", "year": 2007, "title": "Head Coach", "games": 12},
            ],
        }
    ]


def test_fetch_coaches_calls_api_when_no_cache(tmp_path, coaches_payload):
    """Hits the API when no cache exists and saves the result."""
    raw_path = tmp_path / "coaches.json"

    with patch("ingestion.pull_coaches.build_session"), \
         patch("ingestion.pull_coaches.get_json", return_value=coaches_payload):
        result = fetch_coaches(api_key="test-key", raw_path=raw_path)

    assert result == coaches_payload
    assert raw_path.exists()
    assert json.loads(raw_path.read_text()) == coaches_payload


def test_fetch_coaches_uses_cache_when_file_exists(tmp_path, coaches_payload):
    """Returns cached data without hitting the API when file exists."""
    raw_path = tmp_path / "coaches.json"
    raw_path.write_text(json.dumps(coaches_payload))

    with patch("ingestion.pull_coaches.build_session") as mock_build, \
         patch("ingestion.pull_coaches.get_json") as mock_get:
        result = fetch_coaches(api_key="test-key", raw_path=raw_path)

    mock_build.assert_not_called()
    mock_get.assert_not_called()
    assert result == coaches_payload
