# Gap Analysis: reactive-signal-model

**Date:** 2026-05-29 · **Inputs:** `requirements.md` (8 requirements), the finalized `brief.md`, a codebase probe of `src/overlays/*`, `src/micro/*`, the parameter machinery, and the test rings. Brownfield — this spec is mostly *reuse*, so the analysis centers on how cleanly the existing pieces compose and where the requirements introduce genuinely new logic.

## Analysis Summary
- **Reuse is clean.** All three overlay compute cores (`classify` / `classify_flow` / `classify_reversion` + their pure helpers) and `src/micro/indicators.py` take arrays + scalars and do **no I/O** — import-and-pass, zero architectural coupling. `src/reactive/` does not exist (virgin). The golden-vector / no-mock test pattern (`tests/unit/overlays/*`, `tests/unit/micro/`) is the template.
- **Three real design gaps, not mere wiring:** (1) the **direction-conditional reframe** — the reused cores emit a *free* directional choice, but Req 3 needs *confidence that the caller-supplied direction is the correct side*; (2) **daily-ATR anchoring vs fixed-window sub-signals** — the overlays use fixed calendar lookbacks (252d/55d/200d), not ATR-scaled (Req 1.2); (3) **pinned param-snapshot + tighten-only lever** (Req 6) — the existing `parameters_active` view resolves *live*, which is the opposite of P2 pinning.
- **Two cross-spec dependencies on the fork's lane:** the param snapshot must carry **calibration evidence** (Req 7 — produced by `walkforward-tuning-loop`), and the decision-substrate output must match **`decision_process_trace`** fields (`decision-trace-telemetry`). Neither blocks the inner ring.
- **Sequencing unlock:** the deterministic core can be **built + inner-ring-tested NOW against module-constant defaults** (mirroring how flow/reversion do it), deferring production param-snapshot consumption to when the daemon/tuning-loop land. So reactive-signal-model proceeds independently of §14.11.

## 1. Current State (reusable assets)
- **Pure feature cores** — `src/overlays/tactical/bin_classifier.py` (`classify`, Antonacci 12mo rel/abs momentum; FRED RF resolved by *caller*, passed as scalar), `src/overlays/flow/bin_classifier.py` (`classify_flow` + `_vote_from_tsmom/_ma_distance/_donchian`; price-only, zero I/O), `src/overlays/reversion/bin_classifier.py` (`classify_reversion` + `_drawdown_from_high/_rsi_wilder/_bollinger_band_position/_ma_distance_pct`; thresholds are kwargs). `src/micro/indicators.py` — EMA/RSI/MACD/ATR/Bollinger pure math.
- **Softmax+threshold pattern** — `src/micro/signal_model.py` (pure softmax-3 over a weighted blend + temperature, ties→HOLD, insufficient-data→HOLD). Hardcoded module constants.
- **Parameter machinery** — `parameters` table + `parameters_active` view (mig 004, "latest `effective_at ≤ NOW()`" = **live** resolution); `parameters_version` UUID exists in audit tables. **No dedicated pinned-snapshot read helper.**
- **Daily-bar feed** — `mcp__market_data__get_prices(ticker, start, end, interval='1d')` → OHLCV + adj_close/total_return_close, point-in-time `as_of` guard, polygon|yfinance dispatch. (Caller-layer; compute core takes arrays.)
- **Test ring** — golden-vector, no-mock: `tests/unit/overlays/{tactical,flow}/`, `tests/unit/micro/`. **Reversion has no unit ring yet** (integration test + golden fixture only).

## 2. Requirement → Asset Map

| Req | Existing asset | Gap class |
|---|---|---|
| **1** daily-bar features | overlay cores + `indicators.py` (ATR) | **REUSE** cores; **ADAPT** near-equal aggregation + insufficient-history→HOLD (signal_model pattern); **RESEARCH** daily-ATR anchoring vs the overlays' fixed calendar windows |
| **2** calibrated probability | `signal_model.py` softmax pattern | **REUSE** pattern; **ADAPT** logit construction to the reactive features |
| **3** thresholded decision, caller-supplied direction | `signal_model.py` (argmax) | **NEW/RESEARCH** — reused cores *pick* a side; this model must take direction as input and emit *confidence-in-that-direction* + threshold. The core semantic divergence. |
| **4** subordination / non-final | — | **NEW** (low) — output non-final flag; never import/inspect survival state |
| **5** advisory sizing hint | `signal_model.py` confidence | **ADAPT** — scalar scaling with prob-above-threshold, marked advisory; no size/cap |
| **6** pinned param + tighten-only lever | `parameters_active` view, `parameters_version` | **CONSTRAINT/GAP** — existing view is *live* resolution; P2 pinning + tighten-only threshold override is new; no ready pinned-read helper; **depends on daemon (fork)** to pin+pass the version |
| **7** calibration evidence + substrate exposure | — | **NEW** output envelope; **cross-spec**: calibration evidence must be in the snapshot (`walkforward-tuning-loop`); substrate fields must match `decision_process_trace` (`decision-trace-telemetry`) |
| **8** deterministic / isolatable | `signal_model.py` purity + golden-vector tests | **REUSE** pattern; add `tests/unit/reactive/` (+ inner-ring cover any reused reversion helper, currently untested) |

## 3. Implementation Approaches

- **Option A — Extend `src/micro/signal_model.py`** (parameterize by horizon). ✅ max reuse ❌ couples a live intraday module to the reactive lane; regression risk. **Rejected** (operator-confirmed: leave `/micro` untouched).
- **Option B — New `src/reactive/` sibling, reuse pure cores** *(recommended; operator-confirmed)*. New `src/reactive/signal_model.py` + a feature adapter importing the overlay cores + `indicators.py`, its own softmax/threshold/weights, daily-ATR anchoring, param-snapshot consumption. ✅ clean separation, isolatable (P14), `/micro` untouched ❌ a little softmax scaffolding duplicated.
- **Option C — Extract a shared softmax/threshold engine** used by both `/micro` and `/reactive`. ✅ maximal DRY ❌ refactors the working intraday module now (bigger blast radius). **Defer** — graft only if duplication proves real (YAGNI).

## 4. Effort & Risk
- **Feature reuse + softmax core (Req 1,2,8):** **S–M** — pure cores exist; main new logic is the aggregation + daily-ATR anchoring. **Risk: Medium** (the daily-ATR-vs-fixed-window reconciliation is a real unknown).
- **Direction-conditional decision (Req 3,4,5):** **M** — the reframe (confidence-in-given-direction) is genuinely new design. **Risk: Medium.**
- **Pinned param + tighten-only (Req 6):** **M** — depends on the daemon/snapshot schema (fork). **Risk: Medium** — mitigated by building inner-ring against module defaults first, wiring production snapshot later.
- **Calibration/substrate output (Req 7):** **S–M** — output shaping. **Risk: Low** (just cross-spec field coordination).
- **Overall: M, Risk Medium.** No unfamiliar tech, no architectural change; risk concentrated in the direction-conditional reframe + the two fork-lane cross-spec contracts.

## 5. Recommendations for Design + Research-Needed
**Preferred approach:** Option B. **Build the deterministic core + inner-ring tests against module-constant defaults first** (P14), so the spec proceeds independently of §14.11; wire production param-snapshot consumption when the daemon/tuning-loop produce the snapshot.

**Research-Needed (carry into `/kiro-spec-design`):**
1. **Direction-conditional confidence** — how to turn the directional sub-signal aggregate into a calibrated `P(caller-direction is the correct side)` + threshold (vs the cores' free-choice argmax). The load-bearing design decision.
2. **Daily-ATR anchoring** — reconcile Req 1.2's ATR-scaled lookback with the overlays' fixed calendar windows (252d/55d/200d): ATR-scale the lookbacks, or keep fixed windows + use ATR only to normalize the probability/horizon? 
3. **Pinned param-snapshot contract (cross-spec, fork):** the schema carrying reactive params **and** calibration evidence (Brier/reliability) — owned by `walkforward-tuning-loop`; pinned+passed by `execution-daemon` (P2). Define the consumption interface; stub with defaults until it exists.
4. **Decision-substrate fields (cross-spec):** align the per-decision output (features, derived probability, effective threshold, consumed version) with `decision-trace-telemetry`'s `decision_process_trace` JSONB schema.
5. **Reversion helper coverage:** if reused, add inner-ring tests for the reversion sub-signal helpers (currently no unit ring) — P14 before any outer-ring scoring.

---

## Design synthesis (2026-05-29)

Resolved the gap-analysis Research-Needed items into design decisions (see `design.md`):

1. **Direction-conditional confidence** — directional aggregate `s in [-1,+1]` -> signed projection on the caller direction -> 2-class softmax `P = sigma(signed / T)` -> threshold. Reuses signal_model's Boltzmann/temperature pattern; P15-derived. Caller supplies direction; model emits confidence-in-that-side.

2. **Aggregation conflict behaviour (made explicit)** — `s = w_t*trend + w_f*flow + w_m*meanrev*(1 - trend_strength)`, near-equal base weights with mean-reversion **dampened by trend strength** (carried from `signal_model.py`). Genuine cross-family conflict -> `s ~ 0 -> P ~ 0.5 -> HOLD` **by design** (trade only when families agree; Survive-first). Resolves the naive-blend cancellation flagged in review.

3. **Req 1.2 CORRECTED** — the original "rescale each feature's *lookback* to a daily-ATR horizon" contradicted the confirmed reuse stance (cannot reuse `classify_reversion`'s 252d window AND rescale it). Corrected to: ATR anchors **feature normalization + decision horizon**; reused sub-signal windows stay canonical. Requirements were not yet approved; the correction is reversible by dropping the reuse stance.

4. **Pinned snapshot + tighten-only** — `ParamSnapshot` by value (P2, no live re-resolution); module-constant `DEFAULTS` for the inner ring; `effective_threshold = max(snapshot, runtime_if_higher)`; calibration evidence **exposed** (computed by the tuning-loop, not here).

**Build-vs-adopt:** adopt the overlay pure cores + `indicators.py` + the softmax pattern by import (Option B); build only the reactive adapter + decision core + param contract. No `/micro` refactor (Option C deferred, YAGNI).

**Cross-spec contracts carried forward:** `ParamSnapshot.calibration` (walkforward-tuning-loop) and `DecisionSubstrate` <-> `decision_process_trace` (decision-trace-telemetry). The inner ring proceeds against `DEFAULTS`, independent of the section-14.11 fork.

---

## Design Regeneration — validation fixes (2026-05-29)

`/kiro-validate-design` returned **GO-conditional** with three issues; `/kiro-spec-design -Y` regenerated `design.md` to fold them in. Integration-focused discovery (read-only contract extraction on the three reused cores) resolved the one blocker.

### Discovery — overlay core output contracts (exact, 2026-05-29)
Verified by reading `src/overlays/{tactical,flow,reversion}/bin_classifier.py` + `contracts.py`. All three are pure (take pre-fetched arrays; no MCP/DB).
- **tactical `classify(ticker_close, spy_close, rf_yield_pct) -> dict`** = **BIN ONLY**: returns `{bin ∈ positive|neutral|negative|unavailable, rf_degenerate, unavailable_reason}`. The continuous 12mo momentum (`rel`, `abs_`) is computed then **discarded** → no continuous vote, no continuous strength.
- **flow `classify_flow(ticker_close, spy_close, ...) -> dict`** = **CONTINUOUS EXPOSED**: `components.composite_score_normalized ∈ [−1,+1]` is a direct signed vote; `abs(...)` is a [0,1] strength.
- **reversion `classify_reversion(ticker_close, **thresholds) -> dict`** = **MIXED**: categorical `bin ∈ MR_OVERSOLD|MR_NEUTRAL|MR_OVERBOUGHT|MR_UNAVAILABLE` + exposed continuous components (`rsi_14`, `drawdown_from_252d_high_pct`, `bollinger_band_position`, `ma_distance_200d_pct`).

### Synthesis decisions (folded into design.md)
1. **Issue 2 (vote derivation, the blocker) — resolved with an explicit convention.** `trend_vote` = tactical bin→{+1,0,−1,0}; `flow_vote` = `composite_score_normalized` field read; `meanrev_vote` = reversion bin→{`MR_OVERSOLD:+1`, `MR_OVERBOUGHT:−1`, neutral/unavailable:0}. **Sign trap caught:** mean-reversion is contrarian — oversold is **+1 (LONG-favoring)**, not −1 (the discovery agent's own draft had it inverted). Unit-tested via a mirror test.
2. **`trend_strength = abs(flow_vote) ∈ [0,1]`** — tactical is bin-only (degenerate as a strength) and reversion is the dampened term, so the flow composite magnitude is the only continuous trend-conviction signal exposed. v0.1 choice; tactical+flow agreement blend noted as a refinement.
3. **Input-contract correction.** `compute_features` cannot take only `(daily_bars, atr_period)`: tactical+flow need **SPY closes**, tactical needs **rf_yield_pct**, and `indicators.atr` needs OHLC bars. Signature widened to `(ticker_bars, spy_close, rf_yield_pct, atr_period)`; fetch stays caller-side (boundary unchanged).
4. **Issue 1 (horizon) — clarified, not redesigned.** Prediction horizon = days-to-weeks; **hold lifecycle = intraday-flat-by-close** (daemon/`survival-gate`, §16.1). Added a calibration outcome-alignment revalidation trigger: the tuning-loop must score against the intraday-with-daily-reentry realization (§12.5 outer-ring question). No requirements change — input-contract + horizon are design-level.
5. **Issue 3 (vocabulary) — precision fixes.** "calibrated confidence" → "model-derived probability (calibration established downstream)"; conflict→HOLD relabelled from "Survive-first" to a **conservative Edge default** (Survive is enforced downstream and lexicographically above, §13). Also: the 2-class logistic framed not as a "specialization" but as a **deliberate drop** of `_softmax3`'s liquidity hold-logit (liquidity/survival = the gate's job, §13).

---

## Pass-2 validation — design converged, loop terminated (2026-05-29)

`/kiro-validate-design` pass 2 returned **GO** (pass 1 = real blocker → pass 2 = interface nits = healthy convergence). Per advisor, the validate-loop self-perpetuates on open "either-is-fine" micro-choices, so they were **decided** in `design.md` to terminate it (all low-stakes, trivially reversible in code):
- **`Bar`** → a `TypedDict` (OHLCV), structurally a `dict` so it passes straight to `indicators.atr(Sequence[dict])`; keys validated at the `compute_features` boundary. Chosen over bare `dict` because the design is a **cross-session contract surface** the §14.11 fork reads.
- **Failure handoff** → `compute_features` returns a discriminated `FeatureFailure(reason ∈ {insufficient_history, degenerate_features})` (covers `atr → None`); `features` owns history+ATR checks, `decide` owns `invalid_direction` and maps failures → HOLD. Single-owned reasons.
- **Weights** → normalized `Σw = 1` (so `s ∈ [−1,+1]`); interpretive only (temperature would otherwise absorb scale) — settled, not a critical issue.

**Real verification now shifts from doc review to P14 unit tests** (Bar-is-a-dict, atr→None, the discriminator all resolve the instant code+tests exist). Self-validation ceiling reached; next action is `/kiro-spec-tasks`, not a pass 3.

---

## Correlation-key seam vs the LANDED decision-trace-telemetry contract (2026-05-30)

**Trigger:** operator flagged that this spec lists only 2 of the 4 correlation keys the landed telemetry table demands. Verified against the shipped artifacts (fork's lane — cited, not edited): `db/migrations/048_decision_trace_telemetry.sql` + `src/reactive/telemetry/schema.py`.

**Landed contract:** `decision_process_trace` has **4 typed correlation columns** — `run_id NOT NULL`, `code_version NOT NULL`, `param_version NOT NULL`, `walk_forward_window NULL` — plus a JSONB `trace`. `CorrelationKeys` = `{run_id, code_version, param_version, walk_forward_window}`.

**Resolution — the 2/2 split is FORCED, not a defect.** The telemetry design makes the `execution-daemon` the *writer's caller / row-assembler*: it mints the client-side `trace_id` and pins `event_ts` (decision time). A pure feature→probability model can supply neither — so the daemon is unavoidably the assembler. This model legitimately emits only the **2 keys it owns** (`code_version` = its own version; `param_version` = the consumed `ParamSnapshot` version, same semantics as telemetry's column). `run_id` (run-context) and `walk_forward_window` (tuning-orchestration context) are not model inputs/outputs. There is no architecturally consistent world where the model carries 4 — it can never be a self-contained telemetry row. (Making the model carry 4 would be a change to the *telemetry* contract — fork's lane — not this spec.)

**What WAS wrong (now fixed in design.md):** the spec called `code_version`/`param_version` "the shared correlation keys," which understated the landed 4-key contract and never handed the other two to the daemon. Fixed: cite the landed 4-key `CorrelationKeys`; state the substrate→row mapping (the 2 keys promote to typed columns; `feature_values`/`probability`/`effective_threshold`/`calibration` → JSONB `trace`); pin `param_version`/`code_version` semantic identity across the seam.

**⚠️ Forward-obligation (currently UN-OWNED):** no briefed spec assigns population of `run_id` + `walk_forward_window`. The telemetry spec states only a generic "complete `CorrelationKeys`" precondition; `execution-daemon` (the assembler) is **un-briefed**. Pinned in this spec's design Open Questions as a forward-obligation: **`execution-daemon` MUST populate `run_id` + `walk_forward_window` when assembling the `DecisionTraceRow`.** If lost, the first live write throws `run_id NOT NULL`. Carry into the `execution-daemon` brief.
