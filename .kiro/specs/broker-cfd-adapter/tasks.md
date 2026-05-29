# Implementation Plan

> Scope: the leaf-level Gate TradFi CFD execution adapter (`src/mcp/broker/`) per `design.md`. Paper-only v0.1 — no live real-money path is enabled. `(P)` marks tasks runnable concurrently with their peers (non-overlapping boundaries). Dependency direction: `types → config → gate_client → {mappers, symbol_cache} → validation → paper → core → server`.

- [ ] 1. Foundation: package, types, configuration, test harness

- [x] 1.1 Scaffold the broker server package and secrets configuration
  - Create the server package skeleton following the house MCP layout (manifest requiring Python ≥3.11 with mcp / httpx / python-dotenv; a consumer README skeleton; non-packaged uv project).
  - Add `GATE_API_KEY` and `GATE_API_SECRET` to the example environment file, noting the Gate CFD execution venue is distinct from the pre-existing schwab block.
  - Confirm the canonical host directory is the new broker server directory; do not resurrect the stale `broker_mcp` stub.
  - Observable: `uv run --directory` against the broker package imports the MCP library successfully, and the example env file documents the GATE_* keys.
  - _Requirements: 8.1_

- [x] 1.2 (P) Define the domain types and decision vocabulary
  - Define the value objects and enums: trade direction, order type, rejection reasons, order intent (including a trigger price), order result, position, account assets, symbol info, and history record.
  - Reuse the canonical BUY/HOLD/TRIM/SELL Label from the calibration module; do not redefine it.
  - Observable: each type instantiates in a unit test, and a test asserts the four-member Label enum is imported from the shared module.
  - _Requirements: 1.4_
  - _Boundary: models_
  - _Depends: 1.1_

- [x] 1.3 (P) Implement configuration and secret resolution
  - Read the Gate credentials fresh per call; return a structured error (never raise) when they are absent.
  - Establish runtime mode: paper/dry-run defaults ON; expose survival-gate clearance and the kill switch as boolean inputs that default to the safe state (not cleared / not engaged); hold the settlement currency and US-stock category id.
  - Observable: with credentials unset a config read returns a structured error; paper mode defaults to enabled; clearance and kill-switch inputs default to the safe state.
  - _Requirements: 8.1, 8.3, 8.4_
  - _Boundary: config_
  - _Depends: 1.1_

- [x] 1.4 (P) Establish test fixtures and a mock venue transport
  - Capture representative Gate `/tradfi` JSON responses (symbol detail, assets, mt5-account, tickers, orders, positions, history) as fixtures.
  - Provide a mock transport that returns canned responses so leaf functions are unit-testable with no live venue.
  - Observable: the fixtures load and the mock transport returns a canned positions/assets payload in a smoke unit test.
  - _Requirements: 9.2_
  - _Boundary: tests fixtures_
  - _Depends: 1.1_

- [ ] 2. Transport and mapping

- [x] 2.1 (P) Implement the signed REST transport to the Gate venue
  - Sign requests (APIv4 HMAC-SHA512) for the `/tradfi` endpoint set and return raw venue JSON only.
  - Parse the rate-limit signals and back off on a rate-limit condition; discover the effective limit at runtime; never raise — return structured transport errors (authentication failure, unreachable, rate-limited).
  - Observable: against the mock, an authentication failure and a rate-limit response each yield a structured error result (not an exception), and a normal call returns parsed JSON.
  - _Requirements: 1.7, 9.1, 9.2, 9.5_
  - _Boundary: gate_client_
  - _Depends: 1.3, 1.4_

- [x] 2.2 (P) Implement venue↔domain mappers and decision-action mapping
  - Map the decision plus direction to the venue action: BUY → buy/sell-to-open with the side-enum guard, TRIM → partial close, SELL → full close; carry no per-order leverage parameter.
  - Compute used-margin/exposure as notional divided by the per-symbol leverage.
  - Map raw venue JSON to typed position/account/symbol/history readouts reporting venue-supplied profit/loss and swap, with the close reason flagging normal versus forced liquidation; never substitute self-computed values.
  - Observable: unit tests show BUY-long → side 2, BUY-short → side 1, TRIM → partial close, SELL → full close, and a forced-liquidation history record surfaces the forced flag.
  - _Requirements: 1.1, 1.2, 1.3, 1.9, 2.2, 3.2, 5.2, 5.3, 10.2, 10.3_
  - _Boundary: mappers_
  - _Depends: 1.2_

- [ ] 3. Symbol cache, validation, and paper simulation

- [x] 3.1 (P) Build the symbol metadata cache and ticker mapping
  - Load and cache per-symbol detail (leverage, trade mode, min/max volume, swap rates, price precision, session status, next open time) via authenticated detail reads in batches of at most ten symbols.
  - Map and validate instruments by US ticker only; never use the free-text description for identity; restrict the tradable set to the US-stock CFD category.
  - Provide a freshness/refresh policy (refresh on a validation miss) so trade mode and session status stay current.
  - Observable: a known ticker resolves to its metadata, an out-of-category or description-only lookup is rejected, and the cache repopulates after a forced miss.
  - _Requirements: 3.3, 4.1, 4.2, 5.1_
  - _Boundary: symbol_cache_
  - _Depends: 2.1, 2.2_

- [x] 3.2 Implement the pre-transmit validation chain
  - Compose an ordered predicate chain that can only reject (never mutate): account active → symbol in the validated set → category → tradable and not a sub-floor-leverage name → trade mode allows the action → order type is market or trigger with a trigger price present when trigger → volume within bounds → session open (report the next open time) → live-send clearances when live; for TRIM/SELL require an existing position.
  - Lock the chain order and short-circuit on the first failure to a structured reason.
  - Observable: rejections fire for each rule (inactive account, unknown or out-of-category symbol, sub-floor leverage, disallowed trade mode, bad order type, missing trigger price, out-of-bounds volume including over the maximum, closed session with the next open time, TRIM/SELL with no position), and no rule path increases the requested volume.
  - _Requirements: 1.5, 1.6, 1.8, 1.10, 1.11, 4.3, 5.1, 6.1, 7.1, 7.2_
  - _Boundary: validation_
  - _Depends: 3.1_

- [ ] 3.3 (P) Implement the paper/dry-run simulator
  - Given a validated intent and the current bid/ask, return a structured simulated confirmation without invoking the venue order-create operation.
  - Reuse the identical validation and mapping path used by live so paper coverage is meaningful (this component does not itself run validation; the operations layer sequences validate-then-simulate).
  - Observable: in paper mode a BUY returns a simulated confirmation priced from the ticker bid/ask with no order POST issued (asserted against the mock).
  - _Requirements: 8.2_
  - _Boundary: paper_
  - _Depends: 2.1, 2.2_

- [ ] 4. Operations layer (leaf functions)

- [ ] 4.1 Implement the readout leaf functions
  - Provide positions, account-assets, tradable-symbols/validate-symbol, and history readouts returning typed results; empty position and history sets return empty rather than an error.
  - Surface account equity and margin state plus the stop-out level for downstream survival logic without computing a liquidation distance; surface fills, realized swap, and forced-liquidation flags via history; emit no telemetry.
  - Observable: positions returns venue profit/loss and an empty set when flat; account assets exposes the stop-out level without a derived liquidation distance; history returns fills/realized swap/forced-liquidation flag and an empty window returns empty.
  - _Requirements: 2.1, 2.3, 3.1, 3.2, 3.3, 9.3, 9.4, 10.1, 10.4_
  - _Boundary: core_
  - _Depends: 2.1, 2.2, 3.1_

- [ ] 4.2 Implement decision routing, the pre-transmit snapshot, and live-send gating
  - Route BUY/HOLD/TRIM/SELL plus direction to the correct operation; HOLD returns a structured no-op; act only on the caller-supplied position id for same-symbol multiples.
  - Gather one consistent pre-transmit snapshot (account assets/status, open positions, target symbol session) into the validation context and run the chain; this single positions read is the one later reused by the double-send guard.
  - Enforce live-send gating (paper disabled AND account active AND survival clearance present AND kill switch clear); refuse otherwise; never size, score, or increase the requested volume.
  - Observable: BUY opens in the requested direction, TRIM partial-closes by position id, SELL full-closes, and HOLD no-ops; a TRIM/SELL with no position is rejected; in v0.1 no live path transmits, and a missing clearance or engaged kill switch refuses.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.8, 1.9, 1.10, 7.1, 7.3, 8.1, 8.3, 8.4, 8.5_
  - _Boundary: core_
  - _Depends: 4.1, 3.2, 3.3_

- [ ] 4.3 Implement the async order lifecycle and double-send guard
  - Treat submission as asynchronous: confirm the result by polling orders and positions, and surface an unconfirmed outcome rather than assuming a fill.
  - Retain the returned queue-task-id and correlate it against active orders/positions before any resend (reusing the positions read from the 4.2 snapshot) so a retry creates no duplicate position.
  - Observable: an async submission is confirmed by polling and an unconfirmed outcome is surfaced (never assumed filled); a simulated resend after an unconfirmed submit creates no second position.
  - _Requirements: 1.7, 7.4, 9.2_
  - _Boundary: core_
  - _Depends: 4.2_

- [ ] 5. MCP server interface and registration

- [ ] 5.1 Expose the MCP tool surface and register the server
  - Wrap each leaf function as an MCP tool that coerces typed results to dictionaries and never raises (structured error dictionaries on failure).
  - Register the broker server in the MCP manifest following the house uv-run pattern.
  - Observable: the server launches under uv, the broker tools are listed, and a tool call returns a structured dictionary (including a structured error dictionary on a forced failure).
  - _Requirements: 9.2_
  - _Boundary: server_
  - _Depends: 4.1, 4.2, 4.3_

- [ ] 6. Test suites and live validation

- [ ] 6.1 (P) Unit-test the order path, validation chain, gating, and paper simulation
  - Cover decision routing and action mapping, the full rejection matrix, live-send gating and the kill switch, the double-send guard, and paper simulation — all against the mock transport.
  - Observable: tests pass for each acceptance criterion in the order/validation/gating/paper set, and the validation chain order is asserted.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.8, 1.9, 1.10, 1.11, 4.2, 4.3, 5.1, 6.1, 7.1, 7.2, 7.3, 7.4, 8.1, 8.2, 8.3, 8.4, 8.5_
  - _Boundary: tests order-path_
  - _Depends: 5.1_

- [ ] 6.2 (P) Unit-test the readouts, transport errors, and history
  - Cover positions/assets/symbols/history mapping including venue-supplied profit/loss and swap, stop-out exposure without a derived liquidation distance, ticker-only identity, empty sets, authentication/unreachable/rate-limit transport errors, the no-telemetry invariant, and the forced-liquidation flag.
  - Observable: tests pass for each acceptance criterion in the readout/transport/history set.
  - _Requirements: 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 4.1, 5.2, 5.3, 9.1, 9.2, 9.3, 9.4, 9.5, 10.1, 10.2, 10.3, 10.4_
  - _Boundary: tests readouts_
  - _Depends: 5.1_

- [ ] 6.3 (P) Contract/golden tests for the MCP tool output shapes
  - Assert each MCP tool returns the documented dictionary shape against recorded fixtures.
  - Observable: golden-shape assertions pass for every broker tool.
  - _Requirements: 9.2_
  - _Boundary: tests contract_
  - _Depends: 5.1_

- [ ] 6.4 Add the opt-in authenticated live round-trip
  - Behind a credential-presence skip guard, read symbol detail plus assets plus mt5-account and exercise a paper order→poll→close cycle against a live account; cross-check the field names and async/position-id lifecycle against the read-only reference MCP.
  - Observable: with credentials set, the live-marker test confirms the field names and the async/position-id lifecycle; with credentials unset it skips cleanly.
  - _Requirements: 1.7, 9.3_
  - _Boundary: tests integration_
  - _Depends: 5.1_

## Implementation Notes

- **Test environment (from 1.1):** the repo's `pytest tests/` does NOT run green under the host's system Python — ~18 PRE-EXISTING collection errors (missing `src` on PYTHONPATH + missing third-party deps like `polygon`/`yfinance`/`mcp`). This is an environment gap, not a regression. Treat regression as a DELTA against that baseline (no NEW failures referencing the changed boundary), not absolute green. Run broker checks inside the broker uv venv: `uv run --directory src/mcp/broker python ...`. Broker unit tests (1.4, 6.x) need an interpreter that has `mcp`/`httpx` — i.e. the broker uv venv — so plan the test invocation to run under `uv run --directory src/mcp/broker` (and make broker modules importable, e.g. via importlib-by-path like `tests/unit/mcp/test_polygon.py`, or by running pytest from within the package).
- **Packaging (from 1.1):** broker `pyproject.toml` mirrors the house `massive` shape (python>=3.11; deps mcp/httpx/python-dotenv; `[tool.uv] package=false`). `uv.lock` is tracked; `.venv` is gitignored.
- **Test importlib aliasing (from 2.2 — LOAD-BEARING):** when a test loads multiple broker modules via importlib-by-path, load `models.py` under its CANONICAL alias `models` FIRST, then load dependent modules — so their `from models import ...` reuses the SAME module instance. Otherwise two copies of the classes/enums exist and `isinstance(...)` / `Direction.LONG is ...` identity checks fail spuriously. (Also: the mapper raises on a HOLD decision by design — core short-circuits HOLD upstream per 1.4, so HOLD never reaches the mapper.)
- **Concurrent worktree work (from 2.1):** `.kiro/specs/execution-daemon/` + `.kiro/steering/roadmap.md` are being edited in parallel (another spec). Commit broker files with EXPLICIT paths only; never `git add -A`. Leave those files untouched.
- **Module naming (from 1.2 — LOAD-BEARING):** the domain-types module is `src/mcp/broker/models.py`, NOT `types.py` — a module named `types.py` shadows the stdlib `types` module and breaks `python server.py` sibling imports (reviewer-confirmed: no env config makes by-name imports work). All broker production modules import domain types via `from models import ...`. `Label` (P9) is imported into `models.py` from `src.calibration.scorer` via a repo-root `sys.path` bootstrap (`Path(__file__).resolve().parents[3]`); `src.calibration` uses lazy imports so no heavy deps are pulled. Canonical broker test command: `PYTHONSAFEPATH=1 uv run --directory src/mcp/broker python -m pytest <ABS test path> -q` (test files load broker modules via importlib-by-path under a unique alias). design.md File Structure Plan + Data Models updated to `models.py`.
