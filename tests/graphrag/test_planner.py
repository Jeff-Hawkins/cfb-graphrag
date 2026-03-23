"""Tests for graphrag/planner.py."""

import json
from unittest.mock import MagicMock

import pytest

from graphrag.planner import (
    EntityBundle,
    SubQuery,
    SubQueryPlan,
    TraversalFn,
    _assemble_plan,
    build_plan,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_client(response_json: dict) -> MagicMock:
    """Return a mock genai.Client whose generate_content returns fixed JSON."""
    client = MagicMock()
    client.models.generate_content.return_value.text = json.dumps(response_json)
    return client


def _gemini_response(
    *,
    coaches: list[str] | None = None,
    teams: list[str] | None = None,
    conferences: list[str] | None = None,
    year_start: int | None = None,
    year_end: int | None = None,
    roles: list[str] | None = None,
    ambiguous: list[str] | None = None,
    missing_required: list[str] | None = None,
    sub_queries: list[dict] | None = None,
    warnings: list[str] | None = None,
) -> dict:
    """Build a minimal valid Gemini planner response dict."""
    return {
        "coaches": coaches or [],
        "teams": teams or [],
        "conferences": conferences or [],
        "year_start": year_start,
        "year_end": year_end,
        "roles": roles or [],
        "ambiguous": ambiguous or [],
        "missing_required": missing_required or [],
        "sub_queries": sub_queries or [],
        "warnings": warnings or [],
    }


def _sq(
    id: str,
    traversal_fn: str,
    params: dict | None = None,
    depends_on: list[str] | None = None,
    description: str = "",
) -> dict:
    """Build a single sub-query dict for use in _gemini_response."""
    return {
        "id": id,
        "traversal_fn": traversal_fn,
        "params": params or {},
        "depends_on": depends_on or [],
        "description": description,
    }


# ---------------------------------------------------------------------------
# TREE_QUERY
# ---------------------------------------------------------------------------


def test_tree_query_saban_hc_filter():
    """'Every coach who worked under Saban and became a HC' → TREE_QUERY with role_filter='HC'.

    Acceptance criteria from task spec.
    """
    response = _gemini_response(
        coaches=["Nick Saban"],
        roles=["HC"],
        sub_queries=[
            _sq(
                "sq1",
                TraversalFn.GET_COACHING_TREE,
                params={"coach_name": "Nick Saban", "role_filter": "HC", "max_depth": 4},
                description="Coaching tree for Nick Saban, filtered to head coaches",
            )
        ],
    )
    client = _mock_client(response)
    plan = build_plan(
        question="Show me every coach who worked under Saban and became a head coach",
        intent="TREE_QUERY",
        confidence=0.97,
        client=client,
    )

    assert plan.intent == "TREE_QUERY"
    assert plan.confidence == 0.97
    assert plan.ready is True
    assert plan.entities.coaches == ["Nick Saban"]
    assert plan.entities.roles == ["HC"]
    assert len(plan.sub_queries) == 1

    sq = plan.sub_queries[0]
    assert sq.traversal_fn == TraversalFn.GET_COACHING_TREE
    assert sq.params["coach_name"] == "Nick Saban"
    assert sq.params["role_filter"] == "HC"
    assert sq.params["max_depth"] == 4
    assert sq.depends_on == []


def test_tree_query_direct_reports_max_depth_override():
    """'Saban's direct reports only' → max_depth clamped / preserved as 1."""
    response = _gemini_response(
        coaches=["Nick Saban"],
        sub_queries=[
            _sq(
                "sq1",
                TraversalFn.GET_COACHING_TREE,
                params={"coach_name": "Nick Saban", "max_depth": 1},
                description="Direct reports of Nick Saban only",
            )
        ],
    )
    client = _mock_client(response)
    plan = build_plan(
        question="Show me Nick Saban's direct reports only",
        intent="TREE_QUERY",
        confidence=0.91,
        client=client,
    )

    assert plan.ready is True
    assert plan.sub_queries[0].params["max_depth"] == 1


def test_tree_query_max_depth_out_of_range_is_clamped():
    """max_depth > 4 from Gemini is clamped to 4 with a warning."""
    response = _gemini_response(
        coaches=["Nick Saban"],
        sub_queries=[
            _sq(
                "sq1",
                TraversalFn.GET_COACHING_TREE,
                params={"coach_name": "Nick Saban", "max_depth": 99},
            )
        ],
    )
    client = _mock_client(response)
    plan = build_plan(
        question="Show me Saban's entire tree",
        intent="TREE_QUERY",
        confidence=0.88,
        client=client,
    )

    assert plan.sub_queries[0].params["max_depth"] == 4
    assert any("clamped" in w for w in plan.warnings)


# ---------------------------------------------------------------------------
# PERFORMANCE_COMPARE
# ---------------------------------------------------------------------------


def test_performance_compare_two_coaches_with_combine():
    """'Compare Kirby Smart's defense to Brian Kelly's over last 5 years'.

    Acceptance criteria from task spec:  two independent coach sub-queries +
    one combine sub-query depending on both.
    """
    response = _gemini_response(
        coaches=["Kirby Smart", "Brian Kelly"],
        roles=["DC"],
        year_start=2021,
        year_end=2026,
        sub_queries=[
            _sq(
                "sq1",
                TraversalFn.GET_COACH_TREE,
                params={"coach_name": "Kirby Smart"},
                description="Coaching data for Kirby Smart",
            ),
            _sq(
                "sq2",
                TraversalFn.GET_COACH_TREE,
                params={"coach_name": "Brian Kelly"},
                description="Coaching data for Brian Kelly",
            ),
            _sq(
                "sq3",
                TraversalFn.COMBINE,
                params={"strategy": "compare", "year_start": 2021, "year_end": 2026},
                depends_on=["sq1", "sq2"],
                description="Compare defensive coaching data for Kirby Smart vs Brian Kelly (2021-2026)",
            ),
        ],
    )
    client = _mock_client(response)
    plan = build_plan(
        question="Compare Kirby Smart's defense to Brian Kelly's over the last 5 years",
        intent="PERFORMANCE_COMPARE",
        confidence=0.92,
        client=client,
    )

    assert plan.intent == "PERFORMANCE_COMPARE"
    assert plan.ready is True
    assert plan.entities.coaches == ["Kirby Smart", "Brian Kelly"]
    assert plan.entities.year_start == 2021
    assert plan.entities.year_end == 2026
    assert len(plan.sub_queries) == 3

    # First two sub-queries are independent coach traversals.
    sq1, sq2, sq3 = plan.sub_queries
    assert sq1.traversal_fn == TraversalFn.GET_COACH_TREE
    assert sq1.params["coach_name"] == "Kirby Smart"
    assert sq1.depends_on == []

    assert sq2.traversal_fn == TraversalFn.GET_COACH_TREE
    assert sq2.params["coach_name"] == "Brian Kelly"
    assert sq2.depends_on == []

    # Third sub-query is the combine step.
    assert sq3.traversal_fn == TraversalFn.COMBINE
    assert sq3.params["strategy"] == "compare"
    assert set(sq3.depends_on) == {"sq1", "sq2"}


# ---------------------------------------------------------------------------
# PIPELINE_QUERY
# ---------------------------------------------------------------------------


def test_pipeline_query_dc_to_hc_role_transition():
    """'Which DCs became HCs in the last 5 years?' → PIPELINE_QUERY."""
    response = _gemini_response(
        roles=["DC", "HC"],
        year_start=2021,
        year_end=2026,
        sub_queries=[
            _sq(
                "sq1",
                TraversalFn.GET_COACHES_IN_CONFERENCES,
                params={"conferences": []},
                description="Find coaches who transitioned from DC to HC role",
            )
        ],
    )
    client = _mock_client(response)
    plan = build_plan(
        question="Which defensive coordinators became head coaches in the last 5 years?",
        intent="PIPELINE_QUERY",
        confidence=0.88,
        client=client,
    )

    assert plan.intent == "PIPELINE_QUERY"
    assert plan.ready is True
    assert "DC" in plan.entities.roles
    assert "HC" in plan.entities.roles
    assert plan.entities.year_start == 2021


# ---------------------------------------------------------------------------
# CHANGE_IMPACT
# ---------------------------------------------------------------------------


def test_change_impact_after_coach_event():
    """'How did Alabama's defense change after Saban retired?' → CHANGE_IMPACT."""
    response = _gemini_response(
        coaches=["Nick Saban"],
        teams=["Alabama"],
        sub_queries=[
            _sq(
                "sq1",
                TraversalFn.GET_COACH_TREE,
                params={"coach_name": "Nick Saban"},
                description="Retrieve Alabama defensive staff under Saban",
            )
        ],
    )
    client = _mock_client(response)
    plan = build_plan(
        question="How did Alabama's defense change after Saban retired?",
        intent="CHANGE_IMPACT",
        confidence=0.85,
        client=client,
    )

    assert plan.intent == "CHANGE_IMPACT"
    assert plan.ready is True
    assert "Nick Saban" in plan.entities.coaches
    assert "Alabama" in plan.entities.teams
    assert plan.sub_queries[0].traversal_fn == TraversalFn.GET_COACH_TREE


# ---------------------------------------------------------------------------
# SIMILARITY
# ---------------------------------------------------------------------------


def test_similarity_shortest_path_between_coaches():
    """'Shortest path between Kirby Smart and Lincoln Riley' → SIMILARITY."""
    response = _gemini_response(
        coaches=["Kirby Smart", "Lincoln Riley"],
        sub_queries=[
            _sq(
                "sq1",
                TraversalFn.SHORTEST_PATH_BETWEEN_COACHES,
                params={"coach_a": "Kirby Smart", "coach_b": "Lincoln Riley"},
                description="Shortest path between Kirby Smart and Lincoln Riley",
            )
        ],
    )
    client = _mock_client(response)
    plan = build_plan(
        question="What is the shortest path between Kirby Smart and Lincoln Riley?",
        intent="SIMILARITY",
        confidence=0.95,
        client=client,
    )

    assert plan.intent == "SIMILARITY"
    assert plan.ready is True
    assert len(plan.sub_queries) == 1

    sq = plan.sub_queries[0]
    assert sq.traversal_fn == TraversalFn.SHORTEST_PATH_BETWEEN_COACHES
    assert sq.params["coach_a"] == "Kirby Smart"
    assert sq.params["coach_b"] == "Lincoln Riley"


# ---------------------------------------------------------------------------
# Edge cases — missing entities / ambiguity
# ---------------------------------------------------------------------------


def test_missing_required_coach_sets_ready_false():
    """TREE_QUERY with no coach name → ready=False, missing_required populated."""
    response = _gemini_response(
        coaches=[],
        missing_required=["coach"],
        sub_queries=[],
    )
    client = _mock_client(response)
    plan = build_plan(
        question="Show me the coaching tree",
        intent="TREE_QUERY",
        confidence=0.6,
        client=client,
    )

    assert plan.ready is False
    assert "coach" in plan.entities.missing_required


def test_missing_second_coach_for_similarity_sets_ready_false():
    """SIMILARITY with only one coach → ready=False."""
    response = _gemini_response(
        coaches=["Kirby Smart"],
        missing_required=["second_coach"],
        sub_queries=[],
    )
    client = _mock_client(response)
    plan = build_plan(
        question="Who is most similar to Kirby Smart?",
        intent="SIMILARITY",
        confidence=0.7,
        client=client,
    )

    assert plan.ready is False
    assert "second_coach" in plan.entities.missing_required


def test_unknown_traversal_fn_skipped_with_warning():
    """Sub-query with an unknown traversal_fn is skipped; a warning is appended."""
    response = _gemini_response(
        coaches=["Nick Saban"],
        sub_queries=[
            _sq("sq1", "nonexistent_fn", params={"coach_name": "Nick Saban"}),
            _sq(
                "sq2",
                TraversalFn.GET_COACHING_TREE,
                params={"coach_name": "Nick Saban", "max_depth": 4},
            ),
        ],
    )
    client = _mock_client(response)
    plan = build_plan(
        question="Show me Saban's tree",
        intent="TREE_QUERY",
        confidence=0.9,
        client=client,
    )

    # Only sq2 should survive.
    assert len(plan.sub_queries) == 1
    assert plan.sub_queries[0].id == "sq2"
    assert any("nonexistent_fn" in w for w in plan.warnings)


def test_non_json_gemini_response_returns_fallback_plan():
    """Non-JSON Gemini response → fallback plan with ready=False, no crash."""
    client = MagicMock()
    client.models.generate_content.return_value.text = "I cannot help with that."

    plan = build_plan(
        question="Show me Saban's tree",
        intent="TREE_QUERY",
        confidence=0.97,
        client=client,
    )

    assert plan.ready is False
    assert plan.sub_queries == []
    assert any("Planner Gemini call failed" in w for w in plan.warnings)


def test_empty_sub_queries_from_gemini_sets_ready_false():
    """Even with entities present, an empty sub_queries list → ready=False."""
    response = _gemini_response(
        coaches=["Nick Saban"],
        sub_queries=[],
    )
    client = _mock_client(response)
    plan = build_plan(
        question="Show me Saban's tree",
        intent="TREE_QUERY",
        confidence=0.97,
        client=client,
    )

    assert plan.ready is False
    assert plan.entities.coaches == ["Nick Saban"]


# ---------------------------------------------------------------------------
# Plan structural invariants
# ---------------------------------------------------------------------------


def test_plan_preserves_original_question():
    """The original question string is preserved verbatim on the plan."""
    question = "Compare Kirby Smart's defense to Brian Kelly's over the last 5 years"
    response = _gemini_response(
        coaches=["Kirby Smart", "Brian Kelly"],
        sub_queries=[
            _sq("sq1", TraversalFn.GET_COACH_TREE, params={"coach_name": "Kirby Smart"}),
        ],
    )
    client = _mock_client(response)
    plan = build_plan(question=question, intent="PERFORMANCE_COMPARE", confidence=0.9, client=client)

    assert plan.question == question


def test_plan_passthrough_confidence_and_intent():
    """intent and confidence are passed through unchanged from the caller."""
    response = _gemini_response(
        coaches=["Kirby Smart", "Lincoln Riley"],
        sub_queries=[
            _sq(
                "sq1",
                TraversalFn.SHORTEST_PATH_BETWEEN_COACHES,
                params={"coach_a": "Kirby Smart", "coach_b": "Lincoln Riley"},
            )
        ],
    )
    client = _mock_client(response)
    plan = build_plan(
        question="Path between Kirby and Riley",
        intent="SIMILARITY",
        confidence=0.77,
        client=client,
    )

    assert plan.intent == "SIMILARITY"
    assert plan.confidence == 0.77


def test_get_coaching_tree_default_max_depth_injected_when_missing():
    """If Gemini omits max_depth, the planner injects the default value of 4."""
    response = _gemini_response(
        coaches=["Nick Saban"],
        sub_queries=[
            _sq(
                "sq1",
                TraversalFn.GET_COACHING_TREE,
                # Intentionally omit max_depth
                params={"coach_name": "Nick Saban"},
            )
        ],
    )
    client = _mock_client(response)
    plan = build_plan(
        question="Show me Saban's full coaching tree",
        intent="TREE_QUERY",
        confidence=0.95,
        client=client,
    )

    assert plan.sub_queries[0].params["max_depth"] == 4
