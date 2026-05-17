# `mcp__market_data` server

Market data MCP server for the equity research system. Per BUILD_LOG.md decision 6, this is a *tool consumed by Claude Code* (memo generation, daily monitor, entry/exit checks), not an orchestrator. Three tools, exactly matching `.claude/references/mcp-required.md` §"`mcp__market_data`":

| Tool | Purpose | Notes |
|---|---|---|
| `get_prices(ticker, start, end, interval)` | Historical OHLCV bars | Daily/weekly/monthly via `interval` (`1d`, `1wk`, `1mo`); `end` is **inclusive** (we add one day internally because yfinance's `end` is exclusive) |
| `get_news(ticker, since)` | Recent news headlines | Uses yfinance's `.news` endpoint; optional ISO-date `since` filter (inclusive) |
| `get_real_time_quote(ticker)` | Last price + timestamp | V0.5+ scaffold via `fast_info`. Production v0.5+ would use Polygon or Finnhub for true real-time |

## Bring up

```sh
# From repo root, install deps into the project's venv.
uv sync --project src/mcp/market_data

# Smoke test: no API key required for yfinance. Pulls 5 days of AAPL.
uv run --project src/mcp/market_data python -c "
from server import get_prices, get_real_time_quote
prices = get_prices('AAPL', '2024-12-01', '2024-12-05')
print(prices['ticker'], prices['rowcount'], 'rows')
for r in prices['rows']:
    print(r['date'], r['close'])
print('quote:', get_real_time_quote('AAPL'))
"
```

The MCP server itself is launched by Claude Code (not by you) via `.mcp.json` at repo root. Restart Claude Code after editing `.mcp.json` for the changes to take effect.

## How connection info is loaded

`server.py` walks up to repo root and loads `.env` via `python-dotenv` — the same single source of truth as `mcp__postgres`, `mcp__edgar`, and `mcp__contamination_check`. yfinance itself needs no env vars at v0.1; the dotenv load is kept for shape parity so swapping in Polygon/Finnhub in v0.5+ is a one-file change with no bring-up surprises.

### Required env

| Var | Required | Purpose |
|---|---|---|
| (none at v0.1) | — | yfinance is unauthenticated. Polygon/Finnhub keys land in v0.5+. |

## Why yfinance for v0.1

Per `.claude/references/mcp-required.md`, market-data provider selection was flagged "soft" / deferred at Day 1, with the commitment to land *some* provider before sample memo generation. yfinance is the v0.1 commitment because:

- **Free, no API key.** Zero friction for the v0.1 single-operator workflow; no rate-limit budget to babysit during backtests.
- **Sufficient fidelity for v0.1 scope.** Daily OHLCV is what `BacktestingFramework` consumes for walk-forward evaluation; v0.1 does not place live orders, so real-time tick gaps don't bite.
- **Decision 2 deferral honored.** Polygon and Finnhub were explicitly deferred. Promoting one of them to "the real-time provider" is a v0.5+ act tied to live position monitoring; nothing in v0.1 needs that yet.
- **Single-file swap.** When v0.5+ arrives and we promote Polygon/Finnhub, only `server.py` changes — the tool surface (`get_prices`, `get_news`, `get_real_time_quote`) is the contract callers depend on.

## What this is not

- **Not real-time tick data.** `get_real_time_quote` reads yfinance's `fast_info`, which is end-of-day-ish for free users. v0.5+ live monitoring needs Polygon or Finnhub.
- **Not an order book / Level 2 feed.** Quotes only; no bid/ask depth.
- **Not options chains.** v0.1 strategy is long-only equity; options data is out of scope.
- **Not adjusted-only.** `get_prices` returns both `close` (raw) and `adj_close` (split-and-dividend-adjusted) so consumers pick the column that matches their semantic.
- **Not a connection pool / not retry-aware.** New `yf.Ticker(...)` per tool call. Yahoo errors propagate as-is — `mcp` surfaces them. No translation layer.
- **Not authenticated.** No keys at v0.1.
