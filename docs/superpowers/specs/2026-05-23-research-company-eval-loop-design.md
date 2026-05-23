# `/research-company` Evaluation Loop — Clean-Slate Redesign

**Date:** 2026-05-23
**Author:** equity-research-system operator + Claude (brainstorming session)
**Scope:** Stand up a price-grounded evaluation loop for the current `/research-company` chain by (a) deleting the dead eval infrastructure from the 5-bin / SPY-only / probabilistic-emission era, and (b) building a minimal three-component eval surface (resolver, scoring, model-health trigger) against the live `counterfactual_ledger` table (mig 030 HIGH-4 schema).
**Status:** Plan-file approved 2026-05-23 (`/Users/sehoonbyun/.claude/plans/async-yawning-owl.md`); pending operator review of this canonical spec before invoking `writing-plans`.
**Out of scope:** Probabilistic emission (p10/p50/p90), backtest replay for accelerated sample size, automated parameter rewrite, portfolio-level P&L attribution, mode/materiality cell scoping.

---

## 1. Background and motivation

The operator wants a price-grounded evaluation loop for `/research-company`: compare the chain's final recommendation against realized price action over a defined horizon, with a margin of error; if persistently off-band → calibrate parameters; if a specific model is persistently off-band → refine or replace.

The prior eval infrastructure (built ~2026-04 through early 05) was designed for a different chain:

- 5-bin enum {ADD, WATCH, PASS, REJECT, HOLD}
- SPY-only benchmark
- 30d / 90d / 1y horizons
- Probabilistic p10/p50/p90 emission

The current chain (post HIGH-4 consensus 2026-05-16, mig 030 applied 2026-05-22, bear-case removed 2026-05-12, counterfactual-veto retired 2026-05-17) is:

- 4-bin {BUY, HOLD, TRIM, SELL}
- Sector-conditional Brinson-Fachler benchmark via SPDR ETF + parallel SPY
- 90d / 1y / 3y / 5y horizons
- Categorical (not probabilistic) emission
- Universal-write per run (4 ledger rows per `/research-company` call)

The prior code path is schema-incompatible with the live chain and has zero rows in its target tables. Building on top would force adapters across multiple dimensions and obscure what is actually load-bearing. **Operator decision: delete the dead path entirely and redesign from scratch against the live `counterfactual_ledger` table.**

The current `pm-supervisor.md` §9 step 2 explicitly flags the gap this spec closes:

> "Returns columns (`ticker_return_pct`, `vs_sector_etf_return_pct`, `vs_spy_return_pct`, etc.) are NULL at INSERT time. A separate window-close resolution path (NOT defined here — separate change set) populates them when each window's `measurement_date` is reached."

This document is that change set.

---

## 2. Deprecation plan

### 2.1 Confirmed dead — drop in mig 041

**DB tables / views** — zero rows in live DB, no writer in current `/research-company` chain, schema reflects retired architecture:

| Object | Origin | Why dead |
|---|---|---|
| `recommendation_outcomes` (table) | mig 013 | 30d/90d/1y windows + SPY-only benchmark; superseded by `counterfactual_ledger` HIGH-4 columns (mig 030). 0 rows. |
| `predictions` (table) | early-launch | Probabilistic p10/p50/p90 emission never wired; current chain emits categorical only. 0 rows. |
| `system_vs_operator_brier` (view) | mig 025 | JOINs against `recommendation_outcomes` + `operator_overrides`. Dead dependency chain. |
| `counterfactual_retrievals` (table) | mig 011 | counterfactual-veto retired 2026-05-17 (`src/counterfactual_veto/DEPRECATED.md`). |
| `peak_pain_archetypes_retired_20260517` (table) | mig 032 (rename) | Already explicitly retired; rename was the soft step. Drop now. |
| `calibration_test_results` (table) | survivor-correctness era | Tied to peak-pain-archetype survivorship calibration that was retired with counterfactual-veto. 0 rows. |
| `materiality_classifier_drift` (table) | mig pending | 0 rows. Drift detector for a classifier that isn't writing to its log table (see §2.2). |

**Source code dirs / files** — target dead tables, or implement retired logic:

| Path | LOC | Why dead |
|---|---|---|
| `src/outcomes/resolver.py` | 432 | Writes to `recommendation_outcomes`. Wrong table, wrong windows, wrong benchmark model. |
| `src/outcomes/cli.py` | 137 | CLI wrapper for the above. |
| `src/outcomes/override_resolver.py` | — | Tied to `operator_overrides` + `override_outcomes` calibration loop. |
| `src/calibration/brier.py` | 258 | Scopes by `(mode, materiality, rec_type)` over empty tables; assumes probabilistic predictions. |
| `src/calibration/cli.py` | 182 | `/calibration-status` against the dead path. |
| `src/calibration/believability.py` | — | Per-style believability weighting; tied to dead Brier scoping. |
| `src/calibration/__init__.py` | — | Re-exports the above. |
| `src/counterfactual_veto/` (entire dir) | — | Explicitly deprecated 2026-05-17; preserved-for-reference is no longer worth the maintenance load if we are cleaning up. |
| `src/peak_pain_catalog/` (entire dir) | — | Deprecated alongside `counterfactual_veto`; pair-delete per `DEPRECATED.md` "resurrection procedure" coupling. |
| `src/orchestrator/phase_detector.py` | — | Gates feature flags on `predictions.resolved_predictions` count; dead trigger. |
| `src/orchestrator/v05_activation.py` | — | Feature-flag system gated on the above; current chain does not use this gating. |
| `src/backtesting/framework.py` | 761 | Targets `recommendation_outcomes`-shape data. **To verify in implementation (see §2.2)** — if it is the only backtest scaffold and not tied to the dead schema in a load-bearing way, port instead of delete. |

**Slash commands** — entry points for the dead modules:

| File | Why dead |
|---|---|
| `.claude/commands/calibration-status.md` | Invokes `src/calibration/cli.py`. Replaced by §5.2 `/eval-status`. |
| `.claude/commands/resolve-outcomes.md` | Invokes `src/outcomes/cli.py`. Replaced by §5.1 `/resolve-outcomes` against the new resolver. (Keep filename, rewrite contents.) |
| `.claude/agents/bear-case.md.removed-20260512` | Already soft-removed; delete the renamed file entirely. |

### 2.2 Verify-before-drop — defer to implementation phase

These tables / modules are suspected dead but cannot be confirmed without deeper grep across the live chain. The implementation plan (post-`writing-plans`) will produce a verification subtask per row before any DROP statement enters mig 041:

| Object | Suspicion | Verification |
|---|---|---|
| `operator_overrides`, `override_outcomes` | Tied to mig 013 era operator-override loop | Check whether any current operator-facing command writes to these |
| `debate_consensus_history` | mig 013 era, predates 2026-05-12 bear-case removal | Check whether pm-supervisor §2.6 stress-test writes here |
| `fill_divergence` | mig 013 era | Check whether sizing/disposition flow writes here |
| `mode_classifications` (0 rows) | `src/mode_classifier/` dir still exists | Check whether mode_classifier persists, or only emits in-envelope |
| `materiality_events` (0 rows) | Similar pattern | Same check |
| `src/backtesting/framework.py` | 761 LOC, targets dead schema | Read header + entry points; decide port-vs-delete |
| `.claude/commands/backtest.md` | Entry to backtesting | Lives or dies with the framework decision |

### 2.3 Out of deprecation scope — keep as-is

- `counterfactual_ledger` (mig 030 HIGH-4 — **the new eval surface**)
- `execution_recommendations` (live target of pm-supervisor §9 step 1)
- `evidence_index`, `audit_provenance` (cross-cutting infrastructure)
- `analyst_briefs`, `research_essentials` (cdd ensemble caches)
- `run_parameters_snapshot`, `parameters`, `parameters_active` (parameter snapshotting)
- `watchlist`, `positions`, `position_history`, `current_disposition` (portfolio state)
- `anchor_drift_*`, `regime_*`, `latest_actuals`, `yfinance_cache` (live infra)

---

## 3. Architecture

Three new modules + one new SQL view + one new flag table + two slash commands. No probabilistic emitter (categorical-only, matching what the current chain produces).

```
                              live & untouched
                    ┌─────────────────────────────────────────┐
/research-company → │ pm-supervisor §9 step 2                 │
                    │   INSERT 4 rows → counterfactual_ledger │
                    │   (returns columns NULL at insert)      │
                    └─────────────────────────┬───────────────┘
                                              │
                                              ▼
                          ┌──────────────────────────────────┐
                          │ counterfactual_ledger (live)     │
                          │   (decision_date, window,        │
                          │    summary_code, conviction,     │
                          │    gics_sector, benchmark_etf,   │
                          │    measurement_date,             │
                          │    ticker_return_pct=NULL …)     │
                          └──┬────────────────┬──────────────┘
                             │                │
        (1) writes returns   │                │  (2) reads closed rows
            on measurement   │                │
                             ▼                ▼
              ┌─────────────────────┐  ┌────────────────────────────┐
              │ NEW: resolver_v2    │  │ NEW: scoring_v2            │
              │  src/eval/          │  │  src/eval/scoring.py       │
              │    resolver.py      │  │  emits view rows + flags   │
              │  cron daily         │  │                            │
              └─────────────────────┘  └────────────┬───────────────┘
                                                    │
                                                    ▼
                                ┌─────────────────────────────────────┐
                                │ NEW: model_health                   │
                                │  src/eval/model_health.py           │
                                │  scopes by (model_id, cell)         │
                                │  emits CALIBRATE vs REPLACE flags   │
                                └─────────────────────────────────────┘
                                                    │
                                                    ▼
                                ┌─────────────────────────────────────┐
                                │ NEW: /eval-status (slash command)   │
                                │ REWRITTEN: /resolve-outcomes        │
                                └─────────────────────────────────────┘
```

### 3.1 Artifacts changed

| Path | Change | Notes |
|---|---|---|
| `src/eval/__init__.py` | New | Module root (separate namespace from dead `src/outcomes/` and `src/calibration/`) |
| `src/eval/resolver.py` | New | Daily window-close resolver — populates `counterfactual_ledger` return columns |
| `src/eval/scoring.py` | New | Directional hit + magnitude scoring per cell |
| `src/eval/model_health.py` | New | Trigger logic — emits CALIBRATE vs REPLACE flags |
| `src/eval/cli.py` | New | CLI entrypoints (resolve, status) |
| `.claude/commands/resolve-outcomes.md` | Rewrite | Point at `src/eval/cli.py resolve` |
| `.claude/commands/eval-status.md` | New | Invokes `src/eval/cli.py status` |
| `db/migrations/041_eval_loop_redesign.sql` | New | DROP dead path (§2.1, verified §2.2 subset) + CREATE new view + flag table + indexes |
| `tests/eval/` | New | Unit + smoke tests |

---

## 4. Component design

### 4.1 Component 1 — resolver_v2 (`src/eval/resolver.py`)

**Job:** for each row in `counterfactual_ledger` where `measurement_date ≤ today AND ticker_return_pct IS NULL`, fetch ticker + `benchmark_etf` + SPY close prices and UPDATE the return columns.

**Inputs:**

- `counterfactual_ledger` rows filtered by `measurement_date ≤ as_of_date AND ticker_return_pct IS NULL`
- Price provider — Polygon primary, yfinance fallback. The provider abstraction in the deleted `src/outcomes/resolver.py` was sound; the table targeting was wrong. Port the abstraction, drop the rest.

**Outputs (per row):**

- UPDATE of `ticker_return_pct`, `benchmark_return_pct`, `vs_sector_etf_return_pct`, `spy_return_pct`, `vs_spy_return_pct`
- Subject to mig 030 trigger — `counterfactual_ledger_guard()` allows these 5 columns + `measurement_date` to mutate (mig 030 lines 140-144); all identity columns are blocked.

**Trading-day anchor:**

- Decision-date anchor: first close ≥ `decision_date` for both legs (handles weekends/holidays).
- Measurement-date anchor: last close ≤ `measurement_date` for both legs.
- If no bar exists in the anchor window for either leg, leave the row NULL and log to `system_errors`.

**Idempotency:** safe to re-run; only acts on rows with `ticker_return_pct IS NULL`.

**Failure handling:**

- Per-row provider errors do NOT halt the batch (log to `system_errors`, continue).
- Provider auth/network errors halt the batch and surface to operator.

**Scheduling:** daily cron (operator-installed via `CronCreate`) at end of trading day + 1hr buffer. CLI invocation:

```
python -m src.eval.cli resolve --as-of $(date -u +%Y-%m-%d)
```

### 4.2 Component 2 — scoring_v2 (`src/eval/scoring.py`)

**Job:** given resolved rows, compute per-cell directional hit + magnitude error.

**Cells:** `(model_id, summary_code, conviction, gics_sector, window)`. `model_id` lives on `execution_recommendations`, NOT on `counterfactual_ledger` — JOIN via:

```
counterfactual_ledger.run_id
  = (execution_recommendations.trigger_metadata->>'pm_supervisor_run_id')::uuid
```

This is the same JOIN pattern wired into the dashboard's `/__api/runs` endpoint after the 2026-05-21 join-fix.

**Directional hit rule** (deterministic, mechanical):

| summary_code | Hit condition (primary = `vs_sector_etf_return_pct`) |
|---|---|
| BUY  | `vs_sector_etf > +ε_buy` |
| SELL | `vs_sector_etf < −ε_sell` |
| TRIM | `vs_sector_etf < +ε_trim` |
| HOLD | `|vs_sector_etf| < ε_hold` |

The ε values are **domain decisions deferred to `/review-me`** (see §7). The scoring module reads them from a config table or `parameters_active`; it does not hardcode.

**Magnitude error:** `|vs_sector_etf − expected_magnitude(conviction)|`. The conviction → expected-magnitude mapping is also a `/review-me` decision; scoring module treats it as a parameter lookup.

**Output:** new SQL view `eval_cell_scoreboard` (created in mig 041, Phase B):

```sql
CREATE VIEW eval_cell_scoreboard AS
SELECT
  er.model_id,
  er.model_version,
  cl.summary_code,
  cl.conviction,
  cl.gics_sector,
  cl."window",
  COUNT(*)                                                   AS n,
  AVG((<directional hit expression>)::int)::numeric          AS hit_rate,
  AVG(ABS(cl.vs_sector_etf_return_pct - <expected_magnitude>)) AS mean_magnitude_error,
  AVG(cl.vs_sector_etf_return_pct)                           AS mean_active_return,
  MIN(cl.decision_date)                                      AS first_decision,
  MAX(cl.decision_date)                                      AS last_decision
FROM counterfactual_ledger cl
JOIN execution_recommendations er
  ON cl.run_id = (er.trigger_metadata->>'pm_supervisor_run_id')::uuid
WHERE cl.ticker_return_pct IS NOT NULL
GROUP BY er.model_id, er.model_version, cl.summary_code, cl.conviction,
         cl.gics_sector, cl."window";
```

The `<directional hit expression>` and `<expected_magnitude>` are CASE statements parameterized by the config lookup at view-create time. If the parameter set changes, the view is dropped and recreated as part of the parameter migration.

### 4.3 Component 3 — model_health (`src/eval/model_health.py`)

**Job:** classify each cell as OK / CALIBRATE / REPLACE based on rolling-window stats.

**Distinction:**

- **CALIBRATE** = cell-specific drift. e.g., `(model=X, BUY, HIGH, Tech, 90d)` shows degraded hit-rate but other cells for model X are fine. Action: review the parameter that controls this cell's expectation (ε or expected_magnitude).
- **REPLACE** = model-wide drift. Aggregate hit-rate across all cells for `model_id=X` degraded. Action: review the model itself.

**Trigger logic** — the thresholds are `/review-me` decisions; this module owns the *mechanism*, not the *values*:

- Need `n ≥ N_min` rows in the cell (sample-size gate).
- Compare current rolling-window hit-rate to baseline (either historical rolling baseline or a configured target).
- Flag if difference exceeds `Δ_threshold` with confidence `p < p_threshold` (binomial test).
- For REPLACE: aggregate over all cells for the model; require model-wide degradation.

**Output:** writes to a new table `eval_health_flags` (created in mig 041, Phase B):

```sql
CREATE TABLE eval_health_flags (
  flag_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  flag_type        TEXT NOT NULL CHECK (flag_type IN ('CALIBRATE','REPLACE')),
  model_id         TEXT NOT NULL,
  cell_json        JSONB NOT NULL,
  n                INTEGER NOT NULL,
  observed         NUMERIC NOT NULL,
  baseline         NUMERIC NOT NULL,
  p_value          NUMERIC NOT NULL,
  raised_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  status           TEXT NOT NULL DEFAULT 'OPEN'
                     CHECK (status IN ('OPEN','ACK','RESOLVED','SUPPRESSED')),
  resolved_at      TIMESTAMPTZ,
  resolved_by      TEXT,
  resolution_note  TEXT
);

CREATE INDEX idx_eval_health_flags_open
  ON eval_health_flags(model_id, raised_at)
  WHERE status = 'OPEN';
```

Append-only trigger on `eval_health_flags` (mirroring `counterfactual_ledger_guard()` pattern) — only `status`, `resolved_at`, `resolved_by`, `resolution_note` may UPDATE post-insert. Operator-resolution column mirrors the `anchor_drift_review_decisions` workflow.

### 4.4 New CLI (`src/eval/cli.py`)

Exposed subcommands:

- `resolve --as-of <date>` — invokes resolver_v2
- `status` — prints scoreboard summary + active health flags (replaces `/calibration-status`)
- `score --force` — recomputes scoreboard view (normally view is live)

---

## 5. Slash command surface

### 5.1 `/resolve-outcomes` (rewritten)

File: `.claude/commands/resolve-outcomes.md`. Body invokes:

```
python -m src.eval.cli resolve --as-of $(date -u +%Y-%m-%d)
```

Replaces the file currently invoking dead `src/outcomes/cli.py`.

### 5.2 `/eval-status` (new)

File: `.claude/commands/eval-status.md`. Body invokes:

```
python -m src.eval.cli status
```

Prints:

- Total rows in `counterfactual_ledger` per window × resolution-status.
- Top N cells by sample size, with hit-rate and mean active return.
- Active CALIBRATE / REPLACE flags.

---

## 6. Database changes (mig 041)

Single migration, two phases. Phase A is gated by per-DROP verification blocks (count rows, check FK references, check active writers); failure of any verification halts the migration before any DROP fires.

**Phase A — DROP (confirmed-dead block):**

```sql
DROP VIEW IF EXISTS system_vs_operator_brier;
DROP TABLE IF EXISTS recommendation_outcomes;
DROP TABLE IF EXISTS predictions;
DROP TABLE IF EXISTS counterfactual_retrievals;
DROP TABLE IF EXISTS peak_pain_archetypes_retired_20260517;
DROP TABLE IF EXISTS calibration_test_results;
DROP TABLE IF EXISTS materiality_classifier_drift;

-- Verify-before-drop (§2.2) — gated on implementation-phase verification:
-- DROP TABLE IF EXISTS operator_overrides, override_outcomes,
--                      debate_consensus_history, fill_divergence,
--                      mode_classifications, materiality_events;
```

**Phase B — CREATE:**

```sql
CREATE VIEW eval_cell_scoreboard AS …;  -- per §4.2
CREATE TABLE eval_health_flags ( … );   -- per §4.3
CREATE INDEX idx_eval_health_flags_open ON eval_health_flags(model_id, raised_at)
  WHERE status = 'OPEN';

CREATE OR REPLACE FUNCTION eval_health_flags_guard() RETURNS TRIGGER AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'eval_health_flags is append-only — DELETE not permitted';
  END IF;
  -- UPDATE: only resolution columns may change
  IF NEW.flag_id IS DISTINCT FROM OLD.flag_id
     OR NEW.flag_type  IS DISTINCT FROM OLD.flag_type
     OR NEW.model_id   IS DISTINCT FROM OLD.model_id
     OR NEW.cell_json  IS DISTINCT FROM OLD.cell_json
     OR NEW.n          IS DISTINCT FROM OLD.n
     OR NEW.observed   IS DISTINCT FROM OLD.observed
     OR NEW.baseline   IS DISTINCT FROM OLD.baseline
     OR NEW.p_value    IS DISTINCT FROM OLD.p_value
     OR NEW.raised_at  IS DISTINCT FROM OLD.raised_at
  THEN
    RAISE EXCEPTION 'eval_health_flags UPDATE rejected: only status / resolved_at / resolved_by / resolution_note may change after insert';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER eval_health_flags_no_modify
  BEFORE UPDATE OR DELETE ON eval_health_flags
  FOR EACH ROW EXECUTE FUNCTION eval_health_flags_guard();
```

---

## 7. Operator decisions deferred to `/review-me`

Per the standing rule that SE-role surfaces harness/data/context-engineering questions only; investment-logic and quant-method choices route to `/review-me`:

| # | Decision | Mechanism owned here | Value owned by `/review-me` |
|---|---|---|---|
| 1 | ε bands for directional hit (ε_buy, ε_sell, ε_trim, ε_hold) | scoring.py reads from config | Domain-appropriate values per `window` |
| 2 | conviction → expected_magnitude mapping | scoring.py reads from config | What HIGH/MEDIUM/LOW conviction means in active-return terms |
| 3 | N_min sample-size gate per cell | model_health.py reads from config | Minimum N for statistical claim |
| 4 | Δ_threshold + p_threshold for CALIBRATE / REPLACE | model_health.py reads from config | Statistical confidence floor |
| 5 | Rolling-window length (90d? 1y?) for baseline | model_health.py reads from config | What "recent" means for drift detection |
| 6 | Primary scoring signal — `vs_sector_etf` vs `vs_spy` | scoring.py uses vs_sector_etf as primary per §4.2 | Confirm or override |
| 7 | What "REPLACE" means operationally (block new emissions? require operator override?) | flag_type='REPLACE' raises the flag | Operator runbook on response |

The spec proposes the mechanisms and leaves the values to operator/quant judgment via the existing `parameters_active` table or a sibling `eval_parameters_active` table (created by a follow-up parameter-seed migration).

---

## 8. Out of scope (phase-2 backlog)

- **Probabilistic emission** (p10/p50/p90). Current chain does not produce; adding it is its own spec.
- **Backtest replay** for accelerated sample size. Requires contamination boundary design (the existing `contamination_check` MCP is the right tool); separate spec.
- **Automated parameter rewrite** when CALIBRATE fires. Flag-and-await-operator is the v1 pattern, matching the existing `anchor_drift_review_decisions` workflow.
- **Portfolio-level P&L attribution** (book IRR, sleeve attribution).
- **Mode / materiality scoping.** `mode_classifications` and `materiality_events` are 0-row in production (§2.2 verification will confirm whether they are dead or just empty); v1 scopes on `(model_id, summary_code, conviction, gics_sector, window)` — columns that are actually populated.

---

## 9. Rollout phases

| Phase | Gate | Action |
|---|---|---|
| **P0 — Verify** | implementation kick-off | Run verification subtasks for §2.2 items. Lock the final DROP list. |
| **P1 — Build (no DROP)** | P0 complete | Land `src/eval/` modules + tests + new slash commands. CREATE new view + flag table (Phase B of mig 041). Run resolver against existing 4 rows. No deletes yet. |
| **P2 — Shadow** | P1 green | Run resolver on a cron for ≥7 days. Verify `counterfactual_ledger` return columns populate as windows close. Verify `/eval-status` output is sensible. No flags raised yet (insufficient data — first 90d window will not close until ~2026-08-20 for the existing AAPL run). |
| **P3 — Drop dead path** | P2 stable | Apply Phase A of mig 041 (the DROP block). Delete the §2.1 source-code dirs/files. Delete `.claude/commands/calibration-status.md`. Delete `.claude/agents/bear-case.md.removed-20260512`. |
| **P4 — Live flags** | data sufficient (`n ≥ N_min` per cell, ≥1 closed window) | Enable model_health trigger. First real flags possible only when 90d windows close. |

---

## 10. Testing strategy

- **Unit (`tests/eval/test_resolver.py`):** mock price provider; assert correct anchor-day selection, idempotency, NULL handling, trigger compliance (UPDATE only on allowed columns).
- **Unit (`tests/eval/test_scoring.py`):** synthetic cells with known hits/misses; assert `hit_rate` + `magnitude_error` correctness.
- **Unit (`tests/eval/test_model_health.py`):** binomial-test boundary cases; CALIBRATE-vs-REPLACE classification.
- **Smoke (`tests/eval/test_smoke_live_db.py`):** end-to-end against live DB (the 4 existing AAPL rows) with a stub price provider; verifies no schema violations.
- **Migration test:** apply mig 041 to a snapshot DB; verify verification blocks gate the DROPs; verify CREATE produces the right surface.

---

## 11. Critical files

**To create:**

- `src/eval/__init__.py`
- `src/eval/resolver.py`
- `src/eval/scoring.py`
- `src/eval/model_health.py`
- `src/eval/cli.py`
- `.claude/commands/eval-status.md`
- `db/migrations/041_eval_loop_redesign.sql`
- `tests/eval/test_resolver.py`
- `tests/eval/test_scoring.py`
- `tests/eval/test_model_health.py`
- `tests/eval/test_smoke_live_db.py`

**To rewrite:**

- `.claude/commands/resolve-outcomes.md` (point at new CLI)

**To delete (phase P3, after verification):**

- `src/outcomes/` (entire dir)
- `src/calibration/` (entire dir)
- `src/counterfactual_veto/` (entire dir)
- `src/peak_pain_catalog/` (entire dir)
- `src/orchestrator/phase_detector.py`
- `src/orchestrator/v05_activation.py`
- `src/backtesting/framework.py` (if §2.2 verification confirms)
- `.claude/commands/calibration-status.md`
- `.claude/commands/backtest.md` (if §2.2 verification confirms)
- `.claude/agents/bear-case.md.removed-20260512`

**Reference (not modified):**

- `.claude/agents/pm-supervisor.md` §9 — describes the universal-write that feeds the new resolver
- `db/migrations/030_counterfactual_ledger_high4_redesign.sql` — defines the trigger semantics the resolver must respect

---

## 12. Verification (end-to-end)

After P1 lands:

```
# 1. Run resolver against existing 4 AAPL rows
#    (none should resolve — all measurement_dates are in the future)
python -m src.eval.cli resolve --as-of 2026-05-23

# 2. Confirm no UPDATE was attempted, no error raised
psql ... -c "SELECT count(*) FROM counterfactual_ledger
             WHERE ticker_return_pct IS NOT NULL;"
# Expected: 0

# 3. Backdate one row's measurement_date for smoke test (in test fixture, not prod)
# 4. Re-run resolver, confirm UPDATE succeeds
# 5. Query scoreboard view, confirm row appears

# 6. Run /eval-status
# Expected: scoreboard prints, no flags raised (n=0 active)
```

After P2 (real data):

```
# When first AAPL 90d window closes (~2026-08-20):
python -m src.eval.cli resolve --as-of 2026-08-21
# Verify ticker_return_pct, vs_sector_etf_return_pct populated
# Verify scoreboard view shows the row
# Verify no health flags raised (n=1 << N_min)
```

---

## 13. Operator-friendly diagnosis

The prior eval code was built for a different chain (5-bin, SPY-only, 30d horizons, probabilistic). The current chain (4-bin, sector-ETF, 90d/1y/3y/5y, categorical) needs its own minimal evaluation surface: a resolver to fill in the return columns the chain already leaves NULL, a scoreboard view to roll up per `(model_id, cell)`, and a flag table to distinguish "tune the parameter" from "swap the model." Everything else (probabilistic emission, backtest replay, automated calibration) is a separate spec — this one is the load-bearing minimum to start grading the chain against price reality.

---

## 14. Next step after operator approval

On approval of this spec:

1. Invoke `writing-plans` to produce a phase-by-phase implementation plan (P0 verification subtasks → P1 build → P2 shadow → P3 drop → P4 live flags).
2. The implementation plan owns the per-table verification work that gates §2.2 from being added to mig 041's Phase A DROP block.
3. Domain decisions in §7 route to `/review-me` before P4 can activate flags.
