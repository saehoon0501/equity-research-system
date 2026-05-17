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

After applying mig 035 to dev DB, run the VERIFY block at the bottom of the migration file. Expected counts:

- 15 rows with `run_parameters_snapshot_id` column added
- 15 `_pv_xor_rpsi` CHECK constraints
- 15 BEFORE INSERT triggers
- 2 BEFORE UPDATE triggers (scenarios, watchlist)
- 15+ COMMENT entries flagging legacy `parameters_version` deprecation

## Sunset plan (mig 036+)

After operator-declared backfill window (TBD; recommended ≥90 days post-mig-035), mig 036 will:

1. DROP COLUMN `parameters_version` from all 15 tables.
2. DROP the three existing FK constraints to `parameters(version_id)` that mig 006 / 007 / 011 declared.
3. DROP the per-table `_pv_xor_rpsi` CHECK constraints (no longer meaningful once legacy column is gone).
4. DROP the BEFORE INSERT trigger's `OR parameters_version IS NULL` clause (legacy column no longer exists to be tested).
5. Backfill plan: any row whose `parameters_version` is non-NULL and `run_parameters_snapshot_id` is NULL at sunset time must either be backfilled (insert a `run_parameters_snapshot` row reconstructed from `parameters_version`'s effective snapshot at the row's `created_at`) or accepted as legacy (set both to NULL).

## INV-2 operator-disambiguation slot

The orchestrator validator (§1.5 Phase 1.5) ships with INV-2 (WACC drift × sensitivity 2× ratio) as a **soft warning**, not a hard fail. Operator answer needed:

> Is the relationship `wacc.erp_sensitivity_band_bps = 2 × wacc.erp_refresh_drift_bps` load-bearing (i.e., does a downstream sensitivity table assume a 2σ symmetric band around the drift threshold), or are the two values independently tunable?

If load-bearing → promote INV-2 to hard fail. If tunable → drop INV-2 entirely from the validator. Until the answer arrives, the soft warning logs are the audit trail.

## Outstanding work (post-Phase 5)

- Backfill any in-flight worktree-managed migrations that diverge in their parameters_version usage from this audit. The 9 active worktrees under `.claude/worktrees/` have their own `db/migrations/` copies; once main lands mig 035, any worktree-local additions to the affected tables must be reconciled before merge.
- Update `/parameters-review` skill to accept the `sweep_tag` arg per Q1=D (testability path). This is downstream of /research-company refactor; tracked separately.
