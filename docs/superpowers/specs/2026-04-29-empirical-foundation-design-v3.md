# Empirical Foundation Design — v3.0

**Date:** 2026-04-29
**Status:** v3.0 FROZEN — operator sign-off attested 2026-04-29T16:57:06+09:00
**Sign-off attestation:** `docs/superpowers/specs/v3.0-signoff-attestation.md`
**Phases completed:**
- ✓ Phase 1: consolidation draft from Sections 1-8 consensus
- ✓ Phase 2: cross-section gap-detection sweep (19 findings; resolutions in Section 8 Phase 4 Q1, Q4, Q9)
- ✓ Phase 3: parallel adversarial review (bear-case agent; 5 P0 + 6 P1 + 4 P2 findings; resolutions in Section 8 Phase 4 Q2, Q3, Q5-Q8)
- ✓ Phase 4: operator review + 9 reconciling decisions integrated into spec body
- ✓ Sign-off: operator typed `/spec-approve v3.0` in conversation transcript; manual attestation logged (slash-command implementation deferred to v0.1 build)
**Mutability:** v3.0 immutable. Subsequent revisions tracked as v3.1+ with explicit change-log per Section 8 PB#1.

**Supersedes:** `2026-04-26-empirical-foundation-design.md` (v2-final, preserved as historical reference)
**Authoritative for:** v0.1 implementation. Engineering reads from this document.

This document consolidates Sections 1-8 consensus locks (~64 architectural decisions) + Phase 4 reconciling decisions (9 additional locks resolving cross-section gaps surfaced by Phase 2 + Phase 3 reviews). Full provenance for any decision lives in `docs/section-N-consensus.md` per section.

---

## Section 1 — Operating Context

### 1.1 Operator profile

| Attribute | Value | Implication |
|---|---|---|
| Portfolio size | <$1M (individual investor) | Big-firm tooling structurally unaffordable. Cost-conscious design. |
| Goal | Mix of (B) "beat market by 2-4%" + (C) "find multi-baggers in pursuit of 3-5x outcomes" | Two-mode operation; PASS-default discipline mis-tuned for C; mode-aware discipline required. |
| Background | Engineering (zero finance prior to library) | Domain knowledge explicit, not assumed. Engineering analogies welcome. |
| LLM API budget | Covered by Claude Code Max (20× usage) | LLM cost not a constraint dimension. |
| Other tooling | Up to $250/mo | Sharadar fundamentals + Tiingo Power feasible. |

### 1.2 The bet

> **At <$1M scale with a B+C goal mix, structural discipline + smart-money tracking + mode-aware default with active ledger feedback > raw input-volume disadvantage.**

Decomposed:
- **Structural discipline** = mode-aware PASS-default + 5-style debate (Phase A→B→C→D) + active counterfactual ledger with quarterly review authority + mode-tagged outcomes + Evaluator hard-gates outside the debate
- **Smart-money tracking** = L7's Tier-A signals only (opportunistic insider clusters; drawdown-period institutional accumulation; 13G new-5%-holder; activist 13D from curated roster). Folklore signals (rally-period 13F replication, CNBC options-flow, unfiltered whale-watching) discarded
- **Mode-aware default with active ledger feedback** = B-mode strict + B' moderate + C minimum-tightness; relative-to-benchmark drawdown auto-tightens; quarterly operator review with parameter-recalibration authority (system proposes, operator approves)
- **Raw input-volume disadvantage** = no Bloomberg, no expert networks, no alt-data, no 24/7 macro team — accepted gaps

### 1.3 Falsifiability test

Mode-conditional:

| Mode | Test | Trigger to abandon mode |
|---|---|---|
| B | Specific missed 5x+ winners due to PASS-default | 3+ such cases in 12 months → discipline too conservative |
| C | Net same as S&P 500 over 18 months | Wasted time; pivot strategy or just index that portion |

### 1.4 System scope (operator-locked)

The system does NOT execute trades. The operator manually executes based on system output. System goal: **facilitate data aggregation + automate complex decision model using LLM and code; surface results to operator.** Default operator-facing view: clean recommendation. Audit chain available on request, not surfaced by default. Per-name decision augmentation only — portfolio-level concerns (concentration, sector exposure, mode-mix balance, correlation) are out of scope; aggregation across names is operator's job.

---

## Section 2 — System Architecture

### 2.1 Funnel composition

**4 always-on sidecars** (S3 tax-bucket removed in Section 2):

| Sidecar | Source | Provides |
|---|---|---|
| S0 | L1 regime capture | 6-dimension regime classification + BOCPD shift probability |
| S1 | Calibration history | Brier-trend per agent (rolling 90d); applied as conviction haircut at v0.5+ |
| S2 | Counterfactual ledger | Every PASS/exit/trim baseline-tracked, mode-tagged |
| S4 | L7 smart-money | Insider-cluster / drawdown-accumulation / 13G filings — fires events |

**9 phases (linear with explicit loop-backs):**

```
P1 trend capture
  ↓
P2 scenario writing (2-4 scenarios per theme)
  ↓
P3 name discovery (3-stage hybrid scorer)
  ↓
P4 deep dive (5-style debate Phase A→B→C-conditional→D)
  ↓
P5 watchlist add (research artifact — NO portfolio cap)
  ↓
P6 disposition determination (mode + horizon)
  ↓
P7 entry execution → recommendation output
  ↓
P8 daily refresh (loop)
  ↓
P9 exit
```

**Watchlist (P5) ≠ Portfolio.** Watchlist is research artifact (curated approved-to-buy names with conviction + size bands + kill criteria). Portfolio is real-money positions. 5% per-name cap applies at P7 only (price-appreciation exemption: positions growing past 5% via gains not force-trimmed).

### 2.2 Three-mode model

| Mode | Definition | Examples | Discipline priority |
|---|---|---|---|
| **B** (steady compounder) | Established quality, durable moat, 5-12% growth, 15-25% vol, FCF-driven | KO, COST, V, MA, BRK, MCO | Valuation + downside protection + moat durability |
| **B'** (growth compounder) | Profitable, growth is the bet, 25-50% vol, multi-decade compounder potential | NVDA, AMD, GOOGL, MSFT, META | Growth-rate sustainability + moat extension + valuation conditional on growth |
| **C** (thematic) | Pre-revenue/pre-profit, narrative-driven, >50% vol, can fail to ~zero | RKLB, IONQ, PLTR-pre-2024, COIN | Growth + tech moat + can-take-loss + narrative reflexivity |

**Mode classification — LAYERED ARCHITECTURE (per Phase 4 Q1 reconciling S1 + S7 PB#3):**

```
Stage 1 — Market-structural filter (Section 1 Item 1; establishes B/B'/C bin):
  IF market_cap > $50B AND vol < 25% AND profitable >5y AND growth < 12% → bin: B
  IF market_cap > $50B AND profitable AND (vol > 25% OR growth > 15%) → bin: B'
  IF market_cap < $50B OR not_yet_profitable OR narrative-driven → bin: C

Stage 2 — Company-quality refinement (Section 7 PB#3 criteria; flag within bin):
  HIGH-quality flag if (founder ≥10yr tenure if B, ≥5yr if B') AND (ROIIC > 15% sustained 5yr if B) AND profitability-path-clear
  STANDARD flag otherwise

Stage 3 — Overlap detection + LLM tie-breaker (per Section 7 PB#3):
  IF candidate hits >1 bin OR fails all 3 → LLM tie-breaker
  Single-attribute LLM call (Sonnet/Opus per Section 6 Q1)
  Forced JSON: {bin, confidence, rationale, evidence_quotes}
  Verbatim evidence required (no quote → defaults to most-conservative C)
  Self-consistency N=5 samples at temp=0.7
```

**Mode (B/B'/C bin)** drives sizing band, cadence, cut threshold, capitulation cooling-off, primary horizon view.
**Company-quality flag (HIGH/STANDARD)** is a CONVICTION MULTIPLIER input — HIGH-quality compounders within the same mode deserve higher conviction.

**Mode silent-failure detection (per Phase 4 Q5):**
- **Per-name quarterly re-classification:** runs Stage 1 against current data; mismatch with stored mode → operator review + pre-mortem before reclassification (Section 6 Q4 trigger 4)
- **Mode-implied-vol check (semi-annual):** computes 252d realized vol; >2σ outside mode band per Section 2.2 (B <25%, B' 25-50%, C >50%) for 2 consecutive checks → flag
- **Launch gate:** 100% of watchlist names mode-confirmed by operator (replaces "first 10")
- **Mode-fit dashboard** integrated into `/disposition`: per-row `mode | realized_252d_vol | last_confirmed_date | flag_status`

**Single-mode-per-name watchlist data model.** Watchlist row keyed by ticker; mode is a column. Same name cannot have two modes simultaneously. Reclassification triggers Section 6 Q4 pre-mortem mandatory before commit.

**Mode-specific discipline:**

| Knob | B | B' | C |
|---|---|---|---|
| Conviction threshold | ≥0.7 | ≥0.6 | ≥0.5 |
| Thesis pillars | 5 KPIs + valuation anchor | 4 KPIs + growth-sustainability | 3 KPIs (valuation can be optionality) |
| Variant-view requirement | Mandatory | Mandatory if covered | Optional |
| Bear non-negotiables | All addressed (no relaxation across modes) | All addressed | All addressed |
| Sizing band | 2-5% | 1.5-4% | 0.5-2% |

**Drawdown auto-tighten (relative-to-benchmark, NOT absolute):**

| Mode | Auto-tighten trigger | Tighten action | Catastrophic absolute halt |
|---|---|---|---|
| B | B-book underperforms S&P 500 by 5pp in rolling Q | Conviction +0.05; sizing ceiling -1pp | B-book down -25% → halt + full review |
| B' | B'-book underperforms QQQ by 7pp | Conviction +0.05; sizing ceiling -1pp | B'-book down -35% → halt + full review |
| C | C-book underperforms IWO/ARKK by 10pp | Conviction +0.05; sizing ceiling -0.5pp | C-book down -50% → halt + full review |

### 2.3 Five-style debate architecture

5 styles (per L8 research, replaces bull/bear binary):

1. **Value** (Buffett, Klarman, Marks, Tepper)
2. **Growth** (Druckenmiller-long-equities, Tiger, Coatue, Baillie Gifford)
3. **Quality / Moat** (Mauboussin, Munger, GMO, Terry Smith)
4. **Macro / Regime** (Bridgewater, Druckenmiller, Soros)
5. **Quant / Technical** (AQR, CTA-systematic, Renaissance)

**Phase architecture:**

| Phase | Action | Purpose |
|---|---|---|
| **A** Isolated research | Each style independently builds case; no cross-style visibility | Manufactured independence; prevent persona contamination |
| **B** Locked claims | Each writes load-bearing claims + non-negotiables; immutable for Phase C | Prevent Phase C drift / sycophancy |
| **C** Conditional negotiation | LLM-as-judge detects claim-conflict (Type 1/2/3); bounded to 3 rounds | Refine conflicts only when needed |
| **D** PMSupervisor synthesis | Reads all phases; produces ADD/WATCH/PASS with explicit dissent preservation | Decision with audit trail |
| **Evaluator** Hard-gate | Existing Evaluator runs OUTSIDE debate; process rubric, contamination check | Preserve correct minority view |

**Mode-style weighting matrix:**

| Style | B | B' | C | Anchor |
|---|---|---|---|---|
| Value | 30% | 15% | 10% | Steady names live or die on "is price wrong?" |
| Growth | 5% | 35% | 35% | Catch decline transitions (KO 1990s, IBM 2010s) |
| Quality / Moat | 35% | 30% | 20% | RMW (Fama-French 2015) strongest factor |
| Macro / Regime | 20% | 10% | 20% | Compounders regime-insensitive; thematic ARE regime bets |
| Quant / Technical | 10% | 10% | 15% | Crowding/factor-exposure check |
| **Sum** | **100%** | **100%** | **100%** | |

**Sector overrides:**
- Biotech-C: Growth 50% / Macro 25% / Quant 15% / Quality 5% / Value 5%
- Banks/insurers-B: Value 35% / Macro 30% / Quality 25% / Growth 5% / Quant 5%

### 2.4 Three critical architectural findings

1. **PMSupervisor MUST NOT force consensus** — sycophancy is dominant MAD failure mode (ICML 2025). Phase D output explicitly preserves dissenting views per agent
2. **Persona drift is real** — Phase B locks load-bearing claims and non-negotiables in writing; Phase C cannot modify Phase B locks
3. **Evaluator stays OUTSIDE the debate** — non-debating hard-gate anchor preserves correct minority view against debate dynamics

### 2.5 L7 smart-money signals (Tier-A only)

| Signal | Edge | Mode | Rule |
|---|---|---|---|
| Cohen-Malloy-Pomorski opportunistic insider purchases | ~82bp/mo value-weighted | Cross-mode | Multiple insiders (CEO + CFO + 2+ directors), open-market (not 10b5-1), large $ |
| LSV institutional accumulation in drawdowns | Behavioral premium | B and B' (ride-along) | 2+ Tier-1 institutions added in last 1-2 13Fs WHILE flat or down >10% from 6mo high AND valuation within ±25% sector median |
| Activist 13D (curated roster) | ~7.2% short-window abnormal | Cross-mode | Brav-Jiang anchor; magnitude compressed (15.9%→3.4% from 2001→2006) |
| 13G new-5%-holder | Thin lit; conditional | C-mode (small-caps) | Forces visibility on accumulation; wait-for-arrival framework |

McLean-Pontiff post-publication decay caveat: discount stated effects ~35-50%.

**Folklore signals discarded:** pure 13F large-cap replication, CNBC options-flow, unfiltered whale-watching.

### 2.6 Sidecar wiring

**S0 hybrid pull/push:**
- Pull (each phase fetches at invocation; stale-acceptable ≤5 trading days): P1, P3 (era-fit), P6 (vol regime), P4 Macro-Regime agent
- Push (regime shifts trigger): L1 detects shift → S0 fires event → P8 escalates affected positions to materiality-2; sensitivity-tagged-HIGH names re-underwrite

**S4 routing:**

| Event category | Routes to |
|---|---|
| Catastrophic / fraud-signature on held name | P9 fast-path (exit consideration) |
| Smart-money positive on candidate (not on watchlist) | P3 candidate-discovery |
| Smart-money positive on watchlisted name | P4 reunderwrite |

**Mode-classification at phase-entry, not at signal-detection.** L7 fires generic events; downstream phase classifies mode using rule + LLM tie-breaker.

---

## Section 3 — Data Layer

### 3.1 MCPs

Existing:
- `mcp__edgar__*` — SEC filings, company facts, filing text
- `mcp__market_data__*` — prices, news, real-time quote
- `mcp__fred__*` — macro time series
- `mcp__fundamentals__*` — Sharadar wrapping; delistings + fundamentals
- `mcp__postgres__*` — query, execute, schema_info
- `mcp__contamination_check__*` — verify, verify_memo, diagnostic

**New for v0.1:**
- `mcp__broker__get_positions` (read-only positions endpoint; Section 7 Q5)
  - First broker: Schwab (default; openness post-TDA acquisition); IBKR/Fidelity pluggable
  - OAuth via existing `.env` pattern; rate-limit-aware caching at mode-cadence-floor frequency

### 3.2 Postgres tables

Append-only event log pattern; every row carries timestamp + version metadata (rule_engine_version, prompt_version, model_id, parameters_version); HMAC-signed where audit chain applies; indexed on (ticker, date) for time-series queries; retention indefinite at v0.1.

```yaml
# Decision-model state
parameters                   # Versioned config (thresholds, prompts, weights) — every parameter change
regime_state                 # S0 daily classification per dimension + BOCPD probabilities
scenarios                    # P2 scenario branches with kill_criteria_structured
watchlist                    # P5 research-approved names with conviction, mode, size band, kill criteria
positions                    # Current portfolio state (synced from broker MCP)

# Decision-event log (calibration capture per Section 8 Q4)
execution_recommendations    # P5/P9 emissions with full Q1 schema (Section 7) + conviction rollup
position_history             # Append-only fill events
audit_provenance             # Per-stage structured log with HMAC chain
daily_refresh_log            # Per-ticker per-day materiality + structured event log
mode_classifications         # Rule + LLM tie-breaker outputs
unread_alerts                # Push alert queue + acknowledgments
materiality_events           # M-1/M-2/M-3 event log
counterfactual_retrievals    # Top-3 retrieval results per veto-trigger event
veto_lifecycle               # Section 6 Q6 PB#5 lifecycle states
anchor_drift_checks          # 3 channels (pillar / outcome / periodic)
premortem                    # Mode-tuned cadence + event triggers
operator_overrides           # Every override (sizing, routing, veto, mode) with rationale
recommendation_outcomes      # T+30d/T+90d/T+1y returns vs prediction
regime_classification_history # Daily snapshot per dimension; dual-signal columns `bocpd_change_probability` (canonical / audit) + `bocpd_short_run_mass` (firing) — migration 005 + migration 020. Used for v0.5+ BB-pseudo-BMA+ calibration.
debate_consensus_history     # 5-style outputs + dissents
fill_divergence              # Recommended vs actual fill (timing, sizing %, slippage)
calibration_test_results     # Periodic test runs against gold-standard sets
system_errors                # MCP failures, retries, escalations

# Catalogs
peak_pain_archetypes         # Section 6 Q6 catalog (~160 cases; two-layer schema)
counterfactual_ledger        # 32 fraud-signature named cases + 10 archetypes
successful_company_patterns  # L3-e patterns
```

### 3.3 Data-source mapping (S0 dimensions)

All 6 Tier-1 dimensions buildable on free data; total v0.1 incremental cost: $0/mo.

| Dimension | Source | Cost | Integration |
|---|---|---|---|
| 1 — Excess Bond Premium (EBP) | Fed CSV | Free | New trivial wrapper |
| 2 — Near-Term Forward Spread (NTFS) | FRED zero-coupon curve | Free | `mcp__fred` + computation |
| 3 — Variance Risk Premium (VRP) | VIX² − realized variance | Free | `mcp__fred` + `mcp__market_data` |
| 4 — MP/liquidity composite | FRED (WALCL, RESBALNS, RRPONTSYD, M2SL) + Cboe FF futures | Free | `mcp__fred` + market data |
| 5 — Trade-Weighted Broad Dollar | FRED `DTWEXBGS` | Free | `mcp__fred` |
| 6 — Stock-bond correlation | S&P + 10y Treasury rolling 60d, Forbes-Rigobon corrected | Free | Computation |

**Recommended optional v0.1 spend:** Sharadar $75/mo + Tiingo Power $30/mo = $105/mo; $145/mo headroom against $250 cap.

---

## Section 4 — Decision Model

### 4.1 L1 / S0 — Regime sidecar

**6 Tier-1 dimensions** (Section 3 Q1 lock). Each dimension produces probability distribution per state, NOT point classification. Single highest-edge: EBP (Gilchrist-Zakrajšek 2012).

**4 method overlays:**
1. **BOCPD** (Adams-MacKay 2007) — operator-locked **dual-signal architecture**. BOCPD per Adams-MacKay 2007 produces a posterior over run-lengths. The canonical change-point marginal `P(r_t=0|x_{1:t})` is structurally pinned near hazard rate in steady state when one run-length dominates the posterior (the prior P(r_t=0)=h and the posterior share predictive geometry under constant hazard); the cumulative short-run mass `P(r_t<10|x_{1:t})` is what crosses operational thresholds on regime shifts. Architecture stores both: **`bocpd_short_run_mass`** drives firing (Q3 thresholds below), **`bocpd_change_probability`** preserves academic provenance / audit traceability. Both are first-class, both indexed, both auditable in `regime_classification_history` (migration 020).
2. **Forbes-Rigobon vol-conditional correction** — MUST apply to dimension #6 to prevent spurious correlation-regime triggers
3. **Surprises (actual − consensus)** — applied to macro inputs in #1, #2, #4
4. **MSGARCH** (R) — production-grade vol-regime detection at v0.5+

**Weighting at v0.1: pure 1/6 equal-weight** for headline regime score (Smith-Wallis 2009; Claeskens-Magnus-Vasnev-Wang 2016 theorem-level result; equal-weight beats optimization at small N). Validation-depth tags retained ONLY as transparency annotations + trim-priority + monitoring cadence; NOT numerical multipliers.

**v0.5+ upgrade path:**
- N≈30 (months 12): equal-weight live; pseudo-BMA+ shadow-running
- Promote to live if Bayes-factor > 20 vs equal-weight (Kass-Raftery strong-evidence)
- N≈50 (months 18+): BB-pseudo-BMA+ with Diebold-Pauly shrinkage:
  ```
  w_final = (38/(38+N)) · w_equal_1/6 + (N/(38+N)) · w_pseudoBMA+
  ```
- Classical BMA REJECTED (M-closed assumption fails per Yao et al. 2018)

**Q3 firing thresholds (BOCPD-tiered).** All thresholds operate on `bocpd_short_run_mass` (the firing signal under the dual-signal architecture). The canonical `bocpd_change_probability` marginal does NOT systematically cross these thresholds; it is preserved for audit traceability per the operator-locked decision and is consumed by provenance / verbatim-emission flows only.

| Trigger | Materiality | Downstream |
|---|---|---|
| 1 dimension `bocpd_short_run_mass` > 0.7 sustained 2+ days | M-2 | Targeted memo update on sensitivity-HIGH names |
| 2+ dimensions `bocpd_short_run_mass` > 0.7 sustained 2+ days | M-3 | Full P4 re-underwrite on sensitivity-HIGH names |
| Any dimension `bocpd_short_run_mass` > 0.95 single-day catastrophic | M-3 + alert | Full re-underwrite + operator-attention flag |

**Refresh cadence: daily.** S0 re-classifies every trading day; BOCPD is *online* by design. Cold-start at first launch: full BOCPD on T-12mo data; `cold_start: true` flag for first 90 days; sizing overlays apply with `cold_start_caveat` annotation.

### 4.2 L2 / P2 — Probabilistic scenario writing

**Scenario data model (Q1 lock):** structured branches; Postgres JSON with explicit schema (scenario_id, theme_id, name, horizon_years, probability, description, kill_criteria_narrative, kill_criteria_structured, value_drivers, regime_fit, key_dates_to_watch).

**Scenarios per theme (Q2 lock):** variable 2-4 (Shell empirical sweet spot). Probabilities sum to 1.0 across siblings.

**Kill-criteria specification (Q3 lock):** hybrid pre-mortem narrative + structured conditions.

```yaml
kill_criteria_structured:
  - criterion_id: uuid
    type: hard | soft
    template_id: ref to catalog (optional)
    variable: e.g., fed_funds_rate, deposit_outflow_pct_48h
    comparator: < | > | == | between | sustained_above_for_days
    threshold: float
    deadline: ISO date | EOQ_YYYY_QN | null
    description: text gloss
    precedent_episodes: [historical episodes]
    degradation_status: durable | recalibrate | discredit_post_2020 | new_post_2020
```

**Firing logic:**
- Hard fires → scenario probability → 0; re-normalize across remaining branches
- N soft fire → cumulative haircut: probability × (1 − 0.2·N)
- Post-haircut < 0.1 → flag invalidated to operator
- `discredit_post_2020` → criterion read-only / informational

**Pre-loaded template library at v0.1 launch:**
- ~25 durable (use as priors): VIX>40, Lowry 90%-down, A-D divergence, capex 5-pillar, two-axis triggers
- ~15 new post-2020: SVB-deposit-outflow, NVDA-concentration, DRAM-weeks, GEX-flip, Ackman-dispersion
- ~25 discredited (read-only annotated): Yield curve as hard trigger, Sahm Rule, CAMELS, TED, naive AAII, OPEC-floor

**Q4: P2 → S0 = pure read-only** (P2 doesn't second-guess S0). **Q5: revision cadence = hybrid daily kill-checks (deterministic, no LLM) + event-driven full re-write (LLM regenerates only on regime-shift / kill-fire / operator invocation).** **Q6: probability granularity = hybrid schema [0.05, 0.95] + 0.05 step + sum-to-1 + Tetlock prompt + post-write linter (round-number + arithmetic-series detection).** **Q7: P2 → Macro-Regime agent contract = full scenario set with probabilities + theme tags from P3.**

### 4.3 L3 / P3 — Successful-company patterns + counterfactuals

**3-stage hybrid scorer (Section 5 Q1 lock):**

```
Stage 1A — Multiplicative knockout (any fail → REJECT):
  - Fraud signature 3+/6 (charismatic CEO + board lacks domain + novel accounting + secrecy + dismissed bear research + related-party)
  - Era-fit binary (right-thing-right-decade match)

Stage 1B — Additive equal-weight 4-criterion Tier-A composite (among Stage-1A survivors):
  - Founder/CEO duration ≥15 years
  - Per-share-value primary management metric
  - ROIIC > 15% sustained
  - Pivot-creates-multi-bag (not original product)
  - Threshold: ≥3 = A / 2 = WATCH / ≤1 = REJECT
  - Missing data: LEI-style proportional re-weighting

Stage 2 (LLM rubric, INFORMATION-ISOLATED from Stage 1):
  - Per-pattern single-attribute call (anchoring-bias mitigation)
  - 3-level ordinal {LOW, MEDIUM, HIGH} → {0.0, 0.5, 1.0}
  - Forced JSON: {rating, confidence, evidence_quotes[], rationale ≤2 sentences, defer_to_human, tie_break_applied}
  - Required verbatim evidence (no quote → defaults to LOW)
  - Self-consistency N=5 samples at temp=0.7; median rating
  - Stage 2 LLM does NOT see Stage 1 mechanical output

Stage 3 (deterministic linter):
  - Cross-check LLM output against Stage-1-known-true facts
  - Flag: contradictions, HIGH without evidence, round-number defaulting, position bias, verbosity
  - Routes to operator review; logged to S2 ledger
```

**Audit trail:** per-stage structured log with versioning at every layer; `saw_rule_output: false` enforced isolation flag; `disagreement: bool` first-class field.

**L3-e cross-era patterns:** 28 patterns categorized HIGH/MEDIUM/CONTESTED. **L3-d counterfactual catalog:** 32 named "looked like multi-bagger but failed" cases + 10 newly-surfaced archetypes (funding-monoculture, long-fuse-short-fuse, Ch.22 retail, SPAC redemption, real-estate Ponzi, regulatory-edict, single→multi-franchise pivot, captured-board-vs-founder-RPT, long auditor tenure, M&A blowups).

**Q2 mechanical structural-feature similarity:** Hamming/Jaccard on boolean/categorical features (NOT embeddings — embeddings have no relation to structural pattern). Per-instance rubrics adapted from legal-tech LRAGE.

**Q3 catalog feature extraction:** 3-LLM iterative-consensus pipeline with 5-iteration cap until HIGH confidence. Reaches consensus or flags persistent disagreement to operator.

**Q4 catalog drift:** event-driven adds (when name hits >50% drawdown and outcome resolves, auto-add via Section 5 Q4); event-driven recalibration automated; LLM figures out drift, asks operator only for confirmation.

**Q5 archetype tagging:** orthogonal to mode (mode is portfolio-level discipline; archetype is structural pattern).

**Q6 calibration test set:** lean ~50-case test set (20 canaries + 15 known-good + 15 stratified-similarity).

### 4.4 Peak-pain archetype catalog (Section 6 Q6 d')

**Two-layer schema** (Section 6 Q6 PB#1):

**Layer 1 — Universal core (sector-agnostic, mandatory):**
1. founder_insider_stake_direction (increasing/flat/decreasing/departed)
2. cash_runway (>24mo / 12-24mo / <12mo / distressed)
3. founder_in_place (yes/departed/replaced-by-competent)
4. margin_trajectory (improving/stable/deteriorating)
5. revenue_trajectory (growing/flat/declining/pre-revenue)
6. industry_tailwind (intact/weakening/reversed/structural-decline)

**Layer 2 — Sector-specific extensions** (used as tie-breaker when sectors match):
- Tech/SaaS: customer_engagement, engagement_decoupling_from_price, NDR_trend
- Semis: moat_state, cycle_state, customer_concentration
- Banks: capital_ratio, uninsured_deposit_pct, dilution_at_trough, asset_quality
- Energy: net_debt_at_trough, hedge_book, reserve_quality, cost_curve
- Industrial: backlog_quality, litigation_state, CEO_change_quality
- ... (full table in `.claude/references/empirical/peak-pain-archetypes/catalog-v0.1.md`)

**Retrieval scoring:**
```
similarity = 0.7 × universal_core_similarity
           + 0.3 × sector_extension_similarity   IF sector(candidate) == sector(case)
           + 0   × sector_extension_similarity   IF sectors differ
```

Universal-core similarity: Hamming over 6 features, equal-weight (1/6 each); Bayesian shrinkage λ=1.0 at v0.1.

**Catalog status:** ~160 cases across 15 sectors + 4 pre-2008 expansion eras (dot-com, GFC non-financial, 1989-92, 1973-82 stagflation). Outcome distribution: ~38 SURVIVOR / ~5 DILUTED-SURVIVOR / ~37 NON-SURVIVOR / ~30 TBD. Active retrieval pool excludes TBD.

**Catalog hygiene (PB#6):**
1. Recently-touched marker (event-driven): when retrieved, auto-marks last_touched_in_retrieval
2. Annual full audit (Jan 1): operator reviews 10% sample (~16 cases) stratified 50% not-touched-in-12mo / 25% TBD-near-24mo / 25% random
3. M-3-event-driven re-validation: cases retrieved as new top-3 auto-promote to recently-touched + queue for spot-check
4. Drift escalation: if ≥20% of audit sample needs reclassification, full catalog audit + M-2 system event

**3-LLM iterative-consensus validation (PB#7 + Phase 4 Q4):** priority subset (~45 cases: 15 calibration test + 30 canonical archetypes) before v0.1 launch; lazy validation for tail (~115 cases) on first-retrieval.

**Feature-typed consensus rule (Phase 4 Q4):**
- **Categorical features** (founder_in_place, founder_insider_stake_direction, sector-specific categorical): exact match required across all 3 LLMs
- **Ordinal features** (cash_runway, customer_engagement, margin_trajectory, revenue_trajectory, industry_tailwind, sector-specific ordinals): within-±1 ordinal step counts as agreement
- 5-iteration cap retained; persistent disagreement → tagged `consensus_status: disputed`, excluded from active retrieval, counted toward 5% allowable miss in Section 7 launch gate

**Validation metric: archetype-coverage agreement** (NOT NDCG@3 per PB#4). For each test case: operator pre-annotates expected archetype distribution in top-3; pass criteria:
- ≥80% of test cases retrieved-top-3 distribution within ±1 of expected
- ≥90% canonical SURVIVOR retrieves ≥2 SURVIVOR matches
- ≥90% canonical NON-SURVIVOR retrieves ≥2 NON-SURVIVOR matches

### 4.5 L4 / P8 — View-refresh discipline (daily monitor)

**Q1 — Daily refresh output (per ticker per day):** materiality + structured event log.

```yaml
daily_refresh_log:
  date: 2026-04-30
  ticker: NVDA
  mode: B'
  materiality: 2          # M-1 / M-2 / M-3
  events:
    - type: earnings_call_remark
      source_id: earnings_q1_fy27
      timestamp: 2026-04-30T20:30:00Z
      verbatim_quote: "..."
      impact: "Reduces growth dimension; check vs scenario A kill criteria"
      cited_kill_criterion_id: scenario_A.kill_3
  regime_context_at_eval:
    S0_classification: late_cycle_high_vol
    relevant_dimensions: [vol, credit]
  recommended_action: "P4 partial reunderwrite — Macro-Regime + Quality only"
  llm_call_metadata:
    model: claude-sonnet-4-6   # Default for M-1/M-2; Opus for M-3
    prompt_version: L4-daily-refresh-v0.1
    tier_escalated_to_opus: false
```

**Model constraint (operator-locked):** Sonnet or Opus only. NO Haiku.
- M-1 / M-2: claude-sonnet-4-6 default
- M-3: claude-opus-4-7 escalation

**Q2 — Materiality routing (hybrid floor + LLM judge):**

| Tier | Action | LLM-judge role |
|---|---|---|
| M-1 | No-op, log only | None |
| M-2 | P4 partial re-underwrite; LLM picks 2-4 of 5 agents | Bounded selection; defaults to event-type lookup table if confidence < 0.6 |
| M-3 | P4 full 5-agent re-underwrite + operator alert | Cannot downgrade |

Event-type → default agent lookup (M-2 fallback):
- Earnings call remark / EPS surprise → Quality + Growth
- Macro print (CPI, NFP, Fed) → Macro-Regime + Value
- Smart-money signal → Quality + Quant-Technical
- Sector rotation / peer move → Macro-Regime + Quant-Technical
- Regulatory / litigation → Quality + Value
- Product / capex / M&A → Growth + Value
- Credit-event / spread blowout → Macro-Regime + Value

**Q3 — Mode-tuned cut thresholds:**

**Mode B (steady) — hold-through bias:** cut on (i) ≥2 kill-criteria fired OR (ii) thesis-defining moat erosion verbatim-confirmed OR (iii) drawdown vs S&P 500 > 10pp sustained ≥3 quarters.

**Mode B' (growth) — moderate:** cut on (i) ≥1 thesis-defining kill-criterion fired OR (ii) growth-rate inflection > -50% YoY 2 consecutive quarters OR (iii) drawdown vs QQQ > 12pp sustained ≥2 quarters.

**Mode C (thematic) — cut-fast bias:** cut on (i) any kill-criterion fired OR (ii) BOCPD regime-change probability > 0.7 against thesis OR (iii) drawdown vs IWO/ARKK > 15pp sustained ≥1 quarter OR (iv) smart-money exit signal verified.

**Q4 — Pre-mortem cadence (mode-tuned + event triggers):**

| Mode | Calendar floor |
|---|---|
| B | 180 days |
| B' | 120 days |
| C | 60 days |

Event triggers (force pre-mortem regardless of calendar):
1. Thesis-confirmation event (paradoxically dangerous moment)
2. Consecutive M-2 events on same name within 30 days
3. First auto-tighten threshold crossed (B/S&P 5pp, B'/QQQ 7pp, C/IWO 10pp)
4. Mode reclassification proposed → pre-mortem mandatory before commit

LLM role: devil's-advocate assistant (Opus for high-stakes contestable judgment); generates 3 plausible failure modes; operator accepts/rejects each with rationale logged.

**Q5 — Anchor-drift defense (3 independent channels):**

1. **Pillar drift (diff-based)**: P3 lock writes immutable `thesis_pillars_original` (HMAC-signed); on every M-2/M-3 event, LLM diffs current vs original; trigger if drift score > 0.25
2. **Outcome divergence (quantitative)**: `scenario_A_base_projections` immutable; quarterly earnings → if any of {revenue, gross margin, FCF} deviates > 25% → trigger
3. **Periodic forced re-read**: cadence matches Q4 (B 180d, B' 120d, C 60d); operator must explicitly acknowledge or revise

When triggered: operator must choose Reaffirm / Revise-with-rationale (verbatim citation required) / Cut. No-op default BLOCKED.

**Q6 — Capitulation triggers (d' counterfactual VETO authority):**

Activates at 2× cut threshold (B/20pp, B'/24pp, C/30pp).

**Layer 1 — Cooling-off floor:**
- Mode B: 72h
- Mode B': 48h
- Mode C: 24h

**Layer 2 — Multi-source confirmation (mode-tuned, fires even on Mode C at 2× threshold):**
- ≥2 INDEPENDENT kill-criteria fired (BOCPD-correlated triggers collapse to 1)
- Verbatim primary-source confirmation (10-K, earnings call, regulatory filing)
- Operator pre-mortem within last 30 days

**Layer 3 — Counterfactual VETO:**
- Section 5 mechanical retrieval queries peak-pain archetype catalog using two-layer schema
- If ≥2 of top-3 are SURVIVOR archetype → cut requires explicit operator override
- If ≥2 of top-3 are NON-SURVIVOR archetype → cut proceeds per mode polarity
- If mixed → operator review required
- Veto operates ON TOP of mode polarity (can block Mode-C cut-fast when survivor pattern dominates — the PLTR-2022 problem)

**Re-fire policy (PB#5):**
- Single-fire per peak-pain event
- Re-fires automatically on M-3 materiality refresh (e.g., founder departure flips founder_in_place → archetype mix changes → veto re-evaluates)

### 4.6 L5/L6 — Execution output + multi-horizon disposition

**Recommendation output schema (Section 7 Q1):**

```yaml
execution_recommendation:
  ticker: NVDA
  date: 2026-04-30
  recommendation: BUY              # BUY / HOLD / TRIM / SELL
  conviction: HIGH                 # HIGH / MEDIUM / LOW (per PB#5 rollup)
  conviction_breakdown:
    debate_consensus: "4/5 (Quant-Technical dissents HOLD)"
    kills_fired: "0 of 7"
    counterfactual_top_3: "3 SURVIVOR archetype"
    mode_certainty: "rule-clean (no LLM tie-breaker)"
    drift_channels: "0 of 3 triggered"
  mode: B'
  sizing_suggestion:
    initial_pct: 1.4               # post-overlay
    max_pct: 3.5
    base_band: { initial: 2.0, max: 5.0 }
    applied_overlays:
      - { name: cash_constraint, multiplier: 1.0, reason: ... }
      - { name: drawdown_tighten, multiplier: 0.5, reason: ... }
      - { name: vol_regime, multiplier: 1.0, reason: ... }
    net_multiplier: 0.5
    funding_required: false        # if cash binds → true; surfaces companion TRIM candidates
  execution_context:
    current_price: 158.32
    fair_value_estimate: { point: 175, range_low: 155, range_high: 195 }
    near_term_catalysts: [{ event, date, importance }]
    suggested_pacing: "DCA over 21 days (Mode B' ride-along default)"
    technical_signals: { ma_50d, ma_200d, rsi_14, atr_20 }
    risk_flags: [...]
  trigger_metadata:
    triggered_by: mode_cadence_floor   # mode_cadence_floor / m2_event / m3_event / new_candidate
    cadence_floor_due_at: ...
    materiality_event_ref: null
    prior_recommendation_date: 2026-04-30
    prior_recommendation: BUY
    changed_from_prior: false
  audit_available: true            # full provenance available via /audit-trail
```

**Sizing v0.1 — mode-static + 3 hard overlays (PB#2):**

| Mode | Initial | Max |
|---|---|---|
| B | 3% | 8% |
| B' | 2% | 5% |
| C | 1% | 3% |

Hard overlays:
1. **Cash constraint:** suggested_initial = min(mode_band, available_cash_pct); if cash < suggested_initial → surface companion TRIM candidates (lowest-conviction holdings)
2. **Drawdown auto-tighten:** if portfolio drawdown vs benchmark exceeds threshold (B/S&P 5pp, B'/QQQ 7pp, C/IWO 10pp), sizing × 0.5 until drawdown clears
3. **S0 vol-elevated:** if S0 vol dimension > +1σ, sizing × 0.7

**v0.5+ composable formula (deferred):** weighted multipliers (conviction, regime, drawdown, cash); calibrated empirically once v0.1 produces ≥3 months of recommendation+fill+outcome data.

**Conviction rollup (Phase 4 Q2 revision of Section 7 PB#5):**

- **HIGH** = ≥4/5 debate AND 0 kills fired AND ≥2 SURVIVOR matches in top-3 AND ≤1 of {1 anchor-drift channel triggered}
- **MEDIUM** = ANY ONE of {3/5 debate, 1 kill fired, mixed counterfactual (1-2 SURVIVOR + 1-2 NON-SURVIVOR), ≥2 anchor-drift channels triggered}
- **LOW** = ANY ONE of {<3/5 debate, ≥2 kills fired, ≥2 NON-SURVIVOR matches in top-3}

**`mode_certainty: rule_clean | llm_tiebreaker`** is a separate annotation field, NOT a conviction-bucket determinant.
Company-quality flag (HIGH/STANDARD per Phase 4 Q1) feeds conviction multiplier at v0.5+.

**Conviction hysteresis (Phase 4 Q7):**
- Conviction transition (any direction) requires the transitioning condition to persist **2 consecutive cadence cycles**
- Per-name `conviction_flip_count_30d` tracked
- >3 flips in 30 days → name escalates to operator review (M-2 system event); auto-demote to MEDIUM and freeze until reviewed

**Multi-horizon disposition view (Section 7 Q2):**
- Single screen lists all watchlist names; three horizon columns (Short ≤3mo / Mid 3-12mo / Long 12+mo)
- Mode-anchored primary horizon highlighted/expanded by default:
  - B: Long primary
  - B': Mid primary
  - C: Short primary
- Operator can manually toggle primary horizon

**Trigger logic (Section 7 Q3):**

| Mode | Forced cadence floor | Materiality interrupts |
|---|---|---|
| B | Weekly Monday open | M-2 or M-3 → immediate |
| B' | Every 3 days | M-2 or M-3 → immediate |
| C | Daily | M-2 or M-3 → immediate |

New-candidate trigger: initial BUY recommendation fires upon completion of full P3 → P4 funnel approval, regardless of cadence rules.

**Position state source (Section 7 Q5):** broker MCP (read-only); auto-detect fills via diff against last polled snapshot; price from market_data quote at fill timestamp or broker-provided fill price.

### 4.7 L7 / S4 — Smart-money sidecar

Per Section 1 Item 8 + Section 2 Item 4. Tier-A signals only; folklore signals discarded; McLean-Pontiff post-publication decay caveat applied.

### 4.8 L8 / 5-style debate

Per Section 1 Item 7. Phase A→B→C-conditional→D + Evaluator hard-gate outside debate.

**Phase C trigger via LLM-as-judge** (Section 2 Item 2):
- Type 1 (direct contradiction)
- Type 2 (material magnitude disagreement)
- Type 3 (mutually exclusive prerequisite)

Judge's prompt is `parameters` table entry (versioned, recalibratable). Decisions logged to Postgres.

**Sensitivity-tagging** (Section 2 Item 3): at P5 watchlist-add, each name tagged regime-sensitivity HIGH/MEDIUM/LOW by Macro-Regime style agent during Phase A. When S0 fires regime-shift, only HIGH auto-re-underwrite; MEDIUM flagged-for-quarterly-review; LOW ignored.

---

## Section 5 — Operator Surfaces

### 5.1 Default operator-facing view

Clean recommendation output per Section 4.6 schema. No audit information surfaced unless requested.

### 5.2 Audit-mode UX (Section 7 Q4 — layered drill-down)

Operator runs `/audit-trail <rec_id>` → top-level audit summary with `drill_link` per stage:

```yaml
audit_summary:
  recommendation_id: uuid
  ticker, recommendation, date
  decision_path:
    stage_1_mechanical: { outcome, score, drill_link }
    stage_2_debate:     { consensus, dissenter, drill_link }
    stage_3_kill_criteria: { fired, drill_link }
    stage_4_counterfactual: { top_3_archetype, veto_status, drill_link }
    materiality:         { classification, trigger, drill_link }
  versions:
    rule_engine, debate_prompt, model, parameters
```

Each `drill_link` surfaces full audit data: verbatim quotes, agent outputs, 3-LLM iterative-consensus iterations, retrieval results, kill-criteria evaluation chain. HMAC-signed audit chain ensures tamper-evidence.

### 5.3 Push alerts (Section 7 PB#4 — multi-channel)

| Channel | Purpose | Triggers |
|---|---|---|
| Email | Real-time critical alerts | M-3 events only |
| Claude Code session push | Catch-up at session start | Unread M-3/M-2 since last session |
| `/alerts` slash command | On-demand review | All current alerts |

**M-3 events triggering email:**
- Counterfactual veto fires
- Anchor-drift channel triggers
- Mode reclassification triggered
- Kill-criterion explicitly fired or disproven
- Drawdown crossing 2× cut threshold
- Materiality classification = M-3

Operator acknowledges via `/ack <alert_id>` or `/ack all`.

### 5.4 Slash commands

| Command | Purpose |
|---|---|
| `/parameters-review` | Cadence-driven parameter recalibration; system proposes, operator approves |
| `/research-company <ticker>` | Manual P3+P4 funnel invocation |
| `/audit-trail <rec_id>` | Surface layered drill-down audit |
| `/audit-trail <ticker> --latest` | Latest audit for ticker |
| `/alerts` | List unacknowledged alerts |
| `/ack <alert_id>` / `/ack all` | Acknowledge alerts |
| `/disposition` | Multi-horizon disposition view + mode-fit dashboard (Phase 4 Q5) |
| `/premortem <ticker>` | Trigger pre-mortem (or surface scheduled) |
| `/system-health` | Unified visibility on degraded MCPs, queued recoveries, disputed catalog entries, system_errors, push-alert backlog (Phase 4 Q9) |
| `/wash-sale-harvest` | Ad-hoc tax-aware decisions (operator-driven; system not auto-surfacing) |
| `/spec-approve <version>` | Operator sign-off on v3 spec revisions |
| `/launch-confirm <gate_name>` | Operator sign-off on launch gates |

### 5.5 Operator onboarding (Section 8 Q5)

Documentation-only; no setup wizard.
- v3 final spec (this document)
- `docs/superpowers/operator-reference.md` (NEW; consolidated slash-command reference)
- Section consensus docs (1-7) for full Q&A provenance / deep dives

---

## Section 6 — Calibration + Drift

### 6.0 Calibration circularity defense (Phase 4 Q6)

To prevent v0.5+ formulas from regressing toward operator's behavioral biases:

**`override_outcomes` table:** every operator override tagged with T+90d / T+1y outcome + counterfactual baseline ("what system's recommendation would have produced"). Joined to `execution_recommendations` and `recommendation_outcomes`. Append-only; HMAC-signed.

**`system_vs_operator_brier` Postgres view:** computed monthly per (mode, materiality, recommendation_type) cell. Outputs system_brier vs operator_brier, N count per cell, direction-of-better flag.

**Override-rate dashboard** surfaces in `/parameters-review` quarterly. Cells with >50% override AND negative-Brier flagged as M-2 system event.

**v0.5+ formula calibration sign convention:**
- For cells where operator_brier < system_brier → calibration regresses TOWARD operator behavior
- For cells where operator_brier > system_brier → calibration regresses AGAINST operator bias (inverts default)
- Direction decided per cell, not globally

### 6.1 Calibration data capture (Section 8 Q4)

Capture everything + structured retrieval — every decision-event in typed Postgres tables (full list in Section 3.2). Append-only event log; HMAC-signed where audit applies; indexed (ticker, date); retention indefinite at v0.1.

### 6.2 Drift monitoring per subsystem

| Subsystem | Drift mechanism | Cadence |
|---|---|---|
| S0 regime | BOCPD probability per dimension; per-dim OOS performance tracked from day 1 in S2 | Daily |
| L3 catalog | Event-driven adds (>50% drawdown + outcome resolves); annual signature audit | Continuous + annual |
| L4 materiality | Cohen's kappa vs operator gold-standard; quarterly drift watch (10 production samples re-rated) | Quarterly |
| Peak-pain catalog | Recently-touched marker (event-driven) + annual full audit (10% sample, stratified) + M-3-driven re-validation + drift escalation if ≥20% reclassification | Continuous + annual |
| Anchor-drift | 3 independent channels per name; immutable original pillars HMAC-signed | Continuous |
| Mode classifier | **Per-name quarterly re-classification** (rule mismatch → review) + **semi-annual mode-implied-vol check** + quarterly portfolio-wide bias scan (Phase 4 Q5) | Quarterly + semi-annual |
| Materiality classifier | **N≥30 quarterly drift watch** + **rolling 30-event gold standard** (re-rated each quarter) + **confidence distribution monitoring** (P50/P90 shifts >0.1) (Phase 4 Q8) | Quarterly |
| Conviction rollup | Hysteresis (2-cadence persistence per transition) + flip-frequency tracking (>3 flips in 30d → operator review) (Phase 4 Q7) | Continuous |
| Override-rate | Per (mode, materiality, recommendation_type) cell; >50% override + negative-Brier → M-2 system event (Phase 4 Q6) | Monthly |

### 6.3 Parameter governance

`/parameters-review` skill — protocol locked (Section 1 Item 5):
- Pulls counterfactual ledger for period (default last 90d)
- Runs analysis: missed-winners, false-positives, mode-classification accuracy, drawdown vs benchmark per mode
- Generates proposed parameter changes with cited evidence
- Operator approves / modifies / rejects each
- Approved changes write to versioned `parameters` Postgres table
- Effective date stamped

Cadence (overrideable):
- Drawdown / risk monitoring: real-time / event-driven
- Ledger inspection: monthly
- Parameter recalibration: annually OR on-trigger

### 6.4 v0.5+ upgrade paths

| Upgrade | Source data | Activation |
|---|---|---|
| Brier-haircut on conviction | recommendation_outcomes + execution_recommendations | ~50 resolved predictions OR 18-24 months |
| Believability-weighted Issue Log | debate_consensus_history + recommendation_outcomes | Same as Brier |
| BB-pseudo-BMA+ regime weights | regime_classification_history + recommendation_outcomes | N≈30 (pseudo-BMA+ shadow) → N≈50 (live) |
| Composable sizing formula | operator_overrides + recommendation_outcomes + fill_divergence | ~3 months of v0.1 data |
| Continuous conviction score | execution_recommendations.conviction_breakdown + recommendation_outcomes | ~3 months |
| Peak-pain catalog tail validation | counterfactual_retrievals (first-retrieval events) | Lazy via event-driven |
| Mode classifier refinement | mode_classifications (rule + LLM tie-breaker outputs) | Disagreement-case analysis |

---

## Section 7 — v0.1 Launch Gates

All-or-nothing checklist (Section 8 Q3); any gate fail = no launch.

### 7.1 Hard gates (functional correctness)

- [ ] Postgres schema migrations applied + all required indexes
- [ ] Broker MCP OAuth flow tested; token refresh validated
- [ ] Audit-trail HMAC chain validates end-to-end
- [ ] Push alert email channel sends test email successfully
- [ ] Push alert Claude Code session push surfaces unread alerts at session start
- [ ] `/alerts`, `/ack <id>`, `/audit-trail <rec_id>` slash commands functional
- [ ] Recommendation emitter produces valid Q1 schema (zero missing fields across 50 test invocations)
- [ ] Mode classifier produces output for 100% of watchlist names
- [ ] L1-L2 regime sidecar producing all 6 S0 dimensions with BOCPD probabilities
- [ ] Materiality classifier producing M-1/M-2/M-3 with verbatim-quote citations on 100% of test events
- [ ] Counterfactual veto pipeline retrieves top-3 + computes archetype distribution

### 7.2 Calibration gates

- [ ] Peak-pain catalog priority-subset (~45 cases) at HIGH consensus on ≥95% of universal-core features
- [ ] Calibration test set (15 cases) archetype-coverage agreement ≥80% within ±1
- [ ] Canonical SURVIVOR test cases retrieve ≥2 SURVIVOR matches in ≥90% of cases
- [ ] Canonical NON-SURVIVOR test cases retrieve ≥2 NON-SURVIVOR matches in ≥90% of cases
- [ ] Mode classifier rule-clean rate ≥75% on watchlist
- [ ] L4 materiality classifier inter-rater agreement ≥0.61 Cohen's kappa vs operator gold-standard on 30 historical events

### 7.3 Operator sign-off

- [ ] Operator reviewed peak-pain catalog priority-subset validation results
- [ ] **100% of watchlist names mode-confirmed by operator** (Phase 4 Q5; replaces "first 10")
- [ ] Operator reviewed first 10 recommendation outputs for sensibility
- [ ] Operator confirmed broker MCP positions match brokerage UI
- [ ] Operator confirmed push alert email + Claude Code session push reach correctly
- [ ] `/system-health` returns valid output (Phase 4 Q9)

### 7.3a Walkthrough launch gates (Phase 4 Q3)

All 10 walkthroughs must produce verdict PASS or OPERATOR-OVERRIDE-REQUIRED with HMAC-signed attestation:

- [ ] **Walkthrough #1 — PLTR-2022** (motivating case): counterfactual veto authority + Layer 1/2/3 capitulation defense
- [ ] **Walkthrough #2 — NVDA-2023** (inverse): conviction rollup HIGH-gate (post Phase 4 Q2 fix)
- [ ] **Walkthrough #3 — SVB-March-2023**: Banks-B mode + M-3 deposit-flight + sector-extension matching
- [ ] **Walkthrough #4 — Cold-start day-1**: anchor-drift channels + cold-start cap on conviction
- [ ] **Walkthrough #5 — Mode reclassification race** (B'→C): pre-mortem cadence resolution
- [ ] **Walkthrough #6 — Override-rate >50% scenario**: dashboard surfaces pattern; system catches operator-bias
- [ ] **Walkthrough #7 — Catalog reclassification ripple**: TBD→NON-SURVIVOR; live retrievals re-evaluate
- [ ] **Walkthrough #8 — Broker MCP outage during M-3**: sizing degraded-flag + staleness display
- [ ] **Walkthrough #9 — Conviction flip-flop**: hysteresis prevents noise (drift score 0.23↔0.28)
- [ ] **Walkthrough #10 — Phase C judge silent miss**: judge confidence threshold + false-negative detection

Per-walkthrough deliverable: `docs/superpowers/launch-walkthroughs/<case-name>.md` per Phase 4 Q3 schema.

### 7.4 Implementation order (Section 8 Q2 — critical-path-first + parallel)

**Critical path (serial):**
```
Postgres schema (foundation)
  ↓
L1-L2 regime sidecar (S0 6-dim + BOCPD)
  ↓
P3 mechanical scorer (Stage 1 + Stage 2 LLM rubric + Stage 3 linter)
  ↓
P4 debate orchestrator (5-style)
  ↓
Mode classifier (rule + LLM tie-breaker)
  ↓
L4 materiality classifier + Q3 routing
  ↓
P5 recommendation emitter (Q1 schema with conviction rollup)
  ↓
Push alert channels (multi-channel)
```

**Parallel tracks:**
- Peak-pain catalog 3-LLM consensus validation (~45 cases)
- Broker MCP build (Schwab default)
- L8 multi-style debate prompts authoring
- Counterfactual veto pipeline
- Anchor-drift detector (3 channels)
- Pre-mortem scheduler (mode-tuned cadence)
- Audit drill-down UI
- Disposition view rendering

**Resource implication:** v0.1 ~6-8 weeks (including v3 spec authorship 1-2w + 4-6w implementation per Pushback #1 full-scope + spec-first lock).

### 7.5 Cold-start + error handling

**Initial regime classification cold-start:**
1. S0 sidecar runs full BOCPD on T-12mo macro data
2. Produces initial 6-dimension classification with `cold_start: true` flag for first 90 days
3. During cold-start: regime overlays apply with `cold_start_caveat` annotation in execution_context risk_flags
4. After 90 days, cold_start flag clears

**Error handling philosophy:**
1. First MCP/external API failure: retry once with 30s backoff
2. Second failure: escalate to operator alert (M-2 system-level event)
3. Never silent-fail: every failure logged to `system_errors` Postgres
4. Degraded operation: if any L1-L4 lane down, recommendations carry `degraded: true` flag with reason
5. Hard stop: multiple MCPs fail OR Postgres unreachable → maintenance mode → suppress recommendation output

---

## Section 8 — Open Items + v0.5+ Roadmap

### 8.1 Deferred to v0.5+

| Item | Reason | Activation trigger |
|---|---|---|
| Calibration haircut (Brier) | Sample size insufficient at v0.1 scale | ~50 resolved predictions OR 18-24 months |
| Believability-weighted Issue Log | Same sample-size constraint | Same as Brier |
| Real-money execution path | v0.1 is research/recommendation only | Checkpoint 3 advancement decision |
| BB-pseudo-BMA+ regime weighting | N too small at v0.1 | N≈30 shadow → N≈50 live |
| Composable sizing formula | No calibration data at v0.1 | ~3 months of v0.1 outcomes |
| Continuous conviction score | Same as composable sizing | Same |
| Backup / disaster recovery | Engineering ops; pg_dump sufficient at v0.1 | Operator demand |
| Cost tracking (LLM, broker rate) | Engineering ops | Operator demand |
| Behavioral risk overlays (overconfidence, loss-aversion drift) | Out of scope per per-name framing | Re-eval if portfolio surfaces added |
| Multi-broker MCP | First broker (Schwab) is sufficient at v0.1 | Operator's other brokers |
| Web UI for disposition view | Terminal sufficient at v0.1 | Operator demand |
| Multi-operator support | Single-operator at v0.1 | Future scenario |
| MSGARCH (R) production-grade vol-regime | Defer to v0.5+ per Section 3 Q1 | v0.5+ |
| S3 tax-bucket sidecar | Removed in Section 2 | Re-add if material drag |
| Tax-lot accounting beyond FIFO | FIFO sufficient at v0.1; SpecID supported per fill | Operator demand |

### 8.2 Out of scope (operator-locked)

- Portfolio-level concerns (concentration risk, sector exposure, mode-mix balance, correlation matrix, cash-as-portfolio-policy)
- Behavioral risk overlays (overconfidence streak detection, loss-aversion drift detection)
- Currency handling for ADRs (engineering detail)
- Dividend reinvestment policy (operator decides)
- Corporate actions (engineering detail; broker MCP feeds reality)

### 8.3 Falsifiability check (per Section 1.3)

- B-mode: 3+ specific missed 5x+ winners due to PASS-default in 12 months → discipline too conservative
- C-mode: net same as S&P 500 over 18 months → wasted time on C-mode names; pivot strategy or just index that portion

---

## Appendix A — Section consensus doc references

Full provenance + Q&A context for any decision lives in:

| Section | Doc | Locks |
|---|---|---|
| 1 | `docs/section-1-consensus.md` | 9 items + 3 architectural findings |
| 2 | `docs/section-2-consensus.md` | 5 wiring items + 3 open-floor |
| 3 | `docs/section-3-consensus.md` | Q1-Q4 (S0 sidecar) |
| 4 | `docs/section-4-consensus.md` | Q1-Q7 (P2 scenario writing) |
| 5 | `docs/section-5-consensus.md` | Q1-Q6 (L3/P3) |
| 6 | `docs/section-6-consensus.md` | Q1-Q6 + 7 pushbacks (L4/P8) |
| 7 | `docs/section-7-consensus.md` | Q1-Q5 + 5 pushbacks (L5/L6) |
| 8 | `docs/section-8-consensus.md` | Q1-Q6 + 2 pushbacks (v3 + gaps) |

---

## Appendix B — Catalogs + reference data

| Resource | Path |
|---|---|
| Peak-pain archetype catalog | `.claude/references/empirical/peak-pain-archetypes/catalog-v0.1.md` |
| Counterfactual ledger (32 fraud cases + 10 archetypes) | `.claude/references/empirical/counterfactual-ledger.md` (TBD path) |
| L3 successful-company patterns | `.claude/references/empirical/L3-successful-companies/` |
| Lane references L1-L8 | `.claude/references/empirical/L{1-8}-*.md` |
| Section 5 Q3 deep-dives | `.claude/references/empirical/data-sources/Q3-*.md` |
| Section 5 Q6 cross-domain calibration | `.claude/references/empirical/data-sources/Q6-Section5-*.md` |

---

**End of v3.0-draft.** Awaiting Phase 2 cross-section gap-detection sweep + Phase 3 parallel adversarial review (bear-case agent) before operator review (Phase 4) and `/spec-approve v3.0` sign-off.
