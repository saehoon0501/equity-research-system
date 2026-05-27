# G-CHECK-4: counterfactual_ledger write-path verification spec (v2)

**Status:** v2 locked 2026-05-22 (folds Reviewer C iteration-1 catches: A.6 DELETE-impossible → BEGIN/ROLLBACK pattern; A.5 column scope explicit; B.3 row-count grounded in code, not migration docstring intent; Q4 §9-extension remedy defended via consensus item #4).
**Scope:** pre-launch + first-production-run verification that the full Phase 2 JOIN path (ledger insert → content match → resolution-time update → JOIN under partial-NULL → idempotency) is sound before envelopes accumulate.

## Why this verification exists

Phase 2 quadrant analysis (returns spread BUY-HIGH vs BUY-MED) requires JOINing `counterfactual_ledger` to envelope JSON via `run_id`. v5-final iteration 3 caught that "row exists" is insufficient — need insert + content + resolution-update + JOIN-under-partial-NULL + idempotency. Reviewer C iteration-1 then caught critical bugs in v1 of this verification spec.

## Critical correction from v1: A.6 cleanup was DELETE-impossible

Migration 030 line 148 enforces append-only via a `BEFORE UPDATE OR DELETE` trigger that raises `'counterfactual_ledger is append-only — DELETE not permitted'`. v1's A.6 `DELETE WHERE run_id` would ALWAYS fail, leaving permanent synthetic test pollution.

**v2 fix:** Phase A is wrapped in `BEGIN; ... ROLLBACK;` — all synthetic INSERTs are rolled back at the end, leaving no DB state changes. The ROLLBACK bypasses the trigger because no row ever commits.

## v2 substantive design clarification: pm-supervisor.md §9 extension IS aligned with consensus item #4

Reviewer C iteration-1 Q4 flagged that extending §9 to write on BUY would "invert the original design intent (TRIM-without-veto is noise)." This concern is REFUTED by re-reading mig 030 docstring lines 14-16:

> "Trigger generalizes to universal: every /research-company run writes 4 rows (one per window: 90d / 1y / 3y / 5y) per Consensus Item #4 (was: only PASS/REJECT bins triggered)."

The HIGH-4 consensus (2026-05-16) explicitly RE-DESIGNED the ledger to be universal-write. The current pm-supervisor.md §9 narrowness (SELL/TRIM+veto only) is the bug — it never implemented the consensus item #4 intent. Extending §9 to write on BUY (and 4 rows per run) realigns to consensus, not corruption.

**Implication:** a separate tactical_ledger table is NOT needed. The fix is to extend pm-supervisor.md §9 to:
1. Write on every summary_code (BUY/HOLD/TRIM/SELL), not just SELL/TRIM+veto.
2. Loop over the 4 windows {90d, 1y, 3y, 5y} per run, emitting 4 INSERT rows.

This is the change-set required before Phase B can succeed.

---

## Phase A — pre-launch synthetic exercise (v2 — transaction-wrapped, no commits)

Run before the first production tactical-overlay invocation. Validates code paths AND trigger semantics without leaving DB state changes.

**A.1 Schema contract check (SQL, no envelope required, READ-ONLY — no transaction needed):**

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

Expected: 11 rows.

**A.2-A.5 transaction-wrapped synthetic exercise (SQL — entire block rolls back):**

```sql
BEGIN;

-- A.2 Synthetic insert: BUY conviction MEDIUM at 90d window.
INSERT INTO counterfactual_ledger (
  run_id, ticker, research_date, summary_code, conviction,
  gics_sector, benchmark_etf, "window", measurement_date
) VALUES (
  '00000000-0000-0000-0000-000000000001', 'TEST-GCHECK4', CURRENT_DATE,
  'BUY', 'MEDIUM', 'Information Technology', 'XLK', '90d',
  CURRENT_DATE + INTERVAL '90 days'
);

-- A.2 Readback: confirm content match.
SELECT run_id, ticker, summary_code, conviction, "window", measurement_date
FROM counterfactual_ledger
WHERE run_id = '00000000-0000-0000-0000-000000000001';
-- Expected: 1 row matching the INSERT.

-- A.3 Resolution-update (COMPLETION FIELDS ONLY per mig 030 lines 169-174):
--   Allowed-to-change: measurement_date, ticker_return_pct, benchmark_return_pct,
--                      vs_sector_etf_return_pct, spy_return_pct, vs_spy_return_pct.
--   Forbidden-to-change: run_id, ticker, summary_code, conviction, envelope_id,
--                        "window", research_date, gics_sector, benchmark_etf.
UPDATE counterfactual_ledger
SET ticker_return_pct = 5.2,
    benchmark_return_pct = 3.1,
    vs_sector_etf_return_pct = 2.1,
    spy_return_pct = 2.8,
    vs_spy_return_pct = 2.4
WHERE run_id = '00000000-0000-0000-0000-000000000001'
  AND "window" = '90d';
-- Expected: UPDATE applied; trigger permits because only completion fields changed.

-- Negative check (v2 NEW): attempting to mutate a guarded column MUST raise.
-- Comment-block; uncomment to verify trigger semantics if needed:
-- UPDATE counterfactual_ledger SET summary_code = 'TRIM' WHERE run_id = '00000000-...01';
-- Expected: ERROR — trigger raises 'counterfactual_ledger guarded column'.

-- A.4 Partial-NULL JOIN semantics: insert 2nd row at 1y, deliberately unresolved.
INSERT INTO counterfactual_ledger (
  run_id, ticker, research_date, summary_code, conviction,
  gics_sector, benchmark_etf, "window", measurement_date
) VALUES (
  '00000000-0000-0000-0000-000000000001', 'TEST-GCHECK4', CURRENT_DATE,
  'BUY', 'MEDIUM', 'Information Technology', 'XLK', '1y',
  CURRENT_DATE + INTERVAL '365 days'
);

-- Phase 2-style JOIN candidate (this is the QUERY SHAPE Phase 2 will use;
-- the spec for Phase 2 will define the canonical query, but the column set
-- below is the minimum needed for a quadrant analysis):
SELECT run_id, "window", ticker_return_pct, vs_sector_etf_return_pct, vs_spy_return_pct
FROM counterfactual_ledger
WHERE run_id = '00000000-0000-0000-0000-000000000001'
ORDER BY "window";
-- Expected: 2 rows. 90d returns non-NULL; 1y returns NULL.
-- The query MUST return BOTH rows (not silently filter NULL via INNER JOIN semantics
-- when Phase 2's actual query is written).

-- A.5 Idempotency on resolution double-fire (completion-field-scoped per mig 030).
-- Pre-declared expected behavior: OVERWRITE (newer fill supersedes older).
UPDATE counterfactual_ledger
SET ticker_return_pct = 5.5,
    benchmark_return_pct = 3.2,
    vs_sector_etf_return_pct = 2.3,
    spy_return_pct = 2.9,
    vs_spy_return_pct = 2.6
WHERE run_id = '00000000-0000-0000-0000-000000000001'
  AND "window" = '90d';

SELECT COUNT(*) AS row_count, MAX(ticker_return_pct) AS latest_return
FROM counterfactual_ledger
WHERE run_id = '00000000-0000-0000-0000-000000000001'
  AND "window" = '90d';
-- Expected: row_count = 1, latest_return = 5.5.
-- row_count = 2 → duplicate-insert anti-pattern (should never happen on UPDATE).
-- latest_return = 5.2 → no-op anti-pattern (trigger blocks UPDATE silently — investigate).

ROLLBACK;
-- Phase A leaves no DB state changes; the trigger never sees a COMMIT, so
-- the append-only constraint is not violated and no cleanup is needed.
```

**A.6 (v2 — removed):** v1 had a separate cleanup step that was impossible. v2 folds cleanup into the `ROLLBACK` at the end of Phase A. No separate cleanup step exists; nothing to clean up.

---

## Phase B — first-production-run verification (v2 — row count grounded)

When the first real tactical-overlay /research-company run completes:

**B.1 (v2 — precondition expanded):** confirm pm-supervisor.md §9 has been extended to:
- Write on every summary_code (BUY/HOLD/TRIM/SELL) — per consensus item #4
- Loop over the 4 windows {90d, 1y, 3y, 5y} per run, emitting 4 INSERT rows

If either is unimplemented, halt B.2-B.5 — the verification cannot complete on a partial implementation. This is a SEPARATE change set from the G-CHECK artifacts; flag for the next /research-company spec revision as a blocking dependency.

**B.2 Identify the run's run_id** (from the operator's terminal log, or the most recent envelope file):

```bash
ls -t memos/envelopes/tactical-overlay__*.json 2>/dev/null | head -1 \
  | sed -E 's|.*tactical-overlay__([^.]+)\.json|\1|'
```

**B.3 (v2 — row count corrected):** query ledger for this run_id:

```sql
SELECT run_id, ticker, summary_code, conviction, "window", measurement_date,
       ticker_return_pct, vs_sector_etf_return_pct, vs_spy_return_pct
FROM counterfactual_ledger
WHERE run_id = '<extracted_run_id>'
ORDER BY "window";
```

Expected: **depends on the §9 extension implementation** (B.1 precondition).
- If §9 writes 1 row per run (current behavior, even after BUY-extension): expect 1 row, "window" = '90d' or whatever the default-emit value is.
- If §9 writes 4 rows per run per consensus item #4 intent: expect 4 rows, one per window {90d, 1y, 3y, 5y}.

v1 incorrectly asserted "expect 4 rows" without grounding it in current code. v2 makes the count contingent on the §9 extension status, which B.1 verifies before proceeding.

**B.4 Cross-reference envelope JSON:**

```bash
jq '.summary_code, .conviction' memos/envelopes/pm-supervisor__<extracted_run_id>.json
```

Expected: matches ledger row content per B.3.

**B.5 If any mismatch:** halt before more production runs accumulate; fix the write path; re-test.

---

## Acceptance

G-CHECK-4 v2 passes when:
- A.1 succeeds (read-only) AND
- A.2-A.5 succeed inside the BEGIN/ROLLBACK block (no DB state changes after rollback) AND
- pm-supervisor.md §9 has been extended (per consensus item #4) — verified by B.1 AND
- B.2-B.5 all succeed on the first production tactical-overlay run.

If any step fails, log the failure inline in this file and halt further tactical-overlay production runs until resolved. Phase 2 quadrant analysis cannot proceed on a broken JOIN path.
