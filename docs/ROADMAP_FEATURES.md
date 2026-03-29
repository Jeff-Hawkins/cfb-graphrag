# **CFB Coaching Intelligence Platform**

Feature & Agent Roadmap — Unified View

*Last updated: 2026-03-29 Session 16  |  Items within each phase are in priority order. Do not skip ahead. Phase 1 split into 1a (player outcomes data layer — F12, F13) and 1b (content engine — A2, A3). Phase 1a must be loaded and A1-validated before Phase 1b begins.*

Each phase builds on validated learnings from the previous one. Features (F) are product capabilities. Agents (A) are Claude Code automation workflows. All features share a common **Coaching Semantic Model** (`docs/COACHING_SEMANTIC_MODEL.md`) that defines entities, relationships, vocabulary, and data contracts.

| **Phase** | **Focus** | **Timeline** | **Features** | **Agents** |
| --- | --- | --- | --- | --- |
| Phase 0 | Core Build | Now → May 2026 | F1, F2, F3, F4, F4b, **F4c** | A1 |
| Phase 1a | Player Outcomes Data Layer | Months 1–2 (Jun–Jul 2026) | F12, F13 | — |
| Phase 1b | Content Engine | Months 2–4 (Jul–Oct 2026) | — | A2, A3 |
| Phase 2 | Monetize Attention | Months 4–8 (Oct 2026–Jan 2027) | F5 | A4, A5 |
| Phase 3 | B2B Validation | Months 8–14 (Carousel 2026–27) | F6, F7 | A6 |
| Phase 4 | SaaS Productize | Months 14–24 (2027+) | F8, F9, **F11** | A7, A8, A9 |
| Phase 5 | Expand the Graph | Year 2+ (2028+) | Data expansion | — |

---

**Phase 0 — Core Build     Now → May 2026**

*Everything built in Phase 0 must work before a single post ships. Bad data in content = credibility destroyed before you have any.*

| **F1** | **"Explain My Result" Affordance** **WHAT:** Every GraphRAG response includes a secondary text block explaining WHY each coach/result appears. Format: "Included because: Offensive Coordinator at Alabama (2019–22), top-15 SP+ defense, coached under Saban, produced 2 Day 1 picks." Explanation strings use semantic names from the Coaching Semantic Model (`docs/COACHING_SEMANTIC_MODEL.md`) — human-readable role names, team names, and relationship descriptions — never raw property keys or Cypher syntax. **WHY:** Makes every screenshot self-explanatory. Directly feeds Phase 1 content. Without this, users see a graph but don't understand the traversal logic. **IMPL:** Add to GraphRAG response template in S4. Extract traversal path from Cypher result metadata. Map raw properties to semantic vocabulary (e.g. `r.role_abbr='OC'` → "Offensive Coordinator", `COACHED_AT` → "coaching stint"). Store as explanation field alongside each query result. Render below each node/card in Streamlit UI. **Status: DONE — 2026-03-29.** `graphrag/utils.py`: `ROLE_DISPLAY_NAMES` (35 abbr → semantic names) + `role_display_name()`. `graphrag/graph_traversal.py`: `get_mentee_stints()` batch query — for each mentee-mentor pair returns role/team/year-range from overlapping COACHED_AT stints. `graphrag/synthesizer.py`: `ResultRow` gains `team`/`years` fields; `_explain_coaching_tree_row()` uses semantic names. `graphrag/retriever.py`: `_fetch_direct_mentees()` enriched with stint data via `_build_explain()` + `_format_year_range()`; produces "Included because: Offensive Coordinator at Alabama (2019–22), coached under Nick Saban." `ui/components/graph_component.py`: passes `row.team`/`row.years` to vis.js nodes. 29 new tests in `tests/graphrag/test_f1_explain.py`; 740/740 pass. |
| --- | --- |

| **F2** | **Query Presets — Semantic Query Layer** **WHAT:** 15–20 pre-built query templates organized by user segment (Agents, ADs/Search Firms, Media, Betting). Together with F4 (Smart Query Planning), presets form a **semantic query layer** over the coaching graph — users interact with concepts like Coach, Season, Coordinator, and Conference, never raw Cypher or property names. **WHY:** Solves cold-start problem. Demonstrates product range immediately. Gives a fixed Cypher query set to optimize and validate during Phase 0 instead of handling arbitrary NL from day one. Presets also serve as **semantic contracts** between the UI and the graph: parameter names, descriptions, and result labels all use vocabulary from the Coaching Semantic Model (`docs/COACHING_SEMANTIC_MODEL.md`), so no raw schema leaks to users. **IMPL:** Create presets/ directory with YAML files per segment. Each preset: name, description, cypher_template, nl_prompt, segment. Parameters use semantic vocabulary (e.g., `coach_name`, `conference`, `season`, `role_tier`) not graph internals. Streamlit sidebar: segment selector → preset dropdown → one-click run. Presets are parameterized with input fields. **Status: DONE — 2026-03-28.** 5 YAML presets in presets/: coaching_tree (tree), sec_defensive_coordinators, oc_hire_context, staff_stability, coaching_path (all table). presets/runner.py: load_presets(), run_preset() dispatches to direct Cypher execution (bypassing F4 LLM pipeline), returns PresetResult (tree → GraphRAGQueryResult → render_coaching_tree(); table → st.dataframe()). Streamlit sidebar: segment selector (All/General/Media/Agents/ADs) → preset dropdown → dynamic parameter inputs → Run Preset button. staff_stability uses computed_params for prev_season derivation. 23 new tests. 686/686 pass. |
| --- | --- |

| **F3** | **Event Tracking & Semantic Query Observability** **WHAT:** Log every query, export, and interaction from day one. Fields: query text, timestamp, query_type (preset vs. freeform), segment, result count, failure flag, duration_ms, exported/screenshotted, session_id. **WHY:** When Phase 3 requires product decisions, you'll have months of actual usage data. Tracks which presets are popular, which NL queries fail, which segments engage most. Also provides **query quality observability**: if a preset fails > 10% of the time over a 7-day rolling window, it is flagged for review — this is how the semantic query layer self-heals. **IMPL:** Lightweight: append JSON lines to log file or SQLite table. Fields: timestamp, query_text, query_type (preset vs. freeform), preset_id (if applicable), segment, result_count, failure (bool), duration_ms, exported, session_id. Weekly summary script outputting top queries, failure rate, segment breakdown. Review threshold: preset failure rate > 10% over rolling 7 days → flag for rewrite. Do NOT over-engineer — JSON lines file is fine for Phase 0-2. **Status: DONE — 2026-03-28.** analytics/tracker.py: log_event() appends JSON lines to logs/query_events.jsonl (path overridable via CFB_EVENT_LOG env var; parent dirs created automatically; OSError swallowed). analytics/summary.py: CLI (python -m analytics.summary --days N --log PATH) prints total/failure rates, top-10 queries, segment breakdown, per-preset stats; flags any preset with >10% failure rate over the rolling window. app/streamlit_app.py: session_id (UUID) initialised in st.session_state; both freeform and preset paths timed with time.monotonic() and logged. logs/ added to .gitignore. 25 new tests; 711/711 pass. |
| --- | --- |

| **F4** | **Smart Query Planning — Semantic Query Layer** **WHAT:** Multi-step query planning that forms the core of the **semantic query layer** (together with F2 presets). (1) Classify intent into TREE_QUERY │ PERFORMANCE_COMPARE │ PIPELINE_QUERY │ CHANGE_IMPACT │ SIMILARITY via classifier.py — these are semantic intent categories, not Cypher patterns. (2) Decompose complex NL into sub-queries via planner.py. (3) Generate Cypher per sub-query. (4) Validate intermediate results. (5) Retry on failure. (6) Synthesize final response using semantic vocabulary from the Coaching Semantic Model. **WHY:** This is the difference between a demo and a product. Complex questions require composed traversals — a naive single-Cypher approach fails on most interesting queries. The planner reasons over coaching concepts (trees, tenures, roles, conferences), not graph primitives. **IMPL:** graphrag/classifier.py, planner.py, executor.py, retry.py, synthesizer.py. Gemini handles NL plan decomposition and final response synthesis. Cypher generation is template-based where possible, LLM-generated for novel queries. **Status: COMPLETE — 2026-03-23.** All 5 F4 modules done. Full pipeline wired: NL → classify → plan → execute → retry → synthesize. Streamlit wired to F4 pipeline. Pyvis coaching-tree graph renders direct mentees for Saban preset. 617/617 tests pass. |
| --- | --- |

| **F4b** | **Precomputed Tree Narratives** **WHAT:** Pre-build polished coaching tree outputs for the top 10 coaches (Saban first). Store as node properties in Neo4j. Use as reliable Phase 1 content source and GraphRAG fallback for high-traffic queries. **WHY:** Runtime LLM generation requires QA every time. Precomputed narratives give you manually reviewed, screenshot-ready outputs for the queries that will be 80% of traffic. Faster responses, better content, and a fallback when Cypher generation fails on complex traversals. **IMPL:** Run Saban tree query manually, review output, write polished version. Store as narrative property on Coach node in Neo4j. Repeat for top 10 trees: Saban, Meyer, Fisher, Riley, Smart, Sarkisian, Stoops, Dabo, Harbaugh, Belichick. GraphRAG retriever checks for precomputed narrative before running full pipeline. **Status: COMPLETE — 2026-03-24.** Clean Saban tree verified: 8 direct HC mentees, 112 total HC mentees, 2,070 total mentees (d1:33, d2:219, d3:685, d4:1133). All top-10 narratives written and saved to Neo4j. Railway MENTORED: 14,219 unique pairs. 601/601 tests pass. |
| --- | --- |

| **F4c** | **vis.js Coaching Tree UI + Design System** **WHAT:** Replace the default Pyvis component with a production-grade vis.js coaching tree visualization embedded in Streamlit via st.components.v1.html(). Three-panel layout: left sidebar (filters + presets), center graph canvas (hierarchical UD layout, role-based node styling), right context panel (coach detail card, updates on node click). Governed by a project-scoped DESIGN_SYSTEM.md that Claude Code reads before every UI task. **WHY:** The Saban tree screenshot IS the Phase 0 exit criteria and the Phase 1 launch post. Pyvis produces a force-directed spaghetti layout with no role-based styling, no click handlers, and no context panel. The vis.js component is the difference between a screenshot people stop scrolling for and a screenshot nobody shares. The design system is not duct tape — the vis.js component, color tokens, and layout logic migrate directly to the React rebuild in Phase 4. **IMPL:** `ui/design_system/DESIGN_SYSTEM.md` — design enforcer doc Claude Code reads before every UI session. Locks in navy palette (#0F1729 base), role colors (HC gold #F5C842, OC coral #E8503A, DC blue #4F8EF7, POS purple #A78BFA), Barlow Condensed display font, Inter body font, 14px card border-radius, flat surfaces with no drop shadows. `ui/components/coaching_tree.html` — vis.js template with __GRAPH_DATA__ token. Loaded from CDN (vis 4.21.0). Hierarchical UD layout, physics disabled, levelSeparation=95, nodeSpacing=85. Root node: box shape size=32. HC depth>0: ellipse size=22. OC/DC: ellipse size=17. Position coaches: ellipse size=13. Node click fires right panel update. Hover tooltip: mini card with name, role, team, years. `ui/components/graph_component.py` — Python wrapper. Reads HTML template, accepts GraphRAGQueryResult, converts result_rows to __GRAPH_DATA__ JSON shape (nodes/edges/meta), calls st.components.v1.html(html, height=600). Data handoff: JSON inject (Python serializes Neo4j results → embeds in template before st.components call). No postMessage or extra infra needed for Phase 0-3. `app.py` — replace Pyvis render call with render_coaching_tree(result) from graph_component.py. Keep F1 Explain My Result expanders below graph. Keep pipeline warnings expander. **Phase 4 migration path:** vis.js node/edge data and DESIGN_SYSTEM.md tokens migrate directly to React + D3/react-force-graph component. The Streamlit shell and JSON inject handoff are the only throwaway pieces (~20 lines). **Status: DONE — 2026-03-28.** Full CFB IQ site UI complete and screenshot taken. Session 10–11: all F4c component files built (DESIGN_SYSTEM.md, coaching_tree.html, graph_component.py, streamlit_app.py). Role-colored nodes, hierarchical UD layout, depth slider, click-to-detail panel. Session 12: full-site shell styling — `page_title="CFB IQ"`, CSS injection hiding all Streamlit chrome, navy background on entire shell, "CFB IQ" branded top nav with gold diamond logo and tab bar (Coaching Trees active, 4 placeholder tabs in muted color), stats bar inside vis.js center panel (coach name · HC mentees · total coaches from `GRAPH_DATA.meta`), mode toggle moved to sidebar, results expanders removed (graph is front and center), full-width query input. 663/663 tests pass. |
| --- | --- |

| **A1** | **Data Quality / Validation Agent — Semantic Data Contracts** **WHAT:** Enforces the **semantic data contracts** defined in the Coaching Semantic Model (`docs/COACHING_SEMANTIC_MODEL.md`). Audits Neo4j data against known ground truth after each ingestion batch. Validates MENTORED edge confidence flags against known coaching trees (Saban, Meyer, Fisher). Flags anomalies. **Concrete contract checks:** (1) Every `COACHED_AT` edge has a valid `source`, and `mcillece_roles` edges have a valid `role_abbr` (in `ROLE_LEGEND`), `role_tier`, and `year` in range. (2) Every `MENTORED` edge satisfies the 2+ consecutive season overlap rule, passes the same-unit filter, has a valid `confidence_flag`, and is not a self-loop. (3) `SAME_PERSON` edges point from a CFBD node to a McIllece node with non-null `match_type` and `confidence`. (4) Coach, Team, and Player nodes satisfy uniqueness and non-null constraints per the semantic model. **WHY:** Ingestion will have edge cases — duplicates, missing years, coaches with multiple roles. Catching errors before they propagate into content saves you from publishing wrong data. A1 is the enforcement layer for the data contracts that the semantic query layer (F2, F4) depends on. **IMPL:** agents/data_validation/: ground_truth.yaml, validate.py, anomaly_checks.py, mentorship_confidence.py. Run after every ingestion batch. **Status: DONE — 2026-03-29.** Built: add_mentored_confidence_flag.py, flag_mentored_edges.py, role_constants.py (COORDINATOR_ROLES, ASSISTANT_ROLES, ALL_ROLES, same_unit() filter, OFFENSIVE/DEFENSIVE/NEUTRAL_ROLES partition). confidence_flag surfaced in synthesizer + retriever UI. ground_truth.yaml (11 tenures, 5 expected MENTORED, 2 expected-absent), validate.py (tenure + MENTORED ground-truth checks + structural anomaly + overlap sanity), anomaly_checks.py (self-loops, bidirectional cycles, null role_abbr, duplicate coach nodes, large year gaps, graph summary). Confidence flags populated on Railway: 9,824 STANDARD + 4,395 REVIEW_REVERSE across 14,219 MENTORED edges. validate.py runs clean: 11/11 tenure pass, 5/5 mentored pass, 2/2 absent pass, 0 overlap issues, 0 critical anomalies. 740/740 tests pass. |
| --- | --- |

| **EXIT CRITERIA:** The full CFB IQ site UI matches the reference mockup — top nav, stats row, full-width graph canvas, Streamlit shell styled to navy design system. Screenshot of the complete redesigned site with a Saban coaching tree rendered. The graph must be visually impressive, role-colored, hierarchically laid out, and the query must be explainable via the right context panel. SAME_PERSON edge audit complete: CFBD/McIllece identity resolution verified for all coaches appearing in top-10 precomputed tree narratives. No coach in a published narrative should exist as two disconnected nodes. validate.py contract check (3) runs clean. |
| --- |

**Pre-Phase 1b Decision Gate — Shareable Demo URL**
Before the first content post ships, make a deliberate decision: publish a password-protected Railway URL or defer to Phase 3. If deferred, document the reason here. A journalist or agent responding to a post will ask for a link. 'It's not public yet' is an answer — but it should be a conscious choice, not an oversight.

---

**Phase 1a — Player Outcomes Data Layer     Months 1–2  |  June–July 2026**

*Prerequisite for differentiated content. The coaching tree structure alone is publicly known — ESPN has covered it. What makes content defensible and share-worthy is connecting coaching staff history to player outcomes. Phase 1b does not begin until F12 is loaded and A1-validated on Railway.*

| **F12** | **Player Outcomes Data Layer** **WHAT:** Pull NFL draft outcomes, individual season stats, and PPA (Predicted Points Added) from the CFBD API. Load into Neo4j with edges connecting players to the coaching staff they overlapped with. Enables queries like "all DBs coached by a Saban-tree DC who were later drafted" or "OC EPA delta vs. prior coordinator at same program." **WHY:** This is what separates original analysis from recapping public knowledge. Draft production and PPA under specific coaching lineages are not published anywhere in queryable form. Required before A2 can generate differentiated content. Also feeds directly into F5 (Coordinator Success Score) in Phase 2 — building this now avoids a second ingestion pass later. **IMPL:** `ingestion/pull_draft_picks.py` — CFBD `/draft/picks` endpoint, store by year in `data/raw/`. `ingestion/pull_player_stats.py` — CFBD `/stats/player/season`, store by year. `ingestion/pull_ppa.py` — CFBD `/ppa/players`, store by year. `loader/load_draft_picks.py` — MERGE draft round/pick/year as properties on existing Player nodes. `loader/load_player_stats.py` — MERGE season stat totals as properties on PLAYED_FOR edges or new PlayerSeason nodes. New Neo4j edges: `(:Coach)-[:DEVELOPED]->(:Player)` inferred from COACHED_AT + PLAYED_FOR season overlap (same team, same year). A1 ground truth extensions: known draft picks to spot-check (e.g. Jalen Hurts at Alabama 2016-2018, drafted 2020 Round 2; DeVonta Smith at Alabama 2017-2020, drafted 2021 Round 1). 80%+ test coverage on all new ingestion + loader functions. **Status: NOT STARTED.** |
| --- | --- |

| **F13** | **Recruiting Data Layer** **WHAT:** Pull recruiting ratings and rankings from CFBD `/recruiting/players`. Add as properties on Player nodes (recruit_rating, recruit_ranking, recruit_stars, recruit_position_rank). **WHY:** Enables "development vs. recruitment" analysis — the most compelling content angle. A coordinator who turns 3-star recruits into draft picks is a better story than one who develops 5-stars. Required for the full Coordinator Success Score (F5) in Phase 2. **IMPL:** `ingestion/pull_recruiting.py` — CFBD `/recruiting/players` by year. `loader/load_recruiting.py` — MERGE rating/ranking onto existing Player nodes (match by name + team + year). Handle name mismatches between recruiting DB and roster DB (common). A1 ground truth: known high-rated recruits at known programs (e.g. Bryce Young 5-star to Alabama 2021). **Status: NOT STARTED.** |
| --- | --- |

| **EXIT CRITERIA (Phase 1a):** F12 loaded and validated on Railway. Can Cypher-query: coaches → players they overlapped with → draft outcomes. Can Cypher-query: coordinator role at team → position group PPA delta vs. prior coordinator. F13 loaded and spot-checked. A1 ground truth extended with 5+ player outcome facts and running clean. All new ingestion + loader functions at 80%+ test coverage. REVIEW_REVERSE audit complete: all 4,395 REVIEW_REVERSE MENTORED edges reviewed. Each edge either confirmed as STANDARD, reclassified, or deleted. validate.py runs clean with updated ground_truth.yaml after resolution. |
| --- |

---

**Phase 1b — Content Engine     Months 2–4  |  July–October 2026**

*The only job in Phase 1b is proving demand through content. 1 LinkedIn post/week with vis.js coaching tree screenshots, cross-posted to X. Methodology breakdowns on r/CFBAnalysis (6K members). Cross-post to r/CFB (4.4M) during carousel season. Track engagement, DMs, and inbound obsessively. USF football background = credibility edge. Do not sell anything yet. All posts use player outcome data from F12/F13 — coaching tree structure alone is not enough.*

*Note: All content screenshots must use the F4c vis.js component and navy design system. The visual language is now the brand. Consistency across posts = recognizable identity.*

| **A2** | **Content Generation Agent** **WHAT:** Queries Neo4j, pulls interesting data, and drafts LinkedIn/Twitter posts or Substack outlines with the data already embedded. Now uses F12/F13 data — queries join coaching staff to player outcomes, not just tree structure. **WHY:** You need 4+ posts/month. Writing each one manually from raw Cypher output is slow. This agent does the data pull + first draft, you edit and publish. Cuts content production time 60-70%. **IMPL:** agents/content_gen/: templates/ per platform, queries/ of curated Cypher (including player outcome joins), generate.py. Drafts go to content/drafts/ for human review before publishing. Example queries: "Saban-tree DCs → drafted DBs vs. national average", "OC EPA delta by coaching lineage", "3-star → drafted rate by coordinator". Claude Code prompt: 'Query coaching staff + player outcomes from Neo4j. Generate a LinkedIn post draft with a hook, the key stats, and a vis.js screenshot description. Tone: analytical but accessible, not clickbait.' |
| --- | --- |

| **A3** | **Competitive Intelligence Monitor** **WHAT:** Checks CFBD API changelog, ANSRS website, PFF blog, and r/CFBAnalysis weekly for new developments relevant to your competitive position. **WHY:** CFBD endpoint expansion and ANSRS scope creep are the two key risks to your moat. This agent watches so you don't have to manually check weekly. **IMPL:** agents/competitive_intel/: sources.yaml with URLs and RSS feeds, monitor.py diffs against last run, reports/ directory of weekly markdown summaries. Run weekly via cron or manual Claude Code invocation. |
| --- | --- |

| **EXIT CRITERIA (Phase 1b):** Consistent weekly content publishing. Track: engagement rate per post, DMs received, inbound from journalists or agents. Any single viral post (>10K impressions) validates the content strategy. 4+ posts/month for 2+ consecutive months. 3+ r/CFBAnalysis methodology posts with meaningful engagement. A2 producing usable first drafts (editing, not rewriting from scratch). A3 running weekly. |
| --- |

---

**Phase 2 — Monetize Attention     Months 4–8  |  October 2026–January 2027**

*Substack free + paid tier ($8-10/mo). November-January carousel window = peak publishing. Coordinator performance grades, position coach draft production, coaching tree evolution. Target 200-500 paid subs = $2K-5K/mo. Upgrade McIllece Academic to General Use license ($4,500) in September/October 2026 before carousel season monetization.*

| **F5** | **Coordinator Success Score** **WHAT:** An interpretable composite score for coordinator performance. Components: weighted SP+/EPA change vs. prior 2 years, staff stability bonus, recruiting improvement factor, plus a Tree Adjustment prior based on coaching lineage. **WHY:** Raw metrics require expertise to interpret. A single score lets journalists write 'Coach X scored 82/100' and agents say 'my client is a top-15 DC by CSS.' The methodology itself becomes Substack content. **IMPL:** models/coordinator_score.py with configurable weights. models/tree_adjustment.py for Bayesian prior based on coaching lineage depth. All components visible in UI and exports (transparency = trust). Backtest against known successful/unsuccessful coordinator hires. |
| --- | --- |

| **A4** | **Carousel Season Research Agent** **WHAT:** When a coordinator gets hired or fired, feed it the name and it pulls their full graph history, generates performance context, and drafts a quick-take analysis within minutes. **WHY:** Speed matters during carousel season. If you can publish a data-driven take within hours of a hire/fire announcement, you become the source journalists check. **IMPL:** agents/carousel_research/: research.py pulls graph data, templates/quick_take.md format. Integrates with content generation agent (A2) for final formatting. Trigger on breaking news; output Twitter thread + LinkedIn post draft. |
| --- | --- |

| **A5** | **Engagement Tracker Agent** **WHAT:** Pulls Substack stats, LinkedIn post analytics, and Reddit engagement into a single weekly report. Tracks which content types perform best. **WHY:** Feeds Phase 2 content strategy with data instead of gut feel. Identifies which topics drive paid Substack conversions vs. just free engagement. **IMPL:** agents/engagement/: collect.py from platform APIs / manual CSV, report.py generates weekly summary with trends. data/ directory for historical trend analysis. |
| --- | --- |

| **EXIT CRITERIA:** 200+ paid Substack subscribers at $8-10/mo. At least one journalist citation during carousel season. $6K initial investment recouped by January/February 2027. |
| --- |

---

**Phase 3 — B2B Validation     Months 8–14  |  Carousel Season 2026–27**

*Free pilot with 2-3 coaching agents during hiring season. White-label data proposal to Parker Executive Search or Collegiate Sports Associates. Learn what pros actually query, what format they need, what they would pay. Do not build SaaS yet — test with manual delivery first.*

| **F6** | **Coaching Dossier One-Pager (PDF Export)** **WHAT:** One-click PDF export of a coach's complete profile: bio, roles by year, tree lineage, unit performance vs. talent, draft/portal outcomes for their position group, salary/buyout context where available. **WHY:** This is the artifact agents, ADs, and journalists actually pass around. During Phase 3 pilots, deliver these manually. Productizing as one-click export turns pilot learnings into a Phase 4 feature. **IMPL:** exports/dossier.py generates PDF from coach node + connected data. 1-page summary + optional detailed appendix. Includes Coordinator Success Score and Explain My Result provenance. Uses reportlab or weasyprint for PDF generation. |
| --- | --- |

| **F7** | **Documentation & Example Query System** **WHAT:** Auto-generated and continuously updated documentation: 'How to ask X' guides, example queries using semantic vocabulary, API code snippets. Fine-tuned on actual query logs and responses. All docs use the Coaching Semantic Model vocabulary — users see "coaching tree," "coordinator tenure," and "mentorship confidence," not Cypher or property names. **WHY:** Once external users touch the product in Phase 3 pilots and Phase 4 API, stale docs kill adoption. This keeps documentation current without manual maintenance — highest-ROI ops task for a solo builder. **IMPL:** docs/user_guide/ auto-generated from preset definitions and query logs. docs/examples/ top 20 most-run queries with annotated results. Agent regenerates weekly from F3 event tracking data. |
| --- | --- |

| **A6** | **Lead Research & Outreach Agent** **WHAT:** Builds targeted prospect lists AND drafts personalized outreach. Given a target segment (search firms, agents, journalists), it researches individuals, builds a CSV, and drafts emails with specific data hooks from your graph. **WHY:** Phase 3 requires B2B outreach. Researching targets and writing personalized emails manually is the biggest time sink. This agent does both in one workflow. **IMPL:** agents/lead_outreach/: research.py, list_builder.py (CSV output), draft.py (personalized emails), templates/ by target type. Segments: coaching agents, FBS ADs, journalists, betting analysts. |
| --- | --- |

| **EXIT CRITERIA:** At least 2 active B2B pilots (coaching agent or search firm). Clear signal on what format pros want, what they query, and what they would pay. White-label proposal delivered to at least one search firm. |
| --- |

---

**Phase 4 — SaaS Productization     Months 14–24  |  2027+**

*Deploy on Railway. Tiered pricing: Free (3 queries/day) / Pro $29/mo / API $299/mo. Build features based on Phase 1-3 learnings — which queries people actually ask, which vizs resonate, what pros need. Graph DB + GraphRAG layer = moat (2yr head start).*

| **F8** | **Prospect List Workflows** **WHAT:** Users can tag coaches into named lists (e.g., 'my clients,' 'DC shortlist 2027') and attach private notes to coach nodes. Per-account state. **WHY:** Turns the platform from a query tool into a workflow tool people log into daily during carousel season. This is what makes users sticky and reduces churn. **IMPL:** User accounts with auth (Supabase). lists table: user_id, list_name, coach_ids[]. notes table: user_id, coach_id, note_text, timestamp. Private by default. No sharing features until validated. |
| --- | --- |

| **F9** | **Public API (Developer Preview)** **WHAT:** REST or GraphQL endpoint exposing coaching tree, staff history, and basic performance metrics. Rate-limited, labeled 'developer preview.' **WHY:** Pulls in power users (CFBAnalysis community, analytics researchers) who build on top of your data, creating distribution you don't have to pay for. **IMPL:** FastAPI endpoints: /tree/{coach}, /staff/{team}/{year}, /score/{coach}. Rate limiting: 100 req/day free, unlimited paid. API key auth. Auto-generated docs (OpenAPI/Swagger) fed by F7. Deploy on Railway. |
| --- | --- |

| **F11** | **React + D3 UI Rebuild** **WHAT:** Replace the Streamlit shell with a React frontend and replace the vis.js HTML component with a native D3 or react-force-graph coaching tree component. Full three-panel layout (sidebar, graph canvas, context panel) as a proper React SPA. **WHY:** Streamlit is the right call for Phase 0-3 — it lets you ship and validate fast without a frontend build step. By Phase 4 with paying users, Streamlit's limitations (iframe component boundaries, no real auth, limited state management) become friction. The React rebuild is not a redesign — it's a translation. The vis.js node/edge data structures, DESIGN_SYSTEM.md color tokens, three-panel layout, and role-based styling all migrate directly. The design language built in F4c is the spec for F11. **IMPL:** React SPA with Vite. D3 or react-force-graph for coaching tree (same hierarchical UD layout, same role colors, same click-to-panel behavior). DESIGN_SYSTEM.md tokens become CSS custom properties. JSON inject → proper REST API calls to FastAPI backend (F9). Supabase auth for F8 user accounts. Deploy on Railway alongside Neo4j + FastAPI. **Migration path from F4c:** vis.js node/edge schema → D3 data format (near 1:1). DESIGN_SYSTEM.md palette → :root { --navy: #0F1729; ... } CSS variables. Three-panel layout → CSS Grid. coach_component.py wrapper → React component with useEffect + fetch(). Streamlit session_state → React useState/useContext. **Build only after:** Phase 1-3 learnings tell you which queries people actually run, which panels they use, and what the context panel actually needs to show. Don't guess the feature set — let Phase 1-3 data drive the React build spec. |
| --- | --- |

| **A7** | **Query Optimization Agent** **WHAT:** Monitors NL queries users submit, identifies patterns, flags queries that fail or return bad results, and suggests new presets to add to the semantic query layer. Uses F3 observability data (including the >10% failure review threshold) as its primary input. **WHY:** Automated feedback loop that makes the product better based on actual usage without manual log review. **IMPL:** agents/query_optimization/: reads F3 event tracking logs, clusters similar queries, identifies failure patterns. Suggests new presets for common queries that aren't covered. Flags high-failure-rate presets for rewriting based on F3 review thresholds. Validates that new preset parameters conform to semantic vocabulary. |
| --- | --- |

| **A8** | **Data Ingestion Pipeline Agent** **WHAT:** Automates seasonal graph updates — detects coaching changes published to CFBD, runs the ingestion pipeline for new records, validates the delta, and reports what changed. **WHY:** Manual pipeline runs are fine in Phase 0-3. By Phase 4 with paying users, stale data is a churn driver. This agent keeps the graph current with minimal human intervention. **IMPL:** agents/ingestion_pipeline/: detect_changes.py diffs graph vs CFBD API, run_pipeline.py triggers delta ingestion only. Integrates with A1 (data validation) after each update. |
| --- | --- |

| **A9** | **Pricing & Usage Analytics Agent** **WHAT:** Weekly report synthesizing F3 event tracking, subscription data, and engagement metrics: retention risk, feature usage distribution, cohort behavior, experiment suggestions. **WHY:** At Phase 4 scale, gut feel is insufficient. This agent gives you the data to make pricing and product decisions without building a full analytics dashboard. **IMPL:** agents/pricing_analytics/: cohort.py for retention/churn by segment, usage.py for feature adoption from F3 logs. report.py for weekly digest. Feeds pricing tier decisions and feature prioritization. |
| --- | --- |

| **EXIT CRITERIA:** Paying users across Free/Pro/API tiers. Automated graph updates running without manual intervention. Usage data driving feature and pricing decisions. |
| --- |

---

**Phase 5 — Expand the Graph     Year 2+  |  2028 and Beyond**

*Longitudinal depth compounds over time — each year of new data is harder for any competitor starting from scratch to replicate. This is the long-term moat.*

| **Data Layer** | **Source** | **Value Add** |
| --- | --- | --- |
| Coordinator salary data | USA Today annual DB | Salary comps for agents + ADs |
| Recruiting ratings tied to coaching staff | 247Sports / On3 | Player development attribution |
| Transfer portal flows vs. staff changes | CFBD (2019+) | Predictive portal modeling |
| NFL coaching staff history | PFR / manual | College-to-pro graph extension |
| Game film metadata | Future partnership | Formation + personnel analytics |

---

## **Key Milestone Dates**

| **Milestone** | **Target Date** |
| --- | --- |
| F4c vis.js UI complete — Saban tree screenshot | May 2026 |
| Phase 0 complete | Done — 2026-03-29 |
| Phase 1a: F12 player outcomes loaded + validated | July 2026 |
| Phase 1a: F13 recruiting data loaded + validated | July 2026 |
| Phase 1b: First LinkedIn post live (uses player outcome data) | July 2026 |
| Phase 1b: Consistent weekly content | July–October 2026 |
| McIllece General Use license upgrade ($4,500) — trigger condition: at least one carousel-season Substack post published AND measurable paid subscriber conversion signal before committing spend. Do not treat as a fixed calendar date. | Decision gate — not calendar-driven |
| Paid Substack launch | October 2026 |
| Peak carousel content window | November 2026–January 2027 |
| $6K investment recouped | January/February 2027 |
| B2B pilots active (Phase 3) | Mid-2027 |
| SaaS launch (Phase 4) | 2027+ |
| React UI rebuild (F11) | Phase 4 (2027+) |

---

## **Committed Expenses**

| **Item** | **Amount** | **Status** |
| --- | --- | --- |
| McIllece Academic License | $1,500 | Paid |
| McIllece General Use (upgrade) | $4,500 | Locked in — target Sep 2026 |
| Railway Neo4j Hobby Plan | ~$5-10/mo | Active |
| Total committed | ~$6,060+ | |

---

## **UI Architecture — Decision Log**

| **Decision** | **Rationale** | **Revisit At** |
| --- | --- | --- |
| vis.js over Pyvis | Pyvis wraps vis.js but hides layout/styling control. Direct vis.js = full hierarchical UD layout, role-based node sizes/colors, click handlers, hover tooltips. Same CDN dependency. | Never — Pyvis not coming back |
| JSON inject over postMessage | postMessage requires React wrapper component + build step. JSON inject = Python string template replacement, zero extra infra. Works in st.components.v1.html() today. | Phase 4 (swap to API call) |
| Streamlit over React now | Streamlit ships Phase 0 in one session. React would cost 3-4 weeks rebuilding infra while the graph sits idle. Phase 0 exit is a screenshot, not a product launch. | Phase 4 (F11) |
| DESIGN_SYSTEM.md as enforcer | Same pattern as a Claude Code marketplace skill, scoped to this repo. Prepend "Read DESIGN_SYSTEM.md first" to every UI session prompt. Locks palette + component rules across sessions. | Add to when new component patterns emerge |
| Navy palette (#0F1729 base) | Reference: ZTV sports dashboard aesthetic. Dark navy + rounded cards + role-accent colors = premium sports app feel. Matches what agents and ADs see in professional tools. | Phase 4 brand refresh if needed |

---

## **UI Target Mockup — Reference Spec (2026-03-25)**

The user provided a polished mockup of the full "CFB IQ" site. This is the north star for F4c completion and the Phase 4 React rebuild (F11). The current vis.js component is a subset — the gap defines remaining work.

**Mockup element status (updated 2026-03-28):**

| Element | Location | Status |
| --- | --- | --- |
| "CFB IQ" branded logo + gold diamond | Top-left nav | **DONE — Session 12** |
| Tab nav (Coaching Trees, Coordinators, Recruiting, Draft Outcomes, Carousel) | Top bar | **DONE — Session 12** (Coaching Trees active; others placeholder) |
| FAQ / Docs / User avatar (JH) | Top-right | Not built — Phase 4 (auth, F7 docs) |
| Stats bar (HC MENTEES · TOTAL COACHES) | Center panel header | **DONE — Session 12** (live from `GRAPH_DATA.meta`) |
| Achievement badges ("3× NATL CHAMP") | Right panel top-right | Not built — need championship data source |
| SP+ stat card with real values (+16.1) | Right panel | Not built — SP+ data not in current ResultRow |
| "TOP MENTEES — SP+" ranked table | Right panel bottom | Not built — need SP+ per mentee from graph |
| "Screenshot" button | Center panel bottom | Not built |
| Coordinator presets (SEC DCs 2024, OC Hire Grades) | Left sidebar | Not built — F2 presets |
| Conference filter dropdown | Left sidebar | Stubbed in HTML, not wired |
| Role-differentiated node colors | Graph canvas | DONE — `get_best_roles()` + `_resolve_role()` pipeline |
| Navy Streamlit shell (no chrome) | Entire page | **DONE — Session 12** (CSS injection) |
| Graph front and center (no results list) | Main area | **DONE — Session 12** |

**What IS built and matching the mockup:**
- Navy background (#0F1729) on full Streamlit shell
- "CFB IQ" logo + tab nav bar (Coaching Trees active with gold underline)
- Stats bar: coach name · HC mentees · total coaches
- Three-panel vis.js layout (left sidebar, center graph, right detail)
- Hierarchical UD tree with role-colored nodes (HC gold, OC coral, DC blue, POS purple)
- HC gold (#F5C842) root box + ellipse mentees
- Depth slider + role filter in left panel
- Coach detail panel with name, role badge, "Why included" explain block
- Legend (HC, OC, DC, Pos. Coach)
- Barlow Condensed headers, Inter body font, flat surfaces, no shadows

*Last updated: 2026-03-29 — Session 14 (F1): Explain My Result complete. role_display_name() semantic mapping, get_mentee_stints() enrichment query, ResultRow team/years fields, _fetch_direct_mentees() produces rich provenance strings ("Included because: Offensive Coordinator at Alabama (2019–22), coached under Nick Saban."), team/years wired through to vis.js nodes. 29 new tests; 740/740 pass.*
