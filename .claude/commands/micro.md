---
description: Intraday (≤1-day) day-trading helper. Builds on the latest /research-company decision as a directional prior, applies a technical-indicator panel to real-time Massive websocket price + intraday bars, and emits a PROBABILISTIC LONG/SHORT/HOLD call with a price range (entry/target/stop) per direction. Advisory only — its own lane, not a portfolio decision.
argument-hint: <ticker>
---

# /micro

**Goal:** give the operator a fast, real-time, intraday read on `<ticker>` for day-trading — *long / short / hold* with probabilities and price ranges — anchored on (but not bound by) the slow layer's multi-month view.

**Horizon:** ≤ 1 trading day. This is the shortest-horizon command in the system. `/research-company` reasons in weeks/months; `/micro` reasons in minutes/hours off the live tape.

**Architecture:** main-session, lightweight (like `/entry-check` — no `run_id`/envelope/evaluator machinery). Pulls a slow-layer prior from Postgres → fetches intraday bars + a live micro-aggregate from the `massive` MCP → runs the deterministic signal model in `src/micro` → renders an operator card. Cost is dominated by two MCP calls + one local Python run.

## Decision-vocabulary carveout (READ THIS — CLAUDE.md P9)

P9 locks **BUY / HOLD / TRIM / SELL** as the *only* decision vocabulary across the slow layer, pm-supervisor, operator-facing output, and `execution_recommendations` writes. `/micro` is a **deliberate, scoped exception**:

- The slow layer is **long-only portfolio actions**. Intraday day-trading needs a **SHORT** bias the 4-bin vocabulary cannot express, so `/micro` speaks **LONG / SHORT / HOLD** instead.
- These are **different decision surfaces** and must never mix. `/micro` *reads* the 4-bin `summary_code` as a prior; it **never emits** BUY/HOLD/TRIM/SELL and **never writes** `execution_recommendations`, `summary_code`, or `counterfactual_ledger`.
- `/micro` persists to its **own lane**: a `micro_signal` artifact on disk (§7). Nothing downstream of the P9-governed pipeline consumes it.
- It is **advisory**. It does not place orders and does not override `/research-company`, `/entry-check`, or `/exit-check`.

Do not "fix" this into BUY/HOLD/TRIM/SELL — that would erase the long/short distinction that is the whole point of the command.

## Argument

`<ticker>` — required. US-listed symbol. Need not be on any watchlist; if the slow layer has never researched it, `/micro` runs **prior-free** (neutral bias) and says so.

## Procedure

### 1. Pre-flight checks

- `mcp__massive` connected (real-time feed). If absent: halt and report — `/micro` has no signal without price.
- `mcp__postgres` connected (for the slow-layer prior). If absent or the query fails: **continue in prior-free mode**, don't halt.
- `MASSIVE_API_KEY` present in `.env`. If missing, the `massive` tools return `status="config_error"` — see §6 degradation.

### 2. Load the slow-layer prior (directional bias) — PM Recommendation → PM report fallback

`/research-company` persists to the **database**, not flat files, so resolve the prior in priority order (most authoritative first). Pass whatever you find to `src/micro/prior.py:resolve()`, which applies the fallback chain deterministically and returns `{"summary_code", "source"}` — never eyeball BUY/HOLD/TRIM/SELL out of prose yourself.

**Tier 1 — PM Recommendation (structured, canonical).** The pm-supervisor's decision:

```sql
-- 1a. canonical recommendation
SELECT recommendation, conviction, date
FROM execution_recommendations
WHERE ticker = '<TICKER>'
ORDER BY created_at DESC
LIMIT 1;

-- 1b. logged twin (use if 1a is empty)
SELECT summary_code, conviction, research_date
FROM counterfactual_ledger
WHERE ticker = '<TICKER>' AND summary_code IS NOT NULL
ORDER BY created_at DESC
LIMIT 1;
```

**Tier 2 — PM report (fallback).** Only if Tier 1 is empty. The narrative pm-supervisor synthesis / CDD memo:
- DB: `analyst_briefs` for the ticker (latest `content` by `created_at`; pm/cdd-type brief preferred), or
- Disk: the pm-supervisor envelope at `memos/envelopes/pm-supervisor__<run_id>.json` if present.

Pass that text as `report_text` to `resolve()`; it parses a labelled "Recommendation: X" line or a JSON `recommendation`/`summary_code` key.

**Resolve:**

```bash
python -m src.micro.prior_cli \
  --recommendation "<1a or empty>" --summary-code "<1b or empty>" --report-file "<tier-2 text path or omit>"
# -> {"summary_code": "HOLD", "source": "pm_recommendation"}
```

(or import `src.micro.prior.resolve(...)` directly). Result:
- `summary_code` non-null → `prior = {"summary_code": <code>, "source": <source>, "conviction": <if known>}`.
- `summary_code` null, or any query error / `mcp__postgres` absent → `prior = null` (**prior-free**). Note it in the output; do not halt.

The prior is a **bias term**, not a veto: the signal model weights it at ~10% and lets intraday technicals dominate (a day-trader can fade a multi-month BUY). `summary_code = HOLD` contributes a **0.0** tilt — it neither helps nor fights the intraday read.

### 3. Fetch the intraday bar series

The indicators need a series, not just a snapshot:

```
mcp__massive.get_intraday_bars(ticker="<TICKER>", multiplier=1, timespan="minute", lookback_minutes=390)
```

- `status="ok"` → keep `bars`.
- `status` in {`config_error`,`http_error`} → record it; you can still try the live tape, but with too few bars the model returns `insufficient_data` (a clean HOLD).

Also fetch **daily** bars for the robust volatility anchor (the price-range band is scaled off daily ATR, not 1-minute ATR — see §5):

```
mcp__massive.get_intraday_bars(ticker="<TICKER>", multiplier=1, timespan="day", lookback_minutes=43200)   # ~30 sessions
```

Compute ATR14 on those daily bars and pass it to the signal model as `daily_atr`. If daily bars are unavailable, omit it — the model falls back to intraday-ATR √time scaling.

### 4. Get the live micro-aggregate (Massive websocket)

```
mcp__massive.stream_micro_aggregate(ticker="<TICKER>", collect_seconds=10, channels="T,Q,A")
```

This opens a short-lived websocket, drains ~10 s of trades/quotes/aggregates, and returns `last_trade_price`, `vwap_window`, `tick_velocity_per_s`, `bid`/`ask`/`mid`/`spread_bps`, etc. Interpret `status`:

- `ok` → live confirmation available. Check `authorized_channels`/`rejected_channels`: a **delayed/aggregates-only plan** authorizes `A` but rejects `T`/`Q`, so `bid`/`ask`/`spread_bps` come back null (the liquidity check just won't fire) — that's expected, not an error. Note "delayed aggregates only" in the card when `Q` is rejected.
- `no_ticks` → market likely closed / illiquid (but the channel was authorized); the model falls back to the last bar close. Say "no live ticks (market closed?)".
- `not_entitled` → the plan rejected **every** channel (e.g. real-time channels on a delayed key). Surface the provider message and the fix (point `MASSIVE_WS_URL` at the delayed cluster). Proceed bars-only.
- `auth_failed` / `connection_error` / `config_error` → note it; proceed bars-only.

### 5. Compute the probabilistic signal (deterministic, local)

Write the gathered inputs to a scratch JSON file, then run the signal model (P1: math lives in Python, not this markdown):

```bash
# payload.json = {"ticker": "<TICKER>", "bars": <bars>, "live": <micro-aggregate>,
#                 "prior": <prior-or-null>, "daily_atr": <ATR14 of daily bars>,
#                 "horizon_minutes": <60..390>}   # 1h floor → 1 trading-day cap; default 120 (2h)
python -m src.micro.cli signal --input payload.json
```

It prints a JSON object: `primary` (LONG/SHORT/HOLD), `probabilities` {long,short,hold} (sum→1), `confidence`, the `indicators` panel (RSI/MACD/EMA stack/session VWAP/ATR/Bollinger %B/opening range), `prior_used`, `live_tape`, and `directions` with ATR-anchored `entry_zone`/`target_zone`/`stop` for LONG and SHORT.

Model stance (don't silently retune): five near-equal-weighted components — trend, momentum, VWAP-distance, (regime-gated) mean-reversion, and **Flow Pressure** — are fused into a directional score; the prior adds a small tilt; conflict and wide spreads push probability toward **HOLD** (not toward a long/short coin-flip).

**Flow Pressure** is the synthesized order-flow indicator: an equal blend of **BVC signed-volume imbalance** (Bulk Volume Classification — bar volume split buy/sell by the normal CDF of the standardized bar return; Easley/López de Prado/O'Hara) and **Chaikin Money Flow**. It adds the *volume* dimension that price-only trend/momentum miss, and is horizon-appropriate (true order-flow imbalance / OFI predicts only at a seconds horizon and needs L2 depth we don't have). Weights are kept near-equal by design — optimized signal weights overfit out-of-sample (DeMiguel 2009; Sullivan-Timmermann-White 1999).

### 6. Degradation (no live signal)

If both bars and live tape are unavailable (e.g., `config_error` because `MASSIVE_API_KEY` is unset), render a **"no live signal"** card stating exactly which inputs failed and how to fix (set `MASSIVE_API_KEY`; run the smoke test). Never fabricate a directional call without price data.

### 7. Persist the `micro_signal` artifact (own lane)

Write the full signal JSON (plus the raw `live` and `prior`) to:

```
memos/micro/<TICKER>__<UTC-timestamp>.json
```

This is `/micro`'s private lane. **Do not** write `execution_recommendations`, `summary_code`, or `counterfactual_ledger` (P9, §carveout).

### 8. Output to operator

```
/MICRO — <TICKER>   <UTC timestamp>   (horizon: intraday ≤1d)

REFERENCE PRICE: $X.XX   (live: ok / no_ticks — market closed?)
SLOW-LAYER PRIOR: <BUY/HOLD/TRIM/SELL @ research date> (source: PM Recommendation | PM report)  |  prior-free
LIVE TAPE: tick velocity X.X/s · spread X.X bps · liquidity ok/THIN

CALL (probabilistic · horizon <1h–1 trading day> · levels scaled to expected move over that window):
  LONG   P=0.XX   entry $A–$B   target $C–$D   stop $E
  SHORT  P=0.XX   entry $A–$B   target $C–$D   stop $E
  HOLD   P=0.XX   stand aside
PRIMARY: LONG | SHORT | HOLD   (confidence 0.XX)

INDICATORS: RSI14 X · MACD-hist ±X · EMA9/20/50 stack <up/down/mixed>
            VWAP $X (price ±X%) · ATR14 X · Bollinger %B X · OR <hi/lo>
            FLOW PRESSURE ±X.XX (BVC imbalance ±X.XX · CMF ±X.XX)  ← order-flow

WHY: <2–3 lines — which components drove the call, how the prior tilted it,
      any conflict/liquidity caveat>

⚠ Advisory only — intraday LONG/SHORT/HOLD, NOT a portfolio BUY/HOLD/TRIM/SELL
  (P9 lane). No order is placed. Not investment advice.
```

## When to use

- Operator is considering an intraday entry/exit on a name and wants a real-time, technically-grounded read with explicit probabilities and price levels.
- Confirming or fading a slow-layer thesis on the day's tape.

## When NOT to use

- For the multi-month thesis or position decision → `/research-company`.
- For timing an entry into an **approved** long-term position → `/entry-check` (daily-bar 4-factor model, operates only within the slow-layer-approved universe).
- For exit logic on a **held** position → `/exit-check` (tax-aware).
- As an order trigger — `/micro` never executes; the human does, manually.

## Cost estimate

Low — two `massive` MCP calls (one ~10 s websocket drain + one REST pull) plus a sub-second local Python run. No subagent dispatch, no LLM-heavy stages. ≈ $0.20–$0.60 per invocation in main context.

## Massive feed configuration & live-verification note

- Env: `MASSIVE_API_KEY` (required), `MASSIVE_WS_URL` (default `wss://socket.massive.com`; set `wss://delayed.massive.com` for the delayed feed), `MASSIVE_REST_URL` (default `https://api.massive.com`). See `.env.example`.
- The `massive` server implements the documented (Polygon-compatible) protocol but is **unverified against a live key** in this repo. Before relying on `/micro`, run once:
  ```sh
  uv run --project src/mcp/massive python src/mcp/massive/smoke_test.py SPY
  ```
  to confirm the WS host/feed entitlement.

## Architecture references

- `src/mcp/massive/` — the real-time MCP server (`README.md` documents the two tools + protocol).
- `src/micro/` — `indicators.py` (pure TA incl. the synthesized **Flow Pressure** = `flow_pressure` / `bvc_imbalance` / `chaikin_money_flow`), `signal_model.py` (probabilistic LONG/SHORT/HOLD + price ranges), `cli.py` (entry point). Tests: `tests/unit/micro/`.
- `.claude/commands/entry-check.md` / `exit-check.md` — the daily-bar execution-layer siblings `/micro` complements at the intraday scale.
- CLAUDE.md **P1** (math in Python, not markdown), **P9** (decision vocabulary — see carveout above), **P14** (inner-ring tests before outer).
