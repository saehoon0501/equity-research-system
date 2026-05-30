# Research & Design Decisions — reactive-replay-harness

## Summary
- **Feature**: `reactive-replay-harness`
- **Discovery Scope**: Complex Integration (a net-new point-in-time backtest engine that drives landed reactive cores + DESIGNED survival cores + the landed paper-fill sim over a new Massive historical client)
- **Key Findings**:
  - **Two data layers**: the reactive *decision* runs on **daily** bars (the overlay cores need 252+ daily adj-closes); **intraday** bars/trades/quotes drive **fill simulation + stop-hit + §16.1 flat-by-close**. This split is the engine's spine.
  - **Most dependencies are LANDED**: `src/reactive/signal_model.py::decide`, `features.py::compute_features`, `params.py::ParamSnapshot`, the overlay cores, `src/micro/indicators.py::atr`, `src/mcp/broker/paper.py::simulate`, `src/reactive/telemetry/reader.py::query_trace`, the `counterfactual_ledger`, and `src/mcp/fred` `get_series`. Only the **survival cores** (`src/survival/gate.py` `admit`/`assess`) are DESIGNED-not-landed → stub in inner-ring tests.
  - **Build only the Massive historical REST client** (the real-time `massive` MCP server is unsuitable) + the simulation loop + fidelity + outcome assembly. Module lives at **`src/reactive/replay/`** (a compute leaf sibling to `telemetry/`, NOT `src/skills/`).

## Research Log

### Driven cores + feature contracts (LANDED reactive / DESIGNED survival)
- **Sources**: `src/reactive/{signal_model.py:212, features.py:88, params.py:30, types.py}`; `src/overlays/{tactical,flow,reversion}/bin_classifier.py`; `src/micro/indicators.py:116`; `.kiro/specs/survival-gate/design.md`.
- **Findings**: `decide(features, direction, snapshot, runtime_threshold) -> ReactiveDecision`; `compute_features(ticker_bars, spy_close, rf_yield_pct, atr_period) -> FeatureSet|FeatureFailure`; `ParamSnapshot{weights, temperature, threshold, calibration, code_version, param_version}`. Overlay cores consume **252+ daily adj-closes** (tactical+flow need SPY; tactical needs rf). `atr` consumes OHLC bars. Survival `admit(order,state,op_state,params,clock)` / `assess(state,op_state,params,clock)` + `SurvivalParameters` + `AccountState`/`Position`/`OperationalState`/`ClockState`/`ProposedOrder`/`AdmitDecision`/`AssessDirective` — all DESIGNED in `survival-gate/design.md`, not yet coded.
- **Implications**: param-INDEPENDENT features (ATR/MA200/RSI/Bollinger/252d-high, computed from daily bars) can be cached and reused across candidate configs; only the param-DEPENDENT aggregate→softmax→threshold is recomputed per candidate. Decisions are **daily**; the account path is intraday.

### Paper-fill sim + telemetry/ledger reads (LANDED)
- **Sources**: `src/mcp/broker/paper.py:102-161`, `models.py`, `mappers.py`; `src/reactive/telemetry/reader.py:123`; `db/migrations/048_*.sql`, `003`, `030`.
- **Findings**: `paper.simulate(intent, *, bid, ask, position_volume, transport) -> OrderResult` — pure, stateless, side-aware fill pricing (BUY→ASK, SHORT-open→BID, closes opposite), side via `mappers.map_decision_to_action` (must reuse). `query_trace(filters, conn=None)` filters on the 4 keys + `kind` + `since`/`until`; rows carry the full column set + JSONB `trace`. `counterfactual_ledger` holds version-attributed realized return columns (`system_return`, `vs_sector_etf_return_pct`, …) per (code_version, param_version, walk_forward_window); fill rows in `decision_process_trace` carry actual_fill_price/slippage.
- **Implications**: the harness feeds the paper sim **historical** bid/ask and tracks its own position state (sim is stateless). The fidelity baseline (R7) is the champion's **recorded fills** (decision_process_trace `kind=fill`) as the fine-grained check, cross-checked against the ledger's version-attributed return.

### Massive historical access — BUILD (real-time MCP unsuitable)
- **Sources**: `src/mcp/massive/server.py` (real-time only: lookback-from-now intraday bars + websocket; no deep history/trades/quotes/grouped/reference); `src/mcp/broker/gate_client.py:99-350` (REST transport template); `src/mcp/fred/server.py` (`get_series`); deep-research verdict (Massive endpoints).
- **Findings**: a NEW direct-REST historical client is required — `/v2/aggs/.../range/...` (`adjusted=false`), `/v3/trades`, `/v3/quotes`, `/v2/aggs/grouped/...`, `/v3/reference/{splits,dividends,tickers,market-holidays}`. Auth = `MASSIVE_API_KEY` (shared with the MCP server) as an `apiKey` param (no HMAC). Mirror `gate_client.py`'s structured-result/no-raise/rate-limit-from-headers pattern. FRED rf-yield via the landed `fred` access.
- **Implications**: build `data_client.py` in `src/reactive/replay/`; the daemon-speaks-REST-directly rationale (§14.10) applies — a compute leaf speaks REST directly, not via the Claude→tool MCP seam.

### Backtest precedent + placement (net-new; `src/reactive/replay/`)
- **Sources**: `src/mcp/broker/paper.py` (fill sim), `scripts/backtest_reversion.py` (overlay-specific CLI), `src/overlays/*/phase1_harness.py` (verification, not backtest); `src/reactive/telemetry/` (sibling layout); `tests/unit/mcp/test_broker_*.py` + `tests/conftest.py:32-54` (`integration_live`).
- **Findings**: no generalized backtest engine exists — net-new. Module lives at `src/reactive/replay/` (compute leaf), tests at `tests/unit/reactive/replay/` + a `tests/integration/` `integration_live` Massive smoke test. `calibration.scorer.Label` is the realized-label vocabulary (the harness populates `realized_label`; the consumer calls `score()`).

## Architecture Pattern Evaluation
| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Pure compute-leaf pipeline in `src/reactive/replay/` (CHOSEN) | data_client → features → simulator → {outcomes, fidelity}; drives landed cores | P14 inner-ring testable; matches telemetry sibling; no orchestration | survival cores DESIGNED (stub until landed) | Adopted |
| Extend the `massive` MCP server with historical tools | one Massive surface | fewer modules | MCP is the Claude→tool seam, not a compute-leaf seam (§14.10); real-time server is websocket-oriented | Rejected |
| Generic multi-source backtest framework | abstract data sources + engines | future-proof | speculative; only Massive+FRED needed now (simplification) | Rejected |

## Design Decisions

### Decision: Two-layer simulation — daily decisions, intraday account path
- **Context**: the reactive decision needs 252+ daily closes (overlay cores); execution is intraday-flat (§16.1).
- **Selected Approach**: per trading day in the window — compute daily features (point-in-time daily bars) → drive `decide` (candidate `ParamSnapshot`); if actionable, simulate the intraday entry/fills (paper sim + intraday bars/quotes) under survival `admit`/`assess` (candidate `SurvivalParameters`), force-flatten before close, compute total-return P&L (credit dividends).
- **Rationale**: matches the landed feature cores' daily input contract + §16.1 intraday-flat; isolates param-independent daily features (cacheable) from the per-candidate decision.
- **Trade-offs**: two data granularities to fetch + reconcile; intraday fetch only on actionable days bounds cost.

### Decision: Reuse landed cores; BUILD only client + simulator + fidelity + outcomes
- **Alternatives**: reimplement decision/fill logic (rejected — P11/R3.3 forbid; duplicates landed code).
- **Selected**: drive `decide`, `compute_features`, overlay cores, `atr`, `paper.simulate` (+ `map_decision_to_action`), `query_trace`, `fred.get_series` — all landed. Build `data_client.py`, `simulator.py`, `fidelity.py`, `outcomes.py`, `types.py`.

### Decision: Fidelity baseline = champion's recorded fills (R7)
- **Context**: R7 reproduces "the champion's realized ledger P&L."
- **Selected**: compare simulated-champion fills/P&L to the champion's **recorded fills** (`decision_process_trace` `kind=fill`) as the fine check; cross-check the aggregate against `counterfactual_ledger` version-attributed return. Cold-start sparse-baseline → **not-evaluable** (R7.3), distinct from failure.

## Risks & Mitigations
- **Survival cores DESIGNED-not-landed** — stub `admit`/`assess` in inner-ring tests; revalidate on their landed signatures (R10.3).
- **Replay-fidelity drift** (sim ≠ recorded champion) — the R7 precondition gates it; if it can't reproduce the known path, the consumer withholds promotion.
- **Daily-vs-intraday reconciliation + §16.1 path** — the hardest correctness surface; covered by determinism tests + the champion-reproduction anchor.
- **Massive cost** (trial-set × partitions × replay, no aggregate cap) — bounded by caching param-independent daily features + fetching intraday only on actionable days; the consumer sizes the trial set.
- **Live-probe items** (SPY/S&P500 symbols, rate limits, reference-endpoint entitlement, delisted depth) — confirm via a one-shot live Massive probe before implementation.

## References
- `docs/exploration-systematic-flow-architecture-2026-05-28.md` §12, §14.6, §16.1.
- Deep-research verdict (Task wfho5d8um) — Massive API data feasibility.
- `src/reactive/{signal_model,features,params}.py`, `src/mcp/broker/{paper,gate_client}.py`, `src/reactive/telemetry/reader.py`, `db/migrations/048_*.sql` — landed seams.
