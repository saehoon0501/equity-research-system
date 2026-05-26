---
description: Run BacktestingFramework on a memo or memo set. Walk-forward validation with embargo, DSR with trial reporting, PBO, pre/post-cutoff Sharpe split. Per v2-final §2.6.
argument-hint: <memo-set-id> | <ticker> [date-range]
---

# /backtest

**Status: v0.1 weeks 10-11 build target.** Not functional in v0.1 weeks 1-9. This file specifies what the command will do once BacktestingFramework lands.

## Argument

`<memo-set-id>` — backtests against a saved set of memos
OR
`<ticker> [date-range]` — backtests a single position based on a memo's recommendation

Optional flags:
- `--include-friction` (default: yes) — include realistic friction modeling
- `--counterfactuals all` (default) — include SPY, equal-weight, sector-matched, 60/40 baselines

## Procedure

Per v2-final §2.6 and `.claude/references/contamination-check.md`:

### 1. Pre-flight checks

- BacktestingFramework deployed (per the Backtesting + Sample Memo Generation step in BUILD_LOG.md)
- `mcp__postgres` connected for memo + Evidence Index access
- Sharadar fundamentals subscription active (`mcp__fundamentals`)
- `mcp__market_data` for price history

### 2. Load memo(s)

If memo-set-id: load all memos in the set.
If ticker: load the most recent CompanyDeepDive memo for that ticker.

### 3. Determine effective_cutoff

```
effective_cutoff = stated_model_cutoff + 6 months
```

Per phasing-plan.md §2.5.1 and Lopez-Lira et al. (2025). Models continue absorbing information through ongoing pretraining and RLHF data refreshes after stated cutoff. The 6-month buffer is conservative.

For each memo, determine if its effective_cutoff is in the past (post-cutoff testable) or future (pre-cutoff only — would need to wait).

### 4. Walk-forward validation

For each memo:
- Anchor entry date as the surfaced_date of the memo
- Forward-only execution: no using post-entry information to inform pre-entry decisions
- Embargo period between in-sample data and out-of-sample evaluation (Lopez de Prado purge logic)

### 5. Apply realistic friction

Per v2-final §2.6:
- Bid-ask spread per liquidity tier (computed from market_data)
- Market impact for orders >1% ADV
- Commission and SEC fees (operator's brokerage rates from configuration)
- **Tax cost modeling** for taxable account simulation

### 6. Compute metrics

For each memo:
- Realized return over horizon
- Sharpe ratio (annualized)
- Maximum drawdown
- Total holding period

For the set:
- Aggregate Sharpe with multiple-trial correction
- **Deflated Sharpe Ratio (DSR)** with explicit reporting of number of trials/parameter combinations
- **Probability of Backtest Overfitting (PBO)**

### 7. Pre-cutoff vs post-cutoff split

```
Pre-effective-cutoff sample:
  N memos
  Sharpe: <X>
  
Post-effective-cutoff sample:
  N memos
  Sharpe: <Y>

Degradation ratio: (X - Y) / X = Z%
```

If Z > 20%: flag (per phasing-plan.md §2.5.1, this is the contamination defense gate)
If Z > 40%: KILL CRITERION (per phasing-plan.md §2.6.1)

### 8. Counterfactual baselines (mandatory)

Per v2-final §2.6:

```
Counterfactual comparisons (over same period):
  - SPY buy-and-hold: Sharpe X, return Y
  - Equal-weight watchlist (no entry timing): Sharpe X, return Y
  - Sector-matched basket: Sharpe X, return Y
  - 60/40 portfolio: Sharpe X, return Y
```

Per phasing-plan.md §2.6.3 KILL CRITERION: if SPY or equal-weight beats the system on risk-adjusted basis post-cutoff, the strategy is sophisticated theater. Halt v0.1; the §7 sunk-cost question is asked early.

### 9. Output

```
BACKTEST RESULTS

SAMPLE: <N memos> | <date range>
EFFECTIVE CUTOFF: <stated cutoff + 6 months>

PRE-EFFECTIVE-CUTOFF (potentially contaminated):
  Sample size: N
  Sharpe: X
  Mean return: Y%
  Max drawdown: Z%

POST-EFFECTIVE-CUTOFF (uncontaminated test):
  Sample size: N
  Sharpe: X
  Mean return: Y%
  Max drawdown: Z%

DEGRADATION RATIO: <%>
GATE 2.5.1 STATUS: PASS (≤20%) | FAIL (20-40%) | KILL (>40%)

DSR: X (with N trials reported)
PBO: Y%
GATE 2.5.3 STATUS: PASS (DSR>0.5, PBO<50%) | FAIL

COUNTERFACTUAL COMPARISONS (over same period as post-cutoff):
  SPY buy-and-hold:        Sharpe X | Return Y%
  Equal-weight watchlist:  Sharpe X | Return Y%
  Sector-matched basket:   Sharpe X | Return Y%
  60/40 portfolio:         Sharpe X | Return Y%
  
  System vs SPY: <better/worse> by <X% Sharpe>
  System vs equal-weight: <better/worse> by <X% Sharpe>

KILL CRITERION 2.6.3 (counterfactuals beat system on risk-adjusted): TRIGGERED | NOT TRIGGERED

FRICTION MODELING:
  Bid-ask spread cost: <$X total>
  Market impact cost: <$X total>
  Commission + fees: <$X total>
  Tax cost (taxable account assumption): <$X total>

INTERPRETATION:
  <narrative interpretation of results>
  <confidence in the post-cutoff signal — is it noise or signal?>
  <any specific memos that drove outliers>

NEXT STEPS:
  - If KILL triggered: halt v0.1; redesign required
  - If FAIL on contamination but not kill: investigate which memos contributed; possibly mechanical contamination check has gaps
  - If PASS on all gates: proceed to next checkpoint
```

### 10. Persistence

Write to Postgres:
- Backtest run record (versioned)
- Per-memo results
- Aggregate metrics
- Counterfactual baselines

These feed Checkpoint 3 evaluation and the v0.1 → v0.5 advancement decision.

### 11. Anti-patterns to avoid

Per `docs/implementation-sequencing.md` week-11 anti-pattern (substance retained from the spec doc; the dated label refers to the original plan, the substance is timeless):

> Anti-pattern to avoid: Optimizing parameters this week to "improve the backtest output." Multiple-trials correction is in DSR for a reason; optimizing now and reporting the post-hoc DSR is the gameable version of the metric. Backtest with the parameters chosen in advance.

If backtesting an alternative parameter set: explicitly count it as an additional trial in DSR. Don't selectively report best parameters as if they were chosen first.

## When to use

- v0.1 Checkpoint 3 evaluation: generate the post-cutoff Sharpe vs counterfactuals comparison
- Validation of a strategy refinement (with explicit trial reporting)
- Periodic re-validation in v0.5 / v1.0 to detect drift

## When NOT to use

- Live position evaluation (use `/exit-check` instead — that's forward-looking)
- Pre-week-10 in v0.1 — BacktestingFramework not yet built

## Cost

Variable — depends on sample size and date range. For 30-memo sample over 5-year period: ~$5-15 per backtest run (mostly numerical computation; LLM only used for narrative interpretation).
