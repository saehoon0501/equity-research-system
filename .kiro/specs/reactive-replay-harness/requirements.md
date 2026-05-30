# Requirements Document

> Generated 2026-05-30 from the discovery brief. Extracted from `walkforward-tuning-loop`; data feasibility confirmed against the Massive API (deep-research, Advanced/Business tier). WHAT-not-HOW: endpoint paths, the historical-data-client internals, the cores' exact signatures, and the fidelity-tolerance value are deferred to design. **Carried open items (verify before implementation, not blockers):** the four Massive live-probe items — SPY/S&P 500 symbol coverage, exact per-tier rate limits, reference-endpoint (splits/dividends/tickers/market-holidays) entitlement, delisted-OHLC depth.

## Introduction

The Replay Harness is a deterministic, point-in-time **counterfactual backtest engine** for the reactive CFD layer's after-market tuning. Its consumer, `walkforward-tuning-loop`, validates candidate trading configs by in-process CPCV replay (operator decision 2026-05-30, amends §14.6): it must re-simulate each candidate over partitions of realized history. Because a changed parameter makes a candidate take *different* decisions than the live system did, the re-simulation cannot replay recorded outcomes — it must reconstruct the candidate's **own** decision-and-account path, fetching point-in-time market data for instants and names the live system never traded. The Replay Harness is that engine: given one candidate config and one historical window, it drives the landed reactive signal-model and survival-gate cores plus the broker paper-fill simulator over point-in-time Massive data and returns a structured per-period outcome record. It is the highest-risk component of the tuning loop — every autonomous promotion's score rests on its fidelity — which is why it is isolated here for independent hardening and reuse.

## Boundary Context

- **In scope**: the single-config, single-window backtest (the atomic unit the tuner calls per CPCV partition); counterfactual decision-and-account-path reconstruction (re-fetching point-in-time inputs where the candidate diverges from the champion); driving the landed reactive + survival cores + paper-fill sim (param and code candidates); point-in-time Massive historical-data access (bars/trades/quotes/grouped-daily/dividends; split-unadjusted; delisted; no look-ahead; pagination); total-return P&L with separate dividend crediting; fill realism at counterparty (bid/ask) prices + intraday stop-hit determination; the structured per-period outcome record; the champion-reproduction fidelity precondition; deterministic, isolatable execution.
- **Out of scope**: the CPCV partition scheme (purge/embargo) and which windows to replay; the survival-net risk-adjusted metric + calibration scoring; the DSR/PSR/PBO promotion gate; the fit / trial-set generation; publish / audit (all `walkforward-tuning-loop`); live or real-time trading and the real-time `massive` MCP path (`execution-daemon` / `/micro`); the reactive and survival decision *logic* (driven, never reimplemented); the decision-trace / `counterfactual_ledger` schemas (read-only consumer).
- **Adjacent expectations**: drives `reactive-signal-model`'s decision core (candidate `ParamSnapshot`) and `survival-gate`'s `admit`/`assess` cores (candidate `SurvivalParameters`); uses `broker-cfd-adapter`'s paper-fill simulator; reads realized history + the champion's actual path from `decision-trace-telemetry` + `counterfactual_ledger`; fetches historical inputs from the Massive API and the risk-free yield from FRED; returns raw outcome records that the tuner scores (this harness computes no metric or gate). Requires a Massive **Advanced/Business** subscription for full-depth history.

## Requirements

### Requirement 1: Single-config, single-window backtest

**Objective:** As the walk-forward tuner, I want to backtest exactly one candidate config over one historical window and get back a per-period outcome record, so that I can call the harness independently for each config and CPCV partition.

#### Acceptance Criteria
1. When given one candidate config and one historical window, the Replay Harness shall produce a per-period outcome record for that config over that window.
2. The Replay Harness shall accept an arbitrary historical window and shall not impose or assume any cross-validation partition scheme (the consumer supplies the window).
3. The Replay Harness shall accept a candidate config expressed as a reactive parameter snapshot and/or survival parameters and/or a code version.

### Requirement 2: Counterfactual path reconstruction (not outcome replay)

**Objective:** As the tuner, I want the harness to simulate the candidate's own decisions rather than re-read the champion's recorded outcomes, so that a parameter change that alters decisions is scored on what the candidate would actually have done.

#### Acceptance Criteria
1. The Replay Harness shall reconstruct the candidate's own decision-and-account sequence over the window, not the champion's recorded outcomes.
2. When the candidate's decisions diverge from the champion's (e.g. the champion held but the candidate would have entered), the Replay Harness shall obtain the point-in-time market inputs needed for the divergent path, including for names the live system never traded.
3. The Replay Harness shall simulate the account path sequentially — positions, margin, survival responses, and fills are order-dependent — honoring the intraday-flat-before-close invariant (§16.1).

### Requirement 3: Drive the landed cores; never reimplement

**Objective:** As the operator enforcing P11, I want the harness to drive the same decision logic the live system uses, so that replay decisions match production semantics and the logic is not duplicated.

#### Acceptance Criteria
1. The Replay Harness shall produce reactive decisions by driving the landed reactive signal-model core with the candidate's parameters, and survival decisions by driving the landed survival-gate `admit`/`assess` cores with the candidate's survival parameters.
2. Where the code track is exercised (it may be deferred for v0.1 per `walkforward-tuning-loop`), the Replay Harness shall run the candidate code end-to-end over the window.
3. The Replay Harness shall not reimplement, approximate, or fork the reactive or survival decision logic.

### Requirement 4: Point-in-time historical data, no look-ahead

**Objective:** As the operator guarding against leakage, I want every input fetched as-of the simulated instant, so that no future information can leak into a replay.

#### Acceptance Criteria
1. The Replay Harness shall fetch the decision/model inputs as-of the simulated instant and shall not feed any data timestamped after that instant into the candidate's decisions (the champion-reproduction baseline read of Requirement 7 may legitimately span the full window).
2. The Replay Harness shall fetch split-unadjusted price data so that splits occurring after the simulated instant do not retroactively alter prices.
3. If a requested window exceeds the data source's available historical depth, then the Replay Harness shall fail explicitly rather than silently truncate or return a partial-window result.
4. The Replay Harness shall retrieve data for delisted names over the period they traded, and shall paginate where a dense window exceeds the source's per-request row limit.

### Requirement 5: Total-return P&L with separate dividend crediting

**Objective:** As the tuner, I want P&L to reflect total return, so that dividend-paying names are not mis-scored given the price data is never dividend-adjusted.

#### Acceptance Criteria
1. The Replay Harness shall compute total-return P&L that credits cash dividends separately from price changes.
2. The Replay Harness shall not assume price bars are dividend-adjusted.

### Requirement 6: Fill realism at counterparty prices

**Objective:** As the tuner, I want fills and stop-hits modeled against actually traded/quoted prices, so that simulated P&L reflects executable reality, not a mid-price idealization (§11.4).

#### Acceptance Criteria
1. The Replay Harness shall simulate order fills at counterparty (bid/ask or traded) prices, not at the mid price.
2. The Replay Harness shall determine whether a protective stop level was reached from the intraday price path.

### Requirement 7: Champion-reproduction fidelity precondition

**Objective:** As the operator, I want proof the engine reproduces known reality before any candidate number is trusted, so that an unfaithful engine cannot drive a promotion.

#### Acceptance Criteria
1. When re-simulating the incumbent champion's own version over a window, the Replay Harness shall reproduce the champion's realized ledger P&L within a configured tolerance.
2. If the champion-reproduction tolerance is not met, then the Replay Harness shall report a fidelity failure for that window so the consumer can withhold promotion.
3. If the champion's realized ledger P&L is absent or insufficient for the window (e.g. paper cold-start with little realized history), then the Replay Harness shall report fidelity as not-evaluable, distinct from a fidelity failure, so the consumer can treat sparse-baseline cold-start differently from an engine defect.

### Requirement 8: Outcome-record contract (raw outcomes, not scores)

**Objective:** As the tuner, I want a structured per-period record rich enough that I can compute the survival-net metric and calibration myself, so that scoring stays in the tuner and the harness stays a pure backtest primitive.

#### Acceptance Criteria
1. The Replay Harness shall return, per period, the candidate's decisions, fills (with prices), total-return P&L, survival events (e.g. stop-outs, flatten, safe-mode), the model's predicted probabilities, and the realized outcome labels.
2. The Replay Harness shall not compute the survival-net risk-adjusted metric, calibration metrics, or any promotion decision; those are the consumer's.

### Requirement 9: Determinism and inner-ring isolation

**Objective:** As the operator maintaining the system, I want the engine reproducible and testable in isolation, so that the highest-risk tuning component can be verified before any promotion relies on it (P14).

#### Acceptance Criteria
1. Given identical candidate config, window, and point-in-time inputs, the Replay Harness shall produce an identical outcome record.
2. The Replay Harness shall be exercisable in isolation — with stubbed cores and fixture data, without a live market feed, an LLM, or a live database.

### Requirement 10: Consumption boundary and revalidation

**Objective:** As the operator maintaining cross-spec seams, I want the harness to consume its dependencies as a reader/driver without owning their concerns, so that boundaries stay clean and breakage is caught.

#### Acceptance Criteria
1. The Replay Harness shall read the decision trace and outcome ledger read-only and shall not write to or alter their schemas.
2. The Replay Harness shall not perform CPCV partitioning, metric scoring, gating, fitting, publishing, or live trading.
3. If a driven core's interface (the reactive decision core or the survival `admit`/`assess` cores) or the historical-data contract changes shape, then the Replay Harness shall be revalidated against the new shape.
