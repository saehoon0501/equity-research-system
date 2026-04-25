# Position Sizing Formula

Per v2-final §2.4. Used by `/size <ticker>` command.

## Algorithm

```
expected_edge = (P50_target_price / current_price - 1) - risk_free_rate
estimated_variance = realized_vol_60d^2  # annualized
kelly_full = expected_edge / estimated_variance

# Calibration-driven Kelly fraction
# Default starting fraction: 0.25 (quarter-Kelly)
# Adjusted by Brier trend over rolling 90-day window
# Minimum 30 resolved predictions per agent before any adjustment
kelly_fraction = compute_kelly_fraction(
    base = 0.25,
    floor = 0.125,    # 1/8 Kelly hard floor
    ceiling = 0.50,   # 1/2 Kelly hard ceiling
    agent_calibration_history = last_90_days,
    min_sample = 30
)

# Cycle modifier (from MacroCycleAgent)
cycle_mod = aggressiveness_modifier  # 0.5 in euphoria, 1.5 in panic

# Volatility-managed sizing (Moreira & Muir 2017)
vol_target = 20%  # annualized portfolio vol target
vol_mod = min(1.0, vol_target / realized_vol_60d)

# Correlation adjustment
correlation_mod = 1 / sqrt(1 + sum_of_correlations_with_existing_positions)

# Combine
suggested_weight = kelly_full × kelly_fraction × cycle_mod × vol_mod × correlation_mod

# Bound by approved size band (from PMSupervisor)
final_weight = clip(suggested_weight, size_band_min, size_band_max)

# Apply hard concentration limits
final_weight = min(final_weight, single_name_cap)
```

## Inputs required

- `P50_target_price` from CompanyDeepDive memo's `target_price`
- `current_price` from market data MCP
- `risk_free_rate` from FRED MCP (10Y Treasury or 3M T-bill, depending on horizon convention)
- `realized_vol_60d` from market data MCP, annualized
- `agent_calibration_history` from Predictions DB
- `aggressiveness_modifier` from latest MacroCycle output
- Existing positions and their correlations from positions table + market data
- `size_band_min`, `size_band_max` from PMSupervisor's `recommended_size_band`

## Calibration-driven Kelly fraction

The base fraction is 0.25 (quarter-Kelly). It moves between 0.125 and 0.50 based on per-agent Brier-score trends:

```
if total_resolved_predictions < 30:
    return 0.25  # not enough data, hold at default

brier_trend_90d = (
    rolling_brier(last_30_days) - rolling_brier(prior_30_days)
) / rolling_brier(prior_30_days)

if brier_trend_90d < -0.10:  # 10%+ improvement (lower Brier is better)
    fraction = min(0.50, current_fraction × 1.1)
elif brier_trend_90d > +0.10:  # 10%+ degradation
    fraction = max(0.125, current_fraction × 0.9)
else:
    fraction = current_fraction  # no change
```

Adjustments are gradual (10% per evaluation) to prevent whipsaw on small-sample noise. Minimum sample size of 30 prevents premature adjustments.

## Why quarter-Kelly base

Quarter-Kelly is a defensible practitioner heuristic, not a theoretical optimum. The calibration-driven adjustment is the empirical part — start at 0.25, let the data argue for half-Kelly if it earns it.

If at v0.5 month 12 the data argues for 0.5, the system moves there. If it argues for 0.125, the system moves there. The bounded floor and ceiling prevent the calibration adjustment from going to extreme positions on small-sample noise.

## Volatility-managed sizing

Moreira & Muir (2017, JFE): scaling exposure inversely with realized volatility produces alpha even for buy-and-hold. The formula `vol_mod = min(1.0, vol_target / realized_vol_60d)` reduces position size when realized volatility exceeds the 20% portfolio target.

For a quiet stock (realized vol = 15%): vol_mod = min(1.0, 0.20/0.15) = 1.0 (no reduction; capped at 1.0)
For a volatile stock (realized vol = 40%): vol_mod = 0.20/0.40 = 0.50 (size halved)

The `min(1.0, ...)` cap prevents leverage — quiet stocks don't get larger than the unmanaged size, only volatile ones get smaller.

## Correlation modifier

Existing portfolio correlation reduces sizing for new positions that overlap with existing exposure. The formula:

```
correlation_mod = 1 / sqrt(1 + sum_of_correlations_with_existing_positions)
```

Where `sum_of_correlations_with_existing_positions` is the sum of pairwise correlations between the proposed position and each existing holding (using 60-day daily return correlation).

For a new uncorrelated position (sum = 0): correlation_mod = 1.0 (no reduction)
For a new highly correlated position (sum = 3.0 across existing holdings): correlation_mod = 1/sqrt(4) = 0.50 (size halved)

This prevents accidental concentration via correlation cluster buildup.

## Hard concentration limits (enforced regardless of model output)

Per v2-final §2.4:

- **Single name:** max 8% of portfolio
- **Single sector:** max 35% of portfolio
- **Top 5 positions:** max 50% of portfolio
- **Cash floor:** min 5%
- **Cash ceiling:** max 30%

These are non-negotiable. The model's `final_weight` is capped at `single_name_cap`. Sector and top-5 caps are checked at portfolio level before allowing the position to enter.

## Output format

The `/size <ticker>` command produces:

```
TICKER: <ticker>
CURRENT PRICE: $X.XX
P50 TARGET (from CDD memo): $Y.YY
EXPECTED EDGE: Z%
REALIZED VOL 60D: V%
KELLY FULL: F (annualized return / variance)
KELLY FRACTION (calibrated): K (between 0.125 and 0.50)
CYCLE MOD (from MacroCycle): C (0.5–1.5)
VOL MOD (Moreira-Muir): M (≤1.0)
CORRELATION MOD: R (≤1.0)
SUGGESTED WEIGHT: W%
SIZE BAND (from PM Supervisor): [W_min%, W_max%]
HARD LIMIT BINDING: <which limit, if any, capped the recommendation>
FINAL WEIGHT: F%
DOLLAR SIZE (at current portfolio value of $P): $D
SIZING FACTORS DECOMPOSITION: full breakdown of how each modifier contributed
```

## Edge cases

### Negative expected edge

If `expected_edge < 0` (target price below current price), `kelly_full` is negative. The system does not short positions in v0.1/v0.5/v1.0 (long-only strategy per v2-final §2.4). A negative-edge result triggers a recommendation to PASS, not enter.

### Zero or undefined volatility (newly listed stocks, illiquid)

If `realized_vol_60d` cannot be computed (insufficient history), use sector ETF volatility as fallback and surface this in the output.

### MacroCycleAgent not yet run

If no MacroCycle output exists, default to `cycle_mod = 1.0` and surface a warning. The first MacroCycle run is in week 11 of v0.1 (or before v0.5 entry).

### No existing positions

For an empty portfolio (or v0.5 entry with no positions yet), `correlation_mod = 1.0`.

### Below-floor result

If the combined modifiers produce a `suggested_weight` below the size band's `W_min`, the recommendation is to PASS or wait — do not enter at sub-band size. Sub-band positions don't exercise the calibration data meaningfully (per phasing-plan.md §3.7 v0.5 position discipline).

## Validation

The `/size` command validates:

1. CompanyDeepDive memo exists and has been Evaluator-approved (otherwise no `target_price`)
2. PMSupervisor has approved the position with a `recommended_size_band`
3. Hard concentration limits are not already violated by existing portfolio (don't propose enters that breach limits)
4. All MCP data sources are available (market data, FRED, Postgres for calibration history)

If validation fails, the command halts and reports the failure. It does not produce a sizing recommendation against incomplete data.
