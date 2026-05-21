# /grill-me Section 1 consensus — calibration overlay design

**Date:** 2026-05-21
**Session purpose:** Resolve the values question on /research-company's 0-BUY-across-24-tickers outcome and lock the design approach for closing the consensus-fit gap.
**Status:** LOCKED (Section 1)

## Operator profile (captured during session)

- **Scale**: 24 tickers researched to date across core_fundamental + thematic_growth + speculative_optionality tiers
- **Goal**: outputs should land "at least close to market consensus" for all tickers (per 2026-05-21 stated preference)
- **Constraints**: minimal + simple; investment-logic decisions → /review-me, not operator chair; describe-not-prescribe specific parameter values
- **Success criteria**: per-ticker outputs should be differentiable + market-aware without diluting Damodaran/Mauboussin framework's analytical contribution
- **Falsifiability**: if the proposed overlay design produces the same HOLD-on-everything output as the current pipeline, the design is wrong

## The position / thesis (refined form)

**Operator's framing (after pushback on bug/signal binary):** two competing hypotheses to discriminate empirically —

- **H1 (pessimism bug)**: conservatism is a fixable parameter-calibration issue within the existing framework
- **H2 (framework-inherent)**: Damodaran narrative DCF + Mauboussin outside view are *intrinsically* conservative by design; the 30-50% IV/spot gap is a *feature* of the framework choice

**Conditional implication if H2:** tuning framework parameters dilutes the analytical value of the framework. The right move is to ADD a separate compensation overlay that bridges the fundamental-conservative output to a more market-aligned view, WITHOUT modifying the upstream framework.

**Research-grounded verdict** (per `docs/superpowers/research/2026-05-21-framework-conservatism-and-compensation-overlays.md`): **H2 dominates (~80%) with H1 residual (~20%)**.

Damodaran himself frames the IV/price gap as **price discipline requiring catalyst identification**, not model misspecification. Mauboussin's outside view is **explicitly a corrective** against inside-view analyst optimism via Bayesian shrinkage to cohort base rates. The H1 residual lives in the *uniformity* of 0-BUY-across-24-tickers, but the right response is a downstream overlay, not upstream framework tuning.

**Notable disclosure** from research: even Damodaran himself acknowledged in his Sep 2024 NVIDIA writeup that "the company can scale up more than I thought it could, has higher and more sustainable margins than I predicted" — feeding the H1 residual but not overturning the H2-dominant verdict.

## Locked consensus items

### Consensus Item #1 — H2 verdict locked

The framework's conservatism is intrinsic-by-design, not a parameter-calibration bug. ~80% confidence per the research artifact. Source: `docs/superpowers/research/2026-05-21-framework-conservatism-and-compensation-overlays.md`.

**Implication**: tuning Damodaran terminal-growth premium, Mauboussin Bayesian shrinkage r, or cohort means dilutes the analytical contribution of the framework. NOT the right response.

### Consensus Item #2 — Preserve framework analytical value

Damodaran/Mauboussin framework parameters are NOT to be tuned to close the consensus-fit gap. The frameworks remain at their canonical values (or operator-curated values via /review-me, but specifically NOT as a response to the 0-BUY-across-24-tickers concern).

**Implication**: the v5-final calibration plan (proposed earlier this session) is DISMISSED as the response to the consensus-fit concern. v5-final remains valid as a separate workstream IF the operator decides framework parameters need attention for other reasons, but it does NOT address the present concern.

### Consensus Item #3 — Add compensation overlay downstream

The right design pattern is to ADD a compensation overlay downstream of the LLM-orchestrated research pipeline, NOT to modify the upstream pm-supervisor / quant / strategic agents. This preserves the framework's analytical value while adding a separate signal layer that translates fundamental-conservative output into market-aware output.

**Implication**: new stage(s) in /research-company; no changes to existing agent prompts.

### Consensus Item #4 — Soft-modulator composition

The overlay produces a separate signal block alongside pm-supervisor's existing output. Final emitted recommendation surfaces BOTH the fundamental verdict and the composed verdict; the overlay does NOT silently override pm-supervisor's verdict. Multiple signals visible in the audit trail.

**Implication**: the new overlay stage emits an additional envelope; pm-supervisor's envelope remains unmodified; the final operator-facing output report carries both signals.

### Consensus Item #5 — 2D Conviction × Timing matrix with pre-committed mandates

Composition rule = a 2D grid:
- **Axis 1 (Conviction)**: pm-supervisor's HIGH / MEDIUM / LOW (existing 3 bins)
- **Axis 2 (Timing)**: tactical signal bin pos / neutral / neg (3 bins from Antonacci dual-momentum)
- **Matrix size**: 3×3 = 9 cells; each with a pre-committed size mandate

**Precedent**: Druckenmiller / Soros-era macro-fund architecture. Pre-commitment eliminates ad-hoc rationalization in the moment. Cell-to-size mapping is deterministic config (parameter table), NOT LLM judgment per decision.

**Implication**: 9 cell-mandate values become a new parameter table block (`cell_mandate.conviction_timing.<conviction>_<timing>.size_pct`); /review-me locks the values. Plus 2 bin-threshold parameters for the tactical axis.

### Consensus Item #6 — Hybrid LLM agent + deterministic Python

The new overlay stage is hybrid:
- **LLM Agent component**: new `tactical-overlay` agent emits a structured envelope (parallel to catalyst-scout's envelope shape) — `tactical_signal_bin` (pos / neutral / neg) with reasoning + evidence_refs
- **Deterministic Python component**: cell-mandate lookup from `(conviction, tactical_signal_bin)` tuple → pre-committed size_mandate; underlying Antonacci dual-momentum compute is also deterministic Python

**LLM vs Python split**:
- LLM does qualitative tactical-signal-bin classification (with reasoning for audit trail; surfaces anomalies like "momentum positive but volume collapsing")
- Python does the mechanical momentum compute + the 2D cell lookup (no LLM judgment per ticker)

**Implication**: new agent definition at `.claude/agents/tactical-overlay.md`; new Python module at `src/p8_tactical_overlay/` for compute + lookup; new HG validator for tactical envelope shape (mirroring HG-31 catalyst_memo_shape pattern).

### Consensus Item #7 — Stage 1 slot (parallel with quant + strategic)

The new tactical-overlay agent dispatches in Stage 1 in parallel with quantitative-analyst + strategic-analyst. Has no upstream dependency — only needs ticker + market data via mcp__market_data.

**New chain**:
- **Stage 1 (parallel)**: quantitative-analyst + strategic-analyst + **tactical-overlay**
- **Stage 2**: integrate Stage 1 → catalyst-scout (sequential, consumes integrated CDD memo including tactical_signal_bin)
- **Stage 3**: pm-supervisor (consumes all upstream; runs deterministic `derive_cell_mandate()` helper for size lookup; outputs both fundamental verdict AND cell-mandate composed size)
- **Stage 4**: evaluator (single end-gate as today)

**Implication**: /research-company orchestrator (skill markdown) updated to add tactical-overlay to Stage 1 parallel dispatch. Stage 1 PARAMETERS_USED header block for tactical-overlay includes `tactical.*` namespace.

## Critical architectural findings

### Finding A — Antonacci dual-momentum signal

Pattern 1 from the research artifact (top recommendation):
- Relative momentum: 12mo total return vs benchmark (e.g., SPY)
- Absolute momentum: 12mo total return vs risk-free rate (T-bill / DGS10)
- BOTH positive → tactical_signal_bin = positive
- BOTH negative → tactical_signal_bin = negative
- Mixed → tactical_signal_bin = neutral

Mechanical formula. Empirical track record: 20+ years of academic validation (Antonacci 2014 + follow-up replications). Implementation complexity: low (just compute price relatives over 12mo windows).

### Finding B — Asymmetric loss complement (Pattern 5)

Per the research artifact, Pattern 1 should be complemented by Pattern 5 — pipeline-stage separation with asymmetric loss threshold. This means cell mandates should NOT be symmetric: the cost of "missing a quality compounder when momentum confirms" is different from the cost of "buying an overpriced compounder when momentum reverses." Operator decides asymmetry magnitude via /review-me.

**Implication**: cell-mandate values are not a simple table — they encode operator's asymmetric loss preference. /review-me must surface the asymmetry tradeoff explicitly when locking values.

### Finding C — Catalyst-scout coexistence

catalyst-scout (forward 90d catalysts) and tactical-overlay (trailing 12mo momentum) are different signal types. Both consumed by pm-supervisor downstream. They can disagree.

**Resolution per Consensus Item #4 (soft-modulator)**: pm-supervisor's output surfaces both modifiers + the cell-mandate composed size. No silent merging. Operator-facing report shows the disagreement explicitly when it exists.

## Design changes from prior baseline

| Component | Prior baseline | Post-Section-1 |
|---|---|---|
| Calibration objective | "close to consensus" via framework parameter tuning (v5-final plan) | "close to consensus" via downstream tactical overlay; framework parameters unchanged |
| Pipeline shape | Stage 1 (quant+strategic) → Stage 2 (catalyst-scout) → Stage 3 (pm-supervisor) → Stage 4 (evaluator) | Stage 1 (quant+strategic+tactical-overlay) → Stage 2 (catalyst-scout) → Stage 3 (pm-supervisor + cell-mandate lookup) → Stage 4 (evaluator) |
| Sizing logic | pm-supervisor's conviction × mode multiplier × sleeve cap → size band | pm-supervisor's conviction × tactical_signal_bin → cell-mandate lookup → size mandate (sleeve-cap aware) |
| Source of size_band | LLM-derived from conviction tier | Deterministic 2D table lookup (pre-committed); LLM-emitted tactical_signal_bin feeds Axis 2 |
| Audit trail | conviction + size + summary_code | conviction + tactical_signal_bin + cell coordinates + cell_mandate_size + summary_code (all visible) |

## Deferred items

| Item | Why deferred | Activation trigger |
|---|---|---|
| Specific cell-mandate values (9 cells × size_pct) | Domain decision — /review-me territory per operator-role rule | After Section 1 lock, dispatch /review-me on the cell-mandate matrix |
| Tactical-axis bin thresholds (positive_min / negative_max momentum cuts) | Domain decision | /review-me on tactical bin thresholds; could be co-located with cell-mandate /review-me |
| Asymmetric loss magnitude | Domain decision per Finding B | /review-me on the asymmetry tradeoff |
| Backtest design before production wiring | Implementation-detail decision | After Section 2 (implementation plan) drafted |
| H1 residual address (20% of conservatism is fixable) | Scoped out of Section 1 — overlay is the H2 response; H1 residual addressed separately if at all | Operator-initiated; not a current priority |
| 2027-Q2 realized-returns calibration milestone | Time-gated by counterfactual_ledger window closures | 2027-Q2 (when 12mo windows close on the oldest ledger rows) |

## What's locked vs what's open

**Locked (Section 1 — this document)**:
- H2 verdict + research grounding
- Framework parameters preserved
- Overlay added downstream (soft-modulator, 2D matrix)
- Hybrid LLM + Python; Stage 1 parallel slot
- Architectural placement and component split

**Open (deferred to subsequent sections / workstreams)**:
- Cell-mandate values (Section 2 — /review-me)
- Tactical-bin thresholds (Section 2 — /review-me)
- Asymmetric loss magnitude (Section 2 — /review-me)
- Implementation plan + backtest design (Section 3 — after Section 2)
- HG validator spec for tactical envelope (Section 3 implementation)
- PARAMETERS_USED header composition logic for tactical-overlay (Section 3 implementation)

**Next operator action**: dispatch /review-me on the deferred domain items (Section 2), OR ask the system to draft Section 2 directly with /review-me embedded in the proposal.
