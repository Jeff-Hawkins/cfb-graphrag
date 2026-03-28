# Project Status

Updated at the start and end of each work session.
Reference: [docs/ROADMAP_FEATURES.md](ROADMAP_FEATURES.md) for full feature/agent specs.

---

## Current Phase: 0 — Core Build

### Active Sprint (week of 2026-03-28)

**In Progress:**
- [ ] F2: Query Presets — first 5 Cypher+NL YAML templates (Saban tree, SEC DCs, OC hire grades, staff stability, Smart→Riley path)
- [ ] F3: Event Tracking — JSON lines logger in Streamlit

**Up Next:**
- [ ] F1: Explain My Result — map raw role abbrs to semantic names (OC → "Offensive Coordinator") in explanation strings
- [ ] A1: ground_truth.yaml, validate.py, anomaly_checks.py — finish contract validation suite

**Done This Sprint:**
- [x] 2026-03-28 — F4c DONE: Full CFB IQ site UI complete. `page_title="CFB IQ"`. CSS injection hides all Streamlit chrome, sets navy shell. "CFB IQ" branded top nav with gold diamond logo + tab bar (Coaching Trees active/gold underline, 4 placeholder tabs). Stats bar in vis.js center panel (coach name · HC mentees · total coaches from `GRAPH_DATA.meta`). Mode toggle moved to sidebar. Results expanders removed — graph front and center. Full-width query input. 663/663 tests pass.
- [x] 2026-03-27 — Docs: `docs/COACHING_SEMANTIC_MODEL.md` created. F1/F2/F4 reframed as semantic query layer in roadmap. A1 formalized with semantic data contracts. F3 extended with review thresholds.
- [x] 2026-03-26 — F4c: Role data pipeline — `role` + `mentor_coach_id` fields added to ResultRow. `get_best_roles()` batch Cypher lookup (HC > OC > DC > POS priority). `_resolve_role()` uses actual role from Neo4j instead of defaulting all nodes to HC.
- [x] 2026-03-26 — F4c: Depth-2 HC tree — `_fetch_direct_mentees()` now fetches depth 1–2 with `role_filter="HC"`. Correct edge wiring via `mentor_coach_id`. Orphaned depth-2 nodes (mentor not in depth-1 set) filtered out.
- [x] 2026-03-26 — F4c: Component height 580→830px for better screenshots.
- [x] 2026-03-26 — Gemini model upgrade 2.0-flash → 2.5-flash across classifier, entity_extractor, planner, vanilla_rag. `parse_gemini_json()` utility for markdown-fenced JSON responses.
- [x] 2026-03-26 — 15 new tests (get_best_roles, _resolve_role, role passthrough, depth-2 inclusion). 663/663 pass.
- [x] 2026-03-26 — All previously untracked Session 5–10 files committed (executor, retry, synthesizer, narratives, utils, agents scaffold, scripts, precomputed narratives).
- [x] 2026-03-25 — F4c: `ui/design_system/DESIGN_SYSTEM.md` — navy palette, role colors (HC gold, OC coral, DC blue, POS purple), typography, component rules, vis.js node specs
- [x] 2026-03-25 — F4c: `ui/components/coaching_tree.html` — vis.js 4.21.0 three-panel layout (filters | hierarchical UD network | coach detail card), CDN loaded, role-based node styling, click-to-detail, hover tooltips, legend
- [x] 2026-03-25 — F4c: `ui/components/graph_component.py` — `result_to_graph_data()` converts GraphRAGQueryResult → nodes/edges/meta JSON; `render_coaching_tree()` injects into template via `st.components.v1.html()`
- [x] 2026-03-25 — F4c: `app/streamlit_app.py` — replaced Pyvis `render_graph()` with `render_coaching_tree(grag_result)` for TREE_QUERY intents; added sys.path guard for reliable module resolution
- [x] 2026-03-25 — F4c: Fixed hierarchical layout bug — vis.js requires `level` property on nodes, not just `depth`. Added `"level": row.depth` to all node dicts and `level: n.level` in `buildVisNode()`.
- [x] 2026-03-25 — 27 new tests in `tests/test_graph_component.py` (json_shape, role_colors, depth_filter, depth_maps_to_level, empty_result, helpers). 648/648 pass.

**Done Previously:**
- [x] 2026-03-24 — Rule 1 two-part fix in `infer_mentored_edges_v2()`: Part A (same-team HC during overlap) + Part B (global prior-HC before overlap_start). Suppression: 1,861 → 3,036.
- [x] 2026-03-24 — Full MENTORED edge rebuild on Railway: 22,020 → 20,932 edges.
- [x] 2026-03-24 — Cycle detection added to `get_head_coach_tree_summary()` in `graphrag/narratives.py` (post-query filter on all_rows and hc_rows). Fixes "Saban at depth 2" bug.
- [x] 2026-03-24 — Deleted 2 bad inbound MENTORED edges to Saban (Kevin Steele, Kirby Smart) via `scripts/delete_saban_inbound_mentored.py`.
- [x] 2026-03-24 — Verified clean Saban tree: 8 direct HC, 112 total HC, 2,070 total mentees (d1:33, d2:219, d3:685, d4:1133).
- [x] 2026-03-24 — 3 new tests (2 cycle-detection in test_narratives.py, 1 Rule 1 Part A in test_mentored_dry_run.py). 556/556 pass.
- [x] 2026-03-24 — `scripts/diagnose_rule1.py` + `scripts/delete_saban_inbound_mentored.py` written for audit/cleanup.

**Done Previously:**
- [ ] F1: Explain My Result — provenance template in GraphRAG response
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
- [x] Full CFB IQ site UI matches mockup (top nav, stats row, full-width graph, Streamlit shell styling) — **DONE 2026-03-28**
- [x] **Site screenshot taken showing the complete redesigned UI — DONE 2026-03-28**

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
| 2026-03-24 | Rule 1 prior-HC check is two-part: same-team HC during overlap (Part A) + global prior-HC before overlap_start (Part B) | Old single check `y < overlap_start` missed coaches who became HC the same year overlap began (Bielema, Swinney, Petersen, Sarkisian, Petrino cases). Part A catches any HC year at the same program during any overlap year. |
| 2026-03-24 | Cycle detection post-query filter in `get_head_coach_tree_summary()` | `author_narrative_saban.py` calls this function, not `get_coaching_tree()`. Without filter, Saban appeared as his own mentee at depth 2 via a bad inbound edge. |
| 2026-03-24 | Mike Locksley and Clay Helton remain in Saban tree legitimately | Locksley was OC before becoming HC (no same-team HC during Saban overlap). Helton was not yet HC during his Heyward overlap at USC. Rule 1 correctly does not fire for these. |
| 2026-03-25 | Replace Pyvis with direct vis.js 4.21.0 CDN | Pyvis wraps vis.js but hides hierarchical layout control, node sizing, and click handlers. Direct vis.js gives full control over UD layout, role-based styling, and three-panel component. Same CDN dependency, zero new packages. |
| 2026-03-25 | DESIGN_SYSTEM.md as pre-read for all UI sessions | Locks palette, role colors, typography, and component rules across Claude Code sessions. Prevents style drift. Tokens migrate directly to React CSS variables in Phase 4 (F11). |
| 2026-03-25 | JSON inject (not postMessage) for vis.js data handoff | Python serializes GraphRAGQueryResult → JSON, replaces __GRAPH_DATA__ token in HTML template, passes to st.components.v1.html(). Zero extra infra for Phase 0-3. Swap to API call in Phase 4. |
| 2026-03-25 | sys.path guard in streamlit_app.py | `Path(__file__).parent.parent` ensures project root is always on sys.path regardless of how Streamlit is invoked. Required after adding `ui/` as a sibling package to `app/`. |
| 2026-03-26 | Batch role lookup via `get_best_roles()` rather than enriching Cypher tree query | Keeps the variable-length path query simple; role lookup is a separate O(1) batch call. Cleaner separation of concerns. |
| 2026-03-26 | HC role_filter + orphan filtering for depth-2 tree | Cypher `role_filter` only checks leaf nodes, not intermediates. Depth-2 mentees whose depth-1 mentor is non-HC (filtered out) would render as orphans. Post-query filter removes them. |
| 2026-03-26 | Phase 0 exit = full site UI rebuild, not just Saban screenshot | User wants the complete CFB IQ site matching the mockup before sharing. Individual tree screenshot is no longer the gate. |
| 2026-03-28 | Remove results expanders — graph is the primary output | User confirmed on seeing the redesigned UI. LLM narrative + graph are sufficient; per-coach expander list adds clutter and obscures the visualization. |
| 2026-03-28 | CSS injection via `st.markdown(unsafe_allow_html=True)` for shell styling | No new dependencies. `@import` loads Google Fonts. Hides Streamlit chrome. `.block-container` padding zeroed so nav bar runs full-width. |
| 2026-03-28 | Stats bar absolute-positioned in vis.js panel-center (36px) | Python already puts `hc_mentees` and `total_nodes` in `GRAPH_DATA.meta`; JS reads them in `renderMeta()`. No Python-side changes needed. |
| 2026-03-26 | Gemini 2.5-flash replaces 2.0-flash | Better JSON compliance, faster, same cost tier. `parse_gemini_json()` handles markdown-fenced responses from 2.5. |

---

## Blockers

| Blocker | Impact | Status | Action |
|---------|--------|--------|--------|
| ~~MENTORED edges not yet rebuilt from McIllece full dataset~~ | ~~Coaching tree queries still limited~~ | **RESOLVED 2026-03-24** | Rule 1 two-part fix + full rebuild complete. 20,932 edges on Railway. |

---

## Weekly Metrics (start tracking in Phase 1)

| Week | LinkedIn Impressions | X Impressions | Reddit Engagement | Substack Subs | DMs/Inbound | Notes |
|------|---------------------|---------------|-------------------|---------------|-------------|-------|
| | | | | | | |

---

## Session Log

| Date | What Was Built | Next Session |
|------|---------------|--------------|
| 2026-03-28 | Session 12: Full CFB IQ site UI — navy CSS injection, "CFB IQ" branded top nav + tab bar (Coaching Trees active/gold, 4 placeholder tabs), stats bar in vis.js center panel (coach name · HC mentees · total coaches from meta), mode toggle to sidebar, results expanders removed (graph front and center), full-width query input. `page_title="CFB IQ"`. Docs: COACHING_SEMANTIC_MODEL.md, semantic vocabulary pass on F1/F2/F3/F4/A1. F4c marked DONE. 663/663 tests. | F2 presets (5 YAML templates + sidebar wiring). F3 JSON lines logger. |
| 2026-03-26 | Session 11: Role data pipeline — `role` + `mentor_coach_id` on ResultRow, `get_best_roles()` batch Cypher, `_resolve_role()`. Depth-2 HC tree with correct edge wiring and orphan filtering. Gemini 2.5-flash upgrade + `parse_gemini_json()`. Component height bump (580→830px). All untracked Session 5–10 files committed. 663/663 tests. | Full-site UI rebuild to match CFB IQ mockup (top nav, stats row, full-width layout, Streamlit shell CSS). Populate team/years/SP+ in node data. |
| 2026-03-25 | Session 10: F4c vis.js coaching tree component built. Pyvis replaced with three-panel vis.js layout (DESIGN_SYSTEM.md, coaching_tree.html, graph_component.py). Hierarchical layout bug fixed (depth→level mapping). sys.path guard in streamlit_app.py. 648/648 tests. | Live verification with Neo4j, Saban tree screenshot (Phase 0 exit), richer node data (team/years/SP+) |
| 2026-03-24 | Session 6: Rule 1 two-part prior-HC fix in `infer_mentored_edges_v2()`. Full MENTORED rebuild on Railway (22,020→20,932). Cycle detection in `get_head_coach_tree_summary()`. Deleted 2 bad Saban inbound edges. Clean Saban tree verified (8 direct HC, 112 total HC, 2,070 total). 553→556 tests. `diagnose_rule1.py` + `delete_saban_inbound_mentored.py`. | Write narratives/saban.txt → --save → Streamlit screenshot (Phase 0 exit) |
| 2026-03-23 | Session 5: F4 complete (classifier, planner, executor, retry, synthesizer). F4b infrastructure: narratives.py, author_narrative_saban.py. Streamlit wired to F4 pipeline. A1 confidence_flag layer. role_constants.py. 553 tests. | MENTORED edge Rule 1 fix (prior-HC two-part check) |
| 2026-03-22 | Session 3C: CFBD coverage audit. `expand_roles.py` + `run_mcillece_pipeline.py`. Full FBS 2005–2025 loaded: 4,216 coaches, 39,031 per-role COACHED_AT edges. TEAM_NAME_MAP fixes 9 mismatches (+2,356 edges). 144 tests. | Rebuild MENTORED edges from McIllece full dataset |
| 2026-03-22 | Session 3B: McIllece ingestion + loader. `pull_mcillece_staff.py`, `load_staff.py`, role-priority MENTORED inference, 62 tests. Roadmap + new dirs scaffolded. | Load full FBS 2005–2025 McIllece dataset; rebuild MENTORED edges |
| (Session 3) | Inferred and loaded 163 MENTORED edges from CFBD head-coach overlaps. 35 tests. | McIllece ingestion |
