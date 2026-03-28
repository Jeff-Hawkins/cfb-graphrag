"""CFB GraphRAG — Streamlit application entry point.

Run with:
    streamlit run app/streamlit_app.py
"""

import logging
import os
import sys
from pathlib import Path

# Ensure the project root is on sys.path regardless of how Streamlit is invoked.
_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st

logger = logging.getLogger(__name__)
from dotenv import load_dotenv
from neo4j import GraphDatabase

from ui.components.graph_component import render_coaching_tree
from graphrag.retriever import GraphRAGQueryResult, retrieve_with_graphrag
from graphrag.vanilla_rag import answer_question_vanilla

load_dotenv()
logging.basicConfig(level=logging.INFO)

st.set_page_config(page_title="CFB IQ", page_icon="🏈", layout="wide")

# ── Design system: navy shell + hide Streamlit chrome ─────────────────────────
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@700;800;900&family=Inter:wght@400;500;600&display=swap');

/* Hide Streamlit chrome */
#MainMenu  { visibility: hidden; }
footer     { visibility: hidden; }
header     { visibility: hidden; }

/* Navy shell */
.stApp { background: #0F1729 !important; }

/* Remove padding from the main content block */
.block-container {
    padding-top:    0    !important;
    padding-bottom: 0    !important;
    padding-left:   0    !important;
    padding-right:  0    !important;
    max-width:      100% !important;
}

/* Sidebar */
[data-testid="stSidebar"] {
    background:   #162035 !important;
    border-right: 1px solid rgba(255,255,255,0.07);
}
[data-testid="stSidebar"] * { color: #A8B8D8 !important; }
[data-testid="stSidebar"] .stButton > button {
    background:  #1E2D4A !important;
    color:       #A8B8D8 !important;
    border:      1px solid rgba(255,255,255,0.12) !important;
    border-radius: 8px  !important;
    font-family: 'Inter', sans-serif !important;
    font-size:   12px !important;
    text-align:  left !important;
}
[data-testid="stSidebar"] .stButton > button:hover {
    background: #253558 !important;
    color:      #FFFFFF !important;
}
[data-testid="stSidebar"] .stRadio > label     { color: #5C7099 !important; font-size: 11px !important; }
[data-testid="stSidebar"] .stDivider           { border-color: rgba(255,255,255,0.07) !important; }

/* Text input */
.stTextInput > label { color: #A8B8D8 !important; font-size: 12px !important; }
.stTextInput > div > div > input {
    background:    #1E2D4A !important;
    color:         #FFFFFF !important;
    border:        1px solid rgba(255,255,255,0.12) !important;
    border-radius: 8px !important;
    font-family:   'Inter', sans-serif !important;
    padding:       10px 14px !important;
}
.stTextInput > div > div > input::placeholder { color: #5C7099 !important; }
.stTextInput > div > div > input:focus {
    border-color: rgba(79,142,247,0.6) !important;
    box-shadow:   0 0 0 2px rgba(79,142,247,0.15) !important;
}

/* Divider */
hr { border-color: rgba(255,255,255,0.07) !important; margin: 0 !important; }

/* Body text */
.stMarkdown p, .stMarkdown li { color: #A8B8D8 !important; }
h1, h2, h3                    { color: #FFFFFF !important; font-family: 'Barlow Condensed', sans-serif !important; }

/* Warning / alert */
[data-testid="stAlert"] {
    background:    rgba(232,80,58,0.12) !important;
    border-radius: 8px !important;
    border:        1px solid rgba(232,80,58,0.25) !important;
}

/* Expander */
[data-testid="stExpander"] {
    background:    #182038 !important;
    border:        1px solid rgba(255,255,255,0.07) !important;
    border-radius: 14px !important;
}
[data-testid="stExpander"] summary { color: #FFFFFF !important; }
[data-testid="stExpander"] p       { color: #A8B8D8 !important; }

/* Content padding wrapper */
.main-content { padding: 16px 24px; }
</style>
""",
    unsafe_allow_html=True,
)

# ── Top nav bar ────────────────────────────────────────────────────────────────
st.markdown(
    """
<div style="
  background: #0F1729;
  border-bottom: 1px solid rgba(255,255,255,0.07);
  padding: 0 24px;
  display: flex;
  align-items: center;
  gap: 40px;
  height: 52px;
">
  <!-- Logo -->
  <div style="
    font-family: 'Barlow Condensed', sans-serif;
    font-size: 22px;
    font-weight: 800;
    color: #FFFFFF;
    letter-spacing: 0.05em;
    white-space: nowrap;
    flex-shrink: 0;
  ">
    <span style="color:#F5C842">&#9670;</span>&nbsp;CFB IQ
  </div>

  <!-- Tab bar -->
  <div style="display:flex; align-items:stretch; height:52px;">
    <div style="
      padding: 0 16px;
      display: flex;
      align-items: center;
      border-bottom: 2px solid #F5C842;
      font-family: 'Inter', sans-serif;
      font-size: 13px;
      font-weight: 600;
      color: #FFFFFF;
      cursor: pointer;
    ">Coaching Trees</div>
    <div style="
      padding: 0 16px;
      display: flex;
      align-items: center;
      font-family: 'Inter', sans-serif;
      font-size: 13px;
      font-weight: 500;
      color: #5C7099;
    ">Coordinators</div>
    <div style="
      padding: 0 16px;
      display: flex;
      align-items: center;
      font-family: 'Inter', sans-serif;
      font-size: 13px;
      font-weight: 500;
      color: #5C7099;
    ">Recruiting</div>
    <div style="
      padding: 0 16px;
      display: flex;
      align-items: center;
      font-family: 'Inter', sans-serif;
      font-size: 13px;
      font-weight: 500;
      color: #5C7099;
    ">Draft Outcomes</div>
    <div style="
      padding: 0 16px;
      display: flex;
      align-items: center;
      font-family: 'Inter', sans-serif;
      font-size: 13px;
      font-weight: 500;
      color: #5C7099;
    ">Carousel</div>
  </div>
</div>
""",
    unsafe_allow_html=True,
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
        "Saban coaching tree",
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
# Sidebar: mode toggle + preset queries
# ---------------------------------------------------------------------------

with st.sidebar:
    mode = st.radio("Mode", ["GraphRAG", "Vanilla RAG (baseline)"], index=0)
    st.divider()
    st.markdown(
        "<div style='font-size:11px;font-weight:600;letter-spacing:0.08em;"
        "text-transform:uppercase;color:#5C7099;margin-bottom:8px;'>Presets</div>",
        unsafe_allow_html=True,
    )
    for label, query_text in _PRESETS:
        if st.button(label, use_container_width=True):
            st.session_state.pending_query = query_text
            st.rerun()

# ---------------------------------------------------------------------------
# Query input (full-width, below nav)
# ---------------------------------------------------------------------------

st.markdown("<div class='main-content'>", unsafe_allow_html=True)

question: str = st.text_input(
    "Ask a question",
    placeholder="e.g. Show me Nick Saban's coaching tree",
    key="query_input",
)

st.markdown("</div>", unsafe_allow_html=True)

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

    st.markdown("<div class='main-content'>", unsafe_allow_html=True)

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

        # Coaching-tree graph visualisation (vis.js F4c component).
        logger.info(
            "Graph viz: intent=%s narrative_used=%s result_rows=%d root=%r",
            grag_result.intent,
            grag_result.narrative_used,
            len(response.result_rows),
            grag_result.root_name,
        )

    st.markdown("</div>", unsafe_allow_html=True)

    if mode == "GraphRAG":
        if grag_result.intent == "TREE_QUERY" and grag_result.root_name:
            render_coaching_tree(grag_result)

        # Pipeline warnings / retry metadata (collapsed, non-intrusive).
        if response.warnings:
            st.markdown("<div class='main-content'>", unsafe_allow_html=True)
            with st.expander("Pipeline notes", expanded=False):
                for w in response.warnings:
                    st.text(w)
            st.markdown("</div>", unsafe_allow_html=True)

    else:
        st.markdown("<div class='main-content'>", unsafe_allow_html=True)
        st.markdown(vanilla_text)
        st.markdown("</div>", unsafe_allow_html=True)
