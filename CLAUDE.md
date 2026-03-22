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
├── pipeline.py            ← full ingest → load → verify script (run from project root)
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
│   ├── pull_rosters.py    ← injects season_year into each record in-memory
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
(:Coach {first_name, last_name})
(:Player {id, name, position, hometown})
(:Conference {name})

(:Coach)-[:COACHED_AT {title, start_year, end_year}]->(:Team)
(:Player)-[:PLAYED_FOR {year, jersey}]->(:Team)    ← year = calendar season (2015–2025)
(:Team)-[:IN_CONFERENCE]->(:Conference)
(:Team)-[:PLAYED {game_id, home_score, away_score, season, week}]->(:Team)
(:Coach)-[:MENTORED]->(:Coach)
```

## Live Graph State (as of Session 3)

| Node label | Count |
|---|---|
| Player | 97,765 |
| Team | 1,902 |
| Coach | 1,786 |
| Conference | 74 |

| Relationship type | Count |
|---|---|
| PLAYED_FOR | 231,540 |
| PLAYED | 26,918 |
| COACHED_AT | 12,414 |
| IN_CONFERENCE | 702 |
| MENTORED | 163 |

Data range: rosters and games 2015–2025. Coaches span all years recorded by CFBD.

**MENTORED inference note:** CFBD `/coaches` only records **head-coaching tenures**, not
assistant stints.  MENTORED edges are inferred from coaching-transition overlaps
(e.g., interim head coach + incoming head coach at the same school in the same season).
Famous staff hierarchies (Saban → Smart, etc.) are **not** captured because assistant
roles are absent from the source data.

---

## Coding Standards

- All functions must have docstrings
- Type hints required on all function signatures
- No hardcoded credentials — always use `.env` via `python-dotenv`
- Use `MERGE` not `CREATE` in all Cypher (idempotent loads)
- Save all raw API responses to `data/raw/` before transforming
- Never re-hit the API if a local JSON file already exists
- Shared HTTP helpers live in `ingestion/utils.py`

## CFBD API Field Name Gotchas

The CFBD API returns **camelCase** for most endpoints. The loaders expect **snake_case**.
All normalization is done in `pipeline.py` before calling any loader function.

| Endpoint | Raw field | Normalized to |
|---|---|---|
| `/coaches` | `firstName`, `lastName` | `first_name`, `last_name` |
| `/roster` | `firstName`, `lastName`, `homeCity`, `homeState` | `name` (combined), `hometown` |
| `/roster` | `year` (academic: 1–4) | use `season_year` injected by `pull_rosters` |
| `/games` | `homeTeam`, `awayTeam`, `homePoints`, `awayPoints` | `home_team`, `away_team`, `home_points`, `away_points` |
| `/teams` | matches loader expectations | no normalization needed |

**Never pass raw CFBD records directly to loader functions** — always normalize first.

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

## Running the Pipeline

```bash
# From project root — uses .env for all credentials
python pipeline.py
```

- Ingestion is idempotent: skips any `data/raw/` file that already exists
- Loading is idempotent: all Cypher uses `MERGE`
- Neo4j uniqueness constraints are created automatically on first run
- Load order is **Teams → Conferences → Coaches → Players → Games**
  (Teams must exist before Conferences creates `IN_CONFERENCE` relationships)
- Players batch size: 2,000 records per transaction
- Games batch size: 2,000 records per transaction

---

*Last updated: Session 3 — inferred and loaded 163 MENTORED coaching-tree edges. 35/35 tests pass.*
