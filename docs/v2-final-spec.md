# Component Specification v2: Two-Layer Investment Research System

**Status:** Design document, pre-implementation, frozen
**Version:** v2-final (consolidates v1 + delta + refinements + additions + correctness fixes)
**Scope:** Full system specification — agents, quantitative models, evaluation framework, infrastructure
**Target:** Real-money operation, small size, individual investor, US equities (taxable account), multi-month horizon
**Methodology:** Component-first. Each module is specified as a self-contained unit with explicit contracts.

---

## 0. System Architecture Overview

The system has two layers separated by time horizon, with a strict contract between them.

**Slow layer (Watchlist Layer)** decides *what to own*. LLM-agent driven, monthly refresh cadence with daily monitoring, conservative golden standard (quality compounder + one explicit AI-infrastructure carve-out). Outputs a ranked watchlist of 30–50 names with per-name conviction scores, target prices, and thesis documents.

**Fast layer (Execution Layer)** decides *when to act on what you own*. Quantitative model driven, daily refresh, technical and price-action signals applied only to watchlist names. Tax-aware. Outputs entry/exit/sizing recommendations.

**Cross-cutting layers:** Evaluation framework (process + outcome + counterfactual rubrics), Learning Loop (deferred to Phase 2), Infrastructure spine (data, storage, observability, safety rails, evidence index, cost controls).

**Contract:** The Execution Layer can only act on names the Watchlist Layer has approved. The Watchlist Layer cannot recommend entry timing or sizing. Neither layer trades; they produce recommendations that the human approves.

**Net agent count v1:** 6 LLM agents + LearningLoop deferred. Down from 10 in v1 spec.

---

## 1. Skills Layer (Agent Specifications)

### 1.1 MacroCycleAgent

**Purpose:** Single global cycle and macro view that modulates sizing aggressiveness across the system. Replaces v1's eleven SectorResearchAgents and separate MarketCycleAgent.

**Cadence:** Quarterly full update; monthly delta refresh; daily refresh on major regime indicators (yield curve inversion, VIX spike, credit spread widening).

**Inputs:**
- Equity market valuations (S&P 500 P/E, Shiller CAPE, equity risk premium)
- Credit spreads (HY OAS, IG OAS)
- Yield curve shape and changes
- VIX level and term structure
- Sentiment indicators (AAII bull/bear, NAAIM exposure, put/call ratios)
- IPO heat and SPAC issuance metrics
- Sector ETF performance (top-down view, not per-sector deep research)

**Outputs:**
- `cycle_score`: -3 (euphoric/expensive) to +3 (panic/cheap)
- `regime_classification`: euphoric / late-cycle / mid-cycle / early-cycle / panic
- `evidence_for_score`: cited indicators with current readings vs historical percentiles, evidence_id references to Evidence Index
- `aggressiveness_modifier`: multiplier (0.5–1.5) applied to size bands
- `regime_change_risk`: probability of regime shift in next 30 days

**Note on sector_tilts:** v1 spec included `sector_tilts` as an output, but no downstream component consumed it at watchlist sizes of 10–20 positions. Field dropped at v2 to avoid spec rot. Restore when watchlist exceeds the same threshold that activates per-sector specialists (>5 sectors with ≥3 names each); at that scale, PositionSizingModel applies a sector-tilt multiplier in the 0.8–1.2 range and PMSupervisor uses tilts as a soft tiebreaker between conviction-equivalent candidates.

**Success criteria (process):** Score discrimination over time; cited evidence with Evidence Index references.

**Success criteria (outcome):** Extreme scores (-3, +3) precede actual regime shifts; aggressiveness modifier improves risk-adjusted outcomes vs no modifier.

**Promotion to per-sector agents:** When watchlist exceeds 30 names with diverse sector exposure (>5 sectors with ≥3 names each), evaluate whether per-sector specialists add signal. Until then, this single agent suffices.

---

### 1.2 CompanyDeepDiveAgent

**Purpose:** Produces full investment memos for individual companies. Workhorse of the slow layer. Now includes inline failure_scenarios section (replaces v1's standalone PreMortemAgent).

**Cadence:** Triggered when MacroCycleAgent or screening surfaces a candidate; full re-underwrite quarterly per held name; ad-hoc on materiality escalation.

**Inputs:**
- All filings for the company (last 5 years, via edgartools)
- All earnings call transcripts (last 8 quarters)
- Analyst consensus estimates (current and revision history)
- Peer set comparables
- News and 8-Ks (last 90 days)
- Insider transaction history (last 12 months)
- Institutional ownership changes (last 4 quarters from 13F)
- Industry-specific addenda (see §1.2.5) when applicable
- MacroCycleAgent output for context

**Output structure (mandatory ordering):**

The CompanyDeepDive prompt enforces a specific authoring sequence to prevent rationalization. Sections are written in this order:

1. **`business_summary`** — 1-paragraph what-the-company-does
2. **`failure_scenarios`** (authored before thesis) — 3–5 specific 18-month scenarios where the position is down 40%+, with leading indicators and probabilities
3. **`thesis_pillars`** — 3–5 falsifiable claims with specific KPIs and target dates
4. **`variant_view`** — explicit divergence from sell-side consensus, quantified
5. **`valuation_model`** — DCF or normalized-EPS multiple with base/bull/bear cases
6. **`target_price`** — P50 estimate
7. **`confidence_distribution`** — P10/P50/P90 IRR over 3-year default horizon
8. **`catalysts`** — list with type, expected window, hard/soft classification
9. **`key_risks`** — 3–5 risks with severity scoring
10. **`recommended_action`** — ADD_TO_WATCHLIST / PASS / WATCH (default PASS)
11. **`recommended_size_band`** — % of portfolio range; not actual size
12. **`reviewable_predictions`** — minimum 3 predictions with explicit resolution dates
13. **`evidence_index_refs`** — list of all evidence_ids cited in this memo

**Why ordering matters:** Pre-mortems written *after* the BUY recommendation has been drafted are weaker than pre-mortems written *before*. Forcing failure_scenarios first prevents the inline pre-mortem from becoming a rationalization layer for an already-decided BUY. The model imagines failure before constructing the case for purchase.

**Success criteria (process):**
- Variant view differs from sell-side consensus on at least one quantifiable dimension
- Every numerical claim has an Evidence Index reference (mechanical check; see §4.2.5)
- Confidence distribution P10–P90 spans at least the company's annualized realized volatility × √horizon
- All thesis pillars are falsifiable with specific KPIs
- Failure_scenarios authored before thesis_pillars (verified by output structure)
- Minimum 3 reviewable_predictions with explicit resolution dates

**Success criteria (outcome):**
- Watchlist additions outperform sector-matched basket over 12/24-month horizons
- Reviewable predictions Brier-score better than naive baseline
- P50 target price closer to realized 12-month price than sell-side consensus on average
- Failure_scenarios capture actual failure modes when theses break

**Anti-patterns:**
- Variant view that's consensus dressed up
- Confidence distribution that narrows over rewrites
- Pressure-driven BUY recommendations (counter: PASS is the default)
- Failure scenarios that are three versions of the same risk
- Same-author motivated reasoning in failure_scenarios (compensated partly by BearCase running on different model — *see Path A override in BUILD_LOG.md Day 1*)

**If inline pre-mortem proves weak:** Track calibration of failure_scenarios vs realized outcomes. If the agent systematically underrepresents the failure modes that actually occur, extract PreMortem to a standalone agent on a different model family.

---

### 1.2.5 Industry-Specific Addenda

**Purpose:** Sector-aware ratio packs invoked by CompanyDeepDive when classification matches. Reference documents loaded contextually, not core agent prompts.

**Triggered by company classification:**
- **Banks/financials:** P/TBV, ROTCE, NIM, credit quality metrics, allowance ratios
- **REITs:** FFO/AFFO, occupancy trends, cap rates, NAV-based valuation
- **Biotech/pharma:** rNPV with phase-staged discount rates, patent cliff modeling
- **Insurance:** combined ratio, book value growth, float economics
- **Energy/commodities:** netback margins, production cost curves, reserve replacement
- **Software/SaaS:** rule of 40, NRR, magic number, billings vs revenue
- **Hardware/semis:** unit economics, capex cycle position, customer concentration

When company doesn't fit a defined category, defaults to standard equity ratios.

---

### 1.3 BearCaseAgent

**Purpose:** Adversarial peer to CompanyDeepDive. Produces strongest evidence-based case against every BUY recommendation. Reports independently to PMSupervisor.

**Deployment requirement (originally mandatory; see Path A override):**

The original v2-final mandate required BearCase to run on a different model family/provider than CompanyDeepDive, enforced at system startup by configuration check.

**v2 simplification on provider count:** Three-provider configurations are operationally heavier than the marginal contamination defense justifies. The mechanical Evidence Index check (§4.2.5) is invariant to model choice — that is the load-bearing defense. Model-family diversity provides incremental value for *semantic* checks. v2 default: require `Evaluator ≠ CompanyDeepDive`; allow `Evaluator = BearCase`.

**>>> Path A override (BUILD_LOG.md Day 1):** This deployment uses Path A — all agents run on Anthropic via Claude Code subagent infrastructure. The model-family diversity mandate is deliberately not enforced. Primary contamination defense (mechanical Evidence Index check, §4.2.5) remains the load-bearing protection. Reversibility documented in BUILD_LOG.md.

**Cadence:** Triggered on every CompanyDeepDive BUY output; re-runs on quarterly re-underwrite.

**Inputs:**
- Same raw inputs as CompanyDeepDive (filings, transcripts, news, insider, ownership)
- The CompanyDeepDive BUY memo
- Historical short reports on the company if available
- Short interest data
- Failed historical analogs database

**Outputs:**
- `bear_thesis`: 1-paragraph strongest counter-case
- `attacks_per_pillar`: for each thesis pillar, strongest evidence-based objection
- `unrebutted_concerns`: list of concerns the BUY memo did not address
- `valuation_attack`: where the valuation model is most fragile
- `historical_failure_analogs`: specific named companies with documented outcomes
- `bear_confidence`: 0–1
- `severity_assessment`: catastrophic / serious / manageable
- `evidence_index_refs`: all evidence_ids cited

**Success criteria:** Must identify at least one unrebutted concern; attacks must be evidence-based, not generic risks; historical analogs must be specific named companies; cannot use only the same source data the BUY memo uses.

**Success criteria (outcome):** BUY recommendations with high bear-confidence underperform; flagged unrebutted concerns materialize at higher rates than addressed concerns.

---

### 1.4 PMSupervisorAgent

**Purpose:** Synthesizes deep-dive memo + bear case + macro context into final watchlist decision. Owns conviction scoring and recommended size band. The "you" agent in the system.

**Cadence:** Triggered when CompanyDeepDive + BearCase both produced output for a candidate.

**Inputs:**
- CompanyDeepDive BUY memo
- BearCase dissent log
- Current watchlist composition (for portfolio fit)
- MacroCycleAgent assessment
- Historical calibration scores for contributing agents

**Outputs:**
- `final_decision`: ADD / REJECT / WATCH
- `final_conviction`: calibrated 0–1 score with conviction-haircut applied based on contributing agent calibration history
- `recommended_size_band`: % of portfolio range
- `dissent_acknowledgment`: explicit statement of which unrebutted concerns are accepted, and why
- `position_caveats`: conditions on the recommendation
- `reasoning_trace`: explicit walk-through of how inputs were weighted

**Routing:** Opus-class model (highest-stakes synthesis decision in the daily flow).

**Success criteria (process):**
- Decision rationale addresses every unrebutted concern from BearCase
- Conviction score is calibrated against contributing-agent histories
- Cannot ADD if unrebutted concerns are catastrophic without explicit override-with-justification

**Success criteria (outcome):**
- Calibration of final_conviction Brier-scored
- High-conviction adds outperform low-conviction adds
- High-conviction adds also have lower realized drawdowns

---

### 1.5 DailyMonitorAgent

**Purpose:** Slow layer's daily heartbeat. Reads everything that touched watchlist names or sectors in the last 24 hours; produces digest; flags materiality escalations. Now includes inline materiality classification (replaces v1's standalone MaterialityClassifierAgent).

**Cadence:** Daily, post-market close.

**Two-tier classification (cost optimization):**

- **Tier 1 (Haiku-class):** First-pass scoring of every news/filing item. Cheap, high-volume.
- **Tier 2 (Sonnet-class):** Auto-escalation. Anything Tier 1 scores ≥2 routes to Tier 2 for confirmation before being released as a final score.

This pattern bounds the cost of a Haiku miss on a real thesis-breaking event. False negatives at Tier 1 (missing a 3) are the most expensive error the slow layer can make; auto-escalation absorbs that risk.

**Outputs:**
- `daily_digest`: per-name summary (most are 1 line: "no material activity")
- `materiality_scores`: 0–3 per piece of new information, with mandatory written justification including for zeros
  - 0: noise / routine
  - 1: noteworthy but does not affect thesis
  - 2: thesis-relevant, requires monitoring (auto-escalated to Sonnet for confirmation)
  - 3: thesis-impacting, triggers re-underwrite (auto-escalated to Sonnet for confirmation)
- `escalations`: list of names where any score = 3
- `sector_level_observations`: cross-cutting observations
- `tier_2_escalations`: count and summary of Tier 1 → Tier 2 escalations for the day

**Success criteria (outcome):**
- Score-3 events: >70% actually require thesis revision
- Score-0 events: >95% do not require revision
- Tier 2 escalation accuracy: when Tier 1 scores ≥2 and Tier 2 confirms, outcomes validate the escalation

---

### 1.6 EvaluatorAgent

**Purpose:** Grades outputs of all other agents on process rubrics in real time. Synchronously enforced before output release downstream.

**Critical deployment requirement:**

Original v2: EvaluatorAgent runs on a **different model family** from CompanyDeepDive. May share a family with BearCase. The contamination defense must be invariant to which model runs the evaluator.

**>>> Path A override (BUILD_LOG.md Day 1):** All agents on Anthropic. The mechanical contamination defense (§4.2.5) is invariant to model choice and remains the load-bearing protection. The semantic-judgment value of model-family diversity is the loss accepted under Path A.

**Routing:** Sonnet-class for routine outputs; Opus-class for hard-gate decisions (CompanyDeepDive memos, PMSupervisor decisions).

**Hard gates (block output release):**
- CompanyDeepDive memo with no falsifiable predictions → returned for revision
- BearCase with no unrebutted concerns and no explicit acknowledgment → returned for revision
- Any agent output with claims missing Evidence Index references → returned for revision
- Any agent output where evidence_id references resolve to rows post-dating the claim → returned for revision (contamination defense)

**Why mechanical checks dominate semantic judgment:** Asking the Evaluator to *judge* whether a memo "looks memorized" is asking an LLM to detect its own failure mode — which it can't reliably do. The check is mechanical: every dated claim resolves to a real Evidence Index row that predates the claim's resolution date. This is invariant to which model runs the Evaluator. **This is what makes Path A defensible.**

---

### 1.7 LearningLoopAgent (DEFERRED to Phase 2)

**Status:** Deferred to Phase 2. Not built in v1.

**Phase 2 trigger:** ≥90 resolved predictions across all agents AND ≥10 closed positions with completed postmortems.

**v1 substitute:** Manual monthly review. Read calibration scores, counterfactual ledger summary, rubric-failure cases. Propose system changes manually.

**When activated:** Reads outcome database and counterfactual ledger only. **Has no access to process rubric scores as optimization features.** This boundary is enforced by code, not convention (§3.4).

---

## 2. Quantitative Models (Execution Layer)

### 2.1 PriceFeatureService

**Purpose:** Compute daily feature panel for every watchlist name. Substrate for all other quantitative models.

**Computed features per name per day (v2 simplified):**

*Trend & momentum (core):* 20/50/200-day SMAs and slopes; 12-1 momentum; distance from 52-week high; distance from 200-day SMA; ADX(14); MACD signal and histogram

*Volatility (core):* Realized volatility (10d, 30d, 90d annualized); ATR(14)

*Volume (core):* Volume z-score (20d baseline); VWAP deviation

*Relative strength (core):* vs S&P 500 (3m, 6m, 12m); vs sector ETF (3m, 6m, 12m)

*Position context:* Days held; current P&L (unrealized); drawdown from peak since entry; cost basis vs current price; **Tax holding period status** (days until 1-year long-term threshold)

**Dropped from v1:** Volatility-of-volatility, OBV slope, accumulation/distribution slope, Bollinger band width percentile, ATR percentile, pullback-to-support distance.

**Implementation:** Daily batch job, written to TimescaleDB. Pluggable data layer with fallback chain (§4.2.5).

---

### 2.2 EntryTimingModel

**Purpose:** Given a watchlist name with PMSupervisor approval and target size band, decide whether *now* is a reasonable entry. Multi-factor scoring, not ML.

**Factors and weights (v2 simplified to 4):**

| Factor | Weight | Rationale |
|---|---|---|
| Trend alignment (20/50/200 DMA stack) | 0.30 | Don't fight the long-term trend |
| Distance from 200-day SMA (not too extended) | 0.25 | Avoid parabolic entries |
| Volume confirmation on recent up-days | 0.20 | Accumulation vs distribution |
| Cycle modifier from MacroCycleAgent | 0.25 | Aggressive in panic, cautious in euphoria |

**Output per name per day:**
- `entry_quality_score`: 0–1
- `recommendation`: STRONG_ENTRY (>0.75) / ENTRY_OK (0.5–0.75) / WAIT (0.25–0.5) / DO_NOT_ENTER (<0.25)
- `factor_contributions`: explicit breakdown
- `invalidation_level`: price below which entry thesis is wrong
- `recommended_initial_size`: % of approved size band

**Critical constraint:** Never overrides PMSupervisor approval. Only operates within approved universe.

---

### 2.3 ExitSignalModel (Tax-Aware)

**Purpose:** Generate exit recommendations for held positions. Where most of the alpha lives — bad exit discipline destroys good entry decisions. Tax-aware.

**Exit triggers (any one fires):**

*Thesis-driven (slow layer) — HIGHEST PRIORITY, NEVER SUPPRESSED FOR TAX:*
- **PMSupervisor downgrades thesis** (materiality-3 escalation resolved as thesis-broken)
- **Thesis pillar fails its KPI test at scheduled review** ← *the highest-quality exit signal in the system*

When a falsifiable claim is falsified, the position exits regardless of price action or tax considerations. Capital protection beats tax optimization when the underwriting is wrong.

*Valuation-driven — TAX-AWARE:*
- Price exceeds CompanyDeepDive target_price by >20%
- Forward P/E exceeds 75th percentile of name's 10-year history

*Technical (price-action driven) — TAX-AWARE:*
- Break below 200-day SMA on volume
- Trend structure change (lower highs and lower lows, 3+ weeks)
- Distribution pattern detected (rising price, falling OBV)

*Risk-driven — TAX-AWARE:*
- Drawdown from entry exceeds invalidation level set at entry
- Position size grown beyond max band due to appreciation (trim to band)
- Correlation with other holdings exceeds threshold

*Time-driven — TAX-AWARE:*
- Position held >24 months without thesis re-validation
- Position has stagnated (within ±10% of entry) for >18 months while opportunity cost rising

**Tax-awareness logic:**

```
if position.days_held < 365 and trigger != THESIS_BROKEN:
    days_to_lt_threshold = 365 - position.days_held
    tax_cost = position.unrealized_gain × (st_rate - lt_rate)

    if days_to_lt_threshold < 60 and conviction > 0.4:
        # Approaching 1-year mark with intact conviction; suppress non-thesis exits
        action = WAIT_FOR_LT_THRESHOLD
    elif tax_cost > 0.25 × position.unrealized_gain:
        # Tax bill exceeds a quarter of the gain; suppress unless thesis-broken
        # Static threshold; tunable via calibration data over time
        action = HOLD
    else:
        action = original_signal
```

**Tax-loss harvesting:**

Positions down >15% with stable thesis are candidates for harvest-and-rebuy. Cadence: monthly sub-routine.

**IRS wash-sale compliance (correctness-critical):**

The IRS wash-sale rule disallows the loss if the same or "substantially identical" security is purchased within **30 days before *and* after** the loss sale — a 61-day total window. "Substantially identical" includes:
- The same security
- Single-stock options on the same underlying
- ETFs tracking the same index (SPY → VOO does not escape; both track S&P 500)

The harvest-and-rebuy sub-routine has three legitimate paths:

1. **Cash gap path:** Sell, hold cash, rebuy after the 30-day post-sale window closes.
2. **Non-substantially-identical proxy path:** Rotate into a proxy that has documented divergence from the loss security.
3. **Disclosure path (rare):** Operator chooses to take a substantially-identical position anyway. The recommendation must explicitly disclose the wash-sale risk; the harvested loss is at risk of being disallowed.

**Output per held position per day:**
- `exit_signal`: NONE / TRIM / FULL_EXIT / WAIT_FOR_LT_THRESHOLD
- `triggered_reasons`: list of specific triggers
- `urgency`: routine / elevated / urgent
- `proposed_action`: specific size to trim, target price for exit if not urgent
- `tax_cost_estimate`: dollar estimate of tax cost if executed today vs after LT threshold
- `reasoning_trace`: which signal weighed most

---

### 2.4 PositionSizingModel

**Methodology:** Calibration-driven Kelly with cycle, correlation, and volatility-management adjustments.

**Algorithm:**

```
expected_edge = (P50_target_price / current_price - 1) - risk_free_rate
estimated_variance = realized_vol_60d^2  # annualized
kelly_full = expected_edge / estimated_variance

# Calibration-driven Kelly fraction
# Default starting fraction: 0.25 (quarter-Kelly)
# Adjusted by Brier trend over rolling 90-day window
# Minimum 30 resolved predictions per agent before any adjustment
kelly_fraction = compute_kelly_fraction(
    base = 0.25,
    floor = 0.125,
    ceiling = 0.50,
    agent_calibration_history = last_90_days,
    min_sample = 30
)

# Cycle modifier (from MacroCycleAgent)
cycle_mod = aggressiveness_modifier  # 0.5 in euphoria, 1.5 in panic

# Volatility-managed sizing (Moreira & Muir 2017)
vol_target = 20%  # annualized portfolio vol target
vol_mod = min(1.0, vol_target / realized_vol_60d)

# Correlation adjustment
correlation_mod = 1 / sqrt(1 + sum_of_correlations_with_existing_positions)

# Combine
suggested_weight = kelly_full × kelly_fraction × cycle_mod × vol_mod × correlation_mod

# Bound by approved size band
final_weight = clip(suggested_weight, size_band_min, size_band_max)

# Apply hard concentration limits
final_weight = min(final_weight, single_name_cap)
```

**Quarter-Kelly is a defensible practitioner heuristic with weaker theoretical grounding than the algorithm implies.** Calibration data drives the actual fraction over time within the floor/ceiling bounds.

**Hard limits:**
- Single name: max 8% of portfolio
- Single sector: max 35% of portfolio
- Top 5 positions: max 50% of portfolio
- Cash floor: min 5%
- Cash ceiling: max 30%

---

### 2.5 PortfolioRiskModel

**Metrics computed daily (v2 simplified):**
- Gross/net exposure
- Sector concentration
- Style factor exposure
- Correlation matrix and portfolio-level expected volatility
- Maximum drawdown from peak

**Dropped from v1 for v1 deployment:**
- Parametric VaR
- Four-scenario stress tests

These are retained in code as optional but not in default v1 daily run. Activate when portfolio scales beyond 30 positions or when leverage is introduced.

**Alert triggers:**
- Gross exposure exceeds 100%
- Sector concentration breach (>35%)
- Drawdown exceeds 15% from peak: defensive review
- Drawdown exceeds 25%: hard review
- Correlation cluster forms (3+ positions with correlation >0.8)

---

### 2.6 BacktestingFramework

**Critical requirements:**

*Point-in-time data:* Sharadar Core Fundamentals via Nasdaq Data Link as primary source for survivorship-bias-free fundamentals with proper delistings.

*Walk-forward validation:* Period-out only. Embargo period between train and test (Lopez de Prado).

*Knowledge-cutoff handling (contamination defense):*
- `effective_cutoff = stated_model_cutoff + 6 months` as conservative buffer
- Models continue absorbing information through ongoing pretraining and RLHF data refreshes after stated cutoff (Lopez-Lira et al. 2025)
- Every backtest reports performance separately for pre-effective-cutoff and post-effective-cutoff periods; degradation between periods flagged if >20%

*Realistic frictions:* Bid-ask spread per liquidity tier; market impact for orders >1% ADV; commission and SEC fees; tax cost modeling.

*Multiple-trial correction:* DSR with explicit reporting of trials/parameter combinations; PBO; document every parameter choice.

*Counterfactual baselines required:* SPY buy-and-hold; equal-weight watchlist; sector-matched basket; 60/40.

*Deferred:* Combinatorial Purged CV — heavy for monthly rebalancing; "do it once you have a strategy worth defending."

**Implementation:** Build on `vectorbt`; thin wrapper enforces above discipline.

---

## 3. Evaluation Framework

### 3.1 Process Rubrics

**Universal process rubric (all LLM agents):**

| Criterion | Description |
|---|---|
| Falsifiability | Are claims testable? |
| Source grounding | Every numerical claim has Evidence Index reference |
| Evidence-timestamping | Source dates surfaced AND validated mechanically |
| Calibrated uncertainty | Confidence ranges honest (volatility floor) |
| Reasoning transparency | Logic followable |
| Counter-evidence acknowledgment | Contrary points addressed |

**Hard gates:** Documented in §1.6.

---

### 3.2 Outcome Rubrics

*Per prediction:* Brier score, absolute error, direction accuracy

*Per closed position:* Realized return vs SPY/sector, max drawdown, holding period, **after-tax return**, thesis status at exit

*Per agent over rolling windows:* Calibration curve, AUC, hit rate, slugging rate, drift trend

**Resolution discipline:** Every prediction has scheduled resolution date. On that date, resolution job runs unconditionally.

---

### 3.3 Counterfactual Ledger

**Logged for every action:**
- WatchlistAdd → SPY return from add date forward
- EntrySignal → "what if DCA from same date"
- ExitSignal → "what if held instead" (including after-tax comparison)
- Pass → "what if bought despite the pass"
- Trim → "what if not trimmed"

**Critical use:** The system's escape from self-deception. Excellent process scores plus poor counterfactual performance = sophisticated theater.

---

### 3.4 The Optimization Boundary

**Strict architectural rule:** LearningLoop optimizes against outcome rubrics and counterfactual results only. Process rubrics are guard-rails enforced at output time, not optimization targets.

Enforced by code: LearningLoop's training data sources programmatically exclude process rubric scores.

---

### 3.5 Rubric Review (Annual)

Rubric changes require holdout validation. Previous rubric is baseline; new rubric must demonstrably better predict outcomes on holdout.

---

## 4. Infrastructure Spine

### 4.1 Data Layer

**Time-series storage:** TimescaleDB (Postgres extension)
**Document storage:** PostgreSQL JSONB for memos, dissent logs, daily digests (versioned)
**Cold archive:** Local disk + optional S3
**Secrets:** Environment variables; never committed

---

### 4.2 Data Sources (Primary)

| Source | Use | Cost |
|---|---|---|
| SEC EDGAR (via `edgartools`) | All filings | Free |
| FRED (via `fredapi`) | Macro indicators | Free with key |
| **Sharadar Core Fundamentals** (Nasdaq Data Link) | **Point-in-time fundamentals with delistings** | **$50–$150/mo** |
| Polygon.io | Prices, news | $29–$199/mo |
| yfinance | Backup/cross-check | Free |
| OpenInsider | Insider transactions | Free |
| Benzinga (basic tier) | News with ticker tagging | Low cost |
| FinViz | Sector ETF and peer mapping | Free |

---

### 4.2.5 Pluggable Data Layer + Evidence Index

**Pluggable data adapter pattern:**

Functions like `fetch_prices(ticker)` try providers in fallback chain:
- Polygon → Finnhub → yfinance → Stooq for prices
- Sharadar → FMP → Polygon for fundamentals
- Benzinga → Polygon news → NewsAPI for news
- edgartools (direct EDGAR) for filings

**Evidence Index (load-bearing):**

**Schema:**
```
evidence_id          : UUID, primary key
agent_id             : which agent made the claim
agent_run_id         : which run/output it appeared in
claim_text           : the actual claim
claim_type           : numerical, qualitative, prediction, dated_fact
source_uri           : URL or document reference
source_date          : date of source document
source_quality_tier  : 1=primary filing/regulatory, 2=company IR/transcript,
                       3=sell-side/established financial press, 4=retail/blog
surfaced_date        : when the agent made the claim
related_position_id  : optional FK to position
related_thesis_id    : optional FK to thesis
created_at           : write timestamp
storage_tier         : hot / warm / cold
```

**Definition of "claim" (mandatory population rule):**

> Any sentence containing a numerical value, a date, or a specific named fact about a company beyond identity must populate an Evidence Index row.

Examples requiring rows: "ROIC of 18% over the last 5 years"; "Revenue grew 23% YoY in Q3 2024"; "The company filed an 8-K on March 15, 2024".

Examples not requiring rows: "The company has a strong competitive moat"; "Management has a track record of disciplined capital allocation".

**Three downstream consumers:**
1. **Citation rubric:** every numerical claim must reference an evidence_id; mechanical check
2. **Contamination defense:** source_date must predate claim resolution date; mechanical check
3. **Postmortem traceability:** when thesis is wrong, query "what was the evidence base"

**Mandatory write hook in agent harness:** every claim auto-populates an Evidence Index row before output release.

**Retention policy:**
- Active watchlist names: hot tier, full retention
- Closed positions: hot tier for 4 quarters post-close, then warm
- Cold (object storage) after 8 quarters
- Append-only — no deletions or updates

---

### 4.3 Agent Harness

Originally specified as LangGraph-based. **>>> Path A override (BUILD_LOG.md Day 1):** Agent harness is implemented as Python wrappers around Claude Code subagent infrastructure (Task tool invocation, .claude/agents/ definitions). The standardized interface, Evidence Index write hook, mechanical contamination check, process-rubric grading hook, and versioned prompts are preserved; the substrate changes from LangGraph to Claude Code.

The model-family configuration check at startup is replaced with the Path A override acknowledgment.

---

### 4.4 Orchestration

**Daily heartbeat (cron at market close + 30 min):**
- PriceFeatureService
- DailyMonitorAgent (Tier 1 → Tier 2 escalation)
- ExitSignalModel (with tax-awareness)
- PortfolioRiskModel
- Resolves predictions due today
- Updates calibration scores
- **Brokerage reconciliation (close + 1 hour)** — see §4.5

**Weekly:** MacroCycleAgent delta refresh
**Monthly:** MacroCycleAgent full update; manual review (LearningLoop substitute in Phase 1); tax-loss harvest scan
**Quarterly:** MacroCycleAgent full structural; per-name re-underwrite
**On-demand:** CompanyDeepDive triggered by candidates; BearCase triggered by deep-dive output

---

### 4.5 Safety Rails (Real Money)

**Trade execution safety:**
- All trade recommendations require explicit human approval
- No automated trading API authority granted to any agent
- Daily summary of pending recommendations sent for review
- Hard kill switch

**Brokerage reconciliation protocol:**
- *Cadence:* market close + 1 hour
- *Trigger threshold:* any share count mismatch OR position-value drift >0.5%
- *Corporate actions:* dividends, splits, spinoffs, mergers go through manual confirmation queue
- *Failure procedure:* reconciliation failure → system enters READ_ONLY_MODE; ExecutionLayer paused until manual reconciliation completes

**Drawdown safety:**
- 15% portfolio drawdown: defensive review (manual) within 48 hours
- 25% portfolio drawdown: hard halt
- Single position 35% drawdown: mandatory thesis re-underwrite

**Calibration safety:**
- Overall system calibration degrading two consecutive months → alert and pause prompt revisions

**Mega-cap contamination acknowledgment:**
- Contamination problem is non-uniform — worse for liquid mega-caps than mid-caps
- v2 default: maintain uniform defenses; apply additional rubric scrutiny to top-50 names
- Mega-cap CompanyDeepDive memos require minimum citation density above universe baseline

---

### 4.6 Observability

**Dashboards (Streamlit):** daily monitor digest, materiality escalations, exit signals (with tax cost), entry opportunities, portfolio P&L (pre-tax and after-tax), calibration curves, counterfactual P&L, predictions due, Evidence Index claim lookup.

**Alerts:** Slack/Discord webhooks for materiality-3 escalations, exit signals, risk limit breaches, reconciliation failures.

---

### 4.7 Cost Model and Tiered Routing

**Monthly inference budget cap:** $400/month. Auto-escalation alert at $500/month. Hard cap at $600/month halts non-essential agent runs.

**Honest cost estimate:** $275–520/mo realistic for 30–40 name watchlist with prompt caching and tiered routing.

**Routing tiers (under Path A — all Anthropic):**

| Agent / Task | Tier |
|---|---|
| DailyMonitor Tier 1 | Haiku |
| DailyMonitor Tier 2 | Sonnet |
| EvaluatorAgent (routine) | Sonnet |
| EvaluatorAgent (hard-gate) | Opus |
| CompanyDeepDive | Sonnet |
| BearCase | Sonnet |
| PMSupervisor | Opus |
| MacroCycleAgent (quarterly) | Opus |
| MacroCycleAgent (monthly delta) | Sonnet |

**Prompt caching:** Filings, transcripts, prior memos cached; only delta and prompt change per invocation.

**Provider training-data policy:**
- Anthropic API: zero-retention default; verified at provider_verification/anthropic.md
- System refuses to run if any configured provider does not have training-disabled status confirmed at startup

---

## 5. Component Dependencies

```
PriceFeatureService ─── (foundation)
        │
        ├──→ EntryTimingModel
        ├──→ ExitSignalModel (tax-aware)
        ├──→ PortfolioRiskModel
        └──→ BacktestingFramework

MacroCycleAgent ─── (independent; modulates sizing)

CompanyDeepDiveAgent ─── (depends on data layer + agent harness + Evidence Index)
                │ (with inline failure_scenarios)
                │
                ├──→ BearCaseAgent (parallel; same family under Path A override)
                │
                └──→ PMSupervisorAgent (joins both)
                        │
                        └──→ Watchlist (the contract surface)
                                │
                                ├──→ EntryTimingModel
                                ├──→ ExitSignalModel
                                ├──→ PositionSizingModel
                                └──→ DailyMonitorAgent

DailyMonitorAgent ─── (depends on Watchlist; inline materiality classification)
        │ (Tier 1 Haiku → Tier 2 Sonnet auto-escalation)
        │
        └──→ (escalations trigger CompanyDeepDive re-underwrite)

EvaluatorAgent ─── (graded surface; same family as CDD/BC under Path A)
        │
        └──→ (mechanical Evidence Index validation; semantic process rubric)

LearningLoopAgent ─── DEFERRED to Phase 2
        (gated on ≥90 resolved predictions + ≥10 closed positions)
```

---

## 6. Build Order Considerations

- Data infrastructure + Evidence Index + PriceFeatureService come first
- BacktestingFramework before any quant model is trusted
- Watchlist contract must be defined before Execution Layer can be tested
- Eval framework (with mechanical contamination check) exists from day one
- LearningLoop deferred to Phase 2
- Real-money operation only after backtest validation + safety rails are validated

See `phasing-plan.md` and `implementation-sequencing.md` for the actual build sequence.

---

## 7. Failure Modes Specifically Addressed

**Memorization / look-ahead bias:** Mechanical Evidence Index validation; pre-cutoff vs post-cutoff backtest split with 6-month buffer; mega-cap-specific citation density.

**Sycophantic agents:** EvaluatorAgent process rubrics enforced as hard gates; BearCase reporting independently to PMSupervisor. **Note: model-family diversity defense lost under Path A; mechanical check is now the load-bearing protection.**

**Optimization on wrong objective:** Strict separation of process and outcome rubrics; LearningLoop has zero access to process scores.

**Confirmation bias:** Mandatory adversarial BearCase; explicit dissent preservation; counterfactual ledger; ordered prompt structure forcing failure_scenarios before thesis_pillars.

**Same-author rationalization in inline pre-mortem:** Prompt-ordering enforcement. Tracked as risk; PreMortem can be extracted to standalone agent if calibration shows weakness.

**View instability under news pressure:** DailyMonitor materiality classification; gate to action is materiality-3 escalation; Tier 2 auto-escalation absorbs Tier 1 false-negative risk.

**False precision:** Mandatory P10/P50/P90 ranges with realized-volatility honesty floor.

**Survivorship bias in backtests:** Sharadar point-in-time fundamentals.

**Look-ahead bias (data):** Timestamp-everything discipline; embargo periods; Evidence Index source_dates.

**Sophisticated theater:** Counterfactual ledger; if system loses to SPY on risk-adjusted basis, design is wrong regardless of how good memos look.

**Tax drag:** Tax-aware ExitSignalModel; non-thesis exits suppressed near 1-year LT threshold; thesis-broken exits override correctly; tax-loss harvesting sub-routine with wash-sale path enforcement.

**Brokerage drift:** Concrete reconciliation protocol; READ_ONLY_MODE on failure.

**Contaminated evaluator:** Mechanical (not semantic) contamination checks via Evidence Index validation. Invariant to model choice — what makes Path A defensible.

**Inference cost runaway:** Tiered routing; prompt caching; monthly budget cap with auto-alert; hard cap halts non-essential runs.

**Calibration whipsaw on small samples:** Minimum 30 resolved predictions per agent before Kelly fraction adjustment; trend over rolling 90-day window.

**Sunk-cost commitment:** Pre-committed evaluation question at month 18 — see phasing-plan.md §5.4.

**Real-money operation risk:** Hard human-approval gate; concentration limits enforced at database level; daily reconciliation; kill switch; READ_ONLY_MODE on reconciliation failure.

---

## 8. What This Document Is Not

- A phasing/timeline plan — see `phasing-plan.md`
- An implementation sequencing plan — see `implementation-sequencing.md`
- A code implementation
- A complete prompt library
- A trading strategy
- An alpha guarantee

When ready to build, start with Infrastructure Spine (§4) including Evidence Index, PriceFeatureService, and reconciliation protocol before any agent. Phasing per `phasing-plan.md`.

---

## Path A summary (deployment-specific deviation from canonical v2-final)

This deployment of v2-final uses Path A, documented in BUILD_LOG.md Day 1:

- All agents (CompanyDeepDive, BearCase, MacroCycle, PMSupervisor, DailyMonitor, Evaluator) run on Anthropic via Claude Code subagent infrastructure
- v2-final §1.3 model-family diversity for BearCase is deliberately not enforced
- v2-final §4.3 LangGraph harness is replaced by Claude Code subagent wrappers
- The startup model-family configuration check is replaced with the documented override

**Load-bearing protection that remains intact:** mechanical Evidence Index check (§4.2.5), invariant to model choice. This is the contamination defense that makes Path A defensible.

**Reversibility:** if Checkpoint 3 post-cutoff degradation >20%, Path A is the first override to reconsider. Restoring §1.3 means routing BearCase through OpenAI or Google API directly, bypassing Claude Code for that one agent.
