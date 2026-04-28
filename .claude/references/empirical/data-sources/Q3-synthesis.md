# Q3 Synthesis — Kill-Criteria Templates Cross-Period (Pre-2020 vs Post-2020)

**Date:** 2026-04-29
**Purpose:** Synthesize 8 parallel research subagents (4 post-2020 + 4 pre-2020) covering macro / sector / behavioral / practitioner kill-criteria. Identify what survived BOTH eras (durable templates), what broke post-2020 (discredit or recalibrate), and what's NEW post-2020 (recent additions).

**Predecessors:**
- 8 lane files at `.claude/references/empirical/data-sources/Q3-kill-criteria-*.md`
- Section 4 Q3 question (operator-pending)

---

## 1. Headline finding

**Mechanical / breadth / state-based criteria are durable across both eras.** Survey-based and regime-conditional-on-monetary-policy criteria require recalibration or replacement post-2020. The structural change in retail flow (mutual fund → 0DTE options + social-media-coordinated), in bank-stress dynamics (digital runs in hours), and in monetary regime (QE/QT) broke a meaningful subset of pre-2020 canonical signals — but didn't break the breadth/positioning/event-flow signals.

---

## 2. Templates that SURVIVED both eras (use these as v0.1 priors)

### Macro / monetary

| Template | Pre-2020 evidence | Post-2020 evidence | Status |
|---|---|---|---|
| Excess Bond Premium (EBP) > 1σ | Cleanest credit-based recession warning 1973-2012 (Gilchrist-Zakrajšek) | Survives Bordo-Haubrich 2019 OOS audit; remains highest-edge dimension | **Durable** |
| HY-OAS > 1000bp (crisis line) | Fired 2008 + 2011 (Eurozone) + 2015-16 (oil) + 2018 — sometimes false positive but reliable crisis signal | Fired March 2020 COVID (1087bp from 360bp YE-2019) | **Durable** |
| Reserves / short-term-external-debt < 1.0 | Fired Mexico 1994, Asia 1997, Russia 1998, Fragile Five 2013, Turkey/Argentina 2018 | Still applies (no major test post-2020) | **Durable for EM** |
| NTFS (Engstrom-Sharpe) | Strictly dominates 10y-3m pre-2020 | Survived 2022-23 false-positive episode where 10y-3m flashed; better but not perfect | **Durable, with caveats** |

### Sector / thematic

| Template | Pre-2020 evidence | Post-2020 evidence | Status |
|---|---|---|---|
| **Capex-cycle five-pillar pattern** (capex/rev >15%, debt-financed >50%, order-book divergence, capacity util >85% for 6+ qtrs, marginal producer cancels) | Fired Cisco-2000, telecom-2001, energy-2014, mining-2014, homebuilders-2006 | NVDA AI-capex 2025 — early-stage, in progress | **Durable; canonical** |
| Customer concentration > 35% top-10 + customer capex turning negative | Cisco/Lucent 2001 archetype | NVDA top-3 = 53%, $21.9B (similar pattern in progress) | **Durable** |
| Industry-wide net-debt/EBITDA > 4× at sector peak | Telecom 2001, energy HY 2014, retail LBOs 2017-18 | Available in CRE 2024+ | **Durable** |
| Funding-market spreads leading equity by 3-9 months | ABX BBB- (2007), HY energy (2014), ABCP run (2007) | Held 2020 COVID + 2022 SaaS reset | **Durable** |
| Phase III base-rate framework (31-58% LoA per Wong/BIO) | Robust to 2019 | Still applicable | **Durable** |

### Behavioral / sentiment

| Template | Pre-2020 evidence | Post-2020 evidence | Status |
|---|---|---|---|
| **VIX > 40** | 85-95% fwd 12m positive (Oct '08, May '10, Aug '11, Aug '15) | 96.4% fwd 12m positive at >45 (n=112, 1990-2026) | **Most durable** |
| Lowry 90% Down-Volume Day cluster | 69yr historical sample | Held through 2020 COVID + 2022 drawdown | **Durable** |
| NYSE A-D Line bearish divergence at index high | Every cyclical S&P 500 top last 50yr | Continues | **Durable** |
| Daniel-Moskowitz momentum-crash state (past-2y mkt < 0 + contemporaneous up) | 14/15 worst momentum returns | Still applies | **Durable** |
| Multi-indicator capitulation cluster (90%-down + AAII <-30 + P/C >1.20 + VIX >40) | Reliable bottom signal | Continues | **Durable** |

### Practitioner-framework structural elements

| Element | Pre-2020 evidence | Post-2020 evidence | Status |
|---|---|---|---|
| **Two-axis (price OR time) > single-axis triggers** | PTJ + Burry calendar trigger + Einhorn Lehman threshold | Druckenmiller 18mo-3y framework + Ackman Netflix 84-day exit | **Cross-era consensus** |
| Written/pre-stated kills > implicit | Annie Duke principle confirmed across PMs | Marks "Sea Change" Fed-funds-back-to-zero binary; Ackman dispersion threshold | **Cross-era consensus** |
| **Long-side kill criteria less precise than short-side** | Ackman's Valeant/Herbalife (long) vs Burry/Bass/Eisman (short) | "Bottoms are events, tops are processes" | **Cross-era consensus** |
| Process-level kill review > individual-judgment | Oaktree memo discipline > Ackman pre-2017 | Pershing post-Valeant institutional learning | **Cross-era consensus** |

---

## 3. Templates that BROKE post-2020 (discount, recalibrate, or remove)

### Macro / monetary (the biggest casualty list)

| Template | Pre-2020 status | What broke post-2020 | Recommended treatment |
|---|---|---|---|
| **Yield curve as HARD recession trigger** | 7/7 NBER recessions 1968-2019 | 2022-24 longest inversion since 1980s WITHOUT recession | **Demote to soft; require EBP/NTFS/Sahm confirmation** |
| **Sahm Rule as automatic recession signal** | 11/11 pre-2020 fires | 2024 misfire (immigration-supply shock); Claudia Sahm disavowed | **Demote to soft; condition on demand-driven labor data** |
| Bank-stress CAMELS / NPL / loan-loss canonical signals | Standard pre-2020 | SVB/Signature failed with healthy NPLs; duration mismatch + uninsured-deposit concentration NOT captured | **Replace with deposit-outflow-velocity + uninsured-% + HTM-loss triggers** |
| **Treasury safe-haven assumption** | Standard | March 2020 — Treasuries sold off WITH risk assets | **Add dealer-capacity / basis-trade health indicators** |
| TED spread / LIBOR-OIS | Standard | LIBOR cessation; SOFR-OIS has different statistical properties | **Replace with SOFR-IORB / RRP-utilization** |
| Sticky-CPI > 3% threshold | Zero signals 1995-2019 | > 6.5% in 2022 — calibration failed | **Recalibrate to post-COVID inflation regime** |
| HY-OAS thresholds (sub-1000bp ranges) | Pre-2020 calibration | 2022 peaked at ~600bp WITHOUT recession (QE-era valuation shift) | **Use as soft signal in 500-1000bp range; hard at >1000bp** |
| Adrian-Shin dealer-leverage signal | Standard | Hollowed by Volcker/SLR/GSIB; intermediation migrated to private credit / HFs | **Demote; track private-credit AUM separately** |
| Carry-trade unwind as systemic signal | 1998/2008/2015 systemic | Aug 2024 yen carry didn't propagate to broad EM crisis | **Localize; don't assume cross-asset contagion** |

### Sector / thematic

| Template | Pre-2020 status | What broke post-2020 | Recommended treatment |
|---|---|---|---|
| EV/Sales > 30 → multiple compression in 12-24mo | Standard | Strained for AI-capex names — revenue-growth step-change clause continues | **Soft signal; require fundamental confirmation** |
| Bank deposit-run 5% / 30 days threshold | SVB/SIVB era | 2023 SVB compressed timeline by 30× — digital runs in HOURS | **Recalibrate: >20% in 48h hard; >5% intraday alert** |
| OPEC cut = price floor | Standard | April 2020 negative-WTI broke this | **Demote** |
| Online penetration <25% = retail safe | Pre-2020 | 2020 pulled forward 3-5 years of digital adoption simultaneously | **Discard threshold; track per-category** |
| CAPE > 30 → low forward returns | Empirically robust pre-2020 | Strained 2020-24 (open question) | **Use as soft signal only; longer evaluation horizon** |

### Behavioral / sentiment

| Template | Pre-2020 status | What broke post-2020 | Recommended treatment |
|---|---|---|---|
| Tetlock 2007 WSJ-pessimism construct | Standard | Loses signal share to FinTwit / Reddit; narrative formation compressed weeks → hours | **Augment with FinTwit/Reddit-flow indicators** |
| Naive AAII bull >50% = sell | Pre-2020 worked at extremes | Even at 2σ extreme bull, mean fwd return +2.8% post-2020 | **Discard simple rule; use as confirming signal only** |
| CBOE put-call empirical thresholds (1995-2019 calibration) | Standard | 0DTE options broke them | **Recalibrate; or supplement with 0DTE-specific indicators** |
| Earnings-call NLP edge (Larcker-Zakolyukina, Loughran-McDonald) | Edge documented pre-2020 | Compressed via widespread quant adoption (FinBERT etc.) | **Treat as table stakes; not differentiating alpha** |
| Sentiment-survey contrarian rules | Pre-2020 reliable | Surveys can stay at extremes longer in passive-flow markets (2020-21 meme, 2023-24 AI) | **Require duration filter; combine with breadth confirmation** |

---

## 4. NEW post-2020 templates (no pre-2020 analog — recent additions)

| Template | Empirical episode | Threshold |
|---|---|---|
| **Single-day deposit outflow >20% in 48h** | SVB Mar 2023 ($42B / 25%); First Republic 40% in March; Signature | Hard kill for regional bank theses |
| **Office CMBS delinquency rate >10%** | Surpassed 2008 peak in late 2024 (11.0% by Dec 2024) | Hard threshold for office REIT theses |
| **NVDA top-3 customer concentration + GAAP GM drop** | 53% / $21.9B + GM compression watch | Canonical AI-capex falsifier pair |
| **DRAM weeks-of-inventory at suppliers** | 2022-23 peaked at 31w; current ~8w | >25w glut signal; <10w trough |
| **BVP Cloud Index forward EV/Revenue compression >40% in 12mo** | CY22 -50% ahead of fundamental break | SaaS / cloud reset template |
| **Stablecoin redemption velocity + peg deviation** | Terra-Luna May 2022; USDC March 2023 | Universal kill switch for crypto-adjacent |
| **Dealer GEX negative-flip sustained >5 sessions** | 2022 reflexive selloff regime confirmation | Reflexive-selloff entry signal |
| **Insider liquidity event within 90 days of new high** | Coinbase IPO + BTC top pattern | Canonical narrative top |
| **Bank reserves / GDP < 8%** | NY Fed "ample reserves" threshold; Sep 2019 SOFR spike to 5.25% | Liquidity-stress signal |
| **UMich 5-10y inflation expectation > 4.0%** | Breached April 2026 (4.4%, highest since June 1991) | Structural unanchoring kill |
| **Joint trimmed-mean PCE >3% AND median CPI >4% sustained 6M** | Killed "transitory" thesis 2021-23 | Inflation-persistence confirmation |
| **Ackman dispersion criterion** ("dispersion of outcomes has widened") | Netflix 84-day exit Apr 2022; canonical post-Valeant learning | Predictability-degradation kill |

---

## 5. Recommended Q3 lock — answer the original question

**Original Q3:** *How are kill criteria specified per scenario?*

**Locked answer: (c) hybrid — pre-mortem narrative + structured conditions.**

### Schema additions to v0.1 scenario data model

```
{
  ...existing fields from Q1 (Section 4)...
  kill_criteria_narrative: "Imagine 18 months from now this scenario invalidated. What happened? Most likely: [Klein 2007 prospective hindsight]"
  kill_criteria_structured: [
    {
      criterion_id: uuid,
      type: "hard" | "soft",
      template_id: ref to Q3 synthesis catalog (optional — if matches a known template),
      variable: e.g., "fed_funds_rate" | "ism_pmi" | "deposit_outflow_pct_48h",
      comparator: "<" | ">" | "==" | "between" | "sustained_above_for_days",
      threshold: float,
      deadline: ISO date OR "EOQ_YYYY_QN" OR null (for sustained criteria),
      description: text gloss for operator,
      precedent_episodes: [optional — when did this fire historically],
      degradation_status: "durable" | "recalibrate" | "discredit_post_2020" | "new_post_2020"
    }
  ]
}
```

### Firing logic (locked)

- **Hard criterion fires** → scenario probability → 0; re-normalize across remaining branches
- **N soft criteria fire** → cumulative haircut: probability × (1 − 0.2·N)
- **Post-haircut probability < 0.1** → flag as invalidated to operator
- **`degradation_status` = "discredit_post_2020"** → criterion is read-only / informational; doesn't fire scenario invalidation in v0.1

### Pre-loaded template library at v0.1 launch

The system ships with a curated kill-criteria template library drawn from this synthesis:
- ~25 durable templates (Section 2 of this doc)
- ~15 new-post-2020 templates (Section 4)
- ~25 discredit/recalibrate templates marked read-only with explicit deprecation notes (Section 3)

Operators / agents writing scenarios at P2 can:
1. Pick from the library by template_id (cheap, consistent, well-documented)
2. Define custom criteria with explicit `precedent_episodes` documentation (P2 prompt forces this)
3. Inherit `degradation_status` from template OR override with reasoning

This converts kill-criteria specification from "ad-hoc per scenario" to **"choose from validated catalog with optional customization"** — same pattern as design-system component libraries in software engineering.

---

## 6. Cross-period structural insights for Section 4

These should inform L2 / P2 design beyond just kill criteria:

1. **Mechanical/breadth/state-based signals are most durable.** Build P2 to default toward these; survey-based signals require regime confirmation.
2. **Post-2020 dynamics differ structurally** in retail flow (0DTE + social media), bank stress (digital runs), and monetary regime (QE/QT) — kill-criteria templates are regime-conditional, not universal.
3. **"Bottoms are events; tops are processes."** Long-side kill criteria need to be tighter and faster than short-side. This applies to L6 disposition (swing/long/both) too — already locked but reinforced.
4. **Public commitment is the dominant kill-criteria failure mode.** Ackman's Valeant + Herbalife disasters; this is why /grill-me protocol forces written pre-commitment.
5. **Hard-data lags price action 6-12 months.** Kill criteria should triangulate price + private-data + flow-velocity signals — single-source kills are too slow.
6. **Two-axis (price + time) outperforms single-axis** — applies to all levels (entry, exit, scenario invalidation).

---

## 7. Library deliverables produced (Q3)

8 lane files committed under `.claude/references/empirical/data-sources/`:

| File | Lines | Sources | Criteria |
|---|---|---|---|
| Q3-kill-criteria-macro-monetary.md | 412 | 25 | 48 |
| Q3-kill-criteria-sector-thematic.md | 213 | 28 | 41 |
| Q3-kill-criteria-behavioral.md | 355 | 30 | 45 |
| Q3-kill-criteria-practitioner-frameworks.md | 337 | 36 | 25 PM-thesis cells |
| Q3-kill-criteria-macro-monetary-pre2020.md | 275 | 25 | 24 (15 validated + 9 failed) |
| Q3-kill-criteria-sector-thematic-pre2020.md | 370 | 35 | 95 |
| Q3-kill-criteria-behavioral-pre2020.md | 253 | 25 | 47 |
| Q3-kill-criteria-practitioner-pre2020.md | 244 | 25 | 25 PM-thesis cells |
| **This synthesis** | — | — | — |

Total: 2,459 lines of empirical kill-criteria research; ~229 sources; ~325 specific criteria/templates documented.

---

**Synthesis complete. Q3 of Section 4 ready for lock.**
