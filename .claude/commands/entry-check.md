---
description: Evaluate EntryTimingModel for a watchlist name. Returns entry quality score, recommendation (STRONG_ENTRY/ENTRY_OK/WAIT/DO_NOT_ENTER), invalidation level, and recommended initial size. Per v2-final §2.2.
argument-hint: <ticker>
---

# /entry-check

**Status: v0.5+ scaffold.** This command becomes fully functional once the quant data layer (PriceFeatureService) is operational. v0.1 phase has limited data infrastructure; this command's full implementation lands in week 6+ of the build per implementation-sequencing.md.

## Argument

`<ticker>` — required. Must be a name on the approved watchlist.

## Procedure

### 1. Pre-flight checks

- Ticker is on approved watchlist (PMSupervisor decision = ADD with conviction recorded)
- `mcp__market_data` connected for price/volume data
- `mcp__postgres` connected for watchlist + MacroCycle reads

If ticker is not on watchlist: halt and report. The Execution Layer cannot operate on names the slow layer hasn't approved.

### 2. Compute features (per v2-final §2.1)

For ticker, fetch and compute (last 252 trading days):
- 20/50/200-day SMAs and slope direction
- Distance from 200-day SMA (%)
- Distance from 52-week high (%)
- Volume z-score (20-day baseline)
- Recent volume confirmation on up-days

### 3. Apply 4-factor scoring (per v2-final §2.2)

| Factor | Weight | Computation |
|---|---|---|
| Trend alignment (20/50/200 DMA stack) | 0.30 | All MAs in correct order? Slopes positive? |
| Distance from 200-day SMA | 0.25 | Penalize extension >20% above 200DMA |
| Volume confirmation on recent up-days | 0.20 | Volume z-score on up-days vs down-days |
| Cycle modifier from MacroCycle | 0.25 | Aggressive in panic, cautious in euphoria |

Score: 0–1, weighted sum normalized.

### 4. Recommendation

| Score | Recommendation |
|---|---|
| > 0.75 | STRONG_ENTRY |
| 0.50 – 0.75 | ENTRY_OK |
| 0.25 – 0.50 | WAIT |
| < 0.25 | DO_NOT_ENTER |

### 5. Compute invalidation level

The price below which the entry thesis is wrong. Used as initial stop-loss reference. Typically:
- Below recent swing low + ATR-based buffer
- Below 200-day SMA if trend is the primary thesis
- Below technical support level

Document the rationale.

### 6. Compute recommended initial size

Within the approved size_band from PMSupervisor, scale by entry quality:
- STRONG_ENTRY: enter at upper end of size band
- ENTRY_OK: enter at midpoint of size band, plan to add on confirmation
- WAIT: enter 0% (no entry today); wait for STRONG_ENTRY or ENTRY_OK
- DO_NOT_ENTER: do not enter

### 7. Output

```
ENTRY CHECK — <ticker>

WATCHLIST STATUS: approved (date: <X>, conviction: <Y>, size band: X%–Y%)

PRICE: $X.XX (today)
20-DAY SMA: $X.XX (slope: +/− Z%)
50-DAY SMA: $X.XX
200-DAY SMA: $X.XX (slope: +/− Z%)

DISTANCE FROM 200-DMA: +X% (above) / -X% (below)
DISTANCE FROM 52-WEEK HIGH: -X%

VOLUME Z-SCORE (20-DAY): X
VOLUME ON UP DAYS: confirmation / no confirmation

CYCLE MODIFIER (from MacroCycle): X (0.5–1.5)

FACTOR SCORES:
  Trend alignment: 0.X (weight 0.30)
  Distance from 200DMA: 0.X (weight 0.25)
  Volume confirmation: 0.X (weight 0.20)
  Cycle modifier: 0.X (weight 0.25)

ENTRY QUALITY SCORE: 0.X (overall)
RECOMMENDATION: STRONG_ENTRY / ENTRY_OK / WAIT / DO_NOT_ENTER

INVALIDATION LEVEL: $X.XX (rationale: <support level reference>)
RECOMMENDED INITIAL SIZE: X% of portfolio (within approved band X%–Y%)

NEXT STEP: Run `/size <ticker>` to compute final position size with all sizing modifiers
```

### 8. Critical constraint

This command never overrides PMSupervisor approval. If PMSupervisor said REJECT or WATCH (sub-threshold), no entry is appropriate regardless of technical setup. The Execution Layer operates within the approved universe only.

## v0.1 limitation

In v0.1, the watchlist is empty (no real positions held). This command can be run against historical date-anchored backtesting once PriceFeatureService is built (week 2+) but isn't used in critical path until v0.5.

## Cost estimate

Minimal — this is mostly numerical computation against price data, not LLM-heavy. ~$0.50-$1 per invocation in main context.
