# Industry Addendum: Software / SaaS

Loaded by `company-deep-dive` subagent when company classification = SaaS, software, cloud-native, infrastructure software, or PaaS.

Software has its own unit economics framework that's well-established in 2024-2026.

## Required SaaS-specific metrics

### Rule of 40

The headline efficiency metric:

```
Rule of 40 = Revenue Growth Rate (%) + Profit Margin (%) ≥ 40%
```

Where Profit Margin is:
- **EBITDA margin** for public companies (more standardized)
- **Free Cash Flow margin** for late-stage software (closer to true cash economics)

Industry observations (McKinsey 200+ software company analysis 2011-2021):
- Firms exceeded R40 only 16% of the time
- Consistent achievers (multi-year R40 hits) traded at meaningfully higher EV/Revenue multiples (1.3-1.8x premium)

R40 cliff: companies dropping below 40% see multiple compression; companies sustaining above see expansion.

### Net Revenue Retention (NRR)

Cohort revenue performance:

```
NRR = (Starting ARR + Expansion + Reactivation − Contraction − Churn) / Starting ARR
```

- **>120%** strong; top quartile typically 130%+
- **110-120%** healthy
- **100-110%** stable but growth depends on net new
- **<100%** revenue contraction; concerning unless intentional (e.g., consumption pricing model)

NRR by customer segment is more informative than headline NRR (enterprise NRR vs SMB NRR can diverge).

### Other key metrics

| Metric | Definition | Target |
|---|---|---|
| **ARR (Annual Recurring Revenue)** | annualized subscription revenue | trajectory matters more than absolute |
| **Magic Number** | (current_quarter_revenue − prior_quarter_revenue) × 4 / prior_quarter_S&M | >1.0 efficient growth; <0.5 inefficient |
| **CAC Payback** | gross_margin × ACV / sales_marketing_per_new_customer | <18 months efficient; >36 months concerning |
| **LTV/CAC** | (ACV × gross_margin / churn_rate) / customer_acquisition_cost | >3x healthy; >5x excellent |
| **Gross Margin** | (revenue − COGS) / revenue | software gross margins 70-90%; <70% likely SaaS-like rather than true SaaS |
| **Free Cash Flow Margin** | FCF / revenue | varies by stage; mature software 25-40% |
| **Billings vs Revenue** | YoY billings growth vs YoY revenue growth | billings should lead revenue; divergence flags concerns |

### ARR per employee

Operational efficiency indicator:
- Top decile: $400K+ per employee
- Healthy: $250-400K
- Average: $150-250K
- Concerning: <$150K (likely overstaffed or weak product-market fit)

## Cohort analysis

For deeper insight, look at cohort retention by year of acquisition:

```
Cohort 2021: $100 → $115 → $130 → $135 → $140 (NRR strong, expansion solid)
Cohort 2022: $100 → $108 → $115 → $118
Cohort 2023: $100 → $102 → $98 (concerning; churning)
```

Cohorts diverging signals product-market fit changes, competitive dynamics, or pricing model issues.

## Customer concentration

- Top 10 customers as % of revenue
- Net revenue retention excluding top 10 (sometimes top 10 is unrepresentative)
- Logo concentration vs revenue concentration

## Standard valuation methodologies

### EV/Revenue multiples

Software valuation is dominated by EV/Revenue:
- EV/ARR is more precise (excluding services revenue)
- Multiple correlates strongly with growth + R40 + NRR
- Comparable companies should be matched on growth rate and profitability profile

### Forward valuation

```
Forward EV/Revenue = Current EV / (current_ARR × (1 + expected_NTM_growth))
```

Compare to:
- Sector median forward multiple
- Comparable mid-cap or large-cap software depending on size
- Historical own multiple (5y range)

### DCF works for mature software

DCF valid for mature, FCF-positive software:
- Long discount horizons (15-20 years; software TAMs are big)
- Terminal value typically 60-80% of total
- Gross margin trajectory and market saturation are key sensitivity inputs
- Watch for stock-based comp inclusion in FCF (often excluded; should be subtracted from FCF for honest valuation)

## Required risk factors to extract from 10-K

1. **Customer concentration** — top customer % of revenue
2. **Product market fit drift** — gross margins, NRR by segment
3. **Pricing model risk** — usage-based pricing in macro slowdown
4. **Sales efficiency** — Magic Number, CAC Payback trend
5. **Competition** — incumbents, new entrants, AI-native disruption
6. **Cybersecurity** — breach events, data security exposure
7. **Regulatory** — GDPR/CCPA, SOC 2 compliance, data residency
8. **Stock-based comp dilution** — many software companies have material SBC

## SaaS in 2024-2026 context

Specific themes:
- **AI-native disruption**: many SaaS categories now have AI-native challengers; established SaaS companies racing to integrate AI
- **Consumption-based pricing transitions**: shift from per-seat to per-token / per-API call models
- **Hyperscaler concentration**: heavy customer dependence on AWS/Azure/GCP
- **Slowdown in enterprise software spending** (post-2022 efficiency push)
- **AI infrastructure software** (vector DBs, observability, MLOps) — fast-growing subsector

## Industry-specific catalysts

- Quarterly earnings (ARR, NRR, R40 metrics)
- Major customer wins or losses
- AI feature launches / strategic shifts
- Pricing model changes
- M&A activity in space
- Hyperscaler ecosystem dynamics

## Quality compounder candidates in software

The v2-final golden standard — quality compounder + AI-infrastructure carve-out — fits software well:

**Quality compounder software:**
- Stable, profitable, dominant market position
- Strong NRR (≥120%)
- Multi-year R40 achievement
- Defensible moat (network effects, switching costs, data scale)
- Examples archetype: Microsoft, Adobe, Intuit, ServiceNow

**AI-infrastructure carve-out:**
- Companies building AI tools/infrastructure (the picks-and-shovels)
- May have lower current profitability but TAM expansion case
- Higher volatility; watch position sizing

## Source quality tier guidance

- Tier 1: 10-K, 10-Q (with detailed metrics in MD&A), 8-K guidance
- Tier 2: Earnings calls, IR presentations, customer conferences (Salesforce Dreamforce-style events with disclosed metrics)
- Tier 3: Established software-focused publications (The Information for tech industry; Bessemer Cloud Index; PitchBook for private comparables)
- Tier 4: General financial press without software specialization
