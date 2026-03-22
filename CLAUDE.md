# CLAUDE.md — CFB GraphRAG Project Briefing

> This file is read by Claude Code at the start of every session.
> Update at the end of each phase before committing.

---

## Project Purpose

A GraphRAG system built on College Football Data (CFBD) and Neo4j.
Converts natural language questions into graph traversals and LLM-generated answers.
Portfolio project — code quality, testing, and documentation matter.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| Graph DB | Neo4j AuraDB |
| LLM | Google Gemini Python SDK (`gemini-2.0-flash`) |
| Data Source | CFBD API (college football data) |
| UI | Streamlit |
| Graph Viz | Pyvis |
| Testing | Pytest |
| Linting | Ruff + Black |

---

## Architecture

```
ingestion/ → data/raw/ → loader/ → Neo4j → graphrag/ → app/
```

---

## Environment Variables (.env)

```
CFBD_API_KEY=
NEO4J_URI=
NEO4J_USERNAME=
NEO4J_PASSWORD=
GEMINI_API_KEY=
```

---

## Repo Structure

```
cfb-graphrag/
├── CLAUDE.md
├── .env                   ← secrets, never committed
├── .env.example
├── .gitignore
├── requirements.txt
├── requirements-dev.txt
│
├── ingestion/
│   ├── __init__.py
│   ├── pull_teams.py
│   ├── pull_coaches.py
│   ├── pull_rosters.py
│   ├── pull_games.py
│   └── utils.py           ← rate limiting, retry, shared helpers
│
├── loader/
│   ├── __init__.py
│   ├── neo4j_loader.py    ← MERGE logic, connection handling
│   └── schema.py          ← node/edge definitions as constants
│
├── graphrag/
│   ├── __init__.py
│   ├── entity_extractor.py   ← NL → entity names via Gemini
│   ├── graph_traversal.py    ← Neo4j Cypher traversal logic
│   ├── retriever.py          ← orchestrates the full RAG pipeline
│   └── vanilla_rag.py        ← baseline comparison (text search)
│
├── app/
│   ├── streamlit_app.py
│   └── components/
│       └── graph_viz.py   ← Pyvis rendering
│
├── tests/
│   ├── conftest.py
│   ├── ingestion/
│   │   ├── test_pull_teams.py
│   │   └── test_pull_coaches.py
│   ├── loader/
│   │   └── test_neo4j_loader.py
│   └── graphrag/
│       ├── test_entity_extractor.py
│       ├── test_graph_traversal.py
│       └── test_retriever.py
│
└── data/
    ├── raw/               ← never committed
    └── samples/           ← small committed samples for tests
```

---

## Neo4j Schema

```
(:Team {id, school, conference, abbreviation})
(:Coach {id, first_name, last_name})
(:Player {id, name, position, hometown})
(:Conference {name})
(:Season {year})

(:Coach)-[:COACHED_AT {title, start_year, end_year}]->(:Team)
(:Player)-[:PLAYED_FOR {year, jersey}]->(:Team)
(:Team)-[:IN_CONFERENCE]->(:Conference)
(:Team)-[:PLAYED {home_score, away_score, season}]->(:Team)
(:Coach)-[:MENTORED]->(:Coach)
```

---

## Coding Standards

- All functions must have docstrings
- Type hints required on all function signatures
- No hardcoded credentials — always use `.env` via `python-dotenv`
- Use `MERGE` not `CREATE` in all Cypher (idempotent loads)
- Save all raw API responses to `data/raw/` before transforming
- Never re-hit the API if a local JSON file already exists
- Shared HTTP helpers live in `ingestion/utils.py`

---

## Testing Standards

- Every ingestion function must have a test using mocked API responses
- Every loader function must have a test using a mock Neo4j driver
- Every graphrag function must have a test with fixture data
- Run tests with: `pytest tests/ -v`
- Target: 80%+ coverage

---

## Git Hygiene

- Commit after each working session
- Commit messages: `feat:`, `fix:`, `test:`, `docs:`, `refactor:`
- Never commit `.env` or `data/raw/`

---

## Demo Queries (target outputs)

1. Full Nick Saban coaching tree
2. Coaches who worked in both SEC and Big Ten
3. Shortest path between Kirby Smart and Lincoln Riley

---

## LLM Notes

- All `graphrag/` modules use `google-generativeai` with model `gemini-2.0-flash`
- `system_instruction` is set at `GenerativeModel` construction time — entity extraction and answer generation use **separate model instances** with different system prompts
- In `retriever.py`, the `model` param controls answer generation only; `extract_entities` always creates its own model internally
- Tests mock `genai.GenerativeModel` instances directly: `model.generate_content.return_value.text = "..."`
- `retriever` tests patch `graphrag.retriever.extract_entities` to isolate answer-generation logic

---

*Last updated: Session 2 — replaced Anthropic SDK with Google Gemini 2.0 Flash.*
