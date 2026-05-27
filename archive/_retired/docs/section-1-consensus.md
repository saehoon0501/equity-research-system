# Section 1 Consensus — The Bet + Architectural Multipliers

**Date:** 2026-04-26
**Session:** Q&A consensus review with operator (saehoon0501)
**Status:** Locked — 9 items + 3 architectural findings + parameter values + deferred items
**Purpose:** Capture all design decisions from Section 1 of the consensus-review process so the implementation can proceed without re-reading the conversation.

---

## 1. Operator profile

| Attribute | Value | Implication |
|---|---|---|
| Portfolio size | <$1M (individual investor) | Big-firm tooling structurally unaffordable. Cost-conscious design throughout. Every $50/mo subscription is meaningful. |
| Goal | Mix of (B) "beat the market by 2-4%" + (C) "find multi-baggers in pursuit of 3-5x outcomes" | Two-mode operation; PASS-default discipline mis-tuned for C; mode-aware discipline required. |
| Background | Engineering (zero finance background prior to library) | Domain knowledge must be explicit, not assumed. Engineering analogies welcome. |
| LLM API budget | Covered by Claude Code Max (20× usage subscription) | LLM costs are not a constraint dimension. |
| Other tooling budget | Up to $250/mo | Affords Postgres hosting, Sharadar fundamentals, modest news/sentiment feed, plus buffer. |

### Falsifiability test for the system itself

Mode-conditional, per operator's Q3 answer:

| Mode | Test | Trigger to abandon mode |
|---|---|---|
| B | Specific missed 5x+ winners due to PASS-default discipline | 3+ such cases in 12 months → discipline too conservative |
| C | Net same as S&P 500 over 18 months | Wasted time on C-mode names; either pivot strategy or just index that portion |

---

## 2. The refined bet

> **At <$1M scale with a B+C goal mix, structural discipline + smart-money tracking + mode-aware default with active ledger feedback > raw input-volume disadvantage.**

Decomposed:

- **"Structural discipline"** = mode-aware PASS-default + 5-style debate architecture (Phase A→B→C→D) + active counterfactual ledger with quarterly review authority + mode-tagged outcomes + Evaluator hard-gates outside the debate.
- **"Smart-money tracking"** = L7's Tier-A signals only — opportunistic insider clusters (cross-mode), drawdown-period institutional accumulation (B/B' ride-along), 13G new-5%-holder (C wait-for-arrival). Folklore signals (rally-period 13F replication, CNBC options-flow, unfiltered whale-watching) explicitly discarded.
- **"Mode-aware default with active ledger feedback"** = B-mode strict + B' moderate + C minimum-tightness; relative-to-benchmark drawdown auto-tightens; quarterly operator review with parameter-recalibration authority (system proposes, operator approves).
- **"Raw input-volume disadvantage"** = no Bloomberg, no expert networks, no alt-data, no 24/7 macro team — accepted gaps per `docs/big-finance-comparison.md`.

**Test horizon:** v0.1 → v0.5 → v1.0. Falsifiable per the mode-conditional triggers above.

---

## 3. The 9 locked consensus items

### Item 1 — Three-mode model

**B / B' / C** with hybrid AI-rule-based classification at watchlist-add (operator override allowed).

| Mode | Definition | Examples | Discipline priority |
|---|---|---|---|
| **B** (steady compounder) | Established quality business; durable moat already proven; modest growth (5-12%); 15-25% annualized vol; FCF-driven compounding | KO, COST, V, MA, BRK, MCO | Valuation discipline + downside protection + moat durability |
| **B'** (growth compounder) | Established profitable; growth-rate is the bet; 25-50% annualized vol; multi-decade compounder potential | NVDA, AMD, GOOGL, MSFT, META | Growth-rate sustainability + moat extension via reinvestment + valuation conditional on growth |
| **C** (thematic / aspirational) | Pre-revenue or pre-profit; narrative-driven; >50% annualized vol; can fail to ~zero | RKLB, IONQ, PLTR-pre-2024, COIN | Growth rate + proprietary tech moat + can-take-loss + narrative reflexivity |

**Classification rule** (applied at watchlist-add by AI; operator override allowed):

```
Inputs: market cap, 252d realized vol, profitability profile,
        years-since-IPO, growth rate trajectory, sector

  IF market_cap > $50B AND vol < 25% AND profitable >5y AND growth < 12%
    → B (steady compounder)

  IF market_cap > $50B AND profitable AND (vol > 25% OR growth > 15%)
    → B' (growth compounder)

  IF market_cap < $50B OR not_yet_profitable OR narrative-driven
    → C (thematic)
```

**Sanity-check requirement:** every quarter, scan classifications for systematic bias (is AI putting everything in C? Or everything in B'?). If imbalance >70/30 between modes, the rule needs recalibration.

---

### Item 2 — Single-mode-per-name watchlist data model

Watchlist row keyed by **ticker** (not (ticker × thesis_id)). Mode tag is a column. Same name cannot have two modes simultaneously — if a name's characteristics overlap modes, AI picks one and flags for operator review.

**Rationale:** at <$1M with 20-30 name target, "two theses on one name" is mostly rationalization (the dishonest case where B-mode is failing and operator writes a C-mode "actually it's a turnaround" thesis to justify holding). Single-mode raises the cost of rationalization.

**Aggregate per-name cap:** 5% of portfolio (so ≥20-name diversification floor).

**Cross-name independence:** thesis-pillar-fail on one name doesn't cascade to other names. **Catastrophic failures DO cascade within the name:** fraud-signature trigger (3+/6 of L3 fraud signature) kills the name regardless of mode.

---

### Item 3 — Counterfactual ledger mode-tagging

Mode at decision time, **immutable**. Outcomes scored against the baseline matching the intent at decision:
- B-mode outcomes vs S&P 500
- B'-mode outcomes vs Nasdaq 100 (or QQQ)
- C-mode outcomes vs IWO (small-cap growth) or ARKK

If many B-mode classifications produce C-shaped outcomes (e.g., systematically more volatile than expected), the classification rule itself is wrong — itself a quarterly-review trigger.

---

### Item 4 — Calibration history (Brier-score) deferred to v0.5+

**Collect from day 1 of v0.1; apply as conviction haircut from v0.5+** (or after ~50+ resolved predictions accumulate, whichever comes first).

At <$1M scale with maybe 5-15 names in flight, accumulating 50 resolved predictions could take 18-24 months. Brier-haircut machinery exists in v0.1 but is dormant; activation requires sufficient sample.

---

### Item 5 — `/parameters-review` skill operationalizes cadence

**Protocol:**

```
/parameters-review [period]
  - Pulls counterfactual ledger for period (default last 90 days, override OK)
  - Runs analysis: missed-winner count, false-positive count,
    mode-classification accuracy, drawdown vs benchmark per mode
  - Generates proposed parameter changes with cited evidence
  - Operator approves / modifies / rejects each
  - Approved changes write to versioned `parameters` Postgres table
  - Effective date stamped; future runs use new values
```

**Cadence defaults (operator overrides whenever):**

| Activity | Default cadence | Override allowed? |
|---|---|---|
| Drawdown / risk monitoring | Real-time / event-driven (`/daily-monitor`) | Yes |
| Ledger inspection (read-only) | Monthly | Yes |
| Parameter recalibration (with change-authority) | Annually OR on-trigger | Yes |
| Mode-classification rule revision | Annually OR on-trigger | Yes |

**Authority scope:** system PROPOSES changes with cited evidence; operator APPROVES, MODIFIES, or REJECTS each.

---

### Item 6 — Mode-specific discipline with relative-to-benchmark drawdown auto-tighten

**Discipline knobs vary by mode:**

| Knob | B-mode | B'-mode | C-mode |
|---|---|---|---|
| Conviction threshold to ADD (post-haircut) | ≥0.7 | ≥0.6 | ≥0.5 |
| Thesis pillars required | 5 specific KPIs with valuation anchor | 4 KPIs incl. growth-sustainability | 3 KPIs, valuation can be optionality-based |
| Variant-view requirement | Mandatory (must differ from sell-side) | Mandatory if sell-side covered; optional if not | Optional (narrative-driven names often have no sell-side coverage) |
| Bear non-negotiables | All must be addressed | All must be addressed | All must be addressed (NO RELAXATION — fraud signature, governance failure always hard-veto regardless of mode) |
| Required L3 checks | Tier-A signals + valuation-discipline pattern (#15) | Tier-A signals + structurally-captures-secular-shift (#20) + growth-rate-sustainability evidence | Tier-A signals + structurally-captures-secular-shift + L3-d fraud signature (3+/6 = PASS) |
| Required L1 regime check | "Are we in a regime hostile to compounders?" (rates regime) | "Are we in a regime supporting growth multiples?" (rate cycle + growth dispersion) | "Are we in a regime where this theme has tailwind?" (sector regime) |
| Sizing band per name | 2-5% | 1.5-4% | 0.5-2% |

**Drawdown auto-tighten (relative-to-benchmark, NOT absolute):**

| Mode | Auto-tighten trigger | Tighten action | Catastrophic absolute halt |
|---|---|---|---|
| B | B-book underperforms S&P 500 by 5pp in rolling quarter | Conviction threshold +0.05; sizing band ceiling -1pp | B-book down -25% absolute → halt + full review |
| B' | B'-book underperforms QQQ by 7pp in rolling quarter | Conviction threshold +0.05; sizing band ceiling -1pp | B'-book down -35% absolute → halt + full review |
| C | C-book underperforms IWO/ARKK by 10pp in rolling quarter | Conviction threshold +0.05; sizing band ceiling -0.5pp | C-book down -50% absolute → halt + full review |

**Why relative-to-benchmark:** absolute drawdown triggers fire during market-wide selloffs (2022-style) precisely when buying opportunities are richest. Relative thresholds isolate "discipline failure" (we underperformed comparable indexes) from "regime drawdown" (everything's down).

---

### Item 7 — 5-style debate architecture (replaces bull/bear)

**5 styles** locked per L8 research (`L8-multi-style-debate.md`):

1. **Value** (Buffett, Klarman, Marks, Tepper) — distressed/contrarian variant folded in via cash-as-option rule
2. **Growth** (Druckenmiller-long-equities, Tiger, Coatue, Baillie Gifford)
3. **Quality / Moat** (Mauboussin, Munger, GMO, Terry Smith)
4. **Macro / Regime** (Bridgewater, Druckenmiller, Tepper macro overlay, Soros) — split from Quant/Technical per L8 finding
5. **Quant / Technical** (AQR, CTA-systematic, Renaissance) — split from Macro/Regime

**Vetoed as 6th styles** (with empirical reasoning):
- Activist/Catalyst — operator can't deploy activist capital at <$1M; treat as analytical lens within Value/Growth/Quality
- Contrarian/Distressed — folded into Value with cash-as-option rule

**Phase architecture:**

| Phase | What happens | Purpose |
|---|---|---|
| **A** Isolated research | Each of 5 styles independently builds its case from primary sources; no cross-style visibility | Manufactured independence; prevents persona contamination |
| **B** Locked claims | Each style writes load-bearing claims + non-negotiables; immutable for Phase C | Prevents Phase C drift / sycophancy |
| **C** Conditional negotiation | Runs only if Phase B reveals claim-conflict (bull's load-bearing claim contradicts bear's non-negotiable). Bounded to 3 rounds max. | Refines conflicting positions through dialogue |
| **D** PMSupervisor synthesis | Reads all phases. Produces ADD / WATCH / PASS with explicit dissent preservation ("Macro voted PASS for these reasons; I'm overriding with these stated reasons") | Decision with audit trail; never reports synthesized consensus |
| **Evaluator** Hard-gate check | Existing Evaluator subagent runs OUTSIDE the debate as non-debating anchor — process rubric, contamination check | Prevents debate from washing out a correct minority view |

**Mode-style weighting matrix** (the discipline mechanism per mode, anchored on Asness "Sin a Little" + S&P-DJI/Research-Affiliates equal-weight prior):

| Style | B (steady) | B' (compounder) | C (thematic) | Empirical anchor |
|---|---|---|---|---|
| Value | 30% | 15% | 10% | Steady names live or die on "is price wrong?" |
| Growth | 5% | 35% | 35% | Bumped from 0% in B to catch decline transitions (KO 1990s, IBM 2010s) |
| Quality / Moat | 35% | 30% | 20% | RMW (Fama-French 2015) is the strongest factor empirically |
| Macro / Regime | 20% | 10% | 20% | Compounders intentionally regime-insensitive; thematic ARE regime bets |
| Quant / Technical | 10% | 10% | 15% | Crowding/factor-exposure check; slight lift in C-mode where momentum unwinds bite |
| **Sum** | **100%** | **100%** | **100%** | |

**Sector overrides** (only for sectors with documented framework differences):

| Sector | Mode | Override matrix |
|---|---|---|
| Biotech | C | Growth 50% / Macro 25% / Quant 15% / Quality 5% / Value 5% (Quality meaningless pre-approval; Macro = FDA cycle + biotech-IPO regime) |
| Banks/insurers | B | Value 35% / Macro 30% / Quality 25% / Growth 5% / Quant 5% (Value = book-value-anchored; Macro = rate cycle) |

**Regime-conditional weighting decisions:**
- Per-name decision level: NO mode-weight changes (sin-a-little discipline)
- Mode-mix at portfolio level: YES — L1 regime classifier shifts BALANCE between B/B'/C *names in portfolio*, not within-mode style weights

---

### Item 8 — L7 smart-money signals with mode mapping

Per `L7-smart-money.md`. Operator's "ride-along on B-mode, wait-for-arrival on C-mode" framing refined with empirical conditioning per Lakonishok-Shleifer-Vishny 1994 (LSV contrarian).

**Tier-A do-survive signals** (use these):

| Signal | Empirical edge | Mode mapping | Operational rule |
|---|---|---|---|
| Cohen-Malloy-Pomorski "opportunistic" insider purchases | ~82bp/month value-weighted (~10%/yr abnormal) | Cross-mode | Multiple insiders (CEO + CFO + 2+ directors), open-market purchases (not 10b5-1 plans), large absolute $ |
| Institutional accumulation during drawdowns/flats with reasonable valuation (LSV 1994 + Coval-Stafford 2007) | Behavioral premium documented; not a risk premium | B and B' modes (ride-along) | 2+ Tier-1 institutions added in last 1-2 quarterly 13Fs WHILE stock flat or down >10% from 6mo high AND valuation within +/-25% of sector median |
| Activist 13D filings with known activists (Brav-Jiang) | ~7.2% short-window abnormal; durable, no long-run reversal | Cross-mode (rare for C) | Track curated activist roster; magnitude has compressed (15.9% → 3.4% from 2001 to 2006) — discount accordingly |
| 13G new-5%-holder filings | Thin academic literature; conditional confidence | C-mode (where small-caps don't show in major 13Fs) | Forces visibility on accumulation; fold into wait-for-arrival framework |

**Folklore signals (do NOT use — explicitly discarded):**

| Signal | Why it doesn't work |
|---|---|
| Pure 13F replication of large-cap rallies | GURU/ALFA underperform S&P by 0.5-1.3%/yr; 45-day lag erodes edge; CFA Institute calls them "fair-weather investments" |
| CNBC-publicized unusual options activity (Najarian segment) | Jiang-Strong: immediate overreaction → reversal → *negative* long-run abnormal returns. Following the segment is a losing strategy. |
| Unfiltered whale-watching individual PMs | Biographical entertainment, not strategy. Even Faber's backtest required low-turnover-manager + holdings filters to work. |

**McLean-Pontiff post-publication decay caveat:** stated effect sizes from Tier-1 academic findings should be discounted ~35-50% to reflect post-publication arbitrage. Apply this haircut when sizing positions on these signals.

---

### Item 9 — Mode-weighting matrix locked + Bridgewater Issue Log as v0.5+ feature

L8's mode-weighting matrix above is locked for v0.1 (with sector overrides for biotech and financials). **Believability-weighting Issue Log** (Bridgewater Idea Meritocracy mechanism — log which agent's view was right ex-post; allow believability-weights to adjust agent influence by 0-20% from base over time) is deferred to v0.5+.

This pairs with Item 4 calibration deferral — believability-weighting needs the same minimum sample of resolved predictions to deliver. Both turn on at v0.5+ together.

---

## 4. Three critical architectural findings (load-bearing for implementation)

### Finding 1: PMSupervisor MUST NOT force consensus

**Source:** L8 research — "Talk Isn't Always Cheap" (ICML 2025) + "Peacemaker or Troublemaker" (2025) + Bridgewater Idea Meritocracy.

**Empirical claim:** sycophancy is the dominant failure mode of multi-agent debate. LLMs collapse to premature consensus. Multi-agent debate can DEGRADE accuracy below single-agent baselines when peer pressure corrupts correct minority views.

**Implementation requirement:** PMSupervisor's Phase D output explicitly preserves dissenting views per agent. Format example:

```
DECISION: PASS
RECOMMENDED CONVICTION: 0.42 (haircut from 0.58 base by S1 calibration)

DISSENT TRACE:
  - Value: PASS (margin of safety insufficient at current price)
  - Growth: ADD (TAM expansion thesis intact; growth-rate sustainability validated)
  - Quality: WATCH (moat durability unproven; need 2 more quarters of data)
  - Macro: ADD (regime supportive)
  - Quant: PASS (negative momentum + factor crowding)

OVERRIDE REASONING:
  Growth and Macro voted ADD; PMSupervisor weighted-vote applies B'-mode
  matrix (Growth 35%, Macro 10%, Value 15%, Quality 30%, Quant 10%) →
  weighted score 0.43 below 0.6 B'-mode threshold.
  Quality's WATCH is the tiebreaker; insufficient moat-durability evidence
  is the load-bearing concern, not Value's price-sensitivity.

NON-NEGOTIABLES NOT ADDRESSED:
  Quality non-negotiable: "moat durability evidence over 8+ quarters of
  competitive intensity" — bull failed to provide; explicitly preserved
  as PASS-veto rationale.
```

### Finding 2: Persona drift is a real failure mode → identities and claims must be locked

**Source:** L8 research — ChatEval (ICLR 2024); Liang et al. "Degeneration-of-Thought."

**Empirical claim:** once an LLM commits to an answer, self-reflection cannot dislodge it. Multiple priors break the lock-in. Same-role agents degrade performance — persona diversity matters more than count.

**Implementation requirement:** each style agent has persistent locked identity (system prompt invariant across runs). Phase B locks load-bearing claims and non-negotiables in writing before Phase C negotiation begins. Phase C cannot modify Phase B locks.

### Finding 3: Evaluator stays OUTSIDE the debate as non-debating hard-gate anchor

**Source:** L8 research — multi-agent debate failure mode literature.

**Empirical claim:** debate can wash out correct minority views via peer pressure. A non-debating anchor with hard rejection criteria preserves correctness against debate dynamics.

**Implementation requirement:** existing Evaluator subagent retains its hard-gate role per `.claude/agents/evaluator.md` (process rubric, contamination check, mandatory ordering, evidence-index validation). Evaluator does NOT participate in Phase A-D debate. Evaluator's rejection authority is final regardless of PMSupervisor synthesis.

---

## 5. Design changes from v2-final spec

This Section 1 consensus introduces the following changes vs `docs/v2-final-spec.md`:

| v2-final spec | Section 1 change | Reason |
|---|---|---|
| Bull/bear adversarial isolation (CompanyDeepDive ⊥ BearCase) | **5-style debate** (Value/Growth/Quality/Macro-Regime/Quant-Technical) — Phase A→B→C→D | L8 research: persona diversity > count; bull/bear is binary and doesn't fit names cleanly |
| Single PASS-default discipline | **Mode-aware discipline** (B strict / B' moderate / C minimum-tightness) | Operator's B+C goal mix; PASS-default mis-tuned for C |
| Conviction threshold: single value | **Mode-conditional conviction thresholds** (≥0.7 / ≥0.6 / ≥0.5) | Mode-aware discipline |
| Calibration always-on | **Calibration deferred to v0.5+** (collect from day 1, haircut from v0.5+) | Sample size insufficient at <$1M v0.1 scale |
| (No equivalent) | **Counterfactual ledger mode-tagged**, outcomes scored against mode-matching baselines | Mode-classification accuracy is itself measurable |
| Drawdown thresholds: absolute (if any) | **Relative-to-benchmark drawdown auto-tighten** with absolute catastrophic halt | Absolute thresholds fire at worst times during market drawdowns |
| (No equivalent) | **L7 smart-money signal monitor** as sidecar S4; events feed P3 + P4 | Operator's stated belief that big firms move the market; ride-along for B/B', wait-for-arrival for C |
| (No equivalent) | **`/parameters-review` skill** with system-proposes / operator-approves protocol | Cadence is default not forced; reviews leverage Claude Code skills to unload operator burden |
| PMSupervisor synthesizes single decision | **PMSupervisor preserves disagreement** explicitly in output | L8 finding: sycophancy is dominant MAD failure mode |

**Compatibility note:** v2-final's load-bearing infrastructure (Evidence Index, contamination defense, audit trail, hard human-approval gate, append-only persistence, process-vs-outcome rubric separation) is preserved unchanged. Section 1's changes are at the decision-architecture layer; the substrate layer is paradigm-agnostic.

---

## 6. Deferred to v0.5+ (not part of v0.1 build)

| Feature | Reason for deferral | Activation trigger |
|---|---|---|
| Calibration haircut application | Need ~50+ resolved predictions for reliable Brier signal | At ~50 resolved predictions OR 18-24 months elapsed, whichever comes first |
| Believability-weighting Issue Log | Same sample-size constraint; pairs with calibration | Same as calibration |
| Real-money execution | v0.1 is paper-only per `docs/phasing-plan.md` | Checkpoint 3 advancement decision |

---

## 7. Library deliverables produced for Section 1

Two new lanes added to `.claude/references/empirical/` per the consensus session:

| Lane | File | Purpose |
|---|---|---|
| L7 | `L7-smart-money.md` | Smart-money signal taxonomy with empirical-edge ranking and mode mapping |
| L8 | `L8-multi-style-debate.md` | Multi-style debate architecture validation; refined 5-style taxonomy + mode-weighting matrix |

`00-overview.md` updated to include L7 + L8 in TOC, cross-lane synthesis (S8 + S9 added), funnel (S4 sidecar added; P3 + P4 updated), dependency map, and maintenance notes.

**Library scale after Section 1:** ~530+ sources / 8 lanes / 250+ patterns / 75+ disagreements / 20+ structured D-tables.

---

## 8. What's locked vs what remains for Section 2+

**Locked in this consensus document:**
- All operator-profile parameters (scale, goal, budget)
- The bet's exact form
- 9 consensus items including all parameter values (mode classification rule, mode-weighting matrix, drawdown thresholds, sector overrides)
- 3 critical architectural findings
- Design changes from v2-final
- Deferred items with activation triggers

**Open for Section 2 (refined funnel review):**
- Whether the funnel's per-phase gates correctly enforce the mode-aware discipline
- How regime sidecar (S0) actually feeds each phase operationally (in concrete terms)
- Whether the conditional Phase C trigger (claim-conflict detection mechanism) is robust
- How `/parameters-review` skill integrates into the loop architecture
- Whether L7's S4 sidecar event-firing is correctly wired into P3 + P4 inputs
- Whether the funnel handles "ride-along on B-mode" vs "wait-for-arrival on C-mode" mode-conditional smart-money behavior cleanly

**Open for Sections 3-8** (per session structure):
- L1-L6 substantive review (Sections 3-7)
- Coexistence with v2-final spec + what's still missing (Section 8)

---

**End of Section 1 consensus.** Implementation can proceed from this document without re-reading the conversation transcript.
