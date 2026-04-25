# Industry Addendum: Biotech / Pharma

Loaded by `company-deep-dive` subagent when company classification = biotech, pharma, drug discovery, gene therapy, or life sciences with active clinical pipeline.

Standard equity valuation fails for pre-revenue biotechs. ~80% of Nasdaq Biotech Index components are loss-making. This addendum provides risk-adjusted NPV (rNPV) methodology and pipeline-specific risk factors.

## Replace standard valuation with rNPV

For pre-revenue or pipeline-dependent biotechs:

```
rNPV = Σ (probability_of_success × peak_revenue × duration_factor × discount_factor)
       − development_costs

For each pipeline asset:
  - probability_of_success: phase-staged (see below)
  - peak_revenue: addressable market × penetration assumption × pricing
  - duration: years of patent-protected revenue
  - discount: time-value of money + risk
```

## Phase-staged probability of success

Industry-standard approval probabilities (BIO 2024 and earlier studies; tunable based on therapeutic area):

| Phase | Probability of advancing to next phase | Cumulative probability of approval |
|---|---|---|
| Pre-clinical | 60–70% | 5–10% |
| Phase I | 60–70% | 10–15% |
| Phase II | 30–35% | 15–25% |
| Phase III | 55–65% | 50–65% |
| Approved (large stable pharma) | n/a | 90%+ for late-stage assets |

**Therapeutic-area variation:**
- Oncology: lower POS (high attrition); high revenue if approved
- Cardiovascular: medium POS; large markets but generic competition
- Rare diseases / orphan: higher POS (less competition, regulatory incentives); smaller markets but premium pricing
- Immunology / autoimmune: improving POS due to better targets

## Discount rate scaling with phase

Pre-clinical and early-stage assets get higher discount rates because the risk profile differs from established cash flows.

| Stage | Discount rate |
|---|---|
| Pre-clinical | 35–40% |
| Phase I | 30–35% |
| Phase II | 25% |
| Phase III | 15–20% |
| Approved, growing | 10–15% |
| Approved, stable large pharma | 8–12% |

## Required metrics for biotechs

| Metric | Definition | Why |
|---|---|---|
| **Cash runway** | cash + ST investments / quarterly burn | Pre-revenue biotechs measured in months/quarters of survival |
| **Cash burn rate** | quarterly operating cash outflow | Sustainability |
| **EV/Cash** | enterprise value / cash on hand | Sometimes EV is below cash (negative enterprise value); signal |
| **EV/R&D** | EV / annual R&D spend | Approximation of "what is the market valuing each $ of R&D investment" |
| **Pipeline depth** | # candidates by phase | Diversification across attrition risk |
| **Therapeutic area concentration** | weighted by pipeline value | Single-area exposure is risk |
| **IP runway** | weighted-average years to patent expiration of approved drugs | Cliff exposure |

## Pipeline disclosure (extract from 10-K)

Document each pipeline candidate with:

1. **Target indication** — disease and patient population
2. **Mechanism of action** — clinical novelty
3. **Phase** — pre-clinical, P1, P2, P3, NDA, approved
4. **Trial milestones** — past readouts, expected next readout (data, dates)
5. **Differentiation** — vs. competing therapies in same indication
6. **Partnership status** — wholly owned vs licensed (with milestone payments and royalties)
7. **Patent status** — composition of matter, formulation, methods-of-use; key expiration dates

## Comparables and "biobucks"

For deal-comparable valuation, look at recent M&A and licensing deals in the same therapeutic area:

```
Deal value = upfront + milestones + royalties (in expected value terms)
"Biobucks" = total potential deal value (upfront + all milestones, undiscounted)
```

Biobucks headlines are misleading because milestones are heavily probability-weighted. Use risk-adjusted deal values.

## Catalysts

Biotechs are catalyst-driven; surface these explicitly in memos:

- **Trial readouts** (P1, P2, P3 data) — typically the biggest single moves
- **FDA decisions** — PDUFA dates (Prescription Drug User Fee Act target action date)
- **Advisory committee meetings** (AdComs) — non-binding but predictive
- **Label expansion** — supplemental approvals
- **Patent litigation outcomes**
- **CRL (Complete Response Letter) responses** — re-submission timing
- **Conference presentations** — ASCO (oncology), AHA (cardio), ASH (hematology), AAD (derm), etc.

For each catalyst, note:
- Expected window (date range)
- Hard date vs soft (PDUFA = hard; ASCO = soft within 2-day conference)
- Severity (transformational, material, incremental)

## Required risk factors to extract from 10-K

1. **Clinical trial risk** — current trials, primary endpoints, statistical assumptions
2. **Regulatory risk** — FDA advisory committee composition; expected agency posture
3. **IP risk** — pending litigation, patent thickets, biosimilar/generic threat timing
4. **Manufacturing risk** — single-source manufacturing; CRO dependencies
5. **Reimbursement risk** — payer coverage decisions; ICER reviews
6. **Competition** — pipeline of competitors in same indication
7. **Going concern / cash runway** — for pre-revenue, this is critical

## What doesn't apply

- P/E, EV/EBITDA — meaningless when company is loss-making
- ROIC vs WACC — meaningless without revenue
- Standard DCF on free cash flow — replace with rNPV across pipeline
- Quality compounder framework — biotech is binary (drug works or doesn't); doesn't fit "compounder" archetype

## When biotech is appropriate vs not for the watchlist

The v2-final spec's golden standard is "quality compounder + one explicit AI-infrastructure carve-out." Pre-revenue biotech generally doesn't fit the quality-compounder archetype. Possible exceptions:

- Late-stage biotechs near approval with well-established cash runway and de-risked pipeline
- Approved-product pharma with stable cash flows (closer to consumer staples archetype than biotech)
- Tools/equipment companies serving biotech customers (e.g., diagnostics, lab equipment) — these are operating businesses, not pipeline-dependent

Pure pre-revenue speculation is excluded from the watchlist by design. If the operator wants biotech exposure, this addendum supports the case-by-case evaluation of more mature biotech/pharma names.

## Source quality tier guidance for biotech claims

- Tier 1: 10-K, 10-Q, ClinicalTrials.gov, FDA Drug Approval letters, NEJM/JAMA published trial results
- Tier 2: Earnings calls, ASCO/AHA/ASH conference presentations (recorded, official), management presentations
- Tier 3: BioPharma Catalyst, FierceBiotech, Endpoints News, BioCentury (specialized trade press)
- Tier 4: Pre-prints (medRxiv, bioRxiv) without peer review; general financial press without therapeutic-area specialization
