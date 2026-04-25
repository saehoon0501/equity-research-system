# IRS Wash-Sale Paths for Tax-Loss Harvesting

**Status:** Correctness-critical. Used by `/wash-sale-harvest` command and inside ExitSignalModel.

The IRS wash-sale rule (IRC §1091) disallows the loss if the same or "substantially identical" security is purchased within **30 days before *and* after** the loss sale — a **61-day total window** centered on the sale date.

## "Substantially identical" — what's prohibited

Per IRS Publication 550 and case law:

- The same security
- Single-stock options on the same underlying
- ETFs tracking the same index (SPY → VOO does NOT escape the rule; both track S&P 500)
- Convertible bonds substantially equivalent to the common stock
- Spousal or controlled-account purchases (you can't sell at a loss and have your spouse buy in their account; also disallowed)
- IRA purchases against taxable losses (also disallowed; recent guidance confirms)

The rule is fact-and-circumstances based for ETF substitutions — there's no bright line for "different enough." The system errs conservative.

## Three legitimate paths

For each tax-loss harvest recommendation, the system selects exactly one path and documents it:

### Path 1: Cash gap

**Procedure:** Sell loss position, hold cash through the 30-day post-sale window, rebuy at day 31+.

**When to use:** Default for any loss harvest unless there's a strong reason to maintain market exposure during the gap.

**Pros:**
- Simplest path
- Zero wash-sale risk
- No proxy selection judgment needed

**Cons:**
- 30 days of cash drag (unrebated to the position)
- During strong rallies, the cost of being out can exceed the tax savings

**Implementation in recommendation:**
```
PATH: cash_gap
SELL: 100 shares of XYZ on 2026-MM-DD at $X.XX
HARVESTED LOSS: $YYY
REBUY ELIGIBILITY: 2026-MM-DD + 31 days = 2026-MM-DD
ACTION: hold cash in money market through gap
```

### Path 2: Non-substantially-identical proxy

**Procedure:** Sell loss position, immediately rotate into a proxy that has documented divergence from the loss security during the 30-day gap, then optionally rotate back at day 31+ or hold the proxy permanently.

**When to use:** When market exposure during the gap is important and a defensible proxy exists.

**Defensible proxy examples:**

| Loss security | Defensible proxy | Reasoning |
|---|---|---|
| MSFT (single stock) | Broad tech ETF (XLK, VGT) where MSFT is one of many | Diversified, not concentrated single-name swap |
| MSFT (single stock) | Different mega-cap tech (GOOGL, AMZN) — risky | Distinct company; defensible but check correlation |
| SPY (S&P 500 ETF) | Russell 1000 ETF (IWB) or Total Market (VTI) | Different indexes; documented divergence |
| QQQ (Nasdaq 100) | XLK or VGT (different index, similar sector) | Different index, defensible |
| VOO | IVV — **NOT defensible** | Both track S&P 500; substantially identical |
| AAPL | Tech sector ETF | Diversified swap |

**Indefensible swaps (do not use as Path 2):**
- SPY ↔ VOO ↔ IVV (all S&P 500)
- QQQ ↔ ONEQ (both Nasdaq 100-tracking)
- VTI ↔ ITOT (both total US market)
- VWO ↔ IEMG (both emerging markets, similar index)

**Implementation in recommendation:**
```
PATH: proxy_rotation
SELL: 100 shares of MSFT at $X.XX
HARVESTED LOSS: $YYY
PROXY BUY: 50 shares of XLK at $Z.ZZ (concurrent with sale)
PROXY HOLDING WINDOW: 30 days minimum
DAY 31+ ACTION: optional rotate back to MSFT, or hold XLK permanently
RATIONALE FOR PROXY: XLK has 21% MSFT weight but 79% other holdings;
correlation to MSFT alone over past 60 days = 0.74 (NOT substantially identical)
WASH SALE RISK: low; defensible if challenged
```

### Path 3: Disclosure (rare; high-risk path)

**Procedure:** Operator chooses to take a substantially-identical position anyway for tactical reasons. Recommendation explicitly discloses the wash-sale risk; harvested loss is at risk of being disallowed by IRS.

**When to use:** Almost never. The only legitimate case is when:
- The post-30-day repurchase is forecast to be at materially higher prices, AND
- The operator has consulted a tax professional and accepts the risk explicitly, AND
- The harvested loss's value is small enough that disallowance is acceptable

**Implementation in recommendation:**
```
PATH: disclosure
SELL: 100 shares of MSFT at $X.XX
HARVESTED LOSS: $YYY
REBUY: 100 shares of MSFT at $Z.ZZ within 30 days
WASH SALE RISK: HIGH — substantially identical security
DISCLOSED CONSEQUENCE: harvested loss likely disallowed; cost basis adjusted
OPERATOR ACKNOWLEDGMENT REQUIRED: yes; do not auto-approve
```

The Path 3 recommendation must require explicit operator confirmation before execution. The system does not auto-execute substantially-identical repurchases.

## Output requirement for harvest recommendations

Every tax-loss harvest recommendation produced by `/wash-sale-harvest` must include:

```
TICKER: <ticker>
LOSS BASIS: $ <unrealized loss>
PATH: cash_gap | proxy_rotation | disclosure
WINDOW DATES:
  - Sale window opens: <date - 30 days>
  - Sale date: <today>
  - Sale window closes: <date + 30 days>
PROXY (if Path 2): <proxy ticker + reasoning>
WASH SALE RISK: low | low-moderate | moderate | high
HARVESTED LOSS DOLLAR VALUE: $X
EFFECTIVE TAX SAVINGS (estimated): $Y at <marginal rate>%
NET EXPECTED VALUE: $Y - <expected drag from cash gap or proxy divergence>
```

## Wash sale window math

A loss sale on date D triggers the wash-sale rule for purchases between **D-30 and D+30**. The system computes:

- **Pre-sale window:** D-30 to D-1 (existing positions in this window are wash-sale risk if you're now selling at a loss)
- **Post-sale window:** D+1 to D+30 (purchases here disallow the loss)
- **Total window:** 61 days centered on D

If the operator already purchased the same security in the D-30 to D-1 window (e.g., DCA into the position before deciding to harvest), the loss on those shares is partially or fully disallowed by their own pre-existing purchases. The system flags this.

```
PRE-SALE PURCHASES IN WINDOW:
  - 2026-MM-DD: bought 30 shares at $X.XX
  - 2026-MM-DD: bought 25 shares at $Y.YY
  
LOSS ALLOCATION:
  - 55 shares match against pre-sale purchases (loss disallowed for these)
  - 45 shares can be sold loss-harvested cleanly
  
RECOMMENDATION ADJUSTED: harvest only 45 shares
```

## Special cases

### Replacement shares acquired in different account types

The wash-sale rule applies across all of operator's accounts (taxable, IRA, spousal). Buying in an IRA after a taxable loss sale = wash sale, loss disallowed permanently (no cost basis adjustment in IRA).

The system tracks (or asks operator to track) all of operator's accounts. If brokerage MCP is connected with multiple-account support, this is mechanical. If not, the recommendation includes a checklist asking operator to confirm no replacement shares were purchased in any account.

### Year-end harvest timing

Last-day-of-year sales are common for tax-loss harvesting. The 30-day post-sale window crosses into next year. Wash sale rule still applies cross-year. Operator can rebuy on Jan 31+ (assuming Dec 31 sale date).

### Market closed days

The 30-day window is calendar days, not trading days. Saturday/Sunday/holidays count.

## What NOT to do

- Sell at a loss in taxable account, buy same name in IRA same week → wash sale, loss disallowed permanently
- Sell SPY at a loss, buy VOO same day → substantially identical, loss disallowed
- Sell AAPL at a loss, buy AAPL call options two weeks later → option on same underlying = substantially identical
- Sell at a loss, have spouse buy same security in their account → wash sale (spousal attribution)

## When in doubt: Path 1 (cash gap)

The cash gap path is conservative and defensible. If a proxy doesn't cleanly meet the "documented divergence + diversified holding" test, default to Path 1. The 30-day cash drag is rarely worse than the risk of disallowed loss.
