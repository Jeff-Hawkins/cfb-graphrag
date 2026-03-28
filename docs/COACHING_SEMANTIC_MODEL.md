# Coaching Semantic Model

> Plain-English definitions of every entity, relationship, and vocabulary term in the CFB coaching graph.
> This document is the single source of truth for what names mean across the codebase — presets (F2), explanations (F1), the query planner (F4), and the data validation agent (A1) all speak this vocabulary.

*Last updated: 2026-03-27*

---

## Entities

### Coach
A person who has held a coaching role at one or more FBS programs.

| Attribute | Type | Source | Notes |
|-----------|------|--------|-------|
| `first_name` | string | CFBD | Present on CFBD-sourced nodes |
| `last_name` | string | CFBD | Present on CFBD-sourced nodes |
| `coach_code` | string | McIllece | Stable unique ID for McIllece-sourced nodes |
| `name` | string | derived | Display name (either `first_name + last_name` or resolved from `coach_code`) |

Two populations of Coach nodes exist: CFBD-sourced (keyed by `first_name`/`last_name`) and McIllece-sourced (keyed by `coach_code`). `SAME_PERSON` edges bridge them.

### Team
An FBS football program identified by its canonical CFBD name.

| Attribute | Type | Notes |
|-----------|------|-------|
| `id` | int | CFBD team ID |
| `school` | string | Canonical name (e.g. "Alabama", "San Jos&eacute; State") |
| `conference` | string | Current conference affiliation |
| `abbreviation` | string | Short code |

Nine McIllece school names are mapped to canonical Neo4j names via `TEAM_NAME_MAP` in `expand_roles.py` (e.g. `"MTSU"` &rarr; `"Middle Tennessee"`).

### Player
A student-athlete who appeared on an FBS roster.

| Attribute | Type | Notes |
|-----------|------|-------|
| `id` | int | CFBD player ID |
| `name` | string | Full name |
| `position` | string | Listed position |
| `hometown` | string | Home city/state |

### Conference
A named conference grouping (e.g. "SEC", "Big Ten").

| Attribute | Type |
|-----------|------|
| `name` | string |

### Season *(logical, not always a node)*
A calendar year during which games and coaching assignments occur. Seasons appear as properties on edges (`year`, `start_year`, `end_year`) and as an explicit `Season` node where needed.

### Game *(embedded in PLAYED edges)*
A single contest between two teams in a given season and week. Game data lives on `PLAYED` relationship properties rather than a standalone node.

---

## Semantic Concepts (not stored as nodes, but central to queries)

### Coaching Role
The specific job a coach held during a season. Roles are stored on `COACHED_AT` edges and classified into three tiers:

| Tier | Abbreviations | Examples |
|------|---------------|----------|
| **Coordinator** | HC, AC, OC, DC, PG, PD, RG, RD | Head Coach, Offensive Coordinator, Pass Defense Coordinator |
| **Position Coach** | QB, RB, WR, OL, DL, DB, LB, TE, DE, DT, CB, SF, IB, OB, IR, GC, OT, FB, OR | Quarterbacks, Defensive Line, Cornerbacks |
| **Support** | ST, RC, OF, DF, KO, KR, PR, PK, PT, NB, FG | Special Teams, Recruiting Coordinator, Defensive Assistant |

Full role legend: `ingestion/expand_roles.py::ROLE_LEGEND`.

### Side of Ball / Unit
Roles belong to an offensive, defensive, or neutral unit. The `same_unit()` filter in `ingestion/role_constants.py` governs which mentorship edges are valid (e.g. a DC cannot mentor a WR coach).

| Unit | Roles |
|------|-------|
| Offensive | OC, QB, RB, WR, OL, TE, PG, RG, OF, IR, GC, OT, FB, OR |
| Defensive | DC, DL, DB, LB, DE, DT, CB, SF, IB, OB, PD, RD, DF, NB |
| Neutral | HC, AC, ST, RC, KO, KR, PR, PK, PT, FG |

### Head Coach (HC)
A coach whose best role at a program in a given season is HC. HCs are the roots of coaching trees and the primary subjects of tree queries.

### Coordinator (OC / DC)
Offensive or Defensive Coordinator — the tier between HC and position coaches. Coordinators are the most common subjects of carousel-season analysis.

### Coaching Tree / Mentorship
The directed graph of influence relationships between coaches. If Coach A was a senior staff member and Coach B served under them for 2+ consecutive seasons at the same program, A *mentored* B. Trees are rooted at a head coach and fan out by depth.

### Mentorship Confidence
Each `MENTORED` edge carries a `confidence_flag`:
- **STANDARD** — direction is reliable (default)
- **REVIEW_REVERSE** — mentee's prior career suggests influence may flow the other way
- **REVIEW_MUTUAL** — long bidirectional relationship; direction is ambiguous

---

## Relationships

### COACHED_AT
`(:Coach)-[:COACHED_AT]->(:Team)`

Three flavors coexist, distinguished by `source`:

| `source` value | Granularity | Key properties |
|----------------|-------------|----------------|
| `None` (CFBD) | Career span | `title`, `start_year`, `end_year` |
| `"mcillece"` | One edge per coach-season | `coach_code`, `year`, `team_code`, `roles` (list) |
| `"mcillece_roles"` | One edge per coach-season-role | `coach_code`, `year`, `team_code`, `role`, `role_abbr`, `role_tier` |

### MENTORED
`(:Coach)-[:MENTORED {confidence_flag}]->(:Coach)`

Directed: mentor &rarr; mentee. Inferred from staff overlap with role priority (HC > OC/DC > position coach), 2+ consecutive season requirement, same-unit filter, and four suppression rules. 14,219 unique pairs on Railway.

### PLAYED_FOR
`(:Player)-[:PLAYED_FOR {year, jersey}]->(:Team)`

`year` is the calendar season (2015&ndash;2025), not academic year.

### IN_CONFERENCE
`(:Team)-[:IN_CONFERENCE]->(:Conference)`

### PLAYED
`(:Team)-[:PLAYED {game_id, home_score, away_score, season, week}]->(:Team)`

### SAME_PERSON
`(:Coach)-[:SAME_PERSON {match_type, confidence}]->(:Coach)`

Bridges CFBD coach node &rarr; McIllece coach node for the same individual.

---

## Cypher Examples

Each example is annotated with the semantic concepts it exercises.

### 1. Full coaching tree (depth 1&ndash;4)

*Concepts: Coach, Coaching Tree, MENTORED, depth*

```cypher
// All mentees within 4 levels of Nick Saban
MATCH path = (root:Coach {first_name: "Nick", last_name: "Saban"})
             -[:MENTORED*1..4]->(mentee:Coach)
WITH mentee, min(length(path)) AS depth
RETURN mentee.first_name + ' ' + mentee.last_name AS name, depth
ORDER BY depth, name
```

### 2. Head-coach mentees only

*Concepts: Coaching Role, HC, role_tier filter*

```cypher
// Direct mentees of Saban who became head coaches
MATCH (root:Coach {first_name: "Nick", last_name: "Saban"})
      -[:MENTORED]->(mentee:Coach)
      -[r:COACHED_AT]->(:Team)
WHERE r.role_abbr = 'HC' AND r.source = 'mcillece_roles'
RETURN DISTINCT mentee.coach_code AS coach, mentee.first_name AS first
```

### 3. Coaches who worked in two conferences

*Concepts: Coach, Team, Conference, COACHED_AT, IN_CONFERENCE*

```cypher
// Coaches with stints in both SEC and Big Ten
MATCH (c:Coach)-[:COACHED_AT]->(t1:Team)-[:IN_CONFERENCE]->(conf1:Conference {name: "SEC"})
MATCH (c)-[:COACHED_AT]->(t2:Team)-[:IN_CONFERENCE]->(conf2:Conference {name: "Big Ten"})
WHERE t1 <> t2
RETURN DISTINCT c.first_name + ' ' + c.last_name AS coach
```

### 4. Shortest mentorship path between two coaches

*Concepts: Coaching Tree, MENTORED, shortest path*

```cypher
// Shortest mentorship chain from Kirby Smart to Lincoln Riley
MATCH (a:Coach {first_name: "Kirby", last_name: "Smart"}),
      (b:Coach {first_name: "Lincoln", last_name: "Riley"}),
      path = shortestPath((a)-[:MENTORED*]-(b))
RETURN [n IN nodes(path) | n.first_name + ' ' + n.last_name] AS chain,
       length(path) AS hops
```

### 5. Coordinator career arc

*Concepts: Coaching Role, Coordinator, Season, role_tier*

```cypher
// Every role Kirby Smart held, year by year (McIllece per-role edges)
MATCH (c:Coach {first_name: "Kirby", last_name: "Smart"})
      -[r:COACHED_AT]->(t:Team)
WHERE r.source = 'mcillece_roles'
RETURN r.year AS season, t.school AS team, r.role AS role, r.role_tier AS tier
ORDER BY r.year
```

### 6. Staff overlap at a program

*Concepts: Team, Season, Coaching Role, Side of Ball*

```cypher
// Alabama defensive staff in 2019
MATCH (c:Coach)-[r:COACHED_AT]->(t:Team {school: "Alabama"})
WHERE r.source = 'mcillece_roles'
  AND r.year = 2019
  AND r.role_tier IN ['COORDINATOR', 'POSITION_COACH']
  AND r.role_abbr IN ['DC', 'DL', 'DB', 'LB', 'DE', 'DT', 'CB', 'SF', 'IB', 'OB']
RETURN c.coach_code AS coach, r.role AS role
ORDER BY r.role_tier, r.role
```

### 7. Mentorship confidence audit

*Concepts: Mentorship Confidence, confidence_flag*

```cypher
// All edges flagged for directional review
MATCH (a:Coach)-[m:MENTORED]->(b:Coach)
WHERE m.confidence_flag <> 'STANDARD'
RETURN a.coach_code AS mentor, b.coach_code AS mentee,
       m.confidence_flag AS flag
ORDER BY flag, mentor
```

### 8. Cross-source identity bridge

*Concepts: SAME_PERSON, Coach identity*

```cypher
// Find the McIllece node linked to a CFBD coach
MATCH (cfbd:Coach {first_name: "Jimbo", last_name: "Fisher"})
      -[:SAME_PERSON]->(mc:Coach)
RETURN mc.coach_code AS mcillece_code
```

---

## Semantic Vocabulary & Data Contracts

### Vocabulary rules

The terms defined above are the **canonical vocabulary** for this project. All user-facing text — preset names, explanation strings, log fields, documentation — must use these terms, not raw Neo4j property names.

| Instead of... | Write... |
|---------------|----------|
| `r.role_abbr = 'OC'` | "Offensive Coordinator" |
| `r.source = 'mcillece_roles'` | "McIllece staff records" |
| `r.role_tier = 'COORDINATOR'` | "coordinator-level role" |
| `m.confidence_flag` | "mentorship confidence" |
| `COACHED_AT` edge | "coaching stint" or "tenure" |

### Data contracts (enforced by A1)

Every entity and relationship in the graph must satisfy these invariants. The A1 Data Validation Agent checks these after every ingestion batch.

**Coach nodes:**
- CFBD-sourced: `first_name` and `last_name` are non-empty strings.
- McIllece-sourced: `coach_code` is a non-empty string and unique within McIllece nodes.

**COACHED_AT edges:**
- All edges: `source` is one of `None`, `"mcillece"`, `"mcillece_roles"`.
- `source="mcillece_roles"` edges: `role_abbr` is a valid key in `ROLE_LEGEND`; `role_tier` is one of `COORDINATOR`, `POSITION_COACH`, `SUPPORT`; `year` is an integer in range 2005&ndash;2025.
- `source=None` (CFBD) edges: `start_year` &le; `end_year`; both are positive integers.

**MENTORED edges:**
- `confidence_flag` is one of `STANDARD`, `REVIEW_REVERSE`, `REVIEW_MUTUAL`.
- Mentor and mentee are distinct Coach nodes (no self-loops).
- The pair satisfies the 2+ consecutive season overlap rule at the same program.
- The pair passes the same-unit filter (no cross-unit mentorship, e.g. DC &rarr; WR coach).
- Four suppression rules are satisfied: prior-HC (two-part), same-level coordinator peers, min-2-consecutive-years, no-self-loops.

**SAME_PERSON edges:**
- Exactly one direction: CFBD node &rarr; McIllece node.
- `match_type` and `confidence` are non-null.

**Team nodes:**
- `id` is a positive integer and unique.
- `school` is non-empty and matches the canonical CFBD name (McIllece names are mapped via `TEAM_NAME_MAP`).

**Player nodes:**
- `id` is a positive integer and unique.
- `name` is non-empty.

**PLAYED_FOR edges:**
- `year` is an integer in range 2015&ndash;2025.

---

## How This Model Connects to Features

| Feature | How it uses the semantic model |
|---------|-------------------------------|
| **F1 Explain My Result** | Explanation strings use semantic names ("Offensive Coordinator at Alabama, 2019&ndash;2021") not raw properties (`r.role_abbr`, `r.year`). |
| **F2 Query Presets** | Preset YAML files use semantic vocabulary (Coach, Season, Coordinator, Conference) and act as contracts between the UI and the graph — no raw schema leaks to users. |
| **F3 Event Tracking** | Logs record `query_type` (preset vs freeform), `segment`, and `result_count`. Preset failure rates are tracked against this model's contracts. |
| **F4 Smart Query Planning** | The classifier and planner reason over semantic concepts (tree query, performance comparison, coaching pipeline) not Cypher syntax. |
| **A1 Data Validation** | Enforces the data contracts listed above after every ingestion batch. |
