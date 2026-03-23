# Project Status

Updated at the start and end of each work session.
Reference: [docs/ROADMAP_FEATURES.md](ROADMAP_FEATURES.md) for full feature/agent specs.

---

## Current Phase: 0 — Core Build

### Active Sprint (week of 2026-03-22)

**In Progress:**
- [ ] Rebuild MENTORED edges from McIllece assistant staff data (full FBS dataset now loaded)
- [ ] S4: GraphRAG pipeline (F4 smart query planning architecture)

**Up Next:**
- [ ] F1: Explain My Result — provenance template in GraphRAG response
- [ ] F2: Query Presets — first 5 Cypher+NL templates (Saban tree, OC draft production, staff stability)
- [ ] F3: Event Tracking — JSON lines logger in Streamlit
- [ ] A1: Data Validation Agent — ground_truth.yaml with Saban/Meyer/Fisher trees

**Done This Sprint:**
- [x] 2026-03-22 — CFBD API coverage audit 2005–2025 (`run_coverage_audit.py`, `data/audits/cfbd_coverage_audit.csv`)
- [x] 2026-03-22 — `expand_roles.py`: pos1-pos5 unpivot, ROLE_LEGEND, TEAM_NAME_MAP (9 entries), role tier classification
- [x] 2026-03-22 — Full FBS 2005–2025 McIllece dataset loaded: 4,216 coaches, 39,031 per-role COACHED_AT edges
- [x] 2026-03-22 — `AC` = "Assistant Head Coach" added to ROLE_LEGEND + COORDINATOR tier; `RC?` → `RC` normalization
- [x] 2026-03-22 — TEAM_NAME_MAP recovers 2,356 previously-dropped edges (9 McIllece→Neo4j school name mismatches)
- [x] 2026-03-22 — 144 tests passing
- [x] 2026-03-22 — McIllece ingestion pipeline (`pull_mcillece_staff.py`, `load_staff.py`, `load_mentored_edges_mcillece()`)
- [x] 2026-03-22 — Role-priority MENTORED inference (`infer_mentored_pairs_mcillece()`)
- [x] 2026-03-22 — Feature & Agent Roadmap added to CLAUDE.md + `docs/ROADMAP_FEATURES.md` created
- [x] 2026-03-22 — Scaffolded `agents/`, `presets/`, `models/`, `exports/`, `support/`

---

## Phase Exit Criteria

### Phase 0 → Phase 1
- [ ] All McIllece FBS assistant staff data 2005–2025 loaded in Neo4j
- [ ] COACHED_AT edges for coordinators and position coaches validated
- [ ] MENTORED edges match known Saban, Meyer, Fisher coaching trees
- [ ] GraphRAG pipeline answers NL questions with correct Cypher traversals
- [ ] F1 Explain My Result renders provenance on every query result
- [ ] F2 has 10+ working presets across at least 3 segments
- [ ] F3 event tracking logging every query
- [ ] A1 validation report runs clean on known ground truth
- [ ] Saban coaching tree screenshot is visually compelling and factually accurate
- [ ] **THE SCREENSHOT EXISTS. Phase 1 does not start without it.**

### Phase 1 → Phase 2
- [ ] 4+ content posts published per month for 2+ consecutive months
- [ ] Engagement tracked weekly (impressions, shares, DMs, inbound)
- [ ] 3+ posts on r/CFBAnalysis with meaningful engagement
- [ ] A2 Content Gen Agent producing usable first drafts
- [ ] A3 Competitive Intel running weekly with no major threats flagged
- [ ] Clear signal on which content types resonate (data from F3 + A5)

### Phase 2 → Phase 3
- [ ] Substack live with free + paid tiers
- [ ] 200+ paid subscribers OR clear evidence of B2B demand
- [ ] F5 Coordinator Success Score backtested and published
- [ ] Carousel season content published and cited/shared by 1+ media outlet
- [ ] Revenue: $2K+/month from Substack

### Phase 3 → Phase 4
- [ ] 2+ agent/search firm pilots completed with documented feedback
- [ ] F6 Coaching Dossier PDF template validated by pilot users
- [ ] F7 Documentation system live for pilot users
- [ ] Product requirements doc based on real professional feedback
- [ ] Clear answer to: "Will professionals pay for this, and what do they need?"

---

## Decisions Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-03-22 | `coach_code` as MERGE key for McIllece coaches | Stable unique ID from source; avoids name-matching ambiguity |
| 2026-03-22 | COACHED_AT `source="mcillece"` tag | Keeps CFBD and McIllece edges distinguishable in queries |
| 2026-03-22 | Role priority HC > OC/DC > position coach for MENTORED inference | Seniority is the right proxy for mentorship when direct relationships aren't recorded |
| 2026-03-22 | JSON lines over SQLite for F3 event tracking | Simpler, no dependency, good enough for Phase 0–2 volume |
| 2026-03-22 | Gemini 2.0 Flash for all LLM calls | Cost, speed, already integrated |
| 2026-03-22 | Two COACHED_AT edge flavors: season-level (`source="mcillece"`) + per-role (`source="mcillece_roles"`) | Season-level for coach history queries; per-role for coordinator/tier filtering. Both idempotent via MERGE. |
| 2026-03-22 | TEAM_NAME_MAP in `expand_roles.py` (not `pull_mcillece_staff.py`) | Name normalization is a Neo4j-matching concern, belongs in the expansion layer not the parse layer |
| 2026-03-22 | `AC` (Assistant Head Coach) classified as COORDINATOR tier | Senior administrative role; typically held by a coordinator who also carries AHC designation |

---

## Blockers

| Blocker | Impact | Status | Action |
|---------|--------|--------|--------|
| MENTORED edges not yet rebuilt from McIllece full dataset | Coaching tree queries still limited | Ready | Run `infer_mentored_pairs_mcillece()` + `load_mentored_edges_mcillece()` against loaded data |

---

## Weekly Metrics (start tracking in Phase 1)

| Week | LinkedIn Impressions | X Impressions | Reddit Engagement | Substack Subs | DMs/Inbound | Notes |
|------|---------------------|---------------|-------------------|---------------|-------------|-------|
| | | | | | | |

---

## Session Log

| Date | What Was Built | Next Session |
|------|---------------|--------------|
| 2026-03-22 | Session 3C: CFBD coverage audit. `expand_roles.py` + `run_mcillece_pipeline.py`. Full FBS 2005–2025 loaded: 4,216 coaches, 39,031 per-role COACHED_AT edges. TEAM_NAME_MAP fixes 9 mismatches (+2,356 edges). 144 tests. | Rebuild MENTORED edges from McIllece full dataset |
| 2026-03-22 | Session 3B: McIllece ingestion + loader. `pull_mcillece_staff.py`, `load_staff.py`, role-priority MENTORED inference, 62 tests. Roadmap + new dirs scaffolded. | Load full FBS 2005–2025 McIllece dataset; rebuild MENTORED edges |
| (Session 3) | Inferred and loaded 163 MENTORED edges from CFBD head-coach overlaps. 35 tests. | McIllece ingestion |
