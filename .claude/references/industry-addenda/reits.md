# Industry Addendum: REITs

Loaded by `company-deep-dive` subagent when company classification = REIT (equity REITs, mortgage REITs, hybrid REITs).

Standard EPS and FCF metrics misleadingly characterize REITs because of their high D&A from real estate. This addendum replaces with REIT-specific metrics.

## Replace EPS with FFO and AFFO

**Funds From Operations (FFO)**, the NAREIT-standard REIT earnings metric:

```
FFO = Net Income
      + Depreciation & Amortization (real estate)
      + Losses on property sales
      − Gains on property sales
```

D&A is added back because real estate generally appreciates rather than depreciates economically; GAAP D&A is non-economic for REITs.

**Adjusted FFO (AFFO)**, the more conservative cash-flow proxy:

```
AFFO = FFO
       − Recurring CapEx (maintenance)
       − Straight-line rent adjustments
       − Other non-cash adjustments
```

AFFO is closer to true cash distributable to shareholders. Good REITs have AFFO covering the dividend with payout ratio <90%.

## Required ratios

| Ratio | Definition | Healthy range |
|---|---|---|
| **P/FFO** | market_cap / annualized FFO | 12–20x typical; sector-dependent |
| **AFFO Yield** | AFFO_per_share / share_price | 5–7% reasonable; >8% may signal stress |
| **Dividend Payout Ratio** | dividend / AFFO_per_share | <85% sustainable; >90% risky; >100% unsustainable |
| **NAV per Share** | (estimated property value − debt − preferred) / shares | Compare to current price; premium/discount to NAV |
| **Same-Store NOI Growth** | YoY same-property net operating income | 2–4% typical; >5% strong; <0% concerning |
| **Occupancy** | leased SF / total SF | >95% strong; 90–95% typical; <88% concerning |
| **WALT (Weighted Average Lease Term)** | weighted-avg years until lease expiry | >7 years strong; 4–7 typical; <3 risky |
| **Debt/Total Capitalization** | debt / (debt + equity) | <40% conservative; 40–55% typical; >60% leveraged |
| **Debt/EBITDA** | net debt / annualized EBITDA | <6x healthy; 6–8x average; >8x leveraged |
| **Fixed Charge Coverage** | EBITDA / (interest + preferred dividends) | >2.5x strong; 1.5–2.5x adequate; <1.5x risky |

## NAV-based valuation (primary methodology)

Estimate Net Asset Value bottom-up:

```
For each property:
  property_value = NOI / market_cap_rate  (cap rate from comparable transactions)

Total Property Value = Σ all properties
Net Asset Value = Total Property Value − total_debt − preferred_equity
NAV per share = NAV / fully_diluted_shares
```

Compare current price to NAV:
- Trading at large premium to NAV: market sees growth or quality not in current properties
- Trading at large discount to NAV: market sees deterioration or risk; potential value
- For diversified REITs, premium/discount can be sector-specific

## Sector-specific considerations within REITs

### Office

- WALT critical (longer = more secure)
- Tenant credit (investment-grade vs. not)
- Class A vs B/C
- Submarket trends (urban vs suburban; Sunbelt vs gateway)
- Post-COVID hybrid work impact (still evolving 2024-2026)

### Industrial / Logistics

- E-commerce tailwind
- Lease structures (typically NNN)
- Tenant concentration

### Retail

- Anchor tenant exposure
- Tenant sales / occupancy cost ratio
- Conversion to mixed-use feasibility

### Multifamily

- Same-store rent growth
- Concession trends
- Geographic exposure (Sunbelt growth, NY/CA outflow)

### Data Centers

- Lease structures (often power-based, not SF)
- Customer concentration (hyperscalers vs enterprise)
- Power infrastructure
- AI tailwind (significant 2024-2026 driver)

### Healthcare

- Senior housing vs medical office vs life sciences
- Tenant credit (operator-based for senior housing — tricky)
- Demographic tailwinds

## DCF doesn't work in standard form

Use a Net Asset Value approach plus growth in NOI as the primary methodology. DDM is also reasonable for stable dividend-paying REITs.

For a forward look:
```
Forward AFFO Multiple Approach:
  forward_AFFO = AFFO × (1 + expected_growth)
  target_price = forward_AFFO × forward_P/AFFO_target_multiple
```

## Required risk factors to extract from 10-K

1. **Tenant concentration** — top 10 tenants by base rent
2. **Geographic concentration** — top markets
3. **Lease expiration schedule** — % of leases expiring each year through 5+ years
4. **Debt maturity wall** — when do major debt tranches mature
5. **Interest rate sensitivity** — % floating rate; refinancing exposure
6. **Property-type concentration** (for diversified REITs)
7. **Regulatory** — rent control exposure (multifamily); zoning
8. **Macro** — interest rate sensitivity is high for REITs

## Industry-specific catalysts

- Quarterly earnings (FFO/AFFO releases)
- Major acquisitions or dispositions
- Cap rate trends in operating sector
- Interest rate decisions (heavy REIT sensitivity)
- Tenant earnings (especially for single-tenant REITs)
- 1031 exchange activity
- Public/private cap rate spreads (when public REIT prices imply higher cap rates than private market, signal)

## Source quality tier guidance for REIT claims

- Tier 1: 10-K, 10-Q, supplemental disclosures (REITs publish detailed property-level supplements quarterly), 8-K M&A filings
- Tier 2: Earnings calls, NAREIT presentations, IR property tours
- Tier 3: Green Street, established REIT-focused publications, regional commercial real estate publications
- Tier 4: General financial press without REIT specialization
