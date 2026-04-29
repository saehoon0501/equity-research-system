# Mechanical scoring design for hybrid systems

Research note for Q1 / Section 5. Scope: best-practice patterns for the deterministic-gate
(mechanical) layer of an L3 hybrid scoring system in equity research / candidate evaluation.
Cross-references Q2 (equal-weight puzzle, Bayesian model averaging) and Q3 (kill-criteria).

Date: 2026-04-29
Tier labels: A = peer-reviewed primary source; B = official methodology document /
practitioner publication; C = secondary/explainer.

---

## Section A — Curated sources (tier-labeled)

### A1. Credit-scoring canonical (mechanical scoring methodology)

1. **myFICO — How are FICO Scores Calculated?** (Tier B — official Fair Isaac).
   Confirms 5-category weighting: Payment History 35%, Amounts Owed 30%, Length 15%,
   New Credit 10%, Credit Mix 10%. Weights derived from logistic-regression calibration
   on historical default outcomes; documented and stable for 30+ years.
   https://www.myfico.com/credit-education/whats-in-your-credit-score

2. **Altman, E. (1968) — "Financial Ratios, Discriminant Analysis and the Prediction of
   Corporate Bankruptcy"** (Tier A — original paper, NYU Stern reprint).
   Z = 1.2·X1 + 1.4·X2 + 3.3·X3 + 0.6·X4 + 0.99·X5. Cutoffs: >2.99 safe, 1.81–2.99
   gray, <1.81 distress. Multiple discriminant analysis (MDA), linearly weighted.
   https://pages.stern.nyu.edu/~ealtman/Zscores.pdf

3. **Ohlson, J. (1980) — "Financial Ratios and the Probabilistic Prediction of
   Bankruptcy"** (Tier A — Wikipedia summary of original, includes coefficient table).
   9-variable logistic regression. O = -1.32 - 0.407·SIZE + 6.030·(TL/TA) - 1.430·(WC/TA)
   + 0.076·(CL/CA) - 2.370·(NI/TA) - 1.830·(FFO/TL) + 0.285·NITWO - 1.720·OENEG
   - 0.521·CHNI. Probability via logistic transform exp(O)/(1+exp(O)).
   https://en.wikipedia.org/wiki/Ohlson_O-score

4. **Merton, R. (1974) / KMV adaptation — distance-to-default structural model**
   (Tier A — Wikipedia + MathWorks reference). DD = (ln(V/D) + (r + σ²/2)·T) / (σ·√T).
   Models equity as call option on assets. Default when assets < debt. Still core to
   Moody's KMV CreditEdge.
   https://en.wikipedia.org/wiki/Merton_model
   https://www.mathworks.com/help/risk/default-probability-using-the-merton-model-for-structural-credit-risk.html

5. **MathWorks — Credit Scorecard Modeling with Missing Values** (Tier B — official
   MATLAB Finance Toolbox docs). Shows Weight-of-Evidence (WoE) bin for missing values
   as a first-class category — does not impute, gives partial credit.
   https://www.mathworks.com/help/finance/credit-scorecard-modeling-with-missing-values.html

6. **Listendata — WoE & Information Value tutorial** (Tier C — but well-cited explainer
   for scorecard development pipeline).
   IV = Σ (good% − bad%) · ln(good%/bad%); rule of thumb: 0.1–0.5 = useful predictor.
   https://www.listendata.com/2015/03/weight-of-evidence-woe-and-information.html

### A2. Composite-index construction (multi-signal aggregation)

7. **Conference Board — Calculating the Composite Indexes / LEI Technical Notes**
   (Tier B — official). Inverse-standard-deviation weighting to equalize component
   volatility, normalized to sum to 1; 10 components with adaptive proportional
   re-weighting when components are missing.
   https://www.conference-board.org/data/bci/index.cfm?id=2154
   https://www.conference-board.org/pdf_free/press/US%20LEI%20Technical%20Notes-Feb%202026.pdf

8. **Conference Board — Description of Components (LEI 10 components)** (Tier B).
   Components: avg weekly mfg hours; initial UI claims; consumer-goods orders; ISM
   new orders; nondefense capital-goods orders; building permits; S&P 500; Leading
   Credit Index; 10y–FFR spread; consumer expectations.
   https://www.conference-board.org/data/bci/index.cfm?id=2160

9. **ISM Report on Business — Wikipedia + S&P Global comparison** (Tier B/C).
   PMI = equal-weighted (20% each) avg of New Orders, Production, Employment,
   Supplier Deliveries, Inventories. Each diffusion index ranges 0–100; 50 = neutral.
   https://en.wikipedia.org/wiki/ISM_Report_On_Business
   https://www.spglobal.com/marketintelligence/en/mi/research-analysis/sp-global-pmi-and-ism-survey-comparisons.html

10. **Chicago Fed — NFCI About + FAQ** (Tier B — official). 105 indicators aggregated
    via Kalman-smoothed dynamic factor model (PCA-style); 3 sub-indices (risk, credit,
    leverage); zero mean, unit SD over 1971–present.
    https://www.chicagofed.org/research/data/nfci/about
    https://www.chicagofed.org/-/media/publications/nfci/nfci-faqs-pdf.pdf

11. **Conference Board — Consumer Confidence Survey Technical Note (May 2021)**
    (Tier B). 5 survey questions, ternary response (positive/negative/neutral);
    relative value = pos / (pos + neg); indexed to 1985 = 100. Present-situation
    weight 40%, expectations 60%.
    https://www.conference-board.org/pdf_free/press/TCB_CCS_TechNote_May2021.pdf

### A3. Factor-zoo composite scoring (finance / equity research)

12. **Asness, Frazzini, Pedersen (2019) — "Quality Minus Junk"** (Tier A — *Review of
    Accounting Studies*, also AQR working paper). Quality composite = profitability +
    growth + safety + payout, each itself a sub-composite of z-scored ratios. Equal-weight
    aggregation across sub-composites. 0.66%/mo risk-adjusted return US sample.
    https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2312432
    https://www.aqr.com/Insights/Research/Working-Paper/Quality-Minus-Junk

13. **Piotroski, J. (2000) — "Value Investing: The Use of Historical Financial
    Statement Information to Separate Winners from Losers"** (Tier A — *J. Accounting
    Research*). 9 binary criteria, additive 0–9 score, cutoff at 8+/9. 23%/yr long–short
    spread on high book-to-market universe 1976–1996.
    https://en.wikipedia.org/wiki/Piotroski_F-score
    https://www.quant-investing.com/blog/piotroski-f-score-improves-global-stock-performance

14. **Greenblatt, J. — Magic Formula** (Tier B — *The Little Book That Beats the
    Market*). Two-metric rank composite: rank by ROC, rank by EBIT/EV, sum of ranks.
    Pure ordinal aggregation (no metric weights, no z-scores).
    https://en.wikipedia.org/wiki/Magic_formula_investing
    https://www.gurufocus.com/tutorial/article/57/greenblatts-earnings-yield-and-return-on-capital

15. **Harvey, Liu, Zhu — "...and the Cross-Section of Expected Returns" (2014/2016)**
    (Tier A). Multiple-testing correction for factor zoo: argues t > 3.0 (not 2.0)
    needed after Bonferroni / BH / family-wise-error adjustment for the ~316 factors
    tested in literature.
    https://people.duke.edu/~charvey/Research/Published_Papers/P118_and_the_cross.PDF

16. **Bailey & López de Prado — Deflated Sharpe Ratio** (Tier A). Adjusts SR for
    selection bias from N independent trials, sample length, skew, kurtosis.
    Reference for haircutting any composite-score backtest.
    https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf

### A4. Calibration / weight-stability

17. **DeMiguel, Garlappi, Uppal (2009) — "Optimal vs. Naive Diversification"**
    (Tier A — *Review of Financial Studies*). 1/N beats 14 optimization-based models
    out-of-sample due to estimation error. Cross-references Q2 equal-weight puzzle.
    https://ideas.repec.org/a/eee/inteco/v179y2024ics2110701724000489.html

18. **Hoeting, Madigan, Raftery, Volinsky (1999) — "Bayesian Model Averaging: A
    Tutorial"** (Tier A — *Statistical Science* 14(4): 382–417).
    BMA combines models weighted by posterior probability — proper accounting for
    weight uncertainty. Cross-references Q2 BB-pseudo-BMA+ recommendation.
    https://www.stat.colostate.edu/~jah/papers/statsci.pdf

19. **Hyndman & Athanasopoulos — "Forecasting: Principles and Practice" §5.10
    Time-series cross-validation** (Tier B — standard textbook). Walk-forward /
    expanding-window CV is the only valid approach for serially-correlated data.
    https://otexts.com/fpp3/tscv.html

### A5. Edge-case handling / production architecture

20. **Wikipedia — Winsorizing** (Tier C — but standard reference for the technique).
    Replace values below pth and above (1−p)th percentile (typically p = 0.01) with
    the cutoff values. Standard in accounting research and factor construction.
    https://en.wikipedia.org/wiki/Winsorizing

21. **Leone — "Influential Observations and Inference in Accounting Research"** (Tier
    A — UO working paper). Empirically demonstrates that 1%/99% winsorization is the
    de-facto convention in accounting/finance ratio studies.
    https://business.uoregon.edu/sites/default/files/media/andrew-leone-accounting-research-wkshop-2013-11.pdf

22. **Stripe — "How we built it: Stripe Radar"** (Tier B — engineering blog).
    Hybrid architecture: deterministic rules engine (custom + built-in) layered on
    top of pure-DNN ML model; rules execute first as hard gate; ML model returns risk
    score for marginal cases. Sub-100ms latency; 1000+ characteristics.
    https://stripe.dev/blog/how-we-built-it-stripe-radar
    https://stripe.com/blog/using-ai-dynamic-radar-rules

23. **Upstart — "How AI drives more affordable credit access"** (Tier B — corporate).
    2,500+ variables, 82M repayment events; 75% improvement in default prediction
    over traditional FICO-only models. ML supplements but does not replace regulatory
    deterministic checks.
    https://info.upstart.com/how-ai-drives-more-affordable-credit-access

24. **Gawande, A. — *The Checklist Manifesto*; Pabrai investment checklist**
    (Tier B/C). Mechanical binary checklists outperform unaided expert judgment on
    rare/high-consequence events. Pabrai operates a ~97-item checklist before any
    capital commitment.
    https://www.oldschoolvalue.com/investment-tools/mohnish-pabrai-checklist-investor/
    https://www.valueinvestingworld.com/2009/09/checklist-by-atul-gawande.html

25. **Kästner — "Versioning, Provenance, and Reproducibility in Production ML"**
    (Tier B — CMU course book). Tuple = (data version, code version, config,
    random seed) → bit-identical artifact. Standard for auditable ML.
    https://mlip-cmu.github.io/book/24-versioning-provenance-and-reproducibility.html
    https://ckaestne.medium.com/versioning-provenance-and-reproducibility-in-production-machine-learning-355c48665005

---

## Section B — Scoring patterns

### B.1 Additive vs multiplicative

| Property | Additive (sum of points) | Multiplicative (any-fail = exit) |
|---|---|---|
| Compensation between criteria | Yes — strength on A offsets weakness on B | No — weakness on any criterion sinks the score |
| Normalization sensitivity | High — different normalizations flip rankings (Add-or-Multiply tutorial) | Low — invariant to monotone transforms when binary |
| Models "must-have" features | Poorly | Naturally |
| Models compensable trade-offs | Naturally | Poorly |
| Examples | FICO (within category), Piotroski F-score, AQR QMJ, ISM PMI, LEI | Fraud knockout rules; regulatory hard limits; Stripe Radar built-in rules; Pabrai disqualifiers |
| Failure mode | Hides catastrophic flaws under aggregate score | Single false positive on any criterion blocks otherwise-good candidate |

**Empirical rule**: every published mechanical scoring system that meaningfully gates
binary outcomes uses **multiplicative gates first, then additive scoring on what
survives**. FICO is internally additive but applied after multiplicative regulatory
gates (US identity verification, frozen-credit blocks). Stripe Radar runs deterministic
rules before the ML score. This two-stage pattern is universal.

### B.2 Equal-weight vs optimized-weight

This is the empirical question already locked in Q2. Re-stating the consensus relevant
to mechanical scoring:

- **DeMiguel-Garlappi-Uppal (2009)**: 1/N beats 14 optimization models OOS.
- **ISM PMI**: explicitly equal-weighted (20% each) and has been the reference
  manufacturing index for 80+ years.
- **AQR QMJ**: equal-weight across sub-composites (profitability/growth/safety/payout).
- **Piotroski**: 9 criteria, 1 point each — fully equal-weighted.
- **FICO/Ohlson/Altman**: optimized-weight, but trained on millions of outcome
  observations. **Not** comparable to a system with <100 historical names.

**Implication for L3**: at our data scale (<100 historical successful-companies cases)
the equal-weight Smith-Wallis / DeMiguel result dominates. Optimized weights overfit.
This locks B.2 to **equal-weight at v0.1**, with a possible move to BB-pseudo-BMA+ at
v0.5+ once we have 100+ outcome observations (per Q2 Section 3 lock).

### B.3 Threshold setting: single-cutoff vs ordinal vs probabilistic

Three options observed in the literature:

1. **Single hard cutoff** (Piotroski 8+/9, Altman 1.81 / 2.99, fraud-rule tripwires).
   Pro: maximally interpretable, audit-friendly. Con: information loss near boundary;
   tiny score change flips decision.

2. **Ordinal bands** (FICO 300–579 / 580–669 / 670–739 / 740–799 / 800–850;
   Conference Board LEI signal grades). Pro: graceful degradation; preserves more
   information. Con: arbitrary band cuts.

3. **Probabilistic / continuous** (Ohlson logistic probability; Merton DD →
   default probability). Pro: full information preserved; calibrated. Con: requires
   sufficient outcome data to calibrate; harder to communicate.

**For L3**: use **single hard cutoff for fraud-signature gate** (binary
KEEP/EXIT), **ordinal bands for Tier-A composite** (e.g., A+/A/B/REJECT), and
**continuous score retained internally for tie-breaking and audit**. This matches
both FICO's "score number AND letter band" pattern and Stripe's "rule outcome AND
underlying ML risk score retained" pattern.

---

## Section C — Calibration approaches

### C.1 Logistic regression on historical outcomes

The Ohlson 1980 template:

1. Collect historical cases with binary outcome label (multi-bag winner / not).
2. Compute candidate predictors (founder tenure, ROIIC, etc.) as of t = decision time.
3. Fit logit: log(p / (1−p)) = β₀ + Σ βᵢ · xᵢ.
4. Validate by AUC, Brier score, calibration plot.
5. Convert coefficients to scaled point values via WoE/Information-Value pipeline
   (MathWorks scorecard reference; Listendata WoE tutorial).

**Honest caveat**: logistic regression at <100 events overfits. The Ohlson sample
was 105 failing + 2,058 healthy companies. We do not have that. Until we have
≥100 outcome-labeled candidates, logistic-fit weights are not advisable — equal
weights dominate (B.2 above; Q2 lock).

### C.2 Walk-forward validation

Standard k-fold CV is invalid for time-ordered scoring (data leakage; future
training, past test). **Walk-forward / expanding-window CV is the only valid
approach** (Hyndman §5.10; Alpha Scientist; ScienceDirect 2024 backtest-overfitting
study).

For L3:
- Train on candidates known by year T-3.
- Score candidates discovered in T-2, observe outcome at T.
- Roll forward.
- Track AUC stability, weight stability, and signal decay across folds.

This is consistent with the BacktestingFramework already in `src/backtesting/`
(walk-forward + embargo + DSR — see `framework.py`, `dsr.py`).

### C.3 Cross-reference: Q2 weight-optimization findings

From Q2 lock (commit 7d2d048):
- **v0.1**: equal-weight composite (Smith-Wallis equal-weight puzzle dominates at
  small N).
- **v0.5+**: BB-pseudo-BMA+ once N ≥ 100 outcomes available.
- BMA accounts for **weight uncertainty**, not just model selection (Hoeting et al. 1999).

L3 mechanical-scoring weights inherit this rule: equal-weight at v0.1, BB-pseudo-BMA+
on logistic-regression sub-models at v0.5+. No optimized weights before then.

---

## Section D — Edge-case handling

### D.1 Missing data

Three patterns observed; ranked by appropriateness for L3:

1. **Explicit "missing" bin with WoE-derived points (FICO/MATLAB scorecard
   approach)**. Treat "we have no data on founder tenure" as its own category
   with empirically-derived contribution. Best for production but requires
   outcome labels.

2. **Conference-Board LEI proportional re-weighting**: if k of 10 components
   missing, scale remaining (10−k) component weights to sum to 1. Preserves
   the index's intent without assuming missing-data direction.

3. **Conservative impute-as-fail** (multiplicative gate convention): if data
   missing on a kill-criterion, treat as fail. Strong-prior bias toward
   false-negative; appropriate when missed-multibagger is *less* costly than
   admitting fraud (NOT our use case — we have the opposite asymmetry).

**For L3**: use **LEI-style proportional re-weighting on Tier-A composite**
(missing data does not auto-fail, but does not get partial credit either),
and **explicit-no-data → REJECT** on fraud-signature gate (conservative on
the gate that prevents capital loss).

### D.2 Threshold setting

Per B.3, use a hybrid:
- Hard binary at fraud gate.
- Ordinal bands at Tier-A composite.
- Continuous score retained for audit / tie-break.

For our asymmetric loss (missed-multibagger more costly than false-positive at
<$1M scale), set **Tier-A threshold at the 60th percentile**, not the Piotroski
8+/9 (top 10–15%) level. Reason: at <$1M with a multi-bag goal, position
sizing handles the false-positive cost (small starter positions) but the missed
opportunity cost is irreversible.

This is *opposite* of how Piotroski-style screens are typically tuned for
institutional context (where false-positive = capital lost on a bad name) and
matches the small-AUM heuristic that "you can size your way out of a soft-bad
name but you can't size your way into a missed-multibagger."

### D.3 Tie-breaking

Three layers, applied in order:
1. **Continuous-score tie-break** (retained from B.3): higher continuous score
   wins.
2. **Fraud-margin tie-break**: fewer fraud-signature flags raised wins.
3. **Era-fit tie-break**: stronger era-fit wins.
4. **Bayesian posterior tie-break** (v0.5+): higher posterior probability of
   multi-bag outcome wins.

### D.4 Outlier robustness

Standard accounting-research convention: **winsorize at 1% / 99%** before
computing any ratio-based score (Leone working paper; Wikipedia Winsorizing).
This is independently the convention in AQR QMJ, Piotroski follow-up studies,
and Bayesian factor-model literature.

For L3:
- Winsorize all continuous inputs (ROIIC, founder tenure, growth rate) at
  1%/99% based on relevant peer-group distribution.
- Use **median-and-MAD** (not mean-and-SD) for any z-score normalization
  inside a sub-composite.
- Cap any single sub-score contribution at ±3 robust-z to prevent one outlier
  metric from dominating.

---

## Section E — Recommended mechanical scoring spec for L3 gate

### E.1 Fraud signature (6-criteria) — RECOMMENDED SPEC

**Pattern**: multiplicative knockout (any-fail = exit).
**Threshold**: 3+/6 flags = automatic REJECT (per existing spec).
**Justification**: this is the canonical "knockout" use case (Stripe Radar
deterministic rules; FICO regulatory gates; Pabrai disqualifiers). Additive
scoring here would let strength on 3 criteria offset failure on the other 3,
which is exactly the wrong behavior for fraud detection. Multiplicative-style
scoring rewards consistency (Add-or-Multiply tutorial).

**Concrete spec**:
```
fraud_flags = [
    check_revenue_recognition_anomaly(),     # binary
    check_audit_qualification_history(),     # binary
    check_related_party_concentration(),     # binary
    check_promotional_lang_density(),        # binary
    check_insider_selling_unusual(),         # binary
    check_governance_red_flags(),            # binary
]
n_flags = sum(fraud_flags)
fraud_decision = "EXIT" if n_flags >= 3 else "PASS"
fraud_score = n_flags  # retained for audit / tie-break
```

**Edge cases**:
- Missing data on any criterion → treat as flag raised (conservative).
- Document which criteria fired in the memo (`memos/<ticker>_cdd_<date>.json`).

### E.2 Tier-A signal checks — RECOMMENDED SPEC

**Pattern**: equal-weight additive, 4 binary criteria → 0–4 raw score.
**Threshold**: ≥3 of 4 satisfied = Tier-A PASS; 2/4 = WATCH; ≤1 = REJECT.

**Justification**:
- Equal-weight: Q2 lock at our N. DeMiguel-Garlappi-Uppal applies.
- Additive: these criteria are intentionally compensable (a great founder can
  partially substitute for missing per-share-value primary metric, etc.).
  Unlike fraud, no single Tier-A miss is disqualifying.
- 3-of-4 threshold (75%): more lenient than Piotroski 8/9 (89%) because of the
  asymmetric-loss argument in D.2.

**Concrete spec**:
```
tier_a_checks = {
    "founder_tenure_15y":     check_founder_tenure() >= 15,
    "per_share_value_metric": check_primary_metric_is_per_share(),
    "roiic_above_15":         compute_roiic_5y() > 0.15,
    "pivot_creates_multibag": check_pivot_optionality(),
}
tier_a_raw = sum(tier_a_checks.values())
tier_a_band = (
    "A" if tier_a_raw >= 3 else
    "B" if tier_a_raw == 2 else
    "REJECT"
)
```

**Missing-data handling**: LEI-style — if k of 4 unmeasurable, threshold scales
to ⌈0.75·(4−k)⌉. (e.g., 2 measurable, both must pass.)

### E.3 Era-fit binary — RECOMMENDED SPEC

**Pattern**: single binary check (right-thing-right-decade).
**Treatment**: gate, not score component.
**Justification**: era-fit is a knockout-style criterion (a great company in
a wrong-decade business is structurally capped). Treat as multiplicative
guard, not as Tier-A point.

**Concrete spec**:
```
era_fit_passed = check_era_fit(company, decade_thesis)
if not era_fit_passed:
    return "REJECT"   # short-circuit before Tier-A scoring
```

### E.4 Composite Tier-A score — RECOMMENDED PATTERN

**Two-stage pattern (matches Stripe Radar / FICO universal pattern)**:

```
# Stage 1: deterministic gates (multiplicative)
if fraud_score >= 3:           return REJECT_FRAUD
if not era_fit_passed:         return REJECT_ERA
if tier_a_band == "REJECT":    return REJECT_QUALITY

# Stage 2: composite ranking among survivors (additive)
composite_continuous = (
    1.0 * (tier_a_raw / 4)      # 0–1 normalized Tier-A
  + 1.0 * (1 - fraud_score/6)   # 0–1 fraud margin
  + 1.0 * era_fit_strength      # 0–1 era-fit (continuous variant)
) / 3.0   # equal-weight
```

This makes the L3 layer **multiplicative for hard knockouts, additive among
survivors, equal-weighted within the additive composite** — consistent with
the dominant pattern in production credit/fraud/factor systems.

---

## Section F — Production-system architecture

### F.1 Module structure

Recommended layout (extends existing `src/`):

```
src/
  scoring/
    __init__.py
    fraud_gate.py          # deterministic fraud_flags() + threshold
    tier_a_gate.py         # binary checks + composite
    era_fit_gate.py        # era-fit binary
    composite.py           # two-stage orchestrator
    weights.py             # parameters table (versioned)
    types.py               # ScoringResult dataclass
  backtesting/
    framework.py           # already exists
```

### F.2 Versioned parameters table

Per Kästner production-ML reproducibility convention, every weight, threshold,
and cutoff lives in `weights.py` with explicit version:

```python
SCORING_VERSION = "0.1.0"  # bump on any change

FRAUD_THRESHOLD = 3            # 3+/6 = exit
TIER_A_PASS_THRESHOLD = 3      # 3+/4 = pass
TIER_A_WATCH_THRESHOLD = 2     # 2/4 = watch
WINSORIZE_BOUNDS = (0.01, 0.99)
ROIIC_FLOOR = 0.15
FOUNDER_TENURE_FLOOR_YEARS = 15

# Equal weights at v0.1 per Q2 lock
TIER_A_WEIGHTS = {"founder": 0.25, "per_share": 0.25,
                  "roiic": 0.25, "pivot": 0.25}
```

### F.3 Determinism / auditability requirements

Every score must be reproducible from inputs. Concretely:

1. **Pure functions only** — no globals, no time.now(), no network calls.
   All inputs explicit in function signature.
2. **Frozen input snapshot** — store the data tuple used at decision time
   (matches existing memos/aapl_cdd_*.json pattern).
3. **Version stamping** — every memo includes SCORING_VERSION.
4. **Reproducibility test** — `tests/test_scoring.py` asserts that
   `score(snapshot_inputs)` returns bit-identical result on re-run.
5. **Walk-forward harness** — `BacktestingFramework` already implements
   walk-forward + embargo + DSR; reuse for scoring-version validation.

### F.4 Testing strategy

```
tests/
  test_fraud_gate.py        # boundary tests at 0/1/2/3/4/5/6 flags
  test_tier_a_gate.py       # boundary tests at 0/1/2/3/4 checks
  test_era_fit_gate.py      # binary
  test_composite.py         # two-stage orchestration
  test_scoring_versioning.py  # bit-identical reproducibility on snapshot
  test_walk_forward.py      # weight stability across folds
```

Each gate gets a property-based test: monotonicity (more flags ⇒ never lower
risk score), independence (changing one input doesn't perturb others), and
determinism (same input twice ⇒ same output bit-identical).

---

## Final report

**(a) Deliverable path**:
`/Users/sehoonbyun/Documents/equity-research-system/.claude/references/empirical/data-sources/Q1-Section5-mechanical-scoring.md`

**(b) Total scoring methods compared**: 12 systems analyzed in depth — FICO,
Altman Z-score (1968), Ohlson O-score (1980), Merton DD/KMV, ISM PMI, Conference
Board LEI, Chicago Fed NFCI, Conference Board CCI, AQR Quality-Minus-Junk,
Piotroski F-score, Greenblatt Magic Formula, plus the Stripe Radar / Upstart
hybrid-production templates.

**(c) Recommended spec for L3 fraud-signature gate**: **multiplicative knockout
at 3+/6 flags = REJECT**. Single hard cutoff. Missing data treated as flag
raised (conservative). Continuous flag-count retained for audit. Justified by
universal pattern across Stripe Radar, FICO regulatory gates, Pabrai
disqualifier checklists — every published fraud-style system uses
multiplicative-first knockouts, never additive compensation.

**(d) Recommended spec for L3 Tier-A composite**: **equal-weight additive
4-criterion sum, ordinal-band threshold (≥3 = A, 2 = WATCH/B, ≤1 = REJECT)**,
with LEI-style proportional re-weighting on missing data. Equal-weight per Q2
lock; additive because Tier-A criteria are intentionally compensable (great
founder partially substitutes for missing per-share-value framing, etc.); 75%
threshold (vs Piotroski's 89%) because of asymmetric loss at <$1M scale.

**(e) Honest answer on additive vs multiplicative for our use case**:
**Both, in a two-stage pipeline — and the order matters.** Multiplicative
hard-knockout gates first (fraud, era-fit), then additive equal-weighted
composite among survivors. This is the universal pattern in production
mechanical-scoring systems (FICO + regulatory gates; Stripe rules + ML score;
Upstart underwriting + reg compliance). Pure-additive systems (e.g., a single
weighted-sum L3 score) hide catastrophic flaws under aggregate score and are
empirically inferior for asymmetric-loss problems where a single criterion
(fraud) can wholesale invalidate the candidate. Pure-multiplicative systems
(e.g., AND across all criteria) are too brittle when criteria are imperfect
proxies and produce excess false-negatives. The two-stage hybrid avoids both
failure modes.
