# Section 4 Consensus — L2 / P2 (Probabilistic Scenario Writing)

**Date:** 2026-04-29 (in progress)
**Session:** Q&A consensus review with operator (saehoon0501) — Section 4 of the consensus-documentation-protocol series
**Status:** Partially locked — Q1 / Q2 / Q3 closed; further sub-questions pending
**Purpose:** Capture how P2 (probabilistic scenario writing phase) actually works: data model, scenario count per theme, kill-criteria specification, revision cadence, connections to S0 and L8.

**Predecessors:**
- [Section 1](section-1-consensus.md), [Section 2](section-2-consensus.md), [Section 3](section-3-consensus.md)

---

## 1. Section 4 scope

P2 is the funnel phase that turns a candidate theme (output of P1) into 2-4 falsifiable 3/5/10-year scenarios consumed by:
- P3 name discovery (era-fit check)
- P4 5-style debate (Macro-Regime style agent)
- P8 daily refresh (kill-criteria checks)

L2 lane has 58 sources, 33 patterns, 8 disagreements, 6 D-tables. The lane established WHAT empirically works for scenario writing (Tetlock granular probabilities, Shell 2-3 scenarios, Klein pre-mortem, Damodaran 3P test, Hussman long-term-return decomposition). Section 4 specifies HOW P2 operationalizes the lane's findings.

---

## 2. Q1 LOCKED — Scenario data model

**Locked: (b) structured branches.** Each scenario is a JSON object with explicit fields, persisted to Postgres.

### Schema (v0.1)

```
{
  scenario_id: uuid
  theme_id: uuid (ref P1 trend-capture output)
  name: text (e.g., "Rates stay elevated, AI capex slows")
  horizon_years: 3 | 5 | 10
  probability: float in [0,1] (granular per Tetlock; sum-to-1 across siblings)
  description: text
  kill_criteria_narrative: text (pre-mortem; locked in Q3)
  kill_criteria_structured: [...] (locked in Q3 — see §4 below)
  value_drivers: [
    { dimension: e.g., "growth_rate", direction: e.g., "decelerating to 8-12%", magnitude: ... }
  ]
  regime_fit: { S0_dimensions: { credit, cycle, vol, mp_liquidity, dollar, stock_bond_corr } }
  key_dates_to_watch: [...]
  created_at, last_updated_at
}
```

### Why structured branches over alternatives

- **Free-text** has no schema BUT every consumer (P3/P4/P8) does its own LLM parsing → drift, inconsistency, bugs go silent
- **Scenario tree** is over-engineered for v0.1; tree structures are harder to query, update, and refactor
- **Structured-but-extensible JSON** is the standard pattern for systems that need to evolve (REST contracts, Protobuf, OpenAPI, Postgres + migrations); add nullable fields as needs surface; old scenarios remain valid

---

## 3. Q2 LOCKED — Scenarios per theme

**Locked: (c) variable 2-4 per theme.** Schema constraint `branch_count ∈ [2,4]`. Probabilities sum to 1.0 across siblings.

### Why variable 2-4 over fixed counts

- **Empirical anchor:** Shell's 50+ years of scenario practice converged on 2-3 as the sweet spot. 4 is acceptable for natural 2×2 frameworks (Bridgewater growth × inflation).
- **(a) Always 2** forces binary thinking and misses the realistic "muddle through" middle case.
- **(b) Always 3** matches sell-side convention but creates decorative "base case" when theme is genuinely 2-branch.
- **5+** produces decision paralysis and noisy individual-branch probabilities (Shell empirically rejected).

The Macro-Regime style agent in P4 enforces probability sum constraint at write time.

---

## 4. Q3 LOCKED — Kill-criteria specification

**Locked: (c) hybrid — pre-mortem narrative + structured conditions.**

### Schema additions

```
{
  ...other scenario fields...
  kill_criteria_narrative: "Imagine 18 months from now this scenario invalidated. What happened? Most likely: ..."
  kill_criteria_structured: [
    {
      criterion_id: uuid,
      type: "hard" | "soft",
      template_id: ref to catalog (optional, for catalog-derived criteria),
      variable: e.g., "fed_funds_rate" | "deposit_outflow_pct_48h",
      comparator: "<" | ">" | "==" | "between" | "sustained_above_for_days",
      threshold: float,
      deadline: ISO date OR "EOQ_YYYY_QN" OR null (sustained criteria),
      description: text gloss for operator,
      precedent_episodes: [historical episodes where it fired],
      degradation_status: "durable" | "recalibrate" | "discredit_post_2020" | "new_post_2020"
    }
  ]
}
```

### Firing logic

- Hard criterion fires → scenario probability → 0; re-normalize across remaining branches
- N soft criteria fire → cumulative haircut: probability × (1 − 0.2·N)
- Post-haircut probability < 0.1 → flag invalidated to operator
- `degradation_status = "discredit_post_2020"` → criterion is read-only / informational; doesn't fire scenario invalidation in v0.1

### Pre-loaded template library at v0.1 launch

Curated catalog drawn from cross-period synthesis (`Q3-synthesis.md`):

| Tier | Count | Description |
|---|---|---|
| Durable (use as priors) | ~25 | VIX>40, Lowry 90%-down, A-D divergence, capex 5-pillar, two-axis triggers |
| New post-2020 | ~15 | SVB-deposit-outflow, NVDA-concentration, DRAM-weeks, GEX-flip, Ackman-dispersion |
| Discredited (read-only annotated) | ~25 | Yield curve as hard trigger, Sahm Rule, CAMELS, TED, naive AAII, OPEC-floor |

Operators / agents writing scenarios at P2 choose by `template_id` (consistent, well-documented) or define custom criteria with explicit `precedent_episodes` documentation.

Engineering analogy: same pattern as design-system component libraries — pre-built validated components + escape hatch for custom.

### 6 cross-period structural insights documented

(For full detail see `.claude/references/empirical/data-sources/Q3-synthesis.md`)

1. Mechanical/breadth/state-based signals most durable (NOT survey-based)
2. Post-2020 dynamics differ structurally (regime-conditional, not universal)
3. "Bottoms are events, tops are processes" → long-side kills tighter than short-side
4. Public commitment is dominant kill-criteria FAILURE mode (Ackman/Valeant/Herbalife)
5. Hard data lags price action 6-12 months → kill criteria must triangulate price + private-data + flow-velocity
6. Two-axis (price + time) > single-axis at every level

### Library deliverables (Q3)

8 lane files + synthesis at `.claude/references/empirical/data-sources/Q3-*.md`:
- 4 post-2020 (macro / sector / behavioral / practitioner)
- 4 pre-2020 (same dimensions)
- 1 cross-period synthesis

Total: 2,459 lines, ~229 sources, ~325 specific criteria/templates.

---

## 5. Pending sub-questions for Section 4 closure

Before Section 4 closes:

- **Q4** — How does P2 connect to S0 (read-only? feedback loop? regime-shift triggers?)
- **Q5** — When does P2 revise scenarios (cadence; triggers; how often probabilities update)
- **Q6** — How is granular probability assignment enforced (Tetlock 60/40 not 75/25)?
- **Q7** — How does P2's output flow to the Macro-Regime style agent in P4?

These can likely be bundled — they're tightly coupled (revision cadence + S0 connection + L8 contract are three views of the same plumbing).

---

## 6. What's locked so far

- Scenarios are structured JSON objects (not free text, not trees)
- 2-4 scenarios per theme
- Kill criteria = pre-mortem narrative + structured conditions with template-library priors
- Hard/soft firing logic
- Mechanical/breadth/state-based criteria preferred over survey-based
- Discredited-post-2020 templates retained read-only with deprecation notes

Sections 1, 2, 3 fully locked. Section 4 partially locked. Sections 5-8 pending.

---

**Section 4 partial consensus committed. Q4-Q7 to follow.**
