"""Tests for graphrag/entity_extractor.py."""

import json
from unittest.mock import MagicMock

import pytest

from graphrag.entity_extractor import extract_entities


def _mock_model(response_json: dict) -> MagicMock:
    """Build a mock GenerativeModel that returns a fixed JSON response."""
    model = MagicMock()
    model.generate_content.return_value.text = json.dumps(response_json)
    return model


def test_extract_entities_returns_coaches_and_teams():
    """Should parse coach and team names from Gemini's JSON response."""
    payload = {"coaches": ["Nick Saban"], "teams": ["Alabama"], "players": []}
    model = _mock_model(payload)

    result = extract_entities("Who did Nick Saban coach at Alabama?", model=model)

    assert result["coaches"] == ["Nick Saban"]
    assert result["teams"] == ["Alabama"]
    assert result["players"] == []


def test_extract_entities_raises_on_invalid_json():
    """Should raise ValueError when Gemini returns non-JSON text."""
    model = MagicMock()
    model.generate_content.return_value.text = "Sorry, I can't help with that."

    with pytest.raises(ValueError, match="non-JSON"):
        extract_entities("Who coached Alabama?", model=model)


def test_extract_entities_handles_missing_keys():
    """Should return empty lists for keys missing from Gemini's response."""
    payload = {"coaches": ["Kirby Smart"]}
    model = _mock_model(payload)

    result = extract_entities("Tell me about Kirby Smart", model=model)

    assert result["coaches"] == ["Kirby Smart"]
    assert result["teams"] == []
    assert result["players"] == []
