"""Orchestrates the full F4 GraphRAG pipeline: classify → plan → execute → synthesize.

Pipeline position::

    NL query → retriever.py
                ↓
            classifier.py   (intent bucket + confidence)
                ↓
            planner.py      (entity extraction + sub-query plan)
                ↓
            executor.py     (Neo4j traversals, topo-sorted)
                ↓
            retry.py        (ReduceDepth / LimitRoleFilter / FallbackTraversal)
                ↓
            synthesizer.py  (structured answer + F1 Explain My Result rows)

Typical usage::

    from graphrag.retriever import retrieve_with_graphrag

    result = retrieve_with_graphrag(question, driver=driver)
    print(result.response.answer)
    for row in result.response.result_rows:
        print(row.display_name, "—", row.explanation)
"""

import logging
import os
from dataclasses import dataclass

from google import genai
from neo4j import Driver

from graphrag.classifier import classify_intent
from graphrag.planner import EntityBundle, SubQueryPlan, build_plan
from graphrag.retry import execute_with_retry
from graphrag.synthesizer import (
    SynthesisInput,
    SynthesizedResponse,
    synthesize_response,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------


@dataclass
class GraphRAGQueryResult:
    """Return type of :func:`retrieve_with_graphrag`.

    Bundles the structured response with metadata the UI needs to make
    smart rendering decisions (e.g. which visualization to show).

    Attributes:
        response: Full :class:`~graphrag.synthesizer.SynthesizedResponse`
            with the primary answer, per-coach result rows (each carrying an
            F1 *Explain My Result* string), partial flag, and warnings.
        intent: Classified intent bucket (e.g. ``"TREE_QUERY"``).
        root_name: First coach entity from the plan, or ``""`` when absent.
            Useful in the UI as the label for the root node of a tree
            visualisation.
    """

    response: SynthesizedResponse
    intent: str
    root_name: str


# ---------------------------------------------------------------------------
# Primary pipeline entry point
# ---------------------------------------------------------------------------


def retrieve_with_graphrag(
    question: str,
    driver: Driver,
    client: genai.Client | None = None,
) -> GraphRAGQueryResult:
    """Execute the full F4 GraphRAG pipeline for a natural language question.

    Steps:

    1. :func:`~graphrag.classifier.classify_intent` — intent bucket + confidence.
    2. :func:`~graphrag.planner.build_plan` — entity extraction + sub-query plan.
    3. :func:`~graphrag.retry.execute_with_retry` — run plan with retry strategies.
    4. :func:`~graphrag.synthesizer.synthesize_response` — structured answer + F1
       *Explain My Result* strings.

    Degrades gracefully on classification or planning failures — returns a
    partial result with warnings rather than raising.

    Args:
        question: Natural language question about college football.
        driver: Open Neo4j driver connected to the loaded graph.
        client: Optional ``genai.Client``.  If omitted a new client is created
            using ``GEMINI_API_KEY`` from the environment.

    Returns:
        :class:`GraphRAGQueryResult` bundling the structured
        :class:`~graphrag.synthesizer.SynthesizedResponse`, classified intent,
        and root coach name for UI rendering decisions.
    """
    if client is None:
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    # 1. Classify intent.
    try:
        classification = classify_intent(question, client=client)
    except Exception as exc:  # noqa: BLE001
        logger.warning("classify_intent failed: %s", exc)
        classification = {"intent": "TREE_QUERY", "confidence": 0.0}

    intent: str = classification["intent"]
    confidence: float = float(classification["confidence"])

    # 2. Build sub-query plan.
    try:
        plan: SubQueryPlan = build_plan(
            question=question,
            intent=intent,
            confidence=confidence,
            client=client,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("build_plan failed: %s", exc)
        plan = SubQueryPlan(
            intent=intent,
            confidence=confidence,
            question=question,
            entities=EntityBundle(),
            sub_queries=[],
            ready=False,
            warnings=[f"Planning failed: {exc}"],
        )

    root_name: str = plan.entities.coaches[0] if plan.entities.coaches else ""

    # 3. Execute with retry.
    retry_outcome = execute_with_retry(plan, driver=driver)

    # 4. Synthesize structured response.
    response = synthesize_response(
        SynthesisInput(
            plan=plan,
            execution_result=retry_outcome.final_result,
            retry_outcome=retry_outcome,
        )
    )

    return GraphRAGQueryResult(
        response=response,
        intent=intent,
        root_name=root_name,
    )


# ---------------------------------------------------------------------------
# Backward-compatible thin wrapper
# ---------------------------------------------------------------------------


def answer_question(
    question: str,
    driver: Driver,
    client: genai.Client | None = None,
) -> str:
    """Answer a natural language question using the F4 GraphRAG pipeline.

    Thin wrapper over :func:`retrieve_with_graphrag` that returns only the
    primary answer string.  Use :func:`retrieve_with_graphrag` directly when
    you need structured result rows and F1 *Explain My Result* provenance.

    Args:
        question: Natural language question about college football.
        driver: Open Neo4j driver connected to the loaded graph.
        client: Optional ``genai.Client``.  If omitted a new client is
            created using ``GEMINI_API_KEY`` from the environment.

    Returns:
        A natural language answer string.
    """
    return retrieve_with_graphrag(
        question, driver=driver, client=client
    ).response.answer
