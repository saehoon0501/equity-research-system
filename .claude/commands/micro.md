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

### 2. Load the slow-layer prior (directional bias)

Query the most recent `/research-company` decision for this ticker:

```sql
SELECT summary_code, created_at
FROM counterfactual_ledger
WHERE ticker = '<TICKER>'
  AND summary_code IS NOT NULL
ORDER BY created_at DESC
LIMIT 1;
```

- One row → `prior = {"summary_code": "<BUY|HOLD|TRIM|SELL>"}`. (If the ledger's timestamp column differs in this deployment, order by `decision_date` instead — the only requirement is "latest".)
- Zero rows, or any query error → `prior = null` (**prior-free**). Note it in the output; do not halt.

The prior is a **bias term**, not a veto: the signal model weights it at ~10% and lets intraday technicals dominate (a day-trader can fade a multi-month BUY).

### 3. Fetch the intraday bar series

The indicators need a series, not just a snapshot:

```
mcp__massive.get_intraday_bars(ticker="<TICKER>", multiplier=1, timespan="minute", lookback_minutes=390)
```

- `status="ok"` → keep `bars`.
- `status` in {`config_error`,`http_error`} → record it; you can still try the live tape, but with too few bars the model returns `insufficient_data` (a clean HOLD).

### 4. Get the live micro-aggregate (Massive websocket)

```
mcp__massive.stream_micro_aggregate(ticker="<TICKER>", collect_seconds=10, channels="T,Q,A")
```

This opens a short-lived websocket, drains ~10 s of trades/quotes/aggregates, and returns `last_trade_price`, `vwap_window`, `tick_velocity_per_s`, `bid`/`ask`/`mid`/`spread_bps`, etc. Interpret `status`:

- `ok` → live confirmation available (reference price, liquidity check via `spread_bps`).
- `no_ticks` → market likely closed / illiquid; the model falls back to the last bar close. Say "no live ticks (market closed?)" in the card.
- `auth_failed` / `connection_error` / `config_error` → note it; proceed bars-only.

### 5. Compute the probabilistic signal (deterministic, local)

Write the gathered inputs to a scratch JSON file, then run the signal model (P1: math lives in Python, not this markdown):

```bash
# payload.json = {"ticker": "<TICKER>", "bars": <bars>, "live": <micro-aggregate>, "prior": <prior-or-null>}
python -m src.micro.cli signal --input payload.json
```

It prints a JSON object: `primary` (LONG/SHORT/HOLD), `probabilities` {long,short,hold} (sum→1), `confidence`, the `indicators` panel (RSI/MACD/EMA stack/session VWAP/ATR/Bollinger %B/opening range), `prior_used`, `live_tape`, and `directions` with ATR-anchored `entry_zone`/`target_zone`/`stop` for LONG and SHORT.

Model stance (don't silently retune): trend + momentum + VWAP-distance + (regime-gated) mean-reversion are fused into a directional score; the prior adds a small tilt; conflict and wide spreads push probability toward **HOLD** (not toward a long/short coin-flip).

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
SLOW-LAYER PRIOR: <BUY/HOLD/TRIM/SELL @ research date>  |  prior-free
LIVE TAPE: tick velocity X.X/s · spread X.X bps · liquidity ok/THIN

CALL (probabilistic):
  LONG   P=0.XX   entry $A–$B   target $C–$D   stop $E
  SHORT  P=0.XX   entry $A–$B   target $C–$D   stop $E
  HOLD   P=0.XX   stand aside
PRIMARY: LONG | SHORT | HOLD   (confidence 0.XX)

INDICATORS: RSI14 X · MACD-hist ±X · EMA9/20/50 stack <up/down/mixed>
            VWAP $X (price ±X%) · ATR14 X · Bollinger %B X · OR <hi/lo>

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
- `src/micro/` — `indicators.py` (pure TA), `signal_model.py` (probabilistic LONG/SHORT/HOLD + price ranges), `cli.py` (entry point). Tests: `tests/unit/micro/`.
- `.claude/commands/entry-check.md` / `exit-check.md` — the daily-bar execution-layer siblings `/micro` complements at the intraday scale.
- CLAUDE.md **P1** (math in Python, not markdown), **P9** (decision vocabulary — see carveout above), **P14** (inner-ring tests before outer).
