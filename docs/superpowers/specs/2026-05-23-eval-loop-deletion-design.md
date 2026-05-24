# `/research-company` Eval Loop — Deletion Spec (Part 1 of 2)

**Date:** 2026-05-23
**Author:** equity-research-system operator + Claude (brainstorming session)
**Scope:** Remove the dead eval infrastructure from the 5-bin / SPY-only / probabilistic-emission era. DROP the affected DB tables/views, delete the source-code dirs and entry-point slash commands, and ship a single migration (041) that gates each DROP on per-object verification.
**Status:** Approved 2026-05-23 by operator.
**Out of scope:** Anything that creates new eval surface — resolver, scoring, model-health, new view, new flag table, new slash commands. That is the companion *creation* spec (`2026-05-23-eval-loop-creation-design.md`, draft) and is intentionally deferred to a separate approval cycle.

---

## 1. Background

The prior eval infrastructure was designed for a different `/research-company` chain (5-bin enum {ADD, WATCH, PASS, REJECT, HOLD}, SPY-only benchmark, 30d/90d/1y horizons, probabilistic p10/p50/p90 emission). The current chain (post HIGH-4 consensus 2026-05-16, mig 030 applied 2026-05-22, bear-case removed 2026-05-12, counterfactual-veto retired 2026-05-17) is 4-bin {BUY, HOLD, TRIM, SELL}, sector-conditional Brinson-Fachler benchmark via SPDR ETF + parallel SPY, 90d/1y/3y/5y horizons, categorical emission, universal-write per run.

The prior code path is schema-incompatible with the live chain and has zero rows in its target tables. Building new eval on top would force adapters across multiple dimensions and obscure what is actually load-bearing. **Operator decision: delete the dead path entirely as a discrete checkpoint, then design the new eval surface separately.**

This spec only deletes. The eval system that the operator originally requested — a price-grounded loop that compares recommendations to realized returns and triggers calibration/replacement — is the subject of `2026-05-23-eval-loop-creation-design.md` (draft), which the operator has explicitly NOT approved yet.

---

## 2. Deletion inventory

### 2.1 Confirmed dead — DROP in mig 041

**DB tables / views** — zero rows in live DB, no writer in current `/research-company` chain, schema reflects retired architecture:

| Object | Origin | Why dead |
|---|---|---|
| `recommendation_outcomes` (table) | mig 013 | 30d/90d/1y windows + SPY-only benchmark; superseded by `counterfactual_ledger` HIGH-4 columns (mig 030). 0 rows. |
| `predictions` (table) | early-launch | Probabilistic p10/p50/p90 emission never wired; current chain emits categorical only. 0 rows. |
| `system_vs_operator_brier` (view) | mig 025 | JOINs against `recommendation_outcomes` + `operator_overrides`. Dead dependency chain. |
| `counterfactual_retrievals` (table) | mig 011 | counterfactual-veto retired 2026-05-17 (`src/counterfactual_veto/DEPRECATED.md`). |
| `peak_pain_archetypes_retired_20260517` (table) | mig 032 (rename) | Already explicitly retired; rename was the soft step. Drop now. |
| `calibration_test_results` (table) | survivor-correctness era | Tied to peak-pain-archetype survivorship calibration that was retired with counterfactual-veto. 0 rows. |
| `materiality_classifier_drift` (table) | mig pending | 0 rows. Drift detector for a classifier that is not writing to its log table (see §2.2). |

**Source code dirs / files** — target dead tables, or implement retired logic:

| Path | LOC | Why dead |
|---|---|---|
| `src/outcomes/resolver.py` | 432 | Writes to `recommendation_outcomes`. Wrong table, wrong windows, wrong benchmark model. |
| `src/outcomes/cli.py` | 137 | CLI wrapper for the above. |
| `src/outcomes/override_resolver.py` | — | Tied to `operator_overrides` + `override_outcomes` calibration loop. |
| `src/outcomes/__init__.py` | — | Re-exports the above. |
| `src/calibration/brier.py` | 258 | Scopes by `(mode, materiality, rec_type)` over empty tables; assumes probabilistic predictions. |
| `src/calibration/cli.py` | 182 | `/calibration-status` against the dead path. |
| `src/calibration/believability.py` | — | Per-style believability weighting; tied to dead Brier scoping. |
| `src/calibration/__init__.py` | — | Re-exports the above. |
| `src/counterfactual_veto/` (entire dir) | — | Explicitly deprecated 2026-05-17; preserved-for-reference is no longer worth the maintenance load. |
| `src/peak_pain_catalog/` (entire dir) | — | Deprecated alongside `counterfactual_veto`; pair-delete per `DEPRECATED.md` "resurrection procedure" coupling. |
| `src/orchestrator/phase_detector.py` | — | Gates feature flags on `predictions.resolved_predictions` count; dead trigger. |
| `src/orchestrator/v05_activation.py` | — | Feature-flag system gated on the above; current chain does not use this gating. |

**Slash commands + agent files** — entry points for the dead modules:

| File | Why dead |
|---|---|
| `.claude/commands/calibration-status.md` | Invokes `src/calibration/cli.py`. |
| `.claude/commands/resolve-outcomes.md` | Invokes `src/outcomes/cli.py`. After deletion, this slash command is non-functional. **Operator choice (see §3):** remove the file OR leave it dangling for the creation spec to rewrite later. Recommendation: remove. |
| `.claude/agents/bear-case.md.removed-20260512` | Already soft-removed; delete the renamed file entirely. |

### 2.2 Verify-before-drop — gated by per-object verification

These tables/modules are suspected dead but cannot be confirmed without deeper grep across the live chain. The deletion is staged behind a verification subtask per row; if a verification fails, the row stays in the schema and the corresponding DROP is removed from mig 041 before the migration is applied:

| Object | Suspicion | Verification check |
|---|---|---|
| `operator_overrides` (table) | Tied to mig 013 era operator-override loop | `grep -rn "operator_overrides" .claude/ src/` excluding `__pycache__` and deprecated dirs. If 0 active writers → drop. |
| `override_outcomes` (table) | Same | Same check. |
| `debate_consensus_history` (table) | mig 013 era, predates 2026-05-12 bear-case removal | Check whether pm-supervisor §2.6 stress-test or any live module writes here. |
| `fill_divergence` (table) | mig 013 era | Check whether sizing/disposition flow writes here. |
| `mode_classifications` (table, 0 rows) | `src/mode_classifier/` dir still exists | Check whether mode_classifier persists OR only emits in-envelope. |
| `materiality_events` (table, 0 rows) | Similar pattern | Same check. |
| `src/backtesting/framework.py` (761 LOC) | Targets dead schema | Read header + entry points; decide port-vs-delete. |
| `.claude/commands/backtest.md` | Entry to backtesting | Lives or dies with the framework decision. |

### 2.3 Out of deletion scope — keep as-is

- `counterfactual_ledger` (mig 030 HIGH-4 — the live outcome surface)
- `execution_recommendations` (live target of pm-supervisor §9 step 1)
- `evidence_index`, `audit_provenance` (cross-cutting infrastructure)
- `analyst_briefs`, `research_essentials` (cdd ensemble caches)
- `run_parameters_snapshot`, `parameters`, `parameters_active` (parameter snapshotting)
- `watchlist`, `positions`, `position_history`, `current_disposition` (portfolio state)
- `anchor_drift_*`, `regime_*`, `latest_actuals`, `yfinance_cache` (live infra)

---

## 3. Operator open decision (deletion-only scope)

**`/resolve-outcomes` post-delete behavior** — when `src/outcomes/cli.py` is deleted, the slash command at `.claude/commands/resolve-outcomes.md` becomes non-functional. Two operator choices:

| Option | Behavior | Tradeoff |
|---|---|---|
| **A. Delete the .md file too** | `/resolve-outcomes` disappears from the slash-command list | Clean break. If/when the creation spec ships, it will create a new `.md` invoking the new CLI. |
| **B. Leave the .md dangling** | `/resolve-outcomes` continues to appear; invocation errors at runtime when the dead CLI is gone | Reserves the user-facing slash command name for the creation spec to repopulate. Costs an error-on-invoke window. |

This spec defaults to **A (clean delete)** but the implementation plan will surface this as a single-question operator confirmation before P3 fires.

---

## 4. Migration 041 — DROP-only

Single migration, single phase (no CREATE — the CREATE block belongs to the creation spec, which is intentionally deferred). Each DROP is preceded by a per-object verification block; failure of any verification halts the migration before any DROP fires.

```sql
-- =============================================================================
-- Migration 041: research-company eval loop dead-path removal
-- Date:    2026-05-23
-- Spec:    docs/superpowers/specs/2026-05-23-eval-loop-deletion-design.md §2.1
-- Pairs:   none. The companion CREATE migration is intentionally separated to
--          keep deletion and creation as discrete operator approvals.
-- =============================================================================

BEGIN;

-- Verification: every confirmed-dead table is currently empty.
-- If any returns nonzero, raise NOTICE and ROLLBACK before any DROP fires.
DO $$
DECLARE
  v_rows INTEGER;
BEGIN
  FOREACH v_rows IN ARRAY ARRAY[
    (SELECT count(*) FROM recommendation_outcomes),
    (SELECT count(*) FROM predictions),
    (SELECT count(*) FROM counterfactual_retrievals),
    (SELECT count(*) FROM peak_pain_archetypes_retired_20260517),
    (SELECT count(*) FROM calibration_test_results),
    (SELECT count(*) FROM materiality_classifier_drift)
  ] LOOP
    IF v_rows > 0 THEN
      RAISE EXCEPTION 'mig 041 abort: a confirmed-dead table is non-empty (rowcount=%). Investigate before re-running.', v_rows;
    END IF;
  END LOOP;
END $$;

-- Verification: no incoming FK references to objects we're about to drop.
DO $$
DECLARE
  v_fk RECORD;
BEGIN
  FOR v_fk IN
    SELECT conrelid::regclass AS referencing_table, conname
    FROM pg_constraint
    WHERE contype = 'f'
      AND confrelid::regclass::text IN (
        'recommendation_outcomes', 'predictions',
        'counterfactual_retrievals', 'peak_pain_archetypes_retired_20260517',
        'calibration_test_results', 'materiality_classifier_drift'
      )
  LOOP
    RAISE EXCEPTION 'mig 041 abort: incoming FK from %.% references a to-be-dropped table.', v_fk.referencing_table, v_fk.conname;
  END LOOP;
END $$;

-- DROP block — confirmed-dead (§2.1)
DROP VIEW  IF EXISTS system_vs_operator_brier;
DROP TABLE IF EXISTS recommendation_outcomes;
DROP TABLE IF EXISTS predictions;
DROP TABLE IF EXISTS counterfactual_retrievals;
DROP TABLE IF EXISTS peak_pain_archetypes_retired_20260517;
DROP TABLE IF EXISTS calibration_test_results;
DROP TABLE IF EXISTS materiality_classifier_drift;

-- Verify-before-drop block (§2.2) — added conditionally during implementation
-- after each per-object verification subtask passes. Each line stays commented
-- until its verification passes:
-- DROP TABLE IF EXISTS operator_overrides;
-- DROP TABLE IF EXISTS override_outcomes;
-- DROP TABLE IF EXISTS debate_consensus_history;
-- DROP TABLE IF EXISTS fill_divergence;
-- DROP TABLE IF EXISTS mode_classifications;
-- DROP TABLE IF EXISTS materiality_events;

COMMIT;

-- =============================================================================
-- VERIFY: run these after applying to confirm the migration took effect.
-- =============================================================================
SELECT table_name FROM information_schema.tables
WHERE table_schema='public'
  AND table_name IN (
    'recommendation_outcomes','predictions','counterfactual_retrievals',
    'peak_pain_archetypes_retired_20260517','calibration_test_results',
    'materiality_classifier_drift'
  );
-- Expected: 0 rows.

SELECT table_name FROM information_schema.views
WHERE table_schema='public' AND table_name = 'system_vs_operator_brier';
-- Expected: 0 rows.
```

---

## 5. Source-code + slash-command deletion list

After mig 041 applies, the following filesystem deletions ship in the same change set:

**Source code (entire dirs):**

- `src/outcomes/`
- `src/calibration/`
- `src/counterfactual_veto/`
- `src/peak_pain_catalog/`

**Source code (individual files):**

- `src/orchestrator/phase_detector.py`
- `src/orchestrator/v05_activation.py`

**Verify-before-delete:**

- `src/backtesting/framework.py` — only delete if §2.2 verification confirms no live caller.

**Slash commands + agents:**

- `.claude/commands/calibration-status.md`
- `.claude/commands/resolve-outcomes.md` (per operator choice §3, option A; deleted by default)
- `.claude/commands/backtest.md` — only if §2.2 framework deletion confirms.
- `.claude/agents/bear-case.md.removed-20260512`

---

## 6. Rollout phases

| Phase | Gate | Action |
|---|---|---|
| **D0 — Verify** | implementation kick-off | Run the per-object verification subtasks for §2.2. Lock the final DROP list (which §2.2 lines move from commented to active in mig 041). Confirm operator choice on §3. |
| **D1 — Migration** | D0 complete | Apply mig 041 against a snapshot DB first; confirm verification blocks fire on tampered fixtures. Apply against live DB. |
| **D2 — Code delete** | D1 green | Remove the source dirs/files in §5 in one commit. Remove the slash commands + agent file. |
| **D3 — No-regression sweep** | D2 complete | Run any existing test suite; grep for dangling imports; run dashboard + manual `/research-company` smoke to confirm nothing referenced the deleted paths. |

---

## 7. Testing strategy (deletion-only)

- **Verification-block test:** apply mig 041 to a fixture DB where one of the §2.1 tables has been seeded with 1 row; confirm the DO block raises and the migration aborts before any DROP.
- **FK-block test:** apply mig 041 to a fixture DB where a synthetic FK references one of the to-be-dropped tables; confirm the migration aborts.
- **Clean-apply test:** apply mig 041 to the current live-DB schema snapshot; confirm all 7 objects are gone and no other table is affected.
- **Import-regression sweep (after D2):** `python -c "import src; import src.orchestrator; import src.eval"` (the last fails because `src/eval` does not exist yet — that is expected post-deletion; the creation spec will fill it). Grep for `from src.outcomes`, `from src.calibration`, `from src.counterfactual_veto`, `from src.peak_pain_catalog`, `from src.orchestrator.phase_detector`, `from src.orchestrator.v05_activation` — expect 0 hits in non-deprecated code.
- **Dashboard smoke:** open the dashboard, click through the Runs and Gates views, confirm nothing references a deleted path.
- **Slash-command sweep:** run `ls .claude/commands/` and confirm the 2-3 deleted entries are gone; run any remaining slash command and confirm it still functions.

---

## 8. Verification (end-to-end)

After all 4 phases:

```
# 1. Confirm 7 tables/views are gone
psql ... -c "SELECT count(*) FROM information_schema.tables
             WHERE table_name IN (
               'recommendation_outcomes','predictions','counterfactual_retrievals',
               'peak_pain_archetypes_retired_20260517','calibration_test_results',
               'materiality_classifier_drift'
             );"
# Expected: 0

# 2. Confirm source dirs are gone
ls src/outcomes src/calibration src/counterfactual_veto src/peak_pain_catalog 2>&1 | grep "No such"
# Expected: 4 "No such file or directory" lines

# 3. Confirm slash commands are gone
ls .claude/commands/calibration-status.md .claude/commands/resolve-outcomes.md 2>&1 | grep "No such"
# Expected: 2 "No such file or directory" lines

# 4. Confirm no live module imports a deleted path
grep -rn "from src.outcomes\|from src.calibration\|from src.counterfactual_veto\|from src.peak_pain_catalog\|from src.orchestrator.phase_detector\|from src.orchestrator.v05_activation" src/ 2>/dev/null
# Expected: 0 matches

# 5. Confirm /research-company still runs end-to-end (smoke against any ticker)
# /research-company SHOP
# Expected: chain completes, writes counterfactual_ledger + execution_recommendations rows
```

---

## 9. Critical files

**To delete (entire):**

- `src/outcomes/`
- `src/calibration/`
- `src/counterfactual_veto/`
- `src/peak_pain_catalog/`

**To delete (individual files):**

- `src/orchestrator/phase_detector.py`
- `src/orchestrator/v05_activation.py`
- `src/backtesting/framework.py` (verify-first)
- `.claude/commands/calibration-status.md`
- `.claude/commands/resolve-outcomes.md` (operator-confirmable; default delete)
- `.claude/commands/backtest.md` (verify-first)
- `.claude/agents/bear-case.md.removed-20260512`

**To create:**

- `db/migrations/044_eval_loop_dead_path_removal.sql` (originally created as 041; renamed to resolve collision with `041_flow_overlay_v03_crowding.sql`)

**Reference (not modified):**

- `.claude/agents/pm-supervisor.md` §9 — current writer that the deletion does NOT touch.
- `db/migrations/030_counterfactual_ledger_high4_redesign.sql` — the table the deletion preserves.

---

## 10. Followup

This spec deletes only. After D3 completes and the system is verified clean, the operator may:

1. **Approve `2026-05-23-eval-loop-creation-design.md`** (companion draft) to build the new eval surface (resolver + scoring + model-health + new view + flag table + slash commands). The creation spec assumes this deletion spec has landed first; its mig 042 will not conflict because it only CREATEs.
2. **Defer eval entirely** — the system can run `/research-company` indefinitely without an eval loop. `counterfactual_ledger` will accumulate rows with NULL return columns; nothing reads them. No functionality is lost.
3. **Adopt a different eval design** — the deletion is fully orthogonal to whatever comes next.

---

## 11. Operator-friendly diagnosis

This is a code-cleanup spec: remove ~1.5k lines of source code and 7 database objects that target an architecture the chain no longer matches. After this lands, the system has zero eval infrastructure — but it also currently has zero *working* eval infrastructure (all dead tables are 0 rows, all CLI commands target dead schema), so functionality regression is zero. The followup creation spec is a separate decision the operator can take, defer, or reject.
