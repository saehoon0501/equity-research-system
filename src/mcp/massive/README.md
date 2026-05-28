# `massive` MCP — real-time stocks feed for `/micro`

Real-time US-equities market data from [Massive.com](https://massive.com),
exposed as a decision-6 typed capability for the **`/micro`** intraday
day-trading helper (≤1-day horizon). Deliberately separate from the slow-layer
`market_data` server (daily OHLCV / news, feeds `/research-company`).

## Tools

| Tool | What it returns | Notes |
|---|---|---|
| `stream_micro_aggregate(ticker, collect_seconds=10, channels="T,Q,A")` | One micro-aggregate over a bounded live window: `last_trade_price`, `vwap_window`, `tick_velocity_per_s`, `window_high/low/volume`, `bid`/`ask`/`mid`/`spread_bps`, trade/quote counts | Opens a **short-lived websocket per call**, auths, subscribes, drains for `collect_seconds` (clamped 1–60), closes. MCP is request/response — this is how "websocket real-time" fits a tool call. |
| `get_intraday_bars(ticker, multiplier=1, timespan="minute", lookback_minutes=390)` | Ordered intraday OHLCV+vwap bar series | REST `/v2/aggs`. The websocket gives *now*; the indicators in `src/micro` need a *series*. |

Both **degrade gracefully** — missing key / auth reject / closed market return a
payload with an explanatory `status` (`config_error`, `auth_failed`,
`connection_error`, `no_ticks`, `http_error`) instead of raising, so `/micro`
renders a "no live signal" card rather than crashing.

## Configuration

In the repo-root `.env`:

```
MASSIVE_API_KEY=...                       # required for live data
MASSIVE_WS_URL=wss://socket.massive.com   # default; wss://delayed.massive.com for the delayed feed
MASSIVE_REST_URL=https://api.massive.com  # default
```

## Why this is a Polygon twin

Massive's wire protocol is Polygon-compatible (verified against the
[Massive WebSocket docs](https://massive.com/docs/websocket/stocks/overview)):

- **Auth:** `{"action":"auth","params":"<MASSIVE_API_KEY>"}`
- **Subscribe:** `{"action":"subscribe","params":"T.AAPL,Q.AAPL,A.AAPL"}`
- **Channels:** `T` trades, `Q` quotes, `A` per-second aggregates, `AM` per-minute
- **Data frames** carry the same field names as Polygon (`ev`, `sym`, `p`, `s`,
  `bp`, `ap`, `o/h/l/c/v/vw`, `t`).

The REST `/v2/aggs` mapping here is intentionally the twin of
`market_data/polygon_provider.py:get_prices`.

## Smoke test (needs a real key)

The unit tests in `tests/unit/micro/` cover the deterministic signal math; this
covers the network seam, which can't run without a key:

```sh
uv run --project src/mcp/massive python src/mcp/massive/smoke_test.py SPY
```

During market hours: `status=ok` with a populated `last_trade_price`. Off-hours:
`no_ticks` from the websocket, but bars from the last session via REST.

## Status

`stream_micro_aggregate` is implemented against the documented Massive protocol
but has **not** been verified against a live key in this environment — the
operator must run the smoke test once to confirm the WS host/feed entitlement
(`wss://socket.massive.com` real-time vs `wss://delayed.massive.com` delayed).
