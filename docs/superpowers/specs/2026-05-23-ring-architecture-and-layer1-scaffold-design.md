# Ring Architecture & Layer-1 Scorer Scaffold — Design

**Date:** 2026-05-23
**Status:** DRAFT — pending operator review (this file)
**Scope:** Codifies the inner-ring `tests/` layout per P14 (CLAUDE.md), establishes `src/eval/` greenfield for the outer ring, and scaffolds Layer 1 (pure scorer) with its inner-ring unit tests. Defers Layers 2 (resolver) and 3 (model_health) to the companion creation spec.
**Companion specs:**
- `2026-05-23-eval-loop-deletion-design.md` — APPROVED, LANDED (mig 041, ~3.5k LOC removed)
- `2026-05-23-eval-loop-creation-design.md` — DRAFT, covers Layers 2 & 3 (resolver + model_health + mig 042 + slash commands)
- This spec is the **prerequisite** for the creation spec — inner ring lands first per P14 build order.

**Out of scope:**
- Layer 2 (resolver) implementation — companion creation spec
- Layer 3 (model_health) aggregation — companion creation spec
- mig 042 — companion creation spec
- Probabilistic emission, backtest replay, portfolio P&L — explicitly excluded by deletion spec

---

## 1. Background & motivation

P14 (CLAUDE.md): `/research-company` has two test surfaces. Inner ring (per-step unit tests for refactor safety) must precede the outer ring (Eval loop). Until inner-ring coverage exists for a component, outer-ring scoring against it is uninterpretable — you can't separate calibration signal from refactor regression.

Today's `tests/` directory is flat (~25 files) — mixes unit, integration, regression, and dead-code remnants. No structural separation. New components have no canonical home. This spec establishes the layout and migrates what exists.

---

## 2. Inner-ring `tests/` layout — mirror `src/`, categorize by test type

```
tests/
├── conftest.py                                # exists — keep (loads .env, registers markers)
├── unit/                                      # pure-deterministic, <1s, no I/O
│   ├── agent_harness/
│   ├── alert_channels/
│   ├── audit_trail/
│   ├── eval/                                  # outer ring's own inner-ring tests
│   │   └── test_scorer.py                     # FIRST TARGET — this spec
│   ├── evaluator_gates/
│   │   ├── test_envelope_shape.py             # HG-23 (presence-only per P13)
│   │   └── test_tactical_envelope_shape.py
│   ├── l4_daily_monitor/
│   ├── mode_classifier/
│   ├── parameters_review/
│   └── premortem_scheduler/
├── contract/                                  # LLM subagent envelope shape-lock
│   ├── catalyst_scout/
│   │   ├── fixtures/<scenario>.json
│   │   └── test_envelope.py
│   ├── evaluator/
│   ├── pm_supervisor/
│   ├── quantitative_analyst/
│   ├── strategic_analyst/
│   └── tactical_overlay/
├── integration/                               # cross-component / live DB
│   ├── test_e2e_integration.py
│   ├── test_full_pipeline.py
│   └── test_live_db_smoke_extended.py
└── regression/                                # bug-fix lock-ins
    ├── test_datetime_audit_regression.py
    ├── test_timezone_dst_audit_regression.py
    └── test_hmac_integration.py
```

**Pytest impact:** auto-discovers nested `test_*.py` — no `pytest.ini` / `pyproject.toml` change needed. `pytest tests/unit/` becomes the fast inner-ring loop (target: <5s total). Existing markers `integration` + `integration_live` remain.

**Migration commit:** single `git mv` pass for existing files. No content changes in the migration commit — that keeps blame intact and makes the diff trivially reviewable.

---

## 3. Contract-test design — hybrid fixtures, schema + invariants

Per locked decisions (this session):

**Fixture sourcing — option (c) hybrid:**
- Hand-authored synthetic JSON for edge cases (cap-breach, LOW-conviction, sleeve violation, mode-D thin-evidence)
- Live-captured envelopes from real `/research-company` runs for the baseline shape lock
- Fixtures live at `tests/contract/<agent>/fixtures/<scenario>.json`

**Assertion depth — option (b) schema + key invariants:**
- Validate top-level shape (all required keys present)
- Enforce enum constraints: `summary_code ∈ {BUY,HOLD,TRIM,SELL}` (P9), conviction tier within enum, mode within enum
- Type-check load-bearing fields (`sleeve_cap_compliance` is object with required subkeys, return targets are numeric)
- Explicitly NOT a deep-equality golden — prose tweaks must not break tests
- Complements P13's presence-only HG-23 with richer type/enum richness in tests/

**Contract test does NOT run the LLM.** It only validates a captured/authored fixture. Fast, deterministic, free.

---

## 4. Outer-ring layout — `src/eval/`, separate from `src/backtesting/`

```
src/eval/
├── __init__.py
├── scorer.py                                  # Layer 1 — THIS SPEC
├── resolver.py                                # Layer 2 — companion creation spec
├── model_health.py                            # Layer 3 — companion creation spec
├── cli.py                                     # python -m src.eval — companion creation spec
└── README.md                                  # ties to P14 + HIGH-4 consensus

db/migrations/
└── 042_eval_verdicts.sql                      # companion creation spec (Layer 2/3 persistence)

.claude/commands/
├── eval-status.md                             # companion creation spec
└── eval-run.md                                # companion creation spec
```

**Why separate from `src/backtesting/`:** different verbs, different lifecycles. Backtest = simulate a strategy over history. Eval = grade live recommendations against forward returns. Different consumers, different DBs, different cadence.

---

## 5. Layer 1 — Scorer (this spec's deliverable)

### 5.1 Signature

```python
# src/eval/scorer.py
from dataclasses import dataclass
from enum import Enum

class Label(str, Enum):
    BUY = "BUY"
    HOLD = "HOLD"
    TRIM = "TRIM"
    SELL = "SELL"

class Verdict(str, Enum):
    HIT = "hit"
    MISS = "miss"

@dataclass(frozen=True)
class ScoreInput:
    label: Label
    excess_return_pct: float       # ticker_total_return - sector_etf_total_return
    margin_pct: float              # the ±n% band

def score(inp: ScoreInput) -> Verdict:
    """Pure function. No I/O, no clock, no DB. Maps (label, excess_return, margin) → hit/miss."""
```

### 5.2 Hit/miss rules — DEFERRED to operator review

Hit/miss semantics per label (e.g., does BUY need `excess_return > +margin`? Does HOLD need `|excess_return| < margin`? Does TRIM hit on flat or only on negative?) are **domain decisions** — per memory rule `user_role_se_delegates_domain.md`, route to `/review-me`. Scorer signature is fixed; the rule table is a parameter the spec leaves as TBD.

Placeholder for the rule table (to be filled by `/review-me`):

| Label | Hit condition | Notes |
|---|---|---|
| BUY  | TBD | likely `excess_return > +margin` |
| HOLD | TBD | likely `\|excess_return\| < margin` |
| TRIM | TBD | likely `excess_return < +margin` or band |
| SELL | TBD | likely `excess_return < -margin` |

### 5.3 Tests — `tests/unit/eval/test_scorer.py`

Table-driven, ~12 cases covering:
- Each label × {strongly hit, marginal hit, marginal miss, strongly miss}
- Boundary cases at `excess_return == +margin` and `excess_return == -margin`
- Zero excess return for HOLD (should hit)
- Sign-flip edge: BUY with deeply negative excess return must MISS

**Test target:** <50ms total, no fixtures, no imports beyond `src.eval.scorer`.

---

## 6. Build order

1. Migrate existing `tests/` flat → categorized (Section 2). One commit, `git mv` only. *(unblocks step 2 by creating `tests/unit/eval/` home.)*
2. Author `src/eval/scorer.py` with signature from §5.1. Hit/miss rule table left TBD (pulled from `/review-me`).
3. Author `tests/unit/eval/test_scorer.py` with table-driven cases against the rule table.
4. Outer-ring Layers 2/3 — gated on companion creation spec approval.

---

## 7. Decision log (this session)

- Inner-ring layout: **A** (mirror `src/`, category subdirs)
- Outer-ring placement: **`src/eval/` separate** from `src/backtesting/`
- Fixtures: **(c) hybrid** — synthetic + live-captured
- Contract assertions: **(b) schema + key invariants**
- Build order: **Layer 1 scorer first**

---

## 8. Out of scope (defer to companion creation spec)

- `src/eval/resolver.py` — Layer 2
- `src/eval/model_health.py` — Layer 3
- `src/eval/cli.py`
- `db/migrations/042_eval_verdicts.sql`
- `.claude/commands/eval-*.md`
- Calibration trigger semantics
- Sample-size sufficiency thresholds
- Mode/materiality scoping
