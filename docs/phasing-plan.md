# Phasing Plan: Two-Layer Investment Research System

**Status:** Phasing companion to v2-final-spec.md
**Purpose:** Translate the v2-final spec into a buildable, real-money-safe sequence with explicit gates, kill criteria, and a wind-down protocol
**Audience:** The future tired version of you — the one running this six months in, with a position down 18%, who missed a reconciliation alert and is rationalizing why the v0.5 → v1.0 gate criteria really apply to this specific situation. Every threshold in this document is written to survive that version's motivated reasoning.

---

## 0. Why This Document Is Adversarial

The version of you writing this is energized and disciplined. The version of you running it six months in is tired, has lost money, and is rationalizing.

**This document is the contract between those two versions.**

Operating principles for everything below:

1. **Numerical thresholds, not qualitative ones.**
2. **Dated deadlines, not open-ended evaluations.**
3. **"Must do X before Y" gates, not "should consider X."**
4. **Pre-committed decision trees, not in-the-moment judgment.**
5. **Specific salvage value, not vague consolation.**

If you find yourself wanting to soften a threshold while reading this six months from now, that's the threshold doing its job. Tighten it, don't relax it.

---

## 1. Phasing Principles

### 1.1 Why phase at all

Profit Mirage paper documented 50–72% Sharpe decay across published frameworks when evaluated post-knowledge-cutoff. There is no a priori reason to believe v2-final escapes this; the only honest answer is "we'll find out."

Phasing exists because the cost of finding out scales with how much money is at stake.

### 1.2 What each phase validates

| Phase | Validates | Cost of being wrong |
|---|---|---|
| **v0.1** | Contamination defense actually works. Backtest produces honest numbers. Evidence Index schema is sound. | Time only. No capital at risk. |
| **v0.5** | Operational machinery functions under real conditions. Reconciliation, safety rails, daily orchestration, alerts, calibration tracking all run reliably. Position sizing exercises at v1.0 parameters. | 10–20% of intended capital. Bounded. |
| **v1.0** | The alpha question itself, asked honestly only after the system has earned the right. | Full intended capital. |

### 1.3 Why kill criteria are real

**Rule:** When a kill criterion fires, the response is not to argue about whether it really fired. The response is to investigate why, document the investigation, and either fix the underlying issue (returning to the prior phase) or wind down. Arguing the threshold itself is out of bounds.

### 1.4 The 20% gate is held firm

The v0.1 gate sets post-cutoff backtest degradation at ≤20%. This is stricter than the public-frameworks baseline (50–72% per Profit Mirage), but it has to be — the entire architectural premise of the v2-final spec is that mechanical contamination defense produces materially better numbers than the public frameworks did.

Relaxing to 30% buys 10 percentage points of comfort at the cost of the gate's job. **Held firm.**

---

## 2. Phase v0.1: Paper-Only Foundation

### 2.1 Purpose

Build the infrastructure spine. Validate that the mechanical contamination defense produces materially better post-cutoff backtest performance than public-frameworks baselines. Validate that the Evidence Index schema and agent harness are sound under real workloads.

Zero capital at risk. No watchlist in any operational sense. No daily orchestration. The system runs only as a backtest harness with one agent end-to-end (CompanyDeepDive) producing memos against historical data.

### 2.2 Entry criteria

- v2-final spec frozen
- Decision committed to ~12 weeks of build before any real money
- Provider accounts established with training-disabled status verified

### 2.3 Scope of work

**Infrastructure spine:** TimescaleDB; PostgreSQL JSONB; append-only Predictions DB; append-only Counterfactual Ledger; append-only Evidence Index with retention tiering; pluggable data layer with fallback chain; Sharadar Core Fundamentals subscription active.

**Agent harness:** Standardized interface; versioned prompts; token/cost tracking; mandatory Evidence Index write hook; mechanical contamination check; process-rubric grading hook; model-family configuration check at startup (under Path A this is replaced with the documented override; see BUILD_LOG.md Day 1).

**One agent live: CompanyDeepDiveAgent** with mandatory output ordering, industry-specific addenda, full output schema with Evidence Index references for every claim per definition rule.

**BacktestingFramework:** Walk-forward validation with embargo; DSR with explicit reporting of trials; PBO; pre-effective-cutoff vs post-effective-cutoff split with `effective_cutoff = stated_cutoff + 6 months`; Sharadar point-in-time fundamentals; realistic friction modeling; counterfactual baselines.

**Sample of memos:** ≥30 historical names; mix of mega-cap and mid-cap; mix of pre- and post-effective-cutoff entry dates; reviewable_predictions tracked through to resolution.

### 2.4 Expected duration

**Target: 12 weeks from start of build (FTE pace).** For evening/weekend pace, expect 18–22 weeks. **Kill criterion remains 24 weeks regardless of track.**

### 2.5 Phase gates

To advance from v0.1 to v0.5, **all** of the following must be true.

**Gate 2.5.1 — Contamination defense validated:**
- Sample size: ≥30 memos
- Pre-effective-cutoff Sharpe and post-effective-cutoff Sharpe both reported
- Degradation ratio: `(pre_sharpe - post_sharpe) / pre_sharpe`
- **Required:** degradation ≤ 20%

**Gate 2.5.2 — Mechanical contamination check coverage:**
- ≥99% of dated claims in sample memos have Evidence Index references that resolve to real rows predating claim resolution dates
- Manual audit of 50 random claims with zero false-pass

**Gate 2.5.3 — Backtest discipline:**
- DSR > 0.5 on post-cutoff sample
- PBO < 50%
- Counterfactual baselines computed and reported

**Gate 2.5.4 — Infrastructure soundness:**
- Append-only databases verified
- Evidence Index retention tiering tested with synthetic 8-quarter data
- Pluggable data layer fallback chain functions correctly

**Gate 2.5.5 — Cost model:**
- Per-memo inference cost measured
- Projected monthly cost for v0.5 cadence within $400/mo budget

**Required date:** Gates evaluated by week 14 from start.

### 2.6 Kill criteria

**Kill 2.6.1 — Post-cutoff degradation >40%:** Contamination defense not working at architectural level. Halt; redesign.

**Kill 2.6.2 — Mechanical check false-pass rate >2%:** Evidence Index implementation unsound. Halt until rebuilt.

**Kill 2.6.3 — Counterfactual baselines beat the system on risk-adjusted basis:** SPY or equal-weight has higher post-cutoff Sharpe. The system is sophisticated theater. Halt.

**Kill 2.6.4 — Total v0.1 build duration exceeds 24 weeks:** Spec too complex to ship at individual-investor scale. Halt; revise spec, do not compress timeline further.

### 2.7 Phase-completion checklist

```
□ All four phase gates (2.5.1 through 2.5.5) passed with documented evidence
□ Sample memo audit (50 claims manual review) completed with zero false-pass
□ Schema review: is anything in the Evidence Index, Predictions DB, or
  Counterfactual Ledger schema load-bearing for v0.5 that we want to revise
  before progressing? If yes, revise now, not later.
□ Append-only verification: each database has a deletion/update attempt
  test that demonstrates the constraint cannot be violated
□ Provider training-data status documented per provider, with explicit evidence
□ Cost model: per-agent cost projection for v0.5 documented and within budget cap
□ Sharadar subscription active; data integrity validated against ≥3 known delistings
□ Pluggable data layer: each fallback chain tested with primary-source failure simulation
□ Mechanical contamination check: ≥99% coverage on dated claims, ≤2% false pass
□ Failure-mode review: which v2-final §7 failure modes does v0.1 evidence
  validate as mitigated? Document explicitly.
```

---

## 3. Phase v0.5: Limited Real Money

### 3.1 Purpose

Validate operational machinery under real conditions. The point of v0.5 is **not** to test the alpha. The point is to validate that the machine itself works under live conditions.

### 3.2 Entry criteria

- All v0.1 phase gates passed
- v0.1 phase-completion checklist signed off
- All six agents implemented and tested in dev (Path A: all on Anthropic via Claude Code subagents)
- Brokerage reconciliation protocol implemented and tested with synthetic drift scenarios
- Provider training-data status re-verified at v0.5 entry

### 3.3 Scope of work

- **Watchlist:** 3–5 names, all passing extra-high conviction bar (§3.7)
- **Capital:** 10–20% of intended v1.0 deployment
- **Daily orchestration live:** post-market-close + 30 min cron
- **All six agents running** in their routing tiers
- **Brokerage reconciliation live:** market close + 1 hour
- **Manual monthly review** as LearningLoop substitute

### 3.4 Expected duration

**Target: 9–12 months. Not 3 months. Not 6 months.**

The duration is set by prediction-resolution math:

```
Calibration data per agent requires ≥30 resolved predictions
CompanyDeepDive runs ~3x/month + quarterly re-underwrites
Each memo includes ~3 reviewable predictions
Most predictions resolve on quarterly horizons (3 months)

Time to 30 resolved per agent = 9–12 months realistic
```

The timeline is not emotionally negotiable.

### 3.5 Phase gates

**Gate 3.5.1 — Operational reliability:**
- Reconciliation success rate ≥98% over rolling 90 days
- No more than 1 reconciliation failure unresolved beyond same-day
- Zero hard concentration limit violations
- Zero unauthorized trades

**Gate 3.5.2 — Calibration data sufficiency:**
- ≥30 resolved predictions per agent
- Per-agent Brier score computed and trending non-degrading over rolling 90-day window

**Gate 3.5.3 — Regime diversity in resolved predictions:**
- Resolved predictions span at least 2 of {early-cycle, mid-cycle, late-cycle, panic, euphoric}
- **No more than 60% of resolved predictions in any single regime** (operative gate; 70% is hard ceiling)
- If v0.5 occurs entirely within one regime, **the phase extends** until regime diversity is met. Calendar duration alone is insufficient.

**Gate 3.5.4 — Counterfactual ledger:**
- Counterfactual ledger has accumulated entries for every system action
- Quarterly counterfactual report has been generated at least 3 times
- System's risk-adjusted performance over v0.5 is no worse than -5% Sharpe gap to SPY

**Gate 3.5.5 — Cost model held:**
- Monthly inference cost over rolling 6 months stayed within $400/mo budget cap
- No hard-cap halts triggered
- Prompt caching demonstrably reducing cost vs un-cached baseline

**Gate 3.5.6 — Process rubric compliance:**
- EvaluatorAgent hard-gate failure rate trending non-increasing
- ≥95% of CompanyDeepDive outputs pass all hard gates on first submission by month 9

**Required date:** Gates evaluated no earlier than month 9. **No advancement before month 9 even if gates technically met — duration floor is structural.**

### 3.6 Kill criteria

**Kill 3.6.1 — Reconciliation failures more than monthly:** Operational machinery unreliable. Halt.

**Kill 3.6.2 — Calibration degrading two consecutive months:** System getting worse, not better. Halt.

**Kill 3.6.3 — Single-position 35% drawdown without thesis re-underwrite revealing systemic blind spot:** Halt.

**Kill 3.6.4 — Portfolio drawdown >25% during v0.5:** System cannot bound risk. Halt.

**Kill 3.6.5 — Provider training-data status changes mid-phase:** Halt immediately.

**Kill 3.6.6 — v0.5 exceeds 18 months:** System not reaching steady state. Halt; investigate.

### 3.7 v0.5 position discipline sub-spec

Position sizing in v0.5 is not "scaled-down v1.0." Kelly fractions on tiny capital are arbitrary; the math doesn't translate. The framing:

> Positions at the size you'd take if you were running v1.0, but only on names that pass an extra-high conviction bar.

**Concrete rules:**
- **Capital deployed:** 10–20% of intended v1.0 capital. Cash held in money market on the rest.
- **Position size:** computed by full v1.0 PositionSizingModel. Not scaled down.
- **Number of positions:** 3–5
- **Conviction bar:** PMSupervisor's `final_conviction` must be ≥0.7
- **Watchlist:** 3–5 names approved by full v1.0 watchlist process
- **Exits:** Full ExitSignalModel with tax-awareness; wash-sale path selection enforced

### 3.8 Phase-completion checklist

```
□ All six phase gates passed with documented evidence
□ Calendar duration ≥9 months (no early advancement regardless of gate status)
□ Regime diversity in resolved predictions confirmed
□ Reconciliation log audit: every failure documented with root cause + fix
□ Schema review: anything load-bearing for v1.0 to revise before progressing?
□ Cost model held over rolling 6-month average
□ Provider training-data status re-verified at v0.5 exit
□ Counterfactual ledger sanity check: per-agent attribution computed
□ Process rubric audit: ≥95% first-submission pass rate over last 90 days
□ Position discipline sub-spec adherence verified
□ Tax-loss harvest sub-routine exercised at least once with wash-sale path documented
□ Failure-mode review: which v2-final §7 failure modes does v0.5 evidence validate?
```

---

## 4. Phase v1.0: Full Deployment

### 4.1 Purpose

Full intended capital. Full watchlist scale (30–50 names). The alpha question, asked honestly only after v0.1 and v0.5 have validated.

### 4.2 Entry criteria

- All v0.5 phase gates passed
- v0.5 phase-completion checklist signed off
- v0.5 ran for ≥9 months calendar
- v0.5 produced regime-diverse calibration data
- Schema and infrastructure decisions confirmed sound or revised before v1.0
- Provider training-data status re-verified at v1.0 entry

### 4.3 Scope of work

- **Watchlist:** Scale from 3–5 to 30–50 names over 6 months
- **Capital:** Deploy remaining 80–90% over 6 months. Phased, not lump-sum.
- **LearningLoop activation:** evaluated at v1.0 month 6 against §4.5 below
- **Quarterly per-name re-underwrites:** activated as standing schedule
- **Annual rubric review:** scheduled

### 4.4 Expected duration

v1.0 is not time-bounded. It runs until either:
- The month-18 honest-answer rubric (§5.4) determines wind-down
- A kill criterion fires
- The system is intentionally retired for external reasons

### 4.5 LearningLoop activation gate

**Gate 4.5.1 — Counting thresholds:**
- ≥90 resolved predictions across all agents
- ≥10 closed positions with completed postmortems

**Gate 4.5.2 — Regime diversity in outcome data:**
- Resolved predictions span ≥3 regime classifications
- No single regime represents >50% of resolved predictions
- Closed positions span ≥2 regimes

**Gate 4.5.3 — Outcome data integrity:**
- Counterfactual ledger entries complete and consistent
- Per-agent calibration histories show no anomalous regime breaks
- Process rubric scores explicitly excluded from LearningLoop training inputs (verified by code)

**Gate 4.5.4 — Strategy quality bar (two-condition):**
- **Rolling 6-month Sharpe difference ≥0 vs SPY**
- **AND not declining over the prior 3-month window**
- If performance is below SPY, LearningLoop activation **delays** until either performance recovers or the §5.4 wind-down rubric resolves the question

LearningLoop activation is a one-way door.

### 4.6 Kill criteria

**Kill 4.6.1 — 25% portfolio drawdown:** Hard halt.

**Kill 4.6.2 — Reconciliation failures escalate:** Same threshold as v0.5.

**Kill 4.6.3 — Calibration degrading two consecutive months at v1.0 scale:** System regressing.

**Kill 4.6.4 — Counterfactual ledger shows persistent value destruction:** Quarterly reports show system underperforming SPY for ≥2 consecutive quarters by ≥3% annualized.

**Kill 4.6.5 — Provider training-data violation discovered:** Halt immediately.

### 4.7 Phase-completion checklist (LearningLoop activation)

```
□ All four LearningLoop activation gates passed with documented evidence
□ Outcome data audit: every resolved prediction's resolution evidence
  preserved in Evidence Index
□ Counterfactual ledger audit: per-agent attribution computed
□ Code verification: LearningLoop's training data sources programmatically
  exclude process rubric scores. Test verified.
□ Rollback plan: documented and rehearsed
```

---

## 5. Cross-Phase Concerns

### 5.1 What carries through phases

The infrastructure spine is built once in v0.1 and inherited:
- TimescaleDB schemas
- Evidence Index schema and retention tiering
- Append-only Predictions database
- Append-only Counterfactual Ledger
- Agent harness with mechanical contamination check
- Pluggable data layer
- Process rubric definitions
- Versioned prompt registry

### 5.2 What gets revised between phases

**Allowed revisions at phase boundaries (with documented justification):**
- Process rubric criteria
- Agent prompts (versioned)
- Routing tier assignments
- Industry-specific addenda
- Pluggable data layer fallback chains

**Never revised mid-phase except to fix bugs:**
- Evidence Index schema
- Mechanical contamination check logic
- Process rubric hard gates
- Hard concentration limits
- Brokerage reconciliation protocol
- **Phase gate thresholds**

### 5.3 Calibration data hygiene across phases

- Predictions resolved during regime transitions are flagged
- Predictions for which underlying source data was later revised are flagged
- Per-agent calibration computed on rolling windows, never lifetime
- Calibration drift detection runs at every phase boundary

### 5.4 The month-18 honest-answer rubric

This is the structural decision point that prevents v1.0 from running on inertia. Begins clock at v1.0 entry; fires at v1.0 month 18 ± 30 days.

**The decision tree is pre-committed.** Future-tired-you with a position down 18% does not get to argue about which inputs to use or how to weight them.

**Three boolean inputs:**

**Input 1 — SPY performance comparison:**
- TRUE if `(system_return - SPY_return) / annualized_volatility ≥ 0`
- TRUE means "system performed at least equivalently to SPY on risk-adjusted basis"

**Input 2 — Counterfactual value-add (active management specifically):**
- TRUE if system net-of-everything return > DCA-into-watchlist baseline by ≥1% annualized
- TRUE means "the system's specific entry-timing, sizing, and exit decisions added measurable value over passive watchlist execution"

**Important attribution caveat:** Input 2 specifically tests the *active management value-add* (timing, sizing, exits) — not the watchlist construction value. If the watchlist itself is great but DCA on it beats the timing/sizing/exit logic, that's a real signal that the active layer is overhead, even if the watchlist is valuable. This is a legitimate outcome the rubric should be willing to identify; the recommendation in such a case is "use the research, drop the active layer."

**Input 3 — Per-agent calibration trend:**
- TRUE if at least 4 of 5 agents show non-degrading Brier scores from month 12 to month 18
- TRUE means "the system is learning, not regressing"

**Decision tree:**

```
Failures (count of FALSE inputs):
  0 failures → CONTINUE. System is performing as designed.
  1 failure → CONTINUE with documented monitoring of the failed input.
              Decision re-evaluated at month 24.
  2 failures → CONDITIONAL EXTENSION. 6-month conditional period at v1.0
               with tighter criteria: at month 24, all three inputs
               must be TRUE or wind-down begins.
  3 failures → WIND-DOWN BEGINS. The system has not earned its
               continuation. Proceed to §5.5 wind-down protocol.
```

There is no fourth path.

### 5.5 Wind-down protocol

**Total wind-down window: 60 days from decision date.**

**Sequencing (in order):**

**Days 0–14: Assessment and harvest setup.** Audit positions; identify tax-loss harvest candidates; select wash-sale paths; document plan.

**Days 14–30: Tax-loss harvesting executed.** Sell loss positions per chosen wash-sale paths. No re-entry during wind-down.

**Days 30–45: Short-term gains exited in offset pairs.** For positions with short-term unrealized gains, pair with realized losses where possible.

**Fallback for days 30–45:** If realized losses are insufficient to offset short-term gains, defer short-term gains to day 45+ where possible to push into long-term territory; where deferral isn't possible because positions hit 1-year mark before day 45, document and accept the short-term tax cost as the price of the wind-down decision.

**Days 45–60: Long-term gains exited last.** Long-term gains taxed at preferential rate; exit last to maximize tax efficiency.

**Day 60: Final accounting.** All positions closed or formally exempted; final tax accounting; counterfactual ledger frozen with terminal state recorded; Evidence Index moved to long-term cold storage; salvage-value documentation produced (§5.6).

**Hard rule:** No new positions entered during wind-down.

### 5.6 Salvage value (concrete)

**Artifact 1 — Codebase as portfolio-grade demonstration of applied agent systems engineering.**

**Artifact 2 — Evidence Index as queryable research history.** Every claim, every source, every date, retained in append-only structured form.

**Artifact 3 — Calibration data as pedagogical material.** Per-agent calibration histories — Brier scores, prediction outcomes, counterfactual baselines — are honest empirical data on how an individual investor's *own* judgment performs over multi-year horizons.

**Caveat for Artifact 3:** Pedagogical value scales with regime diversity of the underlying data. A v1.0 that ran in a single regime before wind-down produces calibration data of limited generalizability — useful as a record but not as an inference base for future regimes. The same regime-diversity condition that gates LearningLoop activation also gates this artifact's standalone value.

**Artifact 4 — Eval framework as transferable methodology.** The process/outcome rubric separation, mechanical contamination check, and counterfactual ledger transfer to any future LLM-driven decision system.

**The honest framing:** wind-down means the strategy did not produce excess return. It does not mean the system, the engineering, or the methodology was worthless. Those are separable.

---

## 6. What This Document Protects Against

The phasing structure exists to prevent specific, named failure modes.

**6.1 — Pressure-testing gates by skipping them.** Prevented by §2.5 numerical thresholds; §2.7 phase-completion checklist requiring documented evidence; §1.3 explicit rule.

**6.2 — Compressing v0.5 duration under impatience.** Prevented by §3.4 explicit prediction-resolution math; §3.5.2 numerical gate; §3.5.3 regime-diversity gate.

**6.3 — Activating LearningLoop on insufficient data.** Prevented by §4.5.2 regime-diversity gate; §4.5.3 outcome data integrity audit.

**6.4 — Continuing past month-18 because the project has identity attached.** Prevented by §5.4 pre-committed decision tree with no escape hatch; §5.6 explicit salvage-value framing.

**6.5 — Soft language creating escape hatches.** Prevented by every gate being numerical; every checklist using "must"; every threshold dated.

**6.6 — Numerical threshold drift under stress.** Prevented by §1.4 explicit statement; §5.2 explicit rule.

**6.7 — Wind-down dragging into bagholding.** Prevented by §5.5 hard 60-day window; day-by-day sequencing; rule against new positions during wind-down.

**6.8 — Sophisticated theater.** Prevented by §2.6.3 v0.1 kill criterion; §3.5.4 v0.5 counterfactual gate; §4.6.4 v1.0 counterfactual kill criterion; §5.4 month-18 rubric.

**6.9 — Provider IP leakage discovered too late.** Prevented by v2-final §4.7 startup check; §3.2 v0.5 entry re-verification; §4.2 v1.0 entry re-verification; §3.6.5 / §4.6.5 kill criteria.

**6.10 — Schema decisions becoming locked-in too early.** Prevented by §2.7 v0.1 checklist explicit prompt to revise schema before v0.5; §5.2 list of what may be revised at phase boundaries.

**6.11 — Calibration data contamination invalidating LearningLoop training.** Prevented by §5.3 hygiene rules; §4.5.2 regime-diversity gate; §4.5.3 integrity audit.

**6.12 — Position sizing in v0.5 producing data that doesn't transfer.** Prevented by §3.7 position discipline sub-spec — v1.0 sizing on extra-high conviction names.

---

## 7. Summary

**Three phases, structurally distinct:**
- v0.1 (12 weeks FTE / 18–22 weeks evenings): paper-only, validates contamination defense and infrastructure
- v0.5 (9–12 months): limited real money, validates operational machinery at v1.0 sizing parameters
- v1.0 (open-ended, evaluated at month 18): full deployment, alpha question asked honestly

**Three load-bearing artifacts:**
- Phase gates: numerical, dated, no escape hatches
- Phase-completion checklists: questions future-tired-you must answer yes to, with documented evidence
- Month-18 rubric: pre-committed decision tree on whether v1.0 has earned continuation

**One operating principle:** This document is the contract between disciplined-now-you and tired-then-you.

**One honest acknowledgment:** Wind-down is a possible outcome, not a failure of the project. The strategy producing alpha and the system producing value are separable questions.
