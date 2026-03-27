# Precomputed Coaching Tree Narratives (F4b)

Polished, manually reviewed narrative strings for the top 10 coaches.
Once stored in Neo4j, the GraphRAG retriever returns these instantly for
any TREE_QUERY about that coach — no LLM call, no Cypher, no variance.

## Authoring workflow

1. **Get the structured data:**
   ```bash
   python scripts/author_narrative_saban.py --coach-name "Nick Saban"
   # or for others:
   python scripts/author_narrative_saban.py --coach-name "Kirby Smart"
   ```
   This prints the HC mentees (depth-sorted), all mentees by depth, and
   the coach_code you'll need for the --save step.

2. **Write the narrative** in the corresponding `.txt` file here.
   Aim for 150–300 words. Target audience: journalists, agents, ADs.
   Tone: analytical, factual, no hype. Lead with the most striking stat.

3. **Store it in Neo4j:**
   ```bash
   python scripts/author_narrative_saban.py \
       --coach-code <code> \
       --save narratives/<coach>.txt
   ```
   The script verifies the round-trip before confirming.

4. **Test the fast-path** by running a Saban tree query in the Streamlit
   app and confirming `result.narrative_used is True` in the logs.

## Priority order (Phase 0 → Phase 1)

| File | Coach | coach_code | Status |
|---|---|---|---|
| saban.txt | Nick Saban | 1457 | Written — ready to --save |
| harbaugh.txt | Jim Harbaugh | 1416 | Written — ready to --save |
| meyer.txt | Urban Meyer | 1170 | TODO |
| smart.txt | Kirby Smart | 709 | TODO |
| sarkisian.txt | Steve Sarkisian | 1062 | TODO |
| swinney.txt | Dabo Swinney | 244 | TODO |
| fisher.txt | Jimbo Fisher | 583 | TODO |
| riley.txt | Lincoln Riley | 1440 | TODO |
| stoops.txt | Bob Stoops | 83 | TODO |

## What makes a good narrative

- Open with the headline number: "X current P4 head coaches trace back to Saban."
- Name the most prominent direct mentees explicitly.
- Note 1–2 depth-2 branches that are themselves significant trees.
- End with a provenance note: years at Alabama, total staff coached under him.
- Keep it screenshot-ready — someone should be able to post this as a
  LinkedIn caption without editing.
