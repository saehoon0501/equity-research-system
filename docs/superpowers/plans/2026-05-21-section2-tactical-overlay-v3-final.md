# Section 2 Composed Plan v3 — Tactical Overlay Implementation

**Composition iteration:** v3 (post-final-review-iteration-2)
**Status:** Iteration 2 of composed-plan review caught 3 substantive (+ 1 field-name audit) findings; v3 addresses all 4.

**v2→v3 changes (composition-level only):**
- Q1 ADDRESSED: field-name convention pin — `tactical_bin` is canonical across `TacticalSignal` dataclass + Plan B v6 emission + Plan C v5 consumption. Implementer applies the rename uniformly (one-line touch-up across the converged plans, not a re-open).
- Q2 FIXED: `metadata.locked_status` storage mechanism deferred to Section 3 (Section 2 cites candidate approaches without locking storage shape).
- Q3 FIXED: explicit Section 2.1 scope narrowing — label vocabulary only (BUY → BUY-HIGH/BUY-MED, RESOLVED at Section 2.1 v5-final; see `docs/superpowers/consensus/2026-05-21-section2.1-label-vocabulary.md`); tier-dependent mapping (which would change matrix SHAPE) explicitly punted to Section 3.
- Q4 FIXED: 40% fire-rate threshold DROPPED at Phase 1; Phase 1 reports fire rates descriptively only; threshold-setting deferred to Phase 2 when cohort data exists.

## Composition provenance (unchanged from v2)

| Source plan | Converged at | Notes |
|---|---|---|
| Plan A | Folded into Plan C v4 (cut) | — |
| Plan B | v6 | Antonacci dual-momentum classifier; emits `TacticalSignal` dataclass |
| Plan C | v5 | Cell selector + tactical_disposition mapping + renderer rules |

## Cross-plan contract (v3 — field-name convention pinned)

```python
# src/p8_tactical_overlay/contracts.py
from dataclasses import dataclass
from typing import Literal, Optional
from datetime import date

@dataclass(frozen=True)
class TacticalSignal:
    """Single source of truth for Plan B → Plan C handoff.
    Field-name convention (v3): `tactical_bin` is canonical; Plan B v6's converged
    emission uses `bin` informally — implementer applies `tactical_bin` uniformly.
    """
    ticker: str
    as_of_date: date
    tactical_bin: Literal["positive", "neutral", "negative", "unavailable"]
    rf_degenerate: bool
    unavailable_reason: Optional[Literal["insufficient_price_history", "rf_resolver_staleness"]] = None
```

**v3 field-name convention (per iteration-2 Q1 audit):** the canonical name is `tactical_bin`. Plan B v6's converged spec uses `bin` shorthand in some examples — implementer normalizes to `tactical_bin` in code. This is implementation polish, not a re-open of Plan B v6's converged state.

**INV-COMPOSE-1:** Plan B emits exactly the `TacticalSignal` shape; Plan C consumes exactly this shape. Mypy + integration test enforce.

## Architecture (Stage 1 parallel slot — unchanged from v2)

(Rationale paragraph unchanged: tactical-overlay fills wall-clock idle slot during quant + strategic MCP queries; Section 1 #7 LOCK.)

```
Stage 1 (parallel):  quantitative-analyst + strategic-analyst + tactical-overlay
Stage 2:             integrate Stage 1 → catalyst-scout
Stage 3:             pm-supervisor
Stage 4:             evaluator
```

## Plan B v6 (unchanged from converged state — emits `TacticalSignal`)

(Full algorithm + parameters + invariants + backtest gates unchanged from converged v6. Field-name normalization to `tactical_bin` at implementation time.)

## Plan C v5 (unchanged from converged state)

(Cell selector + disposition mapping + symmetric renderer + LOW-CONVICTION VETO + auto-review trigger unchanged from converged v5.)

### Provisional-status tracking (v3 — storage mechanism Section 3 deferred per Q2)

The composed plan asserts that 17 Plan C parameter rows are **Phase-1-provisional** (subject to Phase 2 recalibration). The STORAGE MECHANISM for tracking provisional-status is deferred to Section 3.

**Section 3 candidate approaches (NOT locked here):**
- (a) Extend `parameters` table with a JSON `metadata` column if not present
- (b) Sidecar table `parameters_status` keyed by parameter_key + version_id
- (c) Naming convention: append `.provisional` to provisional parameter keys; rename to drop the suffix when locked
- (d) Some other mechanism per Section 3 schema-migration design

Section 2 commits to the SEMANTIC (provisional status exists; auto-review triggers re-evaluation) without locking the IMPLEMENTATION SHAPE.

### Operator action matrix (v3 — descriptive wording preserved from v2)

(Unchanged from v2: descriptive "both visible; operator decides" framing; HMAC-signed acknowledgement; no "consider acting unless X" prescription.)

### Cell matrix + disposition mapping (Phase-1-provisional)

(2D 3×4 matrix unchanged from converged Plan C v5.)

## Falsifiability test (v3 — Phase 1 threshold dropped per Q4)

### Phase 1 (immediate, 12-envelope GOOGL cohort)

Steps 1-7 unchanged.

**Step 8 (v3 revised per Q4):** Per-label fire-rate audit — DESCRIPTIVE REPORTING ONLY at Phase 1.

- For each of the 4 renderer labels (downward OVERRIDE / upward DIVERGENCE / comparator HOLD / LOW-CONVICTION VETO), report the absolute count and per-envelope rate across the 12-envelope cohort
- **No acceptance threshold at Phase 1** (n=12 is too small to calibrate a fatigue threshold)
- Output is logged for Phase 2 calibration

**Phase 2 calibration (v3 NEW per Q4):** when N-ticker cohort accumulates (envelope_count≥50, ticker_count≥5), establish per-label fire-rate baseline from the broader cohort. Threshold for operator-fatigue concern is set BASED ON Phase 2 base rates, NOT a pre-committed guess.

### Phase 2 (broader cohort — unchanged from v2)

- Per-cell BUY-rate vs joint probability
- Per-cell realized-return demotion logic
- Establish per-label fire-rate threshold from accumulated cohort (Q4 v3 fix)

### Phase 3 (counterfactual_ledger — unchanged from v2)

## Section 2.1 follow-up (v3 — scope narrowed per Q3)

**v3 explicit scope:** Section 2.1 follow-up is **LABEL VOCABULARY ONLY**. It does NOT change matrix SHAPE (3 conviction × 4 tactical_bin = 12 cells). Specifically:

- **BUY-HIGH vs BUY-MED label split (RESOLVED at Section 2.1 v5-final)** — refines the BUY label into two sub-labels: HIGH × Positive → BUY-HIGH; MEDIUM × Positive → BUY-MED. Same 12-cell matrix; relabel BUY cell contents only. NO new cells. NO new axes. See `docs/superpowers/consensus/2026-05-21-section2.1-label-vocabulary.md` for the converged decision + INV-2.1-A disjointness invariant + Phase 2 4-quadrant decision matrix + Phase 3 18-month deadline with default re-merge.

**Tier-dependent mapping is NOT Section 2.1.** v3 reclassifies it back to Section 3:

- **Tier-dependent mapping** — would create separate matrices for core_fundamental / thematic_growth / speculative_optionality. This expands cell count from 12 → 36 (3-fold expansion). Changes matrix SHAPE, not just label vocabulary. Section 3 (or a separate Section 2.2 if operator wants it before Section 3 implementation).

**Ordering invariant (v3 NEW per Q3):** Section 2.1 (label vocabulary) must complete BEFORE Phase 1 provisional values commit to the parameters table — otherwise Phase 1 fire-rate audit runs against a matrix whose labels Section 2.1 invalidates. The 12-cell matrix SHAPE is locked at Section 2; only label vocabulary refinements happen at Section 2.1.

**Clarification (v3-polish, post-iteration-3):** Section 2.1 IS a Section-2-level deliverable (label vocabulary design decision), NOT a Phase-1 execution task. Reading order for the operator: "Section 2 locks → Section 2.1 label vocabulary resolves → THEN Phase 1 (12-envelope GOOGL audit) launches." Phase 1 should not be conflated with "Section 2 ready to launch"; Section 2.1 sits between them.

## Total parameter footprint (Section 2 v3 — unchanged from v2)

- Plan B: 12 parameter rows in `tactical.*`
- Plan C: 17 parameter rows in `tactical_disposition.*` + `tactical_cell.*` (Phase-1-provisional status, storage mechanism Section 3-deferred)
- Plan A: 0 new rows
- **Total: 29 new parameter rows** + 1 cross-plan dataclass (code, not parameter)

## Empirical anchor (v3 — caveat unchanged from v2)

12-envelope GOOGL cohort: HIGH 17% / MEDIUM 83% / LOW 0%. All HOLD/TRIM, zero BUYs.

**Caveat preserved:** single-ticker sweep-test cohort; Phase 2 recalibration via broader N-ticker REQUIRED before locking (MEDIUM × Positive) → BUY as final.

## Section 3 deferred (v3 — tier-dependent mapping moved back per Q3)

- Module implementation: `src/p8_tactical_overlay/{bin_classifier,overlay,contracts}.py`
- Agent definition: `.claude/agents/tactical-overlay.md`
- HG validator spec for tactical envelope
- Postgres migration: 29 parameter rows + Phase-1-provisional storage mechanism (one of the v3-cited candidate approaches)
- `/research-company` orchestrator update: Stage 1 parallel dispatch + PARAMETERS_USED header
- Backtest harness: Phase 1 (12-envelope GOOGL) + Phase 2 (broader N-ticker)
- counterfactual_ledger schema for Phase 3
- Integration test enforcing `TacticalSignal` dataclass at handoff
- HMAC-signing of operator-acknowledgement audit entries
- **Tier-dependent mapping (v3 reclassified back here)** — matrix shape change (12 → 36 cells); implementation-territory if operator decides to pursue

## Convergence record — composed-plan track

| Iteration | Substantive composition-level issues caught | Direction |
|---|---|---|
| v1 (initial) | 5 substantive + 1 minor (cross-plan contract; "consider acting"; Stage 1 rationale; phase-1-provisional; notice fatigue; deferral reclassification) | added (spec) |
| v1 → v2 | 5 of 5 fixed | added (spec) |
| v2 | 3 substantive + 1 audit (field-name convention; storage mechanism premature; Section 2.1 scope; threshold uncalibrated) | added (spec polish) |
| v2 → v3 | 4 of 4 fixed | polish + **cut** (40% threshold dropped; tier-dependent reclassified back to Section 3) |
| v3 | pending review | — |

## Section 2 → operator handoff (v3)

If iteration-3 signals "no substantive issues," Section 2 is locked. Plan v3 is the converged design awaiting operator execution-gate.

Upon final convergence:
- Section 2 locked → Section 2.1 (BUY-HIGH/BUY-MED label vocabulary) RESOLVED at v5-final per `docs/superpowers/consensus/2026-05-21-section2.1-label-vocabulary.md`
- Section 3 (implementation plan + backtest harness + optional tier-dependent expansion) becomes operator-actionable
