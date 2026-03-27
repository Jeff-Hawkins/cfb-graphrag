"""Orchestrates the full F4 GraphRAG pipeline: classify → plan → execute → synthesize.

Pipeline position::

    NL query → retriever.py
                ↓
            classifier.py   (intent bucket + confidence)
                ↓
            planner.py      (entity extraction + sub-query plan)
                ↓
            narratives.py   (F4b precomputed narrative check — early exit if found)
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
from dataclasses import dataclass, field

from google import genai
from neo4j import Driver

from graphrag import graph_traversal as _graph_traversal
from graphrag.classifier import classify_intent
from graphrag.narratives import get_coach_narrative_by_name
from graphrag.planner import EntityBundle, SubQueryPlan, build_plan
from graphrag.retry import execute_with_retry
from graphrag.synthesizer import (
    ResultRow,
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
        narrative_used: ``True`` when the answer came from a precomputed
            F4b narrative rather than the live F4 pipeline.  The UI can use
            this to show a "precomputed" badge or skip re-rendering a graph.

    Note — ``confidence_flag`` passthrough:
        Each :class:`~graphrag.synthesizer.ResultRow` in
        ``response.result_rows`` carries a ``confidence_flag`` field
        (``"STANDARD"``, ``"REVIEW_REVERSE"``, ``"REVIEW_MUTUAL"``, or
        ``None``) sourced from the MENTORED edge that placed that coach in
        the result.  Non-STANDARD flags are also surfaced inline in each
        row's ``explanation`` string with the suffix
        ``"[relationship direction flagged for review]"``.
        The UI can inspect ``row.confidence_flag`` directly for richer
        rendering (e.g. an amber badge on flagged nodes in the Pyvis graph).
    """

    response: SynthesizedResponse
    intent: str
    root_name: str
    narrative_used: bool = field(default=False)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_mc_coach_code(root_name: str, driver: Driver) -> int | None:
    """Resolve a coach display name to a McIllece ``coach_code``.

    Uses the same dual-path lookup as :func:`~graphrag.narratives.get_coach_narrative_by_name`:

    1. CFBD ``Coach`` node matched by ``first_name`` + ``last_name``, then
       follows any ``SAME_PERSON`` edge to get the McIllece ``coach_code``.
    2. Falls back to a direct McIllece ``Coach`` node matched by the ``name``
       property — necessary on Railway where SAME_PERSON edges are not yet
       loaded.

    Args:
        root_name: Full display name (e.g. ``"Nick Saban"``).
        driver: Open Neo4j driver.

    Returns:
        Integer ``coach_code``, or ``None`` if not found.
    """
    parts = root_name.strip().split(None, 1)
    if len(parts) != 2:
        return None
    first, last = parts[0], parts[1]

    query = """
    OPTIONAL MATCH (cfbd:Coach {first_name: $first, last_name: $last})
    OPTIONAL MATCH (cfbd)-[:SAME_PERSON]->(mc_via_cfbd:Coach)
    WHERE mc_via_cfbd.coach_code IS NOT NULL
    OPTIONAL MATCH (mc_direct:Coach {name: $full_name})
    WHERE mc_direct.coach_code IS NOT NULL
    RETURN coalesce(mc_via_cfbd.coach_code, mc_direct.coach_code) AS mc_code
    LIMIT 1
    """
    with driver.session() as session:
        result = session.run(query, first=first, last=last, full_name=root_name.strip())
        record = result.single()

    if record is None:
        return None
    return record.get("mc_code")


def _fetch_direct_mentees(root_name: str, driver: Driver) -> list[ResultRow]:
    """Return HC coaching-tree rows (depth 1–2) for graph visualization.

    Resolves *root_name* to a McIllece ``coach_code`` via
    :func:`_resolve_mc_coach_code` (which handles the SAME_PERSON fallback
    to direct McIllece name lookup), then runs a ``max_depth=2``,
    ``role_filter="HC"`` MENTORED traversal — showing the root's direct
    HC mentees and their HC mentees one level deeper.

    Args:
        root_name: Display name of the root coach (e.g. ``"Nick Saban"``).
        driver: Open Neo4j driver.

    Returns:
        List of :class:`~graphrag.synthesizer.ResultRow` objects with
        ``depth`` 1 or 2.  Returns an empty list on any failure — never raises.
    """
    try:
        mc_code = _resolve_mc_coach_code(root_name, driver)
        if mc_code is None:
            logger.warning(
                "F4b graph: no mc_coach_code resolved for %r; skipping graph.",
                root_name,
            )
            return []

        raw_rows = _graph_traversal.get_coaching_tree(
            coach_code=mc_code,
            max_depth=2,
            role_filter="HC",
            driver=driver,
        )

        # Batch-fetch best role for each mentee coach_code.
        mentee_codes = [
            row.get("coach_code")
            for row in raw_rows
            if row.get("coach_code") is not None
        ]
        role_map = _graph_traversal.get_best_roles(mentee_codes, driver)

        # Build name → coach_code lookup so depth-2 nodes can reference
        # their mentor's coach_code for correct edge wiring.
        name_to_code: dict[str, int | str] = {}
        for row in raw_rows:
            rn = row.get("name") or ""
            rc = row.get("coach_code")
            if rn and rc is not None:
                name_to_code[rn] = rc

        # First pass: collect depth-1 coach codes so we can validate
        # depth-2 mentors are actually in the result set.
        depth1_codes: set[int | str] = set()
        for row in raw_rows:
            if int(row.get("depth", 0)) == 1:
                rc = row.get("coach_code")
                if rc is not None:
                    depth1_codes.add(rc)

        rows: list[ResultRow] = []
        seen: set[str] = set()
        for row in raw_rows:
            name: str = row.get("name") or ""
            depth = int(row.get("depth", 0))
            if not name or name in seen or depth < 1:
                continue

            cc = row.get("coach_code")
            path_coaches = row.get("path_coaches") or []
            mentor_name = path_coaches[-2] if len(path_coaches) >= 2 else root_name
            mentor_cc = name_to_code.get(mentor_name) if depth > 1 else None

            # Skip depth-2+ nodes whose mentor isn't in our depth-1 set.
            # This happens when the HC role_filter passes the leaf but the
            # intermediate node (e.g. an OC) was filtered out.
            if depth > 1 and (mentor_cc is None or mentor_cc not in depth1_codes):
                continue

            seen.add(name)
            explanation = (
                f"Direct mentee of {root_name}."
                if depth == 1
                else f"Depth-{depth} mentee (via {mentor_name})."
            )
            rows.append(
                ResultRow(
                    coach_id=cc,
                    display_name=name,
                    depth=depth,
                    explanation=explanation,
                    confidence_flag=row.get("confidence_flag") or None,
                    role=role_map.get(cc) if cc is not None else None,
                    mentor_coach_id=mentor_cc,
                )
            )

        logger.info(
            "F4b graph: fetched %d rows (depth 1–2, HC only) for %r (mc_code=%s).",
            len(rows),
            root_name,
            mc_code,
        )
        return rows

    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "F4b graph: traversal failed for %r (%s); skipping graph.", root_name, exc
        )
        return []


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

    # 2b. F4b precomputed narrative fast-path (TREE_QUERY only).
    #
    # For tree queries where the root coach has a manually reviewed narrative
    # stored in Neo4j, skip the full execute → retry → synthesize pipeline
    # and return the precomputed answer directly.  This saves LLM latency,
    # eliminates QA variance on high-traffic queries, and feeds Phase 1
    # content generation (A2) with stable, screenshot-ready output.
    #
    # Only fires when:
    #   - intent is TREE_QUERY (other intents always use the live pipeline)
    #   - root_name is non-empty (a coach entity was resolved)
    #   - a narrative property exists on the coach's Neo4j node
    if intent == "TREE_QUERY" and root_name:
        try:
            narrative = get_coach_narrative_by_name(root_name, driver=driver)
            if narrative:
                logger.info(
                    "F4b: returning precomputed narrative for %r (%d chars).",
                    root_name,
                    len(narrative),
                )
                # Fetch direct mentees (depth=1) for the graph visualization.
                # Uses a direct traversal rather than the full execute+synth
                # pipeline so the graph renders even when plan.ready is False
                # (e.g. Gemini returned coaches but no valid sub_queries).
                graph_rows: list[ResultRow] = _fetch_direct_mentees(
                    root_name, driver
                )
                return GraphRAGQueryResult(
                    response=SynthesizedResponse(
                        answer=narrative,
                        result_rows=graph_rows,
                        partial=False,
                        warnings=[],
                    ),
                    intent=intent,
                    root_name=root_name,
                    narrative_used=True,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "F4b narrative check failed for %r, falling back to pipeline: %s",
                root_name,
                exc,
            )

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
