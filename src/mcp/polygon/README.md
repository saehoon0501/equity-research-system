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
- `get_put_call_ratio(ticker, lookback_days=30)` — aggregated put vs call
  volume + P/C ratio from today's chain snapshot. `lookback_days` is retained
  for API forward-compat; multi-day historical aggregation requires per-contract
  aggs (rate-limit bound) and lands in a follow-up release.
- `get_unusual_activity(ticker, lookback_days=5)` — contracts where
  `volume / open_interest > 1.0`. Top-20 of those are enriched with a 90-day
  rolling-avg comparison (`vol_vs_avg_x` flagged when > 3x).

## Architecture note (task 29 refactor)

All four endpoints ride a single `list_snapshot_options_chain` call per
invocation — the snapshot endpoint returns full contract metadata + greeks +
IV + volume + OI inline, so the per-contract `get_snapshot_option` and
`get_aggs` loops have been retired. Runtime on a liquid ticker (SPY ≈ 3k
contracts) is now seconds, not minutes.

## Environment

Requires `POLYGON_API_KEY` in `.env` (repo root). Register at
<https://polygon.io/dashboard/api-keys>.

**Tier requirement**: `list_snapshot_options_chain` requires the paid
**Options Starter** plan ($29/mo) or higher. The free plan returns
`NOT_AUTHORIZED` on the chain endpoint; this MCP detects that and surfaces
a distinguishable `polygon_tier_insufficient` payload (see below) so the
agent layer can route to a fallback (e.g., yfinance sentiment) without
mistaking the upgrade-required signal for a ticker-not-found.

## Failure-mode contract

| Condition | Payload |
|---|---|
| Underlying unknown / not optionable | `{"ticker_not_found": True}` |
| Auth / quota / connectivity error | `{"ticker_not_found": True, "error_class": "<exception_class_name>"}` |
| Polygon plan lacks chain endpoint | `{"ticker_not_found": True, "error_class": "polygon_tier_insufficient", "upgrade_url": "https://polygon.io/pricing", "note": "..."}` |
| Any other snapshot-chain transport failure | `{"ticker_not_found": True, "error_class": "snapshot_chain_error", "detail": "..."}` |

CatalystScout consumes `error_class` to decide whether to (a) skip the
positioning panel entirely or (b) fall back to yfinance-derived sentiment.

## Run

Used by Claude Code via `.mcp.json`. Manual invocation:

```
uv run --project src/mcp/polygon python src/mcp/polygon/server.py
```

## Test

```
uv run --project src/mcp/polygon pytest tests/test_polygon.py -v
```

On a free-tier `POLYGON_API_KEY`, expect 6 passed + 4 skipped (the 4 live
happy-path tests skip cleanly with the upgrade message; the
`test_tier_insufficient_payload_shape_when_chain_unauthorized` test
verifies the upgrade-payload contract). On a paid-tier key, all 10 tests
should pass.
