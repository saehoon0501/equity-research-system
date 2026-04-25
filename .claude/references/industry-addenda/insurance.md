# Industry Addendum: Insurance

Loaded by `company-deep-dive` subagent when company classification = property & casualty (P&C), life insurance, reinsurance, or insurance holding company (e.g., Berkshire-style).

Insurance economics are fundamentally different from operating businesses because of float economics and underwriting cycles.

## Replace standard valuation with insurance-specific

### P&C insurers

**Combined Ratio** is the central metric:

```
Combined Ratio = (Losses + LAE + Expenses) / Earned Premiums
```

- <100% means underwriting profit
- 95–100%: solid; profit comes from underwriting + investment income
- 100–105%: marginal underwriting loss; profitability dependent on investment income
- >105%: clear underwriting loss; investment income must cover the gap
- <90%: exceptionally good underwriting (often signals hard market or premium pricing)

Excellent insurers: combined ratio averages 90–95% over the cycle. Average insurers: 95–100%.

### Life insurers

- Embedded Value (EV) — actuarial PV of in-force business
- VNB margin — value of new business as % of premium
- ROEV — return on embedded value
- Investment portfolio composition (life insurers are massive bond investors)

### All insurers

- **Float** = reserves held against future claims; the "loan" from policyholders that earns investment income
- **Cost of float** = (-1 × underwriting profit) / average float; can be negative (paid to take the float)
- **Book value growth** + dividends = total return proxy

## Required ratios

| Ratio | Definition | Target |
|---|---|---|
| **Combined Ratio** (P&C) | (losses + LAE + expenses) / earned premiums | <100%; <95% strong |
| **Loss Ratio** | losses + LAE / earned premiums | depends on line; auto ~70%, homeowners ~60% |
| **Expense Ratio** | underwriting expenses / earned premiums | <30% efficient |
| **Loss Reserve Development** | favorable / unfavorable prior-year reserve releases | favorable = good underwriting discipline |
| **Premium Growth** | YoY net written premium growth | >10% in hard market; <5% in soft market |
| **Book Value per Share Growth** | YoY change in BV/share + dividends | >10% strong (Buffett's preferred metric for insurers) |
| **ROTCE** | net income / avg tangible common equity | 12–15% strong |
| **Float / Equity** | float / shareholders' equity | leverage proxy; higher = more leverage |
| **Reserve Adequacy Ratio** | reserves / claims paid | tracks reserving conservatism |

## Float economics (the Buffett framework)

Insurance company is essentially:
1. A pool of float (the reserves)
2. An underwriting business (which earns or loses money on premiums vs. claims)
3. An investment portfolio invested out of the float

If underwriting profits are achieved (combined ratio <100%), the company is being PAID to hold the float. The investment returns on the float are then incremental to the underwriting profit.

```
Total economic return = underwriting profit + investment income on float
Cost of float = (-underwriting profit) / average float
```

Excellent insurers achieve:
- Long-term combined ratio ≤ 95% (underwriting profit)
- Investment yields exceeding 10-year Treasury
- Float growth roughly matching premium growth, with reserve adequacy maintained

## Underwriting cycle

P&C insurance is cyclical:

- **Hard market** (high pricing): combined ratios drop, premium growth accelerates, capital flows in. 2023-2024 was hard for many P&C lines (especially commercial property post catastrophe years).
- **Soft market** (low pricing): combined ratios rise, premium growth slows, capital exits, eventually losses force pricing back up.

Cycle dynamics:
- Catastrophe events (hurricanes, wildfires, earthquakes) accelerate hardening
- New capacity (re-insurance, ILS) softens markets
- Inflation pressures combined ratios (medical, auto-parts, construction)

Surface in memo: where in the cycle is the specific line of business?

## Required risk factors to extract from 10-K

1. **Reserve adequacy** — historical reserve development; recent unfavorable releases concerning
2. **Catastrophe exposure** — PML (probable maximum loss) by peril; reinsurance attachment points
3. **Reinsurance program** — quality of reinsurers, terms, retention
4. **Investment portfolio risk** — credit quality, duration, equity exposure (life insurers especially)
5. **Regulatory** — state regulators, NAIC, capital requirements (RBC ratios)
6. **Climate change exposure** — increasing for P&C; specifically wildfire, flood
7. **Litigation / liability creep** — social inflation in casualty lines
8. **Cyber exposure** — both as insurer and as company (operational)

## Industry-specific catalysts

- Quarterly earnings (combined ratio for P&C)
- Hurricane/wildfire seasons (for P&C insurers)
- Reinsurance treaty renewals (Jan 1, July 1 — major moves)
- Regulatory announcements (RBC, capital adequacy)
- Investment portfolio re-positioning (rate environment changes)
- Major capital actions (buybacks, dividend changes)

## Berkshire-style insurance holding analysis

For insurance-led holding companies (Berkshire Hathaway, Markel, Fairfax), the analysis extends to:
- Operating subsidiaries (BNSF, BHE for Berkshire; etc.)
- Equity portfolio quality and concentration
- Capital allocation track record
- Sum-of-the-parts vs. consolidated valuation

These are quality compounders and fit the v2-final golden standard well.

## What doesn't apply

- Standard DCF (which assumes operating cash flows) — substitute with book value growth + earnings
- ROIC framework (invested capital ambiguous)
- Standard EV/EBITDA — meaningless for insurers

## Source quality tier guidance

- Tier 1: 10-K, 10-Q, statutory annual statements (filed with state regulators), NAIC data, AM Best ratings reports (for credit assessment)
- Tier 2: Earnings calls, IR presentations, investor day materials
- Tier 3: Insurance Journal, Business Insurance, A.M. Best, S&P insurance research
- Tier 4: General financial press without insurance specialization
