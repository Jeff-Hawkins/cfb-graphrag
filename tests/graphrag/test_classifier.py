"""Tests for graphrag/classifier.py."""

import json
from unittest.mock import MagicMock

from graphrag.classifier import classify_intent


def _mock_client(response_json: dict) -> MagicMock:
    """Build a mock genai.Client whose models.generate_content returns fixed JSON."""
    client = MagicMock()
    client.models.generate_content.return_value.text = json.dumps(response_json)
    return client


# ---------------------------------------------------------------------------
# One example per intent bucket
# ---------------------------------------------------------------------------


def test_tree_query_routes_correctly():
    """'Show me every HC from Saban's staff' → TREE_QUERY."""
    client = _mock_client({"intent": "TREE_QUERY", "confidence": 0.97})
    result = classify_intent(
        "Show me every head coach who came from Nick Saban's staff", client=client
    )
    assert result["intent"] == "TREE_QUERY"
    assert result["confidence"] == 0.97


def test_performance_compare_routes_correctly():
    """'Compare Kirby Smart vs Lincoln Riley OC results' → PERFORMANCE_COMPARE."""
    client = _mock_client({"intent": "PERFORMANCE_COMPARE", "confidence": 0.91})
    result = classify_intent(
        "Compare Kirby Smart vs. Lincoln Riley's OC results", client=client
    )
    assert result["intent"] == "PERFORMANCE_COMPARE"
    assert result["confidence"] == 0.91


def test_pipeline_query_routes_correctly():
    """'Which DCs became HCs in the last 5 years?' → PIPELINE_QUERY."""
    client = _mock_client({"intent": "PIPELINE_QUERY", "confidence": 0.88})
    result = classify_intent(
        "Which defensive coordinators became head coaches in the last 5 years?", client=client
    )
    assert result["intent"] == "PIPELINE_QUERY"
    assert result["confidence"] == 0.88


def test_change_impact_routes_correctly():
    """'How did Alabama's defense change after Saban retired?' → CHANGE_IMPACT."""
    client = _mock_client({"intent": "CHANGE_IMPACT", "confidence": 0.85})
    result = classify_intent(
        "How did Alabama's defense change after Saban retired?", client=client
    )
    assert result["intent"] == "CHANGE_IMPACT"
    assert result["confidence"] == 0.85


def test_similarity_routes_correctly():
    """'Who are the most similar OCs to Kliff Kingsbury?' → SIMILARITY."""
    client = _mock_client({"intent": "SIMILARITY", "confidence": 0.82})
    result = classify_intent(
        "Who are the most similar OCs to Kliff Kingsbury?", client=client
    )
    assert result["intent"] == "SIMILARITY"
    assert result["confidence"] == 0.82


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_low_confidence_ambiguous_query():
    """An ambiguous query with confidence < 0.7 is handled gracefully."""
    client = _mock_client({"intent": "TREE_QUERY", "confidence": 0.55})
    result = classify_intent("Tell me about football coaches", client=client)
    assert result["intent"] in {
        "TREE_QUERY", "PERFORMANCE_COMPARE", "PIPELINE_QUERY", "CHANGE_IMPACT", "SIMILARITY"
    }
    assert 0.0 <= result["confidence"] <= 1.0


def test_invalid_intent_falls_back_to_default():
    """Unknown intent string from Gemini falls back to TREE_QUERY with confidence 0."""
    client = _mock_client({"intent": "MADE_UP_INTENT", "confidence": 0.99})
    result = classify_intent("Some question", client=client)
    assert result["intent"] == "TREE_QUERY"
    assert result["confidence"] == 0.0


def test_non_json_response_falls_back_gracefully():
    """Non-JSON Gemini response returns fallback intent without raising."""
    client = MagicMock()
    client.models.generate_content.return_value.text = "I cannot classify this."
    result = classify_intent("Some question", client=client)
    assert result["intent"] == "TREE_QUERY"
    assert result["confidence"] == 0.0
