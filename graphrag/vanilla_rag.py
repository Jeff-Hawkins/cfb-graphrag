"""Baseline RAG using plain text search (no graph traversal).

Loads raw JSON files from data/raw/ and does keyword matching to build
context, then sends that context to Gemini.  Used as a performance
baseline against GraphRAG.
"""

import json
import logging
import os
from pathlib import Path

import google.generativeai as genai

logger = logging.getLogger(__name__)

_RAW_DIR = Path("data/raw")

_ANSWER_SYSTEM = """You are a college football analyst. Answer the question using
only the provided context.  If the context does not contain the answer, say so."""


def _load_text_corpus(raw_dir: Path = _RAW_DIR) -> str:
    """Build a flat text corpus from cached raw JSON files.

    Args:
        raw_dir: Directory containing ``teams.json``, ``coaches.json``, etc.

    Returns:
        A single string with key facts extracted from available JSON files.
    """
    lines: list[str] = []

    teams_path = raw_dir / "teams.json"
    if teams_path.exists():
        teams = json.loads(teams_path.read_text())
        for t in teams:
            lines.append(f"Team: {t.get('school')} | Conference: {t.get('conference')}")

    coaches_path = raw_dir / "coaches.json"
    if coaches_path.exists():
        coaches = json.loads(coaches_path.read_text())
        for c in coaches:
            name = f"{c.get('first_name')} {c.get('last_name')}"
            for season in c.get("seasons", []):
                lines.append(
                    f"Coach: {name} | School: {season.get('school')} | Year: {season.get('year')}"
                )

    return "\n".join(lines)


def answer_question_vanilla(
    question: str,
    raw_dir: Path = _RAW_DIR,
    model: genai.GenerativeModel | None = None,
) -> str:
    """Answer a question using plain text keyword context (baseline).

    Args:
        question: Natural language question about college football.
        raw_dir: Directory with cached raw JSON files.
        model: Optional ``genai.GenerativeModel``.  If omitted a new model
            is created using ``GEMINI_API_KEY`` from the environment.

    Returns:
        A natural language answer string.
    """
    if model is None:
        genai.configure(api_key=os.environ["GEMINI_API_KEY"])
        model = genai.GenerativeModel(
            model_name="gemini-2.0-flash",
            system_instruction=_ANSWER_SYSTEM,
        )

    corpus = _load_text_corpus(raw_dir)
    keywords = question.lower().split()
    relevant_lines = [
        line for line in corpus.splitlines()
        if any(kw in line.lower() for kw in keywords)
    ]
    context = "\n".join(relevant_lines[:200]) if relevant_lines else "No relevant data found."

    response = model.generate_content(f"Question: {question}\n\nContext:\n{context}")
    return response.text
