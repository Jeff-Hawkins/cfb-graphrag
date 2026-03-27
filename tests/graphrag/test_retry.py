"""Tests for graphrag/retry.py."""

from unittest.mock import MagicMock

from graphrag.executor import ExecutionResult
from graphrag.planner import EntityBundle, SubQuery, SubQueryPlan, TraversalFn
from graphrag.retry import (
    FallbackTraversalStrategy,
    LimitRoleFilterStrategy,
    ReduceDepthStrategy,
    RetryOutcome,
    RetryStrategy,
    _has_nonempty_results,
    execute_with_retry,
)

# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_plan(
    *,
    ready: bool = True,
    sub_queries: list[SubQuery] | None = None,
    coaches: list[str] | None = None,
    intent: str = "TREE_QUERY",
    warnings: list[str] | None = None,
) -> SubQueryPlan:
    """Build a minimal :class:`SubQueryPlan`.

    ``coaches=None`` defaults to ``["Nick Saban"]``; pass ``coaches=[]``
    to explicitly produce a plan with no coach entities.
    """
    coach_list = ["Nick Saban"] if coaches is None else coaches
    return SubQueryPlan(
        intent=intent,
        confidence=0.9,
        question="test question",
        entities=EntityBundle(coaches=coach_list),
        sub_queries=sub_queries or [],
        ready=ready,
        warnings=warnings or [],
    )


def _sq(
    sq_id: str,
    traversal_fn: str,
    params: dict | None = None,
    depends_on: list[str] | None = None,
) -> SubQuery:
    """Build a minimal :class:`SubQuery`."""
    return SubQuery(
        id=sq_id,
        traversal_fn=traversal_fn,
        params=params or {},
        depends_on=depends_on or [],
        description=f"test {sq_id}",
    )


def _make_result(
    plan: SubQueryPlan,
    *,
    subquery_results: dict | None = None,
    errors: list[str] | None = None,
    warnings: list[str] | None = None,
    ready: bool = True,
) -> ExecutionResult:
    """Build a minimal :class:`ExecutionResult`."""
    return ExecutionResult(
        plan=plan,
        subquery_results=subquery_results or {},
        errors=errors or [],
        warnings=warnings or [],
        ready_for_synthesis=ready,
    )


# ---------------------------------------------------------------------------
# RetryStrategy protocol compliance
# ---------------------------------------------------------------------------


class TestRetryStrategyProtocol:
    """Both concrete strategies satisfy the RetryStrategy protocol."""

    def test_reduce_depth_is_retry_strategy(self):
        assert isinstance(ReduceDepthStrategy(), RetryStrategy)

    def test_fallback_traversal_is_retry_strategy(self):
        assert isinstance(FallbackTraversalStrategy(), RetryStrategy)


# ---------------------------------------------------------------------------
# ReduceDepthStrategy
# ---------------------------------------------------------------------------


class TestReduceDepthStrategy:
    """Unit tests for ReduceDepthStrategy."""

    strategy = ReduceDepthStrategy()

    # --- should_apply ---

    def test_should_apply_on_timeout_error(self):
        """Timeout error + GET_COACHING_TREE with max_depth > 1 → True."""
        sq = _sq(
            "sq1",
            TraversalFn.GET_COACHING_TREE,
            params={"coach_name": "Saban", "max_depth": 4},
        )
        plan = _make_plan(sub_queries=[sq])
        result = _make_result(
            plan, errors=["sq1 (GET_COACHING_TREE): query timeout exceeded"]
        )
        assert self.strategy.should_apply(plan, result) is True

    def test_should_apply_on_too_large_error(self):
        """'too large' signal also triggers the strategy."""
        sq = _sq("sq1", TraversalFn.GET_COACHING_TREE, params={"max_depth": 3})
        plan = _make_plan(sub_queries=[sq])
        result = _make_result(plan, errors=["sq1: result too large to return"])
        assert self.strategy.should_apply(plan, result) is True

    def test_should_not_apply_when_no_error_signal(self):
        """A generic error without over-scope signals → False."""
        sq = _sq("sq1", TraversalFn.GET_COACHING_TREE, params={"max_depth": 4})
        plan = _make_plan(sub_queries=[sq])
        result = _make_result(
            plan, errors=["sq1 (GET_COACHING_TREE): entity not found"]
        )
        assert self.strategy.should_apply(plan, result) is False

    def test_should_not_apply_when_depth_already_1(self):
        """max_depth=1 means there is nothing to reduce — False."""
        sq = _sq("sq1", TraversalFn.GET_COACHING_TREE, params={"max_depth": 1})
        plan = _make_plan(sub_queries=[sq])
        result = _make_result(plan, errors=["sq1: too many results timeout"])
        assert self.strategy.should_apply(plan, result) is False

    def test_should_not_apply_when_no_coaching_tree_sub_query(self):
        """No GET_COACHING_TREE sub-queries in the plan → False."""
        sq = _sq("sq1", TraversalFn.GET_COACH_TREE, params={"coach_name": "Saban"})
        plan = _make_plan(sub_queries=[sq])
        result = _make_result(plan, errors=["sq1: timeout occurred"])
        assert self.strategy.should_apply(plan, result) is False

    # --- apply ---

    def test_apply_reduces_depth_by_one(self):
        """max_depth=4 → 3 in the returned plan."""
        sq = _sq(
            "sq1",
            TraversalFn.GET_COACHING_TREE,
            params={"coach_name": "Saban", "max_depth": 4},
        )
        plan = _make_plan(sub_queries=[sq])
        new_plan = self.strategy.apply(plan)
        assert new_plan is not None
        new_sq = new_plan.sub_queries[0]
        assert new_sq.params["max_depth"] == 3

    def test_apply_preserves_other_params(self):
        """role_filter and coach_name survive the depth reduction."""
        sq = _sq(
            "sq1",
            TraversalFn.GET_COACHING_TREE,
            params={"coach_name": "Nick Saban", "max_depth": 3, "role_filter": "HC"},
        )
        plan = _make_plan(sub_queries=[sq])
        new_plan = self.strategy.apply(plan)
        assert new_plan is not None
        new_sq = new_plan.sub_queries[0]
        assert new_sq.params["role_filter"] == "HC"
        assert new_sq.params["coach_name"] == "Nick Saban"
        assert new_sq.params["max_depth"] == 2

    def test_apply_returns_none_when_depth_at_minimum(self):
        """All GET_COACHING_TREE sub-queries already at max_depth=1 → None."""
        sq = _sq("sq1", TraversalFn.GET_COACHING_TREE, params={"max_depth": 1})
        plan = _make_plan(sub_queries=[sq])
        assert self.strategy.apply(plan) is None

    def test_apply_does_not_modify_non_coaching_tree_sqs(self):
        """GET_COACH_TREE sub-queries are passed through unchanged."""
        sq_tree = _sq("sq1", TraversalFn.GET_COACHING_TREE, params={"max_depth": 4})
        sq_other = _sq(
            "sq2", TraversalFn.GET_COACH_TREE, params={"coach_name": "Meyer"}
        )
        plan = _make_plan(sub_queries=[sq_tree, sq_other])
        new_plan = self.strategy.apply(plan)
        assert new_plan is not None
        assert new_plan.sub_queries[1].traversal_fn == TraversalFn.GET_COACH_TREE
        assert new_plan.sub_queries[1].params == {"coach_name": "Meyer"}

    def test_apply_adds_warning(self):
        """Returned plan has a warning string indicating the reduction."""
        sq = _sq("sq1", TraversalFn.GET_COACHING_TREE, params={"max_depth": 2})
        plan = _make_plan(sub_queries=[sq])
        new_plan = self.strategy.apply(plan)
        assert new_plan is not None
        assert any("reduce_depth" in w for w in new_plan.warnings)


# ---------------------------------------------------------------------------
# FallbackTraversalStrategy
# ---------------------------------------------------------------------------


class TestFallbackTraversalStrategy:
    """Unit tests for FallbackTraversalStrategy."""

    strategy = FallbackTraversalStrategy()

    # --- should_apply ---

    def test_should_apply_on_empty_tree_result(self):
        """GET_COACHING_TREE returned [] + valid coach entity → True."""
        sq = _sq("sq1", TraversalFn.GET_COACHING_TREE, params={"coach_name": "Saban"})
        plan = _make_plan(sub_queries=[sq])
        result = _make_result(plan, subquery_results={"sq1": []}, ready=True)
        assert self.strategy.should_apply(plan, result) is True

    def test_should_apply_on_errored_tree_sub_query(self):
        """GET_COACHING_TREE sub-query in errors (entity resolution fail) → True."""
        sq = _sq("sq1", TraversalFn.GET_COACHING_TREE, params={"coach_name": "Saban"})
        plan = _make_plan(sub_queries=[sq])
        result = _make_result(
            plan,
            errors=["sq1 (GET_COACHING_TREE): entity resolution failed"],
            ready=False,
        )
        assert self.strategy.should_apply(plan, result) is True

    def test_should_not_apply_without_coach_entities(self):
        """No coaches in entities → False (fallback has no name to use)."""
        sq = _sq("sq1", TraversalFn.GET_COACHING_TREE, params={"coach_name": ""})
        plan = _make_plan(sub_queries=[sq], coaches=[])
        result = _make_result(plan, subquery_results={"sq1": []})
        assert self.strategy.should_apply(plan, result) is False

    def test_should_not_apply_when_no_coaching_tree_sqs(self):
        """Plan only has GET_COACH_TREE sub-queries → False."""
        sq = _sq("sq1", TraversalFn.GET_COACH_TREE, params={"coach_name": "Saban"})
        plan = _make_plan(sub_queries=[sq])
        result = _make_result(plan, subquery_results={"sq1": []})
        assert self.strategy.should_apply(plan, result) is False

    def test_should_not_apply_when_tree_has_results(self):
        """Non-empty GET_COACHING_TREE result and no errors → False."""
        sq = _sq("sq1", TraversalFn.GET_COACHING_TREE, params={"coach_name": "Saban"})
        plan = _make_plan(sub_queries=[sq])
        result = _make_result(
            plan,
            subquery_results={
                "sq1": [
                    {
                        "name": "Kirby Smart",
                        "coach_code": 42,
                        "depth": 1,
                        "path_coaches": [],
                    }
                ]
            },
        )
        assert self.strategy.should_apply(plan, result) is False

    # --- apply ---

    def test_apply_swaps_traversal_fn(self):
        """GET_COACHING_TREE sub-query becomes GET_COACH_TREE."""
        sq = _sq(
            "sq1",
            TraversalFn.GET_COACHING_TREE,
            params={"coach_name": "Nick Saban", "max_depth": 4},
        )
        plan = _make_plan(sub_queries=[sq])
        new_plan = self.strategy.apply(plan)
        assert new_plan is not None
        new_sq = new_plan.sub_queries[0]
        assert new_sq.traversal_fn == TraversalFn.GET_COACH_TREE
        assert new_sq.params == {"coach_name": "Nick Saban"}

    def test_apply_preserves_sub_query_id(self):
        """Sub-query ID is unchanged after swap."""
        sq = _sq(
            "sq_saban",
            TraversalFn.GET_COACHING_TREE,
            params={"coach_name": "Nick Saban"},
        )
        plan = _make_plan(sub_queries=[sq])
        new_plan = self.strategy.apply(plan)
        assert new_plan is not None
        assert new_plan.sub_queries[0].id == "sq_saban"

    def test_apply_returns_none_when_no_get_coaching_tree(self):
        """Only GET_COACH_TREE sub-queries present → None."""
        sq = _sq("sq1", TraversalFn.GET_COACH_TREE, params={"coach_name": "Saban"})
        plan = _make_plan(sub_queries=[sq])
        assert self.strategy.apply(plan) is None

    def test_apply_passes_through_non_coaching_tree_sqs(self):
        """SHORTEST_PATH sub-queries are not modified."""
        sq1 = _sq("sq1", TraversalFn.GET_COACHING_TREE, params={"coach_name": "Saban"})
        sq2 = _sq(
            "sq2",
            TraversalFn.SHORTEST_PATH_BETWEEN_COACHES,
            params={"coach_a": "A", "coach_b": "B"},
        )
        plan = _make_plan(sub_queries=[sq1, sq2])
        new_plan = self.strategy.apply(plan)
        assert new_plan is not None
        assert (
            new_plan.sub_queries[1].traversal_fn
            == TraversalFn.SHORTEST_PATH_BETWEEN_COACHES
        )

    def test_apply_adds_warning(self):
        """Returned plan has a warning mentioning the fallback."""
        sq = _sq("sq1", TraversalFn.GET_COACHING_TREE, params={"coach_name": "Saban"})
        plan = _make_plan(sub_queries=[sq])
        new_plan = self.strategy.apply(plan)
        assert new_plan is not None
        assert any("fallback_traversal" in w for w in new_plan.warnings)


# ---------------------------------------------------------------------------
# LimitRoleFilterStrategy
# ---------------------------------------------------------------------------


class TestLimitRoleFilterStrategy:
    """Unit tests for LimitRoleFilterStrategy."""

    strategy = LimitRoleFilterStrategy()

    # --- protocol compliance ---

    def test_is_retry_strategy(self):
        assert isinstance(LimitRoleFilterStrategy(), RetryStrategy)

    # --- should_apply ---

    def test_should_apply_when_role_filter_and_empty_result(self):
        """role_filter present + empty result list → True."""
        sq = _sq(
            "sq1",
            TraversalFn.GET_COACHING_TREE,
            params={"coach_name": "Saban", "max_depth": 4, "role_filter": "HC"},
        )
        plan = _make_plan(sub_queries=[sq])
        result = _make_result(plan, subquery_results={"sq1": []})
        assert self.strategy.should_apply(plan, result) is True

    def test_should_not_apply_when_no_role_filter(self):
        """GET_COACHING_TREE without role_filter → False."""
        sq = _sq(
            "sq1",
            TraversalFn.GET_COACHING_TREE,
            params={"coach_name": "Saban", "max_depth": 4},
        )
        plan = _make_plan(sub_queries=[sq])
        result = _make_result(plan, subquery_results={"sq1": []})
        assert self.strategy.should_apply(plan, result) is False

    def test_should_not_apply_when_role_filter_none(self):
        """role_filter=None is treated as absent → False."""
        sq = _sq(
            "sq1",
            TraversalFn.GET_COACHING_TREE,
            params={"coach_name": "Saban", "max_depth": 4, "role_filter": None},
        )
        plan = _make_plan(sub_queries=[sq])
        result = _make_result(plan, subquery_results={"sq1": []})
        assert self.strategy.should_apply(plan, result) is False

    def test_should_not_apply_when_results_nonempty(self):
        """role_filter present but results non-empty → False (conservative)."""
        sq = _sq(
            "sq1",
            TraversalFn.GET_COACHING_TREE,
            params={"coach_name": "Saban", "role_filter": "HC"},
        )
        plan = _make_plan(sub_queries=[sq])
        result = _make_result(
            plan,
            subquery_results={
                "sq1": [
                    {
                        "name": "Kirby Smart",
                        "coach_code": 42,
                        "depth": 1,
                        "path_coaches": [],
                    }
                ]
            },
        )
        assert self.strategy.should_apply(plan, result) is False

    def test_should_not_apply_when_result_missing_not_empty_list(self):
        """Sub-query not in subquery_results at all (error path) → False."""
        sq = _sq(
            "sq1",
            TraversalFn.GET_COACHING_TREE,
            params={"coach_name": "Saban", "role_filter": "HC"},
        )
        plan = _make_plan(sub_queries=[sq])
        result = _make_result(
            plan,
            subquery_results={},  # sq1 missing — FallbackTraversal covers this
            errors=["sq1: entity resolution failed"],
            ready=False,
        )
        assert self.strategy.should_apply(plan, result) is False

    def test_should_not_apply_when_wrong_traversal_fn(self):
        """GET_COACH_TREE sub-query with role_filter → False."""
        sq = _sq(
            "sq1",
            TraversalFn.GET_COACH_TREE,
            params={"coach_name": "Saban", "role_filter": "HC"},
        )
        plan = _make_plan(sub_queries=[sq])
        result = _make_result(plan, subquery_results={"sq1": []})
        assert self.strategy.should_apply(plan, result) is False

    # --- apply ---

    def test_apply_removes_role_filter_from_params(self):
        """role_filter key is absent in the returned plan's sub-query."""
        sq = _sq(
            "sq1",
            TraversalFn.GET_COACHING_TREE,
            params={"coach_name": "Nick Saban", "max_depth": 4, "role_filter": "HC"},
        )
        plan = _make_plan(sub_queries=[sq])
        new_plan = self.strategy.apply(plan)
        assert new_plan is not None
        assert "role_filter" not in new_plan.sub_queries[0].params

    def test_apply_preserves_other_params(self):
        """coach_name and max_depth survive the role_filter removal."""
        sq = _sq(
            "sq1",
            TraversalFn.GET_COACHING_TREE,
            params={"coach_name": "Nick Saban", "max_depth": 3, "role_filter": "HC"},
        )
        plan = _make_plan(sub_queries=[sq])
        new_plan = self.strategy.apply(plan)
        assert new_plan is not None
        assert new_plan.sub_queries[0].params["coach_name"] == "Nick Saban"
        assert new_plan.sub_queries[0].params["max_depth"] == 3

    def test_apply_preserves_sub_query_id(self):
        sq = _sq(
            "sq_tree",
            TraversalFn.GET_COACHING_TREE,
            params={"coach_name": "Saban", "role_filter": "HC"},
        )
        plan = _make_plan(sub_queries=[sq])
        new_plan = self.strategy.apply(plan)
        assert new_plan is not None
        assert new_plan.sub_queries[0].id == "sq_tree"

    def test_apply_preserves_traversal_fn(self):
        """Strategy keeps GET_COACHING_TREE — does not swap to fallback."""
        sq = _sq(
            "sq1",
            TraversalFn.GET_COACHING_TREE,
            params={"coach_name": "Saban", "role_filter": "HC"},
        )
        plan = _make_plan(sub_queries=[sq])
        new_plan = self.strategy.apply(plan)
        assert new_plan is not None
        assert new_plan.sub_queries[0].traversal_fn == TraversalFn.GET_COACHING_TREE

    def test_apply_adds_warning(self):
        """Returned plan includes a warning mentioning the strategy name."""
        sq = _sq(
            "sq1",
            TraversalFn.GET_COACHING_TREE,
            params={"coach_name": "Saban", "role_filter": "HC"},
        )
        plan = _make_plan(sub_queries=[sq])
        new_plan = self.strategy.apply(plan)
        assert new_plan is not None
        assert any("limit_role_filter" in w for w in new_plan.warnings)

    def test_apply_returns_none_when_no_role_filter_present(self):
        """Sub-query without role_filter → nothing to modify → None."""
        sq = _sq(
            "sq1",
            TraversalFn.GET_COACHING_TREE,
            params={"coach_name": "Saban", "max_depth": 4},
        )
        plan = _make_plan(sub_queries=[sq])
        assert self.strategy.apply(plan) is None

    def test_apply_does_not_modify_non_coaching_tree_sqs(self):
        """GET_COACH_TREE sub-queries pass through unchanged."""
        sq1 = _sq(
            "sq1",
            TraversalFn.GET_COACHING_TREE,
            params={"coach_name": "Saban", "role_filter": "HC"},
        )
        sq2 = _sq("sq2", TraversalFn.GET_COACH_TREE, params={"coach_name": "Meyer"})
        plan = _make_plan(sub_queries=[sq1, sq2])
        new_plan = self.strategy.apply(plan)
        assert new_plan is not None
        assert new_plan.sub_queries[1].traversal_fn == TraversalFn.GET_COACH_TREE
        assert new_plan.sub_queries[1].params == {"coach_name": "Meyer"}


# ---------------------------------------------------------------------------
# _has_nonempty_results helper
# ---------------------------------------------------------------------------


class TestHasNonemptyResults:
    def test_empty_subquery_results_is_empty(self):
        plan = _make_plan()
        result = _make_result(plan, subquery_results={})
        assert _has_nonempty_results(result) is False

    def test_empty_list_value_is_empty(self):
        plan = _make_plan()
        result = _make_result(plan, subquery_results={"sq1": []})
        assert _has_nonempty_results(result) is False

    def test_nonempty_list_is_not_empty(self):
        plan = _make_plan()
        result = _make_result(plan, subquery_results={"sq1": [{"name": "Kirby Smart"}]})
        assert _has_nonempty_results(result) is True

    def test_nonempty_dict_is_not_empty(self):
        plan = _make_plan()
        result = _make_result(
            plan, subquery_results={"sq1": {"strategy": "compare", "sources": {}}}
        )
        assert _has_nonempty_results(result) is True

    def test_none_value_is_empty(self):
        plan = _make_plan()
        result = _make_result(plan, subquery_results={"sq1": None})
        assert _has_nonempty_results(result) is False


# ---------------------------------------------------------------------------
# execute_with_retry — integration-style tests using monkeypatch
# ---------------------------------------------------------------------------


class TestExecuteWithRetry:
    """Tests for execute_with_retry() that monkeypatch execute_plan."""

    def _tree_result(self, plan: SubQueryPlan, rows: list) -> ExecutionResult:
        return ExecutionResult(
            plan=plan,
            subquery_results={"sq1": rows},
            errors=[],
            warnings=[],
            ready_for_synthesis=True,
        )

    def _error_result(self, plan: SubQueryPlan, error: str) -> ExecutionResult:
        return ExecutionResult(
            plan=plan,
            subquery_results={},
            errors=[error],
            warnings=[],
            ready_for_synthesis=False,
        )

    def test_no_retry_when_success_and_nonempty(self, monkeypatch):
        """First execute returns ready + non-empty → 0 retries, no strategy fires."""
        sq = _sq(
            "sq1",
            TraversalFn.GET_COACHING_TREE,
            params={"coach_name": "Nick Saban", "max_depth": 4},
        )
        plan = _make_plan(sub_queries=[sq])
        rows = [
            {
                "name": "Kirby Smart",
                "coach_code": 42,
                "depth": 1,
                "path_coaches": ["Saban"],
            }
        ]

        mock_execute = MagicMock(return_value=self._tree_result(plan, rows))
        monkeypatch.setattr("graphrag.retry.execute_plan", mock_execute)

        outcome = execute_with_retry(plan, driver=MagicMock())

        assert mock_execute.call_count == 1
        assert outcome.retries_attempted == 0
        assert outcome.strategies_fired == []

    def test_single_retry_empty_results_triggers_fallback(self, monkeypatch):
        """GET_COACHING_TREE returns [] → FallbackTraversalStrategy fires once."""
        sq = _sq(
            "sq1",
            TraversalFn.GET_COACHING_TREE,
            params={"coach_name": "Nick Saban", "max_depth": 4},
        )
        plan = _make_plan(sub_queries=[sq])

        empty_result = self._tree_result(plan, [])
        # After fallback, return a nonempty result.
        cfbd_rows = [
            {
                "root": "Nick Saban",
                "protege": "Kirby Smart",
                "team": "Alabama",
                "years": 2015,
            }
        ]

        mock_execute = MagicMock(
            side_effect=[
                empty_result,
                ExecutionResult(
                    plan=plan,
                    subquery_results={"sq1": cfbd_rows},
                    errors=[],
                    warnings=[],
                    ready_for_synthesis=True,
                ),
            ]
        )
        monkeypatch.setattr("graphrag.retry.execute_plan", mock_execute)

        outcome = execute_with_retry(plan, driver=MagicMock())

        assert mock_execute.call_count == 2
        assert outcome.retries_attempted == 1
        assert outcome.strategies_fired == ["fallback_traversal"]
        # Verify the second call used GET_COACH_TREE.
        second_call_plan: SubQueryPlan = mock_execute.call_args_list[1][0][0]
        assert (
            second_call_plan.sub_queries[0].traversal_fn == TraversalFn.GET_COACH_TREE
        )

    def test_bounded_retries_max_retries_1(self, monkeypatch):
        """max_retries=1 stops after one retry even if result is still bad."""
        sq = _sq(
            "sq1",
            TraversalFn.GET_COACHING_TREE,
            params={"coach_name": "Nick Saban", "max_depth": 4},
        )
        plan = _make_plan(sub_queries=[sq])

        empty_result = self._tree_result(plan, [])
        still_empty = self._tree_result(plan, [])

        mock_execute = MagicMock(side_effect=[empty_result, still_empty])
        monkeypatch.setattr("graphrag.retry.execute_plan", mock_execute)

        outcome = execute_with_retry(plan, driver=MagicMock(), max_retries=1)

        assert mock_execute.call_count == 2  # original + 1 retry
        assert outcome.retries_attempted == 1

    def test_no_retry_when_no_applicable_strategy(self, monkeypatch):
        """Error without matching signals and no empty tree results → 0 retries."""
        sq = _sq("sq1", TraversalFn.GET_COACH_TREE, params={"coach_name": "Nick Saban"})
        plan = _make_plan(sub_queries=[sq])
        # Generic error — neither strategy applies.
        bad_result = self._error_result(plan, "sq1 (GET_COACH_TREE): entity not found")

        mock_execute = MagicMock(return_value=bad_result)
        monkeypatch.setattr("graphrag.retry.execute_plan", mock_execute)

        outcome = execute_with_retry(plan, driver=MagicMock())

        assert mock_execute.call_count == 1
        assert outcome.retries_attempted == 0
        assert outcome.strategies_fired == []

    def test_reduce_depth_fires_on_timeout_error(self, monkeypatch):
        """Timeout error on GET_COACHING_TREE → ReduceDepthStrategy fires."""
        sq = _sq(
            "sq1",
            TraversalFn.GET_COACHING_TREE,
            params={"coach_name": "Saban", "max_depth": 4},
        )
        plan = _make_plan(sub_queries=[sq])

        timeout_result = self._error_result(
            plan, "sq1 (GET_COACHING_TREE): query timeout exceeded"
        )
        rows = [
            {
                "name": "Kirby Smart",
                "coach_code": 42,
                "depth": 1,
                "path_coaches": ["Saban"],
            }
        ]
        success_result = ExecutionResult(
            plan=plan,
            subquery_results={"sq1": rows},
            errors=[],
            warnings=[],
            ready_for_synthesis=True,
        )

        mock_execute = MagicMock(side_effect=[timeout_result, success_result])
        monkeypatch.setattr("graphrag.retry.execute_plan", mock_execute)

        outcome = execute_with_retry(plan, driver=MagicMock())

        assert outcome.retries_attempted == 1
        assert outcome.strategies_fired == ["reduce_depth"]
        retried_plan: SubQueryPlan = mock_execute.call_args_list[1][0][0]
        assert retried_plan.sub_queries[0].params["max_depth"] == 3

    def test_retry_outcome_metadata_accurate(self, monkeypatch):
        """RetryOutcome.strategies_fired reflects what actually ran."""
        sq = _sq(
            "sq1",
            TraversalFn.GET_COACHING_TREE,
            params={"coach_name": "Saban", "max_depth": 4},
        )
        plan = _make_plan(sub_queries=[sq])

        mock_execute = MagicMock(
            side_effect=[
                self._tree_result(plan, []),  # original: empty
                self._tree_result(
                    plan, []
                ),  # retry 1: still empty (no more strategies)
            ]
        )
        monkeypatch.setattr("graphrag.retry.execute_plan", mock_execute)

        outcome = execute_with_retry(plan, driver=MagicMock(), max_retries=2)

        # FallbackTraversalStrategy fires once; after that plan has GET_COACH_TREE
        # so no more strategies apply → 1 retry total.
        assert outcome.retries_attempted == 1
        assert "fallback_traversal" in outcome.strategies_fired

    def test_role_filter_relaxed_on_empty_result(self, monkeypatch):
        """LimitRoleFilterStrategy fires when role_filter gives empty result,
        then second attempt (without role_filter) returns non-empty rows."""
        sq = _sq(
            "sq1",
            TraversalFn.GET_COACHING_TREE,
            params={"coach_name": "Nick Saban", "max_depth": 4, "role_filter": "HC"},
        )
        plan = _make_plan(sub_queries=[sq])

        empty_result = self._tree_result(plan, [])
        rows = [
            {
                "name": "Kirby Smart",
                "coach_code": 42,
                "depth": 1,
                "path_coaches": ["Nick Saban", "Kirby Smart"],
            }
        ]
        success_result = ExecutionResult(
            plan=plan,
            subquery_results={"sq1": rows},
            errors=[],
            warnings=[],
            ready_for_synthesis=True,
        )

        mock_execute = MagicMock(side_effect=[empty_result, success_result])
        monkeypatch.setattr("graphrag.retry.execute_plan", mock_execute)

        outcome = execute_with_retry(plan, driver=MagicMock())

        assert mock_execute.call_count == 2
        assert outcome.retries_attempted == 1
        assert "limit_role_filter" in outcome.strategies_fired
        # Verify the retried plan has no role_filter
        retried_plan: SubQueryPlan = mock_execute.call_args_list[1][0][0]
        assert "role_filter" not in retried_plan.sub_queries[0].params

    def test_role_filter_strategy_not_fallback_on_nonempty(self, monkeypatch):
        """When role_filter produces non-empty results, no retry fires."""
        sq = _sq(
            "sq1",
            TraversalFn.GET_COACHING_TREE,
            params={"coach_name": "Nick Saban", "max_depth": 4, "role_filter": "HC"},
        )
        plan = _make_plan(sub_queries=[sq])
        rows = [
            {
                "name": "Kirby Smart",
                "coach_code": 42,
                "depth": 1,
                "path_coaches": ["Nick Saban", "Kirby Smart"],
            }
        ]
        success_result = self._tree_result(plan, rows)

        mock_execute = MagicMock(return_value=success_result)
        monkeypatch.setattr("graphrag.retry.execute_plan", mock_execute)

        outcome = execute_with_retry(plan, driver=MagicMock())

        assert mock_execute.call_count == 1
        assert outcome.retries_attempted == 0
        assert outcome.strategies_fired == []

    def test_limit_role_filter_precedes_fallback_traversal(self, monkeypatch):
        """With role_filter present and empty results, LimitRoleFilterStrategy
        fires before FallbackTraversalStrategy in the default ordering."""
        sq = _sq(
            "sq1",
            TraversalFn.GET_COACHING_TREE,
            params={"coach_name": "Nick Saban", "max_depth": 4, "role_filter": "HC"},
        )
        plan = _make_plan(sub_queries=[sq])

        # All attempts return empty so we get to see which strategies fire.
        mock_execute = MagicMock(
            side_effect=[
                self._tree_result(plan, []),  # original: empty with role_filter
                self._tree_result(plan, []),  # retry 1: still empty, now no role_filter
            ]
        )
        monkeypatch.setattr("graphrag.retry.execute_plan", mock_execute)

        outcome = execute_with_retry(plan, driver=MagicMock(), max_retries=1)

        assert outcome.retries_attempted == 1
        # LimitRoleFilterStrategy fired first (not fallback_traversal)
        assert outcome.strategies_fired[0] == "limit_role_filter"

    def test_returns_retry_outcome_type(self, monkeypatch):
        """execute_with_retry always returns a RetryOutcome."""
        plan = _make_plan()
        mock_execute = MagicMock(
            return_value=ExecutionResult(plan=plan, ready_for_synthesis=False)
        )
        monkeypatch.setattr("graphrag.retry.execute_plan", mock_execute)

        outcome = execute_with_retry(plan)

        assert isinstance(outcome, RetryOutcome)
        assert isinstance(outcome.final_result, ExecutionResult)
