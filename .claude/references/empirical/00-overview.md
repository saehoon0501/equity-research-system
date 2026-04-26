# Empirical Domain Library — Overview

**Lane count:** 6 (L1–L6) plus this overview.
**Purpose:** ground-zero empirical reference material for the equity-research-system. Curated, source-cited, distilled. Consumed by downstream skills; not a skill itself.

This file is the entry point. It (a) maps each lane to the operator's investment funnel, (b) surfaces cross-lane patterns, (c) tells future skill-builders which lanes to load for which question, and (d) sets ground rules for consuming the library.

---

## How this maps to the operator's investment funnel

Operator's stated workflow:

```
news/indexes/futures → capture a trend → write a scenario for the coming 3/5/10 years
   → research stocks likely to be the next "Palantir case" → put them on the watchlist
   → technical analysis for entry and exit → repeat daily for updates
   (balanced: shift the view when warranted, don't be stubborn — also don't churn)
   → per held name: decide swing trade vs long-term investment vs both
```

Lane-to-phase mapping:

| Funnel phase | Lane |
|---|---|
| capture a trend (news/indexes/futures) | **L1 — Regime capture from cross-asset signals** |
| write a 3/5/10y scenario | **L2 — Probabilistic scenario writing** |
| research the "next Palantir" candidates | **L3 — Successful-company pattern library** |
| daily refresh balance (shift vs stubborn) | **L4 — View-refresh discipline** |
| technical analysis for entry/exit | **L5 — Technical execution playbooks** |
| swing vs long-term vs both per name | **L6 — Multi-horizon disposition** |

---

## Table of contents

### [L1 — Regime capture from cross-asset signals](L1-regime-capture.md)
What in rates, credit, FX, commodities, and equity vol reliably identifies regime. 32 sources (27 Tier 1). 22 quantitative patterns + 10 disagreements + lead-lag table. Anchored on Estrella-Mishkin yield-curve work, Engstrom-Sharpe NTFS, Gilchrist-Zakrajšek excess bond premium, Cochrane-Piazzesi forward-rate factor, Bridgewater All Weather. Demotes VIX correctly as coincident-not-leading. Pattern #20 (Goyal-Welch-Zafirov out-of-sample audit) is the meta-evidence on signal robustness.

### [L2 — Probabilistic scenario writing](L2-scenario-writing.md)
How practitioners write falsifiable multi-year scenarios. 33 sources (23 Tier 1). 18+ patterns + Section C unresolved disagreements + 3 structured tables (forecaster track records by horizon, scenario failure modes, methodology comparison). Anchored on Tetlock IARPA tournament data, GMO/Grantham superbubble framework, Hussman long-term-return decomposition, Marks "Illusion of Knowledge", Soros reflexivity, Damodaran 3P test. Pattern #1: 5y point macro forecasts decline toward chance accuracy. Pattern #4: valuation-based 10y forecasts retain meaningful predictive power even when point macro forecasts fail.

### [L3 — Successful-company pattern library](L3-successful-companies/00-overview.md)
Cross-era multi-bagger case studies + survivorship counterfactuals. 6 sub-files (a-tech, b-consumer, c-financials/healthcare, d-cyclicals/misses, e-cross-era, plus local 00-overview). 141 sources across sub-files. 16 named counterfactuals (Theranos, WeWork, Pets.com, Enron, Valeant, GE, Sears, Cisco, Polaroid, Kodak, Blockbuster, Nokia, BlackBerry, Lehman, Bear, LTCM). 20 cross-era patterns categorized HIGH/MEDIUM/CONTESTED. **The load-bearing artifact is `e-cross-era-patterns.md`** — apply its candidate-evaluation checklist against every "next-X" candidate. Includes the canonical fraud signature (charismatic CEO + board lacking domain expertise + novel accounting + secrecy + dismissed bear research + related-party transactions; 3+ = high alert).

### [L4 — View-refresh discipline](L4-refresh-discipline.md)
How to balance "shift the view when warranted" against "don't be stubborn." 29 sources (18 Tier 1). 18 patterns with quantified effects. Anchored on Tetlock superforecaster work, Odean 1998 disposition effect (~3.4%/yr penalty), Klein 2007 pre-mortem (HBR), Annie Duke kill criteria, Marks/Klarman "hold-through" vs Druckenmiller/Soros "cut-fast" — surfaced in Section C as a real, regime-conditional disagreement. Pattern #6: incremental Bayesian updating outperforms big jumps (Mellers IARPA 0.12 Brier improvement per SD smaller update).

### [L5 — Technical execution playbooks](L5-technical-playbooks.md)
Empirically validated technical patterns only. 32 sources (25 Tier 1). 20 patterns split into "do survive" (12) and "don't survive" (8). Anchored on Jegadeesh-Titman 1993, AQR factor papers (Asness/Pedersen network), Hurst-Ooi-Pedersen century-of-trend, Daniel-Moskowitz momentum crashes, Lo-Mamaysky-Wang chart-pattern study, Marshall-Young candlestick null result, Aronson H&S bootstrap test, McLean-Pontiff post-publication decay, Harvey-Liu-Zhu multiple-testing correction. **Honest about ATR-stops literature gap** — no peer-reviewed comparison vs fixed-percent stops; flagged as sensible-default-not-validated-alpha. Section D includes the "what survives vs what doesn't" table — the discard list (head-and-shoulders, candlesticks, Elliott Waves) is as important as the keep list.

### [L6 — Multi-horizon disposition (swing / invest / both)](L6-horizon-disposition.md)
Decision rules per name × per timeframe. 30 sources (24 Tier 1). Anchored on Druckenmiller's documented framework (×6 distinct interviews), Soros reflexivity, Buffett 1990 letter "lethargy bordering on sloth", Munger sit-on-hands tax math, Lynch six categories, Tudor Jones 21 rules, Klarman 10-15 holdings rule, Livermore pyramiding, Mauboussin position sizing. **Section D's 22-row characteristic→disposition table is the operational artifact for downstream skill builders.** Pattern #6: Munger's tax math (15%/35% terminal vs annual = 13.3% vs 9.75% net CAGR — 3.5%/yr structural drag favoring long-term for true compounders). Pattern #10: time-stop (Tudor Jones) vs thesis-break-only (Marks/Buffett) is the cleanest mechanical separator between swing and long-term.

---

## Cross-lane synthesis

Patterns that recur across multiple lanes — these are the load-bearing claims that survive multiple independent evidence bases and should weight heavily in any downstream skill.

### S1. **Regime-classification works; point forecasting doesn't** (L1 + L2)
- L1: yield-curve and credit-spread signals robustly classify recession-vs-expansion regime, with quantified lead times (10y-3m: 6-24mo lead; EBP: 50bp → 15pp recession-prob).
- L2: Tetlock IARPA + IMF recession studies show 5y+ point forecasts decline toward chance; recession magnitudes are systematically underestimated.
- **Implication:** any downstream skill should treat output as a regime classification (probability across discrete states) not as a point forecast. The forecast horizon is regime-sensitive, not date-specific.

### S2. **Macro/regime enables micro success — "right thing in right decade"** (L1 + L3)
- L1: regime characteristics (rates regime, credit cycle phase, dollar cycle) shape which sectors / business models can compound.
- L3 Pattern #20: Pets.com idea ≠ Chewy outcome despite identical business model — broadband + recurring billing + last-mile logistics matured between. Era-fit is structurally load-bearing.
- **Implication:** name-discovery skills must check macro/infra-stack era-fit alongside company fundamentals. A great founder + great team in the wrong decade still fails.

### S3. **Pre-defined invalidation outperforms discretionary reassessment** (L4 + L5 + L6)
- L4: Annie Duke kill criteria (state + date pairs) prevent in-position sunk-cost dominance.
- L5: ATR-based stops adapt to vol regime → more uniform stop-out probabilities than fixed-percent.
- L6: Tudor Jones uses time-stops (catalyst window passes → exit even if not losing); contrasted with long-term hold's thesis-break-only stop.
- **Implication:** every position should have its invalidation criterion specified at entry. The criterion's *type* is itself a signal of disposition (time-stop = swing, thesis-break = long-term).

### S4. **Concentrated conviction vs tactical rotation is regime-conditional, not absolute** (L4 + L6)
- L4 Section C: Marks/Klarman "hold through volatility" school vs Druckenmiller/Soros "cut fast on thesis change" school — both have track-record support, neither universally dominates.
- L6 Pattern #1+#7: Druckenmiller's 18mo–3yr default lens sits BETWEEN Buffett's "forever" and pure swing; reflexive setups (narrative-driven re-ratings) cannot be long-term holds.
- **Implication:** disposition is the (company × regime × thesis-type) tuple, not a fixed property. The same name can be a swing trade in one regime and a core hold in another.

### S5. **Trend / momentum survives empirical scrutiny; chart-pattern folklore doesn't** (L5 + L6)
- L5: cross-sectional and time-series momentum well-documented (212 years US + 40 markets); head-and-shoulders / candlesticks / Elliott Waves fail formal tests.
- L6: Druckenmiller scale-in protocol (1/3 on thesis, 2/3 on price confirmation) operationalizes momentum-confirmation; Tudor Jones uses 200d MA as universal regime filter.
- **Implication:** entry/exit skills should prefer trend-confirmation signals (volume, MA stack, regime classifiers) over pattern-recognition heuristics. The discard list in L5 Section D is load-bearing — don't encode discredited patterns.

### S6. **Granular probabilities + incremental updates beat verbal hedges + big revisions** (L2 + L4)
- L2 Pattern #6: Tetlock superforecasters use 60/40 vs 55/45 gradations, not "likely / unlikely."
- L4 Pattern #6: Mellers IARPA finding that 1 SD smaller update size correlates with 0.12 better Brier score.
- **Implication:** any skill that produces probability-like outputs should be built to use granular numbers and to update them in small increments per catalyst, not as binary flips.

### S7. **Survivorship bias defense via counterfactual ledger is load-bearing** (L3 + L4)
- L3 sub-file `d`: 16 named counterfactuals — companies that *looked like* multi-baggers and went to zero. Fraud signature codified.
- L4: pattern that "winners get sold, losers ridden" (disposition effect) is empirically backwards from optimal — the only defense is pre-committed kill criteria.
- **Implication:** every name-discovery skill must check candidate-vs-counterfactual resemblance, not just candidate-vs-winner resemblance. Both reference populations matter.

---

## Dependency map for downstream skill builders

Which lanes to load when building a skill for a given question:

| Future skill answers... | Primary lanes | Supporting lanes |
|---|---|---|
| What regime are we in? | L1 | L2 (probabilistic framing) |
| Write a 3/5/10y scenario for a thesis | L2 | L1 (regime context); L3-e (company-arc patterns by era) |
| Is this a "next Palantir" candidate? | L3 (especially `e-cross-era-patterns.md` + `d-cyclicals-and-misses.md`) | L1 (era-fit) |
| Should I refresh my view today? | L4 | L1 (catalyst awareness); L2 (incremental update math) |
| When/at what price do I enter or exit? | L5 | L6 (disposition determines stop type) |
| Is this name a swing trade or long-term hold (or both)? | L6 (esp. Section D decision table) | L3 (company archetype); L5 (regime/trend signal) |
| Daily monitoring digest for held names | L4 | L1 (regime change), L5 (signal change) |

A typical downstream skill loads 2–3 lanes — not the whole library.

---

## Builder's guide — how to consume this library

1. **Load lanes selectively per skill scope.** Don't dump the whole library into a skill's context. Per the dependency map above, most skills need only 2–3 lanes.

2. **Tier-1 patterns are load-bearing; Tier-2/3 are supporting.** When justifying a skill's logic, cite Tier-1 patterns. Tier-2/3 are useful as illustrations but should not be the foundation for a structural decision.

3. **Section C disagreements are first-class.** A skill that pretends consensus exists where Section C says it doesn't is mis-specified. If a skill's logic depends on a contested claim, it must surface the contestation to the operator (e.g., "this routing assumes the cut-fast school per Druckenmiller; if you prefer the hold-through school per Marks, use option B").

4. **Section D tables are the operational artifacts.** Lane Section D's are the closest to "skill input": L1 lead-lag table, L4 trigger-types vs reliability, L5 what-survived-vs-what-didn't, L6 22-row disposition table, L3-e 20-row pattern table. These are intended to be loaded directly when a skill needs decision-rule scaffolding.

5. **Refresh cadence: manual, triggered.** The library is not auto-updated. When a downstream skill discovers a load-bearing claim has shifted (e.g., a new study contradicting a Tier-1 pattern), the operator should re-dispatch the affected lane's research subagent with explicit instruction to update.

6. **The cross-lane synthesis above (S1–S7) is the recommended starting point** when designing any new skill. Each S-pattern names which lanes converge on a claim and what the operational implication is.

---

## Coexistence with `docs/v2-final-spec.md`

This library was produced under operator's framework: top-down macro/regime → thematic scenario → name discovery → multi-horizon technical execution. That framework is **distinct from but not contradictory to** the existing v2-final paradigm (bottom-up PASS-default quality compounders, 3y IRR distributions, watchlist contract).

The two can coexist:
- v2-final's machinery (Evidence Index, contamination defense, calibration history, bull/bear adversarial isolation) is paradigm-agnostic and protects any output.
- This library's content (regime signals, scenario techniques, name-discovery patterns, technical playbooks, disposition rules) is the substantive expertise that v2-final's structure was missing.

**Architectural decision deferred:** how the two integrate (does this library augment `/research-company`? sit alongside as `/horizon-call`? supersede the watchlist paradigm entirely?) is a separate brainstorming cycle. Not resolved here.

---

## Maintenance notes

- The library was produced 2026-04-26 by 6 parallel general-purpose research subagents under the empirical-foundation design spec at `docs/superpowers/specs/2026-04-26-empirical-foundation-design.md`.
- Per-lane diversity rule (no single author/site cited >3 times) was applied. Documented exceptions: L2 Wikipedia at 4-5 distinct topical entries (acceptable — different editorial communities); L5 Moskowitz at 4 distinct papers (acceptable — different research questions, different co-author teams); L6 Druckenmiller at 6 distinct interviews (acceptable — different host sites). All exceptions were flagged transparently by the producing subagent.
- Re-validation triggers: (1) downstream skill discovers a Tier-1 claim has shifted; (2) annual re-check of L3 counterfactuals as new failure modes emerge; (3) major regime change that may invalidate L1 lead-lag relationships.
