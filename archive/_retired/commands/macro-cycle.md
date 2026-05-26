---
description: Refresh macro/cycle view that modulates sizing aggressiveness across the system. Quarterly full update; monthly delta refresh; daily refresh on major regime indicators.
argument-hint: [delta|full] (default: delta)
---

# /macro-cycle

Refreshes the global cycle and macro view per v2-final §1.1. Output modulates sizing aggressiveness via the `aggressiveness_modifier`.

## Argument

`[delta|full]` — optional. Default: `delta`.

- `delta`: monthly refresh; updates against last full snapshot
- `full`: quarterly full update; rebuilds the cycle assessment from scratch

## Procedure

### 1. Pre-flight checks

- `mcp__fred` for macro indicators (or HTTP fallback)
- `mcp__market_data` for sector ETF performance, VIX, etc.
- `mcp__postgres` for prior MacroCycle outputs and Evidence Index writes

### 2. Gather inputs

Per v2-final §1.1:

- **Equity valuations**: S&P 500 P/E, Shiller CAPE, equity risk premium
- **Credit**: HY OAS, IG OAS spreads
- **Yield curve**: 2/10 spread, 3-month/10-year shape, term structure changes
- **Volatility**: VIX level, VIX term structure
- **Sentiment**: AAII bull/bear, NAAIM exposure, put/call ratios
- **IPO heat**: IPO volume, SPAC issuance metrics
- **Sector rotation**: sector ETF performance, rotation patterns

For `delta` mode: pull recent values vs last quarter's snapshot.
For `full` mode: pull full historical context for percentile/regime analysis.

### 3. Compute cycle score

Score range: -3 (euphoric/expensive) to +3 (panic/cheap)

Inputs to scoring (qualitative + quantitative):
- Valuations vs historical percentiles
- Credit conditions (tightening or loosening)
- Yield curve shape and direction
- VIX level and term
- Sentiment indicators (contrarian — extreme bullishness = bearish signal, etc.)
- Macro narrative health (qualitative)

Cycle score is a synthesis, not a formula. Document the reasoning.

### 4. Classify regime

One of: `euphoric` / `late-cycle` / `mid-cycle` / `early-cycle` / `panic`

Probability of regime shift in next 30 days (0-1).

### 5. Compute aggressiveness_modifier

Maps cycle score to a multiplier:
- Euphoric (score -3): 0.5
- Late-cycle (-1 to -2): 0.7-0.85
- Mid-cycle (0): 1.0
- Early-cycle (+1 to +2): 1.15-1.3
- Panic (+3): 1.5

This modifier flows into PositionSizingModel and PMSupervisor sizing decisions.

### 6. Populate Evidence Index

Every cited indicator with its current value and historical percentile is a claim. Per `.claude/references/evidence-index-schema.md`, populate Evidence Index rows for each:

```
claim: "S&P 500 forward P/E is 22.4 vs 10-year median of 17.8 (87th percentile)"
source_uri: <FRED data series or market_data ticker>
source_date: <today>
source_quality_tier: 1 (FRED) or 2 (sell-side aggregation)
```

### 7. Output

```
MACRO CYCLE UPDATE — <date>
Mode: full | delta

CYCLE SCORE: X (-3 to +3)
REGIME CLASSIFICATION: <euphoric/late/mid/early/panic>
REGIME CHANGE RISK (30d): X%

AGGRESSIVENESS MODIFIER: X (0.5–1.5)

EVIDENCE FOR SCORE:
- Valuation: S&P 500 P/E 22.4 (87th percentile) → bearish weight
- Credit: HY OAS 4.2% (40th percentile) → neutral
- Yield curve: 2/10 spread inverted -50bps → bearish weight
- VIX: 14 (low; 25th percentile) → bearish weight (complacency)
- Sentiment: AAII bull/bear at 60/20 (extreme bullish) → bearish (contrarian)
- ...

CHANGES SINCE LAST UPDATE (delta mode):
- Cycle score changed from X to Y (driver: <indicator>)
- Regime classification: unchanged | changed from X to Y

EVIDENCE INDEX REFS: <list of evidence_ids>
```

### 8. Persistence

Write to Postgres:
- New MacroCycle output record (versioned)
- Evidence Index entries
- Update calibration history if prior predictions resolve

### 9. Notify if regime change

If regime classification changed since last full update, surface prominently. This is a signal that:
- Sizing modifier just shifted significantly
- Position sizing recommendations should be re-checked for active candidates
- Possibly cycle-driven exit signals (per ExitSignalModel) should be re-evaluated

## Cadence guidance

- **Full update**: quarterly (every 3 months); pull full historical context
- **Delta update**: monthly; check for material shifts since last full
- **Daily refresh**: only on major regime indicators (Fed action, VIX spike, credit spread widening, geopolitical shock)

## Cost estimate

- Full quarterly: Opus, ~$15-30 per run
- Monthly delta: Sonnet, ~$5-10 per run
- Daily refresh on indicators: Sonnet only when triggered, ~$3-5 per run

## Process rubric

Per `.claude/references/process-rubric.md` universal criteria. The Evaluator runs.

Specific to MacroCycle:
- Score discrimination over time (the score should actually vary, not cluster around 0)
- Cited evidence with Evidence Index references for every numerical claim
- Falsifiability: regime classification has specific characteristics that would change if wrong
