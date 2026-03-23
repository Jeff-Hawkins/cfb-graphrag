"""Sub-query decomposition module for the GraphRAG pipeline.

Receives a classified intent and the original NL query, then makes a single
Gemini call to extract entities *and* produce an ordered sub-query execution
plan.  The plan is returned as a typed :class:`SubQueryPlan` dataclass — not
raw strings — ready for the executor to run against Neo4j.

Pipeline position::

    NL query → classifier.py → planner.py → executor.py → retry.py → synthesizer.py

Typical usage::

    from graphrag.classifier import classify_intent
    from graphrag.planner import build_plan

    classification = classify_intent(question, client=client)
    plan = build_plan(
        question=question,
        intent=classification["intent"],
        confidence=classification["confidence"],
        client=client,
    )
    if plan.ready:
        # hand off to executor …
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Enum — allowed traversal function names
# ---------------------------------------------------------------------------


class TraversalFn(str, Enum):
    """Allowed values for :attr:`SubQuery.traversal_fn`.

    Each value maps to a function in :mod:`graphrag.graph_traversal`, except
    :attr:`COMBINE`, which is a virtual aggregation step handled by the
    executor / synthesizer to merge results from prior sub-queries.
    """

    GET_COACHING_TREE = "get_coaching_tree"
    """McIllece MENTORED edge traversal; preferred for lineage queries."""

    GET_COACH_TREE = "get_coach_tree"
    """CFBD-based coaching tree via shared COACHED_AT tenures."""

    GET_COACHES_IN_CONFERENCES = "get_coaches_in_conferences"
    """Finds coaches who worked across one or more conferences."""

    SHORTEST_PATH_BETWEEN_COACHES = "shortest_path_between_coaches"
    """Shortest COACHED_AT path between two coaches."""

    COMBINE = "combine"
    """Virtual step: aggregate / compare results from prior sub-queries."""


_VALID_TRAVERSAL_FNS: frozenset[str] = frozenset(fn.value for fn in TraversalFn)

_MAX_DEPTH_MIN = 1
_MAX_DEPTH_MAX = 4

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class EntityBundle:
    """All entities extracted from the NL query in one structured object.

    Attributes:
        coaches: Full coach names extracted from the query.
        teams: School / team names.
        conferences: Conference names in standard form (e.g. ``"SEC"``).
        year_start: Earliest year mentioned, or ``None``.
        year_end: Latest year mentioned, or ``None``.
        roles: Role abbreviations found in the query (e.g. ``["HC", "DC"]``).
        ambiguous: Items Gemini could not cleanly classify into a category.
        missing_required: Entity types required by the intent but not found
            (e.g. ``["coach"]``, ``["second_coach"]``, ``["conference"]``).
    """

    coaches: list[str] = field(default_factory=list)
    teams: list[str] = field(default_factory=list)
    conferences: list[str] = field(default_factory=list)
    year_start: int | None = None
    year_end: int | None = None
    roles: list[str] = field(default_factory=list)
    ambiguous: list[str] = field(default_factory=list)
    missing_required: list[str] = field(default_factory=list)


@dataclass
class SubQuery:
    """A single step in the query execution plan.

    Attributes:
        id: Short identifier (``"sq1"``, ``"sq2"``, …).
        traversal_fn: Name of the graph traversal function to call.  Must be
            a value from :class:`TraversalFn`.
        params: Keyword arguments for the traversal function (excluding
            ``driver``).  Coach names are stored as strings here; the executor
            resolves them to graph IDs via
            :func:`graphrag.entity_extractor.resolve_coach_entity`.
        depends_on: IDs of sub-queries whose results must be available before
            this sub-query runs.  Empty list means no dependencies (can run
            immediately or in parallel with other dependency-free sub-queries).
        description: Human-readable summary used for logging and F1 provenance.
    """

    id: str
    traversal_fn: str
    params: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    description: str = ""


@dataclass
class SubQueryPlan:
    """Fully typed sub-query execution plan produced by :func:`build_plan`.

    Attributes:
        intent: Classifier intent bucket (one of the five valid strings).
        confidence: Classifier confidence score in ``[0.0, 1.0]``.
        question: Original NL question (preserved for tracing and F1).
        entities: All entities extracted from the question.
        sub_queries: Ordered list of sub-queries to execute.
        ready: ``False`` when required entities are missing or no sub-queries
            were generated.  The executor must check this flag before running.
        warnings: Non-fatal issues to surface to the caller (e.g. ambiguous
            entity names, sub-queries with unknown traversal functions that
            were skipped).
    """

    intent: str
    confidence: float
    question: str
    entities: EntityBundle
    sub_queries: list[SubQuery]
    ready: bool
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Gemini system prompt
# ---------------------------------------------------------------------------

_PLANNER_SYSTEM = """You are a sub-query planner for a college football coaching knowledge graph.

Given a classified intent and a natural language question, you must:
  1. Extract all relevant entities from the question.
  2. Generate an ordered list of sub-queries to retrieve the data needed to answer it.

AVAILABLE TRAVERSAL FUNCTIONS:

  get_coaching_tree
    Traverses MENTORED edges from a root coach (McIllece staff data 2005-2025).
    Required params: coach_name (str), max_depth (int 1-4)
    Optional params: role_filter (str) — e.g. "HC", "OC", "DC"
    Preferred for TREE_QUERY (lineage / mentorship questions).
    max_depth rules — default 4; override ONLY when the query clearly limits scope:
      "direct reports only" / "immediate staff" / "one level" → max_depth = 1
      "two levels" / "two hops" → max_depth = 2
      "three levels" → max_depth = 3

  get_coach_tree
    Finds coaches who overlapped at the same programs (CFBD data).
    Required params: coach_name (str)
    Use as fallback for TREE_QUERY or as the per-coach query in PERFORMANCE_COMPARE.

  get_coaches_in_conferences
    Finds coaches who worked at programs in one or more conferences.
    Required params: conferences (list of str, e.g. ["SEC", "Big Ten"])
    Use for PIPELINE_QUERY when conferences are mentioned.

  shortest_path_between_coaches
    Finds the shortest COACHED_AT path between two coaches.
    Required params: coach_a (str), coach_b (str)
    Use for SIMILARITY.

  combine
    Virtual aggregation step — no graph call.
    Required params: strategy (str) — one of "compare", "merge", "intersect"
    Optional params: year_start (int), year_end (int)
    depends_on must list all sub-query IDs being combined.
    Use as the final step in PERFORMANCE_COMPARE.

INTENT ROUTING RULES:

  TREE_QUERY → get_coaching_tree (preferred) or get_coach_tree (fallback).
    Set role_filter when the query mentions a specific role (HC, DC, OC, etc.).

  PERFORMANCE_COMPARE → one get_coach_tree per coach (no dependency between them),
    then one combine sub-query with strategy="compare" that depends_on all coach sub-queries.
    Set year_start / year_end on combine params if a time range is specified.

  PIPELINE_QUERY → get_coaches_in_conferences when conferences are mentioned;
    otherwise get_coach_tree with role transition context in the description.

  CHANGE_IMPACT → get_coach_tree for each coach mentioned.
    Capture temporal context via year_start / year_end in the entity fields.

  SIMILARITY → shortest_path_between_coaches with coach_a and coach_b.
    Requires exactly two coach names.

ENTITY EXTRACTION RULES:
  - Resolve partial or informal names to full names when unambiguous
    (e.g. "Saban" → "Nick Saban", "Kirby" → "Kirby Smart").
  - If a name is genuinely ambiguous (multiple plausible matches), add it to ambiguous[].
  - missing_required: list entity TYPES needed by this intent but not present in the query:
      "coach" — at least one coach name required,
      "second_coach" — PERFORMANCE_COMPARE or SIMILARITY requires two coaches,
      "conference" — get_coaches_in_conferences needs at least one.
  - Year ranges: "last 5 years" from the current year 2026 → year_start=2021, year_end=2026.
    "last N years" → year_start = (2026 - N), year_end = 2026.
  - Conference names in standard form: "SEC", "Big Ten", "ACC", "Big 12", "Pac-12", etc.
  - Role abbreviations: HC (head coach), OC (offensive coordinator), DC (defensive coordinator),
    QB, RB, WR, OL, DL, DB, LB, TE, DE, DT, CB, ST (special teams).

Return ONLY valid JSON — no markdown, no code fences, no explanation.

Required schema (include all fields even if empty / null):
{
  "coaches": [],
  "teams": [],
  "conferences": [],
  "year_start": null,
  "year_end": null,
  "roles": [],
  "ambiguous": [],
  "missing_required": [],
  "sub_queries": [
    {
      "id": "sq1",
      "traversal_fn": "",
      "params": {},
      "depends_on": [],
      "description": ""
    }
  ],
  "warnings": []
}"""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _clamp_max_depth(params: dict[str, Any], warnings: list[str], sq_id: str) -> None:
    """Clamp max_depth in-place to [1, 4] for get_coaching_tree sub-queries.

    Args:
        params: Mutable params dict for the sub-query.
        warnings: Mutable warnings list; a warning is appended when clamping occurs.
        sq_id: Sub-query identifier used in the warning message.
    """
    if "max_depth" not in params:
        params["max_depth"] = _MAX_DEPTH_MAX
        return
    original = params["max_depth"]
    clamped = max(_MAX_DEPTH_MIN, min(int(original), _MAX_DEPTH_MAX))
    if clamped != original:
        warnings.append(
            f"{sq_id}: max_depth {original!r} out of range; clamped to {clamped}."
        )
    params["max_depth"] = clamped


def _assemble_plan(
    parsed: dict[str, Any],
    question: str,
    intent: str,
    confidence: float,
) -> SubQueryPlan:
    """Assemble and validate a :class:`SubQueryPlan` from Gemini's parsed JSON.

    Args:
        parsed: Deserialized JSON dict from the Gemini response.
        question: Original NL question.
        intent: Classified intent bucket string.
        confidence: Classifier confidence score.

    Returns:
        A fully populated :class:`SubQueryPlan`.
    """
    entities = EntityBundle(
        coaches=parsed.get("coaches") or [],
        teams=parsed.get("teams") or [],
        conferences=parsed.get("conferences") or [],
        year_start=parsed.get("year_start"),
        year_end=parsed.get("year_end"),
        roles=parsed.get("roles") or [],
        ambiguous=parsed.get("ambiguous") or [],
        missing_required=parsed.get("missing_required") or [],
    )

    raw_sqs: list[dict[str, Any]] = parsed.get("sub_queries") or []
    sub_queries: list[SubQuery] = []
    warnings: list[str] = list(parsed.get("warnings") or [])

    for sq_data in raw_sqs:
        fn = sq_data.get("traversal_fn", "")
        sq_id = sq_data.get("id", f"sq{len(sub_queries) + 1}")

        if fn not in _VALID_TRAVERSAL_FNS:
            warnings.append(
                f"{sq_id}: unknown traversal_fn {fn!r}; sub-query skipped."
            )
            continue

        params: dict[str, Any] = dict(sq_data.get("params") or {})

        # Enforce max_depth bounds for get_coaching_tree sub-queries.
        if fn == TraversalFn.GET_COACHING_TREE:
            _clamp_max_depth(params, warnings, sq_id)

        sub_queries.append(
            SubQuery(
                id=sq_id,
                traversal_fn=fn,
                params=params,
                depends_on=list(sq_data.get("depends_on") or []),
                description=sq_data.get("description", ""),
            )
        )

    ready = not entities.missing_required and bool(sub_queries)

    return SubQueryPlan(
        intent=intent,
        confidence=confidence,
        question=question,
        entities=entities,
        sub_queries=sub_queries,
        ready=ready,
        warnings=warnings,
    )


def _fallback_plan(
    question: str,
    intent: str,
    confidence: float,
    error: str,
) -> SubQueryPlan:
    """Return a minimal non-ready plan when the Gemini call fails.

    Args:
        question: Original NL question.
        intent: Classified intent bucket string.
        confidence: Classifier confidence score.
        error: Error description to surface in warnings.

    Returns:
        A :class:`SubQueryPlan` with ``ready=False`` and the error in warnings.
    """
    return SubQueryPlan(
        intent=intent,
        confidence=confidence,
        question=question,
        entities=EntityBundle(missing_required=["all"]),
        sub_queries=[],
        ready=False,
        warnings=[f"Planner Gemini call failed: {error}"],
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_plan(
    question: str,
    intent: str,
    confidence: float,
    client: genai.Client | None = None,
) -> SubQueryPlan:
    """Decompose a classified NL query into an ordered sub-query execution plan.

    Makes a **single** Gemini call that simultaneously extracts entities
    (coaches, teams, conferences, year ranges, roles) and generates the
    structured sub-query plan.  No Neo4j calls are made here — entity names
    are stored as strings and resolved to graph IDs by the executor.

    Args:
        question: Original natural language query.
        intent: Classified intent bucket from :func:`graphrag.classifier.classify_intent`.
            One of ``TREE_QUERY``, ``PERFORMANCE_COMPARE``, ``PIPELINE_QUERY``,
            ``CHANGE_IMPACT``, ``SIMILARITY``.
        confidence: Classifier confidence score, passed through to the plan
            for use by the executor / synthesizer.
        client: Optional pre-constructed ``genai.Client``.  If omitted a new
            client is created using ``GEMINI_API_KEY`` from the environment.

    Returns:
        A :class:`SubQueryPlan` dataclass.  Check :attr:`SubQueryPlan.ready`
        before passing to the executor — ``False`` means required entities
        are missing or the Gemini call failed.

    Example::

        plan = build_plan(
            question="Show me every coach who worked under Saban and became a head coach",
            intent="TREE_QUERY",
            confidence=0.97,
            client=client,
        )
        # plan.entities.coaches == ["Nick Saban"]
        # plan.sub_queries[0].traversal_fn == "get_coaching_tree"
        # plan.sub_queries[0].params == {"coach_name": "Nick Saban",
        #                                "role_filter": "HC", "max_depth": 4}
        # plan.ready == True
    """
    if client is None:
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    prompt = f"Intent: {intent}\nQuestion: {question}"

    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=types.GenerateContentConfig(system_instruction=_PLANNER_SYSTEM),
        )
        raw = response.text.strip()
        parsed: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("Planner: non-JSON response from Gemini (%s)", exc)
        return _fallback_plan(question, intent, confidence, str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Planner: Gemini call failed (%s)", exc)
        return _fallback_plan(question, intent, confidence, str(exc))

    plan = _assemble_plan(parsed, question, intent, confidence)

    logger.info(
        "Planner: intent=%s ready=%s sub_queries=%d warnings=%d",
        plan.intent,
        plan.ready,
        len(plan.sub_queries),
        len(plan.warnings),
    )
    return plan
