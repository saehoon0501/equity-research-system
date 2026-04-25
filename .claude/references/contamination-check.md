# Mechanical Contamination Check

**Status:** Load-bearing protection under Path A. This is what makes Path A defensible despite losing model-family diversity for BearCase.

**Purpose:** Catch outputs where the agent is citing memorized pre-cutoff knowledge rather than evidence-grounded research. Mechanical, not semantic — invariant to which model produced the output.

## Why this is the load-bearing defense (under Path A)

Per BUILD_LOG.md Day 1, Path A overrides v2-final §1.3 — all agents run on Anthropic. The semantic-judgment diversity that would catch contamination patterns visible to a different model family is not available.

What remains: every dated claim must reference an `evidence_id` that resolves to a real Evidence Index row whose `source_date` predates the claim's resolution date.

This check is invariant to model choice. A claim like "AAPL revenue grew 23% in Q3 2024" can only pass if there's an Evidence Index row referenced (e.g., AAPL's 10-Q filing) with `source_date` predating the resolution date of the claim. If the agent fabricated the claim from training data without sourcing it, no such row exists, and the check fires.

The Evaluator running semantic checks may also be running on Anthropic and may be subject to the same memorization. The mechanical check doesn't depend on the Evaluator's judgment — it depends on row existence in Postgres.

## The check itself

For each claim in an agent's output:

```
1. Extract every evidence_id reference from the agent's `evidence_index_refs` list
2. For each evidence_id, query Postgres:
   SELECT source_date, source_uri FROM evidence_index WHERE evidence_id = $1
3. If row does not exist → REJECT output (fabricated reference)
4. If row exists, get source_date
5. Determine the claim's resolution date:
   - For predictions: the resolution_date in the prediction record
   - For historical claims: the claim's surfaced_date (today, when memo is being written)
6. Verify source_date <= claim_resolution_date
7. If source_date is AFTER the resolution date → REJECT output
   (this would only happen via fabrication; it's a sanity check)
8. If all evidence_id references resolve to real rows with valid dates → ACCEPT
```

## What "accepted" actually means

Acceptance by the mechanical check is necessary but not sufficient for output release:
- Mechanical check says: the claims have proper sourcing structure
- Process rubric (Evaluator) says: the claims have proper substance and reasoning
- Both must pass before output is released downstream

Either failure → output returns to the agent for revision.

## Edge cases

### Claims without dates

A claim like "Net debt is $2.4B" implicitly is a *current* claim. Its resolution date is today. So the source must predate today, which means it must come from a filing/source already published. Trivially satisfied if the source_date is anything other than the future.

### Forward-looking statements (predictions)

Per `claim_type='prediction'` in Evidence Index. Resolution date is set when the prediction is made (e.g., "Revenue will grow 15% in FY26"; resolution_date = end of FY26). The mechanical check verifies:
- source_date (when the prediction was sourced from, e.g., management guidance) predates surfaced_date
- AND the resolution_date is in the future at surfaced_date

### Sources that update over time

Some sources (Wikipedia, dynamic web pages, real-time databases) change content while keeping the same URL. The check uses `source_date` as the snapshot date — if you cite a Wikipedia article on AAPL today, `source_date = today`. The Evidence Index row records the snapshot moment, not the URL's eternal content. If the page later changes, the row preserves what was true when the claim was made.

### EDGAR filings

Filings have unambiguous filing dates (the date SEC received and stamped them). Use that as `source_date`. For 10-Ks, this is typically 60-90 days after fiscal year end. For 10-Qs, ~45 days after quarter end.

### Earnings call transcripts

`source_date` = call date (usually 1-3 days after earnings release).

### Aggregated data sources (Yahoo Finance summaries, screener outputs)

Use the date the data was retrieved as `source_date`. These are typically Tier 4 sources unless the underlying data is from a Tier 1/2 source explicitly cited.

## Implementation as a hook

When implemented (week 6 per implementation-sequencing.md, but specified here for clarity):

```python
# Pseudocode — actual implementation in week 6 via Claude Code post-sample hook

def post_sample_contamination_check(agent_output, agent_run_id):
    refs = agent_output.evidence_index_refs  # list of UUIDs

    # Step 1: every reference must resolve to a real row
    rows = postgres.query(
        "SELECT evidence_id, source_date FROM evidence_index WHERE evidence_id = ANY($1)",
        [refs]
    )
    found_ids = {r.evidence_id for r in rows}
    missing = set(refs) - found_ids
    if missing:
        return REJECT(f"evidence_id references not in Evidence Index: {missing}")

    # Step 2: for every dated claim, source must predate resolution
    for claim in extract_dated_claims(agent_output):
        evidence_row = next(r for r in rows if r.evidence_id == claim.evidence_id)
        resolution_date = compute_resolution_date(claim)  # today for historical, future for predictions
        if evidence_row.source_date > resolution_date:
            return REJECT(
                f"claim '{claim.text}' cites evidence with source_date "
                f"{evidence_row.source_date} after resolution_date {resolution_date}"
            )

    return ACCEPT
```

## What this check does NOT catch

The mechanical check is rigorous but narrow. It does not catch:

- **Claims without numerical/date/named-fact content** — qualitative descriptors are exempt from Evidence Index population (per `evidence-index-schema.md`). A memo could be all qualitative hand-waving and pass the mechanical check.
- **Misinterpretation of the source** — if the source says "revenue grew 12%" and the agent claims "revenue grew 23%", but cites the right filing, the mechanical check passes. The Evaluator's semantic process rubric is what catches this — but per Path A's documented weakness, that semantic check is also same-model-family and may have the same blind spot.
- **Source manipulation** — if the agent invents a fake filing URL but somehow the URL exists (e.g., it points to a real different company), the mechanical check passes. This requires the operator to spot-check during the manual audit at Checkpoint 3.

The Checkpoint 3 manual audit of 50 random claims (per phasing-plan.md §2.5.2) is the cross-check that catches these failure modes that the mechanical check can't.

## Failure mode if this check is wrong

If the mechanical check has bugs (e.g., always returns ACCEPT, or fails to enforce source_date predates resolution), Path A's load-bearing defense is broken and the system has no contamination protection. Implementation correctness here is the most important piece of the harness.

Test cases for week 6 implementation:
1. Output with all valid claims and proper Evidence Index rows → ACCEPT
2. Output with one claim citing a non-existent evidence_id → REJECT
3. Output with one claim where source_date is after resolution_date → REJECT
4. Output with no Evidence Index references at all → REJECT (zero refs is suspicious; explicit empty refs list with explicit "no claims requiring sourcing" justification is acceptable)
5. Output with prediction claim where resolution_date is in past at surfaced_date → REJECT (self-resolving prediction is incoherent)

These test cases must all pass before the harness is considered functional.
