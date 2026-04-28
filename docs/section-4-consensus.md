# Section 4 Consensus — L2 / P2 (Probabilistic Scenario Writing)

**Date:** 2026-04-29
**Session:** Q&A consensus review with operator (saehoon0501) — Section 4 of the consensus-documentation-protocol series
**Status:** **FULLY LOCKED** — Q1 / Q2 / Q3 / Q4 / Q5 / Q6 / Q7 all closed
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

## 5. Q4 LOCKED — P2's connection to S0 = pure read-only consumer

**Locked: (a) read-only.** P2 reads S0's regime classifications + probabilities at invocation; writes scenario objects to its own `scenarios` Postgres table; **never modifies S0 or produces regime-classification information that competes with S0.**

### Why read-only over feedback-loop or audit-log alternatives

- **Separation of concerns:** S0 is the authoritative regime classifier (6 dimensions, BOCPD, all of Section 3 locked). P2 is the scenario writer that USES S0 as input.
- **If P2 systematically disagreed with S0**, that's evidence S0 needs recalibration — the right fix is to improve S0's inputs/methods through `/parameters-review`, NOT have P2 second-guess.
- **Section 1 finding extends here:** "PMSupervisor must NOT force consensus" — same logic applies between sidecars and phases. Automatic feedback loops create sycophantic convergence.
- The audit-log-of-disagreement variant I initially proposed conflated regime-classification with scenario-writing; operator pushback corrected this.

### Implementation

P2 reads S0 at every invocation (pull pattern, per Section 2 Q1 locked). P2 writes scenarios to its own table. No write-back to S0 ever. No "disagreement audit log" — that conflated two different jobs.

---

## 6. Q5 LOCKED — Revision cadence = hybrid daily kill-checks + event-driven full re-write

**Locked: (f) hybrid.**

### Daily (deterministic, fast, no LLM call)
- Kill-criteria check on all active scenarios against latest data
- Probability haircuts via Q3 firing logic:
  - Hard criterion fires → scenario probability → 0; re-normalize across remaining branches
  - Soft criteria fire → cumulative haircut: probability × (1 − 0.2·N)
  - Post-haircut < 0.1 → flag invalidated to operator
- No LLM regeneration of scenarios; just deterministic threshold checks

### Event-driven (LLM regenerates scenarios)
Full P2 re-run only on:
- S0 regime-shift event (M-2 or M-3 per Section 3 Q3)
- Kill-criterion fires on any active scenario for the theme
- Operator manually invokes `/research-company` reunderwrite

### Why hybrid

- Daily kill-checks capture incremental updates (Mellers IARPA: incremental updates beat big jumps; 0.12 Brier improvement per SD smaller updates)
- Full P2 re-write is LLM-cost-bearing; reserve for material events
- Aligns with Section 2's locked materiality-tiered framework

---

## 7. Q6 LOCKED — Probability granularity = hybrid (schema + prompt + lint)

**Locked: (c) hybrid enforcement.**

### Schema constraint (write-time)
- Probability must be in [0.05, 0.95] (no 0.0 or 1.0 — overconfidence rejection)
- Rounded to nearest 0.05 step (0.05, 0.10, 0.15, ..., 0.95)
- Sum-to-1.0 enforced across siblings

### Prompt instruction (LLM-write-time)
- P2's prompt explicitly cites Tetlock superforecaster finding: "use granular probabilities like 0.55 not 0.5; avoid round numbers unless justified"
- Reference 60/40-not-75/25 example

### Post-write linter (validation-time)
Flags suspicious patterns to operator before write commits:
- All branches at exactly 0.50 (round-number defaulting)
- Branches forming arithmetic series (0.25/0.50/0.25 with 3 branches; 0.20/0.30/0.30/0.20 with 4 branches)
- Branches at exactly 0.25/0.50/0.25 (sell-side default)

Operator sees lint warning at write time; can override with explicit reasoning logged.

### Why hybrid

- Pure prompt instruction (a): LLMs default to round numbers when uncertain — exactly the failure mode Tetlock documents
- Pure schema constraint (b): rejects edge cases without educating the writer
- Hybrid: belt-and-suspenders — schema enforces minimum discipline; prompt trains the LLM; linter catches Tetlock's documented failure modes

---

## 8. Q7 LOCKED — P2 → Macro-Regime style agent contract

**Locked: (b) full scenario set with probabilities.** + **theme tags assigned at P3 name-discovery time.**

### Theme→name mapping
- P3 name-discovery tags relevant `theme_ids` on each candidate (multi-theme allowed)
- Macro-Regime style agent at P4 receives scenarios for all tagged themes
- Operator can override theme tags during P4 if AI's tagging is wrong
- Theme-relevance decision lives at the right phase (name discovery has context); not re-done downstream

### Macro-Regime agent input contract
```
{
  candidate_ticker
  mode: "B" | "B'" | "C" (from Section 1 classification rule)
  theme_ids: [list, multi-theme allowed]
  scenarios: [for each theme_id, the 2-4 active scenarios with
              probabilities + kill_criteria_structured + regime_fit]
  S0_classification: settled input (don't re-derive — Macro-Regime agent
                     consumes as authoritative, same way P2 does)
  L1_reference: lane content (Macro-Regime style agent's home lane)
}
```

### Macro-Regime agent output (Phase A → Phase B per Section 1 5-style debate)
```
{
  regime_fit_score: float in [0,1]
  load_bearing_claims: [...]      # for Phase B locking
  non_negotiables: [...]          # for Phase B locking
  scenario_weighted_view: prose explanation of how the scenario
                          distribution shapes the agent's assessment
}
```

### Why full scenario set over alternatives

- (a) Highest-probability-only loses the distribution — defeats Q2/Q6 lock
- (c) Including S0 raw + L1 + scenarios makes Macro-Regime agent re-do S0's job (separation-of-concerns violation; same principle as Q4)
- (b) gives exactly what's needed: scenario distribution + kill-criteria status + probabilities

---

## 9. Section 4 — fully closed

All 7 questions locked:
- **Q1** Scenario data model = structured branches (Postgres JSON with explicit schema)
- **Q2** Scenarios per theme = variable 2-4 (Shell empirical sweet spot)
- **Q3** Kill-criteria spec = hybrid pre-mortem narrative + structured conditions; pre-loaded template library at v0.1
- **Q4** P2 ↔ S0 connection = pure read-only (P2 doesn't second-guess S0)
- **Q5** Revision cadence = hybrid daily kill-checks + event-driven full re-write
- **Q6** Probability granularity = hybrid schema + prompt + lint
- **Q7** P2 → Macro-Regime agent contract = full scenario set with probabilities + theme tags from P3

Sections 1, 2, 3, 4 fully locked. Sections 5-8 pending.

Ready for Section 5 (L3 — Successful-company pattern library review).
