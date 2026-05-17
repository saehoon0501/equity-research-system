# `mcp__fred` server

FRED (Federal Reserve Bank of St. Louis economic data) MCP server for the equity research system. Per BUILD_LOG.md decision 6, this is a *tool consumed by Claude Code* (specifically the MacroCycleAgent), not an orchestrator. Two tools, matching `.claude/references/mcp-required.md` §"`mcp__fred`":

| Tool | Purpose | Notes |
|---|---|---|
| `get_series(series_id, start, end)` | Fetch a FRED time series with optional date bounds | e.g., `DGS10` (10Y Treasury), `UNRATE` (unemployment), `CPIAUCSL` (CPI), `GDP`, `T10Y2Y` (10Y-2Y spread). Missing observations (FRED ships `"."`) are mapped to `None`. |
| `get_series_info(series_id)` | Series metadata only (title, frequency, units) | Cheap; confirm the series exists before doing a heavier observations fetch. |

## Bring up

```sh
# From repo root, install deps into the project's venv.
uv sync --project src/mcp/fred

# Smoke test: requires FRED_API_KEY in .env. Fetches DGS10 (10Y Treasury) for the last ~30 days.
uv run --project src/mcp/fred python -c "
from datetime import date, timedelta
from server import get_series
start = (date.today() - timedelta(days=30)).isoformat()
result = get_series('DGS10', start=start)
print(result['series_id'], '|', result['title'])
print('frequency:', result['frequency'], '| units:', result['units'])
print('rowcount:', result['rowcount'])
for o in result['observations'][-5:]:
    print(o['date'], o['value'])
"
```

The MCP server itself is launched by Claude Code (not by you) via `.mcp.json` at repo root. Restart Claude Code after editing `.mcp.json` for the changes to take effect.

## How connection info is loaded

`server.py` walks up to repo root and loads `.env` via `python-dotenv` — the same single source of truth as `mcp__edgar`, `mcp__postgres`, and `mcp__contamination_check`.

### Required env

| Var | Required | Purpose |
|---|---|---|
| `FRED_API_KEY` | yes | Sent on every FRED HTTP request as the `api_key` query param. Register a free key at [fredaccountmanager.research.stlouisfed.org/apikey](https://fredaccountmanager.research.stlouisfed.org/apikey). This server fails loud (raises `RuntimeError`) on the first tool call if unset, rather than letting FRED return an opaque 400. |

## Why our own server (decision 6)

Several `fredapi`-style Python wrappers exist, but the FRED HTTP API is small (two endpoints used here: `/fred/series/observations` and `/fred/series`) and stable. A thin httpx wrapper (~150 lines) is transparent and auditable: every byte going to FRED is visible in this file. MacroCycleAgent composes the headline series it needs from a handful of `get_series` calls; we don't need a library that supports the full 800k+ series catalog.

This server lives in the same Python shape as `src/mcp/edgar/`, `src/mcp/postgres/`, and `src/mcp/contamination_check/` (FastMCP, `.env` config) and shares the canonical decision-6 pattern: code is a tool consumed by Claude Code, not the orchestrator.

## What this is not

- **Not a heavy time-series library.** No FRED-MD or FRED-QD bulk datasets. No vintages (`/fred/series/observations` with `realtime_start`/`realtime_end` is not exposed at v0.1 — current observations only).
- **Not a nowcasting service.** No GDPNow, no Atlanta Fed indicators that require additional munging. MacroCycleAgent stitches headline series together itself.
- **Not a category browser.** No `/fred/category` or `/fred/series/search` exposure. The operator/agent is expected to know the series ID up front (FRED's website is the catalog of record).
- **Not authenticated** beyond the `FRED_API_KEY` query parameter.
- **Not a connection pool.** New `httpx.Client` per tool call. v0.1 single-operator usage.
- **Not retry-aware.** HTTP errors propagate; mcp surfaces them. FRED 429 (rate limit) means the operator should slow down.
