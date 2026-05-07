# yfinance MCP

Wraps Yahoo Finance via the `yfinance` Python lib for consensus estimates, target prices, recommendations, calendar, holders, and peer comparisons.

## Endpoints (v1)

- `get_consensus_estimates(ticker)` — forward EPS + revenue consensus
- `get_target_prices(ticker)` — sell-side target prices + recommendation summary
- `get_recommendations(ticker, days=90)` — recent upgrades/downgrades
- `get_calendar(ticker)` — next earnings + ex-dividend dates
- `get_holders(ticker)` — institutional + insider ownership
- `get_peer_comps(ticker)` — peer tickers + key multiples

## ToS reality

Yahoo prohibits automated access for commercial use. This MCP is for personal research only. Do not productize.

## Failure modes

Per spec §9.4:
- Endpoint dropped → `{available: False, reason: "endpoint_dropped"}`
- Ticker not found → `{ticker_not_found: True}`
- Rate limited → `{rate_limited: True, retry_after: <seconds>}`

## Run

Used by Claude Code via `.mcp.json`. Manual invocation:

```
uv run --project src/mcp/yfinance python src/mcp/yfinance/server.py
```
