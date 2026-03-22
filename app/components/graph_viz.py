"""Pyvis-based graph visualization component for Streamlit.

Renders a Neo4j subgraph result as an interactive HTML network diagram
embedded inside a Streamlit page.
"""

import tempfile
from pathlib import Path
from typing import Any

import streamlit as st
from pyvis.network import Network


def render_graph(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    height: str = "600px",
    width: str = "100%",
) -> None:
    """Render an interactive Pyvis graph inside a Streamlit component.

    Args:
        nodes: List of node dicts with at minimum ``id`` and ``label`` keys.
            Optional ``color`` and ``title`` (tooltip) keys are supported.
        edges: List of edge dicts with ``source``, ``target``, and optional
            ``label`` keys.
        height: CSS height of the embedded iframe (default ``"600px"``).
        width: CSS width of the embedded iframe (default ``"100%"``).
    """
    net = Network(height=height, width=width, directed=True, notebook=False)
    net.barnes_hut()

    for node in nodes:
        net.add_node(
            node["id"],
            label=node.get("label", str(node["id"])),
            color=node.get("color", "#4e9af1"),
            title=node.get("title", ""),
        )

    for edge in edges:
        net.add_edge(
            edge["source"],
            edge["target"],
            label=edge.get("label", ""),
        )

    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    net.save_graph(str(tmp_path))
    html_content = tmp_path.read_text(encoding="utf-8")
    tmp_path.unlink(missing_ok=True)

    st.components.v1.html(html_content, height=int(height.replace("px", "")), scrolling=True)
