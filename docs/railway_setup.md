# Railway Neo4j Setup — CFB GraphRAG Migration

This document records the step-by-step procedure for migrating the
CFB GraphRAG graph database from AuraDB free tier to Railway Neo4j,
and documents the resulting Railway instance configuration.

---

## Why We Migrated

AuraDB free tier caps relationships at 400,000. After Phase 0 data
load the graph reached ~337,136 relationships and was projected to
exceed the cap. Railway is already the planned deploy target for
Session 6, so migrating Neo4j now avoids a second disruptive migration
later.

---

## Step 1 — Export from AuraDB

Run from the project root against the **old** AuraDB instance:

```bash
python export_auradb.py
```

This creates `data/migrations/auradb_export_YYYYMMDD/` containing:

| File | Contents |
|---|---|
| `nodes_Player.json` | 97,765 Player nodes |
| `nodes_Team.json` | 1,862 Team nodes |
| `nodes_Coach.json` | 4,216 Coach nodes |
| `nodes_Conference.json` | 74 Conference nodes |
| `rels_PLAYED_FOR.json` | 231,540 PLAYED_FOR rels |
| `rels_COACHED_AT_cfbd.json` | 12,414 COACHED_AT (CFBD source) |
| `rels_COACHED_AT_mcillece.json` | 26,368 COACHED_AT (mcillece season) |
| `rels_COACHED_AT_mcillece_roles.json` | 39,031 COACHED_AT (mcillece per-role) |
| `rels_PLAYED.json` | 26,918 PLAYED rels |
| `rels_IN_CONFERENCE.json` | 702 IN_CONFERENCE rels |
| `rels_MENTORED.json` | 163 MENTORED rels |

> `data/migrations/` is **not** committed to git (listed in `.gitignore`).
> Keep the export directory on your local machine until Railway is verified.

---

## Step 2 — Railway Neo4j Setup

### 2a. Create a Railway project (if not already done)

1. Log in to [railway.app](https://railway.app)
2. Click **New Project → Empty Project**
3. Name it `cfb-graphrag`

### 2b. Add Neo4j service

1. In your Railway project, click **+ New Service → Database → Neo4j**
2. Select **Neo4j 5.x Community**
3. Wait for the service to start (green status)

### 2c. Retrieve connection credentials

From the Neo4j service panel → **Connect** tab:

| Variable | Where to find it |
|---|---|
| `RAILWAY_NEO4J_URI` | "Public Network" → Bolt URL (format: `neo4j+s://…`) |
| `RAILWAY_NEO4J_USER` | Default: `neo4j` |
| `RAILWAY_NEO4J_PASSWORD` | Generated password shown in Connect tab |

### 2d. Add to .env

```dotenv
RAILWAY_NEO4J_URI=neo4j+s://<host>:<port>
RAILWAY_NEO4J_USER=neo4j
RAILWAY_NEO4J_PASSWORD=<generated-password>
```

> These variables are for migration only. After Step 4 the main
> `NEO4J_*` vars will be updated to point to Railway and the
> `RAILWAY_*` vars can be removed.

---

## Step 3 — Import to Railway

Run from the project root (uses `RAILWAY_NEO4J_*` vars):

```bash
python import_to_railway.py
```

The importer:
1. Creates uniqueness constraints
2. Loads nodes in order: Teams → Conferences → Coaches → Players
3. Loads relationships: PLAYED_FOR, COACHED_AT (all three flavors),
   PLAYED, IN_CONFERENCE, MENTORED

Expected runtime: ~10–20 minutes depending on Railway instance
performance and your network latency.

### Dry-run (counts only, no writes)

```bash
python import_to_railway.py --dry-run
```

### Specify a different export directory

```bash
python import_to_railway.py --export-dir=data/migrations/auradb_export_20260322
```

---

## Step 4 — Verify

```bash
python verify_railway.py
```

Expected output — all checks must show `[PASS]`:

```
=== Node Counts ===
  [PASS] Player          expected=  97,765  actual=  97,765
  [PASS] Team            expected=   1,862  actual=   1,862
  [PASS] Coach           expected=   4,216  actual=   4,216
  [PASS] Conference      expected=      74  actual=      74

=== Relationship Counts ===
  [PASS] PLAYED_FOR           expected= 231,540  actual= 231,540
  [PASS] COACHED_AT           expected=  75,457  actual=  75,457
  [PASS] PLAYED               expected=  26,918  actual=  26,918
  [PASS] IN_CONFERENCE        expected=     702  actual=     702
  [PASS] MENTORED             expected=     163  actual=     163

=== Verification Result ===
  ALL CHECKS PASSED — Railway Neo4j matches AuraDB counts exactly.
```

---

## Step 5 — Switch .env to Railway

Once verification passes, update `.env`:

```dotenv
# Before (AuraDB)
NEO4J_URI=neo4j+s://26aa5e73.databases.neo4j.io
NEO4J_USERNAME=26aa5e73
NEO4J_PASSWORD=<auradb-password>

# After (Railway)
NEO4J_URI=neo4j+s://<railway-host>:<port>
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=<railway-password>
```

Run `pytest tests/ -v` after switching to confirm everything still works.

---

## Step 6 — Decommission AuraDB

1. Log in to [console.neo4j.io](https://console.neo4j.io)
2. Select the `26aa5e73` instance
3. Click **Pause** (or **Delete** if confirmed complete)
4. Update this doc with the decommission date below

---

## Migration Status

| Step | Status | Date | Notes |
|---|---|---|---|
| Export from AuraDB | ☐ | | |
| Railway Neo4j created | ☐ | | |
| Import to Railway | ☐ | | |
| Verification passed | ☐ | | |
| .env switched to Railway | ☐ | | |
| AuraDB decommissioned | ☐ | | |

---

## Railway Instance Details

*(Fill in after completing Step 2)*

| Field | Value |
|---|---|
| Railway project | cfb-graphrag |
| Neo4j version | 5.x Community |
| Public Bolt URL | `neo4j+s://…` |
| Region | |
| Created | |

---

## Useful Cypher Verification Queries

Run directly in the Railway Neo4j Browser (`/browser` endpoint):

```cypher
// All node counts
MATCH (n) RETURN labels(n), count(n) ORDER BY count(n) DESC

// All relationship counts
MATCH ()-[r]->() RETURN type(r), count(r) ORDER BY count(r) DESC

// Saban coaching history
MATCH (c:Coach {first_name: 'Nick', last_name: 'Saban'})-[r:COACHED_AT]->(t:Team)
RETURN c.first_name + ' ' + c.last_name AS coach, t.school, r.year, r.role
ORDER BY r.year

// Alabama 2015 coordinators
MATCH (c:Coach)-[r:COACHED_AT]->(t:Team)
WHERE t.school = 'Alabama' AND r.year = 2015
RETURN c.first_name + ' ' + coalesce(c.last_name, '') AS coach,
       r.role, r.role_tier
ORDER BY r.role_tier
```
