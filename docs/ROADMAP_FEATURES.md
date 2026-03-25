# **CFB Coaching Intelligence Platform**

Feature & Agent Roadmap — Unified View

*Last updated: 2026-03-24  |  Items within each phase are in priority order. Do not skip ahead.*

Each phase builds on validated learnings from the previous one. Features (F) are product capabilities. Agents (A) are Claude Code automation workflows.

| **Phase** | **Focus** | **Timeline** | **Features** | **Agents** |
| --- | --- | --- | --- | --- |
| Phase 0 | Core Build | Now → May 2026 | F1, F2, F3, F4, F4b | A1 |
| Phase 1 | Content Engine | Months 1–4 (Jun–Oct 2026) | — | A2, A3 |
| Phase 2 | Monetize Attention | Months 4–8 (Oct 2026–Jan 2027) | F5 | A4, A5 |
| Phase 3 | B2B Validation | Months 8–14 (Carousel 2026–27) | F6, F7 | A6 |
| Phase 4 | SaaS Productize | Months 14–24 (2027+) | F8, F9, F10 | A7, A8, A9 |
| Phase 5 | Expand the Graph | Year 2+ (2028+) | Data expansion | — |

**Phase 0 — Core Build     Now → May 2026**

*Everything built in Phase 0 must work before a single post ships. Bad data in content = credibility destroyed before you have any.*

| **F1** | **"****Explain My Result****"**** Affordance** **WHAT: **Every GraphRAG response includes a secondary text block explaining WHY each coach/result appears. Format: "Included because: OC at Alabama (2019-22), top-15 SP+ defense, coached under Saban, produced 2 Day 1 picks." **WHY: **Makes every screenshot self-explanatory. Directly feeds Phase 1 content. Without this, users see a graph but don't understand the traversal logic. **IMPL:** Add to GraphRAG response template in S4 Extract traversal path from Cypher result metadata Store as explanation field alongside each query result Render below each node/card in Streamlit UI |
| --- | --- |

| **F2** | **Query Presets — Jobs To Be Done Per Segment** **WHAT: **15-20 pre-built query templates organized by user segment (Agents, ADs/Search Firms, Media, Betting). Saved Cypher templates + NL prompt pairs so nobody starts from a blank slate. **WHY: **Solves cold-start problem. Demonstrates product range immediately. Gives a fixed Cypher query set to optimize and validate during Phase 0 instead of handling arbitrary NL from day one. **IMPL:** Create presets/ directory with YAML files per segment Each preset: name, description, cypher_template, nl_prompt, segment Streamlit sidebar: segment selector → preset dropdown → one-click run Presets are parameterized (e.g., {coach_name}, {conference}) with input fields |
| --- | --- |

| **F3** | **Event Tracking ****&**** In-Product Analytics** **WHAT: **Log every query, export, and interaction from day one. Fields: query text, timestamp, segment, result count, exported/screenshotted, session duration. **WHY: **When Phase 3 requires product decisions, you'll have months of actual usage data. Tracks which presets are popular, which NL queries fail, which segments engage most. **IMPL:** Lightweight: append JSON lines to log file or SQLite table Fields: timestamp, query_text, query_type (preset vs. freeform), segment, result_count, exported, session_id Weekly summary script outputting top queries, failure rate, segment breakdown Do NOT over-engineer — JSON lines file is fine for Phase 0-2 |
| --- | --- |

| **F4** | **Smart Query Planning in GraphRAG Pipeline (S4 Architecture)** **WHAT: **Multi-step query planning: (1) Classify intent into TREE_QUERY │ PERFORMANCE_COMPARE │ PIPELINE_QUERY │ CHANGE_IMPACT │ SIMILARITY via classifier.py. (2) Decompose complex NL into sub-queries via planner.py. (3) Generate Cypher per sub-query. (4) Validate intermediate results. (5) Retry on failure. (6) Synthesize final response. **WHY: **This is the difference between a demo and a product. Complex questions require composed traversals — a naive single-Cypher approach fails on most interesting queries. The intent classifier routes queries to the right Cypher template before the planner runs, dramatically improving accuracy. **IMPL:** graphrag/classifier.py — classifies NL intent into 5 buckets (single Gemini call, returns intent + confidence) graphrag/planner.py — decomposes NL into sub-query plan using classified intent graphrag/executor.py — runs Cypher sub-queries with validation graphrag/retry.py — alternative traversal strategies on failure graphrag/synthesizer.py — combines sub-results into final response Gemini handles NL plan decomposition and final response synthesis Cypher generation is template-based where possible, LLM-generated for novel queries **Status: IN PROGRESS — 2026-03-23** - classifier.py implemented: single Gemini call → 5-bucket routing with confidence score; graceful fallback on bad response - get_coaching_tree() added to graph_traversal.py: McIllece MENTORED traversal, role_filter, max_depth 1–4, path_coaches provenance - retriever.py wired end-to-end: classify_intent → extract_entities → resolve_coach_entity → intent-routed traversal → Gemini synthesis - SAME_PERSON identity edges added to schema (CFBD ↔ McIllece); ingestion/match_coach_identity.py + loader/load_identity_edges.py written - google-generativeai → google-genai SDK migration complete across all graphrag/ modules - planner.py implemented 2026-03-23: single Gemini call → EntityBundle + SubQueryPlan dataclasses; TraversalFn enum (5 values incl. COMBINE) prevents injection; max_depth defaults to 4 with LLM override for scope-limiting phrases ("direct reports only" → 1 etc.); ready=False on missing entities or Gemini failure; fallback plan returned, never raises; 15 new tests, 266/266 pass - executor.py implemented 2026-03-23: ExecutionResult dataclass; execute_plan() with Kahn's topo-sort, cycle detection, per-sub-query error isolation; entity resolution hook for GET_COACHING_TREE (coach_name → mc_coach_code); combine_results() aggregates PERFORMANCE_COMPARE-style plans; 18 new tests, 284/284 pass
 - retry.py implemented 2026-03-23: RetryStrategy protocol + RetryOutcome dataclass; ReduceDepthStrategy (fires on timeout/too-large error signals, lowers max_depth by 1); FallbackTraversalStrategy (fires when GET_COACHING_TREE returns empty or errors, swaps to GET_COACH_TREE); execute_with_retry() wrapper with bounded retries and strategy metadata; 28 new tests, 368/368 pass
 - synthesizer.py implemented 2026-03-23: SynthesisInput + SynthesizedResponse + ResultRow dataclasses; synthesize_response() produces primary NL answer + per-coach F1-style "Explain My Result" provenance strings; handles GET_COACHING_TREE, GET_COACH_TREE fallback, COMBINE, SHORTEST_PATH, GET_COACHES_IN_CONFERENCES; degrades gracefully on partial results; retry metadata surfaced in warnings; 56 new tests, 368/368 pass
 - **Status: COMPLETE — 2026-03-23** — all 5 F4 modules done (classifier, planner, executor, retry, synthesizer). Full pipeline wired: NL → classify → plan → execute → retry → synthesize.
 - _explain_coaching_tree_row enriched 2026-03-23: accepts optional COACHED_AT fields (role, team, start_year, end_year, draft_info); produces roadmap-target format "OC at Alabama (2019–22), coached under Saban." when metadata present; sports-notation year abbreviation (2019–22 not 2019–2022); graceful fallback to depth-based string when fields absent; 10 new tests.
 - LimitRoleFilterStrategy added 2026-03-23: fires when GET_COACHING_TREE with role_filter returns empty result (conservative — zero rows only); relaxes role_filter to None and retries same traversal before falling back to GET_COACH_TREE; wired into _DEFAULT_STRATEGIES as reduce_depth → limit_role_filter → fallback_traversal; execute_with_retry type hint updated; 15 new tests (unit + integration). 395/395 pass.
 - Streamlit wired to F4 pipeline 2026-03-23: retrieve_with_graphrag() replaces legacy hand-rolled NL→Cypher flow in retriever.py; GraphRAGQueryResult dataclass bundles SynthesizedResponse + intent + root_name for the UI; answer_question() kept as thin string wrapper; UI displays primary answer + per-coach F1 Explain My Result rows in expanders + Pyvis coaching-tree graph (depth-coloured nodes, explanation as tooltip) + collapsed pipeline-warnings expander; preset buttons (Saban demo, SEC+Big Ten, Smart→Riley) bound to session_state; graceful error handling; 12 new tests, 407/407 pass. Phase 0 exit path now reachable from the UI. |
| --- | --- |

| **F4b** | **Precomputed Tree Narratives** **WHAT: **Pre-build polished coaching tree outputs for the top 10 coaches (Saban first). Store as node properties in Neo4j. Use as reliable Phase 1 content source and GraphRAG fallback for high-traffic queries. **WHY: **Runtime LLM generation requires QA every time. Precomputed narratives give you manually reviewed, screenshot-ready outputs for the queries that will be 80% of your traffic. Faster responses, better content, and a fallback when Cypher generation fails on complex traversals. **IMPL:** Run Saban tree query manually during S4, review output, write polished version Store as narrative property on Coach node in Neo4j Repeat for top 10 trees: Saban, Meyer, Fisher, Riley, Smart, Sarkisian, Stoops, Dabo, Harbaugh, Belichick (CFB connection) GraphRAG retriever checks for precomputed narrative before running full pipeline Precomputed narratives also feed A2 Content Generation Agent directly **Status: IN PROGRESS — 2026-03-23** - graphrag/narratives.py implemented: set_coach_narrative() / get_coach_narrative() (keyed by coach_code); get_coach_narrative_by_name() (single Cypher — resolves CFBD→SAME_PERSON→McIllece path, falls back to direct McIllece name match); get_head_coach_tree_summary() returns TreeSummary dataclass with hc_mentees + all_mentees for manual narrative authoring. - retriever.py updated: narrative_used: bool field added to GraphRAGQueryResult; TREE_QUERY fast-path checks for precomputed narrative after plan build — skips execute/retry/synthesize pipeline entirely when narrative found; graceful fallback on Neo4j error. - scripts/author_narrative_saban.py: CLI with --coach-name / --coach-code / --save flags; fetch mode prints HC mentees + all-mentees depth summary; save mode reads narrative from .txt file and calls set_coach_narrative with round-trip verification. Works for all top-10 coaches via --coach-code override. - 21 new tests (test_narratives.py) + 14 new retriever tests (TestNarrativeFastPath); 441/441 pass. - scripts/author_narrative_saban.py verified against live Railway graph: Saban resolved via McIllece name search (coach_code=1457; SAME_PERSON edges not yet loaded on Railway). Live tree data: 14 direct HC mentees (Kirby Smart, Lane Kiffin, Steve Sarkisian, Mario Cristobal, Billy Napier, Mike Locksley, Bill O'Brien, Jim McElwain, Jeremy Pruitt, Brent Key, Charles Huff, Charles Kelly, Curt Cignetti, Kyle Flood), 221 total HC mentees, 2,763 total mentees (depth 1–4). Cypher bugs fixed: (1) parameterized depth in [:MENTORED*1..$depth] → now interpolated as literal; (2) head(collect()) path ordering → pre-sorted by length(path). - Remaining: write narratives/saban.txt, run --save to store in Neo4j, verify fast-path end-to-end in Streamlit.
 - **Status: IN PROGRESS — 2026-03-24** — MENTORED edge blocker resolved. Full rebuild complete.
   - Rule 1 two-part fix in `infer_mentored_edges_v2()`: Part A (mentee was HC at THIS team during any overlap year) + Part B (mentee held any HC role strictly before overlap_start at any program). Old single check `y < overlap_start` missed same-year-as-start cases.
   - Rule 1 suppression: 1,861 → 3,036. Total edges: 22,020 → 20,932 on Railway.
   - Cycle detection added to `get_head_coach_tree_summary()` in `graphrag/narratives.py` (post-query filter on both `all_rows` and `hc_rows`). Fixes "Nick Saban at depth 2" bug in `author_narrative_saban.py`.
   - Deleted 2 bad inbound MENTORED edges to Saban (Kevin Steele→Saban, Kirby Smart→Saban) via `scripts/delete_saban_inbound_mentored.py`.
   - Verified clean Saban tree: **8 direct HC mentees** (Kirby Smart, Lane Kiffin, Steve Sarkisian, Mario Cristobal, Billy Napier, Bill O'Brien, Jim McElwain, Jeremy Pruitt — Locksley removed, see note), **112 total HC mentees**, **2,070 total mentees** (d1:33, d2:219, d3:685, d4:1133).
   - 8/10 prior-HC coaches removed from Saban tree. Remaining 2 are legitimate: Mike Locksley (depth 2 via Saban→Wolford→Locksley; Locksley was OC before becoming HC) and Clay Helton (depth 3 via Saban→Lupoi→Heyward→Helton; Heyward/Helton overlapped before Helton became HC).
   - 553 → 556 tests passing (3 new: 2 cycle-detection tests in test_narratives.py, 1 Rule 1 Part A variant in test_mentored_dry_run.py).
   - Next: write narratives/saban.txt and run `python scripts/author_narrative_saban.py --coach-code 1457 --save`. |
| --- | --- |

| **A1** | **Data Quality / Validation Agent** **WHAT: **Audits Neo4j data against known ground truth after each ingestion batch. Validates MENTORED edge confidence scores against known coaching trees (Saban, Meyer, Fisher). Flags anomalies. **WHY: **Ingestion will have edge cases — duplicates, missing years, coaches with multiple roles. Catching errors before they propagate into content saves you from publishing wrong data. **IMPL:** agents/data_validation/: ground_truth.yaml, validate.py, anomaly_checks.py, mentorship_confidence.py Run after every ingestion batch. Each run leaves the graph more right. Claude Code prompt: 'Run data validation agent against Neo4j. Check known coaching tenures: Kirby Smart at Alabama 2007-2015, Lane Kiffin OC Alabama 2014-2016. Flag coaches with <2 or >25 COACHED_AT edges. Flag MENTORED edges where coach overlap is <2 seasons. Output validation report.' **Status: PARTIALLY COMPLETE — 2026-03-23.** Built: ingestion/migrations/add_mentored_confidence_flag.py (idempotent STANDARD baseline), ingestion/flag_mentored_edges.py (detects ~8,000+ REVIEW_REVERSE edges, KNOWN_REVERSE seeds McNeill/Riley), ingestion/role_constants.py (COORDINATOR_ROLES, ASSISTANT_ROLES, ALL_ROLES, validate_role()), synthesizer + retriever updated to surface confidence_flag in UI. 464/464 tests pass. Remaining: ground_truth.yaml, general anomaly checks (coaches with <2 or >25 COACHED_AT edges, MENTORED overlap <2 seasons). Note: confidence_flag layer will need re-run after MENTORED edge inference logic is fixed next session. **Status: IN PROGRESS — 2026-03-23** - MENTORED edge confidence_flag schema added: ingestion/migrations/add_mentored_confidence_flag.py sets confidence_flag='STANDARD' on all existing edges (idempotent, WHERE IS NULL guard). Valid values: STANDARD / REVIEW_REVERSE / REVIEW_MUTUAL. - ingestion/flag_mentored_edges.py implemented: flag_suspicious_mentored_edges(driver) queries all McIllece MENTORED edges where mentee held HC/coordinator role before the earliest overlap year; sets confidence_flag='REVIEW_REVERSE'; applies KNOWN_REVERSE hardcoded pairs (McNeill/Riley seeded); generates reports/mentored_flag_report.md with FCS filter caveat noted. - graphrag/graph_traversal.py: get_coaching_tree() now returns confidence_flag (last MENTORED edge in path) per result row. - graphrag/synthesizer.py: ResultRow gains confidence_flag field; _explain_coaching_tree_row() appends '[relationship direction flagged for review]' when flag != STANDARD; _rows_from_coaching_tree() passes confidence_flag through. - graphrag/retriever.py: GraphRAGQueryResult docstring documents confidence_flag passthrough via result_rows. - 23 new tests in tests/test_flag_mentored_edges.py; 464/464 pass. - ingestion/role_constants.py created 2026-03-23: COORDINATOR_ROLES (9 roles: HC/OC/DC/PD/PG/RD/RG/ST/RC), ASSISTANT_ROLES (DF/OF), ALL_ROLES (all 38 McIllece legend codes including AC), validate_role() helper; module-level assertions enforce subset/disjoint invariants at import time. - flag_mentored_edges.py import swapped from expand_roles._COORDINATOR_ABBRS to role_constants.COORDINATOR_ROLES; _PRIOR_ROLE_ABBRS now wraps COORDINATOR_ROLES via frozenset(). - loader/load_staff.py: validate_role() called per role in every staff record before Neo4j writes; unknown codes emit logger.warning (non-blocking, ingested unchanged). - 29 new tests in tests/test_role_constants.py (cross-referenced against ROLE_LEGEND for completeness); 493/493 pass. - Remaining for full A1: build ground_truth.yaml, validate.py, anomaly_checks.py for general ingestion auditing beyond MENTORED confidence.
 - **Same-unit filter added to infer_mentored_edges_v2() — 2026-03-24.** OFFENSIVE_ROLES (14), DEFENSIVE_ROLES (14), NEUTRAL_ROLES (10) frozensets added to role_constants.py — partition all 38 McIllece codes. same_unit(mentor_role, mentee_role) helper blocks cross-unit MENTORED edges (e.g. DC → WR coach) while HC/neutral mentors pass any mentee; None/unknown roles fall back to permissive. Filter applied after Rules 1–3 in infer_mentored_edges_v2(); suppressed edges collected via _suppressed_unit_edges kwarg for dry-run reporting. run_mentored_dry_run.py updated to print before/after counts + 10-edge suppressed sample. 45 new tests (601 total, all passing). Dry run against Railway pending before Neo4j rebuild. |
| --- | --- |

| **EXIT CRITERIA: **One screenshot of the Saban coaching tree that makes people stop scrolling. The graph must be visually impressive and the query must be explainable. |
| --- |

**Phase 1 — Content Engine     Months 1–4  |  June–October 2026**

*The only job in Phase 1 is proving demand through content. 1 LinkedIn post/week with Pyvis visualizations, cross-posted to X. Methodology breakdowns on r/CFBAnalysis (6K members). Cross-post to r/CFB (4.4M) during carousel season. Track engagement, DMs, and inbound obsessively. USF football background = credibility edge. Do not sell anything yet.*

| **A2** | **Content Generation Agent** **WHAT: **Queries Neo4j, pulls interesting data, and drafts LinkedIn/Twitter posts or Substack outlines with the data already embedded. **WHY: **You need 4+ posts/month. Writing each one manually from raw Cypher output is slow. This agent does the data pull + first draft, you edit and publish. Cuts content production time 60-70%. **IMPL:** agents/content_gen/: templates/ per platform, queries/ of curated Cypher, generate.py Drafts go to content/drafts/ for human review before publishing Claude Code prompt: 'Query the Saban coaching tree from Neo4j. Count how many current P4 head coaches came from his tree. Generate a LinkedIn post draft with a hook, the key stats, and a Pyvis screenshot description. Tone: analytical but accessible, not clickbait.' |
| --- | --- |

| **A3** | **Competitive Intelligence Monitor** **WHAT: **Checks CFBD API changelog, ANSRS website, PFF blog, and r/CFBAnalysis weekly for new developments relevant to your competitive position. **WHY: **CFBD endpoint expansion and ANSRS scope creep are the two key risks to your moat. This agent watches so you don't have to manually check weekly. **IMPL:** agents/competitive_intel/: sources.yaml with URLs and RSS feeds, monitor.py diffs against last run, reports/ directory of weekly markdown summaries Run weekly via cron or manual Claude Code invocation |
| --- | --- |

| **EXIT CRITERIA: **Consistent weekly content publishing. Track: engagement rate per post, DMs received, inbound from journalists or agents. Any single viral post (>10K impressions) validates the content strategy. |
| --- |

**Phase 2 — Monetize Attention     Months 4–8  |  October 2026–January 2027**

*Substack free + paid tier ($8-10/mo). November-January carousel window = peak publishing. Coordinator performance grades, position coach draft production, coaching tree evolution. Target 200-500 paid subs = $2K-5K/mo. Upgrade McIllece Academic to General Use license ($4,500) in September/October 2026 before carousel season monetization.*

| **F5** | **Coordinator Success Score** **WHAT: **An interpretable composite score for coordinator performance. Components: weighted SP+/EPA change vs. prior 2 years, staff stability bonus, recruiting improvement factor, plus a Tree Adjustment prior based on coaching lineage. **WHY: **Raw metrics require expertise to interpret. A single score lets journalists write 'Coach X scored 82/100' and agents say 'my client is a top-15 DC by CSS.' The methodology itself becomes Substack content. **IMPL:** models/coordinator_score.py with configurable weights models/tree_adjustment.py for Bayesian prior based on coaching lineage depth All components visible in UI and exports (transparency = trust) Backtest against known successful/unsuccessful coordinator hires |
| --- | --- |

| **A4** | **Carousel Season Research Agent** **WHAT: **When a coordinator gets hired or fired, feed it the name and it pulls their full graph history, generates performance context, and drafts a quick-take analysis within minutes. **WHY: **Speed matters during carousel season. If you can publish a data-driven take within hours of a hire/fire announcement, you become the source journalists check. **IMPL:** agents/carousel_research/: research.py pulls graph data, templates/quick_take.md format Integrates with content generation agent (A2) for final formatting Trigger on breaking news; output Twitter thread + LinkedIn post draft |
| --- | --- |

| **A5** | **Engagement Tracker Agent** **WHAT: **Pulls Substack stats, LinkedIn post analytics, and Reddit engagement into a single weekly report. Tracks which content types perform best. **WHY: **Feeds Phase 2 content strategy with data instead of gut feel. Identifies which topics drive paid Substack conversions vs. just free engagement. **IMPL:** agents/engagement/: collect.py from platform APIs / manual CSV, report.py generates weekly summary with trends data/ directory for historical trend analysis |
| --- | --- |

| **EXIT CRITERIA: **200+ paid Substack subscribers at $8-10/mo. At least one journalist citation during carousel season. $6K initial investment recouped by January/February 2027. |
| --- |

**Phase 3 — B2B Validation     Months 8–14  |  Carousel Season 2026–27**

*Free pilot with 2-3 coaching agents during hiring season. White-label data proposal to Parker Executive Search or Collegiate Sports Associates. Learn what pros actually query, what format they need, what they would pay. Do not build SaaS yet — test with manual delivery first.*

| **F6** | **Coaching Dossier One-Pager (PDF Export)** **WHAT: **One-click PDF export of a coach's complete profile: bio, roles by year, tree lineage, unit performance vs. talent, draft/portal outcomes for their position group, salary/buyout context where available. **WHY: **This is the artifact agents, ADs, and journalists actually pass around. During Phase 3 pilots, deliver these manually. Productizing as one-click export turns pilot learnings into a Phase 4 feature. **IMPL:** exports/dossier.py generates PDF from coach node + connected data 1-page summary + optional detailed appendix Includes Coordinator Success Score and Explain My Result provenance Uses reportlab or weasyprint for PDF generation |
| --- | --- |

| **F7** | **Documentation ****&**** Example Query System** **WHAT: **Auto-generated and continuously updated documentation: 'How to ask X' guides, example Cypher queries, API code snippets. Fine-tuned on actual query logs and responses. **WHY: **Once external users touch the product in Phase 3 pilots and Phase 4 API, stale docs kill adoption. This keeps documentation current without manual maintenance — highest-ROI ops task for a solo builder. **IMPL:** docs/user_guide/ auto-generated from preset definitions and query logs docs/examples/ top 20 most-run queries with annotated results Agent regenerates weekly from F3 event tracking data |
| --- | --- |

| **A6** | **Lead Research ****&**** Outreach Agent** **WHAT: **Builds targeted prospect lists AND drafts personalized outreach. Given a target segment (search firms, agents, journalists), it researches individuals, builds a CSV, and drafts emails with specific data hooks from your graph. **WHY: **Phase 3 requires B2B outreach. Researching targets and writing personalized emails manually is the biggest time sink. This agent does both in one workflow. **IMPL:** agents/lead_outreach/: research.py, list_builder.py (CSV output), draft.py (personalized emails), templates/ by target type Segments: coaching agents, FBS ADs, journalists, betting analysts Claude Code prompt: 'Build a prospect list of the top 10 coaching search firms. For each, find their most recent FBS coaching searches from news. Draft personalized outreach emails that include a specific example of how our platform would have informed their last search.' |
| --- | --- |

| **EXIT CRITERIA: **At least 2 active B2B pilots (coaching agent or search firm). Clear signal on what format pros want, what they query, and what they would pay. White-label proposal delivered to at least one search firm. |
| --- |

**Phase 4 — SaaS Productization     Months 14–24  |  2027+**

*Deploy on Railway. Tiered pricing: Free (3 queries/day) / Pro $29/mo / API $299/mo. Build features based on Phase 1-3 learnings — which queries people actually ask, which vizs resonate, what pros need. Graph DB + GraphRAG layer = moat (2yr head start).*

| **F8** | **Prospect List Workflows** **WHAT: **Users can tag coaches into named lists (e.g., 'my clients,' 'DC shortlist 2027') and attach private notes to coach nodes. Per-account state. **WHY: **Turns the platform from a query tool into a workflow tool people log into daily during carousel season. This is what makes users sticky and reduces churn. **IMPL:** User accounts with auth (Supabase) lists table: user_id, list_name, coach_ids[] notes table: user_id, coach_id, note_text, timestamp Private by default. No sharing features until validated. |
| --- | --- |

| **F9** | **Public API (Developer Preview)** **WHAT: **REST or GraphQL endpoint exposing coaching tree, staff history, and basic performance metrics. Rate-limited, labeled 'developer preview.' **WHY: **Pulls in power users (CFBAnalysis community, analytics researchers) who build on top of your data, creating distribution you don't have to pay for. **IMPL:** FastAPI endpoints: /tree/{coach}, /staff/{team}/{year}, /score/{coach} Rate limiting: 100 req/day free, unlimited paid. API key auth. Auto-generated docs (OpenAPI/Swagger) fed by F7. Deploy on Railway. |
| --- | --- |

| **F10** | **In-App Support ****&**** Triage Bot** **WHAT: **Embedded in Streamlit app to answer 'how do I...' product questions and triage feature requests / bug reports into a structured backlog. **WHY: **Once you have 50+ active users, you can't read every support message manually. Before that, you WANT raw feedback — it's product research. Build this only when volume exceeds manual capacity. **IMPL:** support/triage_bot.py answers from F7 docs support/backlog.py structures requests into categories Weekly digest of summarized feedback. Integrates with F3 event tracking. |
| --- | --- |

| **A7** | **Query Optimization Agent** **WHAT: **Monitors NL queries users submit, identifies patterns, flags queries that fail or return bad results, and suggests new Cypher templates to add to the presets library. **WHY: **Automated feedback loop that makes the product better based on actual usage without manual log review. **IMPL:** agents/query_optimization/: reads F3 event tracking logs, clusters similar queries, identifies failure patterns Suggests new presets for common queries that aren't covered Flags high-failure-rate Cypher templates for rewriting |
| --- | --- |

| **A8** | **Data Ingestion Pipeline Agent** **WHAT: **Automates seasonal graph updates — detects coaching changes published to CFBD, runs the ingestion pipeline for new records, validates the delta, and reports what changed. **WHY: **Manual pipeline runs are fine in Phase 0-3. By Phase 4 with paying users, stale data is a churn driver. This agent keeps the graph current with minimal human intervention. **IMPL:** agents/ingestion_pipeline/: detect_changes.py diffs graph vs CFBD API, run_pipeline.py triggers delta ingestion only Integrates with A1 (data validation) after each update |
| --- | --- |

| **A9** | **Pricing ****&**** Usage Analytics Agent** **WHAT: **Weekly report synthesizing F3 event tracking, subscription data, and engagement metrics: retention risk, feature usage distribution, cohort behavior, experiment suggestions. **WHY: **At Phase 4 scale, gut feel is insufficient. This agent gives you the data to make pricing and product decisions without building a full analytics dashboard. **IMPL:** agents/pricing_analytics/: cohort.py for retention/churn by segment, usage.py for feature adoption from F3 logs report.py for weekly digest. Feeds pricing tier decisions and feature prioritization. |
| --- | --- |

| **EXIT CRITERIA: **Paying users across Free/Pro/API tiers. Automated graph updates running without manual intervention. Usage data driving feature and pricing decisions. |
| --- |

**Phase 5 — Expand the Graph     Year 2+  |  2028 and Beyond**

*Longitudinal depth compounds over time — each year of new data is harder for any competitor starting from scratch to replicate. This is the long-term moat.*

| **Data Layer** | **Source** | **Value Add** |
| --- | --- | --- |
| Coordinator salary data | USA Today annual DB | Salary comps for agents + ADs |
| Recruiting ratings tied to coaching staff | 247Sports / On3 | Player development attribution |
| Transfer portal flows vs. staff changes | CFBD (2019+) | Predictive portal modeling |
| NFL coaching staff history | PFR / manual | College-to-pro graph extension |
| Game film metadata | Future partnership | Formation + personnel analytics |

## **Key Milestone Dates**

| **Milestone** | **Target Date** |
| --- | --- |
| Phase 0 complete — Saban tree visual | May 2026 |
| First LinkedIn post live | June 2026 |
| Consistent weekly content (Phase 1) | June–October 2026 |
| McIllece General Use license upgrade | September 2026 |
| Paid Substack launch | October 2026 |
| Peak carousel content window | November 2026–January 2027 |
| $6K investment recouped | January/February 2027 |
| B2B pilots active (Phase 3) | Mid-2027 |
| SaaS launch (Phase 4) | 2027+ |

## **Committed Expenses**

| **Item** | **Amount** | **Status** |
| --- | --- | --- |
| McIllece Academic License | $1,500 | Paid |
| McIllece General Use (upgrade) | $4,500 | Locked in — target Sep 2026 |
| Railway Neo4j Hobby Plan | ~$5-10/mo | Active |
| Total committed | ~$6,060+ |  |

*Last updated: 2026-03-24 — MENTORED edge rebuild complete with corrected Rule 1 (two-part: same-team HC during overlap + global prior-HC before overlap_start). Railway count: 20,932 edges (down from 22,020). Rule 1 suppression: 3,036 (up from 1,861). Clean Saban tree: 8 direct HC, 112 total HC, 2,070 total mentees (d1:33, d2:219, d3:685, d4:1133). Cycle detection added to get_head_coach_tree_summary(). 556/556 tests pass. F4b next: write narratives/saban.txt and store via --save.*