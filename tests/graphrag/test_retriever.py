"""Tests for graphrag/retriever.py — F4 pipeline wiring."""

from unittest.mock import MagicMock, patch

from graphrag.executor import ExecutionResult
from graphrag.planner import EntityBundle, SubQueryPlan
from graphrag.retriever import (
    GraphRAGQueryResult,
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
