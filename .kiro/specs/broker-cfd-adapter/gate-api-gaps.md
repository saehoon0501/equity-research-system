# Gate TradFi CFD API — Specification Gaps

> **✅ LARGELY RESOLVED 2026-05-29 — superseded by `gate-tradfi-api-reference.md`.** The operator supplied the full official TradFi API spec. Nearly every gap below is now answered by verified endpoint/field schemas (see the reference doc). The tables are retained as a resolution record. **True residuals remaining** (not answerable from the API schema):
> - **G10** — no native client-order-id / idempotency key → mitigate adapter-side (poll-before-resend).
> - **G21** — **gap-through-stop CONFIRMED (decision-grade) 2026-05-29**: materializes, downside effectively **unbounded** (50% stop-out non-guaranteed; no GSLO/max-loss-cap; leverage fixed) — strong MT5 + Bybit-comparable analogy; Gate-primary TradFi terms (403) are the **pre-live close-out**. Mitigation = §16 funding cap + gap-event avoidance + `gap-risk-veto-filter`. Sub-residuals (closed-session pricing mechanism, exact hours, `fill_negative` pursuit) → pre-live verification. See `survival-gate/gap-through-stop-findings-2026-05-29.md`.
> - **G22** — **PARTIAL (research 2026-05-29):** confirmed **no negative-balance protection** + plausibly unsecured-creditor/offshore; `fill_negative` is admin reconciliation, **not** NBP. STILL OPEN: exact entity / jurisdiction / US-persons bar + fund segregation (User Agreement).
> - **`close_type` (1/2) semantics** — confirm on first authenticated close.
> - **Account-vs-symbol leverage field interaction + writability** — no setter found; verify against live responses.
>
> **Resolved by deep-research 2026-05-29:** leverage = fixed per-instrument (US stocks **5x**, no setter); swap rates readable (`symbols/detail`); **G24 rate-limits** = no published `/tradfi` row but `X-Gate-RateLimit-*` headers + 429 govern (discover at runtime). Everything else (G1–G9, G11–G20, G23) was resolved by the API spec. The biggest — **G7: positions carry a stable `position_id`, close is by-position-id** — validates the Req 1.2/1.3/1.9 model.

**Status (historical):** was BLOCKING for `broker-cfd-adapter`. The requirements draft (`requirements.md`) rested on Gate API capabilities that were not yet verified. This file enumerated what Gate had to tell us; the reference doc now answers it.

**Source:** exploration `docs/exploration-systematic-flow-architecture-2026-05-28.md` §11 (verified facts) + §11.6 (residual gaps) + the capability assumptions embedded in `requirements.md`.

**Operator note (2026-05-29):** the `broker_mcp/` on-disk dir is **stale cruft** (ignore it). The Gate TradFi API "will be used but is not specified enough to write a spec at this moment" — this checklist is the path from that state to a buildable spec.

---

## Already verified (do not re-litigate)

From §11, confirmed against live `api.gateio.ws/api/v4` on 2026-05-29:

- Signed REST APIv4 (key + secret + SIGN); **no MT5 bridge** (REST proxies exist).
- Endpoints exist (probe: 400=needs-auth, 404=absent): `POST/GET /tradfi/orders`, `GET /tradfi/positions`, `GET /tradfi/users/assets`, `GET /tradfi/users/mt5-account`, `GET /tradfi/symbols` (public, no auth).
- Universe: 441 US-stock CFDs (category_id 2). Leverage tiers: 65 names @ 5x, 370 @ 4x (= product min-order-leverage floor), 6 @ 3.33x (untradeable at the floor).
- Liquidation = MT5 stop-out at **margin level ≤ 50%**, **cross-margin only** (account-level, no isolated).
- Settlement USDx (1:1 USDT). Commission from $0.018/trade at open. Overnight swap *exists* (charged through market closure) and is **variable daily** — mechanism confirmed, values not.
- `symbol_desc` is unreliable (`AAPL`→"American Airlines"); map by ticker only; filter `is_base: true`.
- Order types: market / trigger / TP-SL only (no resting limit book). Units: lots or USDx-value. Each buy/sell opens an **independent** position (no netting except same-pair long/short lot offset). PnL uses counterparty prices, not mid.

---

## Resolved 2026-05-29 — operator-supplied facts

The operator supplied verbatim citations from Gate.io product announcements + industry/educational coverage (Incrypted, Binance Square, CoinGecko Learn — **secondary sources corroborating Gate's releases**; the exact API *field names* still warrant a 🟡 authenticated read, but the *mechanics* below are accepted):

- **Max lot size = 100 per position, regardless of available margin** (closes part of G4). New constraint: the adapter must reject any order exceeding 100 lots even when margin would permit it.
- **Liquidation = account margin level ≤ 50%, executed as a *gradual* forced position reduction** (closes G17): *"When the account margin level falls to 50% or below, the system initiates a forced position closure process, gradually reducing the corresponding positions in accordance with pre-set risk management rules."* — Incrypted. ⟹ `survival-gate` must model liquidation as **progressive de-risking, not a single binary wipe**.
- **Core risk formula: `Margin Level = (Equity ÷ Used Margin) × 100%`** (closes G16 formula): *"...margin calculations (Margin Level = (Equity / Used Margin) × 100%), and the 50% stop-out mechanism."* — CoinGecko Learn.
- **Leverage is a fixed enumerated discrete menu** (closes G2): *"gold supports 20x, 100x, 200x, 500x leverage; silver supports 10x, 20x, 50x, 100x; indices such as NAS100 ... as well as foreign exchange trading pairs like EURUSD, USDJPY, all support multiple leverage options of 20x, 100x, 200x, and 500x..."* — Binance Square. **NB: those high-leverage examples are commodities / indices / FX — NOT the US-stock CFDs in scope, which remain 4x / 5x / 3.33x per §11.3. The takeaway is structural: leverage is a discrete allowed-value set, not a continuous range.**

**Derived consequence (closes G5 + validates §11.3):** used (initial) margin per position = notional ÷ leverage; there is **no separate per-position maintenance margin** — the only stop-out is the account-level margin-level ≤ 50% rule. Worst-case survival distance with zero free margin: margin level = (used_margin − loss) ÷ used_margin × 100% = 50% ⟹ loss = ½ × used_margin ⟹ **−12.5% @4x, −10% @5x** — exactly §11.3. The independently-probed §11.3 figure and the operator-supplied formula now agree.

---

## Gaps — what must be pinned

**Resolution legend:**
🟢 **PROBE** — closable by me against the *public* `/tradfi/symbols` endpoint (no secret needed); just greenlight.
🟡 **AUTH** — needs your Gate APIv4 key+secret, or you run an authenticated read / paper order and paste the response.
🔴 **DOCS/403** — needs you logged into gate.com to read a page behind the 403 (Fee Calculation, margin rules, T&C), or a legal/T&C read.

### A. Symbol metadata — `GET /tradfi/symbols` (public)

| ID | Gap | Blocks | Resolve |
|---|---|---|---|
| G1 | Exact symbol-object schema (field names + types) | Req 4 (symbol map), all enforcement | 🟢 |
| G2 | ✅ **RESOLVED** — leverage is a fixed **enumerated discrete menu** (not a min/max range); US-stock CFDs = 4x/5x/3.33x (§11.3). Residual: 🟢-probe the exact array field name on the symbol object | Req 5 (leverage cap) | ✅ / 🟢 name |
| G3 | `status` enum values + `next_open_time` format/timezone | Req 6 (market hours) | 🟢 |
| G4 | **PARTIAL** — **max lot size = 100 per position, regardless of margin** (operator-supplied 2026-05-29). Still open: min order size, lot/contract size, tick/price increment, lots-vs-USDx unit declaration | Req 1.6 (size units), new Req 1.10 (max size), Req 5/6 | 🟢 |
| G5 | ✅ **RESOLVED** — used (initial) margin = notional ÷ leverage; **no separate per-position maintenance margin** — stop-out is the account margin-level ≤ 50% rule (see G16/G17). Confirms §11.3 worst-case | survival-gate (broker surfaces it) | ✅ |

### B. Order placement — `POST /tradfi/orders` (auth)

| ID | Gap | Blocks | Resolve |
|---|---|---|---|
| G6 | Request schema per order type (market / trigger / TP-SL): required fields, side encoding, how leverage & size are passed | Req 1, 5, 6 | 🟡 / 🔴 |
| G7 | **Does order creation return a stable `position_id`? Is the position the unit you later reduce/close?** | **Req 1.2 / 1.3 / 1.9** (caller-supplied position ID assumption) | 🟡 |
| G8 | Reduce/close mechanism — separate close endpoint? reduce-only flag? close-by-position-id? (§11.4 says "via positions endpoint" — confirm the exact call) | Req 1.2 / 1.3 | 🟡 / 🔴 |
| G9 | Order response schema: fill price, fill qty, status, partial-fill semantics, counterparty fill price | Req 9.3 (slippage), Req 2.2 | 🟡 |
| G10 | Client-order-id / idempotency support (prevent a double-send → independent-position duplication) | safety / Req 7 | 🟡 / 🔴 |
| G11 | Behavior when market closed — API reject vs. accept/queue | Req 6.3 (queuing assumption) | 🟡 / 🔴 (or 🟢 by probing a closed-market order) |
| G12 | Is there an API-native test/dry-run order mode, or must paper mode be simulated in-adapter? | Req 8.2 (paper mode) | 🔴 / 🟡 |

### C. Positions — `GET /tradfi/positions` (auth)

| ID | Gap | Blocks | Resolve |
|---|---|---|---|
| G13 | Position-object schema: `position_id`, symbol, side, size, entry, current/mark price, unrealized PnL, used margin, leverage | Req 2, 3 | 🟡 |
| G14 | Does the position object expose **per-position daily swap/holding fee accrued**? | Req 3.3 (§11.6 swap values behind 403) | 🟡 |
| G15 | Does it expose per-position **liquidation price** / maintenance margin? | survival-gate input | 🟡 |

### D. Account — `GET /tradfi/users/assets` + `/mt5-account` (auth)

| ID | Gap | Blocks | Resolve |
|---|---|---|---|
| G16 | ✅ **FORMULA RESOLVED** — **Margin Level = (Equity ÷ Used Margin) × 100%** (operator-supplied, CoinGecko Learn). Residual 🟡: exact API field *names* for equity / used margin / margin_level | Req 3.1 + survival | ✅ formula / 🟡 names |
| G17 | ✅ **RESOLVED** — forced liquidation at **account margin level ≤ 50%**, executed as a **gradual position reduction** (not a single wipe), per pre-set risk rules (operator-supplied, Incrypted). Account-level confirmed | survival-gate | ✅ |
| G18 | ~~USDx settlement & 1:1 USDT~~ — ✅ resolved (§11.2), listed for completeness | — | ✅ |

### E. Survival / risk facts (§11.6 — primarily block `survival-gate`; broker surfaces some inputs)

| ID | Gap | Blocks | Resolve |
|---|---|---|---|
| G19 | ✅ **RESOLVED** — swap rates readable per symbol via `GET /tradfi/symbols/detail` (`buy/sell_swap_cost_rate`, `swap_cost_3day`); realized swap per closed position in `positions/history.swap` | Req 3.3; survival carry model | ✅ |
| G20 | **LIKELY RESOLVED** — 50% stop-out reads as a **platform-wide** rule (sources state it without per-name qualification); per-symbol margin requirement varies only via the leverage tier (= 1 ÷ leverage, known). Confirm no per-name override | survival-gate | 🔴 confirm-only |
| G21 | **RESOLVED (decision-grade) 2026-05-29** — gap-through-stop CONFIRMED, downside effectively unbounded (50% stop-out non-guaranteed, no GSLO/cap, leverage fixed); strong MT5 + Bybit analogy. Gate-primary terms (403) + closed-session pricing mechanism + exact hours + `fill_negative` pursuit = pre-live verification. See `survival-gate/gap-through-stop-findings-2026-05-29.md` | survival-gate; §16 | 🟡 decision-grade / 🔴 Gate-primary |
| G22 | **PARTIAL (hard finding, research 2026-05-29)** — **NO negative-balance protection** ("lose more than invested"); plausibly **unsecured-creditor / offshore** (Gate disclaims broker/fiduciary; no CFD license). `fill_negative` = administrative reconciliation, **NOT** an NBP guarantee. STILL OPEN: exact operating entity / jurisdiction / explicit US-persons bar (User Agreement); fund segregation + insolvency priority | risk acceptance; survival-gate (§16 funding cap) | 🟡 hard finding / 🔴 entity |

### F. Auth & limits

| ID | Gap | Blocks | Resolve |
|---|---|---|---|
| G23 | Confirm `/tradfi` signing = standard Gate APIv4 HMAC-SHA512 SIGN (payload format for `/tradfi` paths; official SDK does **not** cover TradFi) | all auth operations | 🟡 (needs key to test) / 🔴 |
| G24 | Rate limits on `/tradfi` endpoints | daemon polling cadence | 🟡 / 🔴 |

---

## Resolution routes (corrected 2026-05-29)

The schema gaps are **closed by the supplied API spec** (`gate-tradfi-api-reference.md`) — no probing needed. One earlier claim was wrong and is corrected here:

- **The enforcement-critical fields are AUTHENTICATED, not public.** Per-symbol `leverage`, `min_order_volume`/`max_order_volume`, swap rates, and `price_sl_level` live on `GET /tradfi/symbols/detail` (🔒, ≤10 symbols/call → ~45 calls to cache all 441 names). The **public** `GET /tradfi/symbols` only gives `status` / `trade_mode` / `next_open_time` / `price_precision` / `settlement_currency`. So populating the cap/size/swap enforcement caches needs a key — there is no credential-free shortcut.
- **What still needs you (true residuals):** G21 (gap/oracle behavior — market mechanics), G22 (insolvency/creditor status — legal/T&C), G24 (request-rate limits), `close_type` 1/2 semantics — all design-time confirmations or survival-gate concerns, none blocking the broker requirements.
- **Build-time validation (P12/P14):** before the adapter is trusted, one authenticated round-trip — read `symbols/detail` for a known ticker, read `assets` + `mt5-account`, and (in paper) exercise the order→poll→close flow — confirms the field names and the async/position-id lifecycle against a live account.

## Exit criteria — when does `broker-cfd-adapter` unblock?

The broker spec becomes buildable once the operation/enforcement mechanics are pinned. As of 2026-05-29:

- **Resolved:** G2 (discrete leverage menu), G5 (margin = notional÷leverage, no separate maintenance), G16-formula (Margin Level), G17 (50% gradual stop-out), G4-partial (max lot 100); G20 confirm-only.
- **Still blocking broker:** **G1, G3, G4-remainder, G6–G15, G16-field-names, G23** (+ G24 for the daemon). The single most load-bearing open item is **G7 — does an order return a stable `position_id`?** (Req 1.2/1.3/1.9 hinge on it.)
- **`survival-gate` blockers (shared):** G19 (swap values), G21 (oracle/gap), G22 (insolvency) remain 🔴; but the *core* survival math (G5/G16/G17) is now resolved, so the gate's liquidation-distance model is specifiable — and must adopt the **gradual-reduction** semantics, not a binary wipe.

When the broker block clears, revisit `requirements.md` — criteria 1.2/1.3/1.9 (position-ID targeting), 3.1 (margin field names), 3.3 (swap fee), 6.3 (queuing) may tighten against the verified facts. The new **max-lot-100** rule is already added as Req 1.10.
