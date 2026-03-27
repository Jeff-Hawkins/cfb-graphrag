"""Sub-query execution module for the GraphRAG pipeline.

Receives a :class:`~graphrag.planner.SubQueryPlan` from the planner,
topologically sorts sub-queries by dependency, and dispatches each to the
appropriate :mod:`graphrag.graph_traversal` function.  Results are collected
into an :class:`ExecutionResult` suitable for the synthesizer.

Pipeline position::

    classifier.py → planner.py → executor.py → synthesizer.py

Typical usage::

    from graphrag.executor import execute_plan

    result = execute_plan(plan, driver=driver)
    if result.ready_for_synthesis:
        # hand off to synthesizer …
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from neo4j import Driver

from graphrag import graph_traversal
from graphrag.entity_extractor import resolve_coach_entity
from graphrag.planner import SubQuery, SubQueryPlan, TraversalFn

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class ExecutionResult:
    """Structured result of executing a :class:`~graphrag.planner.SubQueryPlan`.

    Attributes:
        plan: The originating plan (preserved for tracing and F1 provenance).
        subquery_results: Mapping of sub-query ID → traversal result.
            Only sub-queries that executed successfully appear here.
        warnings: Non-fatal issues (skipped sub-queries, entity resolution
            fallbacks, plan-level warnings forwarded from the planner).
        errors: Per-sub-query error descriptions including sub-query ID and
            traversal function name for easy debugging.
        ready_for_synthesis: ``True`` only when all executed sub-queries
            succeeded and no cycle was detected.
    """

    plan: SubQueryPlan
    subquery_results: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    ready_for_synthesis: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _topological_sort(sub_queries: list[SubQuery]) -> tuple[list[SubQuery], bool]:
    """Kahn's algorithm to topologically sort sub-queries by ``depends_on``.

    Unknown dependency IDs (referencing sub-queries not in the plan) are
    silently ignored during the sort; they are caught at dispatch time.

    Args:
        sub_queries: Unordered list of sub-queries.

    Returns:
        Tuple of ``(sorted_list, cycle_detected)``.  If a cycle exists,
        ``cycle_detected`` is ``True`` and ``sorted_list`` contains only
        the sub-queries that could be resolved before the cycle.
    """
    id_to_sq = {sq.id: sq for sq in sub_queries}
    in_degree: dict[str, int] = {sq.id: 0 for sq in sub_queries}
    dependents: dict[str, list[str]] = {sq.id: [] for sq in sub_queries}

    for sq in sub_queries:
        for dep_id in sq.depends_on:
            if dep_id in in_degree:
                in_degree[sq.id] += 1
                dependents[dep_id].append(sq.id)

    queue: deque[str] = deque(
        sq_id for sq_id, deg in in_degree.items() if deg == 0
    )
    sorted_sqs: list[SubQuery] = []

    while queue:
        sq_id = queue.popleft()
        sorted_sqs.append(id_to_sq[sq_id])
        for downstream_id in dependents[sq_id]:
            in_degree[downstream_id] -= 1
            if in_degree[downstream_id] == 0:
                queue.append(downstream_id)

    cycle_detected = len(sorted_sqs) < len(sub_queries)
    return sorted_sqs, cycle_detected


def combine_results(
    subquery: SubQuery,
    subquery_results: dict[str, Any],
) -> dict[str, Any]:
    """Aggregate results from dependent sub-queries into a combined structure.

    Reads each ID listed in ``subquery.depends_on`` from ``subquery_results``
    and bundles them under a ``"sources"`` key.  The ``"strategy"`` param
    (``"compare"``, ``"merge"``, or ``"intersect"``) is forwarded unchanged for
    the synthesizer to act on.

    Args:
        subquery: The COMBINE sub-query describing which IDs to aggregate.
        subquery_results: Mapping of already-executed sub-query ID → result.

    Returns:
        Dict with ``strategy``, ``sources`` (dep_id → result), and optional
        ``year_start`` / ``year_end`` taken from the sub-query params.
    """
    strategy = subquery.params.get("strategy", "merge")
    sources = {
        dep_id: subquery_results.get(dep_id) for dep_id in subquery.depends_on
    }
    aggregate: dict[str, Any] = {"strategy": strategy, "sources": sources}
    if "year_start" in subquery.params:
        aggregate["year_start"] = subquery.params["year_start"]
    if "year_end" in subquery.params:
        aggregate["year_end"] = subquery.params["year_end"]
    return aggregate


def _dispatch(
    subquery: SubQuery,
    subquery_results: dict[str, Any],
    driver: Driver | None,
) -> Any:
    """Dispatch a single sub-query to the appropriate traversal function.

    For :attr:`~graphrag.planner.TraversalFn.GET_COACHING_TREE`, the
    ``coach_name`` param is resolved to a McIllece ``coach_code`` via
    :func:`~graphrag.entity_extractor.resolve_coach_entity` before the
    traversal is called.

    Args:
        subquery: The sub-query to execute.
        subquery_results: Already-executed results (needed only for COMBINE).
        driver: Open Neo4j driver.  Must not be ``None`` for any sub-query
            that performs a graph traversal.

    Returns:
        Traversal result (list or dict).

    Raises:
        RuntimeError: When ``driver`` is ``None`` for a traversal sub-query.
        ValueError: When entity resolution fails to find a ``mc_coach_code``.
        Any exception raised by the underlying traversal function propagates
        to the caller, which should catch it per-sub-query.
    """
    fn = subquery.traversal_fn
    params = subquery.params

    if fn == TraversalFn.COMBINE:
        return combine_results(subquery, subquery_results)

    if driver is None:
        raise RuntimeError(
            f"No Neo4j driver provided for traversal {fn!r} in {subquery.id}"
        )

    if fn == TraversalFn.GET_COACHING_TREE:
        coach_name = params.get("coach_name", "")
        resolved = resolve_coach_entity(coach_name, driver)
        mc_code = resolved.get("mc_coach_code")
        if mc_code is None:
            raise ValueError(
                f"Entity resolution failed for {coach_name!r}: no mc_coach_code found "
                f"(source={resolved.get('source')!r})"
            )
        return graph_traversal.get_coaching_tree(
            coach_code=mc_code,
            max_depth=params.get("max_depth", 4),
            driver=driver,
            role_filter=params.get("role_filter"),
        )

    if fn == TraversalFn.GET_COACH_TREE:
        return graph_traversal.get_coach_tree(
            driver=driver,
            coach_name=params.get("coach_name", ""),
        )

    if fn == TraversalFn.GET_COACHES_IN_CONFERENCES:
        return graph_traversal.get_coaches_in_conferences(
            driver=driver,
            conferences=params.get("conferences", []),
        )

    if fn == TraversalFn.SHORTEST_PATH_BETWEEN_COACHES:
        return graph_traversal.shortest_path_between_coaches(
            driver=driver,
            coach_a=params.get("coach_a", ""),
            coach_b=params.get("coach_b", ""),
        )

    raise ValueError(f"Unhandled TraversalFn: {fn!r}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def execute_plan(
    plan: SubQueryPlan,
    driver: Driver | None = None,
) -> ExecutionResult:
    """Execute a sub-query plan and return structured results.

    Topologically sorts sub-queries by their ``depends_on`` relationships,
    then dispatches each in dependency order.  Errors in one sub-query are
    recorded without halting independent sub-queries.

    Guarantees:
    - Never raises due to traversal exceptions, bad params, or malformed data.
    - Returns a fully populated :class:`ExecutionResult` in all cases.

    Args:
        plan: Plan produced by :func:`graphrag.planner.build_plan`.
        driver: Open Neo4j driver.  Required for any sub-query that performs
            a graph traversal; may be ``None`` when ``plan.ready`` is ``False``
            or the plan contains only virtual (COMBINE) sub-queries.

    Returns:
        An :class:`ExecutionResult`.  Check ``ready_for_synthesis`` before
        passing to the synthesizer — ``False`` means at least one error
        occurred or the plan itself was not ready.
    """
    result = ExecutionResult(plan=plan)

    # Short-circuit: plan not ready (missing entities or planner failure).
    if not plan.ready:
        result.warnings.extend(plan.warnings)
        result.ready_for_synthesis = False
        return result

    # Topological sort — detect cycles before any traversal.
    sorted_sqs, cycle = _topological_sort(plan.sub_queries)
    if cycle:
        resolved_ids = {sq.id for sq in sorted_sqs}
        cycle_ids = [sq.id for sq in plan.sub_queries if sq.id not in resolved_ids]
        result.errors.append(
            f"Cycle detected in sub-query dependencies; affected IDs: {cycle_ids}"
        )
        result.ready_for_synthesis = False
        return result

    errored_ids: set[str] = set()

    for subquery in sorted_sqs:
        # Skip if any dependency errored or has no result.
        failed_deps = [dep for dep in subquery.depends_on if dep in errored_ids]
        missing_deps = [
            dep
            for dep in subquery.depends_on
            if dep not in result.subquery_results and dep not in errored_ids
        ]

        if failed_deps:
            result.warnings.append(
                f"{subquery.id}: skipped — dependent sub-queries failed: {failed_deps}"
            )
            errored_ids.add(subquery.id)
            continue

        if missing_deps:
            result.warnings.append(
                f"{subquery.id}: skipped — dependent sub-queries have no result: {missing_deps}"
            )
            errored_ids.add(subquery.id)
            continue

        # Dispatch to traversal or combine helper.
        try:
            traversal_result = _dispatch(subquery, result.subquery_results, driver)
            result.subquery_results[subquery.id] = traversal_result
            logger.info(
                "Executor: %s (%s) succeeded", subquery.id, subquery.traversal_fn
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Executor: %s (%s) failed — %s",
                subquery.id,
                subquery.traversal_fn,
                exc,
            )
            result.errors.append(f"{subquery.id} ({subquery.traversal_fn}): {exc}")
            errored_ids.add(subquery.id)

    result.ready_for_synthesis = len(result.errors) == 0
    return result
