"""CFB GraphRAG — Streamlit application entry point.

Run with:
    streamlit run app/streamlit_app.py
"""

import logging
import os

import streamlit as st

logger = logging.getLogger(__name__)
from dotenv import load_dotenv
from neo4j import GraphDatabase

from ui.components.graph_component import render_coaching_tree
from graphrag.retriever import GraphRAGQueryResult, retrieve_with_graphrag
from graphrag.vanilla_rag import answer_question_vanilla

load_dotenv()
logging.basicConfig(level=logging.INFO)

st.set_page_config(page_title="CFB GraphRAG", page_icon="🏈", layout="wide")
st.title("🏈 CFB GraphRAG")
st.caption(
    "Ask natural language questions about college football coaching trees, "
    "rosters, and games."
)

# ---------------------------------------------------------------------------
# Neo4j connection (cached per session)
# ---------------------------------------------------------------------------


@st.cache_resource
def _get_driver():
    """Return a cached Neo4j driver using environment variables."""
    return GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
    )


# ---------------------------------------------------------------------------
# Preset queries (Phase 0 demo paths)
# ---------------------------------------------------------------------------

_PRESETS: list[tuple[str, str]] = [
    (
        "Saban coaching tree demo",
        "Show me Nick Saban's coaching tree of current head coaches",
    ),
    (
        "SEC + Big Ten coaches",
        "Which coaches worked in both the SEC and Big Ten?",
    ),
    (
        "Smart → Riley path",
        "What is the shortest path between Kirby Smart and Lincoln Riley?",
    ),
]


# ---------------------------------------------------------------------------
# Session state — query input
# ---------------------------------------------------------------------------

if "query_input" not in st.session_state:
    st.session_state.query_input = ""

if "pending_query" not in st.session_state:
    st.session_state.pending_query = ""

# Transfer any pending preset value into the text-input default *before* the
# widget is instantiated.  Writing to query_input after the widget renders
# raises StreamlitAPIException.
if st.session_state.pending_query:
    st.session_state.query_input = st.session_state.pending_query
    st.session_state.pending_query = ""

# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

col_left, col_right = st.columns([3, 1])

with col_right:
    mode = st.radio("Mode", ["GraphRAG", "Vanilla RAG (baseline)"], index=0)

with col_left:
    question: str = st.text_input(
        "Ask a question",
        placeholder="e.g. Show me Nick Saban's coaching tree",
        key="query_input",
    )

st.divider()

# ---------------------------------------------------------------------------
# Query handling
# ---------------------------------------------------------------------------

if question:
    with st.spinner("Thinking…"):
        try:
            if mode == "GraphRAG":
                driver = _get_driver()
                grag_result: GraphRAGQueryResult = retrieve_with_graphrag(
                    question, driver=driver
                )
            else:
                vanilla_text: str = answer_question_vanilla(question)
        except Exception as exc:
            st.error(f"Error: {exc}")
            st.stop()

    if mode == "GraphRAG":
        response = grag_result.response

        # Partial-results banner.
        if response.partial:
            st.warning(
                "⚠️ Partial results — some sub-queries failed. "
                "See **Pipeline notes** below for details."
            )

        # Primary answer.
        st.markdown(response.answer)

        # Per-coach result rows with F1 Explain My Result strings.
        if response.result_rows:
            st.subheader("Results")
            for row in response.result_rows:
                with st.expander(f"**{row.display_name}**", expanded=True):
                    st.caption(row.explanation)

        # Coaching-tree graph visualisation (vis.js F4c component).
        logger.info(
            "Graph viz: intent=%s narrative_used=%s result_rows=%d root=%r",
            grag_result.intent,
            grag_result.narrative_used,
            len(response.result_rows),
            grag_result.root_name,
        )
        if grag_result.intent == "TREE_QUERY" and grag_result.root_name:
            st.subheader("Coaching tree")
            render_coaching_tree(grag_result)

        # Pipeline warnings / retry metadata (collapsed, non-intrusive).
        if response.warnings:
            with st.expander("Pipeline notes", expanded=False):
                for w in response.warnings:
                    st.text(w)

    else:
        st.markdown(vanilla_text)

# ---------------------------------------------------------------------------
# Sidebar: preset queries
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("Preset queries")
    for label, query_text in _PRESETS:
        if st.button(label, use_container_width=True):
            st.session_state.pending_query = query_text
            st.rerun()
