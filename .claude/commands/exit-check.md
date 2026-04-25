---
description: Evaluate ExitSignalModel for a held position with tax-aware logic. Returns exit signal (NONE/TRIM/FULL_EXIT/WAIT_FOR_LT_THRESHOLD), urgency, proposed action, tax cost estimate. Per v2-final §2.3.
argument-hint: <ticker>
---

# /exit-check

**Status: v0.5+ scaffold.** Full implementation requires held positions and PriceFeatureService. v0.1 uses this for testing the trigger logic.

## Argument

`<ticker>` — required. Must be a currently held position.

## Procedure

### 1. Pre-flight checks

- Ticker is currently held (Postgres: positions table, status='active')
- `mcp__market_data` connected for current price + technical features
- `mcp__postgres` for thesis pillars, prediction status
- `mcp__brokerage` connected (v0.5+ only) for current cost basis and shares

If ticker not held: halt and report.

### 2. Load position context

- Cost basis, shares, days held
- Latest CompanyDeepDive thesis pillars + KPI test schedule
- Latest prediction resolution status (any predictions resolved against this position?)
- Latest PMSupervisor conviction
- Operator's marginal tax rates (federal ST + LT, state) from configuration

### 3. Evaluate triggers in priority order

Per `.claude/references/exit-triggers.md`:

#### Priority 1 — Thesis-driven (NEVER tax-suppressed)

- PMSupervisor downgrade: any recent decision shifting ADD → REJECT?
- Thesis pillar fail: any KPI test failed at scheduled review?

If fired: signal = TRIM or FULL_EXIT, urgency = urgent, **bypass tax-aware logic**.

#### Priority 2 — Risk-driven (tax-aware)

- Drawdown vs invalidation level
- Position size vs max band (8% single-name cap)
- Correlation cluster threshold (>0.8 with 3+ existing)

#### Priority 3 — Valuation-driven (tax-aware)

- Price exceeds target_price by >20%
- Forward P/E exceeds 75th percentile of name's 10-year history

#### Priority 4 — Technical (tax-aware)

- Break below 200-day SMA on volume
- Trend structure change (LH/LL 3+ weeks)
- Distribution pattern (rising price, falling OBV)

#### Priority 5 — Time-driven (tax-aware)

- Position held >24 months without thesis re-validation
- Stagnation: within ±10% of entry for >18 months

### 4. Apply tax-aware logic (Priority 2-5 only)

Per `.claude/references/exit-triggers.md`:

```
if position.days_held < 365 and trigger_priority != 1:
    days_to_lt_threshold = 365 - position.days_held
    tax_cost = position.unrealized_gain × (st_rate - lt_rate)

    if days_to_lt_threshold < 60 and conviction > 0.4:
        action = WAIT_FOR_LT_THRESHOLD
    elif tax_cost > 0.25 × position.unrealized_gain:
        action = HOLD
    else:
        action = original_signal
else:
    action = original_signal  # LT or thesis-broken
```

### 5. Output

```
EXIT CHECK — <ticker>

CURRENT PRICE: $X.XX
COST BASIS: $X.XX (entered <date>)
SHARES: N
UNREALIZED P&L: $X (gain) or $X (loss); X%
DAYS HELD: D (LT eligible if ≥ 365)

TRIGGERS EVALUATED:

Priority 1 — Thesis-driven:
  PMSupervisor downgrade: NO / YES (effective <date>)
  Thesis pillar KPI test: PASS / FAIL <pillar name>

Priority 2 — Risk-driven:
  Drawdown vs invalidation: -X% (limit -Y%); INVALIDATED: NO/YES
  Position size: X% (band: <Y>%); BREACH: NO/YES
  Correlation cluster: <list>; THRESHOLD: NO/YES

Priority 3 — Valuation-driven:
  Price vs target ($X): X% above target
  Forward P/E vs 10y history: <pct percentile>

Priority 4 — Technical:
  200-DMA break on volume: NO/YES <date>
  Trend structure: intact / changed
  Distribution pattern: none / detected

Priority 5 — Time-driven:
  Days since last re-underwrite: D / 730
  Stagnation: <%>

FIRST FIRING TRIGGER: <name + priority>

TAX-AWARE LOGIC (if applicable):
  Days to LT threshold: D
  Conviction (latest): X
  Tax cost if executed today: $T
  25% of unrealized gain: $G_25

EXIT SIGNAL: NONE | TRIM | FULL_EXIT | WAIT_FOR_LT_THRESHOLD
URGENCY: routine | elevated | urgent
PROPOSED ACTION:
  - Specific shares to trim or full exit
  - Target price for limit order, or "market on close"
  - Wash-sale path (if loss): refer to /wash-sale-harvest
TAX COST ESTIMATE: $X (if today) vs $X (if waited for LT)
REASONING TRACE: <which trigger fired, how tax-aware logic resolved>
```

### 6. Hard gate per process rubric HG-5

Output MUST include `tax_cost_estimate` and `reasoning_trace`. The Evaluator will reject the output if these are missing.

### 7. If exit at a loss

Cross-reference with `/wash-sale-harvest <ticker>` to produce wash-sale path recommendation.

### 8. Persistence

Write exit signal record to Postgres. The actual trade is not auto-executed (per v2-final §4.5 hard human-approval gate). Operator reviews the recommendation; if accepted, executes manually with brokerage.

## Daily run

This command runs as part of `/daily-monitor` for every held position. Surfaces signals that need operator attention.

## v0.1 vs v0.5

- **v0.1**: Useful for testing trigger logic against historical positions (sample memos with backtested entry/exit dates). Not in production critical path.
- **v0.5**: Daily for every held position; surfaced in daily digest.
- **v1.0**: Same; with full sample size for tax-cost calibration optimization.

## Cost estimate

Minimal — mostly numerical computation against price/fundamental data. ~$0.50-$1 per invocation.
