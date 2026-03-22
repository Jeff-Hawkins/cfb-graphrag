"""CFB GraphRAG — Streamlit application entry point.

Run with:
    streamlit run app/streamlit_app.py
"""

import os
import logging

import streamlit as st
from dotenv import load_dotenv
from neo4j import GraphDatabase

from graphrag.retriever import answer_question
from graphrag.vanilla_rag import answer_question_vanilla

load_dotenv()
logging.basicConfig(level=logging.INFO)

st.set_page_config(page_title="CFB GraphRAG", page_icon="🏈", layout="wide")
st.title("🏈 CFB GraphRAG")
st.caption("Ask natural language questions about college football coaching trees, rosters, and games.")

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
# UI
# ---------------------------------------------------------------------------

col_left, col_right = st.columns([3, 1])

with col_right:
    mode = st.radio("Mode", ["GraphRAG", "Vanilla RAG (baseline)"], index=0)

with col_left:
    question = st.text_input(
        "Ask a question",
        placeholder="e.g. Show me Nick Saban's coaching tree",
    )

st.divider()

if question:
    with st.spinner("Thinking…"):
        try:
            if mode == "GraphRAG":
                driver = _get_driver()
                answer = answer_question(question, driver=driver)
            else:
                answer = answer_question_vanilla(question)
        except Exception as exc:
            st.error(f"Error: {exc}")
            st.stop()

    st.markdown(answer)

# ---------------------------------------------------------------------------
# Sidebar: example queries
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("Example queries")
    examples = [
        "Show me Nick Saban's full coaching tree",
        "Which coaches worked in both the SEC and Big Ten?",
        "What is the shortest path between Kirby Smart and Lincoln Riley?",
    ]
    for ex in examples:
        if st.button(ex):
            st.session_state["_example"] = ex
            st.rerun()
