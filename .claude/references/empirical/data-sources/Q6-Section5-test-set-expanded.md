# Q6 Section 5 — Expanded Test Set Proposal (12 Subagent Synthesis)

**Date:** 2026-04-29
**Purpose:** Synthesize 12 parallel research subagents into an expanded calibration test set for the L3 counterfactual mechanical-similarity system. Original proposal was ~25 cases; this expansion produces ~120 cases across canaries / known-good / stratified-similarity.

**Predecessor:** Q6 calibration architecture locked in `Q6-Section5-synthesis.md`. This document expands the test-set component of that architecture.

---

## 1. Coverage matrix

12 parallel subagents covered (sector × failure-vs-success):

| Domain | Failures (canaries) | Successes (known-good) |
|---|---|---|
| Tech-platform | ✓ 3 strong + 10 stratified-similarity | ✓ 12 cases |
| Consumer/retail | ✓ 14 | ✓ 9 |
| Financials | ✓ 12 | ✓ 10 |
| Energy/commodities | ✓ 7 | ✓ 5 |
| Healthcare/biotech | ✓ 8 | ✓ 7 |
| International/EM | ✓ 7 | ✓ 6 |
| Recent IPOs/SPACs | ✓ 5 | ✓ 5 |
| Capital structure / governance | ✓ 9 | ✓ 1 (Snap survivor) |
| Audit/accounting/SEC | ✓ 11 | (covered by sector subagents) |

Total deduplicated: ~70 canaries, ~55 known-good. Overlap (e.g., Adelphia/Tyco/GE appear in both capital-structure and audit subagents) deduplicated below.

---

## 2. Canary set (deduplicated, ~70 cases)

Companies that catastrophically failed; system MUST flag them. Coverage spans sector × era × failure-mode-archetype.

### Tech-platform / SaaS / consumer-tech (15)
- **23andMe** (SPAC + recurring-revenue assumption failure + governance collapse 2024-25)
- **SmileDirectClub** (founder-dilution + neg-margin telehealth + Ch.7 2024)
- **Quibi** (capital-distortion + zero PMF + era-mismatch)
- **BuzzFeed** (SPAC 94% redemption + platform-dependency)
- **Magic Leap** (charismatic founder + demo-ware + 2x layoffs)
- **Vice Media** ($5.7B → $225M; multi-vehicle capital stack)
- **Convoy** ($3.8B unicorn → $0 in 18mo; freight-cycle exposure)
- **Bird Global** (SPAC + unit-economics never proved)
- **Peloton** (pull-forward demand misread; -95% from peak)
- **Just Eat Takeaway / Grubhub** (M&A value destruction $7.3B → $650M; -91%)
- **Oatly** (-98% from peak; capex 28% of revenue; misread TAM)
- **Pets.com / dot-com basket** (already in 32-case canon)
- **WeWork** (already in 32-case canon — emphasizes founder-control + RPT)
- **Cisco-2000** (already in 32-case canon — extreme valuation at peak)
- **Theranos** (already in 32-case canon)

### Consumer/retail (14)
- **JCPenney 2020** (Ackman/Johnson activist destruction)
- **RadioShack 2015 + 2017** (7 CEOs in 9yr; $2.6B buybacks)
- **Borders 2011** (Amazon outsourced; missed e-reader cycle)
- **Aeropostale 2016** (mall-channel concentration; logo-tee aged)
- **Forever 21 2019 + 2025** (100k sqft footprints; SHEIN disruption)
- **Payless ShoeSource 2017 + 2019** (LBO debt; Ch.22)
- **Gymboree 2017 + 2019** (Bain LBO debt; Ch.22)
- **Neiman Marcus 2020** (LBO ×2; $5B debt @ 12.4x)
- **J.Crew 2020** (PE LBO; first PE-backed retailer to file COVID)
- **Lord & Taylor 2020** (Le Tote rental SaaS acquisition mismatch)
- **Stein Mart 2020** (off-price stuck between TJX and dept-stores)
- **GNC 2020** (small-box mall obsolete)
- **Tuesday Morning 2020 + 2023** (Ch.22)
- **Sears trajectory** (already in 32-case canon — slow secular decline)

### Financials (12)
- **SVB 2023** (digital-deposit run; 94% uninsured; ~36hr collapse)
- **Signature 2023** (90% uninsured; ~20% crypto deposits)
- **First Republic 2023** (HNW concentration; long-duration loans; ~52d collapse)
- **Washington Mutual 2008** (option-ARM book $52.9B; $16.7B/9d outflow)
- **Wachovia 2008** (Pick-A-Pay/Golden West $120B option-ARM)
- **AIG 2008** (AIGFP $500B+ CDS notional; counterparty cascade)
- **Northern Rock 2007** (86.3× leverage; 75% wholesale-funded)
- **IndyMac 2008** (assets tripled $22B→$90B in 3yr; Alt-A monoline)
- **Credit Suisse 2023** (chronic franchise erosion; AT1 wipeout)
- **IKB 2007** (Rhineland Funding ABCP rollover failure)
- **Monte Paschi 2016** (NPL ratio 34.8%; failed cap raise)
- **Countrywide 2008** ($97.2B subprime book; mortgage monoline)
- **Lehman / Bear / LTCM** (already in 32-case canon)

### Energy/commodities (7)
- **Chesapeake Energy 2020** ($9.5B debt; debt-fueled leasing under McClendon)
- **Linn Energy 2016** ($10B debt; MLP yield-chase)
- **SandRidge Energy 2016** ($4.1B debt converted to equity)
- **Whiting Petroleum 2020** ($3.6B debt; D/EBITDA >3x; Bakken acreage chase)
- **Halcon Resources 2019** (second BK in 3 years; Floyd Wilson serial leveraging)
- **McDermott International 2020** (CB&I deal blowup; leverage 1.3x→17.6x)
- **Murray Energy 2019** (coal demand decline + debt-funded acquisitions)

### Healthcare/biotech (8)
- **MannKind** (FDA CRLs; Sanofi terminated; commercial flop)
- **Biogen Aducanumab** (10-0 ADCOMM "no" approved anyway; payer rejection)
- **Endo International 2022** ($8B debt + opioid liability)
- **Mallinckrodt 2020 + 2023** (Ch.22; opioid liability)
- **Tenet Healthcare** (CMS recurring fraud; $900M FCA settlement)
- **Allergan/Actavis 2016** (sequential roll-up; Ireland inversion abort)
- **Pacific Biosciences early** (10-15% error rate; sub-scale)
- **Theranos / Valeant** (already in 32-case canon)

### International / EM (7)
- **Wirecard 2020** (auditor 10yr fraud; €1.9B fictitious cash)
- **Luckin Coffee 2020** (related-party round-tripping; $300M fabricated)
- **Evergrande 2021** ($300B liabilities; three-red-lines)
- **Country Garden 2023** ($186B liabilities; offshore default)
- **Zhongzhi Enterprise 2024** ($140B AUM Ponzi; insolvent $64B)
- **Didi 2021** (CAC delisting forced; $1.2B fine)
- **TAL Education 2021** ("double reduction" sector ban; -93%)

### Recent IPOs/SPACs (5)
- **Cazoo 2024** (£6.3B SPAC → $35M; UK admin)
- **FaZe Holdings 2023** (negative $73M equity at IPO; -97.7%)
- **Better.com 2023** (-90% IPO day; SoftBank forced-seller risk)
- **Owlet Baby 2021** (FDA warning letter; Class II without 510k)
- **Vinco Ventures 2023** (undisclosed control person; Farnsworth fraud)
- (Plus already-canon: Nikola, Lordstown, Clover, Lucid, Hyzon, Beachbody, Bird, Allbirds, Lyft)

### Capital structure / governance (5 distinct + overlap with audit/sector)
- **WeWork** (already in 32-case canon — founder dilution + RPT)
- **Adelphia 2002** (dual-class Rigas family looting)
- **Tyco 2002** (captured board; $170M+ undisclosed officer loans)
- **Rite Aid 2002** (largest restatement; concealed RPTs)
- **HP/Autonomy 2012** ($8.8B writedown; due-diligence governance gap)
- **GE 2017-2020** ($200M SEC; Power earnings + LTC reserves)
- **Caterpillar 2017** (CSARL Swiss tax-shift)
- **Frontier Communications 2020** ($17.5B debt; Verizon DD failure)

### Audit / accounting fraud (11 — overlapping with sector subagents)
- **WorldCom 2002** ($3.8B+ capitalized expenses; AA missed)
- **Sunbeam 1996-98** (Dunlap channel-stuffing; Andersen barred)
- **Lernout & Hauspie 1996-2000** ($60M fictitious; KPMG withdrew opinions)
- **Olympus 2011** (¥117.7B tobashi loss-hiding; KPMG→EY handoff)
- **Toshiba 2008-14** (¥224.8B overstatement; EY 60yr tenure)
- **Diamond Foods 2012** ("the lever" walnut-payment shifting)
- **Steinhoff 2009-17** (€6.5B related-party transactions; Deloitte refused 2017 sign-off)
- **Kraft Heinz 2015-18** ($208M restatement; supplier discount fraud)
- (Plus already noted: WorldCom, Adelphia, Tyco, GE)

---

## 3. Known-good set (deduplicated, ~55 cases)

Companies that survived superficially-failure-like signals; system must NOT flag despite surface similarity.

### Tech-platform (12)
- **Amazon 2001-2003** (cash-burn; -94% drawdown; survived)
- **Salesforce 2008-2009** (-70% GAAP/SBC skepticism; ~14x)
- **Salesforce 2023** (5-activist siege + AI panic; same-year recovery)
- **Adobe 2013-2014** (subscription pivot revenue compression; 12x+)
- **Microsoft 2014-2016** (Nadella Nokia writedown; 10x+)
- **Netflix 2011-2013** (Qwikster; -77%; ~10x recovery)
- **ServiceNow 2012 IPO+** (high-multiple SaaS skepticism; ~50x+)
- **Atlassian 2015 IPO+** (87% founder voting; ~7x)
- **Zoom 2020** (100x sales; 40% founder voting; ~10x to peak)
- **Shopify 2020-2021** (40-43x sales; multi-bagger)
- **Palantir 2020-2024** (founder mystique; +1,874% by 2025)
- **Square/Block 2018-2019** (~30x sales; ~27x return from 2015 IPO)

### Consumer/retail (9)
- **Chipotle 2015-18** (E.coli; -67% drawdown; ~5x rally)
- **Domino's Pizza 2010** ("our pizza was bad" reset; ~3,175% TR over 15yr)
- **Starbucks 2008-2009** (Schultz return; +143% in 2009; >1,000% from lows)
- **Best Buy 2012** (Joly Renew Blue; $18→$65+; +263%)
- **Lululemon 2013** (Wilson scandal/sheer pants; $36→$65 in 6mo)
- **McDonald's 2014-2015** (Easterbrook; stock doubled)
- **Costco 2008-2009** (FY09 sales -2%; tripled from crisis lows)
- **Hermès 2010-2014** (LVMH stalking-horse; family pool defense)
- **Ferrari 2015 IPO+** (51.6% voting concentration; ~7-10x)

### Financials (10)
- **JPMorgan 2008-2010** (TARP recipient; ~9x to 2021)
- **Bank of America 2011-2019** (sub-$5; $5.13→$35.72; ~7x)
- **American Express 2008-2009** (-64% in 2008; ~10x+ to 2018)
- **Morgan Stanley Sep-Oct 2008** (1994-level lows; MUFG emergency check)
- **Goldman Sachs 2010** (Abacus SEC; $7.9B mkt cap added on settlement)
- **Discover 2009-2019** ($1.2B TARP; +159% Mar 2009-Jan 2010)
- **BlackRock 2009 BGI deal** ("deal of the century")
- **AIG post-bailout 2010-2017** (Treasury 92% recovered +$15.1B)
- **Wells Fargo 2016-2024** (fake-accounts; consent order lifted Feb 2024)
- **Charles Schwab 2009** (-56% to all-time-high $80+ by 2021)

### Energy/commodities (5)
- **ExxonMobil 2014-2020** (capex cut; dividend held; survived)
- **Chevron 2014-2020** (dividend held through trough; LNG cash flow)
- **Pioneer Natural Resources** (hedging-led survivor; A-rated Permian inventory)
- **EOG Resources** (premium-drilling 30% ATROR hurdle at $40 oil)
- **Devon Energy** (2021 WPX merger; value-over-volume pivot)

### Healthcare/biotech (7)
- **UnitedHealth** (16.2% annualized 10y; multi-decade compounder)
- **Regeneron** (single-asset Eylea → multi-franchise Dupixent)
- **Vertex** (CF monopoly Trikafta >$6B 2025)
- **Eli Lilly** (Zyprexa cliff → GLP-1 pivot $40B run-rate 2026)
- **AbbVie** (Humira cliff → Skyrizi+Rinvoq $30B+ 2027)
- **Edwards Lifesciences** (Sapien TAVR multi-generation cycle)
- **Intuitive Surgical** (2008-2010 dilution concerns; recovered)

### International / EM (6)
- **Alibaba** (Ant pulled; $2.5B fine; survived but de-rated)
- **Tencent via Prosus/Naspers** (28-36% NAV discount; survived gaming crackdown)
- **MercadoLibre** (+2,000% / decade; cleanest EM compounder)
- **New Oriental** (-86% in 2021; pivoted to live-stream; survived)
- **PDD Holdings** (founder relinquished super-voting; survived)
- **XPeng / Nio partial** (XPeng +224% YoY 2025; Nio sub-brand reset)

### Recent IPOs (5)
- **Airbnb** (Dec 2020 IPO $68 → ~$129; 2024 net income $461M)
- **DoorDash** (first GAAP profit 2024; 2025 net income $935M)
- **Roblox** (Bookings +55% YoY to $6.8B in 2025)
- **Mr. Cooper** (+63% YTD 2024; Rocket $14.2B acquisition 2025)
- **Robinhood** (PFOF concentration survived; S&P 500 inclusion late 2025)

### Capital structure (1 survivor)
- **Snap Inc** (zero-vote public Class A — extreme structure but survived; useful negative-control showing not-all-founder-control-fails)

---

## 4. Stratified-similarity test cases (~50)

Cases where mechanical-similarity should retrieve specific top-3 counterfactuals. Used to validate retrieval quality (NDCG@3, Precision@3).

Key matches surfaced by subagents:

**Theranos archetype** (fraud + secrecy + dismissed bear research):
- 23andMe (data integrity collapse + founder control)
- Tenet (CMS data manipulation + recurring fraud)
- Aducanumab pre-FDA data-massaging
- Wirecard (long-running auditor failure)
- Olympus (KPMG→EY handoff missed)

**WeWork archetype** (founder dilution + RPT):
- Adelphia (Rigas family co-borrowing)
- Vice Media (charismatic founder $5.7B→$225M)
- Magic Leap (charismatic founder + demo-ware)
- Snap (extreme structure but survived — anti-pattern test)

**Hyzon archetype** (SPAC fraud + customer fabrication):
- FaZe Holdings (negative $73M equity at IPO)
- Vinco Ventures (undisclosed control person)
- Better.com (CEO personal guarantee = forced-seller)
- Cazoo (unsustainable expansion at IPO)
- Beachbody / Body / Allbirds (already canon)

**Pets.com archetype** (right-business-wrong-decade):
- Quibi (premium short-form vs free TikTok)
- Beyond Meat (narrative-driven without sustained PMF)
- Peloton (pull-forward demand misread)
- Forever 21 (mall-channel obsolete)

**Cisco-2000 archetype** (dominance at peak + extreme valuation + customer capex peak):
- NVDA-current (active test — pattern in progress)
- Tesla peaks (governance + valuation extremes)
- Palantir (similar surface but real product)

**Lehman archetype** (leverage spiral + asset-quality denial):
- WaMu (option-ARM denial + ratings cascade)
- Wachovia (Golden West acquisition)
- Countrywide (subprime monoline)
- IKB (off-balance-sheet leverage via SIVs)

**SVB archetype** (digital-deposit run + concentrated depositor monoculture + duration mismatch):
- Signature (crypto monoline analog)
- First Republic (HNW monoline)
- Northern Rock (wholesale-funding monoline)
- IndyMac (Alt-A originator + concentrated jumbo depositors)

**AIG archetype** (counterparty cascade + collateral-call death spiral):
- MBIA / Ambac (monoline insurers)
- Credit Suisse partial (Archegos/Greensill cascade)

**Credit Suisse archetype** (chronic reputation erosion + multi-year scandals → terminal confidence):
- Deutsche Bank (40:1 leverage; LIBOR/sanctions; chronic non-failure control)
- Monte Paschi (Italian governance + decade NPL accumulation)
- Wachovia (slow-mo Golden West thesis decay)

**Chesapeake archetype** (debt-fueled growth):
- Linn (MLP yield-chase)
- SandRidge / Whiting (Bakken acreage chase)
- Halcon (Floyd Wilson serial leveraging)
- McDermott (CB&I roll-up)

**WorldCom archetype** (revenue/expense recognition manipulation to hit Street):
- Sunbeam (channel-stuffing + premature recognition)
- Diamond Foods (cost deferral as EPS lever)
- Kraft Heinz (procurement expense scheme)
- GE (LTSA cost-estimate cookie jar)

**Tyco archetype** (captured board + executive looting):
- Adelphia (Rigas family co-mingling)
- Rite Aid (Grass concealed RPTs)
- Steinhoff (Jooste-orchestrated RPTs across 8 firms / 8 years)

**Sears archetype** (slow secular decline + channel obsolescence):
- RadioShack (small-box electronics)
- Borders (e-reader miss)
- Chico's FAS (decline-but-survived; near-miss anchor)
- GNC (mall-format obsolete)

**Toys R Us archetype** (LBO-debt-driven failure on viable business):
- Payless (Golden Gate dividend recap)
- Gymboree (Bain LBO debt + Ch.22)
- Neiman Marcus (TPG/Ares LBOs)
- J.Crew (TPG/Leonard Green LBO; first COVID retail file)

**Evergrande archetype** (real-estate Ponzi-like):
- Country Garden (three-red-lines)
- Zhongzhi (shadow banking Ponzi rollover)

**Didi/TAL archetype** (regulatory-edict shock):
- Counterfactual: US for-profit colleges 2014-16; payday CFPB cycles
- (Distinct from accounting-integrity fraud — purely sovereign/political)

---

## 5. New structural archetypes surfaced

Beyond the original 32-case catalog's archetypes, the 12-subagent expansion surfaces:

### A. Funding-side monoculture (financials)
SVB / Signature / First Republic / Northern Rock all share: concentrated funding source, unhedged duration mismatch, digital-era run dynamics. **Distinct** from asset-side monoculture (Countrywide / WaMu / IndyMac / Wachovia).

### B. Long-fuse vs short-fuse failure timescales
- Short-fuse (digital): SVB ~36h, First Republic ~52d
- Long-fuse (chronic): Credit Suisse multi-year, Deutsche Bank decade, GE 2016-2020 slow-motion
- Encode timescale as feature

### C. Ch.22 retail (re-bankruptcy within 2-3 years)
RadioShack, Payless, Gymboree, Tuesday Morning, Forever 21. **First-bankruptcy emergence is fragile** — refile rate is high signal.

### D. SPAC sponsor-favorable + 90%+ redemptions
2021-2024 cohort (BuzzFeed, 23andMe, Bird) shares structural mechanism — sponsor-favorable economics + 90%+ redemptions = under-capitalized public companies. Warrants own signature class beyond Hyzon/Nikola SPAC archetypes.

### E. Real-estate Ponzi-like (international)
Evergrande / Country Garden / Zhongzhi: cash-collection vs completion mismatch; presale-funded land acquisition; solvency contingent on continuous price appreciation.

### F. Regulatory-edict (sovereign/political)
Didi / TAL: instant policy reset wipes asset value regardless of accounting integrity. Different structural hazard from Wirecard/Evergrande — purely sovereign/political.

### G. Single-product → multi-franchise pivot (healthcare success)
Regeneron Eylea→Dupixent / LLY Zyprexa-cliff→GLP-1 / ABBV Humira-cliff→Skyrizi+Rinvoq. Pattern: single-product dominance + reinvested R&D into adjacent franchises.

### H. Captured-board looting vs founder-control RPT extraction
Two distinct governance failure axes:
- Founder-control RPT (WeWork, Adelphia): super-voting → company as personal balance sheet
- Captured-board (Tyco, Rite Aid): no formal dual-class but functional control via CEO-Chair + related directors + weak audit committee

### I. Long auditor tenure + dismissed short-seller red flags
Wirecard (EY 10yr), Toshiba (EY 60yr), Olympus (KPMG→EY handoff), Lernout & Hauspie (KPMG): canary pattern. Test feature: auditor tenure × short-report-dismissed.

### J. M&A-driven blowups
McDermott (CB&I 1.3x→17.6x leverage), HP/Autonomy ($8.8B writedown), Caterpillar (CSARL Swiss tax-shift), Diamond Foods (Pringles deal collapse). Distinct from organic-business failures.

---

## 6. Recommended final test-set composition

Building on the Q6-locked architecture (Section 6 of `Q6-Section5-synthesis.md`):

```yaml
test_sets:
  canaries:
    size: 70 deduplicated cases
    role: "Pipeline-validation; system MUST flag every entry"
    metric: "Coverage = 100% required"
    structure: stratified across the 9 archetypes (A-I above) + sector

  known_good:
    size: 55 cases
    role: "FP-rate calibration"
    metric: "FP rate < 15% on this set = HEADLINE calibration metric"
    structure: stratified across sector × era × surface-similarity-to-canary

  stratified_similarity:
    size: 50 cases
    role: "Precision@3 / NDCG@3 measurement"
    metric: "NDCG@3 ≥ 0.7; Precision@3 ≥ 70%"
    structure: per-archetype (15 archetype clusters with 3-5 cases each)

  total: ~175 cases
```

This is ~7× the original 25-case proposal. The expansion is justified by:
- 9 newly-surfaced structural archetypes that need cases per archetype to validate
- Cross-sector coverage (some archetypes manifest only in specific sectors)
- Era coverage (1990s-2026 — different failure modes per era)
- Canary-vs-known-good asymmetry (need KNOWN-GOOD cases that look LIKE specific canaries to validate FP rate per pattern)

---

## 7. Implementation handoff

For the engineer building the test-set infrastructure:

1. **Create `tests/p3_calibration/` directory with subdirectories:**
   - `canaries/` (70 YAML files, one per case)
   - `known_good/` (55 YAML files)
   - `stratified_similarity/` (50 YAML files with expected-top-3 annotations)

2. **Per-case YAML schema:**
```yaml
case_id: enron
metadata:
  name: "Enron Corporation"
  year_of_failure: 2001
  sector: "energy_utilities"
  era: "early_2000s"
  market_cap_at_peak: 65_000_000_000  # $65B
  archetype_primary: "fraud_with_novel_accounting"
  archetype_secondary: ["captured_board", "audit_failure"]
features_at_peak:
  fraud_signature_count: 5
  charismatic_CEO: true
  novel_accounting: true  # SPEs
  ...
expected_top_3_similarity:  # only for stratified_similarity cases
  - cf_id: theranos
    rationale: "Fraud archetype + secrecy + dismissed bear research"
  - cf_id: tyco
    rationale: "Captured board + accounting fraud"
  - cf_id: worldcom
    rationale: "Revenue/expense manipulation to hit Street"
```

3. **Pre-launch validation (per Q6 lock):**
   - Run mechanical similarity on stratified_similarity set
   - Validate canary coverage = 100%, known-good FP rate < 15%, NDCG@3 ≥ 0.7
   - Operator final approval before v0.1 launch

4. **Annual rotation (per Q6 drift-monitoring lock):**
   - Replace 5 of 50 stratified_similarity cases per year
   - Add new canaries event-driven (per Q4 lock for catalog)

---

## 8. Library deliverables produced

12 lane files in `.claude/references/empirical/data-sources/Q6-Section5-test-cases-*.md` (committed alongside this synthesis):
- Tech-platform failures + successes (2 files)
- Consumer/retail failures + successes (2 files)
- Financials failures + successes (2 files)
- Energy/commodities (1 file)
- Healthcare/biotech (1 file)
- International/EM (1 file)
- Recent IPOs/SPACs (1 file)
- Capital structure / governance (1 file)
- Audit / accounting / SEC (1 file)

Total ~120 named cases researched; this synthesis distills to ~175 test-set cases (some cases support multiple archetypes — they appear in multiple test-set entries).

---

**Q6 expanded test set proposal — ready for operator lock.**
