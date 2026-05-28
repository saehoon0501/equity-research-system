# MCP Servers Required by the Skills Layer

Skills and subagents in this repo assume specific MCP servers are connected to expose external systems and persistence. Operator wires these up; skills detect and gracefully report missing MCPs rather than silently failing.

## Hard requirements (system non-functional without these)

### 1. `mcp__postgres` (or equivalent SQL access)

**Purpose:** Persistence for Evidence Index, Predictions DB, Counterfactual Ledger.

**Expected tools:**
- `query`: read-only SELECT queries
- `execute`: INSERT (writes only — append-only constraint enforced at DB level)
- `schema_info`: introspect tables

**Why hard requirement:** Mechanical contamination check (the load-bearing defense under Path A) needs to validate every claim against Evidence Index rows. Without DB access, no commands can release output past the Evaluator hard gate.

**Connection:**
- Local Postgres + TimescaleDB extension on `localhost:5432`
- Database name: `equity_research`
- App user with INSERT-only on append-only tables, SELECT on all

### 2. `mcp__edgar` (or HTTP fallback to data.sec.gov)

**Purpose:** SEC filings — 10-K, 10-Q, 8-K, Form 4, 13F.

**Expected tools:**
- `get_filings(cik_or_ticker, form_type, since_date)`
- `get_filing_text(filing_id)`
- `get_company_facts(cik)`

**Why hard requirement:** CompanyDeepDive cannot produce a memo without filings. Evidence Index entries cite filing dates; mechanical check resolves against them.

**Connection:**
- Either: official `mcp__edgar` if available
- Or: HTTP client to `data.sec.gov/api/xbrl/companyfacts/CIK{n}.json` and `submissions/CIK{n}.json` with User-Agent header per SEC fair-access policy
- `edgartools` Python library is the canonical reference; an MCP wrapper around it is fine

## Soft requirements (skills work in degraded mode without these)

### 3. `mcp__fundamentals` (Sharadar)

**Purpose:** Point-in-time fundamentals via Sharadar Core Fundamentals on Nasdaq Data Link.

**Expected tools:**
- `get_fundamentals(ticker, as_of_date)` — point-in-time snapshot
- `get_delistings(ticker)` — for survivorship-bias-free backtests

**Why soft:** v0.1 sample memo generation can defer Sharadar to week 10 (BacktestingFramework) per BUILD_LOG.md Day 1 deferral. CompanyDeepDive uses EDGAR XBRL for fundamentals when Sharadar isn't connected, with an explicit "non-PIT data — backtest validity caveat" warning surfaced in the memo.

### 4. `mcp__market_data` (Polygon → Finnhub → yfinance fallback chain)

**Purpose:** Prices, news, market data.

**Expected tools:**
- `get_prices(ticker, start, end, interval)`
- `get_news(ticker, since)`
- `get_real_time_quote(ticker)` (v0.5+)

**Why soft:** v0.1 backtests can use any historical price source; live position monitoring (v0.5+) needs reliable real-time data.

**Provider selection:** deferred per BUILD_LOG.md Day 1. Commit before sample memo generation step (per the BUILD_LOG.md step list).

### 4a. `mcp__massive` (Massive.com real-time stocks — `/micro` only)

**Purpose:** Real-time US-equities tape for the `/micro` intraday (≤1-day) day-trading helper. Distinct from `mcp__market_data` (that is the slow layer's daily OHLCV/news; this is the execution layer's live feed).

**Expected tools:**
- `stream_micro_aggregate(ticker, collect_seconds, channels)` — websocket-per-call micro-aggregate (last/vwap/tick-velocity/spread/hi-lo)
- `get_intraday_bars(ticker, multiplier, timespan, lookback_minutes)` — REST intraday bar series for the indicator panel

**Why soft:** only `/micro` uses it; every other command runs without it. Massive's wire protocol is Polygon-compatible. Both tools degrade gracefully (structured `status` instead of raising) so `/micro` renders a "no live signal" card when the key/feed is absent.

**Connection:** `MASSIVE_API_KEY` + `MASSIVE_WS_URL` (default `wss://socket.massive.com`, real-time; `wss://delayed.massive.com` for delayed) + `MASSIVE_REST_URL` in `.env`. Verify with `src/mcp/massive/smoke_test.py`.

### 5. `mcp__fred` (Federal Reserve Economic Data)

**Purpose:** Macro indicators for MacroCycleAgent.

**Expected tools:**
- `get_series(series_id, start, end)` — e.g., yield curve, CPI, unemployment

**Why soft:** MacroCycleAgent is quarterly/monthly; not used in v0.1 critical path. Wire up before week 11 or when first used.

### 6. `mcp__brokerage` (v0.5+ only)

**Purpose:** Position reconciliation and trade execution permission gate.

**Expected tools:**
- `get_positions()` — for daily reconciliation
- `get_orders()` — for in-flight order tracking
- `get_balances()`
- `place_order(...)` — **hardware gated by Claude Code permission system**; never auto-approved

**Why soft (for v0.1):** No real money in v0.1. Wire up before v0.5 entry per phasing-plan.md §3.2 entry criteria.

**Permission policy when connected:** the `place_order` tool is configured to require explicit human approval per v2-final §4.5. Any agent calling it must hit the permission gate. Daily summary of pending recommendations is delivered through `/daily-monitor` summary, not auto-trigger.

## Documentation-only (used by skills but not via MCP)

These come from local files / repo, not MCP:

- **Industry addenda** — `.claude/references/industry-addenda/*.md` (banks, REITs, biotech, insurance, energy, software, hardware)
- **Process rubric** — `.claude/references/process-rubric.md`
- **Evidence Index schema** — `.claude/references/evidence-index-schema.md`
- **Wash-sale paths** — `.claude/references/wash-sale-paths.md`
- **Position sizing formula** — `.claude/references/position-sizing-formula.md`

## How skills handle missing MCPs

Each command/subagent that depends on an MCP runs an availability check at start:

```
1. Check expected MCP tool exists
2. If not: report what's missing, suggest the MCP to wire, halt the operation
3. If yes: proceed with full procedure
```

Skills must NOT silently degrade. A `/research-company AAPL` with no EDGAR connection should refuse to produce a memo, not produce one without filings. Silent degradation is exactly the failure mode the v2-final spec's mechanical contamination check exists to prevent (memos written without proper sourcing).

## Status board

Operator updates as MCPs come online:

- [ ] `mcp__postgres` connected and Evidence Index schema migrated
- [ ] `mcp__edgar` connected (or HTTP fallback configured)
- [ ] `mcp__fundamentals` (Sharadar) connected — deferred per BUILD_LOG.md Day 1; target week 10
- [ ] `mcp__market_data` connected — provider committed by week 4
- [ ] `mcp__fred` connected — target before week 11
- [ ] `mcp__brokerage` connected — target before v0.5 entry

When a `[ ]` becomes `[x]`, BUILD_LOG.md weekly entry should note the connection and the verification that the MCP works end-to-end (not just that it loaded).
