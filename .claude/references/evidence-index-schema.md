# Evidence Index Schema and Write Procedure

The Evidence Index is the load-bearing data substrate under Path A. Per v2-final §4.2.5, every claim made by every agent must populate a row before output release. The mechanical contamination check (the load-bearing protection that makes Path A defensible) validates against this index.

## Schema

Postgres table `evidence_index`:

```sql
CREATE TABLE evidence_index (
    evidence_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id             TEXT NOT NULL,           -- 'company-deep-dive', 'bear-case', etc.
    agent_run_id         UUID NOT NULL,           -- groups all claims from one agent invocation
    claim_text           TEXT NOT NULL,           -- the actual claim sentence
    claim_type           TEXT NOT NULL CHECK (claim_type IN
                            ('numerical', 'qualitative', 'prediction', 'dated_fact')),
    source_uri           TEXT NOT NULL,           -- URL or filing reference (e.g., 'sec://10-K/AAPL/2024-Q4')
    source_date          DATE NOT NULL,           -- date of source document (filing date, etc.)
    source_quality_tier  SMALLINT NOT NULL CHECK (source_quality_tier IN (1, 2, 3, 4)),
                                                  -- 1=primary filing/regulatory
                                                  -- 2=company IR/transcript
                                                  -- 3=sell-side/established financial press
                                                  -- 4=retail/blog
    surfaced_date        DATE NOT NULL DEFAULT CURRENT_DATE,
    related_position_id  UUID,                    -- optional FK; null for non-position research
    related_thesis_id    UUID,                    -- optional FK; null for ad-hoc claims
    created_at           TIMESTAMP NOT NULL DEFAULT NOW(),
    storage_tier         TEXT NOT NULL DEFAULT 'hot'
                            CHECK (storage_tier IN ('hot', 'warm', 'cold'))
);

CREATE INDEX idx_evidence_agent_run ON evidence_index(agent_run_id);
CREATE INDEX idx_evidence_position ON evidence_index(related_position_id) WHERE related_position_id IS NOT NULL;
CREATE INDEX idx_evidence_source_date ON evidence_index(source_date);
CREATE INDEX idx_evidence_surfaced ON evidence_index(surfaced_date);
```

## Append-only constraint

The Evidence Index, Predictions DB, and Counterfactual Ledger are all append-only. Postgres enforcement via trigger:

```sql
CREATE FUNCTION prevent_modify() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'evidence_index is append-only — UPDATE/DELETE not permitted';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER evidence_index_no_update
BEFORE UPDATE OR DELETE ON evidence_index
FOR EACH ROW EXECUTE FUNCTION prevent_modify();
```

Storage tier transitions (hot → warm → cold) happen via a separate "shadow" mechanism (move row to a `_warm` partition, not UPDATE), not by mutating the original row. Append-only means the original row is never modified after creation.

## What counts as a "claim" — mandatory population rule

Per v2-final §4.2.5:

> Any sentence containing a numerical value, a date, or a specific named fact about a company beyond identity must populate an Evidence Index row.

### Examples requiring rows

- "ROIC of 18% over the last 5 years" — numerical
- "The company filed an 8-K on March 15, 2024" — dated_fact
- "Revenue grew 23% YoY in Q3 2024" — numerical + dated
- "Margins compressed from 42% to 36% over 2022–2024" — numerical with date range
- "Insider sold 50,000 shares on April 12, 2024" — dated_fact + numerical
- "Net debt is $2.4B" — numerical
- "Customer concentration: top 5 = 38% of revenue" — numerical
- "Forward P/E of 24x" — numerical (but mark source_quality_tier appropriately for analyst data)

### Examples NOT requiring rows (qualitative descriptors are exempt)

- "The company has a strong competitive moat" — qualitative
- "Management has a track record of disciplined capital allocation" — qualitative
- "The business model exhibits operating leverage" — qualitative
- "Customer satisfaction appears high" — qualitative
- "The brand is well-recognized" — qualitative

The qualitative-vs-numerical line is sharp: any specific number, date, or named fact = row required. Subjective characterization without anchoring data = no row.

### Edge cases

- **Claim without source available:** if you cannot cite a source, do not make the claim. The mechanical check will reject the output.
- **Multiple claims in one sentence:** populate one row per distinct fact. "Revenue grew 23% YoY and EPS grew 31%" = two rows.
- **Claim citing prior memo:** valid if prior memo is in repo + the underlying source from that memo is also in Evidence Index. Don't recursively cite memos; cite the original source.
- **Forward-looking statement:** populate as `claim_type='prediction'` with `source_uri` pointing to the forward-looking guidance source.

## Write procedure for agents

When a CompanyDeepDive (or any agent) produces output:

1. **Parse output for claims** per the rule above
2. **For each claim**:
   a. Identify source (filing, transcript, news article, sell-side report, etc.)
   b. Determine `source_quality_tier`
   c. Extract `source_date` (filing date, publication date, etc.)
   d. Generate `evidence_id` (UUID)
3. **Insert row** into `evidence_index` via `mcp__postgres.execute`
4. **Insert reference** in agent output (`evidence_index_refs` field) listing all `evidence_id` values cited
5. **Output is released downstream only after all referenced `evidence_id` values exist as rows**

If step 4 references an `evidence_id` that step 3 didn't insert (e.g., agent fabricated a UUID), the mechanical contamination check (separate procedure, see `contamination-check.md`) catches this at output release time.

## Source quality tier guide

**Tier 1 — primary filing / regulatory** (highest quality, weight ×1.0)
- 10-K, 10-Q, 8-K, S-1, proxy statements
- Form 4 (insider transactions)
- 13F/13G (institutional holdings)
- FDA approvals, regulatory orders
- Court filings (not commentary on them)

**Tier 2 — company IR / transcripts** (high quality, weight ×0.9)
- Earnings call transcripts (verbatim, from a reliable transcript service)
- Investor day presentations (PDFs from company IR site)
- Press releases issued by the company
- Conference presentations (recorded, official)

**Tier 3 — established financial press / sell-side** (moderate, weight ×0.7)
- Bloomberg, Reuters, WSJ, FT articles
- Sell-side analyst reports (cited specifically, not aggregated estimates)
- Industry publications with editorial standards (Barron's, Institutional Investor)

**Tier 4 — retail / blog / aggregated** (low, weight ×0.4)
- Seeking Alpha articles
- Reddit threads (r/wallstreetbets, etc.)
- Twitter/X posts (even from credible accounts)
- Company-watch blogs without editorial standards
- Aggregator sites (Yahoo Finance summaries, etc.)

The Evaluator (`.claude/references/process-rubric.md`) weights process rubric scores by tier:
- A memo whose claims are 80%+ Tier 1 + Tier 2 scores higher on source grounding
- A memo with >40% Tier 4 fails the source grounding criterion regardless of citation density

## Retention tiering

- **Hot** (`storage_tier='hot'`): active watchlist names, full retention, queryable in real-time. Default for new rows.
- **Warm** (`storage_tier='warm'`): closed positions after 4 quarters post-close. Same DB, possibly different partition. Queryable but not in default workspaces.
- **Cold** (`storage_tier='cold'`): after 8 quarters from closure. Migrated to object storage (S3 or equivalent). Queryable with higher latency.

Transitions happen monthly via a separate management routine (not a normal write hook). The transition COPIES the row to the new tier and ARCHIVES (does not delete) the original. Append-only is preserved.

## Verification queries

Used by the mechanical contamination check and audit procedures:

```sql
-- Does evidence_id X exist with source predating claim resolution date Y?
SELECT EXISTS(
    SELECT 1 FROM evidence_index
    WHERE evidence_id = $1 AND source_date <= $2
);

-- All evidence for a specific agent run
SELECT * FROM evidence_index WHERE agent_run_id = $1 ORDER BY created_at;

-- Source quality tier distribution for a memo
SELECT source_quality_tier, COUNT(*)
FROM evidence_index
WHERE agent_run_id = $1
GROUP BY source_quality_tier;

-- All claims about a specific position
SELECT claim_text, source_uri, source_date, source_quality_tier
FROM evidence_index
WHERE related_position_id = $1
ORDER BY surfaced_date DESC;
```
