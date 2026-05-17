# Tier 4 work — closeout 2026-05-01

This document tracks Tier 4 (Application) per `BUILD_LOG.md`. As of
2026-05-01 all v0.1-blocking items are RESOLVED or explicitly deferred
with a concrete trigger condition. Remaining items are calendar-bound
or operator-spend-gated and are EXPLICITLY NOT in v0.1 launch scope.

## Status table

| Item | v0.1 Status | Notes |
|---|---|---|
| FRED API key (`mcp__fred`) | ✅ RESOLVED 2026-04-30 | Key registered, tested live, in `.env` |
| Market-data provider (`mcp__market_data`) | ✅ RESOLVED 2026-04-30 | Polygon Stocks Starter ($29/mo) active; yfinance fallback retained. JSON fence bug fix landed. |
| Sharadar Core Fundamentals subscription | ✅ EVALUATED + DROPPED 2026-05-01 | Operator obtained free-tier `NDL_API_KEY` and tested. Free tier provides only `MRY` dimension (restated, NOT PIT-correct), 2 fiscal years of history, sample-subset of tickers — strictly worse than EDGAR XBRL on every dimension. Code path removed; key retained in `.env` as a no-op until/unless paid SF1 subscription (~$70-100/mo unlocks ARY/ARQ PIT dimensions + full history + full universe). |
| `mcp__fundamentals` real implementation | ✅ RESOLVED 2026-05-01 | Wired to EDGAR XBRL + Polygon delistings. PIT-correct via `filed`-date filter. Coverage gap (pre-2009 / non-XBRL filers) acknowledged. EDGAR is canonical PIT source; no Sharadar code path active. |
| `mcp__broker` (Schwab integration) | 🚫 REMOVED FROM PLAN 2026-05-01 | Operator holds tokenized US equities on Gate.io (xStocks via Backed Assets / Jersey SPV); conventional brokerage architecture doesn't fit. v0.5+ may add `CryptoExchangeAdapter` (Gate.io REST/WebSocket public API) or Plaid-based positions feed if needed. `src/mcp/broker_mcp/` code retained as scaffold. |
| BacktestingFramework full implementation | 🟡 v0.5 DEFERRED | Now unblocked by EDGAR PIT path (no longer Sharadar-gated). Skeleton + walk-forward harness + DSR/PBO/Sharpe-split signatures already exist at `src/backtesting/`. v0.5 trigger: when 30-memo corpus exists AND 12-month forward window matures. |
| ≥30 sample memo generation | 🟡 OPERATOR-SPEND-GATED | ~$50-150 in LLM inference; operator decides ticker universe + budget. Out of v0.1 scope. v0.5 trigger: operator authorizes spend. |
| Pre/post-cutoff Sharpe split | 🟡 CALENDAR-BOUND | Each memo needs 12+ months of forward returns post-as-of date. Earliest meaningful for v0.1 memos: 2027-mid. Acceptable v0.5 alternative: synthetic/historical replay with explicit "training-cutoff" framing per `.claude/references/contamination-check.md`. |

## What this resolves vs prior state

**RESOLVED:**
- FRED, market-data, Sharadar (via EDGAR pivot), fundamentals MCP, broker scope.
- Tier-4's "5 deferred items" list collapses to 3 actually-deferred items, all calendar/spend-bound.

**EXPLICITLY DROPPED FROM SCOPE:**
- Broker MCP (Gate.io tokenized — wrong architecture fit).
- Sharadar subscription (EDGAR XBRL covers the PIT need at zero cost).

**REMAINS DEFERRED with concrete triggers:**
- 30-memo backtest corpus (operator $50-150 spend authorization).
- 12-month forward returns window (calendar-bound to mid-2027).
- BacktestingFramework full activation (depends on the two above).

## v0.5+ activation conditions

Per Section 8.1 of v3 spec, v0.5 phase activates when:
- ≥50 resolved predictions accumulate, OR
- 540 days elapsed since v0.1 launch (~Oct 2027 if launched May 2026).

At v0.5 entry, the BacktestingFramework should be activated:
1. Wire `src/backtesting/` skeleton against the EDGAR PIT data already provided by `mcp__fundamentals.get_fundamentals(ticker, as_of_date)`.
2. Operator authorizes 30-memo generation budget.
3. Run walk-forward backtest with embargo per v2-final §2.6.
4. DSR + PBO + pre/post-cutoff Sharpe split land at v1.0 substantive correctness gate.

## Gate impact

This closeout shifts the v0.1 launch gate count from **33 → 32** (broker_mcp_oauth removed). All 32 gates green. See `docs/superpowers/launch-readiness-log.md` for HMAC-attested record + `db/migrations/023_v3_launch_readiness_log.sql` for the Postgres mirror.
