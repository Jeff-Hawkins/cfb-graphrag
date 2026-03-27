"""Retry strategies for the GraphRAG execution layer.

Sits between executor.py and synthesizer.py.  When execute_plan returns
errors or empty results that indicate a recoverable condition, retry
strategies produce a modified :class:`~graphrag.planner.SubQueryPlan` and
re-execute.

Pipeline position::

    classifier.py → planner.py → executor.py → retry.py → synthesizer.py

Typical usage::

    from graphrag.retry import execute_with_retry

    outcome = execute_with_retry(plan, driver=driver)
    if outcome.final_result.ready_for_synthesis:
        # hand off to synthesizer …
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from neo4j import Driver

from graphrag.executor import ExecutionResult, execute_plan
from graphrag.planner import SubQuery, SubQueryPlan, TraversalFn

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# RetryOutcome — carries final result + metadata
# ---------------------------------------------------------------------------


@dataclass
class RetryOutcome:
    """Result of :func:`execute_with_retry`, bundling the final execution
    result and metadata about which retry strategies fired.

    Attributes:
        final_result: The last :class:`~graphrag.executor.ExecutionResult`
            produced (either the original or the last retried one).
        retries_attempted: Number of retry attempts that were made (≥ 0).
            Zero means the original execute_plan result was used unchanged.
        strategies_fired: Names of strategies that produced a modified plan,
            in the order they were applied.
    """

    final_result: ExecutionResult
    retries_attempted: int = 0
    strategies_fired: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# RetryStrategy protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class RetryStrategy(Protocol):
    """Protocol for retry strategy implementations.

    A strategy is responsible for:

    1. Deciding whether it applies to the current failure mode via
       :meth:`should_apply`.
    2. Producing a modified :class:`~graphrag.planner.SubQueryPlan` to
       retry via :meth:`apply`.  Returns ``None`` when no modification is
       possible (e.g. max_depth already at minimum, no matching sub-queries).
    """

    name: str

    def should_apply(self, plan: SubQueryPlan, result: ExecutionResult) -> bool:
        """Return ``True`` if this strategy should be attempted.

        Args:
            plan: The current plan being evaluated.
            result: The :class:`~graphrag.executor.ExecutionResult` to inspect.

        Returns:
            bool: ``True`` when the strategy is applicable.
        """
        ...

    def apply(self, plan: SubQueryPlan) -> SubQueryPlan | None:
        """Return a modified plan for retry, or ``None`` when not applicable.

        Args:
            plan: The plan to modify.

        Returns:
            A new :class:`~graphrag.planner.SubQueryPlan`, or ``None`` if the
            strategy cannot produce a meaningful modification.
        """
        ...


# ---------------------------------------------------------------------------
# Strategy 1 — ReduceDepthStrategy
# ---------------------------------------------------------------------------


class ReduceDepthStrategy:
    """Reduce ``max_depth`` by 1 on GET_COACHING_TREE sub-queries.

    Applies when the executor reports an error that suggests the traversal
    returned too many results or timed out.  Recognised error signals:
    ``"timeout"``, ``"too large"``, ``"too many"``, ``"result size"``.

    Requires at least one GET_COACHING_TREE sub-query with ``max_depth > 1``.
    The depth floor is 1 — the strategy will not reduce below 1.
    """

    name: str = "reduce_depth"

    _ERROR_SIGNALS: frozenset[str] = frozenset(
        {"timeout", "too large", "too many", "result size"}
    )

    def should_apply(self, plan: SubQueryPlan, result: ExecutionResult) -> bool:
        """True when at least one error looks like an over-scope traversal.

        Args:
            plan: The current plan being evaluated.
            result: The :class:`~graphrag.executor.ExecutionResult` to inspect.

        Returns:
            bool: ``True`` when an over-scope error signal is present and the
            plan has a reducible GET_COACHING_TREE sub-query.
        """
        has_oversize_error = any(
            any(sig in e.lower() for sig in self._ERROR_SIGNALS) for e in result.errors
        )
        if not has_oversize_error:
            return False
        return any(
            sq.traversal_fn == TraversalFn.GET_COACHING_TREE
            and sq.params.get("max_depth", 4) > 1
            for sq in plan.sub_queries
        )

    def apply(self, plan: SubQueryPlan) -> SubQueryPlan | None:
        """Return a copy of ``plan`` with ``max_depth`` reduced by 1.

        Args:
            plan: The plan to modify.

        Returns:
            A new :class:`~graphrag.planner.SubQueryPlan` with a reduced
            ``max_depth``, or ``None`` if no sub-query was reducible.
        """
        new_sqs: list[SubQuery] = []
        modified = False

        for sq in plan.sub_queries:
            if sq.traversal_fn == TraversalFn.GET_COACHING_TREE:
                current = sq.params.get("max_depth", 4)
                if current > 1:
                    new_params = {**sq.params, "max_depth": current - 1}
                    new_sqs.append(
                        SubQuery(
                            id=sq.id,
                            traversal_fn=sq.traversal_fn,
                            params=new_params,
                            depends_on=list(sq.depends_on),
                            description=(
                                f"{sq.description} "
                                f"[depth reduced {current}→{current - 1}]"
                            ).strip(),
                        )
                    )
                    modified = True
                    continue
            new_sqs.append(sq)

        if not modified:
            return None

        return SubQueryPlan(
            intent=plan.intent,
            confidence=plan.confidence,
            question=plan.question,
            entities=plan.entities,
            sub_queries=new_sqs,
            ready=plan.ready,
            warnings=list(plan.warnings)
            + [f"{self.name}: max_depth reduced by 1 (retry)"],
        )


# ---------------------------------------------------------------------------
# Strategy 2 — FallbackTraversalStrategy
# ---------------------------------------------------------------------------


class FallbackTraversalStrategy:
    """Switch GET_COACHING_TREE → GET_COACH_TREE when tree results are empty.

    Applies when:

    - The plan has at least one coach entity (so the fallback has a name to use).
    - At least one GET_COACHING_TREE sub-query either:

      - Produced an empty result list (executed without error but found no
        mentees in the MENTORED edge set), OR
      - Errored (e.g. entity resolution failure — ``mc_coach_code`` not found).

    GET_COACH_TREE uses CFBD COACHED_AT tenure overlap rather than McIllece
    MENTORED edges, making it a useful fallback when MENTORED edge coverage is
    sparse for the requested coach.
    """

    name: str = "fallback_traversal"

    def should_apply(self, plan: SubQueryPlan, result: ExecutionResult) -> bool:
        """True when a GET_COACHING_TREE sub-query returned empty or errored.

        Args:
            plan: The current plan being evaluated.
            result: The :class:`~graphrag.executor.ExecutionResult` to inspect.

        Returns:
            bool: ``True`` when the fallback is warranted.
        """
        if not plan.entities.coaches:
            return False

        for sq in plan.sub_queries:
            if sq.traversal_fn != TraversalFn.GET_COACHING_TREE:
                continue
            sq_result = result.subquery_results.get(sq.id)
            # Empty result list — tree query ran but found no mentees.
            if (
                sq_result is not None
                and isinstance(sq_result, list)
                and len(sq_result) == 0
            ):
                return True
            # Sub-query error (entity resolution failure, connection error, etc.).
            if any(sq.id in e for e in result.errors):
                return True

        return False

    def apply(self, plan: SubQueryPlan) -> SubQueryPlan | None:
        """Return a copy of ``plan`` with GET_COACHING_TREE swapped to GET_COACH_TREE.

        Args:
            plan: The plan to modify.

        Returns:
            A new :class:`~graphrag.planner.SubQueryPlan` using
            ``GET_COACH_TREE``, or ``None`` if no sub-query was swappable.
        """
        new_sqs: list[SubQuery] = []
        modified = False

        for sq in plan.sub_queries:
            if sq.traversal_fn == TraversalFn.GET_COACHING_TREE:
                coach_name = sq.params.get("coach_name", "")
                new_sqs.append(
                    SubQuery(
                        id=sq.id,
                        traversal_fn=TraversalFn.GET_COACH_TREE,
                        params={"coach_name": coach_name},
                        depends_on=list(sq.depends_on),
                        description=(
                            f"{sq.description} [fallback: GET_COACH_TREE]"
                        ).strip(),
                    )
                )
                modified = True
            else:
                new_sqs.append(sq)

        if not modified:
            return None

        return SubQueryPlan(
            intent=plan.intent,
            confidence=plan.confidence,
            question=plan.question,
            entities=plan.entities,
            sub_queries=new_sqs,
            ready=plan.ready,
            warnings=list(plan.warnings)
            + [f"{self.name}: switched to GET_COACH_TREE (retry)"],
        )


# ---------------------------------------------------------------------------
# Strategy 3 — LimitRoleFilterStrategy
# ---------------------------------------------------------------------------


class LimitRoleFilterStrategy:
    """Relax an overly-strict ``role_filter`` when a tree query returns empty.

    Applies when:

    - At least one GET_COACHING_TREE sub-query has a non-empty ``role_filter``
      parameter (e.g. ``"HC"``).
    - That sub-query's result is an empty list — the traversal ran successfully
      but found no mentees matching the role constraint.

    **Conservative trigger**: the strategy only fires on a completely empty
    result (zero rows), never on a small-but-non-zero result.  This avoids
    silently broadening the query when the user's intent included the role
    constraint and the data returned partial matches.

    Behaviour: produces a new plan variant where ``role_filter`` is removed
    from the affected sub-query params.  The modified plan is annotated in
    ``warnings`` so retry metadata surfaces cleanly in logs and
    :class:`~graphrag.synthesizer.SynthesizedResponse` warnings.
    """

    name: str = "limit_role_filter"

    def should_apply(self, plan: SubQueryPlan, result: ExecutionResult) -> bool:
        """Return ``True`` when a role-filtered tree query returned empty.

        Args:
            plan: The current plan being evaluated.
            result: The :class:`~graphrag.executor.ExecutionResult` to inspect.

        Returns:
            bool: ``True`` only when a GET_COACHING_TREE sub-query has a
            non-empty ``role_filter`` **and** its result was an empty list.
        """
        for sq in plan.sub_queries:
            if sq.traversal_fn != TraversalFn.GET_COACHING_TREE:
                continue
            role_filter = sq.params.get("role_filter")
            if not role_filter:
                continue
            sq_result = result.subquery_results.get(sq.id)
            # Fire only on a confirmed empty result list — not on errors or
            # missing results (FallbackTraversalStrategy covers those).
            if (
                sq_result is not None
                and isinstance(sq_result, list)
                and len(sq_result) == 0
            ):
                return True
        return False

    def apply(self, plan: SubQueryPlan) -> SubQueryPlan | None:
        """Return a copy of ``plan`` with ``role_filter`` removed.

        Args:
            plan: The plan to modify.

        Returns:
            A new :class:`~graphrag.planner.SubQueryPlan` without
            ``role_filter`` on GET_COACHING_TREE sub-queries, or ``None``
            if no qualifying sub-query was found.
        """
        new_sqs: list[SubQuery] = []
        modified = False

        for sq in plan.sub_queries:
            if sq.traversal_fn == TraversalFn.GET_COACHING_TREE and sq.params.get(
                "role_filter"
            ):
                new_params = {k: v for k, v in sq.params.items() if k != "role_filter"}
                new_sqs.append(
                    SubQuery(
                        id=sq.id,
                        traversal_fn=sq.traversal_fn,
                        params=new_params,
                        depends_on=list(sq.depends_on),
                        description=(f"{sq.description} [role_filter relaxed]").strip(),
                    )
                )
                modified = True
            else:
                new_sqs.append(sq)

        if not modified:
            return None

        return SubQueryPlan(
            intent=plan.intent,
            confidence=plan.confidence,
            question=plan.question,
            entities=plan.entities,
            sub_queries=new_sqs,
            ready=plan.ready,
            warnings=list(plan.warnings)
            + [f"{self.name}: role_filter relaxed (retry)"],
        )


# ---------------------------------------------------------------------------
# Default strategy list and helpers
# ---------------------------------------------------------------------------

_DEFAULT_STRATEGIES: list[
    ReduceDepthStrategy | LimitRoleFilterStrategy | FallbackTraversalStrategy
] = [
    ReduceDepthStrategy(),
    LimitRoleFilterStrategy(),
    FallbackTraversalStrategy(),
]


def _has_nonempty_results(result: ExecutionResult) -> bool:
    """Return ``True`` if at least one sub-query produced non-empty results.

    Args:
        result: The :class:`~graphrag.executor.ExecutionResult` to inspect.

    Returns:
        bool: ``True`` when any value in ``subquery_results`` is a non-empty
        list or dict (or any non-None scalar).
    """
    return any(
        v is not None and (not isinstance(v, (list, dict)) or len(v) > 0)
        for v in result.subquery_results.values()
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def execute_with_retry(
    plan: SubQueryPlan,
    driver: Driver | None = None,
    max_retries: int = 2,
    strategies: (
        list[ReduceDepthStrategy | LimitRoleFilterStrategy | FallbackTraversalStrategy]
        | None
    ) = None,
) -> RetryOutcome:
    """Execute a plan with automatic retry on detected failure conditions.

    First runs :func:`~graphrag.executor.execute_plan` on the original plan.
    If the result has errors or empty results that a strategy can address,
    that strategy produces a modified plan and the executor runs again.
    Retries are bounded by ``max_retries``; the loop exits early as soon as
    the result is ready for synthesis *and* non-empty, or no strategy applies.

    Guarantees:
    - Never raises — all exceptions from execute_plan are caught internally.
    - Returns a :class:`RetryOutcome` in all cases.

    Args:
        plan: Plan produced by :func:`graphrag.planner.build_plan`.
        driver: Open Neo4j driver.  Required for graph traversals.
        max_retries: Maximum number of retry attempts (default 2).
        strategies: List of strategy objects applied in priority order.
            Defaults to ``[ReduceDepthStrategy(), FallbackTraversalStrategy()]``.

    Returns:
        :class:`RetryOutcome` with the final result and retry metadata.
        Check ``outcome.final_result.ready_for_synthesis`` before passing
        to the synthesizer.
    """
    if strategies is None:
        strategies = _DEFAULT_STRATEGIES

    outcome = RetryOutcome(final_result=execute_plan(plan, driver=driver))
    current_plan = plan

    for attempt in range(max_retries):
        result = outcome.final_result
        if result.ready_for_synthesis and _has_nonempty_results(result):
            logger.debug(
                "Retry: result is ready and non-empty after attempt %d", attempt
            )
            break

        modified_plan: SubQueryPlan | None = None
        fired_name: str | None = None

        for strategy in strategies:
            if strategy.should_apply(current_plan, result):
                candidate = strategy.apply(current_plan)
                if candidate is not None:
                    modified_plan = candidate
                    fired_name = strategy.name
                    break

        if modified_plan is None:
            logger.debug(
                "Retry: no applicable strategy after attempt %d; giving up", attempt
            )
            break

        logger.info(
            "Retry: applying %s (attempt %d/%d)",
            fired_name,
            attempt + 1,
            max_retries,
        )
        outcome.final_result = execute_plan(modified_plan, driver=driver)
        outcome.retries_attempted += 1
        outcome.strategies_fired.append(fired_name)  # type: ignore[arg-type]
        current_plan = modified_plan

    return outcome
