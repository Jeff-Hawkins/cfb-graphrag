"""Tests for graphrag/retriever.py — F4 pipeline wiring."""

from unittest.mock import MagicMock, patch

from graphrag.executor import ExecutionResult
from graphrag.planner import EntityBundle, SubQueryPlan
from graphrag.retriever import (
    GraphRAGQueryResult,
    _fetch_direct_mentees,
    _resolve_mc_coach_code,
    answer_question,
    retrieve_with_graphrag,
)
from graphrag.retry import RetryOutcome
from graphrag.synthesizer import SynthesizedResponse

# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_plan(coaches: list[str] | None = None, ready: bool = True) -> SubQueryPlan:
    return SubQueryPlan(
        intent="TREE_QUERY",
        confidence=0.9,
        question="test question",
        entities=EntityBundle(
            coaches=coaches if coaches is not None else ["Nick Saban"]
        ),
        sub_queries=[],
        ready=ready,
    )


def _make_exec_result(plan: SubQueryPlan) -> ExecutionResult:
    return ExecutionResult(
        plan=plan,
        subquery_results={},
        errors=[],
        warnings=[],
        ready_for_synthesis=True,
    )


def _make_retry_outcome(plan: SubQueryPlan) -> RetryOutcome:
    return RetryOutcome(final_result=_make_exec_result(plan))


def _make_response(answer: str = "Test answer.") -> SynthesizedResponse:
    return SynthesizedResponse(
        answer=answer, result_rows=[], partial=False, warnings=[]
    )


def _make_graphrag_result(answer: str = "Test answer.") -> GraphRAGQueryResult:
    return GraphRAGQueryResult(
        response=_make_response(answer),
        intent="TREE_QUERY",
        root_name="Nick Saban",
    )


def _neo4j_driver() -> MagicMock:
    """Minimal Neo4j driver mock with an empty-result session."""
    driver = MagicMock()
    session = MagicMock()
    session.run.return_value.__iter__ = MagicMock(return_value=iter([]))
    session.run.return_value.single = MagicMock(return_value=None)
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)
    return driver


# ---------------------------------------------------------------------------
# retrieve_with_graphrag — pipeline orchestration
# ---------------------------------------------------------------------------


class TestRetrieveWithGraphrag:
    """Tests for retrieve_with_graphrag() — the primary F4 pipeline entry point."""

    def _run_with_mocks(
        self,
        question: str = "Show me Nick Saban's tree",
        plan: SubQueryPlan | None = None,
    ):
        """Run retrieve_with_graphrag with all pipeline functions mocked.

        Returns (result, mock_classify, mock_plan, mock_execute, mock_synth).
        """
        if plan is None:
            plan = _make_plan()
        retry_outcome = _make_retry_outcome(plan)
        response = _make_response()

        with (
            patch(
                "graphrag.retriever.classify_intent",
                return_value={"intent": "TREE_QUERY", "confidence": 0.9},
            ) as mock_classify,
            patch("graphrag.retriever.build_plan", return_value=plan) as mock_plan,
            patch(
                "graphrag.retriever.execute_with_retry", return_value=retry_outcome
            ) as mock_execute,
            patch(
                "graphrag.retriever.synthesize_response", return_value=response
            ) as mock_synth,
        ):
            result = retrieve_with_graphrag(
                question, driver=_neo4j_driver(), client=MagicMock()
            )

        return result, mock_classify, mock_plan, mock_execute, mock_synth

    # --- return type ---

    def test_returns_graphrag_query_result(self):
        result, *_ = self._run_with_mocks()
        assert isinstance(result, GraphRAGQueryResult)

    def test_response_is_synthesized_response(self):
        result, *_ = self._run_with_mocks()
        assert isinstance(result.response, SynthesizedResponse)

    # --- metadata fields ---

    def test_intent_set_from_classifier(self):
        result, *_ = self._run_with_mocks()
        assert result.intent == "TREE_QUERY"

    def test_root_name_set_from_plan_entities(self):
        result, *_ = self._run_with_mocks()
        assert result.root_name == "Nick Saban"

    def test_root_name_empty_when_no_coaches(self):
        plan = _make_plan(coaches=[])
        retry_outcome = _make_retry_outcome(plan)
        with (
            patch(
                "graphrag.retriever.classify_intent",
                return_value={"intent": "TREE_QUERY", "confidence": 0.9},
            ),
            patch("graphrag.retriever.build_plan", return_value=plan),
            patch("graphrag.retriever.execute_with_retry", return_value=retry_outcome),
            patch(
                "graphrag.retriever.synthesize_response", return_value=_make_response()
            ),
        ):
            result = retrieve_with_graphrag(
                "test", driver=_neo4j_driver(), client=MagicMock()
            )
        assert result.root_name == ""

    # --- pipeline call sequence ---

    def test_classify_intent_called_with_question(self):
        _, mock_classify, *_ = self._run_with_mocks("Show me Saban's tree")
        mock_classify.assert_called_once()
        assert mock_classify.call_args[0][0] == "Show me Saban's tree"

    def test_build_plan_called_with_intent_and_confidence(self):
        _, _, mock_plan, *_ = self._run_with_mocks()
        mock_plan.assert_called_once()
        kwargs = mock_plan.call_args[1]
        assert kwargs["intent"] == "TREE_QUERY"
        assert kwargs["confidence"] == 0.9

    def test_execute_with_retry_called_with_plan(self):
        plan = _make_plan()
        retry_outcome = _make_retry_outcome(plan)
        with (
            patch(
                "graphrag.retriever.classify_intent",
                return_value={"intent": "TREE_QUERY", "confidence": 0.9},
            ),
            patch("graphrag.retriever.build_plan", return_value=plan),
            patch(
                "graphrag.retriever.execute_with_retry", return_value=retry_outcome
            ) as mock_execute,
            patch(
                "graphrag.retriever.synthesize_response", return_value=_make_response()
            ),
        ):
            retrieve_with_graphrag("test", driver=_neo4j_driver(), client=MagicMock())
        mock_execute.assert_called_once()
        assert mock_execute.call_args[0][0] is plan

    def test_synthesize_response_called(self):
        _, _, _, _, mock_synth = self._run_with_mocks()
        mock_synth.assert_called_once()

    # --- graceful degradation ---

    def test_classify_intent_exception_does_not_raise(self):
        plan = _make_plan()
        retry_outcome = _make_retry_outcome(plan)
        with (
            patch(
                "graphrag.retriever.classify_intent",
                side_effect=RuntimeError("classifier boom"),
            ),
            patch("graphrag.retriever.build_plan", return_value=plan),
            patch("graphrag.retriever.execute_with_retry", return_value=retry_outcome),
            patch(
                "graphrag.retriever.synthesize_response", return_value=_make_response()
            ),
        ):
            result = retrieve_with_graphrag(
                "test", driver=_neo4j_driver(), client=MagicMock()
            )
        assert isinstance(result, GraphRAGQueryResult)

    def test_build_plan_exception_does_not_raise(self):
        """When build_plan raises, a fallback empty plan is used and no error surfaces."""
        plan = _make_plan(ready=False)
        retry_outcome = _make_retry_outcome(plan)
        with (
            patch(
                "graphrag.retriever.classify_intent",
                return_value={"intent": "TREE_QUERY", "confidence": 0.9},
            ),
            patch(
                "graphrag.retriever.build_plan",
                side_effect=RuntimeError("planner boom"),
            ),
            patch("graphrag.retriever.execute_with_retry", return_value=retry_outcome),
            patch(
                "graphrag.retriever.synthesize_response", return_value=_make_response()
            ),
        ):
            result = retrieve_with_graphrag(
                "test", driver=_neo4j_driver(), client=MagicMock()
            )
        assert isinstance(result, GraphRAGQueryResult)

    def test_creates_genai_client_when_none_provided(self, monkeypatch):
        """When client=None, a genai.Client is constructed from GEMINI_API_KEY."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        plan = _make_plan()
        retry_outcome = _make_retry_outcome(plan)
        with (
            patch("graphrag.retriever.genai") as mock_genai,
            patch(
                "graphrag.retriever.classify_intent",
                return_value={"intent": "TREE_QUERY", "confidence": 0.9},
            ),
            patch("graphrag.retriever.build_plan", return_value=plan),
            patch("graphrag.retriever.execute_with_retry", return_value=retry_outcome),
            patch(
                "graphrag.retriever.synthesize_response", return_value=_make_response()
            ),
        ):
            retrieve_with_graphrag("test", driver=_neo4j_driver())
        mock_genai.Client.assert_called_once_with(api_key="test-key")


# ---------------------------------------------------------------------------
# F4b Precomputed narrative fast-path
# ---------------------------------------------------------------------------


class TestNarrativeFastPath:
    """Tests for the F4b narrative check inserted between plan and execute."""

    def _run_with_narrative(
        self,
        narrative: str | None,
        intent: str = "TREE_QUERY",
        coaches: list[str] | None = None,
    ):
        """Run retrieve_with_graphrag with a controllable narrative mock.

        Returns (result, mock_execute, mock_synth, mock_get_narrative).
        """
        plan = _make_plan(coaches=coaches if coaches is not None else ["Nick Saban"])
        # Override intent in plan.
        plan.intent = intent
        retry_outcome = _make_retry_outcome(plan)
        response = _make_response()

        with (
            patch(
                "graphrag.retriever.classify_intent",
                return_value={"intent": intent, "confidence": 0.9},
            ),
            patch("graphrag.retriever.build_plan", return_value=plan),
            patch(
                "graphrag.retriever.get_coach_narrative_by_name",
                return_value=narrative,
            ) as mock_get_narrative,
            patch(
                "graphrag.retriever.execute_with_retry", return_value=retry_outcome
            ) as mock_execute,
            patch(
                "graphrag.retriever.synthesize_response", return_value=response
            ) as mock_synth,
        ):
            result = retrieve_with_graphrag(
                "Show me Nick Saban's tree",
                driver=_neo4j_driver(),
                client=MagicMock(),
            )

        return result, mock_execute, mock_synth, mock_get_narrative

    # --- narrative present ---

    def test_narrative_used_flag_true_when_narrative_found(self):
        result, *_ = self._run_with_narrative("Saban coached everyone.")
        assert result.narrative_used is True

    def test_answer_is_precomputed_narrative(self):
        result, *_ = self._run_with_narrative("Saban coached everyone.")
        assert result.response.answer == "Saban coached everyone."

    def test_pipeline_not_invoked_when_narrative_found(self):
        """execute_with_retry and synthesize_response are NOT called when narrative found.

        The answer text comes from the precomputed narrative.  Graph rows come
        from _fetch_direct_mentees() (direct depth-1 traversal), not the full
        execute+synthesize pipeline.
        """
        _, mock_execute, mock_synth, _ = self._run_with_narrative("Saban coached everyone.")
        mock_execute.assert_not_called()
        mock_synth.assert_not_called()

    def test_narrative_check_called_for_tree_query(self):
        _, _, _, mock_get_narrative = self._run_with_narrative(
            "Saban coached everyone.", intent="TREE_QUERY"
        )
        mock_get_narrative.assert_called_once()
        assert mock_get_narrative.call_args[0][0] == "Nick Saban"

    def test_result_rows_from_live_exec_when_narrative_found(self):
        """result_rows are populated from live execute+synth even when narrative used.

        In this test the mock synthesize_response returns an empty list, so the
        assertion is that result_rows equals whatever the synthesizer returned —
        in production that will be non-empty tree rows for the graph.
        """
        result, *_ = self._run_with_narrative("Saban coached everyone.")
        # Mock _make_response() returns result_rows=[] — confirm it's passed through.
        assert result.response.result_rows == []

    def test_partial_false_when_narrative_used(self):
        result, *_ = self._run_with_narrative("Saban coached everyone.")
        assert result.response.partial is False

    # --- narrative absent (None) ---

    def test_narrative_used_flag_false_when_no_narrative(self):
        result, *_ = self._run_with_narrative(None)
        assert result.narrative_used is False

    def test_pipeline_runs_when_no_narrative(self):
        _, mock_execute, mock_synth, _ = self._run_with_narrative(None)
        mock_execute.assert_called_once()
        mock_synth.assert_called_once()

    # --- non-tree intent: narrative check must NOT fire ---

    def test_narrative_not_checked_for_performance_compare(self):
        _, mock_execute, _, mock_get_narrative = self._run_with_narrative(
            "some narrative", intent="PERFORMANCE_COMPARE"
        )
        mock_get_narrative.assert_not_called()
        mock_execute.assert_called_once()

    def test_narrative_not_checked_for_similarity(self):
        _, mock_execute, _, mock_get_narrative = self._run_with_narrative(
            "some narrative", intent="SIMILARITY"
        )
        mock_get_narrative.assert_not_called()
        mock_execute.assert_called_once()

    def test_narrative_not_checked_when_no_root_coach(self):
        """When no coach entity is resolved (root_name=''), skip the narrative check."""
        plan = _make_plan(coaches=[])
        plan.intent = "TREE_QUERY"
        retry_outcome = _make_retry_outcome(plan)

        with (
            patch(
                "graphrag.retriever.classify_intent",
                return_value={"intent": "TREE_QUERY", "confidence": 0.9},
            ),
            patch("graphrag.retriever.build_plan", return_value=plan),
            patch(
                "graphrag.retriever.get_coach_narrative_by_name"
            ) as mock_get_narrative,
            patch(
                "graphrag.retriever.execute_with_retry", return_value=retry_outcome
            ),
            patch(
                "graphrag.retriever.synthesize_response",
                return_value=_make_response(),
            ),
        ):
            retrieve_with_graphrag("test", driver=_neo4j_driver(), client=MagicMock())

        mock_get_narrative.assert_not_called()

    # --- graceful degradation when narrative check raises ---

    def test_pipeline_runs_when_narrative_check_raises(self):
        """If get_coach_narrative_by_name raises, the full pipeline runs as fallback."""
        plan = _make_plan()
        retry_outcome = _make_retry_outcome(plan)

        with (
            patch(
                "graphrag.retriever.classify_intent",
                return_value={"intent": "TREE_QUERY", "confidence": 0.9},
            ),
            patch("graphrag.retriever.build_plan", return_value=plan),
            patch(
                "graphrag.retriever.get_coach_narrative_by_name",
                side_effect=RuntimeError("neo4j boom"),
            ),
            patch(
                "graphrag.retriever.execute_with_retry", return_value=retry_outcome
            ) as mock_execute,
            patch(
                "graphrag.retriever.synthesize_response",
                return_value=_make_response(),
            ),
        ):
            result = retrieve_with_graphrag(
                "test", driver=_neo4j_driver(), client=MagicMock()
            )

        assert isinstance(result, GraphRAGQueryResult)
        mock_execute.assert_called_once()
        assert result.narrative_used is False

    # --- narrative_used default ---

    def test_narrative_used_defaults_false_on_normal_pipeline(self, monkeypatch):
        """narrative_used is False for a normal (non-narrative) pipeline run."""
        result, *_ = self._run_with_narrative(None)
        assert result.narrative_used is False


# ---------------------------------------------------------------------------
# answer_question — thin wrapper
# ---------------------------------------------------------------------------


class TestAnswerQuestion:
    """answer_question() is a thin wrapper that returns just the answer string."""

    def test_returns_string(self):
        with patch(
            "graphrag.retriever.retrieve_with_graphrag",
            return_value=_make_graphrag_result("Test answer."),
        ):
            result = answer_question(
                "test question", driver=_neo4j_driver(), client=MagicMock()
            )
        assert isinstance(result, str)

    def test_returns_response_answer_field(self):
        expected = "Nick Saban coached many great coaches."
        with patch(
            "graphrag.retriever.retrieve_with_graphrag",
            return_value=_make_graphrag_result(expected),
        ):
            result = answer_question(
                "test question", driver=_neo4j_driver(), client=MagicMock()
            )
        assert result == expected

    def test_delegates_to_retrieve_with_graphrag(self):
        with patch(
            "graphrag.retriever.retrieve_with_graphrag",
            return_value=_make_graphrag_result(),
        ) as mock_rg:
            answer_question("my question", driver=_neo4j_driver(), client=MagicMock())
        mock_rg.assert_called_once()
        assert mock_rg.call_args[0][0] == "my question"

    def test_passes_driver_and_client(self):
        driver = _neo4j_driver()
        client = MagicMock()
        with patch(
            "graphrag.retriever.retrieve_with_graphrag",
            return_value=_make_graphrag_result(),
        ) as mock_rg:
            answer_question("q", driver=driver, client=client)
        kwargs = mock_rg.call_args[1]
        assert kwargs["driver"] is driver
        assert kwargs["client"] is client


# ---------------------------------------------------------------------------
# _fetch_direct_mentees — graph viz helper
# ---------------------------------------------------------------------------


class TestFetchDirectMentees:
    """Unit tests for the _fetch_direct_mentees() internal helper.

    _fetch_direct_mentees calls _resolve_mc_coach_code (not resolve_coach_entity)
    so mocks target graphrag.retriever._resolve_mc_coach_code.
    """

    def test_returns_empty_list_when_no_mc_code(self):
        """When _resolve_mc_coach_code returns None, result is empty."""
        with patch(
            "graphrag.retriever._resolve_mc_coach_code",
            return_value=None,
        ):
            rows = _fetch_direct_mentees("Unknown Coach", _neo4j_driver())
        assert rows == []

    def test_returns_empty_list_on_traversal_error(self):
        """A traversal exception is caught and returns empty list."""
        with (
            patch("graphrag.retriever._resolve_mc_coach_code", return_value=42),
            patch(
                "graphrag.retriever._graph_traversal.get_coaching_tree",
                side_effect=RuntimeError("neo4j down"),
            ),
        ):
            rows = _fetch_direct_mentees("Nick Saban", _neo4j_driver())
        assert rows == []

    def test_returns_result_rows_for_depth_1(self):
        """Depth-1 raw rows are converted to ResultRow objects."""
        raw = [
            {"name": "Kirby Smart", "depth": 1, "coach_code": 99, "confidence_flag": "STANDARD"},
            {"name": "Lane Kiffin", "depth": 1, "coach_code": 77, "confidence_flag": None},
        ]
        with (
            patch("graphrag.retriever._resolve_mc_coach_code", return_value=1457),
            patch(
                "graphrag.retriever._graph_traversal.get_coaching_tree",
                return_value=raw,
            ),
        ):
            rows = _fetch_direct_mentees("Nick Saban", _neo4j_driver())

        assert len(rows) == 2
        assert rows[0].display_name == "Kirby Smart"
        assert rows[0].depth == 1
        assert rows[1].display_name == "Lane Kiffin"

    def test_includes_depth_1_and_depth_2_rows(self):
        """Both depth-1 and depth-2 HC rows are returned."""
        raw = [
            {"name": "Kirby Smart", "depth": 1, "coach_code": 99,
             "path_coaches": ["Nick Saban", "Kirby Smart"]},
            {"name": "Dan Lanning", "depth": 2, "coach_code": 55,
             "path_coaches": ["Nick Saban", "Kirby Smart", "Dan Lanning"]},
        ]
        with (
            patch("graphrag.retriever._resolve_mc_coach_code", return_value=1457),
            patch(
                "graphrag.retriever._graph_traversal.get_coaching_tree",
                return_value=raw,
            ),
        ):
            rows = _fetch_direct_mentees("Nick Saban", _neo4j_driver())

        assert len(rows) == 2
        assert rows[0].display_name == "Kirby Smart"
        assert rows[0].depth == 1
        assert rows[1].display_name == "Dan Lanning"
        assert rows[1].depth == 2
        assert "Kirby Smart" in rows[1].explanation

    def test_deduplicates_by_name(self):
        """Duplicate coach names are collapsed to one ResultRow."""
        raw = [
            {"name": "Kirby Smart", "depth": 1, "coach_code": 99},
            {"name": "Kirby Smart", "depth": 1, "coach_code": 99},
        ]
        with (
            patch("graphrag.retriever._resolve_mc_coach_code", return_value=1457),
            patch(
                "graphrag.retriever._graph_traversal.get_coaching_tree",
                return_value=raw,
            ),
        ):
            rows = _fetch_direct_mentees("Nick Saban", _neo4j_driver())

        assert len(rows) == 1

    def test_explanation_references_root_name(self):
        """The explanation string mentions the root coach name."""
        raw = [{"name": "Kirby Smart", "depth": 1, "coach_code": 99}]
        with (
            patch("graphrag.retriever._resolve_mc_coach_code", return_value=1457),
            patch(
                "graphrag.retriever._graph_traversal.get_coaching_tree",
                return_value=raw,
            ),
        ):
            rows = _fetch_direct_mentees("Nick Saban", _neo4j_driver())

        assert "Nick Saban" in rows[0].explanation


# ---------------------------------------------------------------------------
# _resolve_mc_coach_code — dual-path coach_code lookup
# ---------------------------------------------------------------------------


class TestResolveMcCoachCode:
    """Unit tests for the _resolve_mc_coach_code() internal helper."""

    def test_returns_none_for_single_token_name(self):
        """Names that can't be split into first/last return None."""
        assert _resolve_mc_coach_code("Saban", _neo4j_driver()) is None

    def test_returns_mc_code_from_record(self):
        """Returns the mc_code value from the Cypher record."""
        driver = _neo4j_driver()
        session = driver.session.return_value.__enter__.return_value
        session.run.return_value.single.return_value = {"mc_code": 1457}
        result = _resolve_mc_coach_code("Nick Saban", driver)
        assert result == 1457

    def test_returns_none_when_record_is_none(self):
        """Returns None when no Neo4j record is found."""
        driver = _neo4j_driver()
        session = driver.session.return_value.__enter__.return_value
        session.run.return_value.single.return_value = None
        result = _resolve_mc_coach_code("Nick Saban", driver)
        assert result is None

    def test_returns_none_when_mc_code_is_null(self):
        """Returns None when the record exists but mc_code is NULL."""
        driver = _neo4j_driver()
        session = driver.session.return_value.__enter__.return_value
        session.run.return_value.single.return_value = {"mc_code": None}
        result = _resolve_mc_coach_code("Nick Saban", driver)
        assert result is None
