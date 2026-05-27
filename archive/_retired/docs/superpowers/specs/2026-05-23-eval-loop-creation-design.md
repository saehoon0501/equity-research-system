# `/research-company` Eval Loop — Creation Spec (Part 2 of 2) — DRAFT, PENDING APPROVAL

**Date:** 2026-05-23
**Author:** equity-research-system operator + Claude (brainstorming session)
**Status:** DRAFT. **NOT approved by operator as of 2026-05-23.** Companion to the *deletion* spec (`2026-05-23-eval-loop-deletion-design.md`) which IS approved. This creation spec is intentionally held back pending separate operator review.
**Scope:** Build a minimal three-component eval surface (resolver, scoring, model-health trigger) against the live `counterfactual_ledger` table (mig 030 HIGH-4 schema). Adds new source modules, a CREATE-only migration (042), new slash commands.
**Prerequisite:** the deletion spec must land first. This spec assumes the dead path is gone (no `recommendation_outcomes`, no `predictions`, no `system_vs_operator_brier`, no `src/outcomes`, no `src/calibration`, etc.).
**Out of scope:** Probabilistic emission (p10/p50/p90), backtest replay for accelerated sample size, automated parameter rewrite, portfolio-level P&L attribution, mode/materiality cell scoping.

---

## 1. Background and motivation

The operator wants a price-grounded evaluation loop for `/research-company`: compare the chain's final recommendation against realized price action over a defined horizon, with a margin of error; if persistently off-band → calibrate parameters; if a specific model is persistently off-band → refine or replace.

The current chain (post HIGH-4, 4-bin, sector-conditional, 90d/1y/3y/5y, categorical, universal-write) writes to `counterfactual_ledger` with return columns NULL at insert. `pm-supervisor.md` §9 step 2 explicitly flags the gap this spec closes:

> "Returns columns (`ticker_return_pct`, `vs_sector_etf_return_pct`, `vs_spy_return_pct`, etc.) are NULL at INSERT time. A separate window-close resolution path (NOT defined here — separate change set) populates them when each window's `measurement_date` is reached."

This document is that change set.

---

## 2. Architecture

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
                          └──┬────────────────┬──────────────┘
                             │                │
        (1) writes returns   │                │  (2) reads closed rows
                             ▼                ▼
              ┌─────────────────────┐  ┌────────────────────────────┐
              │ NEW: resolver_v2    │  │ NEW: scoring_v2            │
              │  src/eval/          │  │  src/eval/scoring.py       │
              │    resolver.py      │  │                            │
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
                                │ NEW: /resolve-outcomes (recreated)  │
                                └─────────────────────────────────────┘
```

### 2.1 Artifacts created

| Path | Notes |
|---|---|
| `src/eval/__init__.py` | Module root |
| `src/eval/resolver.py` | Daily window-close resolver |
| `src/eval/scoring.py` | Directional hit + magnitude scoring per cell |
| `src/eval/model_health.py` | Trigger logic for CALIBRATE / REPLACE |
| `src/eval/cli.py` | CLI entrypoints (resolve, status) |
| `.claude/commands/resolve-outcomes.md` | New (the prior file is deleted by the deletion spec) |
| `.claude/commands/eval-status.md` | New |
| `db/migrations/042_eval_loop_creation.sql` | CREATE-only — view + flag table + trigger |
| `tests/eval/` | Unit + smoke tests |

---

## 3. Component design

### 3.1 Component 1 — resolver_v2 (`src/eval/resolver.py`)

**Job:** for each row in `counterfactual_ledger` where `measurement_date ≤ today AND ticker_return_pct IS NULL`, fetch ticker + `benchmark_etf` + SPY close prices and UPDATE the return columns.

**Subject to mig 030 trigger** — `counterfactual_ledger_guard()` allows the 5 return columns + `measurement_date` to mutate (mig 030 lines 140-144); all identity columns are blocked.

**Trading-day anchor:**

- Decision-date anchor: first close ≥ `decision_date` for both legs (handles weekends/holidays).
- Measurement-date anchor: last close ≤ `measurement_date` for both legs.
- If no bar exists in the anchor window for either leg, leave the row NULL and log to `system_errors`.

**Idempotency:** safe to re-run; only acts on rows with `ticker_return_pct IS NULL`.

**Price provider abstraction:** Polygon primary, yfinance fallback. The provider abstraction style from the (now-deleted) `src/outcomes/resolver.py` is sound — port the abstraction into `src/eval/`, drop the table-targeting logic.

**Failure handling:**

- Per-row provider errors do NOT halt the batch (log to `system_errors`, continue).
- Provider auth/network errors halt the batch and surface to operator.

**Scheduling:** daily cron (operator-installed via `CronCreate`) at end of trading day + 1hr buffer. CLI invocation:

```
python -m src.eval.cli resolve --as-of $(date -u +%Y-%m-%d)
```

### 3.2 Component 2 — scoring_v2 (`src/eval/scoring.py`)

**Job:** given resolved rows, compute per-cell directional hit + magnitude error.

**Cells:** `(model_id, summary_code, conviction, gics_sector, window)`. `model_id` lives on `execution_recommendations`, NOT on `counterfactual_ledger` — JOIN via:

```
counterfactual_ledger.run_id
  = (execution_recommendations.trigger_metadata->>'pm_supervisor_run_id')::uuid
```

This is the same JOIN pattern wired into the dashboard's `/__api/runs` endpoint.

**Directional hit rule** (deterministic, mechanical):

| summary_code | Hit condition (primary = `vs_sector_etf_return_pct`) |
|---|---|
| BUY  | `vs_sector_etf > +ε_buy` |
| SELL | `vs_sector_etf < −ε_sell` |
| TRIM | `vs_sector_etf < +ε_trim` |
| HOLD | `|vs_sector_etf| < ε_hold` |

The ε values are **domain decisions deferred to `/review-me`** (see §6). The scoring module reads them from a config table or `parameters_active`; does not hardcode.

**Magnitude error:** `|vs_sector_etf − expected_magnitude(conviction)|`. The conviction → expected-magnitude mapping is also a `/review-me` decision.

**Output:** new SQL view `eval_cell_scoreboard` (created in mig 042) — full DDL in §4.

### 3.3 Component 3 — model_health (`src/eval/model_health.py`)

**Job:** classify each cell as OK / CALIBRATE / REPLACE based on rolling-window stats.

**Distinction:**

- **CALIBRATE** = cell-specific drift. e.g., `(model=X, BUY, HIGH, Tech, 90d)` shows degraded hit-rate but other cells for model X are fine. Action: review the parameter that controls this cell's expectation (ε or expected_magnitude).
- **REPLACE** = model-wide drift. Aggregate hit-rate across all cells for `model_id=X` degraded. Action: review the model itself.

**Trigger logic** — the thresholds are `/review-me` decisions; this module owns the *mechanism*, not the *values*:

- Need `n ≥ N_min` rows in the cell (sample-size gate).
- Compare current rolling-window hit-rate to baseline (either historical rolling baseline or a configured target).
- Flag if difference exceeds `Δ_threshold` with confidence `p < p_threshold` (binomial test).
- For REPLACE: aggregate over all cells for the model; require model-wide degradation.

**Output:** writes to a new table `eval_health_flags` (created in mig 042) — full DDL in §4.

### 3.4 New CLI (`src/eval/cli.py`)

Subcommands:

- `resolve --as-of <date>` — invokes resolver_v2
- `status` — prints scoreboard summary + active health flags
- `score --force` — recomputes scoreboard view (normally view is live)

---

## 4. Migration 042 — CREATE-only

```sql
-- =============================================================================
-- Migration 042: research-company eval loop creation
-- Date:    2026-05-23 (draft; not approved)
-- Spec:    docs/superpowers/specs/2026-05-23-eval-loop-creation-design.md §4
-- Pairs:   prerequisite mig 041 (eval_loop_dead_path_removal) must have applied.
-- =============================================================================

BEGIN;

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
-- The <directional hit expression> and <expected_magnitude> are CASE statements
-- parameterized by the /review-me config lookup at view-create time.

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

CREATE OR REPLACE FUNCTION eval_health_flags_guard() RETURNS TRIGGER AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'eval_health_flags is append-only — DELETE not permitted';
  END IF;
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

COMMIT;
```

---

## 5. Slash command surface

### 5.1 `/resolve-outcomes` (recreated)

File: `.claude/commands/resolve-outcomes.md`. Body invokes:

```
python -m src.eval.cli resolve --as-of $(date -u +%Y-%m-%d)
```

The prior file at this path is deleted by the deletion spec. This spec creates the replacement.

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

## 6. Operator decisions deferred to `/review-me`

| # | Decision | Mechanism owned here | Value owned by `/review-me` |
|---|---|---|---|
| 1 | ε bands for directional hit (ε_buy, ε_sell, ε_trim, ε_hold) | scoring.py reads from config | Domain-appropriate values per `window` |
| 2 | conviction → expected_magnitude mapping | scoring.py reads from config | What HIGH/MEDIUM/LOW conviction means in active-return terms |
| 3 | N_min sample-size gate per cell | model_health.py reads from config | Minimum N for statistical claim |
| 4 | Δ_threshold + p_threshold for CALIBRATE / REPLACE | model_health.py reads from config | Statistical confidence floor |
| 5 | Rolling-window length (90d? 1y?) for baseline | model_health.py reads from config | What "recent" means for drift detection |
| 6 | Primary scoring signal — `vs_sector_etf` vs `vs_spy` | scoring.py uses vs_sector_etf as primary per §3.2 | Confirm or override |
| 7 | What "REPLACE" means operationally (block new emissions? require operator override?) | flag_type='REPLACE' raises the flag | Operator runbook on response |

---

## 7. Out of scope (phase-3 backlog)

- **Probabilistic emission** (p10/p50/p90). Current chain does not produce; adding it is its own spec.
- **Backtest replay** for accelerated sample size. Requires contamination boundary design.
- **Automated parameter rewrite** when CALIBRATE fires. Flag-and-await-operator is the v1 pattern.
- **Portfolio-level P&L attribution** (book IRR, sleeve attribution).
- **Mode / materiality scoping.**

---

## 8. Rollout phases

| Phase | Gate | Action |
|---|---|---|
| **C0 — Approval** | operator approves this spec | Move status from DRAFT to APPROVED in the header. Confirm deletion spec has fully landed (mig 041 applied, source dirs gone). |
| **C1 — Build** | C0 complete | Land `src/eval/` modules + tests + new slash commands. Apply mig 042. Run resolver against existing rows. |
| **C2 — Shadow** | C1 green | Run resolver on a cron for ≥7 days. Verify `counterfactual_ledger` return columns populate as windows close. Verify `/eval-status` output is sensible. |
| **C3 — Live flags** | data sufficient (`n ≥ N_min` per cell, ≥1 closed window) | Enable model_health trigger. First real flags possible only when 90d windows close (~2026-08-20 for existing AAPL run). |

---

## 9. Testing strategy

- **Unit (`tests/eval/test_resolver.py`):** mock price provider; assert anchor-day selection, idempotency, NULL handling, trigger compliance.
- **Unit (`tests/eval/test_scoring.py`):** synthetic cells with known hits/misses; assert `hit_rate` + `magnitude_error` correctness.
- **Unit (`tests/eval/test_model_health.py`):** binomial-test boundary cases; CALIBRATE-vs-REPLACE classification.
- **Smoke (`tests/eval/test_smoke_live_db.py`):** end-to-end against live DB with a stub price provider.
- **Migration test:** apply mig 042; verify view + flag table + trigger semantics.

---

## 10. Critical files

**To create:**

- `src/eval/__init__.py`
- `src/eval/resolver.py`
- `src/eval/scoring.py`
- `src/eval/model_health.py`
- `src/eval/cli.py`
- `.claude/commands/eval-status.md`
- `.claude/commands/resolve-outcomes.md` (recreated post-deletion)
- `db/migrations/042_eval_loop_creation.sql`
- `tests/eval/test_resolver.py`
- `tests/eval/test_scoring.py`
- `tests/eval/test_model_health.py`
- `tests/eval/test_smoke_live_db.py`

**Reference (not modified):**

- `.claude/agents/pm-supervisor.md` §9
- `db/migrations/030_counterfactual_ledger_high4_redesign.sql`

---

## 11. Operator-friendly diagnosis

This spec builds the new eval surface against the live `counterfactual_ledger` table. It is intentionally deferred to a separate approval cycle so that the deletion (mig 041) can land and be verified as a discrete checkpoint. Until this spec is approved and shipped, the system has no eval loop — but the `counterfactual_ledger` is still being populated by `/research-company` runs, so no data is lost. When the operator is ready, this spec can be approved as-is, modified, or replaced with a different design.
