"""F2 preset runner — loads YAML query templates and executes them against Neo4j.

Each preset is a YAML file in this directory.  Two result types are supported:

- ``tree``: resolves the ``coach_name`` parameter to a McIllece coach_code and
  runs a depth-1/2 HC MENTORED traversal.  Returns a
  :class:`~graphrag.retriever.GraphRAGQueryResult` that drops directly into the
  existing vis.js ``render_coaching_tree()`` path.

- ``table``: runs the ``cypher_template`` verbatim against Neo4j with the
  supplied parameters.  Returns rows as a list of dicts plus a column spec for
  ``st.dataframe`` rendering.

Usage::

    from presets.runner import load_presets, run_preset

    presets = load_presets()
    result = run_preset(presets[0], params={"coach_name": "Nick Saban"}, driver=driver)
    if result.result_type == "tree":
        render_coaching_tree(result.grag_result)
    else:
        st.dataframe(result.rows)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from neo4j import Driver

from graphrag import graph_traversal as _gt
from graphrag.retriever import GraphRAGQueryResult
from graphrag.synthesizer import ResultRow, SynthesizedResponse

logger = logging.getLogger(__name__)

_PRESETS_DIR = Path(__file__).parent


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------


@dataclass
class PresetResult:
    """Result from :func:`run_preset`.

    Attributes:
        result_type: ``"tree"`` or ``"table"``.
        preset_id: YAML ``id`` field, e.g. ``"coaching_tree"``.
        preset_name: Human-readable name for UI display.
        grag_result: Populated for ``result_type == "tree"`` — pass directly
            to ``render_coaching_tree()``.
        root_name: Root coach display name; set for tree results.
        columns: Column spec list ``[{key, label}, ...]`` for table rendering.
        rows: Raw result rows as dicts for table rendering.
        answer: Short summary sentence for both result types.
        error: Non-empty when the preset execution failed.
    """

    result_type: str
    preset_id: str
    preset_name: str
    grag_result: GraphRAGQueryResult | None = None
    root_name: str = ""
    columns: list[dict] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)
    answer: str = ""
    error: str = ""


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_presets() -> list[dict]:
    """Return all preset dicts loaded from YAML files in this directory.

    Files are sorted alphabetically so the order is deterministic.

    Returns:
        List of preset dicts, each containing at minimum ``id``, ``name``,
        ``segment``, ``result_type``, and ``parameters``.
    """
    presets: list[dict] = []
    for path in sorted(_PRESETS_DIR.glob("*.yaml")):
        with path.open(encoding="utf-8") as fh:
            preset = yaml.safe_load(fh)
        presets.append(preset)
    return presets


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_coach_code(coach_name: str, driver: Driver) -> int | None:
    """Resolve a display name to a McIllece coach_code.

    Tries two paths:

    1. Match a CFBD Coach by ``first_name``/``last_name``, follow a
       ``SAME_PERSON`` edge to get the McIllece ``coach_code``.
    2. Fall back to a direct McIllece Coach node matched by ``name``
       — required on Railway where SAME_PERSON edges are not yet loaded.

    Args:
        coach_name: Full display name, e.g. ``"Nick Saban"``.
        driver: Open Neo4j driver.

    Returns:
        Integer coach_code, or ``None`` if not found.
    """
    parts = coach_name.strip().split(None, 1)
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
        result = session.run(query, first=first, last=last, full_name=coach_name.strip())
        record = result.single()
    return record.get("mc_code") if record else None


def _build_tree_rows(
    raw_rows: list[dict[str, Any]],
    root_name: str,
    role_map: dict,
    depth1_codes: set,
    name_to_code: dict,
) -> list[ResultRow]:
    """Convert raw graph_traversal rows into typed ResultRow objects.

    Args:
        raw_rows: Rows from :func:`~graphrag.graph_traversal.get_coaching_tree`.
        root_name: Display name of the root coach.
        role_map: ``{coach_code: role_abbr}`` from ``get_best_roles``.
        depth1_codes: Set of coach_codes at depth 1 (for orphan filtering).
        name_to_code: ``{name: coach_code}`` lookup built from raw_rows.

    Returns:
        Deduplicated list of :class:`~graphrag.synthesizer.ResultRow` objects.
    """
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
    return rows


# ---------------------------------------------------------------------------
# Preset executors
# ---------------------------------------------------------------------------


def _run_tree_preset(preset: dict, params: dict, driver: Driver) -> PresetResult:
    """Execute a tree preset and return a PresetResult.

    Args:
        preset: Preset dict from YAML.
        params: UI-supplied parameter values (must include ``coach_name``).
        driver: Open Neo4j driver.

    Returns:
        :class:`PresetResult` with ``result_type="tree"`` and ``grag_result``
        populated on success.
    """
    coach_name = str(params.get("coach_name", "")).strip()
    if not coach_name:
        return PresetResult(
            result_type="tree",
            preset_id=preset["id"],
            preset_name=preset["name"],
            error="coach_name parameter is required.",
        )

    mc_code = _resolve_coach_code(coach_name, driver)
    if mc_code is None:
        return PresetResult(
            result_type="tree",
            preset_id=preset["id"],
            preset_name=preset["name"],
            error=f"Coach '{coach_name}' not found in graph.",
        )

    raw_rows = _gt.get_coaching_tree(
        coach_code=mc_code,
        max_depth=2,
        role_filter="HC",
        driver=driver,
    )

    mentee_codes = [r.get("coach_code") for r in raw_rows if r.get("coach_code") is not None]
    role_map = _gt.get_best_roles(mentee_codes, driver)

    name_to_code: dict[str, Any] = {}
    for row in raw_rows:
        rn = row.get("name") or ""
        rc = row.get("coach_code")
        if rn and rc is not None:
            name_to_code[rn] = rc

    depth1_codes: set = set()
    for row in raw_rows:
        if int(row.get("depth", 0)) == 1:
            rc = row.get("coach_code")
            if rc is not None:
                depth1_codes.add(rc)

    result_rows = _build_tree_rows(raw_rows, coach_name, role_map, depth1_codes, name_to_code)

    grag_result = GraphRAGQueryResult(
        response=SynthesizedResponse(
            answer=(
                f"Coaching tree for {coach_name} — "
                f"depth-1 and depth-2 HC mentees ({len(result_rows)} coaches)."
            ),
            result_rows=result_rows,
            partial=False,
            warnings=[],
        ),
        intent="TREE_QUERY",
        root_name=coach_name,
        narrative_used=False,
    )

    return PresetResult(
        result_type="tree",
        preset_id=preset["id"],
        preset_name=preset["name"],
        grag_result=grag_result,
        root_name=coach_name,
        answer=grag_result.response.answer,
    )


def _run_table_preset(preset: dict, params: dict, driver: Driver) -> PresetResult:
    """Execute a table preset and return a PresetResult.

    Applies any ``computed_params`` (simple integer arithmetic) before running
    the Cypher template.  ``computed_params`` expressions are evaluated against
    the params dict using a restricted ``eval`` with no builtins — they come
    from trusted YAML files in this directory, not from user input.

    Args:
        preset: Preset dict from YAML.
        params: UI-supplied parameter values.
        driver: Open Neo4j driver.

    Returns:
        :class:`PresetResult` with ``result_type="table"``, ``rows``, and
        ``columns`` populated.
    """
    # Apply computed params (e.g. prev_season = season - 1).
    computed: dict = dict(params)
    for cp in preset.get("computed_params", []):
        computed[cp["name"]] = int(
            eval(cp["expr"], {"__builtins__": {}}, dict(computed))  # noqa: S307
        )

    cypher: str = preset["cypher_template"]
    with driver.session() as session:
        result = session.run(cypher, **computed)
        rows = [dict(record) for record in result]

    columns: list[dict] = preset.get("columns", [])
    answer_tmpl: str = preset.get("answer_template", "{count} results.")
    try:
        answer = answer_tmpl.format(count=len(rows), **computed)
    except KeyError:
        answer = f"{len(rows)} results."

    return PresetResult(
        result_type="table",
        preset_id=preset["id"],
        preset_name=preset["name"],
        columns=columns,
        rows=rows,
        answer=answer,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_preset(preset: dict, params: dict, driver: Driver) -> PresetResult:
    """Execute a preset and return the typed result.

    Dispatches to :func:`_run_tree_preset` or :func:`_run_table_preset` based
    on the preset's ``result_type`` field.

    Args:
        preset: Preset dict loaded from a YAML file in this directory.
        params: Parameter values keyed by the parameter ``name`` field in the
            YAML.  Values should match the declared ``type`` (str for ``text``
            and ``select``; int for ``number``).
        driver: Open Neo4j driver connected to the loaded graph.

    Returns:
        :class:`PresetResult` — check ``result_type`` and ``error`` before
        rendering.
    """
    result_type = preset.get("result_type", "table")
    try:
        if result_type == "tree":
            return _run_tree_preset(preset, params, driver)
        return _run_table_preset(preset, params, driver)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Preset '%s' failed: %s", preset.get("id"), exc)
        return PresetResult(
            result_type=result_type,
            preset_id=preset.get("id", ""),
            preset_name=preset.get("name", ""),
            error=str(exc),
        )
