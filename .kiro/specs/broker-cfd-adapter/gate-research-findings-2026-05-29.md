# Gate TradFi — Deep-Research Findings (2026-05-29)

**Source:** `/deep-research` workflow (104 agents, 21 sources fetched, 25 claims adversarially verified → 18 confirmed / 7 killed). Resolves the §11.6 residuals + the leverage-configuration operator question.

**⚠️ Source-read fragility:** most `gate.com` primary pages returned HTTP 403 to automated fetch (Akamai); their content was reconstructed via search snippets + the `r.jina.ai` reader proxy, not direct DOM reads. A key leverage source (chainwire) is a Gate-branded **press release**, not a help-center article. TradFi is a Jan–Mar 2026 product (API moving, ~v4.106) — **re-verify before locking the adapter**. Confidence tags are the verification pass's.

---

## CONFIRMED

### Leverage — RESOLVES the operator decision
- **Leverage is a FIXED per-instrument product attribute — NOT user-changeable.** US-stock/equity CFDs = **up to 5x** (resolves the 4x/5x prior → **5x**); forex / indices / metals up to 500x. *[HIGH — Chainwire PR, Incrypted, CoinGecko, TradingView]*
- The user changes leverage **only by selecting a different listed symbol.** For commodities this is confirmed as separate symbols off one underlying (gold: `XAUUSD20`=20x / `XAUUSD100`=100x / `XAUUSD200`=200x / `XAUUSD`=500x, unified pricing). *[HIGH — gate.com announcement 49704, MEXC]* **Caveat:** the per-tier-symbol mechanism is confirmed only for COMMODITIES; equity is documented at a single 5x ceiling — do **not** assume per-tier stock symbols.
- **No writable leverage-setter endpoint exists for TradFi** (the only leverage-setter in the whole Gate API is crypto Futures `POST /futures/{settle}/positions/{contract}/leverage`). ⟹ **confirms Req 5**: exposure is controlled via order **volume**, never by setting a per-order/per-symbol leverage.

### Negative-balance & insolvency — CRITICAL risk correction
- **No negative-balance protection (NBP) for TradFi CFDs.** Gate's NBP machinery (insurance fund + bankruptcy price + ADL) is **crypto-perpetual-specific**; TradFi uses the separate margin-ratio 50% stop-out. Gate's risk disclosure warns users can **"lose more than your initial investment."** *[HIGH]* ⟹ **assume NO NBP.**
- **CORRECTION (contradicts earlier assumption):** the `fill_negative` ("cover negative balance") txn type means a negative balance *can occur and is reconciled administratively* — it is **NOT** a user-facing NBP guarantee. This reverses the earlier `gate-api-gaps.md` G22 / `gate-tradfi-api-reference.md` gotcha-#9 reading.
- **Unsecured-creditor / offshore posture.** Gate disclaims being broker/agent/fiduciary; states held assets are not covered by any investor-compensation/deposit/insurance scheme; discloses only crypto-custody licenses (no MiFID/CFD investment-firm authorization). *[MEDIUM — risk-disclosure + licenses pages, scoped/hedged]* ⟹ a TradFi CFD holder is plausibly an **unsecured counterparty**, not a protected client with segregated funds.

### Rate limits — RESOLVES G24
- **No dedicated `/tradfi` rate-limit row;** the global `api/v4` rule applies (~150 req / 10s per-endpoint UID class). Every response carries **`X-Gate-RateLimit-Requests-Remain` / `-Limit` / `-Reset-Timestamp` headers + HTTP 429** on excess. ⟹ the adapter should **discover effective limits at runtime from the headers**, not hardcode a number. *[MEDIUM — verify the headers are actually present on a live `/tradfi` response]*

---

## REFUTED (do not resurrect)
- "TradFi runs offshore outside ALL disclosed licensed entities" — *killed 0-3*; only the narrower "licenses page discloses no CFD investment-firm authorization" survives.
- "multi-leverage = a user-configurable slider/tiered model" — *killed 0-3*; it is separate fixed-leverage symbols.
- "`fill_negative` ⟹ NBP guarantee" — refuted by Gate's own "lose more than invested" disclosure.

## STILL OPEN (do NOT infer — verify empirically / from the User Agreement)
- **Q3 gap-through (G21):** closed-session/weekend pricing + whether a stop-loss or the account-level 50% stop-out can be **gapped through** so realized loss exceeds the stop distance. **Genuinely unanswered.** This is `survival-gate`'s core tail-risk (§12.2) and combines with "no NBP" into the worst case.
- **Account-vs-symbol leverage interaction:** how `mt5-account.leverage` relates to `symbols/detail.leverage`, and whether either is writable — no setter found, but absence ≠ proof; verify against live responses.
- **Exact TradFi legal entity / jurisdiction / US-persons bar** — deferred to the User Agreement; not named on the risk/licenses pages.
- **Fund segregation / insolvency priority** — no TradFi-specific segregation policy located.
- **Empirical rate-limit confirmation** — capture a live `/tradfi` response to confirm the headers + concrete limit.

## Disregard
`GatesFX` (gatesfx.com, Saint Lucia, 1:1000 leverage, TradeLocker) is a **separate broker** — name collision, not Gate.io TradFi.
