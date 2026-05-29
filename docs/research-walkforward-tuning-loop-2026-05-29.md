# Research: walk-forward tuning-loop best practices (§14.11 #1/#3/#5/#6)

**Date:** 2026-05-29 · **Source:** deep-research pass (19 sources fetched, 73 claims, 25 adversarially verified, 24 confirmed / 1 killed). **Status:** research-grounded recommendations — **#1/#3/#5/#6 remain operator decisions** (genuinely theirs per §1); this note informs them, it does not resolve them. Feeds the §14.11-gated specs: `execution-daemon`, `walkforward-tuning-loop`, `in-session-monitor`.

**Source tier:** Q2 + the overfitting-guard half of Q4 rest on top-tier primary academic sources (Bailey, Borwein, López de Prado, Zhu — SSRN / davidhbailey.com / AMS Notices), uncontested. Q3 evidence is peer-reviewed but **macro/volatility forecasting, not trading** (transfer is by analogy). Q1 rests on a single counterexample (Freqtrade docs). The ML-ops champion/challenger definition was **refuted (0-3)** — unsupported here.

---

## Cross-cutting finding (affects the whole §14 framing)

**Walk-forward is the *weakest* OOS validator on overfitting metrics** vs Combinatorial Purged Cross-Validation (CPCV): on synthetic data CPCV showed lower Probability of Backtest Overfitting (PBO) and superior Deflated Sharpe Ratio than K-Fold, Purged K-Fold, and especially Walk-Forward (which had "weaker false-discovery prevention, increased temporal variability, weaker stationarity"). [Arian/Norouzi/Seco, *Knowledge-Based Systems* 305, 2024 — single synthetic study, caveat]. **Implication:** the §14 loop should treat a single forward window as *necessary-but-weak* evidence and prefer CPCV-style validation in the promotion gate where feasible — not rely on one forward window as gold-standard. (Operator's call whether to amend §14.6.)

---

## #3 — Forward-window floor → REFRAME (was: "min-N closed trades / survival events")

**The frame is wrong.** There is **no fixed minimum OOS trade count** in the canonical literature. The min-N-closed-trades question dissolves into a *joint* significance condition over sample length, number of trials, and non-Normality.

- **Use PSR + MinTRL** (Probabilistic Sharpe Ratio / Minimum Track Record Length, Bailey & López de Prado, *J. Risk* 15(2) 2012): significance sized in **observation count** (not calendar, not trade count), and **grows with negative skew, fat tails, higher confidence, and a smaller Sharpe**. Example: proving Sharpe 2 > 1 at 95% needs 2.73y IID-Normal → **4.99y (+54%) for a realistic non-Normal hedge-fund distribution.**
- **Leveraged, non-Normal book ⟹ materially MORE OOS data** before promotion — directly relevant to our 4x/5x CFD book.
- Gate against a **non-trivial benchmark Sharpe (e.g. 0.5)**, with skew/kurtosis as explicit inputs.

**Recommendation:** drop the trade-count floor; the tuning-loop gate sizes OOS sufficiency via **MinTRL (observation count, skew/kurtosis-aware)** and requires **PSR ≥ chosen confidence** against a non-trivial benchmark. Adapt the "metric" to our §13 **survival-net risk-adjusted return** (PSR/MinTRL is the significance wrapper around whatever risk-adjusted metric).

## #6 — Promotion criterion → STRENGTHEN (was: "beat champion over ≥K windows")

The overfitting-guard core is well-specified and **purpose-built for an autonomous (no-sign-off) gate** (§14.11 #2):

- **Deflated Sharpe Ratio (DSR)** [Bailey & López de Prado, *JPM* 2014]: a PSR whose rejection threshold **rises with the trial count**. Deflates using **five logged inputs**: skewness, kurtosis, sample length T, variance of Sharpes across trials, and **N = effective independent trials**. Reject if DSR < confidence (e.g. 0.95). **The gate MUST log N.**
- **Never gate on in-sample Sharpe** — high IS Sharpe carries *no* OOS information; past a point, optimizing IS *lowers* OOS (worked example: 100% of IS Sharpes positive, ~78% of OOS Sharpes negative).
- **MinBTL ≈ 2·ln[N]/E[max]²** bounds search breadth to available history: **≤~45 independent configs at 5y**; just **~7 configs at 2y** already manufacture IS Sharpe 1 / OOS 0. Reduce correlated parameter sweeps to an **effective N** before applying.
- **Add a PBO / CSCV diagnostic** (Probability of Backtest Overfitting via Combinatorially Symmetric Cross-Validation) alongside DSR — model-free, swaps all IS/OOS partitions.

**Recommendation:** the automated promotion gate = **DSR (multiple-testing-corrected, effective-N logged) + PSR/MinTRL significance + PBO diagnostic**, on the **survival-net risk-adjusted return** metric (§13); prefer **CPCV** over a single walk-forward window; never gate on IS Sharpe. **Open (literature silent):** the *decision-rule specifics* — required OOS **margin** over the incumbent, number of **consecutive** windows, and **anti-churn / hysteresis** — are NOT resolved by the literature; they remain operator judgment (set provisionally, calibrate). This is also the BUILD_LOG-promotion bar (§7 Q6).

## #5 — Anchored vs rolling split-memory → DEFENSIBLE BUT UNPRECEDENTED (was: "confirm §14.6")

- Window choice is a **first-order, regime-conditional** decision; **rolling helps under nonstationarity**, neither universally dominates, and **dynamic recency-based selection** ("Momentum of Predictability") is defensible [Inoue-Jin-Rossi 2017; Feng et al. 2024; Giannellis et al. 2025].
- The **split-memory idea** (anchored for tail/risk/survival, rolling for edge/return) is **consistent** with regime-conditionality **but has NO direct precedent** — all evidence is macro/volatility forecasting, not trading; it is the operator's extrapolation.

**Recommendation:** keep the §14.6 split as a **theoretically-defensible default**, but record it as a **hypothesis to validate on the book**, not established practice; consider **data-driven (loss-minimizing) or recency-based window selection** rather than a static commitment. (Softer than "confirm" — adopt provisionally, validate.)

## #1 — Version-pinning open positions → NO PRECEDENT; FIRST-PRINCIPLES + §16.1 interaction (was: "confirm §14.5 version-pinned lifecycle")

- **No best-practice endorsement** of either posed option (pin vs flat-book). The only documented production system (**Freqtrade**) **pins nothing** — live loaded code governs already-open positions on a ~5s loop, in-memory state reset on reload. That is the **riskier third option** (live code mutates in-flight management) and a **cautionary counterexample**, not a recommendation.
- **Therefore version-pinning is a deliberate safety choice beyond what open-source provides** — defensible on first-principles for a leveraged book (the Freqtrade approach is exactly the corruption risk §14.5 names), but **not externally precedented**.
- **⚠️ §16.1 interaction (key):** the paper-phase **flat-before-closure / intraday-flat invariant** (other session's §16.1 edit) means the book is **flat at the after-market walk-forward boundary** → version changes deploy against a **flat book** → **#1 is largely MOOT for the paper phase** (the "flat book at deploy" happens naturally). Version-pinning becomes load-bearing **only when multi-day holds go live** (post-paper).

**Recommendation:** adopt **version-pinned lifecycle (§14.5) as the design target for the eventual multi-day live phase** (first-principles safety; the live-code-governs-open-positions counterexample is what to avoid), but note it is **deferred-in-practice for the paper phase** because §16.1's intraday-flat makes the book flat at deploy. Flag as a first-principles choice, not a cited best practice.

---

## Open gaps the literature did NOT resolve (carry to the specs)
- Institutional (non-open-source) version-pinning patterns for mid-hold config/model changes — unresolved.
- Direct trading precedent for split-memory-by-parameter-type — none found.
- ML-ops champion/challenger promotion mechanics (shadow/parallel eval, margins) — the only source was **refuted**; unsupported here.
- Promotion decision-rule specifics (margin / consecutive-window count / anti-churn hysteresis) — literature silent; operator judgment, calibrate empirically.

## Net changes vs my earlier "confirm the doc" recommendations
- **#3:** flipped — no trade-count floor; PSR/MinTRL significance (observation-count, skew/kurtosis-aware; more data for a leveraged book).
- **#6:** strengthened — DSR + PSR + PBO gate, log effective N, never gate on IS Sharpe, MinBTL caps search breadth, prefer CPCV; decision-rule specifics remain operator judgment.
- **#5:** tempered — defensible default, but validate (no trading precedent); consider dynamic window selection.
- **#1:** reframed — no precedent + a cautionary counterexample; version-pinning is a first-principles safety target, and §16.1's intraday-flat makes it moot for the paper phase.
