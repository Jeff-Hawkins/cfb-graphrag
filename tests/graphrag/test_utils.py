"""Tests for graphrag/utils.py — parse_gemini_json()."""

import json

import pytest

from graphrag.utils import parse_gemini_json


# ---------------------------------------------------------------------------
# Happy-path: plain JSON
# ---------------------------------------------------------------------------


def test_plain_json_object():
    """Plain JSON object is parsed without modification."""
    raw = '{"intent": "TREE_QUERY", "confidence": 0.95}'
    result = parse_gemini_json(raw)
    assert result == {"intent": "TREE_QUERY", "confidence": 0.95}


def test_plain_json_with_leading_trailing_whitespace():
    """Whitespace around plain JSON is stripped before parsing."""
    raw = '  \n{"coaches": ["Nick Saban"]}\n  '
    result = parse_gemini_json(raw)
    assert result == {"coaches": ["Nick Saban"]}


# ---------------------------------------------------------------------------
# Happy-path: markdown fences
# ---------------------------------------------------------------------------


def test_json_fence_with_language_tag():
    """```json ... ``` fence is stripped before parsing."""
    raw = '```json\n{"intent": "TREE_QUERY", "confidence": 0.9}\n```'
    result = parse_gemini_json(raw)
    assert result == {"intent": "TREE_QUERY", "confidence": 0.9}


def test_json_fence_without_language_tag():
    """``` ... ``` fence (no 'json' tag) is stripped before parsing."""
    raw = '```\n{"coaches": ["Kirby Smart"]}\n```'
    result = parse_gemini_json(raw)
    assert result == {"coaches": ["Kirby Smart"]}


def test_json_fence_no_trailing_newline():
    """Fence content without a trailing newline before ``` is handled."""
    raw = '```json\n{"key": "value"}```'
    result = parse_gemini_json(raw)
    assert result == {"key": "value"}


def test_json_fence_with_extra_whitespace_inside():
    """Whitespace inside the fence (after stripping) is handled."""
    raw = '```json\n\n  {"x": 1}  \n\n```'
    result = parse_gemini_json(raw)
    assert result == {"x": 1}


def test_nested_json_inside_fence():
    """Nested JSON structures inside a fence are fully parsed."""
    payload = {"sub_queries": [{"fn": "GET_COACHING_TREE", "args": {"coach": "Saban"}}]}
    raw = f"```json\n{json.dumps(payload)}\n```"
    result = parse_gemini_json(raw)
    assert result == payload


# ---------------------------------------------------------------------------
# Error path
# ---------------------------------------------------------------------------


def test_invalid_json_raises_decode_error():
    """Non-JSON content raises json.JSONDecodeError."""
    with pytest.raises(json.JSONDecodeError):
        parse_gemini_json("this is not json at all")


def test_invalid_json_inside_fence_raises_decode_error():
    """Malformed JSON inside a fence still raises json.JSONDecodeError."""
    with pytest.raises(json.JSONDecodeError):
        parse_gemini_json("```json\nnot json\n```")


def test_empty_string_raises_decode_error():
    """Empty string raises json.JSONDecodeError."""
    with pytest.raises(json.JSONDecodeError):
        parse_gemini_json("")
