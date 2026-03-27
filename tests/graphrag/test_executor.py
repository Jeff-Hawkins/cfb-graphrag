"""Tests for graphrag/executor.py."""

from unittest.mock import MagicMock

import pytest

from graphrag.executor import combine_results, execute_plan
from graphrag.planner import EntityBundle, SubQuery, SubQueryPlan, TraversalFn


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_plan(
    *,
    ready: bool = True,
    sub_queries: list[SubQuery] | None = None,
    warnings: list[str] | None = None,
    intent: str = "TREE_QUERY",
) -> SubQueryPlan:
    """Build a minimal synthetic :class:`SubQueryPlan`."""
    return SubQueryPlan(
        intent=intent,
        confidence=0.9,
        question="test question",
        entities=EntityBundle(coaches=["Nick Saban"]),
        sub_queries=sub_queries or [],
        ready=ready,
        warnings=warnings or [],
    )


def _sq(
    id: str,
    traversal_fn: str,
    params: dict | None = None,
    depends_on: list[str] | None = None,
) -> SubQuery:
    """Build a minimal :class:`SubQuery`."""
    return SubQuery(
        id=id,
        traversal_fn=traversal_fn,
        params=params or {},
        depends_on=depends_on or [],
        description=f"test {id}",
    )


# Sentinel values returned by monkeypatched traversal functions.
_TREE_SENTINEL = [{"name": "Kirby Smart", "coach_code": 42, "depth": 1, "path_coaches": ["Nick Saban"]}]
_COACH_TREE_SENTINEL = [{"root": "Nick Saban", "protege": "Kirby Smart", "team": "Alabama", "years": 2015}]
_CONF_SENTINEL = [{"coach": "Nick Saban", "conferences": ["SEC"]}]
_PATH_SENTINEL = [{"path_nodes": ["Nick Saban", "Alabama", "Kirby Smart"], "hops": 2}]

# ---------------------------------------------------------------------------
# Test 1 — Happy path, one sub-query per non-combine TraversalFn
# ---------------------------------------------------------------------------


class TestHappyPath:
    """All four traversal fns succeed with no dependencies."""

    @pytest.fixture()
    def mock_driver(self) -> MagicMock:
        return MagicMock()

    def test_get_coaching_tree(self, mock_driver, monkeypatch):
        """GET_COACHING_TREE: resolves entity, calls traversal, stores result."""
        sq = _sq(
            "sq1",
            TraversalFn.GET_COACHING_TREE,
            params={"coach_name": "Nick Saban", "max_depth": 2, "role_filter": "HC"},
        )
        plan = _make_plan(sub_queries=[sq])

        monkeypatch.setattr(
            "graphrag.executor.resolve_coach_entity",
            lambda name, _: {
                "cfbd_node_id": "node:1",
                "mc_coach_code": 999,
                "display_name": name,
                "source": "both",
            },
        )
        mock_get_coaching_tree = MagicMock(return_value=_TREE_SENTINEL)
        monkeypatch.setattr("graphrag.graph_traversal.get_coaching_tree", mock_get_coaching_tree)

        result = execute_plan(plan, driver=mock_driver)

        mock_get_coaching_tree.assert_called_once_with(
            coach_code=999,
            max_depth=2,
            driver=mock_driver,
            role_filter="HC",
        )
        assert result.subquery_results["sq1"] == _TREE_SENTINEL
        assert result.ready_for_synthesis is True
        assert result.errors == []

    def test_get_coach_tree(self, mock_driver, monkeypatch):
        """GET_COACH_TREE: calls traversal with driver + coach_name."""
        sq = _sq("sq1", TraversalFn.GET_COACH_TREE, params={"coach_name": "Nick Saban"})
        plan = _make_plan(sub_queries=[sq])

        mock_fn = MagicMock(return_value=_COACH_TREE_SENTINEL)
        monkeypatch.setattr("graphrag.graph_traversal.get_coach_tree", mock_fn)

        result = execute_plan(plan, driver=mock_driver)

        mock_fn.assert_called_once_with(driver=mock_driver, coach_name="Nick Saban")
        assert result.subquery_results["sq1"] == _COACH_TREE_SENTINEL
        assert result.ready_for_synthesis is True

    def test_get_coaches_in_conferences(self, mock_driver, monkeypatch):
        """GET_COACHES_IN_CONFERENCES: calls traversal with driver + conferences."""
        sq = _sq(
            "sq1",
            TraversalFn.GET_COACHES_IN_CONFERENCES,
            params={"conferences": ["SEC", "Big Ten"]},
        )
        plan = _make_plan(sub_queries=[sq])

        mock_fn = MagicMock(return_value=_CONF_SENTINEL)
        monkeypatch.setattr("graphrag.graph_traversal.get_coaches_in_conferences", mock_fn)

        result = execute_plan(plan, driver=mock_driver)

        mock_fn.assert_called_once_with(driver=mock_driver, conferences=["SEC", "Big Ten"])
        assert result.subquery_results["sq1"] == _CONF_SENTINEL
        assert result.ready_for_synthesis is True

    def test_shortest_path_between_coaches(self, mock_driver, monkeypatch):
        """SHORTEST_PATH_BETWEEN_COACHES: calls traversal with driver + coach names."""
        sq = _sq(
            "sq1",
            TraversalFn.SHORTEST_PATH_BETWEEN_COACHES,
            params={"coach_a": "Kirby Smart", "coach_b": "Lincoln Riley"},
        )
        plan = _make_plan(sub_queries=[sq], intent="SIMILARITY")

        mock_fn = MagicMock(return_value=_PATH_SENTINEL)
        monkeypatch.setattr(
            "graphrag.graph_traversal.shortest_path_between_coaches", mock_fn
        )

        result = execute_plan(plan, driver=mock_driver)

        mock_fn.assert_called_once_with(
            driver=mock_driver, coach_a="Kirby Smart", coach_b="Lincoln Riley"
        )
        assert result.subquery_results["sq1"] == _PATH_SENTINEL
        assert result.ready_for_synthesis is True

    def test_all_four_traversal_fns_keyed_by_id(self, mock_driver, monkeypatch):
        """All four traversal fns run independently; results keyed by sq id."""
        sqs = [
            _sq("sq1", TraversalFn.GET_COACH_TREE, params={"coach_name": "Nick Saban"}),
            _sq("sq2", TraversalFn.GET_COACHES_IN_CONFERENCES, params={"conferences": ["SEC"]}),
            _sq(
                "sq3",
                TraversalFn.SHORTEST_PATH_BETWEEN_COACHES,
                params={"coach_a": "A", "coach_b": "B"},
            ),
            _sq(
                "sq4",
                TraversalFn.GET_COACHING_TREE,
                params={"coach_name": "Nick Saban", "max_depth": 3},
            ),
        ]
        plan = _make_plan(sub_queries=sqs)

        monkeypatch.setattr(
            "graphrag.executor.resolve_coach_entity",
            lambda name, _: {"mc_coach_code": 1, "source": "both", "display_name": name},
        )
        monkeypatch.setattr("graphrag.graph_traversal.get_coach_tree", MagicMock(return_value=["r1"]))
        monkeypatch.setattr(
            "graphrag.graph_traversal.get_coaches_in_conferences",
            MagicMock(return_value=["r2"]),
        )
        monkeypatch.setattr(
            "graphrag.graph_traversal.shortest_path_between_coaches",
            MagicMock(return_value=["r3"]),
        )
        monkeypatch.setattr(
            "graphrag.graph_traversal.get_coaching_tree", MagicMock(return_value=["r4"])
        )

        result = execute_plan(plan, driver=mock_driver)

        assert set(result.subquery_results.keys()) == {"sq1", "sq2", "sq3", "sq4"}
        assert result.ready_for_synthesis is True
        assert result.errors == []


# ---------------------------------------------------------------------------
# Test 2 — PERFORMANCE_COMPARE-style combine
# ---------------------------------------------------------------------------


class TestCombine:
    """Two independent sub-queries feed a COMBINE sub-query."""

    def test_combine_receives_both_results(self, monkeypatch):
        """C sees A and B results; aggregate stored under 'sq_c'."""
        mock_driver = MagicMock()

        sq_a = _sq("sq_a", TraversalFn.GET_COACH_TREE, params={"coach_name": "Nick Saban"})
        sq_b = _sq("sq_b", TraversalFn.GET_COACH_TREE, params={"coach_name": "Urban Meyer"})
        sq_c = _sq(
            "sq_c",
            TraversalFn.COMBINE,
            params={"strategy": "compare", "year_start": 2010, "year_end": 2020},
            depends_on=["sq_a", "sq_b"],
        )
        plan = _make_plan(sub_queries=[sq_a, sq_b, sq_c], intent="PERFORMANCE_COMPARE")

        result_a = [{"root": "Nick Saban"}]
        result_b = [{"root": "Urban Meyer"}]
        mock_fn = MagicMock(side_effect=[result_a, result_b])
        monkeypatch.setattr("graphrag.graph_traversal.get_coach_tree", mock_fn)

        result = execute_plan(plan, driver=mock_driver)

        # A and B ran first.
        assert mock_fn.call_count == 2
        assert result.subquery_results["sq_a"] == result_a
        assert result.subquery_results["sq_b"] == result_b

        # C produced an aggregate.
        combined = result.subquery_results["sq_c"]
        assert combined["strategy"] == "compare"
        assert combined["sources"]["sq_a"] == result_a
        assert combined["sources"]["sq_b"] == result_b
        assert combined["year_start"] == 2010
        assert combined["year_end"] == 2020

        assert result.ready_for_synthesis is True
        assert result.errors == []

    def test_combine_skipped_when_dependency_errored(self, monkeypatch):
        """If sq_a errors, sq_c (depends_on sq_a) is skipped with a warning."""
        mock_driver = MagicMock()

        sq_a = _sq("sq_a", TraversalFn.GET_COACH_TREE, params={"coach_name": "Nick Saban"})
        sq_b = _sq("sq_b", TraversalFn.GET_COACH_TREE, params={"coach_name": "Urban Meyer"})
        sq_c = _sq(
            "sq_c",
            TraversalFn.COMBINE,
            params={"strategy": "compare"},
            depends_on=["sq_a", "sq_b"],
        )
        plan = _make_plan(sub_queries=[sq_a, sq_b, sq_c], intent="PERFORMANCE_COMPARE")

        def _side_effect(driver, coach_name):  # noqa: ARG001
            if coach_name == "Nick Saban":
                raise RuntimeError("DB connection lost")
            return [{"root": "Urban Meyer"}]

        monkeypatch.setattr("graphrag.graph_traversal.get_coach_tree", _side_effect)

        result = execute_plan(plan, driver=mock_driver)

        assert "sq_a" in result.errors[0]
        assert result.subquery_results.get("sq_b") is not None
        assert "sq_c" not in result.subquery_results
        assert any("sq_c" in w for w in result.warnings)
        assert result.ready_for_synthesis is False


# ---------------------------------------------------------------------------
# Test 3 — Dependency failure propagation
# ---------------------------------------------------------------------------


class TestDependencyFailure:
    """One traversal failure cascades to downstream dependents but not independents."""

    def test_downstream_skipped_independent_runs(self, monkeypatch):
        """sq_b (depends on sq_a) is skipped; sq_c (independent) still runs."""
        mock_driver = MagicMock()

        sq_a = _sq("sq_a", TraversalFn.GET_COACH_TREE, params={"coach_name": "Nick Saban"})
        sq_b = _sq(
            "sq_b",
            TraversalFn.GET_COACH_TREE,
            params={"coach_name": "Kirby Smart"},
            depends_on=["sq_a"],
        )
        sq_c = _sq("sq_c", TraversalFn.GET_COACH_TREE, params={"coach_name": "Urban Meyer"})
        plan = _make_plan(sub_queries=[sq_a, sq_b, sq_c])

        def _side_effect(driver, coach_name):  # noqa: ARG001
            if coach_name == "Nick Saban":
                raise ValueError("traversal error")
            return [{"root": coach_name}]

        monkeypatch.setattr("graphrag.graph_traversal.get_coach_tree", _side_effect)

        result = execute_plan(plan, driver=mock_driver)

        # sq_a errored.
        assert any("sq_a" in e for e in result.errors)
        # sq_b skipped (dependency failed).
        assert "sq_b" not in result.subquery_results
        assert any("sq_b" in w for w in result.warnings)
        # sq_c (independent) still ran.
        assert result.subquery_results.get("sq_c") is not None
        # Overall not ready.
        assert result.ready_for_synthesis is False

    def test_error_message_contains_sq_id_and_fn(self, monkeypatch):
        """Error entries include sub-query ID and TraversalFn name."""
        mock_driver = MagicMock()
        sq = _sq("sq_x", TraversalFn.GET_COACH_TREE, params={"coach_name": "No One"})
        plan = _make_plan(sub_queries=[sq])

        monkeypatch.setattr(
            "graphrag.graph_traversal.get_coach_tree",
            MagicMock(side_effect=RuntimeError("boom")),
        )

        result = execute_plan(plan, driver=mock_driver)

        assert len(result.errors) == 1
        assert "sq_x" in result.errors[0]
        assert "GET_COACH_TREE" in result.errors[0]

    def test_entity_resolution_failure_records_error(self, monkeypatch):
        """Unresolvable coach name records error; downstream is skipped."""
        mock_driver = MagicMock()
        sq = _sq(
            "sq_e",
            TraversalFn.GET_COACHING_TREE,
            params={"coach_name": "Unknown Coach", "max_depth": 2},
        )
        plan = _make_plan(sub_queries=[sq])

        monkeypatch.setattr(
            "graphrag.executor.resolve_coach_entity",
            lambda name, _: {
                "cfbd_node_id": None,
                "mc_coach_code": None,
                "display_name": name,
                "source": "cfbd_only",
            },
        )
        mock_traversal = MagicMock()
        monkeypatch.setattr("graphrag.graph_traversal.get_coaching_tree", mock_traversal)

        result = execute_plan(plan, driver=mock_driver)

        mock_traversal.assert_not_called()
        assert any("sq_e" in e for e in result.errors)
        assert result.ready_for_synthesis is False


# ---------------------------------------------------------------------------
# Test 4 — plan.ready=False short-circuit
# ---------------------------------------------------------------------------


class TestNotReady:
    """When plan.ready is False, no traversals run."""

    def test_no_traversals_called(self, monkeypatch):
        """All traversal functions remain uncalled when plan.ready is False."""
        plan = _make_plan(
            ready=False,
            sub_queries=[
                _sq("sq1", TraversalFn.GET_COACH_TREE, params={"coach_name": "Nick Saban"}),
                _sq("sq2", TraversalFn.GET_COACHES_IN_CONFERENCES, params={"conferences": ["SEC"]}),
            ],
            warnings=["Missing required entity: coach", "Low confidence: 0.3"],
        )

        mock_fn = MagicMock()
        monkeypatch.setattr("graphrag.graph_traversal.get_coach_tree", mock_fn)
        monkeypatch.setattr("graphrag.graph_traversal.get_coaches_in_conferences", mock_fn)

        result = execute_plan(plan, driver=MagicMock())

        mock_fn.assert_not_called()
        assert result.subquery_results == {}
        assert result.ready_for_synthesis is False

    def test_plan_warnings_forwarded(self, monkeypatch):
        """Warnings from plan.warnings appear in result.warnings."""
        plan_warnings = ["Missing required entity: coach", "Ambiguous name: Saban"]
        plan = _make_plan(ready=False, warnings=plan_warnings)

        result = execute_plan(plan)

        for w in plan_warnings:
            assert w in result.warnings

    def test_empty_results_and_no_errors(self):
        """subquery_results is empty and errors list is empty (not the plan's fault)."""
        plan = _make_plan(
            ready=False,
            sub_queries=[_sq("sq1", TraversalFn.GET_COACH_TREE)],
            warnings=["planner warning"],
        )
        result = execute_plan(plan)

        assert result.subquery_results == {}
        assert result.errors == []
        assert result.ready_for_synthesis is False


# ---------------------------------------------------------------------------
# Test 5 — Cycle detection
# ---------------------------------------------------------------------------


class TestCycleDetection:
    """Cycles in depends_on are detected before any traversal runs."""

    def test_cycle_records_error_and_stops(self, monkeypatch):
        """A → B → A cycle: error recorded, ready_for_synthesis False, no traversal."""
        sq_a = _sq("sq_a", TraversalFn.GET_COACH_TREE, depends_on=["sq_b"])
        sq_b = _sq("sq_b", TraversalFn.GET_COACH_TREE, depends_on=["sq_a"])
        plan = _make_plan(sub_queries=[sq_a, sq_b])

        mock_fn = MagicMock()
        monkeypatch.setattr("graphrag.graph_traversal.get_coach_tree", mock_fn)

        result = execute_plan(plan, driver=MagicMock())

        mock_fn.assert_not_called()
        assert len(result.errors) == 1
        assert "Cycle" in result.errors[0]
        assert result.ready_for_synthesis is False


# ---------------------------------------------------------------------------
# Unit tests for combine_results helper
# ---------------------------------------------------------------------------


class TestCombineResults:
    """Direct unit tests for the combine_results helper."""

    def test_combines_sources_and_strategy(self):
        """Sources are keyed by dep_id; strategy is forwarded."""
        subquery = _sq(
            "sq_c",
            TraversalFn.COMBINE,
            params={"strategy": "compare"},
            depends_on=["sq_a", "sq_b"],
        )
        existing = {"sq_a": ["result_a"], "sq_b": ["result_b"]}

        combined = combine_results(subquery, existing)

        assert combined["strategy"] == "compare"
        assert combined["sources"]["sq_a"] == ["result_a"]
        assert combined["sources"]["sq_b"] == ["result_b"]

    def test_year_range_forwarded_when_present(self):
        """year_start and year_end appear in aggregate when in params."""
        subquery = _sq(
            "sq_c",
            TraversalFn.COMBINE,
            params={"strategy": "merge", "year_start": 2015, "year_end": 2022},
            depends_on=["sq_a"],
        )
        combined = combine_results(subquery, {"sq_a": []})

        assert combined["year_start"] == 2015
        assert combined["year_end"] == 2022

    def test_missing_dep_returns_none_in_sources(self):
        """A dep_id not yet in subquery_results maps to None."""
        subquery = _sq(
            "sq_c", TraversalFn.COMBINE, params={"strategy": "merge"}, depends_on=["sq_x"]
        )
        combined = combine_results(subquery, {})

        assert combined["sources"]["sq_x"] is None

    def test_default_strategy_is_merge(self):
        """When no strategy param, defaults to 'merge'."""
        subquery = _sq("sq_c", TraversalFn.COMBINE, depends_on=[])
        combined = combine_results(subquery, {})

        assert combined["strategy"] == "merge"
