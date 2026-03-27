"""Response synthesizer for the GraphRAG pipeline.

Takes the execution results from executor.py (and optional retry metadata
from retry.py) and produces:

1. A primary natural-language answer string focused on clarity and
   provenance rather than marketing copy.
2. A structured list of typed result rows, each carrying an
   *Explain My Result* (F1) provenance string.

Pipeline position::

    classifier.py → planner.py → executor.py → retry.py → synthesizer.py

Typical usage::

    from graphrag.synthesizer import SynthesisInput, synthesize_response

    synthesis_in = SynthesisInput(plan=plan, execution_result=result)
    response = synthesize_response(synthesis_in)
    print(response.answer)
    for row in response.result_rows:
        print(row.display_name, "—", row.explanation)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from graphrag.executor import ExecutionResult
from graphrag.planner import SubQueryPlan, TraversalFn

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Output types
# ---------------------------------------------------------------------------


@dataclass
class ResultRow:
    """A single result item with an F1-style provenance explanation.

    Attributes:
        coach_id: Unique identifier for the coach.  Typically the McIllece
            ``coach_code`` (int) for GET_COACHING_TREE results, or ``None``
            for CFBD-based GET_COACH_TREE results.
        display_name: Human-readable coach name for rendering in the UI.
        depth: Hop distance from the root coach in the coaching tree.
            ``1`` means a direct mentee; higher values mean further removed.
            Set to ``0`` for results where depth is not intrinsically
            available (e.g. shortest-path or conference queries).
        explanation: F1-style provenance string.
            Example: ``"Included because: direct mentee in coaching tree
            (mentored by Nick Saban)."``
            When the inbound MENTORED edge has ``confidence_flag != 'STANDARD'``
            the string ends with ``" [relationship direction flagged for review]"``.
        confidence_flag: Raw ``confidence_flag`` value from the MENTORED edge
            that placed this coach in the result (``"STANDARD"``,
            ``"REVIEW_REVERSE"``, ``"REVIEW_MUTUAL"``, or ``None`` when
            the migration has not yet run).  ``None`` is treated as
            ``"STANDARD"`` for display purposes.
        role: Role abbreviation (``"HC"``, ``"OC"``, ``"DC"``, ``"POS"``,
            etc.) derived from the mentee's highest-priority
            ``mcillece_roles`` COACHED_AT edge.  ``None`` when role data
            is not available — the UI defaults to ``"HC"`` in that case.
        mentor_coach_id: ``coach_id`` of this coach's direct mentor in
            the tree (the node one hop closer to the root).  Used by
            the graph component to wire edges to the correct parent.
            ``None`` for depth-1 nodes (parent is always the root).
    """

    coach_id: int | str | None
    display_name: str
    depth: int
    explanation: str
    confidence_flag: str | None = None
    role: str | None = None
    mentor_coach_id: int | str | None = None


@dataclass
class SynthesizedResponse:
    """Structured output from :func:`synthesize_response`.

    Attributes:
        answer: Primary natural-language answer paragraph — plain text,
            focused on clarity and provenance.
        result_rows: Per-coach (or per-result) items with F1 provenance
            strings.  May be empty when all sub-queries returned no data.
        partial: ``True`` when at least one sub-query failed and the answer
            is based on incomplete data.  The answer string includes a note.
        warnings: Non-fatal issues forwarded from the plan, execution
            result, retry metadata, and synthesis logic.
    """

    answer: str
    result_rows: list[ResultRow] = field(default_factory=list)
    partial: bool = False
    warnings: list[str] = field(default_factory=list)


@dataclass
class SynthesisInput:
    """All inputs needed by :func:`synthesize_response`.

    Attributes:
        plan: :class:`~graphrag.planner.SubQueryPlan` from the planner,
            preserved for intent and entity context used in the narrative.
        execution_result: Result from
            :func:`~graphrag.executor.execute_plan` or
            :func:`~graphrag.retry.execute_with_retry`.
        retry_outcome: Optional :class:`~graphrag.retry.RetryOutcome` from
            retry.py; when present, retry metadata is surfaced in warnings.
            Typed as ``Any`` to avoid a circular import — the synthesizer
            accesses only ``retries_attempted`` and ``strategies_fired``.
    """

    plan: SubQueryPlan
    execution_result: ExecutionResult
    retry_outcome: Any | None = None


# ---------------------------------------------------------------------------
# Internal helpers — per-format explanation builders
# ---------------------------------------------------------------------------


def _explain_coaching_tree_row(row: dict[str, Any], root_name: str) -> str:
    """Build an F1-style explanation for a GET_COACHING_TREE result row.

    Produces a rich explanation when COACHED_AT metadata is present in the
    row, falling back to a simpler depth-based string when it is not.

    **Rich format** (when ``role`` or ``team`` is present)::

        "Included because: OC at Alabama (2019–22), coached under Nick Saban."
        "Included because: OC at Alabama (2019–22), coached under Nick Saban, produced 2 Day 1 picks."

    **Fallback format** (when no COACHED_AT fields are present)::

        "Included because: direct mentee in coaching tree (mentored by Nick Saban)."
        "Included because: depth-2 mentee in coaching tree (mentored by Kirby Smart)."

    Args:
        row: Dict from :func:`~graphrag.graph_traversal.get_coaching_tree`,
            with required keys ``depth`` and ``path_coaches``, plus these
            optional COACHED_AT enrichment keys:

            - ``role``       — role abbreviation (e.g. ``"OC"``).
            - ``team``       — school name (e.g. ``"Alabama"``).
            - ``start_year`` — first season year as int.
            - ``end_year``   — last season year as int.
            - ``draft_info`` — free-text draft note, appended when present
              (e.g. ``"produced 2 Day 1 picks"``).
        root_name: Display name of the root coach (used when ``path_coaches``
            has fewer than 2 entries).

    Returns:
        An explanation string following the F1 shape.  Never raises.
    """
    depth: int = row.get("depth", 1)
    path_coaches: list[str] = row.get("path_coaches") or []

    # Direct mentor is the second-to-last node in path (last node is the mentee).
    mentor = path_coaches[-2] if len(path_coaches) >= 2 else root_name

    # Optional COACHED_AT enrichment fields.
    role: str | None = row.get("role") or None
    team: str | None = row.get("team") or None
    start_year: int | None = row.get("start_year")
    end_year: int | None = row.get("end_year")
    draft_info: str | None = row.get("draft_info") or None

    # confidence_flag from the MENTORED edge — non-STANDARD edges get a note.
    confidence_flag: str | None = row.get("confidence_flag") or None
    _flagged = confidence_flag not in (None, "STANDARD")

    if role or team:
        # Build year-range string using sports-notation abbreviation when
        # both endpoints share the same century (e.g. 2019–22).
        year_str = ""
        if start_year is not None and end_year is not None:
            if end_year // 100 == start_year // 100:
                year_str = f" ({start_year}–{str(end_year)[-2:]})"
            else:
                year_str = f" ({start_year}–{end_year})"
        elif start_year is not None:
            year_str = f" ({start_year})"

        if role and team:
            location_part = f"{role} at {team}{year_str}"
        elif role:
            location_part = f"{role}{year_str}"
        else:
            location_part = f"at {team}{year_str}"

        parts = [location_part, f"coached under {mentor}"]
        if draft_info:
            parts.append(draft_info)
        explanation = "Included because: " + ", ".join(parts) + "."
        if _flagged:
            explanation += " [relationship direction flagged for review]"
        return explanation

    # No COACHED_AT context available — fall back to depth-based explanation.
    hop_label = "direct mentee" if depth == 1 else f"depth-{depth} mentee"
    explanation = (
        f"Included because: {hop_label} in coaching tree (mentored by {mentor})."
    )
    if _flagged:
        explanation += " [relationship direction flagged for review]"
    return explanation


def _explain_coach_tree_row(row: dict[str, Any]) -> str:
    """Build an F1-style explanation for a GET_COACH_TREE (CFBD) result row.

    Args:
        row: Dict with keys ``root``, ``protege``, ``team``, and ``years``
            from :func:`~graphrag.graph_traversal.get_coach_tree`.

    Returns:
        An explanation string following the F1 shape.
    """
    root: str = row.get("root") or "unknown coach"
    team: str = row.get("team") or "an unknown program"
    years = row.get("years")
    year_str = f" ({years})" if years is not None else ""
    return (
        f"Included because: coached with {root} at {team}{year_str} "
        f"(CFBD coaching overlap)."
    )


def _rows_from_coaching_tree(
    sq_result: list[dict[str, Any]],
    root_name: str,
) -> list[ResultRow]:
    """Convert GET_COACHING_TREE results into :class:`ResultRow` objects.

    Deduplicates by display name — the same coach appearing at multiple depths
    is included only at their shallowest depth.

    Args:
        sq_result: Raw list from
            :func:`~graphrag.graph_traversal.get_coaching_tree`.
        root_name: Display name of the root coach for explanation context.

    Returns:
        List of :class:`ResultRow` objects, one per unique mentee.
    """
    rows: list[ResultRow] = []
    seen: set[str] = set()
    for row in sq_result:
        name: str = row.get("name") or ""
        if not name or name in seen:
            continue
        seen.add(name)
        rows.append(
            ResultRow(
                coach_id=row.get("coach_code"),
                display_name=name,
                depth=int(row.get("depth", 1)),
                explanation=_explain_coaching_tree_row(row, root_name),
                confidence_flag=row.get("confidence_flag") or None,
                role=row.get("role") or None,
            )
        )
    return rows


def _rows_from_coach_tree(sq_result: list[dict[str, Any]]) -> list[ResultRow]:
    """Convert GET_COACH_TREE (CFBD) results into :class:`ResultRow` objects.

    Deduplicates by protege name — one row per unique protege coach.

    Args:
        sq_result: Raw list from
            :func:`~graphrag.graph_traversal.get_coach_tree`.

    Returns:
        List of :class:`ResultRow` objects, one per unique protege.
    """
    rows: list[ResultRow] = []
    seen: set[str] = set()
    for row in sq_result:
        protege: str = row.get("protege") or ""
        if not protege or protege in seen:
            continue
        seen.add(protege)
        rows.append(
            ResultRow(
                coach_id=None,
                display_name=protege,
                depth=1,
                explanation=_explain_coach_tree_row(row),
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Internal helper — primary answer string
# ---------------------------------------------------------------------------


def _build_answer(
    plan: SubQueryPlan,
    result_rows: list[ResultRow],
    partial: bool,
    execution_result: ExecutionResult,
) -> str:
    """Build the primary answer string for the synthesis response.

    Args:
        plan: The originating :class:`~graphrag.planner.SubQueryPlan` for
            intent and entity context.
        result_rows: Assembled result rows (may be empty).
        partial: ``True`` when some sub-queries failed.
        execution_result: Used to count errors in the partial note.

    Returns:
        A plain-text answer string.
    """
    intent = plan.intent
    coaches = plan.entities.coaches
    root_name = coaches[0] if coaches else "the requested coach"
    count = len(result_rows)

    partial_note = (
        f"  (Note: results are partial — "
        f"{len(execution_result.errors)} sub-query error(s).)"
        if partial
        else ""
    )

    if intent == "TREE_QUERY":
        if count == 0:
            return (
                f"No coaches were found in {root_name}'s coaching tree "
                f"with the current query parameters.{partial_note}"
            )
        unique_depths = sorted({r.depth for r in result_rows})
        depth_range = (
            f"depth {unique_depths[0]}–{unique_depths[-1]}"
            if len(unique_depths) > 1
            else f"depth {unique_depths[0]}"
        )
        return (
            f"Found {count} coach{'es' if count != 1 else ''} in "
            f"{root_name}'s coaching tree ({depth_range}).{partial_note}"
        )

    if intent == "PERFORMANCE_COMPARE":
        coach_list = ", ".join(coaches) if coaches else "the requested coaches"
        if count == 0:
            return f"No coaching overlap data found for {coach_list}.{partial_note}"
        return (
            f"Found {count} coaching connection{'s' if count != 1 else ''} "
            f"across {coach_list}'s trees.{partial_note}"
        )

    if intent == "SIMILARITY":
        if count == 0:
            return (
                f"No path found between "
                f"{', '.join(coaches) if coaches else 'the requested coaches'}.{partial_note}"
            )
        return (
            f"Found path data between "
            f"{', '.join(coaches) if coaches else 'the requested coaches'} "
            f"({count} result{'s' if count != 1 else ''}).{partial_note}"
        )

    # Generic fallback for PIPELINE_QUERY / CHANGE_IMPACT.
    if count == 0:
        return f"No results found for the query.{partial_note}"
    return (
        f"Found {count} result{'s' if count != 1 else ''} for the query.{partial_note}"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def synthesize_response(synthesis_input: SynthesisInput) -> SynthesizedResponse:
    """Synthesize a structured response from execution results.

    Converts raw sub-query data in an :class:`~graphrag.executor.ExecutionResult`
    into a natural-language answer and a list of typed :class:`ResultRow`
    objects, each carrying an *Explain My Result* (F1) provenance string.

    Degrades gracefully when sub-queries partially failed: rows from
    successful sub-queries are still returned with ``partial=True`` and a
    note in the answer string.

    Current support:

    - ``TREE_QUERY`` — handles both GET_COACHING_TREE (McIllece MENTORED
      edges) and GET_COACH_TREE (CFBD overlap) result formats.
    - ``PERFORMANCE_COMPARE`` — collects rows from each source sub-query
      inside a COMBINE result.
    - ``SIMILARITY`` — surfaces shortest-path rows with path-string explanations.
    - ``PIPELINE_QUERY`` / ``CHANGE_IMPACT`` — generic row collection from
      GET_COACHES_IN_CONFERENCES and GET_COACH_TREE results.

    Args:
        synthesis_input: :class:`SynthesisInput` bundling the plan,
            execution result, and optional retry metadata.

    Returns:
        :class:`SynthesizedResponse` — never raises; returns a partial
        response with warnings on unexpected data shapes.
    """
    plan = synthesis_input.plan
    exec_result = synthesis_input.execution_result
    retry_outcome = synthesis_input.retry_outcome

    partial = bool(exec_result.errors)
    all_warnings: list[str] = list(exec_result.warnings)

    # Surface retry metadata as a warning.
    if retry_outcome is not None:
        retries = getattr(retry_outcome, "retries_attempted", 0)
        if retries > 0:
            fired = getattr(retry_outcome, "strategies_fired", [])
            all_warnings.append(
                f"Retry: {retries} attempt(s) fired ({', '.join(fired)})."
            )

    result_rows: list[ResultRow] = []
    root_name = (
        plan.entities.coaches[0] if plan.entities.coaches else "the requested coach"
    )

    for sq in plan.sub_queries:
        sq_result = exec_result.subquery_results.get(sq.id)
        if sq_result is None:
            continue

        fn = sq.traversal_fn

        try:
            if fn == TraversalFn.GET_COACHING_TREE:
                result_rows.extend(_rows_from_coaching_tree(sq_result, root_name))

            elif fn == TraversalFn.GET_COACH_TREE:
                result_rows.extend(_rows_from_coach_tree(sq_result))

            elif fn == TraversalFn.COMBINE:
                # PERFORMANCE_COMPARE: pull rows from each source sub-query.
                sources: dict[str, Any] = sq_result.get("sources", {})
                for source_id, source_result in sources.items():
                    if not isinstance(source_result, list):
                        continue
                    source_sq = next(
                        (s for s in plan.sub_queries if s.id == source_id), None
                    )
                    if source_sq is None:
                        continue
                    if source_sq.traversal_fn == TraversalFn.GET_COACHING_TREE:
                        result_rows.extend(
                            _rows_from_coaching_tree(source_result, root_name)
                        )
                    elif source_sq.traversal_fn == TraversalFn.GET_COACH_TREE:
                        result_rows.extend(_rows_from_coach_tree(source_result))

            elif fn == TraversalFn.SHORTEST_PATH_BETWEEN_COACHES:
                if isinstance(sq_result, list):
                    for path_row in sq_result:
                        hops = path_row.get("hops", 0)
                        path_nodes: list[Any] = path_row.get("path_nodes", [])
                        path_str = " → ".join(str(n) for n in path_nodes)
                        result_rows.append(
                            ResultRow(
                                coach_id=None,
                                display_name=path_str,
                                depth=0,
                                explanation=(
                                    f"Included because: shortest path "
                                    f"({hops} hops): {path_str}."
                                ),
                            )
                        )

            elif fn == TraversalFn.GET_COACHES_IN_CONFERENCES:
                if isinstance(sq_result, list):
                    for conf_row in sq_result:
                        name: str = conf_row.get("coach") or ""
                        if not name:
                            continue
                        confs: list[str] = conf_row.get("conferences") or []
                        conf_str = ", ".join(confs) if confs else "multiple conferences"
                        result_rows.append(
                            ResultRow(
                                coach_id=None,
                                display_name=name,
                                depth=0,
                                explanation=(
                                    f"Included because: coached in {conf_str}."
                                ),
                            )
                        )

        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Synthesizer: failed to process result for %s (%s): %s",
                sq.id,
                fn,
                exc,
            )
            all_warnings.append(f"Synthesizer: skipped {sq.id} ({fn}) — {exc}")

    answer = _build_answer(plan, result_rows, partial, exec_result)

    return SynthesizedResponse(
        answer=answer,
        result_rows=result_rows,
        partial=partial,
        warnings=all_warnings,
    )
