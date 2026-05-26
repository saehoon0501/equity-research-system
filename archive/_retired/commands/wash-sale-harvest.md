---
description: Propose tax-loss harvest with wash-sale path selection. Three legitimate paths: cash gap, non-substantially-identical proxy, disclosure. Per v2-final §2.3 wash-sale compliance.
argument-hint: <ticker>
---

# /wash-sale-harvest

**Status: v0.5+ scaffold.** Used when an exit recommendation involves a loss; produces wash-sale-compliant harvest plan.

## Argument

`<ticker>` — required. Position currently held at a loss.

## Procedure

Per `.claude/references/wash-sale-paths.md`:

### 1. Pre-flight checks

- Ticker is a held position currently at a loss (cost_basis > current_price)
- `mcp__market_data` connected
- `mcp__brokerage` (v0.5+) for accurate cost basis and shares
- `mcp__postgres` for thesis pillar status

### 2. Verify it's a real harvest candidate

Per v2-final §2.3:
- Position down >15% from cost basis
- Stable thesis (not thesis-broken — thesis-broken exits don't need wash-sale-aware harvest; they exit fully regardless)
- Operator wants to harvest the loss for tax purposes (not auto-triggered; operator-initiated typically)

### 3. Check pre-sale wash-sale window

Query operator's purchases (and spousal/IRA if accessible via brokerage MCP):

```
PRE-SALE WINDOW (D-30 to D-1):
  - 2026-MM-DD: bought N shares at $X.XX
  - 2026-MM-DD: ...

If pre-sale purchases exist:
  Match against shares being sold; loss is partially or fully disallowed.
  Adjust harvest plan to harvest only unmatched shares.
```

### 4. Select wash-sale path

Three legitimate paths per `.claude/references/wash-sale-paths.md`:

#### Path 1: Cash gap (default)

- Sell loss position
- Hold cash for 30+ days post-sale
- No new position in same name during window

```
PATH: cash_gap
SELL: N shares of <ticker> on <today>
HARVESTED LOSS: $<amount>
REBUY ELIGIBILITY: <today + 31 days>
ACTION: hold cash in money market through gap
EXPECTED COST: <30-day return drag estimate>
```

#### Path 2: Non-substantially-identical proxy

- Sell loss position
- Immediately rotate into proxy with documented divergence
- Optionally rotate back at day 31+ or hold proxy permanently

Defensible proxy guidance per wash-sale-paths.md:

| Loss security type | Defensible proxy |
|---|---|
| Single mega-cap stock | Diversified sector ETF where stock is one of many |
| S&P 500 index ETF | Russell 1000 ETF or Total Market ETF (different index) |
| Tech ETF (QQQ) | Different-index tech ETF (XLK or VGT) |

Indefensible (do NOT use as Path 2): SPY ↔ VOO, QQQ ↔ ONEQ, VTI ↔ ITOT, etc. (substantially identical = wash sale)

```
PATH: proxy_rotation
SELL: N shares of <loss-ticker>
HARVESTED LOSS: $<amount>
PROXY BUY: M shares of <proxy-ticker> (concurrent with sale)
PROXY HOLDING WINDOW: 30 days minimum
DAY 31+ ACTION: optional rotate back to <loss-ticker>, or hold <proxy-ticker> permanently
RATIONALE FOR PROXY: <ticker> has X% weight in proxy ETF but Y% other holdings;
  correlation to <loss-ticker> alone over past 60 days = Z (NOT substantially identical)
WASH SALE RISK: low; defensible if challenged
```

#### Path 3: Disclosure (rare; high-risk)

Operator chooses to take a substantially-identical position anyway. Recommendation explicitly discloses the wash-sale risk.

```
PATH: disclosure
SELL: N shares of <ticker>
HARVESTED LOSS: $<amount>
REBUY: N shares of <ticker> within 30 days
WASH SALE RISK: HIGH — substantially identical security
DISCLOSED CONSEQUENCE: harvested loss likely disallowed; cost basis of replacement shares adjusted
OPERATOR ACKNOWLEDGMENT REQUIRED: yes; do not auto-approve
```

Path 3 requires explicit operator confirmation. Do not produce Path 3 recommendations as defaults.

### 5. Path selection logic

```
if has_strong_proxy_with_documented_divergence and operator_wants_market_exposure:
    path = proxy_rotation
elif operator_explicitly_requests_disclosure_path:
    path = disclosure  # rare
else:
    path = cash_gap  # default
```

### 6. Output

```
WASH-SALE HARVEST RECOMMENDATION — <ticker>

LOSS BASIS: $<unrealized loss>
COST BASIS: $X.XX (entered <date>)
SHARES: N
CURRENT PRICE: $X.XX
TODAY: <date>

PRE-SALE WINDOW CHECK (D-30 to D-1):
  Existing purchases in window: <list or "none">
  Loss allocation: <X shares unmatched, available for harvest; Y shares matched, loss disallowed>

WASH SALE WINDOW:
  Sale window opens (D-30): <date>
  Sale date: <today>
  Sale window closes (D+30): <date>

PATH SELECTED: cash_gap | proxy_rotation | disclosure

[For Path 1:]
ACTION: sell N shares; hold cash in money market until <date+31>
EXPECTED CASH GAP COST: <estimate>

[For Path 2:]
ACTION: sell N shares of <ticker>; concurrently buy M shares of <proxy>
PROXY HOLDING WINDOW: 30 days (until <date+31>)
DAY 31+ ACTION: rotate back to <ticker> | hold <proxy> permanently
RATIONALE: <documented divergence and rationale>

[For Path 3:]
ACTION: sell N shares; rebuy within 30 days
WASH SALE RISK: HIGH
DISCLOSED CONSEQUENCE: harvested loss likely disallowed
OPERATOR ACKNOWLEDGMENT: required before execution

HARVESTED LOSS: $<amount>
ESTIMATED TAX SAVINGS: $<amount> at <marginal rate>%
NET EXPECTED VALUE:
  Tax savings: $<X>
  Cash gap drag (Path 1) or proxy divergence (Path 2): $<Y>
  Net: $<X - Y>

DOCUMENTATION:
  IRS Form 8949 entry: <to be recorded at year end>
  Schedule D impact: <to be recorded at year end>
  Cost basis adjustment (Path 3 only): <if applicable>
```

### 7. Persistence

Write to Postgres:
- Harvest recommendation record
- Anticipated tax-related effects

The actual trade is not auto-executed (per v2-final §4.5 hard human-approval gate). Operator reviews and executes manually with brokerage.

### 8. Year-end accounting

At year-end, the operator reconciles:
- All harvested losses (executed)
- Any wash-sale-disallowed harvests (Path 3 paths or accidental violations)
- Net realized loss for IRS Form 8949

The system can produce a summary report (v0.5+) but the actual tax filing remains operator's responsibility.

## When to use

- Position is held at >15% loss
- Thesis is stable (not broken — thesis-broken exits don't optimize for wash-sale; just exit fully)
- It's economically appropriate to take the tax loss this calendar year
- Year-end timing especially relevant (last opportunity for current-year loss)

## When NOT to use

- Thesis is broken: just exit (don't optimize for tax)
- Position is at a gain: not a harvest scenario
- Same-day re-entry needed: that's exactly the case Path 3 covers, but it's almost always better to use Path 1 or 2 instead

## Cost

Minimal — primarily computation against current data. ~$0.50-$1 per invocation.

## Critical safety note

The operator is responsible for ensuring:
- All accounts (taxable, IRA, spousal) are checked for replacement purchases
- The actual trade execution doesn't violate the wash-sale rule
- Year-end tax filing reflects the harvest correctly

The system produces recommendations; actual tax compliance is operator + tax professional.
