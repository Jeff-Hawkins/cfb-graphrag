"""Shared utilities for the GraphRAG pipeline."""

import json
import re
from typing import Any


def parse_gemini_json(raw: str) -> dict[str, Any]:
    """Parse a JSON string that may be wrapped in Gemini markdown code fences.

    Gemini 2.5 Flash sometimes wraps JSON responses in markdown code fences
    (e.g. ```json ... ``` or ``` ... ```) even when instructed to return plain
    JSON.  This function strips those fences before parsing so callers do not
    need to handle the inconsistency themselves.

    Args:
        raw: Raw text returned by a Gemini model call (already ``.strip()``ed
            is fine, but not required).

    Returns:
        Parsed JSON as a dict.

    Raises:
        json.JSONDecodeError: If the text — after fence-stripping — is not
            valid JSON.
    """
    text = raw.strip()

    # Strip ```json ... ``` or ``` ... ``` fences
    fence_match = re.match(r"^```(?:json)?\s*\n?(.*?)\n?```$", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    return json.loads(text)
