# Quantitative Analyst Brief — Template

This template defines the shape of the brief that `cdd-lead` constructs and injects into `quantitative-analyst`'s prompt at dispatch time. The cdd-lead fills each section with sector- and company-specific content drawn from: research_essentials, fresh search-agent findings, the 5-framework core canon, and the prior brief (if warm-start).

The template itself is sector-agnostic. The same structure is used for AAPL, IONQ, a 2027 vertical-AI-agent novel-sector company — only the *content* in each section differs.

---

## Section 1: Tier and identification

- **Tier:** {core_fundamental | thematic_growth | speculative_optionality}
- **Sector identification:** {free-form, e.g. "infrastructure SaaS" or "trapped-ion quantum compute"}
- **Brief type:** quantitative
- **Cold-start or warm-start:** {if warm-start, link prior_brief_id and delta_summary}

## Section 2: Revenue decomposition guidance

For this sector, the load-bearing way to decompose revenue is:
{cdd-lead fills: e.g., for semis = bits × ASP × mix; for SaaS = ARPU × paying customers × NRR; for energy = production × realized price × hedging; for biotech = approved-product royalties + pipeline NPV}

Key drivers to surface in the analyst's output:
{cdd-lead lists 3-5 specific drivers}

## Section 3: Margin and operating leverage guidance

Margin structure peculiarities for this sector:
{cdd-lead fills: e.g., for SaaS = gross margin near 70-80% normal, AI-native 50-60%; for semis = high fixed-cost cyclicality; for banks = N/A, use NIM + efficiency ratio instead}

Cost-of-revenue line items the analyst must isolate:
{cdd-lead lists}

## Section 4: Quality gate inputs

Piotroski F-Score inputs (9 items) — sector-specific notes:
{cdd-lead fills any sector-specific F-Score interpretation, e.g., for banks the leverage/liquidity sub-score uses CET1 not debt-to-equity}

Altman Z-Score variant:
- Manufacturers: standard Z
- Non-manufacturers: Z''
- Financial firms: Merton distance-to-default (not Z)
{cdd-lead picks the right variant for this company}

## Section 5: Damodaran narrative-DCF stress cases

Three required cases (bear / base / bull) with explicit assumptions:
- Growth rate ranges to test
- Margin ranges
- Duration / fade pattern
- Discount rate (use NYU Stern industry beta + ERP, link: https://pages.stern.nyu.edu/~adamodar/)

{cdd-lead pre-loads any sector-specific assumption ranges from research_essentials}

## Section 6: Mauboussin reverse-DCF (expectations investing)

Compute from current price:
- implied_growth (revenue CAGR over CAP)
- implied_margin (steady-state operating margin)
- implied_duration (competitive advantage period in years)

Compare against the company's actual ROIIC (last 5y average) and historical revenue CAGR. Where divergence > 1σ, that's the alpha or the warning.

{cdd-lead pre-loads MEROI from research_essentials if available}

## Section 7: Comparable peer set

Peer tickers for relative valuation:
{cdd-lead fills 3-5 named peers from search-agent + EDGAR SIC + research_essentials}

For each peer, the multiples to surface:
- P/E (trailing + forward)
- EV/EBITDA
- EV/Sales
- {sector-specific multiple, e.g., P/B for banks, EV/2P for E&P}

## Section 8: Recent material data

Fresh data from search-agent (≤30 days where applicable):
{cdd-lead fills: latest earnings beat/miss, recent estimate revisions, recent capacity announcements}

## Section 9: Warm-start delta (skip on cold-start)

Since prior brief at {prior.created_at}:
{cdd-lead fills delta_summary content here — what changed, what's new, what's stale}

## Section 10: Banned outputs reminder

The analyst must NOT output:
- PEG-only ranking
- Stovall sector rotation framing
- Fed commentary without HFI window or FOMC-cycle reference
- Point price targets if tier ∈ {thematic_growth (use ranges), speculative_optionality (skip DCF entirely)}

## Section 11: Output schema reminder

Memo MUST emit:
- frameworks_cited (with framework_key short-keys from canonical-frameworks.md)
- quality_gate (Piotroski F + Altman Z'')
- DCF outputs (3 cases, ranges if thematic_growth, SKIP if speculative_optionality)
- reverse-DCF outputs (implied growth/margin/duration; SKIP if speculative_optionality)
- yfinance_data_freshness flags
