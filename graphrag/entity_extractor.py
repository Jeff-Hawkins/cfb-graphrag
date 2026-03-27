"""Extract named entities (teams, coaches, players) from natural language queries.

Uses Gemini to identify entity names so they can be matched against Neo4j nodes.
"""

import logging
import os
from typing import Any

from google import genai
from google.genai import types
from neo4j import Driver

from graphrag.utils import parse_gemini_json

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are an entity extractor for a college football knowledge graph.
Given a natural language question, return a JSON object with the following keys:
- "coaches": list of coach full names mentioned or implied
- "teams": list of team/school names mentioned or implied
- "players": list of player names mentioned or implied

Return ONLY valid JSON with no additional text."""


def extract_entities(
    question: str,
    client: genai.Client | None = None,
) -> dict[str, list[str]]:
    """Extract college football entities from a natural language question.

    Sends the question to Gemini and parses the returned JSON to identify
    coaches, teams, and players that should be looked up in the graph.

    Args:
        question: A natural language question about college football.
        client: Optional pre-constructed ``genai.Client``.  If omitted
            a new client is created using ``GEMINI_API_KEY`` from the environment.

    Returns:
        Dict with keys ``"coaches"``, ``"teams"``, and ``"players"``, each
        mapping to a (possibly empty) list of name strings.

    Raises:
        ValueError: If Gemini returns a response that cannot be parsed as JSON.
    """
    if client is None:
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=question,
        config=types.GenerateContentConfig(system_instruction=_SYSTEM_PROMPT),
    )
    raw = response.text.strip()

    try:
        entities: dict[str, Any] = parse_gemini_json(raw)
    except ValueError as exc:
        raise ValueError(f"Gemini returned non-JSON entity response: {raw!r}") from exc

    return {
        "coaches": entities.get("coaches", []),
        "teams": entities.get("teams", []),
        "players": entities.get("players", []),
    }


def resolve_coach_entity(name: str, driver: Driver) -> dict[str, Any]:
    """Resolve a coach name to CFBD and/or McIllece graph nodes.

    Looks up the coach by first_name + last_name (CFBD node), then traverses
    any SAME_PERSON edge to find the associated McIllece coach_code.

    Args:
        name: Full coach name string (e.g. ``"Nick Saban"``).
        driver: Open Neo4j driver connected to the graph.

    Returns:
        Dict with keys:

        - ``cfbd_node_id``  — Neo4j elementId of the CFBD Coach node, or None.
        - ``mc_coach_code`` — McIllece coach_code integer, or None.
        - ``display_name``  — canonical name string.
        - ``source``        — one of ``"cfbd_only"``, ``"mcillece_only"``, ``"both"``.
    """
    parts = name.strip().split(None, 1)
    if len(parts) != 2:
        return {
            "cfbd_node_id": None,
            "mc_coach_code": None,
            "display_name": name,
            "source": "cfbd_only",
        }

    first, last = parts[0], parts[1]

    query = """
    MATCH (cfbd:Coach {first_name: $first, last_name: $last})
    OPTIONAL MATCH (cfbd)-[:SAME_PERSON]->(mc:Coach)
    WHERE mc.coach_code IS NOT NULL
    RETURN elementId(cfbd) AS cfbd_id,
           mc.coach_code   AS mc_code
    LIMIT 1
    """
    with driver.session() as session:
        result = session.run(query, first=first, last=last)
        record = result.single()

    if record is None:
        return {
            "cfbd_node_id": None,
            "mc_coach_code": None,
            "display_name": name,
            "source": "cfbd_only",
        }

    cfbd_id = record["cfbd_id"]
    mc_code = record["mc_code"]

    if mc_code is not None:
        source = "both"
    else:
        source = "cfbd_only"

    return {
        "cfbd_node_id": cfbd_id,
        "mc_coach_code": mc_code,
        "display_name": name,
        "source": source,
    }
