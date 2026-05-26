---
description: Calculate PositionSizingModel recommendation for a watchlist name. Returns dollar size and weight % with full sizing decomposition. Per v2-final §2.4.
argument-hint: <ticker>
---

# /size

**Status: v0.5+ scaffold.** Full implementation requires watchlist + entry approval + calibration history. v0.1 uses for testing the formula.

## Argument

`<ticker>` — required. Must be on watchlist with PMSupervisor approval.

## Procedure

Per `.claude/references/position-sizing-formula.md`:

### 1. Pre-flight checks

- Ticker on watchlist (PMSupervisor decision = ADD)
- `mcp__market_data` for current price + realized vol
- `mcp__fred` for risk-free rate
- `mcp__postgres` for calibration history, MacroCycle modifier, existing positions
- Prior CompanyDeepDive memo with target_price exists

### 2. Compute Kelly full

```
expected_edge = (P50_target_price / current_price - 1) - risk_free_rate
estimated_variance = realized_vol_60d^2  # annualized
kelly_full = expected_edge / estimated_variance
```

If `expected_edge < 0`: report PASS recommendation (system is long-only). Do not size negative-edge positions.

### 3. Compute calibrated Kelly fraction

```
if total_resolved_predictions < 30:
    kelly_fraction = 0.25  # default; not enough data

else:
    brier_trend_90d = compute_trend()  # last 30 days vs prior 30 days
    
    if brier_trend_90d < -0.10:  # improving
        kelly_fraction = min(0.50, current × 1.1)
    elif brier_trend_90d > +0.10:  # degrading
        kelly_fraction = max(0.125, current × 0.9)
    else:
        kelly_fraction = current
```

### 4. Apply modifiers

- **cycle_mod**: from latest MacroCycle output (0.5–1.5)
- **vol_mod**: `min(1.0, vol_target / realized_vol_60d)` where vol_target = 20% annualized
- **correlation_mod**: `1 / sqrt(1 + sum_correlations)` with existing portfolio

### 5. Combine and bound

```
suggested_weight = kelly_full × kelly_fraction × cycle_mod × vol_mod × correlation_mod
final_weight = clip(suggested_weight, size_band_min, size_band_max)
final_weight = min(final_weight, single_name_cap)  # 8%
```

Sector cap (35%) and top-5 cap (50%) checked at portfolio level — not just position level.

### 6. Output

```
POSITION SIZING — <ticker>

CURRENT PRICE: $X.XX
P50 TARGET (from CDD memo dated <X>): $Y.YY
EXPECTED EDGE: Z%
RISK-FREE RATE (FRED): R%

REALIZED VOL 60D (annualized): V%
ESTIMATED VARIANCE: V²

KELLY FULL: F (annualized return / variance)

KELLY FRACTION: K (between 0.125 and 0.50)
  Default: 0.25
  Calibration adjustment: <reasoning based on agent calibration history>
  Resolved predictions in 90d window: N

MODIFIERS:
  Cycle modifier (MacroCycle): C
  Volatility modifier (Moreira-Muir): M
  Correlation modifier: R

  Combined effective scale: K × C × M × R = X

SUGGESTED WEIGHT (Kelly × all modifiers): W%

PMSUPERVISOR APPROVED SIZE BAND: [W_min%, W_max%]
HARD CONCENTRATION LIMITS:
  - Single name cap: 8% (current: <if any> X%)
  - Sector cap: 35% (current sector: X%)
  - Top 5 cap: 50% (current top 5: X%)

HARD LIMIT BINDING: <which limit, if any, capped the recommendation>

FINAL WEIGHT: F%
DOLLAR SIZE (at portfolio value $P): $D
SHARES (at $X.XX): N

NEXT STEPS:
- Run `/entry-check <ticker>` to evaluate entry timing quality
- If STRONG_ENTRY or ENTRY_OK: enter at recommended initial size from /entry-check
- If WAIT or DO_NOT_ENTER: hold off; revisit when entry quality improves
```

### 7. Validation

The command halts if:
- CompanyDeepDive memo doesn't exist or hasn't been Evaluator-approved
- PMSupervisor hasn't approved the position with a recommended_size_band
- Hard concentration limits would be breached by adding this position
- MCP data sources unavailable

## Coordination with other commands

`/size` is typically run after `/research-company` produces an ADD recommendation, alongside `/entry-check` for timing. The full entry workflow:

```
1. /research-company <ticker>          → ADD with size band
2. /size <ticker>                       → recommended dollar size
3. /entry-check <ticker>                → STRONG_ENTRY/ENTRY_OK/WAIT/DO_NOT_ENTER
4. If entry quality OK: operator manually places order via brokerage
   (no auto-execution per v2-final §4.5)
```

## Cost estimate

Minimal — primarily numerical. ~$0.50 per invocation.

## v0.1 vs v0.5+

- **v0.1**: Tests the formula against historical positions; verifies algorithmic correctness
- **v0.5**: Used for actual position entries with extra-high conviction bar (≥0.7) per phasing-plan.md §3.7
- **v1.0**: Used for full watchlist; calibration adjustment becomes the dominant tuning lever
