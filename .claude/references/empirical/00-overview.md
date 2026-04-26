# Empirical Domain Library — Overview

**Lane count:** 6 (L1–L6) plus this overview.
**Purpose:** ground-zero empirical reference material for the equity-research-system. Curated, source-cited, distilled. Consumed by downstream skills; not a skill itself.

This file is the entry point. It (a) maps each lane to the operator's investment funnel, (b) surfaces cross-lane patterns, (c) tells future skill-builders which lanes to load for which question, and (d) sets ground rules for consuming the library.

---

## The operator's investment funnel — refined model

The operator's original stated workflow:

```
news/indexes/futures → capture a trend → 3/5/10y scenario → "next Palantir" candidates
   → watchlist → technical entry/exit → daily refresh (shift vs stubborn balance)
   → per held name: swing / long / both
```

That linear arrow is the *intent*. The refined operational model below grounds each step in empirical findings (L1-L6 references), specifies inputs/outputs/gates, and adds the structural elements the lanes' patterns demand: **regime as always-on sidecar (not just step 1), explicit loop-back paths, survivorship-bias gate before watchlist-add, multi-horizon disposition as overlay (not terminal), counterfactual ledger always tracking PASS-and-exit decisions.**

### Refined funnel (with sidecars + loops)

```
                 ┌──────────────────── SIDECARS (always-on) ──────────────────┐
                 │ S0  Regime context        (L1) → piped to every phase       │
                 │ S1  Calibration history   (Brier per agent → conviction haircut)│
                 │ S2  Counterfactual ledger (every PASS/exit baseline-tracked) │
                 │ S3  Tax bucket per name   (LT/ST + wash-sale window)         │
                 └─────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
   ┌─►  P1  TREND CAPTURE  ────────────────────────────────────────  L1, L2
   │       in:   regime read + sector breadth + thematic news clusters
   │       out:  candidate themes (magnitude est, horizon est)
   │       gate: theme has empirical antecedent in L1 + variant-vs-consensus
   │             + identifiable beneficiary names; else PASS
   │
   │   ┌─►  P2  SCENARIO WRITING  3/5/10y  ─────────────────────────  L2
   │   │     in:   theme + regime context
   │   │     out:  2-3 distinct falsifiable scenarios, granular
   │   │           probabilities (60/40 not 75/25), pre-defined kill criteria
   │   │     gate: scenarios distinct + each has invalidator + consensus
   │   │           mismatch documented; else loop back to P1
   │   │
   │   │   ┌─►  P3  NAME DISCOVERY  (next-Palantir)  ─────────────────  L3
   │   │   │     in:   scenario + L3-e Tier-A signals + L3-d red-flag set
   │   │   │     out:  5-15 candidates per theme, fit-to-pattern scored
   │   │   │     gate: ┌─ fraud signature (3+/6) ─→ EXIT to counterfactual
   │   │   │           │  ledger
   │   │   │           ├─ right-thing-wrong-decade ─→ PASS (era mismatch)
   │   │   │           └─ Tier-A signals strong + red flags 0-2 → P4
   │   │   │
   │   │   │   ┌─►  P4  DEEP DIVE  (memo + adversarial bear)  ──────  v2-final §1.2
   │   │   │   │     CompanyDeepDive subagent (bull) ⊥ BearCase subagent
   │   │   │   │     PMSupervisor synthesis  →  ADD / WATCH / PASS
   │   │   │   │     gate:  default PASS;  ADD requires earned conviction
   │   │   │   │            haircut by S1 calibration history
   │   │   │   │     PASS → S2 counterfactual ledger (track vs SPY)
   │   │   │   │
   │   │   │   │   ┌─► P5  WATCHLIST ADD ──────────────────────────  v2-final
   │   │   │   │   │     out: Postgres row {conviction, size band,
   │   │   │   │   │          kill criteria, catalysts, resolution dates}
   │   │   │   │   │
   │   │   │   │   ┌─►  P6  DISPOSITION DETERMINATION  ────────────  L6 (always-on per name)
   │   │   │   │   │     classify: swing / long / both
   │   │   │   │   │     basis: vol regime + trend strength + reflexivity
   │   │   │   │   │            + L6 22-row decision table + tax bucket
   │   │   │   │   │     output: horizon label + disposition-conditional
   │   │   │   │   │             stop type (time-stop vs thesis-break)
   │   │   │   │   │
   │   │   │   │   │   ┌─►  P7  ENTRY EXECUTION ──────────────────  L5 (only patterns that survive)
   │   │   │   │   │   │     in:  L5 4-factor (trend / 200DMA distance /
   │   │   │   │   │   │          volume / cycle modifier)
   │   │   │   │   │   │     out: STRONG_ENTRY / ENTRY_OK / WAIT / DO_NOT
   │   │   │   │   │   │     gate: scaled within approved size band;
   │   │   │   │   │   │           DO_NOT loops back to P5 watch
   │   │   │   │   │   │
   │   │   │   │   │   │ ╔═══════════════════════════════════════════════════════════╗
   │   │   │   │   │   │ ║  P8  DAILY REFRESH (the loop) ──────────  L4              ║
   │   │   │   │   │   │ ║  in:  news/filings sweep + price + catalyst calendar      ║
   │   │   │   │   │   │ ║  out: per-name materiality {1, 2, 3}                      ║
   │   │   │   │   │   │ ║       trigger-based, not timer-based                       ║
   │   │   │   │   │   │ ║                                                            ║
   │   │   │   │   │   │ ║  M1: log + monitor                                         ║
   │   │   │   │   │   │ ║  M2: targeted memo-section update ─────► loops to P4      ║
   │   │   │   │   │   │ ║  M3: full reunderwrite ────────────────► forces P4 + P5   ║
   │   │   │   │   │   │ ║  Regime change in S0 ──────────────────► forces P1→P2 chain║
   │   │   │   │   │   │ ╚═══════════════════════════════════════════════════════════╝
   │   │   │   │   │   │
   │   │   │   │   │   ▼
   │   │   │   │   │  P9  EXIT  ─────────────────────────────────────  v2-final §2.3, L4, L6
   │   │   │   │   │      in:  thesis-pillar-fail flag (highest priority,
   │   │   │   │   │           never tax-suppressed) | exit signal eval
   │   │   │   │   │           | tax bucket S3
   │   │   │   │   │      out: NONE / TRIM / FULL_EXIT / WAIT_FOR_LT_THRESHOLD
   │   │   │   │   │      → S2 counterfactual ledger (track post-exit perf)
   │   │   │   │   │
   │   │   │   │   └──── (any exit/PASS/trim feeds counterfactual ledger S2)
   │   │   │   └──── (calibration update from realized outcomes feeds S1)
   │   │   └──── (regime shift from S0 forces re-entry at P1/P2)
   │   └──── (loop-back: scenarios fail kill criteria → re-write or abandon)
   └──── (loop-back: no candidate names pass P3 gate → theme PASS)
```

### Per-phase specification

| # | Phase | Primary lane | Input artifact | Output artifact | Gate criteria | Common failure modes |
|---|---|---|---|---|---|---|
| **S0** | Regime context (sidecar) | L1 | rates/credit/FX/commodities/vol cross-asset | regime classification + shift probability | refresh ≤5 trading days old | anchor-drift on regime view; over-extrapolating recent regime |
| **S1** | Calibration history (sidecar) | — | per-agent prediction outcomes | Brier-trend per agent (rolling 90d) | applied as conviction haircut | not haircutting overconfident agents |
| **S2** | Counterfactual ledger (sidecar) | — | every PASS/exit/trim | baseline-tracked perf vs SPY/sector/EWWatchlist/60-40 | mandatory write on every disposition decision | survivorship-bias drift if not maintained |
| **S3** | Tax bucket (sidecar) | — | per-position cost basis + acquisition date | LT/ST status + wash-sale window | feeds P9 exit shape | tax-blind exits → 3.5%/yr Munger drag |
| **P1** | Trend capture | L1, L2 | regime + breadth + flow + thematic news | candidate themes with magnitude/horizon estimate | empirical antecedent in L1 + variant-vs-consensus + identifiable beneficiaries | extrapolation, hedgehog framing |
| **P2** | Scenario writing 3/5/10y | L2 | theme + regime | 2-3 distinct falsifiable scenarios, granular probs, kill criteria | scenarios distinct + each has invalidator | single-path determinism; recency anchoring |
| **P3** | Name discovery | L3 | scenario + L3-e Tier-A signals + L3-d red-flags | 5-15 fit-scored candidates | fraud signature 3+/6 = exit; era-mismatch = PASS | survivorship bias (counterfactual-blind) |
| **P4** | Deep dive (bull ⊥ bear) | v2-final §1.2 | candidate name | CompanyDeepDive memo + BearCase critique + PMSupervisor synthesis | default PASS; ADD requires earned conviction; haircut by S1 | pressure-driven BUY; same-author motivated reasoning |
| **P5** | Watchlist add | v2-final §1.2; L4 | PMSupervisor ADD | watchlist row {conviction, size band, kill criteria, catalysts} | conviction ≥0.4 post-haircut | no kill-criteria pre-commit (Annie Duke L4) |
| **P6** | Disposition determination | L6 | watchlist name + vol regime + trend strength + reflexivity + tax | swing / long / both label + stop type (time vs thesis-break) | L6 22-row decision-table classification explicit | collapsing all timeframes into "today's price" (Mellers/Tetlock) |
| **P7** | Entry execution | L5 | watchlist name + disposition | STRONG_ENTRY / ENTRY_OK / WAIT / DO_NOT_ENTER + invalidation level | entry only on STRONG/OK; size scaled in approved band | encoding chart-pattern folklore (L5 discard list) |
| **P8** | Daily refresh (loop) | L4 | news/filings/price/catalyst calendar | per-name materiality {1,2,3} | trigger-based not timer-based; M3 forces P4 reunderwrite | timer-based refresh → anchor drift; ostrich effect (L4 Pattern #8) |
| **P9** | Exit | v2-final §2.3; L4; L6 | thesis-pillar-fail flag OR exit signal + S3 tax bucket | NONE / TRIM / FULL_EXIT / WAIT_FOR_LT_THRESHOLD | thesis-pillar-fail HIGHEST priority, never tax-suppressed | hold-loser-too-long (Marks pole) vs cut-winner-too-early (Druckenmiller pole) — L4 Section C |

### Key design properties of the refined funnel

1. **Regime is a sidecar, not a phase.** S0 feeds every phase. P1's trend-capture, P3's era-fit check, P6's disposition determination, P8's loop-trigger all consult the same regime read. This codifies cross-lane synthesis S2 ("macro/regime enables micro success — right thing in right decade").

2. **Survivorship bias is a P3 gate, not an afterthought.** L3-d's 16-name counterfactual catalog and the canonical fraud signature (3+/6 = exit) are evaluated *before* deep-dive resources are spent. Big firms typically check counterfactuals only at retro post-mortems.

3. **Disposition (P6) is an overlay applied early and re-evaluated continuously**, not a terminal phase. The same name has a swing label vs long-term label that determines the *type* of stop (time-stop vs thesis-break stop, per L6 Pattern #10), and this is set at P5 watchlist-add — not at exit.

4. **Daily refresh (P8) is trigger-based, not timer-based.** Catalyst-calendar events + materiality scoring drive refresh, not a daily clock. This is L4 Pattern #8 (ostrich effect defense) + Pattern #11 (process-vs-outcome separation): refreshing on noise destroys decision quality.

5. **Counterfactual ledger (S2) records every PASS, every exit, every trim.** Tracks performance relative to baselines from the date of the decision. This is the survivorship-bias-defense at the system level — we evaluate the decision-making process, not just the kept positions.

6. **Loop-back paths are explicit.** Scenarios that fail kill criteria → loop to P1 or abandon. Materiality-3 daily-refresh events → loop to P4 reunderwrite. Regime shifts in S0 → force re-entry at P1/P2 chain. The funnel is a graph with cycles, not a linear pipeline.

7. **The two adversarial schools are surfaced, not hidden.** L4 Section C's hold-through (Marks/Klarman) vs cut-fast (Druckenmiller/Soros) polarity governs P9's exit shape. Per cross-lane synthesis S4, this is regime-conditional — not absolute. The funnel doesn't pick a winner; it makes the choice explicit at the position level via L6.

8. **Tax-aware as a first-class sidecar.** S3 + P9 enforce the LT/ST distinction Munger documented (3.5%/yr structural drag if ignored, per L6 Pattern #6). The funnel doesn't pretend taxes are negligible.

### Lane-to-phase mapping (refined)

| Funnel phase | Primary lane | Supporting lanes |
|---|---|---|
| **S0** Regime context (sidecar) | L1 | L2 (probabilistic framing) |
| **P1** Trend capture | L1, L2 | L3-e (theme-to-name candidates) |
| **P2** Scenario writing 3/5/10y | L2 | L1 (regime context); L3-e (multi-decade company arcs by era) |
| **P3** Name discovery | L3 (esp. e + d) | L1 (era fit) |
| **P4** Deep dive | v2-final §1.2 | L3 (case analogs) |
| **P5** Watchlist add | v2-final | L4 (kill-criteria pre-commit) |
| **P6** Disposition | L6 | L3 (company archetype); L5 (regime/trend signal) |
| **P7** Entry execution | L5 | L6 (disposition determines stop type) |
| **P8** Daily refresh | L4 | L1 (regime change), L5 (signal change) |
| **P9** Exit | v2-final §2.3; L4; L6 | — |

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

## Related strategic docs

- **[`docs/big-finance-comparison.md`](../../../docs/big-finance-comparison.md)** — phase-by-phase comparison of what big finance shops (Druckenmiller / Tepper / Citadel / Tiger / etc.) actually utilize for each step of the operator's funnel vs what our system uses. Identifies where we're knowingly accepting gaps and where we're structurally different by design. Read this when deciding which gap to close next.

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
