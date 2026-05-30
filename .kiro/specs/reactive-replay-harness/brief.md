# Brief: reactive-replay-harness

> Created 2026-05-30 by extracting the replay engine out of `walkforward-tuning-loop` (operator decision at /kiro-validate-design). Data feasibility CONFIRMED the same day by a `/deep-research` pass against the Massive API — see `docs/research-walkforward-tuning-loop-2026-05-29.md` siblings + the verdict captured in `walkforward-tuning-loop` notes. Boundary altitude only; requirements/design nail internals.

## Problem

`walkforward-tuning-loop` (operator decision 2026-05-30) validates candidate trading configs by **in-process CPCV replay** — re-simulating each candidate over purged cross-validation partitions of realized history. That re-simulation is a **point-in-time counterfactual backtest engine**: a changed parameter makes a candidate take *different decisions* than the live system did, so the engine must reconstruct each candidate's **own divergent decision-and-account path**, fetching point-in-time market data for instants/names the live system never traded. It is the single largest, highest-risk net-new component of the reactive layer, and every autonomous promotion's score rests on its fidelity. It was specified inside `walkforward-tuning-loop` and **split out** (boundary isolation + independent versioning/testing + reuse).

## Current State

- The replay engine was specified inside `.kiro/specs/walkforward-tuning-loop/design.md` (the `replay` "Subsystem" leaf); it is now extracted here.
- **Data feasibility CONFIRMED (deep-research, 2026-05-30):** the Massive API (the live Polygon.io rebrand, wire-compatible) serves every required historical type on the **Advanced/Business tier** — 1-second intraday bars (`/v2/aggs/ticker/{t}/range/{mult}/{span}/{from}/{to}`), tick trades (`/v3/trades/{t}`), NBBO quotes (`/v3/quotes/{t}`), grouped daily (`/v2/aggs/grouped/locale/us/market/stocks/{date}`), split-unadjusted bars (`adjusted=false`), delisted-name inclusion — back to 2003-09-10.
- The cores it drives exist as specs: `reactive-signal-model` (decision core, DESIGNED), `survival-gate` (`admit`/`assess`, DESIGNED), `broker-cfd-adapter` `src/mcp/broker/paper.py` paper-fill sim (LANDED). Realized history + the champion's actual path come from `decision-trace-telemetry` (mig 048 landed) + `counterfactual_ledger`.

## Desired Outcome

Given a candidate config (a `ParamSnapshot` and/or `SurvivalParameters` delta, and/or a code version) + a historical window, the harness deterministically reconstructs the candidate's counterfactual decision-and-account path — driving the **landed** reactive + survival cores + the paper-fill sim over **point-in-time** historical inputs (no look-ahead; re-fetching where the candidate's decisions diverge from the champion's) — and returns a structured per-period **outcome record** (decisions, fills at counterparty prices, P&L, survival events, predicted probabilities, realized labels). It satisfies a **fidelity precondition**: replaying the champion's own version reproduces its realized ledger P&L within tolerance.

## Approach

A **point-in-time counterfactual backtest engine** as an importable leaf (pure relative to its fetched inputs), driving the landed cores — never reimplementing them (the same pattern `reactive-signal-model` uses to import `src/overlays/*` cores). Historical data via a **direct Massive REST client** (NOT the real-time `massive` MCP server — MCP is the Claude→tool seam; a leaf backtest engine speaks REST directly, mirroring broker's `gate_client.py`): split-unadjusted bars + trades/quotes for fills + grouped-daily for universe, **crediting cash dividends separately** for total-return P&L (the `adjusted` flag is splits-only). Chosen because the operator selected in-process CPCV replay (amends §14.6) and the data is confirmed retrievable on Advanced/Business.

## Scope
- **In**: the counterfactual simulation (drive reactive + survival cores + paper-fill sim over a window for one config, reconstructing the divergent decision-and-account path, honoring §16.1 intraday-flat); the point-in-time Massive historical-data access (bars/trades/quotes/grouped-daily/dividends; split-unadjusted; delisted; no look-ahead; pagination); dividend crediting for total-return P&L; the structured per-period outcome record; the champion-reproduction fidelity check.
- **Out**: the CPCV partition scheme; the survival-net metric + calibration scoring; the DSR/PBO gate; the fit/trial-set; publish/audit (all `walkforward-tuning-loop`); live/real-time trading + the real-time `massive` MCP path (daemon / `/micro`); the reactive/survival decision *logic* (imported, not owned); the trace/ledger schemas (read-only).

## Boundary Candidates
- The counterfactual simulation engine (drive cores + paper sim + account-path reconstruction)
- The point-in-time Massive historical-data client (direct REST: bars/trades/quotes/grouped/dividends)
- The structured per-period outcome record (the contract `walkforward-tuning-loop` scores)
- The champion-reproduction fidelity check

## Out of Boundary
- CPCV partitioning, scoring (survival-net + calibration), the gate, fit, publish, audit — `walkforward-tuning-loop`.
- Real-time/live market access + the `massive` MCP server (real-time `/micro` + daemon).
- The reactive/survival decision logic (imported pure cores) and their param shapes (consumed by value).
- The trace/ledger schemas (`decision-trace-telemetry`, read-only).

## Upstream / Downstream
- **Upstream**: `reactive-signal-model` (decision core), `survival-gate` (`admit`/`assess` cores), `broker-cfd-adapter` (`paper.py` fill sim), `decision-trace-telemetry` (realized history + champion path + in-sample data), Massive REST (historical bars/trades/quotes/grouped/dividends), FRED (risk-free yield).
- **Downstream**: `walkforward-tuning-loop` (primary consumer — calls it per CPCV partition per config); potentially `in-session-monitor` + the eval-loop (reuse the backtest primitive).

## Existing Spec Touchpoints
- **Extends**: nothing schema-wise; reads `counterfactual_ledger` + `decision_process_trace` (read-only). Introduces a **new direct Massive-historical REST client** (mirrors broker `gate_client.py`).
- **Adjacent**: `walkforward-tuning-loop` (the seam: the harness returns raw outcome records; the tuner partitions / scores / gates them); `reactive-signal-model` + `survival-gate` (imported cores — signature changes are revalidation triggers); the `massive` MCP server (same provider, different seam — real-time vs historical-REST).

## Constraints
- **Data tier**: requires Massive **Advanced or Business** for deep intraday + trades/quotes to 2003 (procurement constraint; deep-research 2026-05-30).
- **Dividend caveat (modeling)**: Massive bars are split-unadjustable (`adjusted=false`) but **never dividend-adjusted** → the harness must credit cash dividends separately for total-return P&L.
- **No look-ahead**: point-in-time fetch only; the 50,000-row trades/quotes cap forces pagination on dense windows.
- **Fidelity precondition**: champion-version replay must reproduce realized ledger P&L within tolerance (else the consumer must not promote).
- **P1 / P14**: leaf module (pure relative to inputs), inner-ring testable in isolation (stub cores + fixture data); no orchestration, no subagent dispatch.
- **DESIGNED-not-landed deps**: reactive + survival cores are not landed; inner-ring tests use stubs; revalidate on their signatures.
- **Live-probe items (carry to requirements)**: SPY / S&P 500 symbol coverage, exact per-tier rate limits, reference-endpoint (splits/dividends/tickers/market-holidays) entitlement, and delisted OHLC depth — confirm with a one-shot live Massive probe before implementation (the four items the deep-research flagged as unverified-not-absent).
