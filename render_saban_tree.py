"""Render Nick Saban's coaching tree (depth 1-3) as a Pyvis HTML visualization.

Saves to data/visuals/saban_tree.html.
"""
import os
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv
from pyvis.network import Network

load_dotenv(dotenv_path=".env")

from loader.neo4j_loader import get_driver

SABAN_CODE = 1457


def fetch_tree(driver):
    """Fetch all nodes and edges in Saban's coaching tree (depth 1–3)."""
    tree_rows = []
    inner_edges = []

    with driver.session() as session:
        # All (saban → mentee) paths up to depth 3
        result = session.run(
            """
            MATCH path = (saban:Coach {coach_code: $code})-[:MENTORED*1..3]->(m:Coach)
            RETURN saban.name AS saban_name,
                   saban.coach_code AS saban_code,
                   m.name AS mentee_name,
                   m.coach_code AS mentee_code,
                   length(path) AS depth
            """,
            code=SABAN_CODE,
        )
        tree_rows = [dict(r) for r in result]

        # Edges between any two nodes that are both in Saban's tree
        result2 = session.run(
            """
            MATCH (saban:Coach {coach_code: $code})-[:MENTORED*1..3]->(a:Coach)
            MATCH (saban)-[:MENTORED*1..3]->(b:Coach)
            MATCH (a)-[:MENTORED]->(b)
            RETURN a.name AS mentor_name, a.coach_code AS mentor_code,
                   b.name AS mentee_name, b.coach_code AS mentee_code
            """,
            code=SABAN_CODE,
        )
        inner_edges = [dict(r) for r in result2]

    return tree_rows, inner_edges


def build_graph(tree_rows, inner_edges):
    """Build node/edge data structures for Pyvis."""
    nodes = {}  # code -> {name, depth}
    edges_set = set()

    if not tree_rows:
        return nodes, edges_set

    # Saban root
    first = tree_rows[0]
    nodes[first["saban_code"]] = {"name": first["saban_name"], "depth": 0}

    for row in tree_rows:
        code = row["mentee_code"]
        if code not in nodes:
            nodes[code] = {"name": row["mentee_name"], "depth": row["depth"]}
        # Direct Saban → depth-1 edges
        if row["depth"] == 1:
            edges_set.add((first["saban_code"], code))

    for row in inner_edges:
        edges_set.add((row["mentor_code"], row["mentee_code"]))

    return nodes, edges_set


def render(nodes, edges_set, out_path: Path):
    """Render Pyvis HTML network."""
    # Count outbound edges per node for sizing
    out_degree: dict[int, int] = defaultdict(int)
    for from_code, _ in edges_set:
        out_degree[from_code] += 1

    net = Network(
        height="950px",
        width="100%",
        directed=True,
        bgcolor="#1a1a2e",
        font_color="white",
        notebook=False,
    )
    net.set_options(
        """
{
  "physics": {
    "barnesHut": {
      "gravitationalConstant": -10000,
      "centralGravity": 0.3,
      "springLength": 130,
      "springConstant": 0.04,
      "damping": 0.09
    },
    "stabilization": {"iterations": 300}
  },
  "edges": {
    "arrows": {"to": {"enabled": true, "scaleFactor": 0.7}},
    "color": {"color": "#666666"},
    "smooth": {"type": "dynamic"}
  },
  "interaction": {"hover": true, "tooltipDelay": 100, "navigationButtons": true}
}
"""
    )

    depth_colors = {
        0: "#FFD700",   # Saban — gold
        1: "#FF6B6B",   # direct mentees — coral
        2: "#4ECDC4",   # depth-2 — teal
        3: "#A8E6CF",   # depth-3 — mint
    }

    for code, info in nodes.items():
        depth = info["depth"]
        is_saban = code == SABAN_CODE
        label = info["name"] or str(code)
        # Size: Saban is biggest; then scale by number of mentees
        mentee_count = out_degree.get(code, 0)
        size = 45 if is_saban else max(8, min(35, 8 + mentee_count * 2))
        net.add_node(
            code,
            label=label,
            title=f"{label}<br>Depth {depth} | {mentee_count} mentees in tree",
            color=depth_colors.get(depth, "#CCCCCC"),
            size=size,
            font={"size": 16 if is_saban else 10, "color": "white"},
            borderWidth=3 if is_saban else 1,
        )

    for from_code, to_code in edges_set:
        net.add_edge(from_code, to_code)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    net.save_graph(str(out_path))
    print(f"Saved: {out_path}  ({len(nodes)} nodes, {len(edges_set)} edges)")


def main():
    driver = get_driver(
        os.environ["NEO4J_URI"],
        os.environ["NEO4J_USERNAME"],
        os.environ["NEO4J_PASSWORD"],
    )
    try:
        print("Fetching Saban coaching tree from Neo4j …")
        tree_rows, inner_edges = fetch_tree(driver)
        print(f"  {len(tree_rows)} tree-path rows, {len(inner_edges)} inner edges")
    finally:
        driver.close()

    nodes, edges_set = build_graph(tree_rows, inner_edges)
    print(f"  {len(nodes)} unique nodes, {len(edges_set)} unique edges")

    out = Path("data/visuals/saban_tree.html")
    render(nodes, edges_set, out)


if __name__ == "__main__":
    main()
