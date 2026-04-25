# Exit Triggers (Tax-Aware)

Per v2-final §2.3. Used by `/exit-check <ticker>` command.

## Trigger priority order

The first trigger to fire wins. Triggers are evaluated in priority order:

### Priority 1 — Thesis-driven (NEVER suppressed for tax)

- **PMSupervisor downgrades thesis** (materiality-3 escalation resolved as thesis-broken)
- **Thesis pillar fails its KPI test at scheduled review** ← *the highest-quality exit signal in the system*

When a falsifiable claim is falsified, the position exits regardless of price action or tax considerations. **Capital protection beats tax optimization when the underwriting is wrong.** This is the ONE category that bypasses tax-aware logic.

### Priority 2 — Risk-driven (tax-aware)

- Drawdown from entry exceeds invalidation level set at entry
- Position size grown beyond max band due to appreciation (trim to band)
- Correlation with other holdings exceeds threshold (concentration risk)

### Priority 3 — Valuation-driven (tax-aware)

- Price exceeds CompanyDeepDive `target_price` by >20%
- Forward P/E exceeds 75th percentile of name's 10-year history

### Priority 4 — Technical (tax-aware)

- Break below 200-day SMA on volume
- Trend structure change (lower highs and lower lows, 3+ weeks)
- Distribution pattern detected (rising price, falling OBV)

### Priority 5 — Time-driven (tax-aware)

- Position held >24 months without thesis re-validation
- Position has stagnated (within ±10% of entry) for >18 months while opportunity cost rising

## Tax-awareness logic (applied to Priority 2–5 only)

```
if position.days_held < 365 and trigger_priority != 1:
    days_to_lt_threshold = 365 - position.days_held
    tax_cost = position.unrealized_gain × (st_rate - lt_rate)

    if days_to_lt_threshold < 60 and conviction > 0.4:
        # Approaching 1-year mark with intact conviction; suppress non-thesis exits
        action = WAIT_FOR_LT_THRESHOLD
        rationale = f"Position {days_to_lt_threshold} days from long-term;
                     conviction {conviction} ≥ 0.4 threshold; tax cost suppression active"
    elif tax_cost > 0.25 × position.unrealized_gain:
        # Tax bill exceeds a quarter of the gain; suppress unless thesis-broken
        # Static threshold; tunable via calibration data over time
        action = HOLD
        rationale = f"Tax cost ${tax_cost} exceeds 25% threshold of unrealized gain"
    else:
        action = original_signal
        rationale = "Tax-aware logic does not suppress this trigger"
else:
    # Long-term holding OR thesis-broken — execute original signal
    action = original_signal
```

## Why the static 25% threshold

The original v2-final spec referenced `expected_alpha_from_rotation`, but the system has no clean way to compute the alpha of a hypothetical rotation at exit time (EntryTimingModel scores current candidates, not hypothetical replacement positions).

The static `tax_cost > 0.25 × unrealized_gain` threshold replaces it. Crude but executable. Tunable via calibration data over time — if exits suppressed by this rule consistently outperform exits taken, the threshold can be lowered (more permissive of suppression). If exits suppressed underperform exits taken, the threshold can be raised (less permissive of suppression).

## Marginal tax rate inputs

The `tax_cost` calculation requires:
- Operator's federal marginal income tax rate (for short-term gains)
- Operator's federal long-term capital gains rate (15%, 20%, or 23.8% with NIIT, depending on income bracket)
- State tax (if applicable; some states tax both at ordinary rates)

These are operator-specific and stored in the operator's environment configuration (NOT in code, NOT in repo). Default federal: ST = 32%, LT = 15% (rough middle-bracket assumptions). Operator overrides via environment variable or configuration command.

## Output format for `/exit-check <ticker>`

```
TICKER: <ticker>
CURRENT PRICE: $X.XX
COST BASIS: $C.CC
SHARES: N
UNREALIZED P&L: $G (gain) or $L (loss)
DAYS HELD: D (LT eligible if ≥ 365)

TRIGGERS EVALUATED:

Priority 1 — Thesis-driven:
  - PMSupervisor downgrade: NO / YES (effective <date>)
  - Thesis pillar KPI test: PASS / FAIL <pillar name> at <review date>

Priority 2 — Risk-driven:
  - Drawdown vs invalidation level: <%>; INVALIDATED: NO / YES
  - Position size vs max band: <%> of portfolio (band: <%>); BREACH: NO / YES
  - Correlation cluster: <list of correlated positions>; THRESHOLD EXCEEDED: NO / YES

Priority 3 — Valuation-driven:
  - Price vs target: <% above/below target>
  - Forward P/E vs 10-yr history percentile: <pct>

Priority 4 — Technical:
  - 200-DMA break on volume: NO / YES <date>
  - Trend structure: <intact / changed>
  - Distribution pattern: <none / detected>

Priority 5 — Time-driven:
  - Days since last re-underwrite: D / 730 (24mo)
  - Stagnation: <% from entry>; <months stagnant>

FIRST FIRING TRIGGER: <trigger name + priority>

TAX-AWARE LOGIC:
  Days to LT threshold: <D>
  Conviction (latest PMSupervisor): <C>
  Tax cost if executed today: $T
  25% of unrealized gain: $G_25

EXIT SIGNAL: NONE | TRIM | FULL_EXIT | WAIT_FOR_LT_THRESHOLD
URGENCY: routine | elevated | urgent
PROPOSED ACTION: <specific action with target price/share count>
TAX COST ESTIMATE: $T (if executed today) vs $T_lt (if waited for LT)
REASONING TRACE: <which trigger fired, how tax-aware logic resolved it>
```

## Process rubric requirement (HG-5)

Per `process-rubric.md` HG-5, ExitSignalModel output must include explicit tax cost analysis. Output without `TAX COST ESTIMATE` or without `REASONING TRACE` showing how tax-aware logic was applied is returned for revision.

## Coordination with `/wash-sale-harvest`

The `/exit-check` command identifies positions to exit. If the exit is at a loss, it cross-references with `/wash-sale-harvest` to determine the appropriate wash-sale path. The two commands are typically run in sequence:

1. `/exit-check <ticker>` → identifies that position should be exited at a loss
2. `/wash-sale-harvest <ticker>` → produces the harvest recommendation with wash-sale path

For exits at a gain, only `/exit-check` is needed.

## Scheduled re-evaluation

Exit checks run daily at market close + 30 min as part of `/daily-monitor` orchestration. The output is logged to BUILD_LOG.md and to a dedicated exit signals table for tracking.

Operator review of exit signals is part of the daily summary; no exit is auto-executed (per v2-final §4.5 hard human-approval gate on all trades).
