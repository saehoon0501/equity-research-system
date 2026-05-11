# polygon MCP (options positioning)

Wraps Polygon.io options-chain endpoints for CatalystScout / positioning-analytics
use. Surfaces four Cremers-Weinbaum / Pan-Poteshman-style signals.

## Endpoints (v1)

- `get_options_chain(ticker, expiry=None)` — full chain for nearest 4 expirations
  (or a specific expiry). Returns per-contract greeks + open interest + volume +
  implied volatility.
- `get_iv_term_structure(ticker)` — ATM implied-vol curve across forward
  expirations, plus front-back spread (front-month ATM IV minus 90-day ATM IV).
  Cremers-Weinbaum implied-vol-spread style signal.
- `get_put_call_ratio(ticker, lookback_days=30)` — aggregated daily put vs call
  volume + P/C ratio over the lookback window. Pan-Poteshman style.
- `get_unusual_activity(ticker, lookback_days=5)` — contracts where
  `volume / open_interest > 1.0` OR `daily_volume > 90-day-avg * 3`.

## Environment

Requires `POLYGON_API_KEY` in `.env` (repo root). Register at
<https://polygon.io/dashboard/api-keys>. Options-chain endpoints need the
Stocks/Options Starter tier (free tier returns 15-min-delayed data).

## Failure-mode contract

All four endpoints return `{"ticker_not_found": True}` if the underlying is
unknown or not optionable. On auth / quota / connectivity errors they return
`{"ticker_not_found": True, "error_class": "<exception_class_name>"}`.

## Run

Used by Claude Code via `.mcp.json`. Manual invocation:

```
uv run --project src/mcp/polygon python src/mcp/polygon/server.py
```
