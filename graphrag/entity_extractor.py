"""Extract named entities (teams, coaches, players) from natural language queries.

Uses Gemini to identify entity names so they can be matched against Neo4j nodes.
"""

import json
import logging
import os
from typing import Any

import google.generativeai as genai

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are an entity extractor for a college football knowledge graph.
Given a natural language question, return a JSON object with the following keys:
- "coaches": list of coach full names mentioned or implied
- "teams": list of team/school names mentioned or implied
- "players": list of player names mentioned or implied

Return ONLY valid JSON with no additional text."""


def extract_entities(
    question: str,
    model: genai.GenerativeModel | None = None,
) -> dict[str, list[str]]:
    """Extract college football entities from a natural language question.

    Sends the question to Gemini and parses the returned JSON to identify
    coaches, teams, and players that should be looked up in the graph.

    Args:
        question: A natural language question about college football.
        model: Optional pre-constructed ``genai.GenerativeModel``.  If omitted
            a new model is created using ``GEMINI_API_KEY`` from the environment.

    Returns:
        Dict with keys ``"coaches"``, ``"teams"``, and ``"players"``, each
        mapping to a (possibly empty) list of name strings.

    Raises:
        ValueError: If Gemini returns a response that cannot be parsed as JSON.
    """
    if model is None:
        genai.configure(api_key=os.environ["GEMINI_API_KEY"])
        model = genai.GenerativeModel(
            model_name="gemini-2.0-flash",
            system_instruction=_SYSTEM_PROMPT,
        )

    response = model.generate_content(question)
    raw = response.text.strip()

    try:
        entities: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Gemini returned non-JSON entity response: {raw!r}") from exc

    return {
        "coaches": entities.get("coaches", []),
        "teams": entities.get("teams", []),
        "players": entities.get("players", []),
    }
