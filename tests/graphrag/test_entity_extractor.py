"""Tests for graphrag/entity_extractor.py."""

import json
from unittest.mock import MagicMock

import pytest

from graphrag.entity_extractor import extract_entities, resolve_coach_entity


def _mock_client(response_json: dict) -> MagicMock:
    """Build a mock genai.Client whose models.generate_content returns fixed JSON."""
    client = MagicMock()
    client.models.generate_content.return_value.text = json.dumps(response_json)
    return client


def test_extract_entities_returns_coaches_and_teams():
    """Should parse coach and team names from Gemini's JSON response."""
    payload = {"coaches": ["Nick Saban"], "teams": ["Alabama"], "players": []}
    client = _mock_client(payload)

    result = extract_entities("Who did Nick Saban coach at Alabama?", client=client)

    assert result["coaches"] == ["Nick Saban"]
    assert result["teams"] == ["Alabama"]
    assert result["players"] == []


def test_extract_entities_raises_on_invalid_json():
    """Should raise ValueError when Gemini returns non-JSON text."""
    client = MagicMock()
    client.models.generate_content.return_value.text = "Sorry, I can't help with that."

    with pytest.raises(ValueError, match="non-JSON"):
        extract_entities("Who coached Alabama?", client=client)


def test_extract_entities_handles_missing_keys():
    """Should return empty lists for keys missing from Gemini's response."""
    payload = {"coaches": ["Kirby Smart"]}
    client = _mock_client(payload)

    result = extract_entities("Tell me about Kirby Smart", client=client)

    assert result["coaches"] == ["Kirby Smart"]
    assert result["teams"] == []
    assert result["players"] == []


# ---------------------------------------------------------------------------
# resolve_coach_entity
# ---------------------------------------------------------------------------


def _mock_driver_with_record(cfbd_id: str | None, mc_code: int | None) -> MagicMock:
    """Build a mock Neo4j driver returning a single record."""
    driver = MagicMock()
    session = MagicMock()

    if cfbd_id is not None:
        record = MagicMock()
        record.__getitem__ = lambda self, k: {"cfbd_id": cfbd_id, "mc_code": mc_code}[k]
        session.run.return_value.single.return_value = record
    else:
        session.run.return_value.single.return_value = None

    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)
    return driver


def test_resolve_coach_entity_both_nodes():
    """Should return source='both' when CFBD node has SAME_PERSON to McIllece."""
    driver = _mock_driver_with_record("elem-123", 1457)

    result = resolve_coach_entity("Nick Saban", driver)

    assert result["cfbd_node_id"] == "elem-123"
    assert result["mc_coach_code"] == 1457
    assert result["display_name"] == "Nick Saban"
    assert result["source"] == "both"


def test_resolve_coach_entity_cfbd_only():
    """Should return source='cfbd_only' when no SAME_PERSON edge exists."""
    driver = _mock_driver_with_record("elem-456", None)

    result = resolve_coach_entity("Some Coach", driver)

    assert result["cfbd_node_id"] == "elem-456"
    assert result["mc_coach_code"] is None
    assert result["source"] == "cfbd_only"


def test_resolve_coach_entity_not_found():
    """Should return all-None result when no CFBD node found."""
    driver = _mock_driver_with_record(None, None)

    result = resolve_coach_entity("Unknown Person", driver)

    assert result["cfbd_node_id"] is None
    assert result["mc_coach_code"] is None
    assert result["source"] == "cfbd_only"


def test_resolve_coach_entity_single_name():
    """Single-word names (no space) return all-None without hitting Neo4j."""
    driver = MagicMock()

    result = resolve_coach_entity("Saban", driver)

    assert result["cfbd_node_id"] is None
    assert result["mc_coach_code"] is None
    driver.session.assert_not_called()
