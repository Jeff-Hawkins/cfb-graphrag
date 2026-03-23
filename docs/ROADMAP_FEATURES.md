# CFB Coaching Intelligence Platform — Feature & Agent Roadmap

Prioritized list of features and Claude Code agents to build, organized by phase.
Items within each phase are in priority order. Do not skip ahead — each phase
builds on validated learnings from the previous one.

---

## Phase 0 — Bake Into Core Build (Now, Before Any Content Ships)

### F1: "Explain My Result" Affordance
**What:** Every GraphRAG query response includes a secondary text block explaining
WHY each coach/result appears. Format: "Included because: OC at Alabama (2019–22),
top-15 SP+ defense, coached under Saban, produced 2 Day 1 picks."

**Why:** Makes every screenshot self-explanatory. Directly feeds Phase 1 content
(LinkedIn posts, r/CFB shares). Builds trust in the data. Without this, users
see a graph but don't understand the traversal logic.

**Implementation:**
- Add to GraphRAG response template in S4 pipeline
- Extract traversal path from Cypher result metadata
- Format as human-readable provenance string per result node
- Store as `explanation` field alongside each query result
- Render below each node/card in Streamlit UI

---

### F2: Query Presets ("Jobs To Be Done" Per Segment)
**What:** 15–20 pre-built query templates organized by user segment. Ship as
saved Cypher templates + NL prompt pairs so nobody starts from a blank slate.

**Segments and starter presets:**
- **Agents:** "Find comps for [coach name]", "Which DCs got P5 HC jobs in last
  5 years?", "Salary trajectory for coordinators from [tree]"
- **ADs / Search firms:** "Shortlist OC candidates with top-20 offensive SP+ and
  recruiting track record", "Staff stability vs. win delta for [candidate]",
  "Coordinator success rate from [conference]"
- **Media:** "Notable branches of [Coach X]'s tree that got P4 jobs this cycle",
  "Coaches whose units overachieved talent composite most", "Coaching tree
  visualization for [coach]"
- **Betting:** "Coordinator changes at [team] and next-season SP+ delta",
  "New DC hires and defensive EPA impact year 1"

**Why:** Solves cold-start problem. Demonstrates product range immediately.
Gives you a fixed Cypher query set to optimize and validate during Phase 0
instead of handling arbitrary NL from day one. Also serves as documentation
of what the platform can do.

**Implementation:**
- Create `presets/` directory with YAML files per segment
- Each preset: `name`, `description`, `cypher_template`, `nl_prompt`, `segment`
- Streamlit sidebar: segment selector → preset dropdown → one-click run
- Presets are parameterized (e.g., `{coach_name}`, `{conference}`) with input fields

---

### F3: Event Tracking & In-Product Analytics
**What:** Log every query, export, and interaction from day one. Minimal but
complete: query text, timestamp, segment (if known), result count, whether
user exported/screenshotted, session duration.

**Why:** When you hit Phase 3 and need to make product decisions, you'll have
months of actual usage data instead of guessing. Tracks which presets are
popular, which NL queries fail, which segments engage most.

**Implementation:**
- Lightweight: append JSON lines to a log file or SQLite table
- Fields: `timestamp`, `query_text`, `query_type` (preset vs. freeform),
  `segment`, `result_count`, `exported`, `session_id`
- Weekly summary script that outputs top queries, failure rate, segment breakdown
- Do NOT over-engineer this. JSON lines file is fine for Phase 0–2.

---

### F4: Smart Query Planning in GraphRAG Pipeline (S4 Architecture)
**What:** The S4 GraphRAG pipeline should not be a thin wrapper over Cypher.
Build it with multi-step query planning from the start:
1. Decompose complex NL questions into sub-queries
2. Generate Cypher for each sub-query
3. Validate intermediate results (did this return anything useful?)
4. Retry with alternative traversal strategies if first attempt fails
5. Synthesize final response from validated sub-results

**Why:** This is the difference between a demo and a product. "Show me all DCs
who coached under a top-10 SP+ defense AND later became a P4 HC" requires
two traversals composed together. A naive single-Cypher approach will fail
on most interesting questions. Building this right in S4 means every
downstream feature (presets, content gen, dossiers) works better.

**Implementation:**
- `graphrag/planner.py` — decomposes NL into sub-query plan
- `graphrag/executor.py` — runs Cypher sub-queries with validation
- `graphrag/retry.py` — alternative traversal strategies on failure
- `graphrag/synthesizer.py` — combines sub-results into final response
- Gemini handles NL→plan decomposition and final response synthesis
- Cypher generation is template-based where possible, LLM-generated for novel queries

---

### A1: Data Quality / Validation Agent (Claude Code)
**What:** A Claude Code agent that audits Neo4j data against known ground truth
after each ingestion batch. Also continuously improves MENTORED edge confidence
scores by validating against known coaching trees and flagging edges that
don't match public records.

**Why:** Ingestion will have edge cases — duplicate coach nodes, missing years,
coaches with multiple simultaneous roles. Catching errors before they propagate
into content and graph queries saves you from publishing wrong data.
The mentorship inference improvement piece means your MENTORED edges get
smarter over time — edge confidence scores increase as more validation passes
confirm them, decrease when anomalies are found.

**How to run:**
```
claude-code "Run data validation agent against Neo4j. Check known coaching
tenures: Kirby Smart at Alabama 2007-2015 (various roles), Lane Kiffin OC
Alabama 2014-2016, Jim Leonhard DC Wisconsin 2017-2022. Flag coaches with <2
or >25 COACHED_AT edges. Flag MENTORED edges where coach overlap is <2 seasons.
Check MENTORED edges against known Saban, Meyer, and Fisher trees. Output
validation report with confidence scores."
```

**Implementation:**
- `agents/data_validation/` directory
- `ground_truth.yaml` — known coach tenures for validation (expand over time)
- `validate.py` — runs Cypher queries, compares to ground truth, outputs report
- `anomaly_checks.py` — statistical checks (edge count distributions, missing years)
- `mentorship_confidence.py` — scores MENTORED edges, flags low-confidence ones
- Run after every ingestion batch. Add to CI/CD pipeline later.
- Each run should leave the graph "more right" than the last run

---

## Phase 1 — Content Engine (Months 1–4)

### A2: Content Generation Agent (Claude Code)
**What:** An agent that queries Neo4j, pulls interesting data, and drafts
LinkedIn/Twitter posts or Substack outlines with the data already embedded.

**Why:** You need 4+ posts/month. Writing each one manually from raw Cypher
output is slow. This agent does the data pull + first draft, you edit and publish.
Cuts content production time by 60–70%.

**How to run:**
```
claude-code "Query the Saban coaching tree from Neo4j. Count how many current
P4 head coaches came from his tree. Generate a LinkedIn post draft with a hook,
the key stats, and a Pyvis screenshot description. Tone: analytical but
accessible, not clickbait."
```

**Implementation:**
- `agents/content_gen/` directory
- `templates/` — post templates per platform (LinkedIn, Twitter thread, Substack)
- `queries/` — curated Cypher queries that produce interesting content
- `generate.py` — runs query, formats data into template, outputs draft markdown
- Drafts go to `content/drafts/` for human review before publishing

---

### A3: Competitive Intelligence Monitor (Claude Code)
**What:** An agent that checks CFBD API changelog, ANSRS website, PFF blog,
and r/CFBAnalysis for new developments relevant to your competitive position.

**Why:** You identified CFBD endpoint expansion and ANSRS scope creep as key
risks. This agent watches so you don't have to manually check weekly.

**How to run:**
```
claude-code "Check CFBD GitHub repos for any commits mentioning 'assistant' or
'coordinator' in the last 30 days. Check ANSRS.ai for new product announcements.
Check r/CFBAnalysis for posts about coaching data. Summarize findings and flag
competitive risks."
```

**Implementation:**
- `agents/competitive_intel/` directory
- `sources.yaml` — URLs and RSS feeds to monitor
- `monitor.py` — fetches, diffs against last run, flags changes
- `reports/` — weekly summary markdown files
- Run weekly via cron or manual Claude Code invocation

---

## Phase 2 — Monetization (Months 4–8)

### F5: Coordinator Success Score
**What:** An interpretable composite score for coordinator performance. Components:
weighted SP+/EPA change vs. prior 2 years, staff stability bonus, recruiting
improvement factor. Plus a "Tree Adjustment" prior based on coaching lineage.

**Why:** Raw metrics require expertise to interpret. A single score with
transparent components lets journalists write "Coach X scored 82/100" and
lets agents say "my client is a top-15 DC by Coordinator Success Score."
The methodology breakdown itself becomes great Substack content.

**Why not earlier:** Requires clean SP+/EPA data tied to specific coordinator
tenures, which means COACHED_AT edges and unit performance data both need
to be validated first (Phase 0 work).

**Implementation:**
- `models/coordinator_score.py` — scoring logic with configurable weights
- `models/tree_adjustment.py` — Bayesian prior based on coaching lineage depth
- Components: `unit_performance_delta`, `stability_factor`, `recruiting_delta`,
  `draft_production_rate`, `tree_prior`
- All components visible in UI and exports (transparency = trust)
- Backtest against known successful/unsuccessful coordinator hires

---

### A4: Carousel Season Research Agent (Claude Code)
**What:** When a coordinator gets hired or fired, feed it the name and it
pulls their full history from your graph, generates performance context,
and drafts a quick-take analysis.

**Why:** Speed matters during carousel season. If you can publish a data-driven
take within hours of a hire/fire announcement, you become the source journalists
check. This agent does the research leg in minutes.

**How to run:**
```
claude-code "Breaking: [Name] hired as OC at [School]. Pull their full coaching
history from Neo4j. Get SP+ rankings for units they coached. Get draft picks
from their position groups. Generate a quick-take analysis with the Explain My
Result format. Draft a Twitter thread and LinkedIn post."
```

**Implementation:**
- `agents/carousel_research/` directory
- `research.py` — takes coach name, pulls graph data, generates analysis
- `templates/quick_take.md` — format for rapid-response content
- Integrates with content generation agent for final formatting

---

### A5: Engagement Tracker Agent (Claude Code)
**What:** Pulls Substack stats, LinkedIn post analytics, and Reddit engagement
into a single weekly report. Tracks which content types perform best.

**Why:** Feeds Phase 2 content strategy with data instead of gut feel. Identifies
which topics drive paid Substack conversions.

**Implementation:**
- `agents/engagement/` directory
- `collect.py` — pulls metrics from platform APIs / manual CSV input
- `report.py` — generates weekly summary with trends
- `data/` — historical engagement data for trend analysis

---

## Phase 3 — B2B Validation (Months 8–14)

### F6: Coaching Dossier One-Pager (PDF Export)
**What:** One-click PDF export of a coach's complete profile: bio, roles by year,
tree lineage, unit performance vs. talent, draft/portal outcomes for their
position group, salary/buyout context where available.

**Why:** This is the artifact agents, ADs, and journalists actually pass around.
During Phase 3 pilots, you'd deliver these manually. Productizing it as
one-click export turns pilot learnings into a Phase 4 feature.

**Why not earlier:** The data layers (COACHED_AT + performance + draft outcomes)
need to be validated first, and you need Phase 2 feedback on what format
professionals actually want before committing to a PDF template.

**Implementation:**
- `exports/dossier.py` — generates PDF from coach node + connected data
- Template: 1-page summary + optional detailed appendix
- Includes Coordinator Success Score if available
- Includes "Explain My Result" provenance for all data points
- Uses reportlab or weasyprint for PDF generation

---

### F7: Documentation & Example Query System
**What:** Auto-generated and continuously updated documentation: "How to ask X"
guides, example Cypher queries, API code snippets. Fine-tuned on your actual
query logs and responses so docs mirror real usage patterns.

**Why:** Once external users touch the product (Phase 3 pilots, Phase 4 API),
stale docs kill adoption. This keeps documentation current without manual
maintenance — the highest-ROI ops task for a solo builder with paying users.

**Implementation:**
- `docs/user_guide/` — auto-generated from preset definitions and query logs
- `docs/examples/` — top 20 most-run queries with annotated results
- Agent regenerates docs weekly from F3 event tracking data
- Highlights new presets, most popular queries, and recently added data
- Feeds directly into Phase 4 API documentation

---

### A6: Lead Research & Outreach Agent (Claude Code)
**What:** A single agent that both builds targeted prospect lists AND drafts
personalized outreach. Given a target segment (search firms, agents,
journalists), it researches individuals, builds a clean CSV, and drafts
personalized emails with specific data examples from your graph.

**Why:** Phase 3 requires B2B outreach. Researching targets and writing
personalized emails manually is the biggest time sink. This agent does both
in one workflow — research the target, pull relevant context from your graph
about their world, draft the email with a compelling data hook.

**How to run:**
```
claude-code "Build a prospect list of the top 10 coaching search firms. For
each, find their most recent FBS coaching searches from news. Then draft
personalized outreach emails that include a specific example of how our platform
would have informed their last search. Output: CSV of firms + contacts, and
individual email drafts per firm."
```

**Implementation:**
- `agents/lead_outreach/` directory
- `research.py` — gathers targets from LinkedIn, school directories, media bios
- `list_builder.py` — outputs clean CSV with name, role, org, contact, context
- `draft.py` — generates personalized email per target using graph data
- `templates/` — email templates by target type (agent, search firm, journalist)
- Segments: coaching agents/agencies, FBS ADs/deputies, journalists, betting analysts

---

## Phase 4 — SaaS Productization (Months 14–24)

### F8: Prospect List Workflows
**What:** Users can tag coaches into named lists (e.g., "my clients," "DC shortlist
2027") and attach private notes to coach nodes. Per-account state.

**Why:** Turns the platform from a query tool into a workflow tool people log
into daily during carousel season. This is what makes users sticky.

**Why not earlier:** Requires auth, per-user state, and database layer beyond
Neo4j. Don't build until Phase 3 pilots validate that users want to live
in the tool vs. just pull data from it.

**Implementation:**
- User accounts with auth (Supabase or similar)
- `lists` table: user_id, list_name, coach_ids[]
- `notes` table: user_id, coach_id, note_text, timestamp
- Streamlit sidebar: list management, note viewer on coach detail pages
- Private by default. No sharing features until validated.

---

### F9: Public API (Developer Preview)
**What:** REST or GraphQL endpoint exposing coaching tree, staff history, and
basic performance metrics. Rate-limited, labeled "developer preview."

**Why:** Pulls in power users (CFBAnalysis community, analytics researchers)
who build on top of your data, creating distribution you don't have to pay for.

**Why not earlier:** Requires rate limiting, auth, monitoring, and documentation.
Maintenance burden too high for solo builder before Phase 4. During Phase 1,
publish Cypher query examples on GitHub as a lightweight alternative.

**Implementation:**
- FastAPI or similar lightweight framework
- Endpoints: `/tree/{coach}`, `/staff/{team}/{year}`, `/score/{coach}`
- Rate limiting: 100 req/day free, unlimited for paid tier
- API key auth
- Auto-generated docs (OpenAPI/Swagger) fed by F7 documentation system
- Deploy alongside main app on Railway

---

### F10: In-App Support & Triage Bot
**What:** Embedded in the Streamlit app to answer basic "how do I..." product
questions and triage feature requests / bug reports into a structured backlog.
Hands you summarized feedback, not a raw firehose.

**Why:** Once you have 50+ active users, you can't read every support message
manually. This bot handles tier-1 questions using your F7 docs and routes
everything else into a prioritized backlog.

**Why not earlier:** Before meaningful user volume, you WANT to read every
piece of raw feedback — that's your product research. Automated triage
becomes valuable only when volume exceeds what you can manually process.

**Implementation:**
- `support/triage_bot.py` — answers product questions from F7 docs
- `support/backlog.py` — structures feature requests and bugs into categories
- Weekly digest: summarized feedback, top requests, bug frequency
- Integrates with F3 event tracking for user context on each report

---

### A7: Query Optimization Agent (Claude Code)
**What:** Monitors which NL queries users submit, identifies patterns, flags
queries that fail or return bad results, and suggests new Cypher templates to
add to the presets library.

**Why:** Automated feedback loop that makes the product better based on actual
usage without manual log review.

**Implementation:**
- `agents/query_optimization/` directory
- Reads event tracking logs from F3
- Clusters similar queries, identifies failure patterns
- Suggests new presets for common queries that aren't covered
- Flags Cypher templates with high failure rates for rewriting

---

### A8: Data Ingestion Pipeline Agent (Claude Code)
**What:** Automates seasonal graph updates — detects coaching changes published
to CFBD, runs the ingestion pipeline for new records, validates the delta, and
reports what changed.

**Why:** Manual pipeline runs are fine in Phase 0–3. By Phase 4 with paying
users, stale data is a churn driver. This agent keeps the graph current with
minimal human intervention.

**Implementation:**
- `agents/ingestion_pipeline/` directory
- `detect_changes.py` — diffs current graph state against CFBD API
- `run_pipeline.py` — triggers ingestion for changed records only
- Integrates with A1 (data validation) — runs validation after each update
- Sends summary report on what was added/changed

---

### A9: Pricing & Usage Analytics Agent (Claude Code)
**What:** Weekly report synthesizing F3 event tracking, subscription data, and
engagement metrics into actionable insights: retention risk, feature usage
distribution, cohort behavior, experiment suggestions.

**Why:** At Phase 4 scale, gut feel is insufficient. This agent gives you the
data to make pricing and product decisions without building a full analytics
dashboard.

**Implementation:**
- `agents/pricing_analytics/` directory
- `cohort.py` — retention and churn analysis by segment
- `usage.py` — feature adoption rates from F3 logs
- `report.py` — weekly digest with experiment suggestions
- Feeds pricing tier decisions and feature prioritization

---

*Last updated: Session 3 pre-work — roadmap scaffolded, Phase 0 items identified.*
