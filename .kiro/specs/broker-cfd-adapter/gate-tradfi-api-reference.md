# Gate TradFi CFD API — Reference (operator-supplied 2026-05-29)

**Source:** official Gate TradFi API spec (forex + CFD on MT5), operator-supplied 2026-05-29. This is the **primary source** for `broker-cfd-adapter` design. Base URL: `https://api.gateio.ws/api/v4/`. Auth: APIv4 key+secret (standard Gate v4 signing). **Prerequisite: the TradFi service must be activated** (`POST /tradfi/users`, or in-app); account `status` 1=not opened, 2=pending review, 3=active.

All numeric monetary/price/volume fields are returned as **strings**. All timestamps are Unix (server `timestamp` in ms; data times in seconds unless noted).

## Endpoint surface (our scope)

| Method | Path | Auth | Use in adapter |
|---|---|---|---|
| GET | `/tradfi/users/mt5-account` | 🔒 | account `leverage`, **`stop_out_level`** (liquidation margin ratio), `status` |
| GET | `/tradfi/users/assets` | 🔒 | **`equity`, `margin_level`, `balance`, `margin` (used), `margin_free`, `unrealized_pnl`** — survival-gate input |
| GET | `/tradfi/symbols` | public | universe + `status` (open/closed), `trade_mode`, `next_open_time`, `price_precision`, `settlement_currency` |
| GET | `/tradfi/symbols/categories` | public | `category_id` (stocks = category 2 per §11.3) |
| GET | `/tradfi/symbols/detail?symbols=` (≤10) | 🔒 | **`max_order_volume`, `min_order_volume`, `contract_volume`, `leverage`, `price_precision`, `price_sl_level`, `swap_cost_type`, `buy_swap_cost_rate`, `sell_swap_cost_rate`, `swap_cost_3day`, `trade_timezone`, `trade_mode`** |
| GET | `/tradfi/symbols/{symbol}/tickers` | public | **`bid_price`, `ask_price`, `last_price`** + status — current/counterparty price |
| GET | `/tradfi/symbols/{symbol}/klines` | public | OHLC bars (1m/15m/1h/4h/1d/7d/30d, ≤500) |
| GET | `/tradfi/orders` | 🔒 | active orders: `order_id`, `state`, `finished`, `side`, `volume`, `price`, `price_tp/sl` |
| POST | `/tradfi/orders` | 🔒 | **create order → returns `data.id` = Queue Task ID (async, NOT order/position id)** |
| PUT | `/tradfi/orders/{order_id}` | 🔒 | modify price / TP / SL of a pending order |
| DELETE | `/tradfi/orders/{order_id}` | 🔒 | cancel a pending order |
| GET | `/tradfi/orders/history` | 🔒 | fills: `order_opt_type`, `fill_volume`, `price` (avg fill), `close_pnl`, `time_done` |
| GET | `/tradfi/positions` | 🔒 | **`position_id`, `symbol`, `margin`, `unrealized_pnl`, `unrealized_pnl_rate`, `volume`, `price_open`, `position_dir`** |
| PUT | `/tradfi/positions/{position_id}` | 🔒 | modify position TP / SL |
| POST | `/tradfi/positions/{position_id}/close` | 🔒 | **close/reduce: `close_type` (1/2), `close_volume` (null=full, partial=TRIM)** |
| GET | `/tradfi/positions/history` | 🔒 | closed: `realized_pnl`, `position_status` (1=closed, 2=**forced liquidation**), `close_detail`, `counterparty_price`, `close_price`, `swap`, `fee`, `margin_level`, `stop_out_level` |

## Critical enums

- **`side`: 1 = SELL, 2 = BUY** ⚠️ (counterintuitive — guard against off-by-one).
- **`price_type`**: `market` | `trigger`. (No resting limit book; TP/SL are separate `price_tp`/`price_sl` fields.)
- **`trade_mode`**: 0=disabled, 1=long only, 2=short only, 3=**close only**, 4=full trading. ⚠️ Adapter must respect — a symbol in close-only/long-only/short-only rejects the disallowed action.
- **`order_opt_type`** (history): 1=sell, 2=buy, 3=close long, 4=close short, **5=force close long, 6=force close short** (5/6 = liquidation events → survival telemetry).
- **`position_dir`**: `Long` | `Short`. **`position_status`** (history): 1=fully closed, 2=forced liquidation.
- **`close_type`** (close request): 1 | 2 (exact semantics TBD — confirm on first authenticated close).
- **account `status`**: 1=not opened, 2=pending review, 3=active.
- **`status`** (symbol): `open` (tradable) | `closed`.

## Implementation gotchas (load-bearing)

1. **Orders are asynchronous.** `POST /tradfi/orders` returns a *Queue Task ID*, not an order or position id. The adapter must treat placement as fire-into-queue, then **poll** `/tradfi/orders` (→ `order_id`) and `/tradfi/positions` (→ `position_id`) to confirm. No synchronous fill.
2. **Leverage is NOT a per-order parameter.** It lives on the account (`mt5-account.leverage`) and per-symbol (`symbols/detail.leverage`). The order request has only `price/price_type/side/symbol/volume/price_tp/price_sl`. ⟹ the adapter controls exposure via **`volume`**, not by requesting leverage — this reshapes the old "reject over-leverage" requirement.
3. **TRIM/SELL = close-by-`position_id`.** `POST /tradfi/positions/{position_id}/close` with `close_volume` (partial=TRIM, full/null=SELL). This validates the caller-supplied-position-id model (Req 1.2/1.3/1.9) — the venue *requires* a position_id to close. There is no symbol-level netting close.
4. **Order size = `volume`** in contract units, bounded per-symbol by `min_order_volume` / `max_order_volume` (the operator-stated "max lot 100" is this field — read it live, don't hardcode). `contract_volume` = contract size; `price_precision` = tick.
5. **Swap fees are readable** via `symbols/detail` (`buy_swap_cost_rate`, `sell_swap_cost_rate`, `swap_cost_3day`, `swap_cost_type`) and realized per closed position in `positions/history.swap` — closes the old "swap behind 403" gap.
6. **Stop-out level is account-data**, read from `mt5-account.stop_out_level` (don't hardcode 50%). Liquidation is **account-level** (cross-margin): `margin_level = equity ÷ used_margin × 100%`; forced reduction when `margin_level ≤ stop_out_level`.
7. **No native paper/dry-run mode.** Paper mode must be **simulated in-adapter** (skip POST; price from `tickers` bid/ask) — confirms Req 8.2 is adapter-side.
8. **No client-order-id / idempotency key** in the documented order request. Double-send protection is adapter-side (poll-before-resend / track queue task ids).
9. **`fill_negative` transaction type** ("cover negative balance") is **administrative reconciliation of a negative balance — NOT negative-balance protection** (research 2026-05-29 confirmed Gate CFDs have **no NBP**: "lose more than invested"; plausibly unsecured-creditor / offshore). A negative balance *can occur*; the §16 funding cap is the blast-radius bound.
10. **Counterparty price** is exposed on `positions/history.counterparty_price`; active-position PnL is given directly as `unrealized_pnl` (no mid/mark assumption needed).

## P9 vocabulary → endpoint mapping

| Decision | Action |
|---|---|
| **BUY** | `POST /tradfi/orders`, `volume` = caller size, price_type=market/trigger; **side per caller-supplied direction — long = side 2 (buy-to-open), short = side 1 (sell-to-open)** (⚠️ side enum 1=SELL/2=BUY; gated per-symbol by `trade_mode`) |
| **TRIM** | `POST /tradfi/positions/{position_id}/close`, `close_volume` = partial |
| **SELL** | `POST /tradfi/positions/{position_id}/close`, `close_volume` = null/full |
| **HOLD** | no call |

(**Long + short are both in v0.1 scope** — operator-confirmed 2026-05-29; the reactive layer supplies the directional side per §12.3. A short *entry* is a **BUY decision in the short direction** → side=1 sell-to-open (Req 1.1), not a SELL decision. A SELL **decision** always closes an existing position; a naked SELL with no open position must still be rejected per Req 1.8.)
