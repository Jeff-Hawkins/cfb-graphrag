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

import time
import uuid

import streamlit as st

logger = logging.getLogger(__name__)
from dotenv import load_dotenv
from neo4j import GraphDatabase

from analytics.tracker import log_event
from ui.components.graph_component import render_coaching_tree
from graphrag.retriever import GraphRAGQueryResult, retrieve_with_graphrag
from graphrag.vanilla_rag import answer_question_vanilla
from presets.runner import PresetResult, load_presets, run_preset

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
# Session state
# ---------------------------------------------------------------------------

if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())

if "query_input" not in st.session_state:
    st.session_state.query_input = ""

if "pending_query" not in st.session_state:
    st.session_state.pending_query = ""

if "preset_result" not in st.session_state:
    st.session_state.preset_result = None

# Transfer any pending preset value into the text-input default *before* the
# widget is instantiated.  Writing to query_input after the widget renders
# raises StreamlitAPIException.
if st.session_state.pending_query:
    st.session_state.query_input = st.session_state.pending_query
    st.session_state.pending_query = ""


@st.cache_data
def _load_presets() -> list[dict]:
    """Load and cache preset YAML files."""
    return load_presets()


# ---------------------------------------------------------------------------
# Sidebar: mode toggle + F2 preset panel
# ---------------------------------------------------------------------------

with st.sidebar:
    mode = st.radio("Mode", ["GraphRAG", "Vanilla RAG (baseline)"], index=0)
    st.divider()

    # ── F2 preset panel ───────────────────────────────────────────────────
    st.markdown(
        "<div style='font-size:11px;font-weight:600;letter-spacing:0.08em;"
        "text-transform:uppercase;color:#5C7099;margin-bottom:8px;'>Presets</div>",
        unsafe_allow_html=True,
    )

    all_presets = _load_presets()
    segments = ["All"] + sorted({p["segment"] for p in all_presets})
    selected_segment = st.selectbox("Segment", segments, label_visibility="collapsed")

    filtered_presets = [
        p for p in all_presets
        if selected_segment == "All" or p["segment"] == selected_segment
    ]
    preset_names = [p["name"] for p in filtered_presets]
    selected_name = st.selectbox("Preset", preset_names, label_visibility="collapsed")
    selected_preset = filtered_presets[preset_names.index(selected_name)]

    # Render parameter inputs for the selected preset.
    preset_params: dict = {}
    for param in selected_preset.get("parameters", []):
        ptype = param.get("type", "text")
        label = param["label"]
        default = param.get("default", "")
        if ptype == "text":
            preset_params[param["name"]] = st.text_input(label, value=str(default))
        elif ptype == "number":
            preset_params[param["name"]] = int(
                st.number_input(label, value=int(default), step=1, format="%d")
            )
        elif ptype == "select":
            options: list = param.get("options", [])
            idx = options.index(default) if default in options else 0
            preset_params[param["name"]] = st.selectbox(label, options, index=idx)

    if st.button("Run Preset", use_container_width=True):
        driver = _get_driver()
        with st.spinner("Running preset…"):
            _t0 = time.monotonic()
            _pr = run_preset(selected_preset, preset_params, driver)
            _duration_ms = int((time.monotonic() - _t0) * 1000)
            st.session_state.preset_result = _pr
        log_event(
            query_text=selected_preset.get("name", selected_name),
            query_type="preset",
            preset_id=selected_preset.get("id"),
            segment=selected_segment,
            result_count=len(_pr.rows) if _pr.result_type == "table" else (
                len(_pr.grag_result.response.result_rows) if _pr.grag_result else 0
            ),
            failure=bool(_pr.error),
            duration_ms=_duration_ms,
            session_id=st.session_state.session_id,
        )
        # Clear any freeform query result so preset output takes center stage.
        st.session_state.query_input = ""
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
# Preset result rendering
# ---------------------------------------------------------------------------

if st.session_state.preset_result is not None:
    pr: PresetResult = st.session_state.preset_result
    st.markdown("<div class='main-content'>", unsafe_allow_html=True)

    if pr.error:
        st.error(pr.error)
    elif pr.result_type == "tree" and pr.grag_result is not None:
        st.markdown(pr.grag_result.response.answer)
        render_coaching_tree(pr.grag_result)
    elif pr.result_type == "table":
        if pr.answer:
            st.markdown(pr.answer)
        if pr.rows:
            import pandas as pd  # noqa: PLC0415
            display_cols = {c["key"]: c["label"] for c in pr.columns} if pr.columns else {}
            df = pd.DataFrame(pr.rows)
            if display_cols:
                df = df[[c for c in display_cols if c in df.columns]]
                df = df.rename(columns=display_cols)
            st.dataframe(df, use_container_width=True)
        else:
            st.info("No results returned for this preset.")

    st.markdown("</div>", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Freeform query handling
# ---------------------------------------------------------------------------

if question:
    st.session_state.preset_result = None
    with st.spinner("Thinking…"):
        _freeform_t0 = time.monotonic()
        try:
            if mode == "GraphRAG":
                driver = _get_driver()
                grag_result: GraphRAGQueryResult = retrieve_with_graphrag(
                    question, driver=driver
                )
            else:
                vanilla_text: str = answer_question_vanilla(question)
        except Exception as exc:
            _freeform_duration_ms = int((time.monotonic() - _freeform_t0) * 1000)
            log_event(
                query_text=question,
                query_type="freeform",
                segment=mode,
                result_count=0,
                failure=True,
                duration_ms=_freeform_duration_ms,
                session_id=st.session_state.session_id,
            )
            st.error(f"Error: {exc}")
            st.stop()
        _freeform_duration_ms = int((time.monotonic() - _freeform_t0) * 1000)
    _freeform_result_count = (
        len(grag_result.response.result_rows)
        if mode == "GraphRAG"
        else 0
    )
    log_event(
        query_text=question,
        query_type="freeform",
        segment=mode,
        result_count=_freeform_result_count,
        failure=False,
        duration_ms=_freeform_duration_ms,
        session_id=st.session_state.session_id,
    )

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
