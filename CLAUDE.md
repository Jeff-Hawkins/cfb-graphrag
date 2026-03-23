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
| Graph DB | Neo4j on Railway (migrated from AuraDB free tier 2026-03-22) |
| LLM | Google Gemini Python SDK (`gemini-2.0-flash`) |
| Data Source | CFBD API (college football data) + McIllece CFB Coaches Database (CSV/XLSX) |
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
NEO4J_URI=          ← points to Railway Neo4j (bolt://centerbeam.proxy.rlwy.net:37477)
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
│   ├── pull_rosters.py         ← injects season_year into each record in-memory
│   ├── pull_games.py
│   ├── pull_mcillece_staff.py  ← parses McIllece CSV/XLSX → cleaned staff record dicts
│   ├── expand_roles.py         ← unpivots pos1-pos5 → per-role records; ROLE_LEGEND, TEAM_NAME_MAP, tier classification
│   ├── build_mentored_edges.py ← infers MENTORED pairs; includes infer_mentored_pairs_mcillece()
│   └── utils.py                ← rate limiting, retry, shared helpers
│
├── loader/
│   ├── __init__.py
│   ├── neo4j_loader.py         ← MERGE logic, connection handling
│   ├── load_staff.py           ← MERGE Coach nodes + COACHED_AT edges from McIllece; --dry-run flag
│   ├── load_mentored_edges.py  ← includes load_mentored_edges_mcillece()
│   └── schema.py               ← node/edge definitions as constants
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
├── run_mcillece_pipeline.py   ← end-to-end McIllece load: parse → expand roles → MERGE; --dry-run flag
├── run_coverage_audit.py      ← CFBD API coverage audit by year 2005-2025 for 4 endpoints
├── export_auradb.py           ← dumps AuraDB → data/migrations/auradb_export_YYYYMMDD/ (JSON)
├── import_to_railway.py       ← loads migration dump into Railway Neo4j; idempotent MERGE
├── verify_railway.py          ← checks node/rel counts + spot-checks against expected values
│
├── agents/                ← Phase 0+ Claude Code agents (scaffolded)
├── presets/               ← F2 Cypher+NL query templates (scaffolded)
├── models/                ← F5 scoring logic (scaffolded)
├── exports/               ← F6 PDF dossier generation (scaffolded)
├── support/               ← F10 triage bot (scaffolded)
│
└── data/
    ├── raw/               ← never committed
    ├── samples/           ← small committed samples for tests
    ├── mcillece/          ← McIllece XLSX source files (never committed)
    ├── audits/            ← coverage audit CSVs (committed)
    │   └── cfbd_coverage_audit.csv  ← CFBD API record counts 2005-2025 for 4 endpoints
    └── ala-2020-example.xlsx  ← Alabama 2020 McIllece sample (dry-run verification)
```

---

## Neo4j Schema

```
(:Team {id, school, conference, abbreviation})
(:Coach {first_name, last_name})
(:Player {id, name, position, hometown})
(:Conference {name})

(:Coach)-[:COACHED_AT {title, start_year, end_year}]->(:Team)          ← CFBD source (source=None)
(:Coach)-[:COACHED_AT {coach_code, year, team_code, roles, source}]->(:Team)  ← McIllece season-level (source="mcillece")
(:Coach)-[:COACHED_AT {coach_code, year, team_code, role, role_abbr, role_tier, source}]->(:Team)  ← McIllece per-role (source="mcillece_roles")
(:Player)-[:PLAYED_FOR {year, jersey}]->(:Team)    ← year = calendar season (2015–2025)
(:Team)-[:IN_CONFERENCE]->(:Conference)
(:Team)-[:PLAYED {game_id, home_score, away_score, season, week}]->(:Team)
(:Coach)-[:MENTORED]->(:Coach)
```

## Live Graph State (as of Session 3D — Railway Neo4j)

| Node label | Count | Notes |
|---|---|---|
| Player | 97,765 | |
| Team | 1,902 | 1,862 unique schools + 40 duplicate non-FBS entries (keyed by CFBD id) |
| Coach | 6,002 | 1,786 CFBD (first_name/last_name) + 4,216 McIllece (coach_code) |
| Conference | 74 | |

| Relationship type | Count | Source |
|---|---|---|
| PLAYED_FOR | 231,540 | CFBD |
| COACHED_AT | 77,813 | CFBD (12,414) + McIllece season-level (26,368) + McIllece per-role (39,031) |
| PLAYED | 26,918 | CFBD |
| IN_CONFERENCE | 702 | CFBD |
| MENTORED | 163 | Inferred from CFBD overlaps |
| **Total** | **337,136** | |

Data range: rosters and games 2015–2025. McIllece staff data 2005–2025 (full FBS). Coaches span all years recorded by CFBD and McIllece.

**COACHED_AT edge flavors (query by `r.source`):**
- `source=None` — CFBD coaches endpoint (12,414 edges, `title`/`start_year`/`end_year` properties)
- `source="mcillece"` — one edge per coach-season (26,368 edges, `roles` list property)
- `source="mcillece_roles"` — one edge per coach-season-role (39,031 edges, `role`, `role_abbr`, `role_tier` properties)

**`role_tier` values** (on `source="mcillece_roles"` edges):
- `COORDINATOR` — HC, OC, DC, PG, PD, RG, RD, AC
- `POSITION_COACH` — QB, RB, WR, OL, DL, DB, LB, TE, DE, DT, CB, SF, IB, OB, IR, GC, OT, FB, OR
- `SUPPORT` — ST, RC, OF, DF, KO, KR, PR, PK, PT, NB, FG

**MENTORED inference note:** Two inference methods exist:
- **CFBD-based (163 edges):** Inferred from head-coaching transition overlaps only. Famous staff hierarchies (Saban → Smart, etc.) are not captured.
- **McIllece-based (`infer_mentored_pairs_mcillece()`):** Uses actual staff records with role priority (HC > OC/DC > position coach). Full FBS 2005–2025 dataset is now loaded — ready to rebuild MENTORED edges from McIllece data.

McIllece coaches are keyed by `coach_code`. CFBD coaches (matched by `first_name + last_name`) are untouched.

**Team name normalization:** 9 McIllece school names are mapped to Neo4j canonical names via `TEAM_NAME_MAP` in `expand_roles.py` (e.g. `"MTSU"` → `"Middle Tennessee"`, `"Miami FL"` → `"Miami"`, `"San Jose State"` → `"San José State"`). Without this map, 2,356 role edges silently dropped on MATCH.

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

## Feature & Agent Roadmap

See [docs/ROADMAP_FEATURES.md](docs/ROADMAP_FEATURES.md) for the full detailed spec on each item.

**Phase 0 (now — before any content ships):**
- F1 Explain My Result — provenance string on every query result
- F2 Query Presets — 15–20 segment-specific Cypher+NL templates
- F3 Event Tracking — JSON lines logging from day one
- F4 Smart Query Planning — multi-step decomposition in S4 GraphRAG pipeline
- A1 Data Validation Agent — ground truth checks + MENTORED confidence scoring

**Phase 1 (months 1–4):**
- A2 Content Generation Agent — Neo4j query → LinkedIn/Substack draft
- A3 Competitive Intel Monitor — watch CFBD, ANSRS, PFF, r/CFBAnalysis

**Phase 2 (months 4–8):**
- F5 Coordinator Success Score — interpretable composite + Tree Adjustment prior
- A4 Carousel Season Research Agent — rapid-response coach analysis
- A5 Engagement Tracker Agent — weekly content performance report

**Phase 3 (months 8–14):**
- F6 Coaching Dossier PDF — one-click export for agents/ADs/journalists
- F7 Documentation & Example Query System — auto-updated from usage data
- A6 Lead Research & Outreach Agent — prospect lists + personalized emails

**Phase 4 (months 14–24):**
- F8 Prospect List Workflows — tagging, notes, per-user state
- F9 Public API — REST/GraphQL developer preview
- F10 In-App Support & Triage Bot — tier-1 answers + structured backlog
- A7 Query Optimization Agent — failure patterns, new preset suggestions
- A8 Data Ingestion Pipeline Agent — seasonal graph updates
- A9 Pricing & Usage Analytics Agent — retention, churn, experiment suggestions

**Priority rules:**
- Never build a later-phase item before current phase exit criteria are met
- Features (F-items) before agents (A-items) within each phase
- Phase 0 items are blockers — nothing ships without F1, F2, F3, F4, A1
- Track everything via F3 before expanding it
- Read raw user feedback yourself until Phase 4 volume justifies automation

---

## Project Organization

**Two Claude.ai project folders:**
1. **Build & Strategy (this project)** — platform dev, schema, data, business planning
2. **Content & GTM** (create when Phase 1 starts) — posts, outreach, audience

**Tracking files (in repo):**
- `CLAUDE.md` — project context for Claude Code (read first, always)
- `docs/ROADMAP_FEATURES.md` — full feature & agent specs with implementation notes
- `docs/STATUS.md` — weekly sprint tracking, phase exit criteria, decisions log

---

*Last updated: Session 3D (Task 2) — Railway Neo4j migration complete. AuraDB free tier decommissioned. export_auradb.py, import_to_railway.py, verify_railway.py added at project root. docs/railway_setup.md documents the migration procedure. NEO4J_URI now points to Railway (bolt://centerbeam.proxy.rlwy.net:37477). data/mcillece/ and data/migrations/ added to .gitignore. 216/216 tests pass.*
