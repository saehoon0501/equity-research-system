# Industry Addendum: Hardware / Semiconductors

Loaded by `company-deep-dive` subagent when company classification = semiconductors, hardware, networking equipment, hardware infrastructure, or related capital-intensive technology.

Hardware is cyclical, capital-intensive, and has different unit economics from software. Specific in 2024-2026 by AI capex cycle dynamics.

## Required hardware-specific metrics

### Standard ratios with hardware context

| Ratio | Definition | Notes |
|---|---|---|
| **Gross Margin** | (revenue − COGS) / revenue | Semis: 50-70% leaders; commodity 25-45% |
| **Operating Margin** | operating income / revenue | Top semis: 30-50%; commodity hardware: 10-20% |
| **Inventory Turns** | COGS / avg inventory | Critical in cyclical hardware; 4-8x healthy |
| **Days Inventory** | inventory / (COGS / 365) | <90 days lean; >120 days bloated; signals demand softness |
| **Capex/Revenue** | capex / revenue | Fab leaders: 20-30%; capex-heavy cycles signal cycle position |
| **R&D/Revenue** | R&D / revenue | Semis: 15-25% sustainable competitive advantage |
| **Customer concentration** | top 10 customers as % | Often very high in semis (e.g., Apple = 20%+ of TSMC) |
| **Book-to-Bill** | new bookings / revenue | >1.0 = order growth ahead; <1.0 = book of orders shrinking |

### Capex cycle position

Hardware companies are cyclical, and where in the capex cycle matters enormously:

- **Capex peak**: high capex/revenue, often higher inventory; valuation may reflect future capacity
- **Capex trough**: low capex, sometimes restructuring; valuation may bottom
- **Recovery / expansion**: capex rising to meet demand, margins expanding

Specifically for AI infrastructure (2024-2026):
- AI buildout has driven extraordinary capex/revenue ratios
- TSMC, ASML, NVIDIA capex/demand dynamics are central
- Operator should evaluate where in the cycle — top-heavy spending often precedes correction

## Semiconductor-specific framework

### Memory (DRAM, NAND) vs Logic vs Analog

- **Memory** is hyper-cyclical with brutal pricing cycles; gross margins swing 0% to 50%+
- **Logic** (CPUs, GPUs, custom silicon) — generally stronger margin stability, especially with design-IP moats
- **Analog** (TI, ADI archetype) — most stable margins; long product lifecycles

### Foundry vs Fabless vs IDM

- **Fabless** (NVIDIA, AMD, Apple, Qualcomm, MediaTek): capital-light, high R&D, design moat
- **Foundry** (TSMC, Samsung, Intel Foundry): capex-heavy, capacity utilization is key driver
- **IDM (Integrated Device Manufacturer)** (Intel historically, Samsung): hybrid; both design and manufacturing capex

### Process node leadership

For leading-edge logic (TSMC, Samsung, Intel), process node generation drives competitive position:
- TSMC dominance at advanced nodes (3nm, 2nm)
- Capex required to maintain leadership is enormous
- Yield rates and customer relationships matter

## Customer concentration risk (specific to semis)

Top customers often >50% of revenue for fabless or specialized semis:
- Apple at TSMC, Qualcomm, MediaTek, Broadcom
- Hyperscalers at NVIDIA (Microsoft, Meta, Google, Amazon)
- Auto OEMs at NXP, Infineon, ON Semi

Loss of a top customer = catastrophic; analyze concentration carefully.

## Required risk factors to extract from 10-K

1. **Customer concentration** — top customer revenue %
2. **Capacity utilization risk** — fabs at low utilization burn cash
3. **Inventory risk** — write-downs in cycle downturns
4. **Geopolitical** — export controls (US/China semi tensions), Taiwan Strait risk
5. **Process technology** — node leadership, yield rates
6. **Competitive intensity** — new entrants (Chinese semi push), incumbent shifts
7. **Macro cyclicality** — consumer electronics, enterprise IT, auto demand
8. **Lead times** — long lead time for fab capacity (multi-year)

## DCF modeling approach

DCF works for hardware but with cycle awareness:
- Use mid-cycle earnings rather than peak or trough
- Model capex as % of revenue with cycle-position assumption
- Sensitivity on cycle-adjusted operating margin (50% range top to bottom is common)
- Replacement-cost approach (Tobin's Q) as sanity check for capital-intensive companies

For fabless designers, DCF is more straightforward (less capex; design moat captures via R&D efficiency).

## Industry-specific catalysts

- Quarterly earnings (book-to-bill, inventory, capex guidance)
- Foundry technology roadmap announcements (TSMC quarterly reports)
- Major customer product launches (iPhone, GPU launches)
- Geopolitical: export control actions, Taiwan Strait events
- Semi conference cycle: ISSCC, Hot Chips, GTC for NVIDIA
- Memory pricing data (DRAMeXchange, TrendForce)

## AI infrastructure carve-out (specifically)

Per v2-final golden standard, the operator may include "one explicit AI-infrastructure carve-out" alongside quality compounders.

Candidates:
- **NVIDIA** — current AI compute leader; high concentration risk to current generation
- **TSMC** — manufactures advanced AI chips; broad ecosystem position
- **ASML** — EUV lithography monopoly for advanced nodes
- **Broadcom, Marvell** — networking/custom silicon for hyperscalers
- **AMD** — emerging AI accelerator competitor
- **Memory leaders** — Micron, SK Hynix, Samsung memory (HBM exposure)

For AI carve-out, position discipline matters:
- Cycle position is unclear (potentially top-heavy after 2023-2024 buildout)
- Single-name concentration (8% cap per v2-final §2.4) is critical
- Multiple AI exposures correlate; correlation cluster risk per PositionSizingModel

## Quality compounders in hardware?

Generally hardware is more cyclical than the quality-compounder archetype. Possible exceptions:
- Analog semis (TI archetype) — stable margins, long product lifecycles, mission-critical
- Networking equipment with software/services attach (Cisco, Arista)
- Test & measurement equipment (Keysight, Teradyne)
- Specialty chemicals/materials for semis (Linde, Air Products gases; Entegris materials)

Pure cyclical commodity hardware (consumer PC, generic memory) is more cycle-trade than compounder.

## Source quality tier guidance

- Tier 1: 10-K, 10-Q (with detailed customer concentration disclosures), 8-K major contracts
- Tier 2: Earnings calls (especially TSMC quarterly which is industry-defining), IR presentations, conference keynotes (NVIDIA GTC, AMD events)
- Tier 3: TrendForce, IDC, Gartner research; established semi-focused publications (SemiWiki, AnandTech, Tom's Hardware Pro); equity research (Bernstein semi team, Morgan Stanley semi team)
- Tier 4: General consumer tech press, social media speculation
