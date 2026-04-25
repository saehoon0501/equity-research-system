# Industry Addendum: Energy / E&P / Oilfield Services

Loaded by `company-deep-dive` subagent when company classification = oil & gas E&P (exploration & production), integrated major, midstream, oilfield services, or related energy infrastructure.

Energy is commodity-driven, capital-intensive, and cyclical. Standard ratios (P/E, EV/EBITDA) need commodity-cycle context.

## Replace standard valuation with E&P-specific

### Reserves valuation (E&P primary)

Reserves classification (SEC standardized):

- **1P (Proved)**: ≥90% probability of recovery; the only category SEC allows in financial reporting
- **2P (Proved + Probable)**: 50% probability; used for management/internal valuation
- **3P (Proved + Probable + Possible)**: 10% probability; speculative

PV-10 (Pre-tax PV of future cash flows from proved reserves discounted at 10%):
```
PV-10 = Σ (annual_cash_flow / 1.10^t) for t=1 to reserve_life
```

The SEC requires PV-10 disclosure in 10-K Item 1.

### Required ratios

| Ratio | Definition | Notes |
|---|---|---|
| **EV/EBITDAX** | EV / (EBITDA + exploration expense) | Add back exploration to EBITDA; standardizes treatment of successful-efforts vs full-cost accounting |
| **EV/BOE** (E&P) | EV / total barrels of oil equivalent reserves (1P or 2P) | Compare to recent transactions; current cycle context |
| **EV/Daily Production (BOE/d)** | EV / current daily production | Production-based valuation; useful when reserves are uncertain |
| **F&D Costs** (Finding & Development) | new reserves added / capex | Lower is better; <$15/BOE excellent for U.S. shale |
| **Reserve Replacement Ratio** | reserves added / reserves produced | >100% needed for long-term viability |
| **Breakeven Price** | price needed to cover full-cycle costs | <$40/bbl strong (for oil); shale-dependent |
| **Decline Rate** | annual production decline of existing wells | Important for shale (high initial declines) |
| **Lifting Cost / BOE** | direct production costs per barrel | <$10/BOE efficient; higher is concerning |

### Midstream-specific

Pipeline and storage companies are different — they earn on volume, not commodity price:
- **DCF (Distributable Cash Flow)** — replaces FCF for MLPs and partnerships
- **Coverage Ratio** — DCF / distributions paid; >1.2x healthy
- **EV/EBITDA** — works fine for midstream (less commodity-sensitive)
- **Volume-based capacity utilization** — % of contracted vs available

### Oilfield Services (OFS)

- Cyclical with rig count and well completions
- Equipment utilization rates
- Day rates (offshore drillers, frac fleets)
- Backlog visibility

## DCF works but with commodity-curve sensitivity

For E&P:
```
Production schedule × Price deck × Operating costs × Tax × Royalties
                  − Capex
                  = Free Cash Flow
```

Sensitivity table: price deck assumption × discount rate. Always show base/bull/bear price decks (e.g., $60 / $80 / $100 WTI).

## Hedging considerations

E&P companies hedge production:
- Surface % of forward production hedged and at what price
- Hedge book gains/losses can be material to short-term earnings
- Hedge expiration creates transitions (price exposure)
- Disclose floor/cap structures

## Required risk factors to extract from 10-K

1. **Commodity price exposure** — % of production hedged vs unhedged
2. **Operational risk** — well failures, blowouts, environmental incidents
3. **Regulatory** — federal lands access, drilling permits, methane regulations, carbon pricing
4. **ESG / climate transition** — divestment pressure, capital cost premiums
5. **Litigation** — environmental, royalty owner disputes
6. **Geology** — productivity declines, completion design changes
7. **Decommissioning liabilities** — abandonment costs (offshore especially)

## Industry-specific catalysts

- Quarterly production reports
- OPEC+ decisions (geopolitical price drivers)
- Inventory reports (EIA weekly crude inventory)
- Hedging program updates
- Major drilling results (E&P, especially offshore deepwater)
- M&A in basin (consolidation indicators)
- Regulatory rulings (federal lease sales, methane rules)

## Macro context

Oil price cycle drivers:
- Demand: global GDP, China, transportation electrification
- Supply: OPEC+, U.S. shale productivity, geopolitical disruptions
- Inventory: SPR, commercial inventory levels
- Currency: USD strength (commodities priced in USD)

The MacroCycleAgent's `aggressiveness_modifier` should especially shape energy position sizing — energy is highly cycle-sensitive.

## Quality compounders in energy?

Most oil & gas is commodity-cyclical and doesn't fit the quality-compounder archetype. Possible quality compounder candidates:
- Best-in-class low-cost producers with strong balance sheets through cycles
- Midstream companies with stable fee-based revenues (less commodity sensitivity)
- Energy infrastructure (utilities-adjacent)
- Service/equipment companies with technology moats

Avoid speculative E&P (high-cost producers, single-basin pure plays without scale, leverage that doesn't survive low-price scenarios).

## Source quality tier guidance

- Tier 1: 10-K (with full reserves disclosure), 10-Q, EIA government data, federal regulatory filings (FERC, BLM), SEC reserve estimator
- Tier 2: Earnings calls, IR presentations, reserve report (third-party engineering)
- Tier 3: Wood Mackenzie, IHS/S&P Global Commodity Insights, Bloomberg energy specialists
- Tier 4: General financial press, energy blog opinions
