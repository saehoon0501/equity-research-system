# Implementation Plan

> `reactive-replay-harness` — a pure compute leaf at `src/reactive/replay/` consuming the landed reactive cores + the DESIGNED survival cores (stubbed in unit tests until `survival-gate` lands) + the landed broker paper-fill sim, over a NEW Massive historical REST client. No DB table (read-only consumer). Inner-ring first (P14): `tests/unit/reactive/replay/` + one `integration_live` Massive smoke. Sanity-reviewed 2026-05-30 (2 reviewers); the intraday simulator was split per the sizing review.

- [ ] 1. Foundation: contract types, Massive data client, test scaffolding

- [x] 1.1 Define the shared contract types
  - Frozen dataclasses: `Candidate` (param_snapshot / survival_parameters / code_version), `ReplayWindow` (start, end, tickers), `Fill` (side, price, volume, ts), `OutcomeRecord` (period, symbol, decision, predicted_probability, fills, total_return_pnl, survival_events, realized_outcome, realized_label), `ReplayResult` (records + fidelity), `FidelityResult` (status pass|fail|not_evaluable + detail); plus the `DataPort` `Protocol` (point-in-time fetch signatures)
  - Reuse the decision vocabulary from `src.reactive.types` and `Label` from `src.calibration.scorer` (no re-declaration)
  - Observable: all types import cleanly; `OutcomeRecord` exposes the nine fields; `walkforward-tuning-loop` can import `OutcomeRecord`/`ReplayResult` from here
  - _Requirements: 1.3, 8.1_
  - _Boundary: types_

- [x] 1.2 Build the Massive historical REST transport
  - Mirror `src/mcp/broker/gate_client.py`: `httpx` client, `apiKey` auth from `MASSIVE_API_KEY`/`.env`, structured `Result`/`Error` (never raises), rate-limit parsed from response headers, injected-transport seam for tests; document `MASSIVE_REST_URL` in `.env.example`
  - Observable: a fixture-transport unit test returns a structured `Result` on 200 and a structured `Error` (no exception) on 429/5xx
  - _Requirements: 4.1_
  - _Boundary: data_client_

- [x] 1.3 Implement the point-in-time fetch methods (implements `DataPort`)
  - Fetch daily + intraday aggregate bars with `adjusted=false`, tick trades, NBBO quotes, grouped-daily (universe), splits + dividends reference, and the FRED risk-free yield
  - Point-in-time bounded (no rows after the requested instant for decision inputs); paginate past the per-request row cap; retrieve delisted names over their trading window; **fail explicitly** when a window predates available depth (no silent truncation / partial window)
  - Observable: fixture-transport unit tests — `adjusted=false` is sent; a `>cap` fixture paginates to completion; a window beyond fixture depth raises an explicit error (not a partial result); a delisted-name fixture returns its trading-window bars
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 5.1, 6.1_
  - _Boundary: data_client_
  - _Depends: 1.2_

- [x] 1.4 (P) Build the test scaffolding (fixture DataPort + stub cores)
  - A fixture `DataPort` (deterministic canned responses), stub reactive `decide`/`compute_features` and stub survival `admit`/`assess` (DESIGNED-not-landed), and fixture decision/fill rows; lay out `tests/unit/reactive/replay/` per the repo per-module convention and register the `integration_live` path
  - Observable: a smoke unit test imports the fixtures + stubs and runs with no network/DB/LLM
  - _Requirements: 9.2_
  - _Boundary: tests_
  - _Depends: 1.1_

- [ ] 2. Core: the backtest engine

- [x] 2.1 (P) Feature adapter — daily features + as-of split rule
  - Assemble the daily feature inputs (ticker daily adj-close + SPY + rf-yield + OHLC) from the `DataPort` and drive the landed `compute_features`; never reimplement the overlay cores
  - Apply the as-of split rule: split-adjust feature-window closes for ex-dates ≤ the as-of instant only (in-window pre-T splits applied; post-T never)
  - Observable: unit test — features for day D use only data ≤ D; an in-window split is applied while a post-D split is not
  - _Requirements: 3.1, 4.2_
  - _Boundary: features_adapter_
  - _Depends: 1.3_

- [x] 2.2 (P) Fidelity comparator (pure)
  - FIFO entry/exit fill-pairing per (day, symbol) under the §16.1 one-position invariant → recorded-champion P&L; compare to simulated-champion P&L within a configured tolerance; return pass / fail / not-evaluable (sparse or absent baseline ⇒ not-evaluable, distinct from fail); abort with a pairing-ambiguity signal on a non-round-trip day (never a silent undercount)
  - Pure: no I/O, no `simulator` import (the harness supplies both sides)
  - Observable: unit tests — within-tolerance ⇒ pass; injected mismatch ⇒ fail; empty baseline ⇒ not-evaluable; an ambiguous multi-leg day ⇒ pairing-ambiguity abort
  - _Requirements: 7.1, 7.2, 7.3_
  - _Boundary: fidelity_
  - _Depends: 1.1_

- [x] 2.3 Simulator — daily decision layer + divergence detection
  - Prefetch the champion decisions for the window once (indexed by day, symbol); per trading day drive the landed `decide` with the candidate `ParamSnapshot`; flag divergence vs the champion's indexed decision (incl. champion-HOLD vs candidate-actionable) to trigger an intraday re-fetch; reconstruct the candidate's OWN decision path, never the champion's outcomes
  - Observable: unit test (stub `decide`) — a divergent-decision day is flagged for re-fetch; a non-divergent day reuses recorded inputs; identical inputs ⇒ identical decisions
  - _Requirements: 2.1, 2.2, 3.1, 3.3_
  - _Boundary: simulator_
  - _Depends: 2.1_

- [x] 2.4 Simulator — decision→order + survival gating
  - Construct the order from a decision (volume from `sizing_hint` + `per_order_size_max`; venue side via `map_decision_to_action`); drive the landed/stub survival `admit` (candidate `SurvivalParameters`) and step the sequential account path; a HOLD or `admit=REJECT` yields a flat day. Code-track candidates (run candidate code end-to-end) are **deferrable for v0.1** (param-track first) — left as a guarded branch, not built now
  - Observable: unit test (stub survival) — an actionable decision produces an order at `advisory_max_volume` when admit caps it; a rejected/HOLD day stays flat
  - _Requirements: 2.3, 3.2, 3.3_
  - _Boundary: simulator_
  - _Depends: 2.3_

- [x] 2.5 Simulator — fill realism + intraday stop-hit
  - Drive the landed `paper.simulate` at counterparty (bid/ask) prices, not mid; determine whether a protective stop level was reached from the intraday price path
  - Observable: unit test (stub paper / fixture intraday) — a fill prices at the correct historical bid/ask side; a stop level inside the intraday range registers a hit; one outside does not
  - _Requirements: 6.1, 6.2_
  - _Boundary: simulator_
  - _Depends: 2.4_

- [x] 2.6 Simulator — §16.1 flatten + verify-flat post-condition
  - Force-flatten before close; verify a flat post-condition (am-I-actually-flat, not just "fired the order") and escalate / re-fire if not
  - Observable: unit test — a day with open exposure force-flattens before close and the verify-flat post-condition asserts flat; a non-flattened path is detected and escalated
  - _Requirements: 2.3_
  - _Boundary: simulator_
  - _Depends: 2.5_

- [x] 2.7 Simulator — total-return P- [ ] 2.7 Simulator — total-return P&LL (dividends credited separately)
  - Per-day round-trip P&L = `(exit − entry) × filled_volume × dir` + same-day cash dividends; never assume bars are dividend-adjusted
  - Observable: unit test — P&L credits a fixture cash dividend separately from the price change; a dividend-paying name is not mis-scored
  - _Requirements: 5.1, 5.2_
  - _Boundary: simulator_
  - _Depends: 2.6_

- [ ] 2.8 Outcome-record assembly
  - Assemble the per-period `OutcomeRecord` from the simulator output (decision, predicted probability, fills, total-return P&L, survival events, realized outcome + label); compute NO survival-net metric, calibration, or gate (the consumer's)
  - Observable: unit test — a record carries all nine fields; the module exposes no metric/gate function
  - _Requirements: 8.1, 8.2_
  - _Boundary: outcomes_
  - _Depends: 2.7_

- [ ] 3. Integration: the harness entry point

- [ ] 3.1 Wire `replay_candidate` + the champion re-sim orchestration
  - `replay_candidate(candidate, window, *, data_port=None, conn=None)`: construct the production `DataPort` over the data client when none is injected; run the simulator; assemble outcomes; return `ReplayResult`
  - Champion re-sim: read the champion's pinned config (`ParamSnapshot` + `SurvivalParameters`) from P2 `run_parameters_snapshot` by `param_version` and the champion fills via `query_trace`; run the simulator on the champion config; call `fidelity.compare(simulated, recorded)` and attach the `FidelityResult`
  - Enforce the consumption boundary: read-only (no writes to trace/ledger); no CPCV / metric / gate / fit / publish / live-trading
  - Observable: an integration test (fixture port + stub cores) — `replay_candidate` returns `ReplayResult{records, fidelity}`; a champion-version run attaches a fidelity verdict; the module touches no out-of-boundary surface
  - _Requirements: 1.1, 1.2, 7.1, 10.1, 10.2_
  - _Boundary: harness_
  - _Depends: 2.2, 2.7, 2.8, 1.3_

- [ ] 4. Validation

- [ ] 4.1 Determinism + isolation suite
  - Identical (candidate, window, fixture-port responses) ⇒ identical `OutcomeRecord`s; the whole engine runs with stub cores + fixture data and no network/DB/LLM; assert the reactive/survival logic is driven (via stubs), never recomputed; a changed stub-core signature is caught (revalidation guard)
  - Observable: `pytest tests/unit/reactive/replay/` passes deterministically with no external services
  - _Requirements: 9.1, 9.2, 10.3_
  - _Depends: 3.1_

- [ ] 4.2 (P) Massive `integration_live` smoke _Blocked: needs live Massive Advanced/Business key (operator-gated)_ — the live-probe gate
  - Marked `integration_live` (skipped by default). Confirm the four unverified-in-research items: SPY + a sample S&P 500 symbol resolve; `/v3/trades` + `/v3/quotes` return for a past window; the splits/dividends/market-holidays reference endpoints answer 200 (not 403) on the account tier; a delisted name returns OHLC for its trading period
  - Observable: `pytest -m integration_live` against a live Massive Advanced/Business key passes, or reports the precise gap
  - _Requirements: 4.1, 4.4, 6.1_
  - _Boundary: data_client_
  - _Depends: 1.3_

- [ ] 4.3 E2E cycle — champion-reproduction + not-evaluable
  - Seeded one-config, one-window replay → `OutcomeRecord`s; a champion-version replay reproduces a seeded fill P&L within tolerance ⇒ fidelity pass; a sparse-baseline window ⇒ not-evaluable — end to end with fixtures
  - Observable: the E2E test asserts both the champion-reproduction pass and the not-evaluable branch
  - _Requirements: 1.1, 7.1, 7.3, 8.1, 9.1_
  - _Depends: 3.1_

## Implementation Notes
- 1.2: worktree has no root dep manifest; `httpx` was installed into `.venv-replay` (uv). Reuse that venv for all tasks; if rebuilt, `uv pip install httpx pytest python-dotenv` first.
- 1.3: `fetch_quotes`/`fetch_trades` bound at DAY granularity; if the simulator (2.3+) passes a sub-day instant for instant-precision fills, tighten the bound there to avoid same-day-later leakage (R4.1). And `DataPort.fetch_corporate_actions` reconciled types.py to `-> dict {splits,dividends}`.
- 1.4: survival stubs mirror the in-progress survival-gate-impl: `admit(order,state,op_state,params,clock,evaluation)` carries a 6th `OrderEvaluation` arg (design omitted it) — task 2.4 must construct it. Stub INPUTS are `Any` (name/order match only). On survival landing: delete local mirrors, import from src.survival, re-run signature tests.
- 2.2: fidelity.compare takes HARNESS-SYNTHESIZED recorded-fill dicts {day,symbol,direction,side,actual_fill_price,fill_volume} (schema fill rows lack symbol/side — they live in the decision JSONB; the harness/3.1 must do the parent_trace_id->decision join). DIVIDEND-BASIS asymmetry: recorded side price-only vs simulated total-return -> a dividend day can false-fail (conservative, P7). 3.1/4.3 + calibration: set tolerance to absorb it OR strip dividends from the simulated side before compare.
- 2.3: DIRECTION GAP (linchpin) — reactive `decide` takes direction as INPUT (returns it or HOLD); replay hard-defaults LONG, so SHORT is unreconstructable and champion-SHORT days fail fidelity (R7). Direction is chosen upstream by the daemon (not landed). Also: champion symbol key `trace["symbol"]` is a guess (daemon-minted, schema-free) — fails loud if absent; retarget on daemon landing.

## BLOCKED (paused 2026-05-30 — operator decision: pause the chain for the daemon's direction rule)
- **2.4, 2.5, 2.6, 2.7, 2.8, 3.1, 4.1, 4.3 — BLOCKED on the direction-selection rule.** `decide` takes direction as an INPUT; the daemon's long/short selection rule is not landed/specified. Hard-defaulting LONG breaks champion-SHORT fidelity (R7), so the simulator chain + harness + their validation are paused until the rule lands. **Routing: owned upstream — execution-daemon (§12.3 "direction comes from the reactive layer") and/or reactive-signal-model.** When that contract lands, resume at 2.4 (read champion's recorded direction for fidelity; apply the landed rule for candidate direction) and clear these blocks.
- **4.2 — BLOCKED on a live Massive Advanced/Business API key** (operator-gated; the unit suite uses fixtures).
- **DONE + green (1.1–2.3):** types, transport, fetch-methods, scaffolding, feature-adapter, fidelity, simulator-daily — 81 unit tests pass in `.venv-replay`.
- RESUME 2026-05-30: direction-selection rule SPECIFIED (execution-daemon R2.3/R2.4 + Req 12.5, §12.3): tactical bin->direction (positive=LONG, negative=SHORT, neutral|unavailable=no-trade), read FeatureSet.raw["tactical_bin"]. survival-gate LANDED (merged a45f072). 2.3 amended to the rule (SHORT reconstructable, R7 unblocked). 2.4+ proceeding with real src/survival imports + the daemon order_builder pattern (SHORT-open=BUY+SHORT, ATR stop-loss, reference_price). 4.2 still blocked on a live Massive key.
- 2.5: real `paper.simulate` is un-importable from repo root (bare `from models import` resolves only under the broker MCP launch posture) — MIRRORED its side-aware pricing (LONG->ASK, SHORT->BID uniform, since ProposedOrder.direction encodes the marketable side for opens+reduces). Revalidation seam: if broker is made importable, a CLOSE OrderIntent must carry the HELD-position direction (paper.py keys close on position dir).
- 2.6: DayRoundTrip{entry_fill,exit_fill,exit_reason,flat_verified,survival_events} is the 2.7 seam. Two revalidation triggers: (a) flatten-leg volume=abs(net from entry_fill) vs stop-hit-leg volume=entry_order.volume — net flat only when equal; (b) close_ts defaults to day (not close instant) — fix when real data_client lands.
