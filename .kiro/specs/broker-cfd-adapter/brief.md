# Brief: broker-cfd-adapter

## Problem

The reactive CFD layer (exploration §14) needs a vetted way to place and manage orders against the Gate TradFi CFD venue. Without an execution adapter, the entire fast clock has no hands — there is nothing to route a thresholded Edge signal into an actual position.

## Current State

`src/mcp/broker/` is scaffolded (`server.py`, `pyproject.toml`, `README.md`) but **not registered in `.mcp.json`** (10 servers wired today; broker absent). No order/position/account tools are implemented yet. Gate TradFi facts were verified against live `api.gateio.ws/api/v4` on 2026-05-29 (exploration §11): signed REST APIv4, no MT5 bridge, 441 US stock CFDs, settlement USDx.

## Desired Outcome

A leaf-level MCP tool (and importable leaf functions the daemon can call directly, not via MCP) exposing `place_order` / `get_positions` / `get_account_assets` against Gate TradFi, with built-in cap/hours/symbol enforcement, runnable in paper/dry-run mode.

## Approach

Signed REST (APIv4 key + secret + SIGN), no MT5 bridge (REST proxies exist despite MT5 backing). Tools enforce: per-symbol leverage caps from the live `leverages` array (reject over-cap; reject the 6 sub-4x names); market hours via `status` + `next_open_time`; ticker-only symbol map (`symbol_desc` is unreliable — e.g. `AAPL`→"American Airlines"; filter `is_base: true`). Order types market / trigger / TP-SL; units lots or USDx-value. PnL uses counterparty prices, not mid. Per §11.2 / §11.4.

## Scope

- **In**: `place_order`, `get_positions`, `get_account_assets`; symbol map + validation by ticker; leverage-cap + hours enforcement; BUY/HOLD/TRIM/SELL → side/size mapping (P9, TRIM/SELL reduce/close via positions); paper/dry-run mode.
- **Out**: survival/liquidation gate (own spec); position sizing (daemon); order-trigger decisions (daemon); live real-money send (gated by §11.5 until survival-gate + kill switch are proven green).

## Boundary Candidates

- REST transport + auth (SIGN signing)
- Tool surface (the three tools + importable leaf funcs)
- Symbol / leverage / hours enforcement layer

## Out of Boundary

- Survival / liquidation math (survival-gate)
- The order-trigger decision (execution-daemon)
- Telemetry emission (decision-trace-telemetry)

## Upstream / Downstream

- **Upstream**: Gate API; `.mcp.json` registration (to wire the server, tool-level grants per T2).
- **Downstream**: survival-gate (account readout), execution-daemon (order placement + leaf-func imports), decision-trace-telemetry (expected-vs-actual fill data).

## Existing Spec Touchpoints

- **Extends**: none (new).
- **Adjacent**: the `src/mcp/*` server pattern; the `massive` / `polygon` family (same provider note in CLAUDE.md is about *data*, distinct from this *execution* venue).

## Constraints

Paper-only v0.1 (§11.5): `place_order` must be stubbed/gated behind survival-gate + kill switch before any live send. P1 (leaf MCP tool, not an orchestrator). P7 (the adapter is the most conservative node — may reject, never upsize). T2 (tool-level MCP grants, e.g. `mcp__broker__place_order`, when wired). Per-symbol leverage: min-4x sits at the product ceiling; only 65 names have 5x headroom; 6 names are sub-4x (untradeable at the 4x floor).
