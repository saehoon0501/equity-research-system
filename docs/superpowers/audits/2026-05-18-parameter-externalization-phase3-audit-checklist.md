# Phase 3 audit checklist — parameters_version → run_parameters_snapshot_id

**Date:** 2026-05-18
**Plan reference:** /review-me v7-final convergence (parameter externalization refactor)
**Migration:** `db/migrations/035_run_parameters_snapshot_fk_repoint.sql`

## Purpose

Per C19 (v6 iteration of /review-me): document per-table audit of UPDATE paths and append-only-guard provenance so future migrations that loosen an append-only guard automatically trigger a re-review of the UPDATE-trigger gap for that table.

The mig 035 spec installs a BEFORE INSERT trigger on every table carrying `parameters_version`. It installs a BEFORE UPDATE trigger only on STATE tables; append-only tables are carved out because their existing `_no_modify` guard trigger already blocks UPDATE entirely.

**Re-review rule (load-bearing):** if any future migration alters or drops an append-only guard listed below, the corresponding table MUST receive a `enforce_run_parameters_snapshot_on_update` trigger. The migration that loosens the guard must include the trigger ADD in the same commit.

## Per-table audit

**Live-DB correction (2026-05-18 apply):** initial Phase 0 audit grepped migration source files and incorrectly listed `audit_provenance` (mig 008). Live-DB inspection during mig 035 application showed `audit_provenance.parameters_version` does NOT exist as a column — the grep matched a schema comment describing the `versions` JSONB blob shape, which embeds `parameters_version` as one of its keys. Audit_provenance is therefore dropped from mig 035 scope (14 tables, not 15). For parameter-lineage on audit_provenance rows, extract `versions->>'parameters_version'` and follow to the recommendation row's `run_parameters_snapshot_id`.

| # | Table | Source mig | Append-only? | Timestamp col arg | Guard trigger function | UPDATE trigger installed by mig 035? | Re-review trigger |
|---|---|---|---|---|---|---|---|
| 1 | `regime_classification_history` | 005 | YES | `created_at` | `regime_classification_no_modify` | NO (carved out) | If `regime_classification_no_modify` is dropped or loosened in a future mig → ADD `regime_classification_enforce_snapshot_update` |
| 2 | `scenarios` | 006 | NO (STATE) | `created_at` | — | YES (`scenarios_enforce_snapshot_update`) | n/a (already installed) |
| 3 | `watchlist` | 007 | NO (STATE) | `added_at` | — | YES (`watchlist_enforce_snapshot_update`) | n/a (already installed) |
| 4 | `execution_recommendations` | 008 | YES | `created_at` | `exec_recs_no_modify` | NO (carved out) | If guard dropped → ADD UPDATE trigger |
| 5 | `mode_classifications` | 008 | YES | `classified_at` | `mode_classifications_no_modify` | NO (carved out) | If guard dropped → ADD UPDATE trigger |
| 6 | `daily_refresh_log` | 009 | YES | `created_at` | `daily_refresh_log_no_modify` | NO (carved out) | If guard dropped → ADD UPDATE trigger |
| 7 | `materiality_events` | 009 | YES | `created_at` | `materiality_events_no_modify` | NO (carved out) | If guard dropped → ADD UPDATE trigger |
| 8 | `anchor_drift_checks` | 010 | YES | `created_at` | `anchor_drift_no_modify` | NO (carved out) | If guard dropped → ADD UPDATE trigger |
| 9 | `materiality_classifier_drift` | 010 | YES | `created_at` | `materiality_drift_no_modify` | NO (carved out) | If guard dropped → ADD UPDATE trigger |
| 10 | `counterfactual_retrievals` | 011 | YES | `created_at` | `counterfactual_retrievals_no_modify` | NO (carved out) | If guard dropped → ADD UPDATE trigger |
| 11 | `premortem` | 012 | YES | `created_at` | `premortem_no_modify` | NO (carved out) | If guard dropped → ADD UPDATE trigger |
| 12 | `operator_overrides` | 013 | YES | `created_at` | `operator_overrides_no_modify` | NO (carved out) | If guard dropped → ADD UPDATE trigger |
| 13 | `calibration_test_results` | 015 | YES | `created_at` | `calibration_test_results_no_modify` | NO (carved out) | If guard dropped → ADD UPDATE trigger |
| 14 | `anchor_drift_review_decisions` | 018 | YES | `created_at` | `anchor_drift_review_decisions_no_modify` | NO (carved out) | If guard dropped → ADD UPDATE trigger |

## Verification queries

After applying mig 035 to dev DB, run the VERIFY block at the bottom of the migration file. Expected counts (applied to live DB 2026-05-18, matched):

- 14 rows with `run_parameters_snapshot_id` column added
- 14 `_pv_xor_rpsi` CHECK constraints
- 14 BEFORE INSERT triggers
- 2 BEFORE UPDATE triggers (scenarios, watchlist)
- 14 COMMENT entries flagging legacy `parameters_version` deprecation

## Backfill convention (per /review-me post-apply iteration 1, defect #9)

The BEFORE INSERT trigger `enforce_run_parameters_snapshot_on_insert` raises when `row_ts >= apply_ts AND run_parameters_snapshot_id IS NULL AND parameters_version IS NULL`. Most of the 14 affected tables declare `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()` (or `added_at` / `classified_at` analogously).

**A legitimate backfill INSERT that omits the timestamp column will receive `NOW() ≥ apply_ts` and be rejected** — even though the writer intends a historical-row backfill. To grandfather a backfill INSERT, the writer MUST explicitly set the timestamp column to a value PRE-apply_ts (i.e., before 2026-05-18 unless a session GUC overrides). Example:

```sql
INSERT INTO regime_classification_history (..., parameters_version, created_at)
VALUES (..., '<legacy-uuid>', '2025-12-01T00:00:00Z');
-- trigger sees row_ts < apply_ts → grandfathered → INSERT proceeds
```

Bypassing the timestamp DEFAULT is the operator's responsibility on any backfill path.

## Sunset plan (mig 036+)

After operator-declared backfill window (TBD; recommended ≥90 days post-mig-035), mig 036 will:

1. DROP COLUMN `parameters_version` from all 14 tables.
2. DROP the three existing FK constraints to `parameters(version_id)` that mig 006 / 007 / 011 declared.
3. DROP the per-table `_pv_xor_rpsi` CHECK constraints (no longer meaningful once legacy column is gone).
4. DROP the BEFORE INSERT trigger's `OR parameters_version IS NULL` clause (legacy column no longer exists to be tested).
5. Backfill plan: any row whose `parameters_version` is non-NULL and `run_parameters_snapshot_id` is NULL at sunset time must either be backfilled (insert a `run_parameters_snapshot` row reconstructed from `parameters_version`'s effective snapshot at the row's `created_at`) or accepted as legacy (set both to NULL).

## INV-2 operator-disambiguation slot — RESOLVED 2026-05-19

Resolved via `/review-me` adjudication 2026-05-19: **TUNABLE**. The two parameters serve unrelated functions:
- `wacc.erp_refresh_drift_bps` (50bps): cache-refresh trigger (when to WebFetch Damodaran's implied-ERP)
- `wacc.erp_sensitivity_band_bps` (100bps): output sensitivity band (perturbation magnitude for `wacc_at_erp_plus_100bp` / `wacc_at_erp_minus_100bp` emitted in `wacc_regime` block)

The 2.0 ratio is coincidental, not methodologically required. Reviewer's empirical falsification: regress `|ΔERP_monthly|` on `|ΔDGS10_monthly|` over Damodaran's monthly implied-ERP series (Jan 2000–present) joined to FRED DGS10. Interpretation A ("2× sensitivity band as safety margin around cache-staleness") requires slope ≈ 1.0 with tight residuals. Empirically slope ~0.3-0.5 with R²<0.3 — ERP and DGS10 are weakly coupled at monthly horizon. This falsifies the "50bps DGS10 drift = 50bps ERP staleness" identity that A's framing requires.

**Implementation applied 2026-05-19:**
- INV-2 retired from `.claude/commands/research-company.md` §1.5 Phase 5 validator (no soft-warn, no hard-fail; validator now skips from INV-1 to INV-3).
- `change_rationale` on both `parameters` rows: override rows inserted 2026-05-19 01:52 UTC with `approved_by = 'review_me_INV-2_adjudication_2026-05-19'`. (Parameters table is append-only; UPDATE rejected by `parameters_guard()` trigger — canonical pattern is INSERT new row with `supersedes_version` chaining the prior `version_id`. Active row per key now reflects the verdict via the `parameters_active` view's DISTINCT ON / latest-effective_at logic.)
- Future perturbation plans sweeping these parameters should treat them as independent single-axis dimensions, NOT joint-perturb to preserve a non-existent ratio constraint.

## Outstanding work (post-Phase 5)

- Backfill any in-flight worktree-managed migrations that diverge in their parameters_version usage from this audit. The 9 active worktrees under `.claude/worktrees/` have their own `db/migrations/` copies; once main lands mig 035, any worktree-local additions to the affected tables must be reconciled before merge.
- Update `/parameters-review` skill to accept the `sweep_tag` arg per Q1=D (testability path). This is downstream of /research-company refactor; tracked separately.
- **Stop-hook architecture revisit (added /review-me v7 convergence 2026-05-18):** the orphan-rescue is currently operationally-finalized via `scripts/reconcile_orphan_snapshots.sh` (cron or manual). Threshold for revisiting Stop-hook architecture: orphan-finalization rate >5/week sustained over 4 consecutive weeks per the observability query below. Current expected rate <1/quarter; if reality diverges, the operator-runnable pattern becomes load-bearing and Stop hook (with verified `$CLAUDE_JOB_DIR` per-session uniqueness + DB credential injection contract) becomes worth the runtime machinery.

## Canonical run_status values (per /review-me v7 convergence 2026-05-18 — supersedes prior 5-value list)

Source of truth: `db/migrations/034_run_parameters_snapshot.sql` column comment lines 76-95 + table-level `COMMENT ON TABLE` waterfall paragraph. Mirrored here for audit cross-reference.

| Status | Emitted by | Runtime semantics |
|---|---|---|
| `NULL` | §1.5 Step 4 INSERT (transient) | in-flight |
| `'completed'` | §6.5 happy-path UPDATE | terminal — best-effort |
| `'rejected'` | §4.5 site (b): evaluator HG fail post-revision-exhaustion ONLY (NO LONGER covers contamination — v7 split) | terminal — best-effort |
| `'failed_contamination'` | §4.5 site (a): contamination check fail (v7 — split from `'rejected'`) | terminal — best-effort |
| `'failed_INV-1'` | §1.5 Step 5 invariant validator | terminal — best-effort |
| `'failed_INV-3'` | §1.5 Step 5 invariant validator | terminal — best-effort |
| `'failed_evaluator_dispatch'` | §4.5 site (c): dispatch infra fail | terminal — best-effort |
| `'failed_uncaught'` | `scripts/reconcile_orphan_snapshots.sh` | terminal — operationally finalized |

**Waterfall semantics (mirrors mig 034 `COMMENT ON TABLE`):** every status except `'failed_uncaught'` is best-effort terminal, set inline by orchestrator prose. If that UPDATE itself fails (DB transient), the row stays NULL and is later finalized to `'failed_uncaught'` by the reconcile script. §1.5 Step 7 DB-unreachable HARD FAIL is pre-INSERT; no snapshot row → waterfall does not apply.

## Observability query — weekly Stop-hook revisit signal

```sql
SELECT
  COUNT(*) AS orphans_finalized_last_7d,
  MIN((error_detail::jsonb->>'orphaned_at')::timestamptz) AS earliest_orphan,
  MAX((error_detail::jsonb->>'orphaned_at')::timestamptz) AS latest_orphan
FROM system_errors
WHERE source = 'orphan_reconciler'
  AND error_type = 'unfinalized_snapshot'
  AND error_detail::jsonb ? 'orphaned_at'
  AND (error_detail::jsonb->>'orphaned_at')::timestamptz >= NOW() - INTERVAL '7 days';
```

Grouped by `error_detail->>'orphaned_at'` (orphan-creation time, not reconciler-INSERT time — matters at sweep scale where reconciler cadence may lag orphan-creation by hours). Existence filter `error_detail::jsonb ? 'orphaned_at'` guards against malformed-row noise. Threshold trigger: >5/week sustained 4 weeks → escalate per Outstanding work item above. Currently a doc-only signpost (operator-run); alerting integration deferred.
