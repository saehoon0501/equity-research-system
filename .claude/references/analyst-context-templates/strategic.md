# Strategic Analyst Brief — Template

This template defines the shape of the brief that `cdd-lead` constructs and injects into `strategic-analyst`'s prompt at dispatch time. Sector-agnostic; cdd-lead fills sections with specific content per company.

---

## Section 1: Tier and identification

- **Tier, sector, brief_type=strategic, cold/warm-start** (same as quantitative.md Section 1)

## Section 2: Mauboussin Moat 2024 — sources of advantage

For this sector, the most likely moat sources are:
{cdd-lead fills 1-3 candidate moat sources}

Production advantages to test for:
- Scale economies (sub-additive cost structure)
- Process power (proprietary knowhow that competitors can't replicate)

Consumer advantages to test for:
- Network effects (direct, indirect, two-sided, data, local)
- Switching costs (financial, procedural, relational)
- Search costs (information asymmetry favoring incumbent)
- Habits (consumer behavior lock-in)

External advantages to test for:
- Regulation (e.g., banking charters, FDA approval, spectrum licenses)
- Subsidy / tax preference

Expected fade pattern over next decade:
{cdd-lead fills based on sector empirics from research_essentials, e.g., "consumer brand moats fade slowly (~30y); software switching costs fade fast under platform shifts"}

## Section 3: Helmer 7 Powers — taxonomy check

Apply each Power; for each claimed Power state Benefit (cash-flow effect) AND Barrier (why competitor arbitrage fails):

1. Scale Economies
2. Network Economies
3. Counter-Positioning (rarely held; high-signal when present)
4. Switching Costs
5. Branding
6. Cornered Resource
7. Process Power (rarely held; high-signal when present)

Common confusions in this sector:
{cdd-lead fills, e.g., "Network Economies often over-claimed — distinguish from Switching Costs by asking: does adding the Nth user increase value to existing users (Network) or just raise the cost of leaving (Switching)?"}

## Section 4: Mauboussin Capital Allocation 5-bucket grading

Grade past 5y allocation across 5 buckets, against ROIC vs WACC:

1. **CapEx** — net of depreciation; ROIC on incremental capital
2. **R&D** — capitalize and grade per dollar of NPV-positive revenue created
3. **M&A** — pay-back period; goodwill impairment trail
4. **Dividends** — coverage; trajectory
5. **Buybacks** — only NPV-positive when bought below intrinsic value (cite implied_value from reverse-DCF)
6. **Debt paydown / leverage management**

Sector-specific allocation patterns:
{cdd-lead fills, e.g., "for banks, layer in CET1 capital deployment (loan growth vs buybacks); for E&P, F&D cost on incremental reserves vs share repurchase"}

## Section 5: Strategic context — sector-specific

{cdd-lead fills 200-400 tokens of sector-specific strategic framing pulled from search-agent + research_essentials. Examples:
- For platforms: Hagiu/Eisenmann multi-sided analysis (which side subsidized, cross-side network direction, chicken-and-egg solution at cold-start, envelopment risk)
- For semis: foundry vs fabless model, process node leadership vs trailing-edge, customer concentration risk
- For consumer: brand strength via gross margin, distribution moats, channel power dynamics
- For biotech: pipeline replacement rate, patent cliff timeline, regulatory moat type
- For novel sectors: cdd-lead synthesizes from first principles + recent news}

## Section 6: Recent strategic developments

Fresh from search-agent (≤90 days):
{cdd-lead fills: management changes, strategic pivots, M&A announcements, regulatory actions, key competitor moves}

## Section 7: (RETIRED 2026-05-17 — historical-analog matching removed)

The peak_pain_archetypes catalog has been retired. Analog-driven moat-fade pressure-testing is now handled by §4 pm-supervisor §2.6 stress-test using mechanism + falsifying-observable framing instead of named historical analogs.

## Section 8: Warm-start delta (skip on cold-start)

Since prior brief at {prior.created_at}:
{cdd-lead fills strategic-specific delta — moat strength change, capital allocation grade revision, new structural threats}

## Section 9: Banned outputs reminder

- No Stovall sector rotation framing
- No ARK-style decade-out point targets
- For speculative_optionality tier: no "next NVIDIA" framing without modality-specific evidence

## Section 10: Output schema reminder

Memo MUST emit:
- frameworks_cited with short-keys for moat / 7 Powers / capital allocation
- moat_sources (production / consumer / external) with fade pattern
- powers_held (1-N of 7 with Benefit + Barrier each)
- capital_allocation_grade (5-bucket; A-F or 1-5)
