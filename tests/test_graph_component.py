"""Tests for ui/components/graph_component.py.

Covers:
- test_json_shape: output JSON has nodes/edges/meta with correct types.
- test_role_assignment: HC node gets correct color values per DESIGN_SYSTEM.md.
- test_depth_filter: nodes beyond max_depth are excluded from the output.
- test_empty_result: graceful handling of an empty result — no crash.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from graphrag.retriever import GraphRAGQueryResult
from graphrag.synthesizer import ResultRow, SynthesizedResponse
from ui.components.graph_component import (
    ROLE_COLORS,
    _name_slug,
    _node_id,
    _resolve_role,
    result_to_graph_data,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_result(
    root_name: str = "Nick Saban",
    rows: list[ResultRow] | None = None,
    intent: str = "TREE_QUERY",
) -> GraphRAGQueryResult:
    """Build a minimal GraphRAGQueryResult for testing."""
    return GraphRAGQueryResult(
        response=SynthesizedResponse(
            answer="Test answer",
            result_rows=rows or [],
            partial=False,
            warnings=[],
        ),
        intent=intent,
        root_name=root_name,
    )


def _make_row(
    display_name: str,
    depth: int = 1,
    coach_id: int | None = None,
    explanation: str = "Test explanation.",
    confidence_flag: str | None = "STANDARD",
    role: str | None = None,
) -> ResultRow:
    """Build a minimal ResultRow for testing."""
    return ResultRow(
        coach_id=coach_id,
        display_name=display_name,
        depth=depth,
        explanation=explanation,
        confidence_flag=confidence_flag,
        role=role,
    )


# ---------------------------------------------------------------------------
# test_json_shape
# ---------------------------------------------------------------------------


def test_json_shape_keys():
    """Output dict must have nodes, edges, and meta at the top level."""
    result = _make_result(rows=[_make_row("Kirby Smart", coach_id=100)])
    data = result_to_graph_data(result)

    assert set(data.keys()) == {"nodes", "edges", "meta"}


def test_json_shape_nodes_type():
    """nodes must be a list of dicts with required string/numeric fields."""
    result = _make_result(rows=[_make_row("Kirby Smart", coach_id=100)])
    data = result_to_graph_data(result)

    assert isinstance(data["nodes"], list)
    for node in data["nodes"]:
        assert isinstance(node, dict)
        assert "id" in node
        assert "label" in node
        assert "role" in node
        assert "depth" in node
        assert isinstance(node["id"], str)
        assert isinstance(node["label"], str)
        assert isinstance(node["depth"], int)


def test_json_shape_edges_type():
    """edges must be a list of dicts with from/to string fields."""
    result = _make_result(rows=[_make_row("Kirby Smart", coach_id=100)])
    data = result_to_graph_data(result)

    assert isinstance(data["edges"], list)
    for edge in data["edges"]:
        assert isinstance(edge, dict)
        assert "from" in edge
        assert "to" in edge
        assert isinstance(edge["from"], str)
        assert isinstance(edge["to"], str)


def test_json_shape_meta_type():
    """meta must be a dict with root_name, total_nodes, hc_mentees, query_depth."""
    result = _make_result(rows=[_make_row("Kirby Smart", coach_id=100)])
    data = result_to_graph_data(result)

    meta = data["meta"]
    assert isinstance(meta, dict)
    assert isinstance(meta["root_name"], str)
    assert isinstance(meta["total_nodes"], int)
    assert isinstance(meta["hc_mentees"], int)
    assert isinstance(meta["query_depth"], int)


def test_json_shape_root_node_present():
    """Root node (depth=0) is always present even with empty rows."""
    result = _make_result(root_name="Nick Saban", rows=[])
    data = result_to_graph_data(result)

    assert len(data["nodes"]) == 1
    root = data["nodes"][0]
    assert root["depth"] == 0
    assert root["label"] == "Nick Saban"


def test_json_shape_node_count():
    """Total node count equals number of result rows + 1 (root)."""
    rows = [_make_row(f"Coach {i}", coach_id=i) for i in range(5)]
    result = _make_result(rows=rows)
    data = result_to_graph_data(result)

    assert data["meta"]["total_nodes"] == 6  # 5 mentees + 1 root
    assert len(data["nodes"]) == 6


def test_json_shape_edge_count():
    """Each result row produces exactly one edge."""
    rows = [_make_row(f"Coach {i}", coach_id=i) for i in range(3)]
    result = _make_result(rows=rows)
    data = result_to_graph_data(result)

    assert len(data["edges"]) == 3


# ---------------------------------------------------------------------------
# test_role_assignment
# ---------------------------------------------------------------------------


def test_role_assignment_hc_colors_in_design_system():
    """HC role colors in ROLE_COLORS must match DESIGN_SYSTEM.md spec."""
    assert ROLE_COLORS["HC"]["bg"] == "#F5C842"
    assert ROLE_COLORS["HC"]["border"] == "#C49A1A"
    assert ROLE_COLORS["HC"]["font"] == "#0F1729"


def test_role_assignment_oc_colors_in_design_system():
    """OC role colors must match DESIGN_SYSTEM.md spec."""
    assert ROLE_COLORS["OC"]["bg"] == "#E8503A"
    assert ROLE_COLORS["OC"]["border"] == "#B83020"
    assert ROLE_COLORS["OC"]["font"] == "#FFFFFF"


def test_role_assignment_dc_colors_in_design_system():
    """DC role colors must match DESIGN_SYSTEM.md spec."""
    assert ROLE_COLORS["DC"]["bg"] == "#4F8EF7"
    assert ROLE_COLORS["DC"]["border"] == "#2060C0"
    assert ROLE_COLORS["DC"]["font"] == "#FFFFFF"


def test_role_assignment_pos_colors_in_design_system():
    """POS role colors must match DESIGN_SYSTEM.md spec."""
    assert ROLE_COLORS["POS"]["bg"] == "#A78BFA"
    assert ROLE_COLORS["POS"]["border"] == "#7050CC"
    assert ROLE_COLORS["POS"]["font"] == "#FFFFFF"


def test_role_assignment_root_is_hc():
    """Root node (depth=0) must always have role='HC'."""
    result = _make_result(rows=[])
    data = result_to_graph_data(result)

    root = data["nodes"][0]
    assert root["role"] == "HC"


def test_role_assignment_mentee_defaults_to_hc():
    """Depth-1 nodes default to HC role when no role info is available."""
    result = _make_result(rows=[_make_row("Kirby Smart", coach_id=200)])
    data = result_to_graph_data(result)

    mentee = next(n for n in data["nodes"] if n["depth"] == 1)
    assert mentee["role"] == "HC"


# ---------------------------------------------------------------------------
# test_depth_maps_to_level
# ---------------------------------------------------------------------------


def test_depth_maps_to_level():
    """Every node's level field must equal its depth (vis.js hierarchical requirement)."""
    rows = [
        _make_row("Direct Mentee", depth=1, coach_id=10),
        _make_row("Second Gen",    depth=2, coach_id=11),
    ]
    result = _make_result(root_name="Nick Saban", rows=rows)
    data = result_to_graph_data(result)

    by_depth = {n["depth"]: n for n in data["nodes"]}
    assert by_depth[0]["level"] == 0, "root node must have level=0"
    assert by_depth[1]["level"] == 1, "depth-1 node must have level=1"
    assert by_depth[2]["level"] == 2, "depth-2 node must have level=2"


# ---------------------------------------------------------------------------
# test_depth_filter
# ---------------------------------------------------------------------------


def test_depth_filter_excludes_nodes_beyond_max():
    """Nodes with depth > max_depth must not appear in the output."""
    rows = [
        _make_row("Coach D1", depth=1, coach_id=1),
        _make_row("Coach D2", depth=2, coach_id=2),
        _make_row("Coach D3", depth=3, coach_id=3),
        _make_row("Coach D4", depth=4, coach_id=4),
    ]
    result = _make_result(rows=rows)
    data = result_to_graph_data(result, max_depth=2)

    depths_present = {n["depth"] for n in data["nodes"]}
    assert 3 not in depths_present
    assert 4 not in depths_present


def test_depth_filter_includes_nodes_at_max_depth():
    """Nodes at exactly max_depth must be included."""
    rows = [
        _make_row("Coach D1", depth=1, coach_id=1),
        _make_row("Coach D2", depth=2, coach_id=2),
    ]
    result = _make_result(rows=rows)
    data = result_to_graph_data(result, max_depth=2)

    depths_present = {n["depth"] for n in data["nodes"]}
    assert 1 in depths_present
    assert 2 in depths_present


def test_depth_filter_max_depth_1():
    """max_depth=1 returns only root + direct mentees."""
    rows = [
        _make_row("Direct Mentee", depth=1, coach_id=10),
        _make_row("Indirect Mentee", depth=2, coach_id=11),
    ]
    result = _make_result(rows=rows)
    data = result_to_graph_data(result, max_depth=1)

    labels = {n["label"] for n in data["nodes"]}
    assert "Direct Mentee" in labels
    assert "Indirect Mentee" not in labels


def test_depth_filter_edges_pruned_with_nodes():
    """Edges to pruned nodes must not appear in output edges."""
    rows = [
        _make_row("D1 Node", depth=1, coach_id=1),
        _make_row("D2 Node", depth=2, coach_id=2),
    ]
    result = _make_result(rows=rows)
    data = result_to_graph_data(result, max_depth=1)

    node_ids = {n["id"] for n in data["nodes"]}
    for edge in data["edges"]:
        assert edge["from"] in node_ids
        assert edge["to"] in node_ids


# ---------------------------------------------------------------------------
# test_empty_result
# ---------------------------------------------------------------------------


def test_empty_result_no_crash():
    """Empty result_rows produces a valid single-node graph without raising."""
    result = _make_result(rows=[])
    data = result_to_graph_data(result)

    assert len(data["nodes"]) == 1
    assert len(data["edges"]) == 0
    assert data["meta"]["total_nodes"] == 1
    assert data["meta"]["hc_mentees"] == 0


def test_empty_result_meta_root_name():
    """Meta root_name is populated even with empty rows."""
    result = _make_result(root_name="Urban Meyer", rows=[])
    data = result_to_graph_data(result)

    assert data["meta"]["root_name"] == "Urban Meyer"


def test_empty_result_no_root_name():
    """Missing root_name falls back to 'Unknown' gracefully."""
    result = GraphRAGQueryResult(
        response=SynthesizedResponse(
            answer="", result_rows=[], partial=False, warnings=[]
        ),
        intent="TREE_QUERY",
        root_name="",
    )
    data = result_to_graph_data(result)

    assert data["nodes"][0]["label"] == "Unknown"
    assert data["meta"]["root_name"] == "Unknown"


def test_empty_result_none_rows():
    """None result_rows is treated as empty without raising."""
    result = GraphRAGQueryResult(
        response=SynthesizedResponse(
            answer="", result_rows=None, partial=False, warnings=[]
        ),
        intent="TREE_QUERY",
        root_name="Nick Saban",
    )
    data = result_to_graph_data(result)

    assert len(data["nodes"]) == 1
    assert len(data["edges"]) == 0


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------


def test_name_slug_basic():
    assert _name_slug("Nick Saban") == "nick-saban"


def test_name_slug_special_chars():
    assert _name_slug("O'Brien Jr.") == "o-brien-jr"


def test_node_id_with_coach_code():
    assert _node_id(1457, "Nick Saban") == "mc_1457"


def test_node_id_without_coach_code():
    assert _node_id(None, "Nick Saban") == "cfbd_nick-saban"


def test_node_id_string_coach_code():
    """String coach codes (e.g. legacy CFBD IDs) are formatted as mc_."""
    assert _node_id("abc123", "Some Coach") == "mc_abc123"


# ---------------------------------------------------------------------------
# _resolve_role
# ---------------------------------------------------------------------------


def test_resolve_role_root_always_hc():
    """Root node (depth=0) always returns HC regardless of explicit role."""
    assert _resolve_role("OC", depth=0) == "HC"
    assert _resolve_role(None, depth=0) == "HC"


def test_resolve_role_uses_explicit_role():
    """When an explicit role is provided for a non-root node, it is used."""
    assert _resolve_role("OC", depth=1) == "OC"
    assert _resolve_role("DC", depth=1) == "DC"
    assert _resolve_role("POS", depth=2) == "POS"
    assert _resolve_role("HC", depth=1) == "HC"


def test_resolve_role_defaults_to_hc_when_none():
    """When no explicit role is provided, non-root nodes default to HC."""
    assert _resolve_role(None, depth=1) == "HC"
    assert _resolve_role(None, depth=3) == "HC"


def test_resolve_role_ignores_unexpected_values():
    """Unexpected role strings fall back to HC."""
    assert _resolve_role("QB", depth=1) == "HC"
    assert _resolve_role("", depth=1) == "HC"


# ---------------------------------------------------------------------------
# Role passthrough from ResultRow to graph data
# ---------------------------------------------------------------------------


def test_role_passthrough_oc_node():
    """OC role on ResultRow produces role='OC' on the graph node."""
    result = _make_result(rows=[
        _make_row("Steve Sarkisian", coach_id=500, role="OC"),
    ])
    data = result_to_graph_data(result)
    mentee = next(n for n in data["nodes"] if n["depth"] == 1)
    assert mentee["role"] == "OC"


def test_role_passthrough_dc_node():
    """DC role on ResultRow produces role='DC' on the graph node."""
    result = _make_result(rows=[
        _make_row("Kirby Smart", coach_id=501, role="DC"),
    ])
    data = result_to_graph_data(result)
    mentee = next(n for n in data["nodes"] if n["depth"] == 1)
    assert mentee["role"] == "DC"


def test_role_passthrough_pos_node():
    """POS role on ResultRow produces role='POS' on the graph node."""
    result = _make_result(rows=[
        _make_row("Burton Burns", coach_id=502, role="POS"),
    ])
    data = result_to_graph_data(result)
    mentee = next(n for n in data["nodes"] if n["depth"] == 1)
    assert mentee["role"] == "POS"


def test_role_passthrough_none_defaults_to_hc():
    """ResultRow with role=None produces role='HC' on the graph node (backward compat)."""
    result = _make_result(rows=[
        _make_row("Kirby Smart", coach_id=503, role=None),
    ])
    data = result_to_graph_data(result)
    mentee = next(n for n in data["nodes"] if n["depth"] == 1)
    assert mentee["role"] == "HC"


def test_role_passthrough_mixed_roles():
    """A tree with mixed roles renders each node with its correct role."""
    result = _make_result(rows=[
        _make_row("Kirby Smart", coach_id=100, role="HC"),
        _make_row("Steve Sarkisian", coach_id=200, role="OC"),
        _make_row("Jeremy Pruitt", coach_id=300, role="DC"),
        _make_row("Burton Burns", coach_id=400, role="POS"),
    ])
    data = result_to_graph_data(result)
    roles_by_label = {n["label"]: n["role"] for n in data["nodes"] if n["depth"] == 1}
    assert roles_by_label["Kirby Smart"] == "HC"
    assert roles_by_label["Steve Sarkisian"] == "OC"
    assert roles_by_label["Jeremy Pruitt"] == "DC"
    assert roles_by_label["Burton Burns"] == "POS"
