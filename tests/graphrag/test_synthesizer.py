"""Tests for graphrag/synthesizer.py."""

from unittest.mock import MagicMock

from graphrag.executor import ExecutionResult
from graphrag.planner import EntityBundle, SubQuery, SubQueryPlan, TraversalFn
from graphrag.synthesizer import (
    ResultRow,
    SynthesisInput,
    SynthesizedResponse,
    _build_answer,
    _explain_coach_tree_row,
    _explain_coaching_tree_row,
    _rows_from_coach_tree,
    _rows_from_coaching_tree,
    synthesize_response,
)

# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_plan(
    *,
    intent: str = "TREE_QUERY",
    coaches: list[str] | None = None,
    sub_queries: list[SubQuery] | None = None,
    ready: bool = True,
) -> SubQueryPlan:
    return SubQueryPlan(
        intent=intent,
        confidence=0.9,
        question="test question",
        entities=EntityBundle(coaches=coaches or ["Nick Saban"]),
        sub_queries=sub_queries or [],
        ready=ready,
    )


def _make_result(
    plan: SubQueryPlan,
    *,
    subquery_results: dict | None = None,
    errors: list[str] | None = None,
    warnings: list[str] | None = None,
    ready: bool = True,
) -> ExecutionResult:
    return ExecutionResult(
        plan=plan,
        subquery_results=subquery_results or {},
        errors=errors or [],
        warnings=warnings or [],
        ready_for_synthesis=ready,
    )


def _sq(
    sq_id: str,
    traversal_fn: str,
    params: dict | None = None,
    depends_on: list[str] | None = None,
) -> SubQuery:
    return SubQuery(
        id=sq_id,
        traversal_fn=traversal_fn,
        params=params or {},
        depends_on=depends_on or [],
        description=f"test {sq_id}",
    )


# Reusable fixture data.
_TREE_ROWS = [
    {
        "name": "Kirby Smart",
        "coach_code": 42,
        "depth": 1,
        "path_coaches": ["Nick Saban", "Kirby Smart"],
    },
    {
        "name": "Lane Kiffin",
        "coach_code": 17,
        "depth": 1,
        "path_coaches": ["Nick Saban", "Lane Kiffin"],
    },
    {
        "name": "Mark Stoops",
        "coach_code": 99,
        "depth": 2,
        "path_coaches": ["Nick Saban", "Kirby Smart", "Mark Stoops"],
    },
]

_CFBD_ROWS = [
    {"root": "Nick Saban", "protege": "Kirby Smart", "team": "Alabama", "years": 2015},
    {"root": "Nick Saban", "protege": "Lane Kiffin", "team": "Alabama", "years": 2014},
]


# ---------------------------------------------------------------------------
# Unit tests — explanation helpers
# ---------------------------------------------------------------------------


class TestExplainCoachingTreeRow:
    """Tests for _explain_coaching_tree_row."""

    def test_depth_1_uses_direct_mentee(self):
        row = {"depth": 1, "path_coaches": ["Nick Saban", "Kirby Smart"]}
        explanation = _explain_coaching_tree_row(row, "Nick Saban")
        assert "direct mentee" in explanation
        assert "Nick Saban" in explanation

    def test_depth_2_uses_depth_label(self):
        row = {"depth": 2, "path_coaches": ["Nick Saban", "Kirby Smart", "Mark Stoops"]}
        explanation = _explain_coaching_tree_row(row, "Nick Saban")
        assert "depth-2 mentee" in explanation
        assert "Kirby Smart" in explanation  # direct mentor is path[-2]

    def test_short_path_falls_back_to_root_name(self):
        """When path_coaches has fewer than 2 entries, root_name is used."""
        row = {"depth": 1, "path_coaches": ["Nick Saban"]}
        explanation = _explain_coaching_tree_row(row, "Nick Saban")
        assert "Nick Saban" in explanation

    def test_empty_path_falls_back_to_root_name(self):
        row = {"depth": 1, "path_coaches": []}
        explanation = _explain_coaching_tree_row(row, "Nick Saban")
        assert "Nick Saban" in explanation

    def test_explanation_starts_with_included_because(self):
        row = {"depth": 1, "path_coaches": ["Nick Saban", "Kirby Smart"]}
        explanation = _explain_coaching_tree_row(row, "Nick Saban")
        assert explanation.startswith("Included because:")


class TestExplainCoachingTreeRowEnriched:
    """Tests for _explain_coaching_tree_row with COACHED_AT metadata present."""

    def test_full_metadata_produces_rich_format(self):
        """Complete role/team/years → roadmap target format with semantic role name."""
        row = {
            "depth": 1,
            "path_coaches": ["Nick Saban", "Kirby Smart"],
            "role": "OC",
            "team": "Alabama",
            "start_year": 2019,
            "end_year": 2022,
        }
        explanation = _explain_coaching_tree_row(row, "Nick Saban")
        assert explanation.startswith("Included because:")
        assert "Offensive Coordinator at Alabama" in explanation
        assert "(2019–22)" in explanation
        assert "coached under Nick Saban" in explanation

    def test_year_abbreviation_same_century(self):
        """start_year=2019, end_year=2022 → '(2019–22)' not '(2019–2022)'."""
        row = {
            "depth": 1,
            "path_coaches": ["Nick Saban", "Lane Kiffin"],
            "role": "OC",
            "team": "Alabama",
            "start_year": 2014,
            "end_year": 2016,
        }
        explanation = _explain_coaching_tree_row(row, "Nick Saban")
        assert "(2014–16)" in explanation
        assert "2016" not in explanation.replace("(2014–16)", "")

    def test_draft_info_appended_when_present(self):
        """draft_info field is appended after 'coached under' clause."""
        row = {
            "depth": 1,
            "path_coaches": ["Nick Saban", "Kirby Smart"],
            "role": "DC",
            "team": "Alabama",
            "start_year": 2008,
            "end_year": 2015,
            "draft_info": "produced 2 Day 1 picks",
        }
        explanation = _explain_coaching_tree_row(row, "Nick Saban")
        assert "produced 2 Day 1 picks" in explanation
        # draft_info should appear after coached_under
        coached_idx = explanation.index("coached under")
        draft_idx = explanation.index("produced 2 Day 1 picks")
        assert draft_idx > coached_idx

    def test_missing_years_omits_year_range(self):
        """role and team present but no years → no year range in output."""
        row = {
            "depth": 1,
            "path_coaches": ["Nick Saban", "Kirby Smart"],
            "role": "DC",
            "team": "Alabama",
        }
        explanation = _explain_coaching_tree_row(row, "Nick Saban")
        assert "Defensive Coordinator at Alabama" in explanation
        assert "coached under Nick Saban" in explanation
        assert "(" not in explanation

    def test_start_year_only_shows_single_year(self):
        """start_year present, end_year absent → single year in parens."""
        row = {
            "depth": 1,
            "path_coaches": ["Nick Saban", "Kirby Smart"],
            "role": "OC",
            "team": "Alabama",
            "start_year": 2020,
        }
        explanation = _explain_coaching_tree_row(row, "Nick Saban")
        assert "(2020)" in explanation

    def test_team_only_no_role(self):
        """team present but role absent → 'at Team' prefix, no role label."""
        row = {
            "depth": 1,
            "path_coaches": ["Nick Saban", "Kirby Smart"],
            "team": "Alabama",
            "start_year": 2019,
            "end_year": 2022,
        }
        explanation = _explain_coaching_tree_row(row, "Nick Saban")
        assert "at Alabama" in explanation
        assert "coached under Nick Saban" in explanation

    def test_role_only_no_team(self):
        """role present but team absent → semantic role name only."""
        row = {
            "depth": 1,
            "path_coaches": ["Nick Saban", "Kirby Smart"],
            "role": "OC",
        }
        explanation = _explain_coaching_tree_row(row, "Nick Saban")
        assert "Offensive Coordinator" in explanation
        assert "coached under Nick Saban" in explanation

    def test_no_coached_at_fields_falls_back_to_depth_format(self):
        """When no role/team, original depth-based format is used."""
        row = {"depth": 1, "path_coaches": ["Nick Saban", "Kirby Smart"]}
        explanation = _explain_coaching_tree_row(row, "Nick Saban")
        assert "direct mentee" in explanation
        assert "OC" not in explanation
        assert "Alabama" not in explanation

    def test_empty_role_string_falls_back_to_depth_format(self):
        """Empty string role treated as absent → depth-based fallback."""
        row = {
            "depth": 1,
            "path_coaches": ["Nick Saban", "Kirby Smart"],
            "role": "",
            "team": "",
        }
        explanation = _explain_coaching_tree_row(row, "Nick Saban")
        assert "direct mentee" in explanation

    def test_mentor_comes_from_path_coaches(self):
        """When full metadata present, mentor still reflects path_coaches[-2]."""
        row = {
            "depth": 2,
            "path_coaches": ["Nick Saban", "Kirby Smart", "Mark Stoops"],
            "role": "LB",
            "team": "Georgia",
            "start_year": 2018,
            "end_year": 2022,
        }
        explanation = _explain_coaching_tree_row(row, "Nick Saban")
        # Mentor should be Kirby Smart (path[-2]), not Nick Saban
        assert "coached under Kirby Smart" in explanation
        assert "coached under Nick Saban" not in explanation


class TestExplainCoachTreeRow:
    """Tests for _explain_coach_tree_row."""

    def test_includes_root_team_year(self):
        row = {
            "root": "Nick Saban",
            "protege": "Kirby Smart",
            "team": "Alabama",
            "years": 2015,
        }
        explanation = _explain_coach_tree_row(row)
        assert "Nick Saban" in explanation
        assert "Alabama" in explanation
        assert "2015" in explanation

    def test_missing_years_omits_year(self):
        row = {
            "root": "Nick Saban",
            "protege": "Kirby Smart",
            "team": "Alabama",
            "years": None,
        }
        explanation = _explain_coach_tree_row(row)
        assert "None" not in explanation

    def test_explanation_starts_with_included_because(self):
        row = {"root": "Saban", "team": "Alabama", "years": 2010}
        explanation = _explain_coach_tree_row(row)
        assert explanation.startswith("Included because:")

    def test_mentions_cfbd_coaching_overlap(self):
        row = {"root": "Saban", "team": "Alabama", "years": 2010}
        explanation = _explain_coach_tree_row(row)
        assert "CFBD" in explanation


# ---------------------------------------------------------------------------
# Unit tests — row builders
# ---------------------------------------------------------------------------


class TestRowsFromCoachingTree:
    """Tests for _rows_from_coaching_tree."""

    def test_returns_one_row_per_unique_coach(self):
        rows = _rows_from_coaching_tree(_TREE_ROWS, "Nick Saban")
        names = [r.display_name for r in rows]
        assert names == ["Kirby Smart", "Lane Kiffin", "Mark Stoops"]

    def test_deduplicates_by_name(self):
        duplicate_rows = _TREE_ROWS + [
            {
                "name": "Kirby Smart",
                "coach_code": 42,
                "depth": 2,
                "path_coaches": ["Saban", "Other", "Kirby Smart"],
            },
        ]
        rows = _rows_from_coaching_tree(duplicate_rows, "Nick Saban")
        assert sum(1 for r in rows if r.display_name == "Kirby Smart") == 1

    def test_coach_code_set_correctly(self):
        rows = _rows_from_coaching_tree(_TREE_ROWS, "Nick Saban")
        assert rows[0].coach_id == 42

    def test_depth_set_correctly(self):
        rows = _rows_from_coaching_tree(_TREE_ROWS, "Nick Saban")
        assert rows[0].depth == 1
        assert rows[2].depth == 2

    def test_empty_input_returns_empty(self):
        assert _rows_from_coaching_tree([], "Nick Saban") == []

    def test_row_with_missing_name_skipped(self):
        rows = [{"name": "", "coach_code": 1, "depth": 1, "path_coaches": []}]
        assert _rows_from_coaching_tree(rows, "Saban") == []


class TestRowsFromCoachTree:
    """Tests for _rows_from_coach_tree."""

    def test_returns_one_row_per_unique_protege(self):
        rows = _rows_from_coach_tree(_CFBD_ROWS)
        assert len(rows) == 2
        assert rows[0].display_name == "Kirby Smart"
        assert rows[1].display_name == "Lane Kiffin"

    def test_deduplicates_by_protege_name(self):
        duplicate = _CFBD_ROWS + [
            {
                "root": "Nick Saban",
                "protege": "Kirby Smart",
                "team": "Georgia",
                "years": 2016,
            },
        ]
        rows = _rows_from_coach_tree(duplicate)
        assert sum(1 for r in rows if r.display_name == "Kirby Smart") == 1

    def test_coach_id_is_none(self):
        rows = _rows_from_coach_tree(_CFBD_ROWS)
        assert all(r.coach_id is None for r in rows)

    def test_depth_is_1(self):
        rows = _rows_from_coach_tree(_CFBD_ROWS)
        assert all(r.depth == 1 for r in rows)

    def test_empty_protege_skipped(self):
        rows = [{"root": "Saban", "protege": None, "team": "Alabama", "years": 2015}]
        assert _rows_from_coach_tree(rows) == []


# ---------------------------------------------------------------------------
# Unit tests — _build_answer
# ---------------------------------------------------------------------------


class TestBuildAnswer:
    """Tests for _build_answer covering all intent branches."""

    def _make_rows(self, n: int, depth: int = 1) -> list[ResultRow]:
        return [
            ResultRow(
                coach_id=i, display_name=f"Coach {i}", depth=depth, explanation=""
            )
            for i in range(n)
        ]

    def test_tree_query_with_results(self):
        plan = _make_plan(intent="TREE_QUERY", coaches=["Nick Saban"])
        result = _make_result(plan)
        rows = self._make_rows(5)
        answer = _build_answer(plan, rows, False, result)
        assert "5 coaches" in answer
        assert "Nick Saban" in answer

    def test_tree_query_no_results(self):
        plan = _make_plan(intent="TREE_QUERY", coaches=["Nick Saban"])
        result = _make_result(plan)
        answer = _build_answer(plan, [], False, result)
        assert "No coaches" in answer
        assert "Nick Saban" in answer

    def test_tree_query_partial_note_added(self):
        plan = _make_plan(intent="TREE_QUERY", coaches=["Nick Saban"])
        result = _make_result(plan, errors=["sq1: error"])
        rows = self._make_rows(3)
        answer = _build_answer(plan, rows, True, result)
        assert "partial" in answer.lower()
        assert "1 sub-query error" in answer

    def test_tree_query_depth_range_in_answer(self):
        plan = _make_plan(intent="TREE_QUERY")
        result = _make_result(plan)
        rows = [
            ResultRow(0, "A", 1, ""),
            ResultRow(1, "B", 2, ""),
            ResultRow(2, "C", 3, ""),
        ]
        answer = _build_answer(plan, rows, False, result)
        assert "depth 1–3" in answer

    def test_performance_compare_with_results(self):
        plan = _make_plan(
            intent="PERFORMANCE_COMPARE", coaches=["Nick Saban", "Urban Meyer"]
        )
        result = _make_result(plan)
        rows = self._make_rows(4)
        answer = _build_answer(plan, rows, False, result)
        assert "4 coaching connections" in answer
        assert "Nick Saban" in answer

    def test_similarity_no_results(self):
        plan = _make_plan(intent="SIMILARITY", coaches=["Kirby Smart", "Lincoln Riley"])
        result = _make_result(plan)
        answer = _build_answer(plan, [], False, result)
        assert "No path found" in answer

    def test_generic_fallback_with_results(self):
        plan = _make_plan(intent="PIPELINE_QUERY")
        result = _make_result(plan)
        rows = self._make_rows(2)
        answer = _build_answer(plan, rows, False, result)
        assert "2 results" in answer


# ---------------------------------------------------------------------------
# synthesize_response — TREE_QUERY happy paths
# ---------------------------------------------------------------------------


class TestSynthesizeTreeQuery:
    """Happy-path synthesis for TREE_QUERY with GET_COACHING_TREE results."""

    def test_returns_synthesized_response_type(self):
        sq = _sq(
            "sq1",
            TraversalFn.GET_COACHING_TREE,
            params={"coach_name": "Nick Saban", "max_depth": 4},
        )
        plan = _make_plan(sub_queries=[sq])
        result = _make_result(plan, subquery_results={"sq1": _TREE_ROWS})
        si = SynthesisInput(plan=plan, execution_result=result)
        response = synthesize_response(si)
        assert isinstance(response, SynthesizedResponse)

    def test_answer_mentions_root_coach_and_count(self):
        sq = _sq(
            "sq1",
            TraversalFn.GET_COACHING_TREE,
            params={"coach_name": "Nick Saban", "max_depth": 4},
        )
        plan = _make_plan(sub_queries=[sq], coaches=["Nick Saban"])
        result = _make_result(plan, subquery_results={"sq1": _TREE_ROWS})
        response = synthesize_response(
            SynthesisInput(plan=plan, execution_result=result)
        )
        assert "Nick Saban" in response.answer
        assert "3 coaches" in response.answer

    def test_result_rows_count_matches_unique_mentees(self):
        sq = _sq("sq1", TraversalFn.GET_COACHING_TREE)
        plan = _make_plan(sub_queries=[sq])
        result = _make_result(plan, subquery_results={"sq1": _TREE_ROWS})
        response = synthesize_response(
            SynthesisInput(plan=plan, execution_result=result)
        )
        assert len(response.result_rows) == 3

    def test_per_row_explanation_format(self):
        sq = _sq("sq1", TraversalFn.GET_COACHING_TREE)
        plan = _make_plan(sub_queries=[sq])
        result = _make_result(plan, subquery_results={"sq1": _TREE_ROWS})
        response = synthesize_response(
            SynthesisInput(plan=plan, execution_result=result)
        )
        for row in response.result_rows:
            assert row.explanation.startswith("Included because:")

    def test_depth_1_row_says_direct_mentee(self):
        sq = _sq("sq1", TraversalFn.GET_COACHING_TREE)
        plan = _make_plan(sub_queries=[sq])
        result = _make_result(plan, subquery_results={"sq1": _TREE_ROWS})
        response = synthesize_response(
            SynthesisInput(plan=plan, execution_result=result)
        )
        depth_1_rows = [r for r in response.result_rows if r.depth == 1]
        for row in depth_1_rows:
            assert "direct mentee" in row.explanation

    def test_depth_2_row_says_depth_label(self):
        sq = _sq("sq1", TraversalFn.GET_COACHING_TREE)
        plan = _make_plan(sub_queries=[sq])
        result = _make_result(plan, subquery_results={"sq1": _TREE_ROWS})
        response = synthesize_response(
            SynthesisInput(plan=plan, execution_result=result)
        )
        depth_2_rows = [r for r in response.result_rows if r.depth == 2]
        assert len(depth_2_rows) >= 1
        assert "depth-2 mentee" in depth_2_rows[0].explanation

    def test_result_row_coach_id_set(self):
        sq = _sq("sq1", TraversalFn.GET_COACHING_TREE)
        plan = _make_plan(sub_queries=[sq])
        result = _make_result(plan, subquery_results={"sq1": _TREE_ROWS})
        response = synthesize_response(
            SynthesisInput(plan=plan, execution_result=result)
        )
        ids = {r.coach_id for r in response.result_rows}
        assert 42 in ids  # Kirby Smart's coach_code
        assert 17 in ids  # Lane Kiffin's coach_code

    def test_partial_is_false_when_no_errors(self):
        sq = _sq("sq1", TraversalFn.GET_COACHING_TREE)
        plan = _make_plan(sub_queries=[sq])
        result = _make_result(plan, subquery_results={"sq1": _TREE_ROWS})
        response = synthesize_response(
            SynthesisInput(plan=plan, execution_result=result)
        )
        assert response.partial is False

    def test_empty_tree_returns_no_rows_and_no_coaches_answer(self):
        sq = _sq("sq1", TraversalFn.GET_COACHING_TREE)
        plan = _make_plan(sub_queries=[sq], coaches=["Nick Saban"])
        result = _make_result(plan, subquery_results={"sq1": []})
        response = synthesize_response(
            SynthesisInput(plan=plan, execution_result=result)
        )
        assert response.result_rows == []
        assert "No coaches" in response.answer


# ---------------------------------------------------------------------------
# synthesize_response — GET_COACH_TREE (CFBD fallback) format
# ---------------------------------------------------------------------------


class TestSynthesizeFallbackCoachTree:
    """Synthesis for TREE_QUERY with GET_COACH_TREE (CFBD overlap) results."""

    def test_rows_produced_from_cfbd_result(self):
        sq = _sq("sq1", TraversalFn.GET_COACH_TREE)
        plan = _make_plan(sub_queries=[sq], coaches=["Nick Saban"])
        result = _make_result(plan, subquery_results={"sq1": _CFBD_ROWS})
        response = synthesize_response(
            SynthesisInput(plan=plan, execution_result=result)
        )
        assert len(response.result_rows) == 2

    def test_cfbd_row_explanation_mentions_overlap(self):
        sq = _sq("sq1", TraversalFn.GET_COACH_TREE)
        plan = _make_plan(sub_queries=[sq])
        result = _make_result(plan, subquery_results={"sq1": _CFBD_ROWS})
        response = synthesize_response(
            SynthesisInput(plan=plan, execution_result=result)
        )
        for row in response.result_rows:
            assert "CFBD" in row.explanation

    def test_cfbd_row_explanation_contains_team(self):
        sq = _sq("sq1", TraversalFn.GET_COACH_TREE)
        plan = _make_plan(sub_queries=[sq])
        result = _make_result(plan, subquery_results={"sq1": _CFBD_ROWS})
        response = synthesize_response(
            SynthesisInput(plan=plan, execution_result=result)
        )
        alabama_rows = [r for r in response.result_rows if "Alabama" in r.explanation]
        assert len(alabama_rows) == 2


# ---------------------------------------------------------------------------
# synthesize_response — partial results (some sub-queries failed)
# ---------------------------------------------------------------------------


class TestSynthesizePartialResults:
    """Graceful degradation when some sub-queries fail."""

    def test_partial_true_when_errors_present(self):
        sq1 = _sq("sq1", TraversalFn.GET_COACHING_TREE)
        sq2 = _sq(
            "sq2", TraversalFn.GET_COACH_TREE, params={"coach_name": "Urban Meyer"}
        )
        plan = _make_plan(sub_queries=[sq1, sq2])
        result = _make_result(
            plan,
            subquery_results={"sq2": _CFBD_ROWS},
            errors=["sq1 (GET_COACHING_TREE): entity resolution failed"],
            ready=False,
        )
        response = synthesize_response(
            SynthesisInput(plan=plan, execution_result=result)
        )
        assert response.partial is True

    def test_rows_from_successful_sq_still_returned(self):
        sq1 = _sq("sq1", TraversalFn.GET_COACHING_TREE)
        sq2 = _sq(
            "sq2", TraversalFn.GET_COACH_TREE, params={"coach_name": "Urban Meyer"}
        )
        plan = _make_plan(sub_queries=[sq1, sq2])
        result = _make_result(
            plan,
            subquery_results={"sq2": _CFBD_ROWS},
            errors=["sq1 (GET_COACHING_TREE): entity resolution failed"],
            ready=False,
        )
        response = synthesize_response(
            SynthesisInput(plan=plan, execution_result=result)
        )
        assert len(response.result_rows) == 2  # rows from sq2

    def test_partial_answer_mentions_error(self):
        sq = _sq("sq1", TraversalFn.GET_COACHING_TREE)
        plan = _make_plan(sub_queries=[sq])
        result = _make_result(
            plan,
            subquery_results={},
            errors=["sq1: timeout occurred"],
            ready=False,
        )
        response = synthesize_response(
            SynthesisInput(plan=plan, execution_result=result)
        )
        assert "partial" in response.answer.lower()

    def test_no_rows_when_all_sqs_failed(self):
        sq = _sq("sq1", TraversalFn.GET_COACHING_TREE)
        plan = _make_plan(sub_queries=[sq])
        result = _make_result(
            plan,
            subquery_results={},
            errors=["sq1: fatal error"],
            ready=False,
        )
        response = synthesize_response(
            SynthesisInput(plan=plan, execution_result=result)
        )
        assert response.result_rows == []
        assert response.partial is True


# ---------------------------------------------------------------------------
# synthesize_response — retry metadata surfaced in warnings
# ---------------------------------------------------------------------------


class TestSynthesizeRetryMetadata:
    """Retry outcome metadata appears in warnings."""

    def test_retry_metadata_in_warnings(self):
        sq = _sq("sq1", TraversalFn.GET_COACHING_TREE)
        plan = _make_plan(sub_queries=[sq])
        result = _make_result(plan, subquery_results={"sq1": _TREE_ROWS})

        retry_mock = MagicMock()
        retry_mock.retries_attempted = 1
        retry_mock.strategies_fired = ["fallback_traversal"]

        response = synthesize_response(
            SynthesisInput(plan=plan, execution_result=result, retry_outcome=retry_mock)
        )
        assert any("fallback_traversal" in w for w in response.warnings)
        assert any("1 attempt" in w for w in response.warnings)

    def test_no_retry_warning_when_zero_retries(self):
        sq = _sq("sq1", TraversalFn.GET_COACHING_TREE)
        plan = _make_plan(sub_queries=[sq])
        result = _make_result(plan, subquery_results={"sq1": _TREE_ROWS})

        retry_mock = MagicMock()
        retry_mock.retries_attempted = 0
        retry_mock.strategies_fired = []

        response = synthesize_response(
            SynthesisInput(plan=plan, execution_result=result, retry_outcome=retry_mock)
        )
        retry_warnings = [w for w in response.warnings if "Retry:" in w]
        assert retry_warnings == []

    def test_no_retry_warning_when_retry_outcome_is_none(self):
        sq = _sq("sq1", TraversalFn.GET_COACHING_TREE)
        plan = _make_plan(sub_queries=[sq])
        result = _make_result(plan, subquery_results={"sq1": _TREE_ROWS})
        response = synthesize_response(
            SynthesisInput(plan=plan, execution_result=result)
        )
        retry_warnings = [w for w in response.warnings if "Retry:" in w]
        assert retry_warnings == []


# ---------------------------------------------------------------------------
# synthesize_response — PERFORMANCE_COMPARE (COMBINE sub-query)
# ---------------------------------------------------------------------------


class TestSynthesizePerformanceCompare:
    """Synthesis for PERFORMANCE_COMPARE with COMBINE sub-query."""

    def test_rows_pulled_from_combine_sources(self):
        sq_a = _sq(
            "sq_a", TraversalFn.GET_COACH_TREE, params={"coach_name": "Nick Saban"}
        )
        sq_b = _sq(
            "sq_b", TraversalFn.GET_COACH_TREE, params={"coach_name": "Urban Meyer"}
        )
        sq_c = _sq(
            "sq_c",
            TraversalFn.COMBINE,
            params={"strategy": "compare"},
            depends_on=["sq_a", "sq_b"],
        )
        plan = _make_plan(
            intent="PERFORMANCE_COMPARE",
            coaches=["Nick Saban", "Urban Meyer"],
            sub_queries=[sq_a, sq_b, sq_c],
        )
        saban_rows = [
            {
                "root": "Nick Saban",
                "protege": "Kirby Smart",
                "team": "Alabama",
                "years": 2015,
            }
        ]
        meyer_rows = [
            {
                "root": "Urban Meyer",
                "protege": "Ryan Day",
                "team": "Ohio State",
                "years": 2019,
            }
        ]
        combine_result = {
            "strategy": "compare",
            "sources": {"sq_a": saban_rows, "sq_b": meyer_rows},
        }
        result = _make_result(
            plan,
            subquery_results={
                "sq_a": saban_rows,
                "sq_b": meyer_rows,
                "sq_c": combine_result,
            },
        )
        response = synthesize_response(
            SynthesisInput(plan=plan, execution_result=result)
        )
        names = {r.display_name for r in response.result_rows}
        # sq_a and sq_b are processed directly; sq_c (COMBINE) also pulls the same rows.
        assert "Kirby Smart" in names
        assert "Ryan Day" in names

    def test_answer_mentions_both_coaches(self):
        sq_a = _sq(
            "sq_a", TraversalFn.GET_COACH_TREE, params={"coach_name": "Nick Saban"}
        )
        sq_b = _sq(
            "sq_b", TraversalFn.GET_COACH_TREE, params={"coach_name": "Urban Meyer"}
        )
        sq_c = _sq(
            "sq_c",
            TraversalFn.COMBINE,
            params={"strategy": "compare"},
            depends_on=["sq_a", "sq_b"],
        )
        plan = _make_plan(
            intent="PERFORMANCE_COMPARE",
            coaches=["Nick Saban", "Urban Meyer"],
            sub_queries=[sq_a, sq_b, sq_c],
        )
        saban_rows = [
            {
                "root": "Nick Saban",
                "protege": "Kirby Smart",
                "team": "Alabama",
                "years": 2015,
            }
        ]
        meyer_rows = [
            {
                "root": "Urban Meyer",
                "protege": "Ryan Day",
                "team": "Ohio State",
                "years": 2019,
            }
        ]
        combine_result = {
            "strategy": "compare",
            "sources": {"sq_a": saban_rows, "sq_b": meyer_rows},
        }
        result = _make_result(
            plan,
            subquery_results={
                "sq_a": saban_rows,
                "sq_b": meyer_rows,
                "sq_c": combine_result,
            },
        )
        response = synthesize_response(
            SynthesisInput(plan=plan, execution_result=result)
        )
        assert "Nick Saban" in response.answer
        assert "Urban Meyer" in response.answer


# ---------------------------------------------------------------------------
# synthesize_response — SIMILARITY (shortest path)
# ---------------------------------------------------------------------------


class TestSynthesizeSimilarity:
    """Synthesis for SIMILARITY with SHORTEST_PATH_BETWEEN_COACHES results."""

    def test_path_row_produced(self):
        sq = _sq(
            "sq1",
            TraversalFn.SHORTEST_PATH_BETWEEN_COACHES,
            params={"coach_a": "Kirby Smart", "coach_b": "Lincoln Riley"},
        )
        plan = _make_plan(
            intent="SIMILARITY",
            coaches=["Kirby Smart", "Lincoln Riley"],
            sub_queries=[sq],
        )
        path_result = [
            {
                "path_nodes": [
                    "Kirby Smart",
                    "Alabama",
                    "Nick Saban",
                    "USC",
                    "Lincoln Riley",
                ],
                "hops": 4,
            }
        ]
        result = _make_result(plan, subquery_results={"sq1": path_result})
        response = synthesize_response(
            SynthesisInput(plan=plan, execution_result=result)
        )
        assert len(response.result_rows) == 1
        assert "4 hops" in response.result_rows[0].explanation

    def test_answer_mentions_both_coaches(self):
        sq = _sq("sq1", TraversalFn.SHORTEST_PATH_BETWEEN_COACHES)
        plan = _make_plan(
            intent="SIMILARITY",
            coaches=["Kirby Smart", "Lincoln Riley"],
            sub_queries=[sq],
        )
        result = _make_result(
            plan,
            subquery_results={"sq1": [{"path_nodes": ["A", "B"], "hops": 1}]},
        )
        response = synthesize_response(
            SynthesisInput(plan=plan, execution_result=result)
        )
        assert "Kirby Smart" in response.answer
        assert "Lincoln Riley" in response.answer
