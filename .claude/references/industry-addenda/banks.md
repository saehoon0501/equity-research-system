# Industry Addendum: Banks / Financials

Loaded by `company-deep-dive` subagent when company classification = bank, regional bank, money center bank, investment bank, or insurance-holding hybrid.

Standard equity ratios produce nonsense outputs for banks. This addendum replaces the standard `valuation_model` and `key_risks` sections with bank-appropriate metrics.

## Replace standard valuation with bank-specific

### Primary valuation metric

**P/TBV (Price to Tangible Book Value)**, not P/E or EV/EBITDA.

```
P/TBV = market_cap / (book_value − goodwill − intangibles)
```

Banks trade on tangible book; goodwill from acquisitions doesn't earn returns. Historical bank multiples:
- Premium banks (excellent ROTCE): 1.8–2.5x P/TBV
- Average banks: 1.0–1.5x P/TBV
- Distressed: <1.0x P/TBV (market signaling capital concerns)

### Profitability primary metric

**ROTCE (Return on Tangible Common Equity)**, not ROE or ROA.

```
ROTCE = net_income_to_common / average_tangible_common_equity
```

Targets:
- Excellent: ≥15%
- Good: 12–15%
- Average: 10–12%
- Subpar: <10%

ROE can be inflated by leverage; ROTCE strips that and goodwill bloat. ROIC also less useful for banks because invested capital is hard to define.

## Required ratios (in addition to or replacing standard)

| Ratio | Definition | Healthy range |
|---|---|---|
| **Net Interest Margin (NIM)** | (interest income - interest expense) / earning assets | 3.0–4.0% for community banks; 2.0–3.0% for money centers |
| **Efficiency Ratio** | non-interest expense / revenue | <60% excellent; 60–65% good; >70% subpar |
| **CET1 Capital Ratio** | common equity tier 1 / risk-weighted assets | ≥10% required; ≥12% strong; ≥14% excellent |
| **Net Charge-Off Rate** | net loan charge-offs / total loans | <0.5% benign credit cycle; >1.5% stressed; >2.5% severe |
| **Non-Performing Loans (NPL) Ratio** | non-performing loans / total loans | <1.0% healthy; 1.0–2.0% watch; >3.0% stressed |
| **Allowance for Loan Losses (ALLL)** ratio | ALLL / total loans | 1.0–1.5% normal; >2.0% conservative or distressed signal |
| **Loan-to-Deposit Ratio** | total loans / total deposits | 70–90% typical; <60% under-deployed; >100% wholesale-funded |
| **Tangible Book Value Growth** | YoY % change in TBV per share | ≥10% strong; 5–10% good; <5% weak |

## DCF doesn't work for banks

Standard DCF (EBIT × (1-t) + D&A − CapEx − ΔWC) is meaningless for banks. Banks don't have CapEx or working capital in the standard sense; their "operations" are deposit-taking and lending.

Substitute valuation methodologies:

### Dividend Discount Model (DDM)

Banks are typically dividend-paying with stable payout ratios. Two-stage DDM:

```
Value = Σ (D_t / (1+r)^t) for t=1 to terminal,
        + terminal value via Gordon Growth on dividends

where:
  - D_t = expected dividend in year t
  - r = cost of equity (CAPM, with bank beta typically 1.1–1.3)
  - g = sustainable dividend growth rate (often tied to ROTCE × retention)
```

### Excess Returns Model

```
Value = Book Value + Σ (Excess Returns / (1+r)^t)
where:
  Excess Returns_t = (ROTCE_t - cost_of_equity) × beginning_tangible_equity
```

This captures whether the bank earns above its cost of capital — the bank-specific equivalent of "ROIC > WACC."

## Required risk factors (10-K Item 1A) to extract

Beyond standard risk factors, focus on:

1. **Credit risk concentration** — single borrower, industry, geography exposures
2. **Interest rate risk** — duration of assets vs liabilities; net interest income sensitivity to rate shocks
3. **Liquidity risk** — deposit composition (insured vs uninsured); wholesale funding reliance; contingent liquidity sources
4. **Capital adequacy** — current vs regulatory minimums; planned capital actions; CCAR/stress test results
5. **Regulatory risk** — pending enforcement actions; consent orders; CFPB or OCC examinations
6. **Model risk** — internal models for ALLL, capital, valuation; recent regulatory feedback
7. **Cybersecurity** — recent incidents, controls, third-party exposure

## Required disclosures from 10-K to surface in memo

- Loan portfolio composition (commercial real estate, residential mortgage, commercial & industrial, consumer, etc.)
- Geographic concentration of loans and deposits
- Top 10 deposit relationships (if disclosed; usually only for community banks)
- CRE concentration vs CET1 (regulatory guidance: <300% is recommended)
- Office CRE exposure (post-2023 hot topic)
- Regulatory capital actions (CCAR, DFAST, Basel implementation)

## Industry-specific catalysts

- Quarterly Federal Reserve rate decisions (FOMC) — direct NIM impact
- Annual stress test results (CCAR for top banks, DFAST below threshold)
- Quarterly call reports
- Bank-specific economic indicators (CPI for inflation expectations; jobless claims for credit cycle)
- M&A activity in the sector (regional bank consolidation)

## What doesn't apply

- Standard P/E, EV/EBITDA — meaningless for banks
- ROIC vs WACC framework — banks have non-standard "invested capital"
- DCF in standard form — replace with DDM or Excess Returns
- "Capex / R&D" framing — banks don't have it; technology spend is OpEx and shows up in efficiency ratio

## Source quality tier guidance for bank claims

- Tier 1: 10-K, 10-Q, call reports (Federal Reserve Y-9C for holding companies), CCAR results, FDIC data
- Tier 2: Earnings call transcripts, IR presentations, investor day materials
- Tier 3: Bloomberg, S&P Global Market Intelligence, established bank-focused publications (American Banker)
- Tier 4: Sell-side estimates without specific report citation, retail blogs

## Concentration risk thresholds for portfolio

If considering multiple bank positions (or financial-adjacent positions), pay attention to:
- Sector cap from v2-final §2.4: max 35% in financials
- Correlation cluster: 3+ banks with correlation >0.8 triggers correlation alert
- Macro exposure: rate-sensitive concentration during anticipated rate cycle inflections
