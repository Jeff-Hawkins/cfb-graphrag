"""Query intent classifier for the GraphRAG pipeline.

Routes every incoming NL query into one of five intent buckets before
the planner generates Cypher, dramatically improving traversal accuracy.

Intent buckets:
  TREE_QUERY         — coaching tree / lineage queries
  PERFORMANCE_COMPARE — compare two coaches or programs
  PIPELINE_QUERY     — role-transition queries (DCs who became HCs, etc.)
  CHANGE_IMPACT      — how did something change after an event?
  SIMILARITY         — who is most similar to / shortest path between?
"""

import json
import logging
import os
from typing import Any

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

_VALID_INTENTS = frozenset(
    {"TREE_QUERY", "PERFORMANCE_COMPARE", "PIPELINE_QUERY", "CHANGE_IMPACT", "SIMILARITY"}
)

_CLASSIFY_SYSTEM = """You are a query classifier for a college football coaching knowledge graph.

Classify the user's question into EXACTLY ONE of these intent buckets:

  TREE_QUERY         - Questions about coaching trees, lineage, staff hierarchies, or who came from a specific coach's staff.
  PERFORMANCE_COMPARE - Comparing stats, results, or records between two coaches, programs, or coordinators.
  PIPELINE_QUERY     - Questions about role transitions (e.g. which DCs became HCs, coaches who moved conferences).
  CHANGE_IMPACT      - Questions about how something changed after an event (coaching change, retirement, etc.).
  SIMILARITY         - Questions about similarity between coaches, or shortest path between two coaches.

Return a JSON object with exactly two keys:
  "intent": one of the five bucket strings above (ALL CAPS, exact spelling)
  "confidence": float between 0.0 and 1.0

If the query is ambiguous, pick the most likely intent and set confidence < 0.7.
Return ONLY valid JSON with no additional text."""

_FALLBACK_INTENT = "TREE_QUERY"


def classify_intent(
    question: str,
    client: genai.Client | None = None,
) -> dict[str, Any]:
    """Classify the intent of a natural language query.

    Makes a single Gemini call with a tight classification prompt and returns
    the intent bucket and confidence score.

    Args:
        question: Natural language question about college football.
        client: Optional pre-constructed ``genai.Client``.  If omitted
            a new client is created using ``GEMINI_API_KEY`` from the environment.

    Returns:
        Dict with keys:

        - ``intent``     — one of TREE_QUERY | PERFORMANCE_COMPARE |
          PIPELINE_QUERY | CHANGE_IMPACT | SIMILARITY.
        - ``confidence`` — float in [0.0, 1.0].
    """
    if client is None:
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=question,
            config=types.GenerateContentConfig(system_instruction=_CLASSIFY_SYSTEM),
        )
        raw = response.text.strip()
        parsed: dict[str, Any] = json.loads(raw)
    except (json.JSONDecodeError, Exception) as exc:
        logger.warning("Classifier failed (%s); defaulting to %s", exc, _FALLBACK_INTENT)
        return {"intent": _FALLBACK_INTENT, "confidence": 0.0}

    intent = parsed.get("intent", _FALLBACK_INTENT)
    confidence = float(parsed.get("confidence", 0.0))

    # Validate intent is a known bucket
    if intent not in _VALID_INTENTS:
        logger.warning(
            "Unknown intent %r returned by classifier; defaulting to %s",
            intent,
            _FALLBACK_INTENT,
        )
        intent = _FALLBACK_INTENT
        confidence = 0.0

    return {"intent": intent, "confidence": confidence}
