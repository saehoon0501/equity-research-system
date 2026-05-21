# G-CHECK-4: counterfactual_ledger write-path verification spec

**Status:** v1 locked 2026-05-22 (closes G-CHECK-4 spec; field execution waits on first tactical-overlay /research-company run).
**Scope:** pre-launch + first-production-run verification that the full Phase 2 JOIN path (ledger insert → content match → resolution-time update → JOIN under partial-NULL → idempotency) is sound before envelopes accumulate.

## Why this verification exists

Phase 2 quadrant analysis (returns spread BUY-HIGH vs BUY-MED) requires JOINing `counterfactual_ledger` to envelope JSON via `run_id`. Iteration 3 of /review-me caught that "row exists" is insufficient verification — if returns columns never populate (resolution update path untested), or the JOIN query returns wrong rows under partial-NULL semantics, or idempotency on double-fire isn't pre-declared, the gap surfaces only at Phase 2 trigger 6-12 months in.

## Substantive finding flagged during this spec drafting

The current write path is **narrower than v5-final implied**.

- Per `db/migrations/030_counterfactual_ledger_high4_redesign.sql` docstring lines 14-15: *"Trigger generalizes to universal: every /research-company run writes 4 rows (one per window: 90d / 1y / 3y / 5y)"* — but the migration only adds columns/indexes/constraints; there is NO automated insert trigger.
- Per `.claude/agents/pm-supervisor.md` §9 step 2: ledger INSERT fires ONLY when `summary_code = SELL OR (summary_code = TRIM AND counterfactual veto fired)`. BUY/HOLD runs do NOT write.
- Grep confirms `pm-supervisor.md` is the SOLE ledger writer.

**Consequence:** BUY-HIGH and BUY-MED runs (the main Phase 2 quadrant rows) currently do NOT generate ledger entries. Phase 2 returns-spread is unrecoverable as-is.

**Pre-launch action required:** pm-supervisor.md §9 must be extended to write ledger rows on BUY summary_codes as well. This is a separate change set from the G-CHECK artifacts; flagging here for the next /research-company spec revision (likely a Section 9 amendment). Without this fix, the rest of this verification spec describes a path that won't have data to traverse.

---

## Verification procedure (operator-driven)

### Phase A — pre-launch synthetic exercise

Run before the first production tactical-overlay invocation. Validates code paths without consuming a real /research-company run.

**A.1 Schema contract check (SQL, no envelope required):**

```sql
-- Verify all columns required for Phase 2 JOIN exist on counterfactual_ledger.
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'counterfactual_ledger'
  AND column_name IN (
    'run_id', 'ticker', 'summary_code', 'conviction', 'window',
    'measurement_date', 'ticker_return_pct', 'vs_sector_etf_return_pct',
    'vs_spy_return_pct', 'gics_sector', 'envelope_id'
  )
ORDER BY column_name;
```

Expected: 11 rows, run_id and ticker NOT NULL, others nullable per HIGH-4 spec.

**A.2 Synthetic insert + readback (SQL):**

```sql
-- Insert a synthetic tactical-overlay style row (BUY conviction MEDIUM, 90d window).
INSERT INTO counterfactual_ledger (
  run_id, ticker, research_date, summary_code, conviction,
  gics_sector, benchmark_etf, "window", measurement_date
) VALUES (
  '00000000-0000-0000-0000-000000000001', 'TEST-GCHECK4', CURRENT_DATE,
  'BUY', 'MEDIUM', 'Information Technology', 'XLK', '90d',
  CURRENT_DATE + INTERVAL '90 days'
);

-- Readback: confirm row exists and tactical-cell fields populate as inserted.
SELECT run_id, ticker, summary_code, conviction, "window", measurement_date
FROM counterfactual_ledger
WHERE run_id = '00000000-0000-0000-0000-000000000001';
```

Expected: 1 row, all 6 columns match the INSERT values.

**A.3 Resolution-update path (SQL — exercises (c)):**

```sql
-- Simulate window-close resolution update (returns columns populated).
UPDATE counterfactual_ledger
SET ticker_return_pct = 5.2,
    benchmark_return_pct = 3.1,
    vs_sector_etf_return_pct = 2.1,
    spy_return_pct = 2.8,
    vs_spy_return_pct = 2.4
WHERE run_id = '00000000-0000-0000-0000-000000000001'
  AND "window" = '90d';

-- Verify update applied.
SELECT run_id, ticker_return_pct, vs_sector_etf_return_pct, vs_spy_return_pct
FROM counterfactual_ledger
WHERE run_id = '00000000-0000-0000-0000-000000000001';
```

Expected: 1 row, returns columns non-NULL and match the UPDATE values.

**A.4 Partial-NULL JOIN semantics (SQL — exercises (d) first half):**

```sql
-- Insert a SECOND synthetic row at 1y window, intentionally NOT resolution-updated.
INSERT INTO counterfactual_ledger (
  run_id, ticker, research_date, summary_code, conviction,
  gics_sector, benchmark_etf, "window", measurement_date
) VALUES (
  '00000000-0000-0000-0000-000000000001', 'TEST-GCHECK4', CURRENT_DATE,
  'BUY', 'MEDIUM', 'Information Technology', 'XLK', '1y',
  CURRENT_DATE + INTERVAL '365 days'
);

-- Phase 2-style JOIN query: read both rows; partial-NULL should appear in 1y row.
SELECT run_id, "window", ticker_return_pct, vs_sector_etf_return_pct, vs_spy_return_pct
FROM counterfactual_ledger
WHERE run_id = '00000000-0000-0000-0000-000000000001'
ORDER BY "window";
```

Expected: 2 rows. 90d row has non-NULL returns; 1y row has NULL returns. The query MUST return BOTH rows (not silently filter NULL returns out — that would silently truncate Phase 2 analysis).

**A.5 Idempotency on resolution double-fire (SQL — exercises (d) second half):**

Pre-declared expected behavior on double-fire of the resolution UPDATE: **overwrite** (newer fill of returns columns replaces older fill — windows roll, more accurate readings supersede earlier ones).

```sql
-- Double-fire: re-run the resolution UPDATE with different values.
UPDATE counterfactual_ledger
SET ticker_return_pct = 5.5,
    benchmark_return_pct = 3.2,
    vs_sector_etf_return_pct = 2.3,
    spy_return_pct = 2.9,
    vs_spy_return_pct = 2.6
WHERE run_id = '00000000-0000-0000-0000-000000000001'
  AND "window" = '90d';

-- Verify overwrite (NOT duplicate insert; NOT no-op).
SELECT COUNT(*) AS row_count, MAX(ticker_return_pct) AS latest_return
FROM counterfactual_ledger
WHERE run_id = '00000000-0000-0000-0000-000000000001'
  AND "window" = '90d';
```

Expected: `row_count = 1`, `latest_return = 5.5` (the newer value). If `row_count = 2`, duplicate-insert anti-pattern is present and must be fixed. If `latest_return = 5.2`, no-op anti-pattern (e.g., trigger blocking updates) is present and must be fixed.

**A.6 Cleanup:**

```sql
DELETE FROM counterfactual_ledger
WHERE run_id = '00000000-0000-0000-0000-000000000001';
```

---

### Phase B — first-production-run verification

When the first real tactical-overlay /research-company run completes:

**B.1 Confirm pm-supervisor.md §9 has been extended to write on BUY** (per finding above). If not, this verification cannot complete — fix pm-supervisor.md first.

**B.2 Identify the run's run_id** (from the operator's terminal log, or from the most recent envelope file: `ls -t memos/envelopes/tactical-overlay__*.json | head -1`).

**B.3 Query the ledger for this run_id:**

```sql
SELECT run_id, ticker, summary_code, conviction, "window", measurement_date,
       ticker_return_pct, vs_sector_etf_return_pct, vs_spy_return_pct
FROM counterfactual_ledger
WHERE run_id = '<extracted_run_id>'
ORDER BY "window";
```

Expected: 4 rows (one per window 90d/1y/3y/5y); returns columns NULL (resolution windows haven't elapsed); summary_code + conviction match the envelope JSON.

**B.4 Cross-reference envelope JSON:**

```bash
jq '.summary_code, .conviction' memos/envelopes/pm-supervisor__<extracted_run_id>.json
```

Expected: matches ledger row content per B.3.

**B.5 If any mismatch:** halt before more production runs accumulate; fix the write path; re-test.

---

## Acceptance

G-CHECK-4 passes when:
- A.1-A.6 all succeed (pre-launch synthetic) AND
- pm-supervisor.md §9 has been extended to write on BUY (substantive finding) AND
- B.1-B.5 all succeed on the first production tactical-overlay run.

If any step fails, log the failure inline in this file and halt further tactical-overlay production runs until resolved. Phase 2 quadrant analysis cannot proceed on a broken JOIN path.
