"""vis.js coaching tree component for Streamlit.

Reads the ``coaching_tree.html`` template, converts a
:class:`~graphrag.retriever.GraphRAGQueryResult` to the ``__GRAPH_DATA__``
JSON shape, and renders it via ``st.components.v1.html()``.

Design system reference: ``ui/design_system/DESIGN_SYSTEM.md``
"""

from __future__ import annotations

import json
import re
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import streamlit as st

if TYPE_CHECKING:
    from graphrag.retriever import GraphRAGQueryResult

logger = logging.getLogger(__name__)

# Path to the HTML template (same directory as this module).
_TEMPLATE_PATH = Path(__file__).parent / "coaching_tree.html"

# Role colours per DESIGN_SYSTEM.md — used to validate role assignment.
ROLE_COLORS: dict[str, dict[str, str]] = {
    "HC":  {"bg": "#F5C842", "border": "#C49A1A", "font": "#0F1729"},
    "OC":  {"bg": "#E8503A", "border": "#B83020", "font": "#FFFFFF"},
    "DC":  {"bg": "#4F8EF7", "border": "#2060C0", "font": "#FFFFFF"},
    "POS": {"bg": "#A78BFA", "border": "#7050CC", "font": "#FFFFFF"},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _name_slug(name: str) -> str:
    """Convert a coach display name to a URL-safe slug for use as a node ID.

    Args:
        name: Full display name, e.g. ``"Nick Saban"``.

    Returns:
        Lowercase hyphen-separated slug, e.g. ``"nick-saban"``.
    """
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _node_id(coach_id: int | str | None, display_name: str) -> str:
    """Derive a stable node ID from available coach identifiers.

    Uses the McIllece ``coach_code`` when present (``mc_{coach_id}``),
    otherwise falls back to a name slug (``cfbd_{slug}``).

    Args:
        coach_id: McIllece coach_code (int) or other identifier, or ``None``.
        display_name: Coach full name (fallback for slug generation).

    Returns:
        String node ID, e.g. ``"mc_1457"`` or ``"cfbd_nick-saban"``.
    """
    if coach_id is not None:
        return f"mc_{coach_id}"
    return f"cfbd_{_name_slug(display_name)}"


def _resolve_role(explicit_role: str | None, depth: int) -> str:
    """Return the display role for a node.

    Uses the explicit role from the ``ResultRow`` when available.
    Falls back to ``"HC"`` (the coaching-tree default) when no role
    data has been piped through.

    Args:
        explicit_role: Role abbreviation from ``ResultRow.role``
            (e.g. ``"HC"``, ``"OC"``, ``"DC"``, ``"POS"``), or ``None``.
        depth: Hop distance from the root node (0 = root itself).

    Returns:
        Role string — one of ``"HC"``, ``"OC"``, ``"DC"``, ``"POS"``.
    """
    if depth == 0:
        return "HC"
    if explicit_role and explicit_role in ("HC", "OC", "DC", "POS"):
        return explicit_role
    return "HC"


# ---------------------------------------------------------------------------
# Data conversion
# ---------------------------------------------------------------------------


def result_to_graph_data(
    result: "GraphRAGQueryResult",
    max_depth: int = 4,
) -> dict:
    """Convert a :class:`~graphrag.retriever.GraphRAGQueryResult` to the
    ``__GRAPH_DATA__`` JSON shape consumed by ``coaching_tree.html``.

    Node IDs follow the strategy documented in ``TASK 3``:
    - McIllece ``coach_code`` available → ``mc_{coach_code}``
    - Not available → ``cfbd_{name_slug}``

    Edges are inferred from depth relationships: all depth-1 nodes connect
    to the root; deeper nodes connect to the nearest ancestor in the result
    set.  (Currently the pipeline returns at most depth=1 rows; this handles
    deeper results forward-compatibly.)

    Args:
        result: Full ``GraphRAGQueryResult`` from ``retrieve_with_graphrag()``.
        max_depth: Maximum node depth to include (nodes beyond this are
            excluded).  Defaults to 4.

    Returns:
        Dict with ``nodes``, ``edges``, and ``meta`` keys matching the
        ``__GRAPH_DATA__`` contract.
    """
    root_name: str = result.root_name or "Unknown"
    root_id: str = f"cfbd_{_name_slug(root_name)}"

    nodes: list[dict] = []
    edges: list[dict] = []

    # Root node (depth=0)
    nodes.append(
        {
            "id": root_id,
            "label": root_name,
            "role": "HC",
            "team": "",
            "years": "",
            "sp_plus": None,
            "depth": 0,
            "level": 0,
            "explain": "Root of coaching tree.",
            "mentee_count": None,
            "draft_picks": None,
            "confidence_flag": None,
        }
    )

    # Collect result rows filtered to max_depth.
    filtered_rows = [
        r for r in (result.response.result_rows or [])
        if r.depth <= max_depth
    ]

    for row in filtered_rows:
        nid = _node_id(row.coach_id, row.display_name)
        role = _resolve_role(row.role, row.depth)

        nodes.append(
            {
                "id": nid,
                "label": row.display_name,
                "role": role,
                "team": row.team or "",
                "years": row.years or "",
                "sp_plus": None,
                "depth": row.depth,
                "level": row.depth,
                "explain": row.explanation or "",
                "mentee_count": None,
                "draft_picks": None,
                "confidence_flag": row.confidence_flag,
            }
        )

        # Wire edge to the correct parent.
        # - depth=1 → parent is always the root node.
        # - depth>1 → use mentor_coach_id to find the actual mentor node.
        if row.depth == 1 or row.mentor_coach_id is None:
            parent_id = root_id
        else:
            parent_id = _node_id(row.mentor_coach_id, "")
        edges.append({"from": parent_id, "to": nid})

    # Compute meta.
    hc_mentees = sum(1 for n in nodes if n["depth"] == 1 and n["role"] == "HC")
    meta = {
        "root_name": root_name,
        "total_nodes": len(nodes),
        "hc_mentees": hc_mentees,
        "query_depth": max(n["depth"] for n in nodes) if nodes else 0,
    }

    logger.debug(
        "result_to_graph_data sample nodes: %s",
        nodes[:3],
    )

    return {"nodes": nodes, "edges": edges, "meta": meta}


# ---------------------------------------------------------------------------
# Streamlit entry point
# ---------------------------------------------------------------------------


def render_coaching_tree(result: "GraphRAGQueryResult") -> None:
    """Render the vis.js coaching tree component in Streamlit.

    Reads the ``coaching_tree.html`` template, converts the
    ``GraphRAGQueryResult`` to the ``__GRAPH_DATA__`` JSON shape, injects it
    into the template, and renders via ``st.components.v1.html()``.

    Args:
        result: Full ``GraphRAGQueryResult`` returned by
            ``retrieve_with_graphrag()``.  Only ``TREE_QUERY`` results
            produce a meaningful graph; other intents render a minimal
            single-node tree.
    """
    try:
        template_html = _TEMPLATE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        st.error(
            f"coaching_tree.html template not found at {_TEMPLATE_PATH}. "
            "Please verify the ui/components/ directory is present."
        )
        return

    graph_data = result_to_graph_data(result)

    logger.info(
        "render_coaching_tree: root=%r nodes=%d edges=%d",
        graph_data["meta"]["root_name"],
        graph_data["meta"]["total_nodes"],
        len(graph_data["edges"]),
    )

    # Inject graph data: replace the __GRAPH_DATA__ token with the JSON literal.
    graph_json = json.dumps(graph_data, ensure_ascii=False)
    html = template_html.replace("__GRAPH_DATA__", graph_json)

    st.components.v1.html(html, height=850, scrolling=False)
