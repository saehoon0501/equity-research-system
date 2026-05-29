# Requirements Document

> **Revised 2026-05-29 against the verified Gate TradFi API** (`gate-tradfi-api-reference.md`). The earlier BLOCKED state is cleared — the API is now specified. Criteria below are reconciled to the real endpoint/field schemas. **Long + short are both in scope** (operator-confirmed 2026-05-29; the reactive layer supplies the directional side per §12.3). **Per-symbol leverage configuration is RESOLVED** (research 2026-05-29: it is a fixed per-instrument product attribute — US-stock CFDs 5x, no setter endpoint — so exposure is controlled via order volume per Req 5). True residuals (gap/oracle behavior, insolvency, rate limits, `close_type` semantics) are tracked in `gate-api-gaps.md` — none blocks these requirements; the venue's absence of a native idempotency key is mitigated adapter-side (Req 7.4).

## Introduction

The reactive CFD execution layer (exploration `docs/exploration-systematic-flow-architecture-2026-05-28.md` §11–§14) needs a vetted way to place and manage orders against the **Gate TradFi CFD venue** (forex + CFD on MT5). Without an execution adapter the fast clock has no hands — there is nothing to route a thresholded Edge signal into an actual position.

This feature delivers a **leaf-level broker adapter** exposing operations to place/modify/cancel orders, close/reduce positions, and read positions + account assets — both as MCP tools (the Claude→tool seam) and as directly-importable functions the execution daemon can call outside the MCP transport. The adapter is the **most conservative node** in the chain (P7): it may reject or refuse, never upsize or silently modify. It enforces per-symbol tradability, order-volume bounds, and market-hours, and it defaults to **paper/dry-run**: no live real-money order may be transmitted until a survival-gate clearance and a clear kill switch are in place (§11.5).

The venue API is now fully specified (operator-supplied 2026-05-29; see `gate-tradfi-api-reference.md`). Load-bearing realities the requirements must honor: orders are **asynchronous** (placement returns a queue reference, not a fill); position management (TRIM/SELL) is **by stable position identifier** via a dedicated close operation with optional partial volume; **leverage is not a per-order parameter** (it is account/per-symbol data, controlled via order volume); the account must be **activated** before trading; per-symbol **trade mode** can restrict actions; there is **no native paper mode** (it must be simulated in-adapter); the venue **returns** unrealized PnL (the adapter reports it, does not compute it); and the **stop-out level** and swap rates are venue data read live, not hardcoded.

**Current state (verified 2026-05-29):** the broker server is **not implemented** — no operations exist, no source is tracked under `src/mcp/`, and `broker` is absent from `.mcp.json` (10 servers wired). The on-disk `src/mcp/broker_mcp/` is stale cruft (operator-confirmed). The canonical host directory name is a design-phase decision.

## Boundary Context

- **In scope**: order create / modify / cancel; position close (full + partial) and TP/SL modify; position and account-asset readout; ticker-only symbol mapping + category/trade-mode validation; per-symbol order-volume-bound and tradability enforcement; market-hours enforcement; account-activation precheck; BUY/HOLD/TRIM/SELL → venue-action mapping (P9); paper/dry-run mode (in-adapter simulation) with live-send gating, kill-switch refusal, and structured error reporting; exposed as MCP tools and importable functions.
- **Out of scope**: survival/liquidation-distance computation and sleeve-cap enforcement (owned by `survival-gate`); position sizing and the order-trigger decision (owned by `execution-daemon`); telemetry/decision-trace emission (owned by `decision-trace-telemetry`); live real-money transmission (gated until `survival-gate` + kill switch are proven green per §11.5).
- **Adjacent expectations**: relies on the Gate TradFi venue being reachable and the account being **activated**; relies on `.mcp.json` registration with tool-level grants (T2); expects `survival-gate` to gate live sends (the adapter refuses to transmit live without that clearance and never performs survival math); expects `execution-daemon` to consume the importable functions and own sizing/trigger decisions; surfaces fill prices + swap rates so `decision-trace-telemetry` and `survival-gate` can consume them downstream.
- **Operator decisions:** (a) **Long + short both in scope** (operator-confirmed 2026-05-29) — the reactive layer supplies the directional side (§12.3), so the adapter supports both long and short entries, gated per-symbol by `trade_mode`; (b) **Leverage configuration — RESOLVED** (research 2026-05-29): leverage is a **fixed per-instrument product attribute** (US-stock CFDs **5x**; not user-changeable; **no setter endpoint** for TradFi). Exposure is controlled via order **volume** (confirms Req 5). Residual: how `mt5-account.leverage` relates to `symbols/detail.leverage` + writability — verify against live responses.

## Requirements

### Requirement 1: Order placement and decision-vocabulary mapping

**Objective:** As the execution daemon, I want a single set of operations that maps the canonical BUY/HOLD/TRIM/SELL decision — together with a caller-supplied long/short direction (the reactive layer supplies the side, §12.3) — to the correct venue action, so that an Edge signal becomes a position without the caller re-implementing venue semantics.

#### Acceptance Criteria
1. When the order operation is invoked with a BUY decision (open or add exposure) in the caller-supplied direction for a tradable symbol that passes all validation, the Broker Adapter shall open or increase a position in that direction (long via a buy-to-open order, short via a sell-to-open order) for the requested volume.
2. When the order operation is invoked with a TRIM decision against a caller-identified open position, the Broker Adapter shall reduce that position via the position-close operation with a partial close volume, rather than opening a new opposing position.
3. When the order operation is invoked with a SELL decision against a caller-identified open position, the Broker Adapter shall fully close that position via the position-close operation, rather than opening a new opposing position.
4. When the order operation is invoked with a HOLD decision, the Broker Adapter shall take no order action and return a structured no-op result.
5. The Broker Adapter shall accept only market and trigger order types (with optional take-profit / stop-loss prices); if any other order type is requested, it shall reject the request without transmitting it.
6. The Broker Adapter shall express order size as contract volume and shall reject any order whose volume is below the symbol's minimum or above the symbol's maximum order volume (read live; observed maximum ≈ 100 lots), regardless of available margin.
7. When an order is submitted, the Broker Adapter shall treat acceptance as asynchronous — the venue acknowledges with a queue reference rather than a completed fill — and shall confirm the resulting order and position by reading active orders/positions rather than assuming a synchronous fill.
8. If a TRIM or SELL decision references a symbol that has no corresponding open position, then the Broker Adapter shall reject the request and shall not open a new position in any direction.
9. Where multiple open positions exist for the same symbol, the Broker Adapter shall act only on the caller-supplied position identifier and shall not itself select which position a TRIM or SELL applies to.
10. While the TradFi account is not in an active state, the Broker Adapter shall reject all order and close operations and surface the activation requirement.
11. If a symbol's trade mode disallows the requested action (disabled, long-only, short-only, or close-only), then the Broker Adapter shall reject that action.

### Requirement 2: Open-position readout

**Objective:** As the execution daemon and survival-gate, I want to read all open positions with venue-authoritative valuations, so that downstream sizing, exit, and survival logic operate on the true book.

#### Acceptance Criteria
1. When the positions readout is invoked, the Broker Adapter shall return every open position with at least its position identifier, symbol, direction, volume, average open price, used margin, and unrealized profit/loss.
2. The Broker Adapter shall report the **venue-supplied** unrealized profit/loss for each open position and shall not substitute a self-computed mid or mark valuation.
3. If no positions are open, then the Broker Adapter shall return an empty position set rather than an error.

### Requirement 3: Account-assets readout for downstream survival logic

**Objective:** As the survival-gate, I want account equity, margin state, the stop-out level, and financing rates exposed, so that I can compute account-level (cross-margin) liquidation distance and carry.

#### Acceptance Criteria
1. When the account-assets readout is invoked, the Broker Adapter shall return account equity, used margin, available (free) margin, margin level, and balance in the settlement currency.
2. The Broker Adapter shall expose the account-level stop-out / liquidation margin ratio and the fields needed for a downstream consumer to compute account-level (cross-margin) liquidation distance, and shall not itself compute or assert a liquidation distance.
3. The Broker Adapter shall surface per-symbol financing/swap rates and the realized swap on closed positions, rather than assuming a constant rate.

### Requirement 4: Ticker-based symbol mapping and validation

**Objective:** As the operator, I want instruments identified and validated by US ticker only, so that an unreliable venue description field can never cause an order on the wrong company.

#### Acceptance Criteria
1. The Broker Adapter shall map and validate instruments by US-ticker identity only and shall not use the venue's free-text symbol description for identity resolution.
2. The Broker Adapter shall restrict the tradable set to the in-scope instrument category (US-stock CFDs) and shall reject symbols outside that category.
3. If an order or close operation references a symbol that is not present in the validated tradable-symbol set, then the Broker Adapter shall reject the request without transmitting it.

### Requirement 5: Tradability and exposure control

**Objective:** As the operator, I want the adapter to never trade an untradeable name and to control exposure honestly given the venue's fixed per-symbol leverage, so that no order can exceed venue limits.

#### Acceptance Criteria
1. The Broker Adapter shall read per-symbol leverage and trade mode from the venue and shall reject orders for symbols that are disabled or untradeable at the product leverage floor (the sub-floor names).
2. The Broker Adapter shall control position exposure through order volume (bounded by the venue minimum/maximum order volume) and shall not attempt to set a per-order leverage, because the venue order request carries no leverage parameter.
3. The Broker Adapter shall compute used-margin/exposure for validation as volume-derived notional divided by the per-symbol leverage, consistent with the venue margin model.

### Requirement 6: Market-hours enforcement

**Objective:** As the operator, I want orders blocked when the venue session is closed, so that the adapter does not transmit into a closed or gapping market.

#### Acceptance Criteria
1. While a symbol's venue session is closed, when an order or modify operation is invoked, the Broker Adapter shall reject it without transmitting it and shall report the symbol's next open time. (v0.1 holds no order-queuing state; a closed session is always a rejection.)

### Requirement 7: Conservative posture — reject, never upsize

**Objective:** As the operator, I want the adapter to be the most conservative node, so that no downstream error can be amplified at the venue seam (P7).

#### Acceptance Criteria
1. The Broker Adapter shall never autonomously increase the requested order volume beyond what the caller requested.
2. If a request violates any validation rule (symbol, category, trade mode, volume bound, market hours, activation, or live-send gating), then the Broker Adapter shall reject the request rather than silently modifying, clamping, or partially fulfilling it.
3. The Broker Adapter shall not perform position sizing, conviction scoring, or order-trigger decisions; it shall act only on the volume and side supplied by the caller.
4. Because order submission is asynchronous and the venue provides no idempotency key, before re-submitting an order whose prior submission is unconfirmed, the Broker Adapter shall first poll active orders and positions to confirm the prior submission did not already produce an order or position, and shall not transmit a duplicate that would create an unintended additional position.

### Requirement 8: Paper/dry-run mode, live-send gating, and kill switch

**Objective:** As the operator, I want live real-money transmission disabled by default and gated behind explicit clearances, so that the highest-blast-radius node cannot send a live order prematurely (§11.5).

#### Acceptance Criteria
1. In v0.1, the Broker Adapter shall operate in paper/dry-run mode only and shall expose no enabled path for live real-money transmission.
2. Because the venue provides no native dry-run mode, while in paper/dry-run mode the Broker Adapter shall perform full validation and return a structured simulated confirmation (priced from venue ticker bid/ask) without invoking the venue order-create operation.
3. The Broker Adapter shall not transmit a live real-money order unless all of the following hold simultaneously: paper/dry-run mode is explicitly disabled, the account is active, a survival-gate clearance signal is present, and the kill switch is clear.
4. While the kill switch is engaged, the Broker Adapter shall reject all live order transmissions.
5. If a live real-money transmission is requested while any required clearance (disabled paper mode, active account, present survival-gate clearance, clear kill switch) is absent, then the Broker Adapter shall refuse to transmit the order.

### Requirement 9: Error handling and fill observability

**Objective:** As the operator and downstream telemetry consumer, I want failures reported as structured results and actual fills surfaced, so that the daemon never crashes on a venue error and slippage can be recorded downstream.

#### Acceptance Criteria
1. If venue authentication fails, then the Broker Adapter shall return a structured error identifying the failure class and shall not transmit any order.
2. If the venue returns an error or is unreachable, then the Broker Adapter shall return a structured error result rather than raising an unhandled exception; and if an asynchronous submission's outcome is unconfirmed, it shall surface the order as unconfirmed rather than assuming it filled.
3. When an order fills, the Broker Adapter shall surface the actual fill price and fill volume (from the venue's order/position records, via the history readout in Req 10) so that a downstream consumer can compute expected-vs-actual slippage.
4. The Broker Adapter shall emit no decision-trace telemetry itself; surfacing fill and rate data in the operation result is the boundary of its responsibility (the persisted history readout is defined in Req 10).
5. The Broker Adapter shall respect the venue's rate-limit signals — backing off when the venue signals a rate-limit condition rather than retrying immediately — and shall discover the effective limit at runtime rather than assuming a fixed rate. (Design note: the venue signals rate-limit state via response headers + an HTTP 429 status, with no published `/tradfi` limit — see `gate-tradfi-api-reference.md`.)

### Requirement 10: Order- and position-history readout (fills, realized carry, liquidation events)

**Objective:** As the execution daemon, survival-gate, and downstream telemetry consumer, I want to read closed order and position history with venue-authoritative fill, carry, and close-reason data, so that expected-vs-actual slippage (Req 9.3), realized swap (Req 3.3), and forced-liquidation events are observable from a named capability rather than left implied.

#### Acceptance Criteria
1. When the history readout is invoked, the Broker Adapter shall return closed orders and positions including, at minimum, the fill price, fill volume, realized profit/loss, realized swap/financing, and the close reason for each record.
2. The Broker Adapter shall surface, in the close reason, whether a position was closed normally or by forced liquidation (the venue's forced-liquidation position state and force-close order-operation types), without itself interpreting, scoring, or acting on that distinction.
3. The Broker Adapter shall report venue-supplied history values and shall not substitute self-computed fill, profit/loss, or swap figures.
4. If no history exists in the requested window, then the Broker Adapter shall return an empty history set rather than an error.
