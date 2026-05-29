# Exploration: Systematic-Flow Architecture for the Equity-Research System

**Date captured:** 2026-05-28
**Status:** COMMITTED TO BUILD (operator 2026-05-29) — §11–§14 promoted from exploration to a committed build, **with a revision to §14.3** (in-session LLM monitor/intervention; see §15). Remains v0.1 **paper-only** (§11.5) and is **not yet a `BUILD_LOG.md` decision** — decision-log promotion still awaits outcome-scoping + the inner-ring → outer-ring discipline of P14, per §15. (Originally captured as EXPLORATION 2026-05-28.)
**Trigger:** Operator-driven 4-layer pushback during a live MU position discussion. The MU trade detail is ephemeral; the architectural arc surfaced is what's worth preserving.

---

## 1. What this document is

A self-contained capture of a strategic conversation that walked the operator from "is my probability framework grounded?" to "should the system predict the systematic players rather than the market?" The conversation produced an architectural endpoint worth considering — but no commitment was made. This doc preserves the strategic reasoning so a future session can pick it up cold.

It is **not** a spec, **not** a decision log entry, and **not** a build plan. It is a pre-decision strategic record.

**Working mode:** this doc is where open-ended questions get *worked and converged to a path*. Forks are resolved here by reasoned recommendation — recorded as the chosen path (revisable, since this is exploration) — not by deferring the choice to the operator each pass. A fork is escalated to the operator only when it is genuinely theirs: irreversible, resource-committing, or pure preference with no analytic tiebreaker.

---

## 2. The 4-layer ladder of operator pushback

Each rung was a strict superset of the one below. Each pushback rejected the previous answer as insufficient and forced a higher-order framing.

| Layer | Operator pushback | Strategic answer that emerged |
|---|---|---|
| **L0 — Fundamentals** | "Probability percentages from qualitative reasoning have no empirical grounding (cf. P15). Replace with projected numbers applied to valuation." | Bull scenario as testable structure: FY27/FY28 segment-level revenue + OM projections → derived EPS → applied to P/E framework → 10 named falsifiers per assumption. Grounded, falsifiable, auditable. |
| **L1 — "Right but unrewarded"** | "Being right on fundamentals doesn't get paid in momentum regimes (cf. PLTR $18→$200). System keeps me out of rallies." | Use the sleeve architecture already in CLAUDE.md (core ≤80%, thematic ≤25%, speculative ≤8%). Momentum participation lives in `speculative_optionality` with defined-risk instruments (spreads, LEAPs) and time-stops. The slow-layer governs 92% of book; the other 8% is explicitly off-leash for momentum. **[Instrument choice revisited 2026-05-29 — see §16.1: for the paper phase the 8% sleeve is a leveraged Gate CFD with *account-level* defined-risk (funding cap) + a hard flat-before-closure invariant (intraday-flat); defined-risk spreads/LEAPs (B) are the pre-live target if the Gate User Agreement confirms no-GSLO/no-cap.]** |
| **L2 — Weight drift / non-stationarity** | "What if the fundamental weights themselves have shifted? Detection lag exceeds regime persistence." | Demote slow-layer from "the brain" to one ensemble input. Build framework attribution loop on `counterfactual_ledger` (already exists per P14). Reweight ensemble vote by 90d realized P&L by framework. Default to defined-risk instruments. Response-not-prediction. |
| **L3 — Predict the predictors** | "Rather than predict the market, predict what CTAs / systematic players will be forced to do." | Yes — this is **second-order systematic flow modeling**, an institutional-tier discipline. Build `systematic-flow-overlay` agent emitting price-conditional flow forecasts (CTA flip points, vol-target deleveraging triggers, dealer gamma flip prices, passive index flows, buyback windows). Position around their forced flows. |

**Strongest framing of the conclusion (operator-confirmed):**
> "The market isn't trying to price assets correctly — it's a chain of systematic players executing their decision rules in sequence. If you can model the decision rules and their trigger points, you don't need to predict fundamentals at all. You just need to position into the next forced flow."

---

## 3. Architectural endpoint (if pursued)

A 5-signal ensemble feeding pm-supervisor's `summary_code`, weighted dynamically by realized P&L attribution. **Slow-layer keeps its seat at the table but no longer holds the final vote.**

```
              ┌─ slow-layer fundamental (existing /research-company)  ─┐
              ├─ tactical-overlay / Antonacci (existing)               ─┤
ensemble vote ├─ flow-overlay v0.2 / dealer gamma (existing)           ─┤── weighted by
              ├─ mean-reversion-overlay (existing)                     ─┤   90d realized
              └─ systematic-flow-overlay (NEW — to build)              ─┘   P&L attribution
                       │
                       ▼
              pm-supervisor: summary_code = weighted ensemble vote
              (was: slow-layer-anchored single-brain emission)
                       │
                       ▼
              instrument recommender: cash+leverage / debit spread / LEAP / collar
              (chosen by ensemble agreement strength and IV regime)
                       │
                       ▼
              sleeve allocation: core (≤80%) / thematic (≤25%) / speculative (≤8%)
                       │
                       ▼
              position sized by ENSEMBLE AGREEMENT, not by individual conviction
              (agreement <40% → defined-risk only; agreement >80% → cash+leverage allowed)
```

---

## 4. Three load-bearing builds (if pursued)

### Build A — `systematic-flow-overlay` agent

New peer to tactical/flow/mean-reversion overlays. Emits **price-conditional** flow forecasts over 5/20-day horizons:

- **CTA positioning estimate** — aggregate of AQR-canonical multi-horizon TSMOM signals (1/3/12-month lookbacks per Hurst/Ooi/Pedersen) and Turtle-canonical Donchian breakouts (20d/55d per Dennis 1983), weighted toward SG Trend Index reverse-engineering. Practitioner systems also commonly use 50/100/200d MA crossover filters as a complementary signal lineage.
- **CTA flip points** — at what price does the next signal flip occur in each system
- **Vol-target deleveraging trigger** — implied VIX threshold at which vol-target funds cut exposure
- **Dealer gamma flip price** — where dealer hedging flow direction reverses
- **Passive index events** — next inclusion / rebalance dates with estimated net flow
- **Buyback window state** — corporate blackout/open periods with estimated daily demand
- **Month/quarter-end rebal estimate** — net pension flow into laggards/out of winners

Output envelope shape would follow P11 (per-agent ownership) and pass an HG validator following the existing pattern at `src/eval/gates/`. Stage placement TBD — likely Stage 1 parallel with the other overlays.

### Build B — Framework attribution on `counterfactual_ledger`

`counterfactual_ledger` (mig 030) already exists per P14. Extend it:

- Add `framework_attribution` field per closed trade: which framework drove the conviction (value-DCF / momentum / flow / regime / systematic-flow)
- 90-day rolling P&L attribution by framework
- pm-supervisor reads attribution at ensemble-vote time, dynamically resizes weights
- Frameworks losing money for 90+ days drop to ~5% of the vote; winning frameworks climb

This is the load-bearing piece that addresses L2 (non-stationarity). Without it, the ensemble is just multiple opinions; with it, the system *empirically* knows which framework to trust this regime, regardless of whether weights have philosophically shifted.

### Build C — Instrument recommender

Shift the default instrument from cash + leverage to defined-risk:

- Ensemble agreement >80% AND IV percentile <40 → cash+leverage allowed
- Ensemble agreement 40–80% OR IV percentile 40–70 → debit spread / collar
- Ensemble agreement <40% OR IV percentile >70 → LEAP only, or no trade
- Output integrated into pm-supervisor's structured report as a new dimension

The intent: structure absorbs framework error. A spread risks premium; cash + leverage risks principal. Non-stationary regimes manifest as ensemble disagreement → system automatically routes to less-fragile instruments.

---

## 5. What already exists vs. what's missing

| Component | Status | Source |
|---|---|---|
| Slow-layer fundamental (DCF, Helmer, F-score, Z'') | EXISTING | `/research-company` |
| Tactical-overlay (Antonacci dual momentum) | EXISTING | Stage 1 parallel agent |
| Flow-overlay (CTA-proximity composite; v0.2 adds GEX) | EXISTING | Stage 1 parallel agent |
| Mean-reversion-overlay (drawdown + RSI + Bollinger + MA-distance) | EXISTING | Stage 1 parallel agent |
| pm-supervisor 6-dim report + sleeve cap enforcement | EXISTING | Stage 3 |
| `counterfactual_ledger` for outcome tracking | EXISTING (mig 030) | P14 outer ring |
| Multi-overlay soft-modulator ingestion in pm-supervisor | EXISTING | per CLAUDE.md Section 2.1 v5-final |
| **systematic-flow-overlay (CTA flip points + vol-target + buyback windows + 0DTE gamma)** | **MISSING** | Build A |
| **Framework P&L attribution on counterfactual_ledger** | **MISSING** | Build B |
| **Instrument recommender (defined-risk default)** | **MISSING** | Build C |
| **Dynamic ensemble reweighting in pm-supervisor** | **MISSING** | follows from B |

The architecture is roughly 70% there. Three builds close the gap.

---

## 6. The Lucas-critique / shelf-life concern

Second-order systematic flow modeling is institutionally recognized. Goldman (trading-desk flows notes — historically Rubner, now Flood-desk), Nomura (QIS CTA model — McElligott), Deutsche Bank ("Positioning and Flows" by Chadha/Thatte, which includes CTA exposure as one component), and Société Générale (SG CTA Index — Bloomberg ticker NEIXCTA, the only daily-published official benchmark) all surface CTA positioning analytics; macro funds explicitly trade against them. This means:

- **The edge is real but partially crowded.** AQR and Man AHL document CTA evolution toward multi-horizon filtering and regime-aware vol-targeting; recent evidence shows widening dispersion between managers (~65pp spread between best and worst in 2022) rather than uniform decay. 2022 was actually a banner year for trend (SG CTA Trend +27.4% vs S&P 500 −19.5%), so "CTA capitulation always works" / "CTAs are dead" are both wrong framings.
- **Shelf life is finite.** Whatever flow model gets built will need recalibration every 3–6 months as the systematic players evolve.
- **Single-stock applications are weaker than index-level.** SPY/QQQ have rich, easily-modeled CTA positioning. Single names get diluted signal — works for Mag-7 + heavily-optioned semis, gets thin for idiosyncratic small/mid caps.
- **Reflexivity risk.** If the system becomes a popular pattern, the very flows being predicted shift to defeat the prediction.

The architectural answer to shelf-life is the framework attribution loop (Build B). When a flow model stops working, attribution drops its weight automatically. Ensemble survives even when individual models decay.

---

## 7. Open questions to resolve before commit

If a future planning conversation decides to pursue this direction, these need answers:

1. **Stage placement of `systematic-flow-overlay`** — Stage 1 parallel? Or post-overlay aggregation stage? Affects dispatch budget and latency.
2. **Ensemble weighting algorithm** — simple 90d Sharpe? Bayesian shrinkage on framework win rates? Operator policy on minimum weight floor (don't let any framework drop below 5%?) and ceiling (no framework above 60%?).
3. **Data sourcing for CTA positioning** — proxy via SG Trend Index + price-action reconstruction? Pay for Nomura QIS feed? Build from scratch via Polygon options + market data?
4. **Defined-risk default scope** — apply to all sleeves or just speculative? Some operators run defined-risk for everything (Taleb-style barbell); others only for non-core.
5. **Calibration cadence** — how often is the framework-attribution loop recomputed and reweighted? Daily? Weekly? At trade close only?
6. **Promotion criteria** — what hold-out evidence converts this exploration to a `BUILD_LOG.md` decision? Suggest: 6 months of paper-trading the ensemble alongside the current pm-supervisor, with framework attribution showing the ensemble's Sharpe beats slow-layer-only by ≥X.
7. **Sleeve cap modulation by regime** — does `speculative_optionality` cap dynamically scale by detected regime (8% baseline → 15% momentum-extended → 4% mean-reversion)? Operator policy decision.
8. **Backward compatibility with existing eval-loop** — `counterfactual_ledger` currently scores final 4-bin label vs sector-ETF-excess returns (per P14). Adding framework attribution requires schema extension without breaking existing scoring.

---

## 8. What this is NOT

Per operator's framing ("not decided yet"):

- **Not a `BUILD_LOG.md` entry** — would need promotion through decision review first
- **Not a spec** — would need design doc following v2-final-spec.md pattern
- **Not a trade decision** — the MU $917 context that triggered the conversation is ephemeral and intentionally not surfaced in this architectural record
- **Not a refactor of CLAUDE.md principles** — P1, P9, P11, P14, P15 all remain load-bearing under this architecture; ensemble voting is composable with them, not in conflict
- **Not a rejection of slow-layer research** — slow-layer keeps its seat in the ensemble; it just no longer holds the final vote

---

## 9. Pointers to load-bearing reading

If a future session picks this up cold:

- `CLAUDE.md` — architectural principles, especially P7 (downstream conservatism), P11 (per-agent envelope ownership), P14 (test surface rings), P15 (no performative probabilities)
- `BUILD_LOG.md` — architectural decisions 1–6, especially decision 6 ("where does this code go?")
- `docs/v2-orchestrator-refactor-consensus.md` — 2026-05-12 refactor that produced today's pm-supervisor + overlay architecture
- `docs/v2-final-spec.md` — canonical spec for agent emissions
- `docs/phasing-plan.md` §2.5 — C3 gate thresholds (must not be relaxed)
- `.claude/agents/tactical-overlay.md`, `.claude/agents/flow-overlay.md`, `.claude/agents/mean-reversion-overlay.md` — existing overlay agents to mirror for `systematic-flow-overlay`
- `src/eval/gates/` — existing HG validator pattern for envelope shape
- `counterfactual_ledger` schema (mig 030) — extension target for framework attribution

---

## 10. One-paragraph summary for cold pickup

The current equity-research system anchors final decisions on slow-layer fundamental research (DCF + Helmer + quality gate) with tactical/flow/mean-reversion overlays as soft modulators. Operator surfaced that this architecture under-rewards in momentum regimes (L1), fails under fundamental-weight non-stationarity (L2), and ignores the higher-order edge of modeling systematic players' forced flows (L3). The exploration endpoint is a 5-signal ensemble where slow-layer is one input among peers, weighted dynamically by framework-attributed realized P&L; instrument choice defaults to defined-risk; position size scales with ensemble agreement. Three builds close the gap: (A) `systematic-flow-overlay` agent emitting price-conditional flow forecasts, (B) framework attribution on `counterfactual_ledger` with dynamic ensemble reweighting, (C) instrument recommender. Status as of 2026-05-28: exploration only — no commitment, no build started, several open policy questions unresolved.

---

## 11. Execution vehicle — Gate TradFi CFD (operator-selected 2026-05-29)

Status: vehicle selected; architecture above still EXPLORATION. Gate = **execution + account readout only**, NOT a data source (data from Massive / existing stack). All facts below verified against live Gate API `api.gateio.ws/api/v4` on 2026-05-29 (Tier 1 primary); gate.com docs unfetchable (403) and TradFi absent from official SDK/OpenAPI (rest-v4 v4.22.0 = spot/margin/futures only).

### 11.1 Vehicle decision
| Vehicle | Stock leverage | Universe | Hours | Selected |
|---|---|---|---|---|
| **TradFi CFD** | 4–5x cap | 441 US stocks | market-hours sessions | **YES** |
| xStocks perp (`contract_type: stocks`) | up to 50x (75x SPYX) | 16 mega-caps | 24/7 | no — universe too narrow |

### 11.2 Execution path
- Signed REST (APIv4 key + secret + SIGN). **No MT5 bridge** — REST proxies exist despite MT5 backing.
- Home: `src/mcp/broker/` (already scaffolded; P1-correct — execution is a leaf-level MCP tool).
- Endpoints (probe-confirmed: 400=exists/needs-auth, 404=absent):
  - `POST/GET /tradfi/orders` — order placement
  - `GET /tradfi/positions` — open positions
  - `GET /tradfi/users/assets`, `GET /tradfi/users/mt5-account` — account readout
  - `GET /tradfi/symbols` — public instrument list (no auth)
- Settlement: USD (USDx, 1:1 USDT).

### 11.3 Leverage caps (category_id 2 = stocks, 441 names)
| Cap | # names | Note |
|---|---|---|
| 5x | 65 | only tier with headroom above the 4x floor (incl. MU, NVDA, META, MSFT, TSLA, ORCL) |
| 4x | 370 | min-4x floor == product ceiling → zero margin headroom |
| 3.33x | 6 | below floor → untradeable at 4x |

- min-4x sits AT the product ceiling.
- **Liquidation = MT5 stop-out at margin level ≤ 50%** (verified, gate.com help + chainwire/mexc 2026-01-14; CFD differs from perps, which liquidate at MMR ≤ 100%). Worst-case distance (account holds only the position's used margin, zero free-margin buffer): **−12.5% @4x, −10% @5x**. This is ~35–45% TIGHTER than the prior −18–20% estimate (which wrongly assumed near-zero maintenance margin) — survival distance is worse, not better.
- **Cross-margin only** (no isolated). ⟹ true liquidation distance is **account-level, not per-trade**: free margin / other collateral widens it, concentration narrows it. Survival layer must model account equity vs. aggregate used margin, not a fixed per-position %.
- ⟹ survival/liquidation gate is mandatory upstream and must be account-aware.
- **Universe further restricted to S&P 500 (operator 2026-05-29):** the tradable set is **Gate-441 ∩ S&P 500**, not all 441. Rationale: S&P 500 inclusion criteria (positive trailing-4Q + latest-quarter GAAP earnings, ~$18B+ cap, liquidity/float) remove the *base rate* of the catastrophic Survive-grade gap subset — small-cap fraud / delisting / chronic-halt-proneness. The 5x-headroom names (MU/NVDA/META/MSFT/TSLA/ORCL) are all S&P 500, so the leverage analysis above is unaffected. **Caveat (§13 — tail ≠ base rate):** membership certifies at *review-time*, not *real-time* — sitting members have gone to receivership / halt / equity-wipe in days (SVB, First Republic, 2023; index removal *lagged* the collapse). Under decision C (flat-before-closure) the *overnight* expression of that tail is already caught; the irreducible residual is the thin **intraday halt-while-holding** case (a held position halts mid-session on sudden unscheduled news, and a halted position cannot be flattened). So the restriction sharply shrinks the gap-risk filter's workload but does **not** discharge the lexicographic Survive tail — which is why **B remains the pre-live target** (§16.1). The intraday-halt-while-holding residual is now an **accepted residual with real-time halt detection OUT of boundary** (operator 2026-05-29, `survival-gate` R7; no feed, broker confirmed not the source) — bounded by account-level mechanisms (continuous margin monitor + venue stop-out + §16 funding cap), not a halt-specific survival behavior.

### 11.4 broker build constraints
- Tools: `place_order`, `get_positions`, `get_account_assets`.
- Symbol map = identity on US ticker; filter `is_base: true` (skip variants e.g. `NAS100200`).
- **`symbol_desc` is unreliable** — `AAPL`→"American Airlines", `ABNB`→"AbbVie". Map/validate by ticker only.
- Enforce per-symbol `leverages` array (reject over-cap; reject the 6 sub-4x names).
- Enforce hours via `status` (open/closed) + `next_open_time` (reject/queue when closed).
- `BUY/HOLD/TRIM/SELL` (P9) → order side/size; TRIM/SELL reduce/close via positions endpoint.
- **Order types: market / trigger / TP/SL only** (no resting limit-book depth — book is best-bid/ask, market-price fill). Order units = **lots or USDx-value**. Each buy/sell opens an independent position (no netting except same-pair long/short lot offset).
- **PnL uses counterparty prices** (not a mark/oracle) — slippage/spread is the fill reality; don't assume mid.

### 11.5 Safety gate (blocking, pre-build)
- Live leveraged order routing is **beyond v0.1 paper-only scope** — highest blast-radius node in repo.
- Required upstream of `place_order` before any live send: survival/liquidation gate · sleeve caps · per-order size limit · kill switch.
- Per P7, broker adapter is the most conservative node: may reject, never upsize.

### 11.6 Residual gaps
RESOLVED 2026-05-29 (gate.com help text, operator-supplied):
- **Stop-out level** → margin level ≤ 50% (see §11.3). No longer a gap.
- **Overnight swap/financing** → confirmed it exists, charged on positions held *through market closure*; **rate is variable daily**, driven by the underlying's interest rates + instrument, per Gate's "CFD Fee Calculation". NOT a single quotable rate — the multi-month carry model must read the per-position daily holding fee from the account, not a constant. (Distinct from perp funding, which settles every n hours on USDT notional.)
- Trading commission: from $0.018/trade, deducted from balance at position open; varies by instrument.

**UPDATE 2026-05-29** — official TradFi API spec + `/deep-research` (see `.kiro/specs/broker-cfd-adapter/gate-research-findings-2026-05-29.md`) resolved most of these:
- Numeric swap rates → **RESOLVED**: readable per symbol via `GET /tradfi/symbols/detail` (`buy/sell_swap_cost_rate`, `swap_cost_3day`).
- 50% stop-out varies by tier? → **RESOLVED**: stop-out is **account-level** (`mt5-account.stop_out_level`, read live); per-symbol margin = 1 ÷ leverage (fixed). No per-name override found.
- Leverage configuration → **RESOLVED**: fixed per-instrument product attribute (US stocks **5x**), not user-changeable, no setter endpoint.
- Insolvency / negative balance → **PARTIALLY RESOLVED (hard finding)**: **NO negative-balance protection** ("lose more than your initial investment"); plausibly **unsecured-creditor / offshore** (Gate disclaims broker/fiduciary status; no CFD investment-firm license). The `fill_negative` txn type is administrative reconciliation, **not** an NBP guarantee.

STILL OPEN (verify empirically / from the User Agreement — do NOT infer):
- **Gap-through-stop** — **RESOLVED decision-grade 2026-05-29** (deep-research; `survival-gate/gap-through-stop-findings-2026-05-29.md`): CONFIRMED, downside effectively **unbounded** (50% stop-out non-guaranteed; no GSLO / max-loss cap; leverage fixed) — strong MT5 + Bybit-comparable analogy. Still-open sub-residuals (verify pre-live): the Gate TradFi **User Agreement (403)** for any GSLO/cap + the `fill_negative` clawback mechanics; **closed-session pricing** (frozen-at-last vs index); **exact trading hours** (cash-core vs ~24/5).
- Exact TradFi operating entity / jurisdiction / explicit US-persons bar (deferred to the User Agreement).
- Whether TradFi/CFD client funds are segregated, and the holder's insolvency priority.
- Account-level (`mt5-account.leverage`) vs per-symbol (`symbols/detail.leverage`) field interaction + writability — verify against live responses.

## 12. Decision-layer epistemics — reactive, not predictive (operator-decided 2026-05-29)

Horizon fork (from §11 correction): **fork 3 selected** — slow-layer thesis is a directional *prior only*; the CFD layer runs days-to-weeks on its **own survival clock**, decoupled from the months-horizon thesis. **[Hold-lifecycle revised 2026-05-29 — see §16.1: the reactive layer is now *intraday-flat-by-close* (no levered exposure held across a closure), to structurally eliminate the dominant overnight-gap path. The "own survival clock" stands; the *position* clock is intraday. The days-to-weeks framing now refers to the *prediction* horizon, re-expressed via daily re-entry — not an overnight hold.]** Forks 1 (low-vol-only, full 4–5x) and 2 (high-vol + cushion) rejected: (1) doesn't need this apparatus; (2) a cushion that restores ~−20% liq distance turns nominal 5x into real ~2.5x — defeats its own premise.

### 12.1 Why reactive, not predictive
- **Prediction** forecasts a level and demands you *bear path risk to capture convergence*. At 4x / −10–12.5% stop, **path risk is the killer** → prediction's central demand is exactly what you can't afford.
- A live thesis manufactures **conviction**, and conviction is the mechanism by which a levered position holds *through* its stop into liquidation.
- ⟹ the CFD layer is a **reactive/responsive model** (momentum / mean-reversion / flow / vol + account-aware survival gate). It forecasts nothing; it disciplines the path.

### 12.2 The one thing reaction can't self-supply
- Reaction is **blind until the move starts** → at 4x, "blind until it starts" can mean learning via a **gap through the stop** (going-concern, fraud restatement, guidance cliff, halt). Stops don't fill through gaps.
- Forward gap-sight is the *only* non-vestigial contribution of the predictive stack. It is a **tail-risk exclusion filter, not a thesis**.

### 12.3 The slow layer collapses to a veto-only filter
Firewall test on `/research-company` output:
| Slow-layer output | In the CFD layer |
|---|---|
| DCF target / price level | **OUT** — wrong horizon |
| Conviction tier, multi-month hold mandate | **OUT** — the liquidation mechanism |
| Directional sign | **NOT from fundamentals** — `tactical-overlay` relative-strength supplies the side more honestly at this horizon |
| Going-concern / Altman-Z / fraud / earnings-gap proximity | **KEPT** — but this is `catalyst-scout` + quality gate, a small subset |

⟹ for fork 3 the full thesis apparatus is **largely vestigial**; what survives is a narrow gap-risk filter already provided by quality gate + catalyst calendar.

### 12.4 Architectural consequence — current hierarchy is inverted
- Today: slow layer = brain, overlays = "soft modulators, none overrides" (`pm-supervisor` surfacing of `tactical`/`flow`). **Backwards** for a levered reactive model.
- Correct topology: **reactive stack = decider** (momentum/mean-reversion/flow/vol + survival gate); **slow layer = veto-only kill-list** beside it (can remove a name for gap-risk; cannot size, set conviction, or override a stop). P7 at its limit — predictive layer is not upstream of sizing at all.

### 12.5 Make it falsifiable (P14 outer-ring), don't decide by argument
- Test **filter-gated reactive** vs **pure reactive** on `counterfactual_ledger`, survival-net risk-adjusted return. If the filter doesn't improve it, the slow layer is fully vestigial for this layer → drop it.

### 12.6 Sub-fork — DECIDED: (a) thin veto-only filter first
Options were (a) keep slow layer as a **thin veto-only gap-risk filter** (separable, toggleable), vs (b) **pure-reactive** — fold gap-risk directly into the survival gate.

**Decision: (a) first — not on merits, but because it is the only configuration that makes §12.5 runnable.** The whole point (§12.5) is to *measure* whether the gap-risk filter earns its keep; you can only A/B filter-gated-reactive vs pure-reactive if the filter exists as a separable stage. (b) hard-folds gap-risk into the gate and destroys the comparison before it can run. So: build (a) as a toggleable filter stage → run the ledger test → **collapse to (b) iff the ledger shows the filter is vestigial.** (b) is the migration target, not the starting point. Revisit if the filter proves un-toggleable in practice.

**[Housing clarified 2026-05-29 (§16.1) — decision (a) stands, only its home is named.]** The toggleable gap-risk filter stage is **not a standalone spec/module**; it lives **inside `survival-gate`** as a toggleable ex-ante **entry-exclusion stage consuming existing screens** (`catalyst-scout` + quality gate), restricted to the S&P 500 ∩ Gate-441 universe (§11.3, which removes the catastrophic base rate). The §12.5 A/B (filter-gated vs pure-reactive) is preserved — toggle the stage. The *held-position* intraday-halt tail is **out of boundary for real-time detection** (operator 2026-05-29, `survival-gate` R7) — an accepted residual bounded by survival-gate's account-level mechanisms (margin monitor + stop-out + §16 cap), not a halt-specific behavior.

## 13. The value chain — lexicographic precedence (operator-confirmed 2026-05-29)

The decision layer's structuring unit is not the data payload but **the value the system protects**. Those values form a strict chain; each link is a **precondition for the next being allowed to matter at all**:

**Survive ⊳ Preserve ⊳ Edge ⊳ Return**

- **Survive** — don't get liquidated. If this fails, nothing below it exists.
- **Preserve** — don't bleed capital/carry needlessly. Only meaningful once survival is secured.
- **Edge** — be on the right side. Only worth having if you're still in the game to express it.
- **Return** — size/optimize. The last and lowest value, not the first.

**Structuring rule: lexicographic, not weighted.** Never trade a higher link for any amount of a lower one — no return improvement ever buys down survival. This is P7 lifted from "stages get more conservative" up to "values are strictly ordered." The layer walks the chain top-down and **stops the instant a higher value is threatened**; Edge and Return get no vote until Survive has already said yes.

## 14. The adaptive walk-forward tuning loop — engineering architecture (operator-worked 2026-05-29)

Status: EXPLORATION (working-mode §1 — paths below are reasoned recommendations recorded as chosen, revisable; genuinely-operator forks isolated in §14.11). Captures a live engineering-design session that converged the *execution + adaptation mechanics* for the reactive CFD layer. Where §12 fixed the **epistemics** (reactive, veto-only slow layer) and §13 fixed the **value ordering** (Survive ⊳ Preserve ⊳ Edge ⊳ Return), §14 fixes **how the model runs in-session and how it gets tuned between sessions**.

### 14.1 The architectural inversion + two-clock decomposition

The feature ask: a live websocket feed driving CFD entry/exit order triggers at **retail latency**, via a **persistent process**. This **inverts** today's pull model (operator runs a slash command → MCP servers spawn per-call → agents process a snapshot) into a push model (a long-lived process consuming a stream). The resolution is two decoupled clocks:

```
FAST CLOCK — in-session, hot path, NON-LLM, retail latency
  websocket price          ─┐
  REST account state        ├─→ lexicographic gate (Survive ▸ Preserve ▸ Edge ▸ Return)
  ACTIVE (code_v, param_v)  ─┘        │
                                      ▼  broker place/close
                                      │  emits decision-trace telemetry (§14.8)
                                      │  + queues anomaly events (§14.3)
SLOW CLOCK — after-market, LLM, ASYNC, hours-long batch
  monitor model behavior → fit new params/code → walk-forward promote (§14.6)
```

The two clocks meet **only** at the param-version table (P2) and the telemetry log (P4) — never via in-context handoff, never via the daemon dispatching an agent (§14.10).

### 14.2 The LLM is an outer-loop optimizer, not a trader

The LLM's role is **monitor → evaluate → tune → roll-over → repeat**: a walk-forward optimizer *with judgment*, sitting where a grid-search / Bayesian optimizer would sit, but able to reason about *why* the model behaved as it did and emit falsifiable tuning hypotheses (P15). It generalizes **Build B (§4)** from "reweight the ensemble" to "re-tune the whole reactive param set + structure," riding existing machinery:
- **P2 param-versioning** = the tune→roll-over mechanism (a tune produces a new hashed, versioned snapshot).
- **P14 outer ring + `counterfactual_ledger`** = the behavior-evaluation substrate.

### 14.3 No LLM in-session — not even for anomalies

> **⚠️ SUPERSEDED IN PART — operator 2026-05-29 (see §15).** The blanket "no LLM in-session" is overturned: an LLM IS invoked on a regular in-session cadence to *monitor* behavior, *catch anomalies*, and *intervene* (stop → fix → resume). The rationale below still holds **for FITTING** (multi-hour fits stay after-market, §14.4); what is added is a lightweight in-session **monitor/intervene** loop, which is not a fit. The deterministic safe-mode below remains the **instant reflex** (fires first, no LLM round-trip); the LLM is the slower deliberative overlay. What "fix" may mean is an **open operator fork** (§15).

A multi-hour fit cannot run inside a session (by the time it produces new params/code the session has nearly ended — operator note 2026-05-29). So in-session there is **no LLM in the loop at all**:
- A mid-session anomaly (model outside its behavior envelope; a survival breach the gate can't self-resolve) triggers a **reproducible safe-mode** — tighten / flatten / halt-new-entries on the survival channel — and **queues the event**.
- The LLM drains that queue **after the close**.

⟹ the persistent process never wakes the model in-session; the only triggers are the **walk-forward-boundary scheduler** and the **queued events the after-market batch consumes**. (This closes the original "a persistent process that triggers the model on its own" framing: it triggers *analysis/tuning*, asynchronously — never the live fire decision.)

### 14.4 Fitting vs. applying — the safety axis

The split that keeps "tune at runtime AND after-market, params AND code" safe is **not** param-vs-code; it is **applying validated values vs. fitting new ones.** Fitting new values from data *requires* out-of-sample validation to not be overfitting, and intra-session there is no out-of-sample. Therefore:

|  | Runtime (market open, hot path) | After-market (closed) |
|---|---|---|
| **Params** | **SELECT** among pre-validated sets via a reproducible regime signal + **TIGHTEN** Survive/Preserve (P7 one-way). No fresh fitting. Auto. | **FIT** new values (LLM) → held-out / champion-challenger → promote. Gated; autonomous-capable. |
| **Structure / code** | ✗ never | LLM diff → inner-ring suite green (P14) + evaluator + §13 guard → versioned deploy at clean boundary → rollback path. **Fully autonomous — no human sign-off** (operator-decided 2026-05-29). |

Headline: **runtime only *applies* what was already validated** (regime-select + survival-tighten); **all *fitting* of new values — param or code — happens after-market under OOS discipline.** The regime selector is reproducible code (vol regime, §6 CTA regime); the LLM tunes the *menu*, runtime selects from it. The hours-long fit duration is independent confirmation — runtime fitting was never feasible.

**Both tracks promote autonomously** (operator-decided 2026-05-29 — no human sign-off on any promotion; see §14.11 #2). They differ in *gate weight*, not in *who approves*: a param-fit clears the forward-window OOS-beat + evaluator + §13 guard; a code change additionally clears the full inner-ring suite (P14). So both can be next-session-ready the moment their gates pass — but a code deploy still lands only at the next clean boundary (§14.5), so the champion must tolerate an arbitrary gap with a gate-passed-but-not-yet-deployed code version pending.

### 14.5 Version-pinned position lifecycle + atomic hot-swap

Multi-day holds (§12, days-to-weeks) collide with version changes while positions are open. Resolution (recommended path):
- A position carries the **(code_version, param_version)** it was opened under.
- **Edge/Return management** (target, exit, sizing) stays **pinned** to the opening version — no retroactive re-target or resize.
- **Survive management** takes the **global-tightest** rule across the pinned and current versions — survival is one-way-tightenable, never relaxed by a version a position predates (§13 + P7 at the version seam).
- **Atomic hot-swap:** the daemon reads a whole versioned param object once per evaluation cycle and swaps by pointer-flip (P2 snapshot semantics) — never field-by-field, or a mid-cycle swap evaluates the gate on half-old / half-new params.

### 14.6 Walk-forward semantics — roll-over = advance = deploy

**Roll-over = walk-forward window advance, and the advance *event* is the promotion/deploy of a newly tuned model** (operator-decided 2026-05-29).

Cycle: IS (training) window → LLM fits a new (param and/or code) version → pre-flight validate → run as a **challenger over a forward window on live data** (paper first, §11.5) → if it **out-of-sample-beats** the champion → **promote = deploy = window advances** → the completed forward period folds into the next IS window → re-tune → repeat.

- **The forward window *is* the out-of-sample test.** Promotion is earned on live/paper forward performance, not on a backtest over stale history. This is what makes walk-forward-on-deploy the antidote to overfitting rather than another route to it.
- **Anchored vs. rolling IS window — split by the value chain** (recommended): Survive/Preserve params fit **anchored** (all history; never forget a tail / gap / stop-out — rare events are the entire point of survival); Edge/Return params fit **rolling** (recent regime only; old-regime data poisons the edge under non-stationarity, §6 / L2). Different memory lengths per §13 link.
- **Forward-window length is set by statistical significance, not the calendar.** With days-to-weeks holds, a window must span enough *closed* trades for the OOS score to mean anything — min N closed trades (and/or min survival-event count) before a promotion decision is allowed. ⟹ walk-forward boundaries are weeks apart, not nightly.
- **Temporal firewall on the tuner:** the LLM fitting the next IS sees telemetry *only up to the IS boundary* — never the forward window's outcomes (acute leakage hazard with an LLM carrying context). `counterfactual_ledger` needs a **model-version dimension** so forward P&L attributes per-version-per-window — without it the advance is unscoreable.
- Composes with §12.5: the filter-gated-vs-pure-reactive A/B runs *across* walk-forward steps on the version-attributed ledger.

### 14.7 Inner model = softmax + threshold; the lexicographic chain is typed

The in-session model is a **reproducible non-LLM softmax classifier with a decision threshold** (generalizing `src/micro/signal_model.py` from the intraday layer to the days-to-weeks reactive stack), *not* a hard rule engine. "Reproducible non-LLM" is what the latency (§14.1) and fitting-vs-applying (§14.4) arguments actually rode on — both survive the correction.

The correction's real content: **the chain (§13) is typed per link.**
- **Survive = a hard deterministic rule** — you don't "probably" dodge liquidation; it is a margin-distance test (§11.3), no softmax.
- **Edge = the softmax + threshold.** Clearing the threshold is **necessary-but-not-sufficient**: Survive can veto a 95%-probability entry, and sub-threshold = no order = **HOLD** (P9). The threshold is what "keeps the outcome from the ordering process."

Consequences for tuning:
- **The threshold is the canonical tunable *and* the canonical runtime tighten-only lever.** Raise → fewer, higher-conviction entries → de-risk → **runtime auto-apply**. Lower → more entries, more exposure → Edge-loosening → **after-market gated fit only.** P7's one-way rule reduced to a single scalar.
- **Calibration is a primary behavioral diagnostic.** "How the model behaves" includes *is the softmax calibrated* — does a stated 70% realize ~70% over the forward window (Brier / reliability) — not just hit-rate or P&L. The threshold is optimized against the *calibrated* probabilities and the 4x cost asymmetry (a false entry costs more than a missed one — Survive-first). P15-clean: the probabilities are *derived* from the softmax, and keeping them calibrated is the tuner's job.
- Probability magnitude above threshold can scale **Return-layer sizing** (Survive-capped) — §3 "sized by agreement."

### 14.8 Telemetry — the input side the LLM analysis depends on

"Accurate analysis of how the model behaves" requires a **structured, replayable decision-trace**, not just a P&L curve. The daemon must log, per decision: which gate link triggered, signal values + softmax probabilities at fire, expected-vs-actual fill (slippage; §11.4 counterparty prices, not mid), liquidation proximity, stop-outs, and **declined / missed entries**. `counterfactual_ledger` is the *outcome* side; this trace is the *process* side. Without it the tuner is P&L-staring.

**Scope decision (operator 2026-05-29).** This decision-trace is the **model** process trace only — "how the model decided on what input." The separate **LLM-action / reasoning audit** — *why* the after-market tuner promoted a version (§14.2/§14.6) and *why* the in-session monitor intervened (§15) — is owned **per-spec** by those LLM components (P11 — each agent owns its envelope), **not** folded into this telemetry. The two correlate via shared keys (P3: `run_id, code_version, param_version, walk_forward_window`), so the causal chain (model-trace anomaly → monitor/tuner action → outcome in the ledger) is reconstructable by join even though it spans surfaces. ⟹ `walkforward-tuning-loop` and `in-session-monitor` each carry an LLM-action-audit responsibility in their own specs; `decision-trace-telemetry` owns only the model trace + the correlation keys. (Rejected alternative: one unified telemetry substrate owning both — viable under P11's "cross-agent state via DB tables," but the operator chose per-spec ownership for cleaner boundaries, accepting that the audit spans three surfaces joined by keys.)

### 14.9 Operational consequences of an hours-long async batch

- **Checkpoint / resume** — a crash mid-fit must not lose the run.
- **Cost** — T4: the per-`(run_id, agent)` $60 ceiling caps no aggregate; a code-gen + full inner-ring test pass is the single most expensive job in the repo. An aggregate cap for the tuning job is an open policy (§14.11).
- **Scheduled / cron dispatch**, not interactive — fired at the walk-forward boundary; the trading loop never waits for it.

### 14.10 P1-cleanliness — where the code lives

- The daemon is a **leaf executor + event emitter**: it runs the gate the slow layer armed, fires orders via `broker` (`src/mcp/broker/`, §11.2), emits telemetry, queues events. It **never dispatches an agent** — so it is not the forbidden Python orchestrator (P1 / Decision 6).
- The tuning loop is a vanilla Claude Code orchestration (read telemetry + ledger → analyze → gated envelope → DB write), fired by scheduler/queue — orchestration stays in markdown.
- The daemon speaks **Gate REST directly** (or imports `broker` leaf funcs), **not MCP** — MCP is the Claude→tool seam, not a daemon→tool one.

### 14.11 Open operator questions (genuinely theirs — not resolved by recommendation)

1. **Open-position policy across a version change — RESOLVED 2026-05-29** (research-confirmed; see `docs/research-walkforward-tuning-loop-2026-05-29.md`). **Version-pinned lifecycle (§14.5)** is the design target for the eventual multi-day live phase — a *first-principles* safety choice (no external precedent; the only documented live system, Freqtrade, lets live code govern already-open positions = exactly the corruption risk we avoid). **Moot for the paper phase:** §16.1's intraday-flat (flat-before-closure) leaves the book flat at the after-market deploy boundary, so version-pinning only becomes load-bearing at multi-day live.
2. **Promotion authority — RESOLVED 2026-05-29: full autonomous, no human sign-off on *any* promotion** (param-snapshot FIT *and* code/structure deploy). Consequence to keep visible: the autonomous gates (P14 inner-ring green, evaluator, §13 lexicographic guard) plus the §11.5 safety apparatus (account-aware survival/liquidation gate, sleeve caps, per-order size limit, **kill switch**) are now the *entire* defense between an LLM-authored change and the live levered book — there is no human backstop. ⟹ (a) those gates' rigor is load-bearing in a way it was not when a human stood behind them; (b) "no sign-off" removes the *per-promotion approval*, **not** the §11.5 kill switch (operator emergency halt stays); (c) full autonomy is safe in the paper/challenger phase, but before any *live real-money* cutover the gates + kill switch must be proven green (P14 + §11.5).
3. **Forward-window numeric policy — RESOLVED 2026-05-29: no trade-count floor** (research-confirmed; research doc). The min-N-closed-trades / survival-event frame is **replaced** by **PSR + MinTRL** — significance sized in *observation count* (skew/kurtosis-aware; a leveraged non-Normal book needs materially more OOS data, e.g. +54% in the literature's example), gated against a non-trivial benchmark Sharpe. There is no valid fixed trade-count floor. [Bailey & López de Prado]
4. **Aggregate cost ceiling** — RESOLVED 2026-05-29: **no aggregate cost cap / no ceiling** (operator decision). The existing per-`(run_id, agent)` $60 ceiling (`orchestrator_step`) remains the only cost control; T4's aggregate gap is **accepted, not closed** — a runaway tuning batch (or the in-session monitor cadence, §15) has no aggregate halt. Eyes-open risk-acceptance, consistent with the existing T4 tradeoff. (#1/#3/#5/#6 deferred to a deep-research pass before re-recommending.)
5. **Anchored/rolling split — RESOLVED 2026-05-29: adopt provisionally, validate** (research-confirmed; research doc). The split-memory design (anchored tail/risk, rolling edge/return) is theoretically defensible (window choice is first-order + regime-conditional) but has **no direct trading precedent** — all evidence is macro/volatility forecasting. Adopt as a hypothesis to validate on the book, not established practice; consider dynamic/recency-based window selection. **Cross-cutting:** prefer **CPCV** over a single walk-forward window as the validator (§14.6 may be amended) — walk-forward is the weakest OOS validator on overfitting metrics.
6. **Promotion criterion — RESOLVED 2026-05-29: DSR + PSR + PBO gate** (research-confirmed; research doc). The automated (no-sign-off, #2) gate = **Deflated Sharpe Ratio** (multiple-testing-corrected, **log effective N**) + **PSR/MinTRL** significance + a **PBO/CSCV** overfitting diagnostic, on the **survival-net risk-adjusted return** metric (§13); **never gate on in-sample Sharpe**; **MinBTL** caps parameter-search breadth (≤~45 independent configs at 5y); prefer CPCV over a single forward window. **Still operator-calibrated** (literature silent): the OOS *margin* over the incumbent, the *consecutive-window* count, and *anti-churn hysteresis* — set provisionally, calibrate empirically. This is also the §7-Q6 bar that converts §14 from exploration to a BUILD_LOG decision.

## 15. Promotion to committed build + §14.3 revision (operator-decided 2026-05-29)

**Commit.** The operator promoted §11–§14 from EXPLORATION to a **committed build**. Scope otherwise unchanged: still v0.1 **paper-only** until the §11.5 apparatus (account-aware survival gate, sleeve caps, per-order size limit, kill switch) is proven green (P14). **Not yet a `BUILD_LOG.md` entry** — per §1, decision-log promotion awaits outcome-scoping + the inner→outer-ring discipline; the record stays here until then.

**§14.3 revision — in-session LLM, with reason (not a silent overwrite).** §14.3 said "no LLM in-session, not even for anomalies." That is **overturned**: an LLM is now invoked on a **regular in-session cadence** to monitor how the model behaves, catch anomalies, and **stop → fix → resume** it. The original §14.3 rationale is preserved above and remains valid **for FITTING** — a multi-hour fit can't run in-session, so all *fitting* of new param/code values stays after-market under OOS discipline (§14.4). The reframe: **monitoring + intervention ≠ fitting** — the monitor loop is lightweight and can run periodically intra-session. Only two things are genuinely new — the **in-session cadence** and the **intervention authority**; the monitor half rides existing machinery (telemetry §14.8 is the substrate; calibration is already the named behavioral diagnostic §14.7).

**Design invariant (to honour when specced).** In-session LLM intervention must be expressed as **commands into the existing deterministic mechanisms** — kill switch (§11.5), reproducible safe-mode (§14.3), versioned-config-select (§14.5 / P2) — **never a new direct-mutation path**. One auditable halt path; the **deterministic reflex fires first** (Survive cannot block on an LLM round-trip); the LLM is the **slower deliberative second line** that catches subtler behavioral drift (e.g. calibration breakdown while still inside survival limits).

**Blast-radius note (operator, eyes-open).** This pushes LLM authority *into the live levered session*, and **stacks on §14.11 #2** (fully autonomous promotion, no human sign-off). Two expansions of LLM blast-radius into real money now compound: autonomous between-session promotion **and** autonomous in-session intervention. The §11.5 kill switch + deterministic survival gate remain the *entire* backstop — their rigor is correspondingly more load-bearing. Full in-session autonomy is acceptable in the paper/challenger phase; before any live real-money cutover the gates + kill switch must be proven green (P14 + §11.5).

**RESOLVED FORK — "fix" scope = operational + apply-pre-validated-config (operator 2026-05-29).** Of the three escalating readings, the operator chose **#2**: the in-session LLM may (a) halt / flatten / restart a wedged component and clear bad state (operational), **and** (b) select among already-validated param sets / tighten to a safer known version, then resume — but it may **NOT fit new values live** (#3 rejected; fitting stays after-market under §14.4 OOS discipline). For the record:
1. Operational only — halt / flatten / restart, clear bad state, resume. No param/model change.
2. **[CHOSEN] + apply a pre-validated config** — also select among validated param sets / tighten to a safer known version, then resume. No live fitting. (Respects §14.4.)
3. + live-fit new values — **REJECTED** (conflicts with §14.4 — no out-of-sample exists intra-session).

**Consequence — clean two-loop separation.** The after-market `walkforward-tuning-loop` *populates and validates* the config menu (fits new versions, OOS-gated); the in-session monitor *selects from that menu* (+ halt / tighten) and never fits. The shared seam is the **P2 param-version table** — one loop writes validated versions, the other pointer-flips among them (§14.5 atomic swap). **Spec topology (now decidable):** the in-session monitor is best a **distinct orchestration spec** — sibling to the tuning-loop, leaf-commanding the daemon via the existing kill-switch / safe-mode / versioned-config-select paths (P1) — but final placement is confirmed at discovery.

## 16. Risk-philosophy reconciliation — §11 CFD supersedes §2/L1 defined-risk instruments (operator-decided 2026-05-29)

**REVISITED 2026-05-29 (operator) — SUPERSEDED IN PART.** The bare "CFD supersedes defined-risk" decision below is now **provisional-for-paper**. Standing decision = **C-now / B-pre-live** (see §16.1): the reactive layer is **intraday-flat-by-close**, flat-before-closure is a **hard survival invariant**, and **defined-risk instruments (B) are the pre-live target** if the Gate User Agreement confirms no-GSLO/no-cap. The §11 vehicle + §11–§15 build are kept and specced; the instrument choice is re-opened at the pre-live gate. The tension and original option-A decision are preserved below as the record of why this was revisited.

**The tension.** §2/L1 (and §4 Build C) specified momentum participation via **instrument-level defined-risk** — spreads / LEAPs in the ≤8% `speculative_optionality` sleeve, where "structure absorbs framework error; a spread risks premium, cash+leverage risks principal." §11 then selected a **leveraged Gate TradFi CFD (4x/5x)** as the execution vehicle without reconciling against that stance. The 2026-05-29 deep-research sharpened it to a contradiction: a Gate CFD has **no negative-balance protection** ("lose more than your initial investment") — the opposite of defined-risk. The two stances were incompatible; §11's vehicle won silently.

**Decision (operator, option A) — PROVISIONAL, revisited at §16.1.** §11's leveraged-CFD vehicle **supersedes** §2/L1's defined-risk-instrument choice (for the paper phase only; defined-risk **B** is the pre-live target). Defined risk moves from **instrument-level** (spread payoff caps loss) to **account-level**:

> **Capitalize the Gate CFD account with at most the `speculative_optionality` sleeve's dollars (≤8% of book; §7-Q7 regime-scalable). The funded balance is the defined-risk envelope.**

- **Funding cap** = cross-account blast-radius bound (you cannot lose what you never wired to Gate).
- **`survival-gate`** = within-account discipline (50% margin-level stop-out, per-order size limit, kill switch).
- The ≤8% sleeve cap is enforced at **capitalization** — the right place given account-level cross-margin liquidation. (Folded into the `survival-gate` brief as a capitalization-level cap.)

**Accepted residual (eyes-open) — SHARPENED 2026-05-29.** Strictly weaker than a spread/LEAP, which is structurally gap-proof. Deep-research (`survival-gate/gap-through-stop-findings-2026-05-29.md`) confirmed the **gap-through-stop risk is real and the downside is effectively UNBOUNDED**: the 50% stop-out is non-guaranteed (fills at next-available bid/ask on a reopen gap), there is **no GSLO / no max-loss cap**, and leverage is fixed (not user-reducible). So a violent weekend/holiday/halt gap can drive the funded account **negative** (no-NBP) — losing **more than funded**, not "slightly more." The blast radius is therefore *funded sleeve in expectation, **plus an unbounded negative-balance tail** on a gap* — **not** structurally capped the way a spread is. Three mitigations make this acceptable for the ≤8% sleeve: (1) the **§16 funding cap** keeps expected loss ≈ the sleeve; (2) **time-based gap-event avoidance** (reduce/flatten before known closures); (3) the **ex-ante entry-exclusion stage** (name-specific forward gap-risk *base-rate* reduction, §12.2) — re-validated by this research as load-bearing, not optional (**absorbed into `survival-gate` as an entry-exclusion stage, not a standalone spec — §16.1**; the held-position **halt-while-holding behavior was subsequently removed** — real-time halt detection is out of boundary, `survival-gate` R7, operator 2026-05-29; that reopen-gap tail is bounded by the account-level margin monitor + stop-out + the funding cap, not a halt-specific response). **Pre-live gate:** retrieve the Gate User Agreement (403) to confirm/deny a GSLO + `fill_negative` mechanics, and confirm closed-session pricing + hours, before any real-money cutover. Paper/challenger phase is unaffected. **Standing response to this residual: §16.1 (C-now / B-pre-live).**

**Where this lives.** The Gate CFD reactive layer **is** the `speculative_optionality` sleeve run as a reactive decider (§12.4 "decider" = within this lane); the slow layer still governs the ~92% core+thematic book. §2/L1's "8% off-leash, slow-layer governs 92%" stands — only the instrument changed.

### 16.1 Revisit — C-now / B-pre-live, intraday-flat-by-close (operator-decided 2026-05-29)

**Why revisited.** The gap-through-stop deep-research sharpened option A's residual from "a small gap tail" to an **effectively unbounded negative-balance tail** (no-NBP + non-guaranteed stop + fixed leverage). Under §13 (Survive ⊳ Preserve ⊳ Edge ⊳ Return, **lexicographic** — never trade a higher link for any amount of a lower one), an unbounded **Survive** loss accepted to keep the CFD vehicle's leverage + universe (**Edge/Return**) is the one trade §13 forbids. So A as written is not "an eyes-open residual" — it is a §13 *relaxation*. The revisit asks which response restores §13.

**Survive-axis ordering (honest).** **B** (revert to defined-risk spreads/LEAPs) is the *only* **structurally** §13-compliant option — max loss = premium, fixed at entry, gap-proof *even if every system is down*. **C** (flat-before-closure survival invariant) *operationally* eliminates the *dominant* path (overnight/weekend/holiday closure gaps) — **procedural**, conditional on the flatten action reliably firing before every close, **not** structural the way B is. It leaves **two** gaps vs B: (i) a **bounded-but-nonzero** intraday-halt-reopen residual — and because a Gate CFD is a *synthetic* instrument (not the NMS stock), LULD bands / reopening auctions may not apply to it at all (the still-open closed-session-pricing item, §11.6); and (ii) an **execution-dependency** — a levered position rides overnight if the flatten doesn't run, precisely the catastrophe C exists to prevent. **A** keeps the full tail. So **B (structural) > C (procedural, two named gaps) > A (full residual)**; both A and C *relax* §13, by different amounts.

**Proportionality.** The finding is decision-grade but **MEDIUM-confidence** (MT5 + Bybit-comparable analogy, not a Gate-primary statement; the User Agreement that could reveal a GSLO/cap is behind a 403). The system is **paper-only** — the tail costs nothing until live cutover, which is **already gated** on retrieving that User Agreement. Discarding the §11–§15 build now (B-now) on analogy-grade evidence for a risk that does not bite in paper is disproportionate.

**Decision.** The reactive layer **can go to cash daily** (operator-confirmed 2026-05-29) ⟹ **C now**: **flat-before-closure becomes a hard `survival-gate` invariant** — no levered exposure held across any non-traded window; the gate **force-flattens before close**. This *operationally* eliminates the dominant closure-gap path (conditional on the flatten reliably firing — **procedural, not structural**); the standing residual is the named, bounded-but-nonzero intraday-halt case, handled ex-ante by survival-gate's **toggleable entry-exclusion stage** over existing screens (**no standalone spec**); **real-time halt detection of a held position is out of boundary** (operator 2026-05-29, `survival-gate` R7) — that reopen-gap residual is accepted, bounded by the account-level margin monitor + venue stop-out + §16 funding cap; see consequences. The §11 vehicle + §11–§15 build are **kept and specced**. **B is the pre-live target**: at the pre-live gate, retrieve the Gate User Agreement; **if it confirms no-GSLO / no-cap, flip the instrument to defined-risk (B) before any real money.** This converts A from "eyes-open accepted residual" into **"provisional-for-paper, pre-live-gated."**

**Standing §13 status (eyes-open).** Under C the system is in a **small, named, paper-only §13 relaxation** (intraday-halt-reopen tail), *not* compliance. Full compliance is **B**, reached at the pre-live gate (or sooner if the operator elects).

**Consequences.**
- **§12** — the *position lifecycle* is now **intraday-flat-by-close**; the "own survival clock" is intraday. The days-to-weeks framing now refers to the *prediction* horizon, re-expressed via **daily re-entry**, not an overnight hold. (Noted at §12 intro.)
- **`survival-gate`** — owns the flat-before-closure *invariant* (force-flatten ahead of any closure) and must **not assume the CFD vehicle survives the pre-live gate**. Per **P6**, the invariant cannot reduce to a bare daemon cron: the gate needs a **verifiable pre-close post-condition — *am I actually flat?* (not "I fired the order")** — plus a fallback if it isn't (re-fire / kill-switch / safe-mode). It also absorbs the **gap-risk filter** (operator 2026-05-29): **no standalone `gap-risk-veto-filter` spec is built** — the S&P-500 ∩ Gate-441 restriction (§11.3) removes the catastrophic base rate, leaving (a) a **toggleable ex-ante entry-exclusion stage inside this gate** consuming *existing* screens (`catalyst-scout` + quality gate), which preserves the §12.5 A/B without a new module, and (b) the irreducible held-position intraday-halt tail — **real-time halt detection is OUT of boundary** (operator 2026-05-29, `survival-gate` R7; no feed, broker confirmed not the source, `c79738f`): the gate has **no halt branch**; the reopen-gap residual is accepted, bounded only by the account-level margin monitor + venue stop-out + §16 funding cap (the halted leg is *exposed until reopen* — no within-account action closes it; this supersedes the prior alert-only halt-while-holding behavior). (Folded into its brief + requirements R7.)
- **`execution-daemon`** (fork's lane — *note only, not edited here*) — owns the timed flatten *action* the invariant requires. Cross-seam: **rule** (`survival-gate`) vs **trigger** (daemon) vs **verification** (`survival-gate` post-condition). A **broker-side resting/bracket exit or time-based auto-close** — *if* the MT5/CFD product supports it — would push C back toward *structural* (survives daemon death); worth the fork checking against `broker-cfd-adapter`.
- **`reactive-signal-model`** — the *prediction* horizon (right side over days-to-weeks) is unchanged; whether a days-to-weeks edge survives intraday-only expression (daily re-entry friction + forgone overnight drift) is an **outer-ring empirical question** (§12.5), not a redesign. Spec language to be *clarified*, not rewritten.
- **`broker-cfd-adapter`** — unchanged for the paper phase (still the CFD transport); a pre-live instrument swap, if triggered, introduces a defined-risk (options) adapter as a separate spec.
