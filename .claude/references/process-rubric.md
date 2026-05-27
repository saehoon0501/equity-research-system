# Process Rubric (Universal)

Per v2-final §3.1, every LLM agent output is graded against this rubric. The Evaluator subagent (`.claude/agents/eval/evaluator.md`) applies this. Hard gates listed below block output release.

## Universal criteria

Each criterion scored 0–10 with cited reasoning.

| Criterion | Description | Score 0 | Score 10 |
|---|---|---|---|
| **Falsifiability** | Are claims testable? Can reality eventually verify or refute them? | All claims unfalsifiable platitudes ("strong moat," "good management") | All claims have specific testable conditions with KPIs and dates |
| **Source grounding** | Every numerical claim has Evidence Index reference per claim definition rule | Zero references | Every numerical/dated/named-fact claim references a real Evidence Index row, weighted by source quality tier |
| **Evidence-timestamping** | Source dates surfaced AND validated mechanically (the contamination defense) | Claims appear memorized; no source dates | All dated claims resolve to Evidence Index rows predating claim resolution; validation mechanical |
| **Calibrated uncertainty** | Confidence ranges are honest, not artificially narrow | P10/P90 spread suspiciously narrow; no ranges | Ranges align with realized volatility floor (×√horizon); explicit P10/P50/P90 |
| **Reasoning transparency** | Logic is followable step-by-step | Conclusions without reasoning | Each conclusion traces to specific evidence + named inferences |
| **Counter-evidence acknowledgment** | Contrary points addressed, not cherry-picked | Cherry-picked support only | All meaningful counter-evidence explicitly engaged with rebuttal or accepted concession |

## Source quality weighting

The Source grounding score is weighted by Evidence Index source_quality_tier of cited evidence:

- ≥80% of claims at Tier 1 + Tier 2: full credit
- 50–79% Tier 1 + 2: partial credit, capped at 7/10
- 25–49% Tier 1 + 2: low credit, capped at 4/10
- <25% Tier 1 + 2 (i.e., majority retail/blog sources): fail Source grounding criterion regardless of citation density

A memo built on Seeking Alpha articles isn't well-sourced even if every claim has a citation.

## Hard gates (block output release)

These are non-negotiable. Output that violates any hard gate is returned to the original agent for revision, not released downstream.

### HG-1: Mechanical contamination check passes

Every dated claim's `evidence_id` reference resolves to a real Evidence Index row whose `source_date` predates the claim's resolution date. Procedure: `.claude/references/contamination-check.md`. **This is the load-bearing defense under Path A.**

### HG-2: CompanyDeepDive memo has falsifiable predictions

Memo must include `reviewable_predictions` with at least 3 entries, each with:
- Specific KPI (numerical, not "strong performance")
- Predicted value or directional claim
- Resolution date (specific, not "next year")

Memo with no falsifiable predictions = no way to grade outcome calibration = returned for revision.

### HG-3: BearCase has unrebutted concerns OR explicit acknowledgment of full address

BearCase output must include either:
- At least one entry in `unrebutted_concerns`, OR
- Explicit statement "All concerns identified by Bear analysis are addressed by the deep-dive memo's mitigations" with named addresses

Empty `unrebutted_concerns` field with no acknowledgment = sycophancy collapse signal = returned for revision.

### HG-4: Every numerical/dated/named-fact claim has Evidence Index reference

Per `evidence-index-schema.md` definition rule. Output that contains uncited specific facts = returned for revision. The mechanical check catches missing `evidence_id` references.

### HG-5: ExitSignalModel output includes explicit tax cost analysis

Per v2-final §2.3, exit recommendations must surface `tax_cost_estimate` and the reasoning trace showing why tax-aware logic accepted/rejected the original signal. Missing tax analysis on exit recommendations = returned.

### HG-6: DailyMonitor digest includes justification for every materiality score (including zeros)

Per v2-final §1.5. A digest with score=0 entries lacking justification = laziness = returned. Score-0 justifications are part of the calibration record over time.

## Soft criteria (scored, not gates)

Beyond hard gates, the Evaluator scores each criterion 0–10 with reasoning. Aggregate scores feed:
- Per-agent calibration history (used by PositionSizingModel for Kelly fraction adjustment)
- Quarterly process audits
- Annual rubric review per phasing-plan.md §3.5

Outputs that pass hard gates but score low overall are released downstream with the scores recorded; the agent's calibration record reflects the lower quality.

## Agent-specific addenda

Each agent has additional rubric criteria beyond the universal set. See:
- CompanyDeepDive: success criteria in `.claude/agents/company-deep-dive.md`
- BearCase: success criteria in `.claude/agents/bear-case.md`
- Evaluator (self-evaluation): success criteria in `.claude/agents/eval/evaluator.md`

The Evaluator applies both universal + agent-specific.

## Why mechanical checks dominate semantic judgment

Per v2-final §1.6 and contamination-check.md:

> Asking the Evaluator to *judge* whether a memo "looks memorized" is asking an LLM to detect its own failure mode — which it can't reliably do. The check is mechanical: every dated claim resolves to a real Evidence Index row that predates the claim's resolution date. This is invariant to which model runs the Evaluator.

The Evaluator's semantic judgment is the primary line of defense for soft criteria (reasoning quality, counter-evidence engagement, calibration honesty). The mechanical check is the primary line of defense for hard gates (contamination, sourcing, falsifiability). They complement each other; neither alone is sufficient.

## Calibration of the Evaluator itself

Per phasing-plan.md §3.5 (annual rubric review):

- Cases where high process scores produced poor outcomes → rubric criterion that doesn't predict outcomes; candidate for refinement
- Cases where low process scores produced good outcomes → rubric criterion that overweights spurious signals; also candidate for refinement
- Per-criterion correlation with realized outcomes is the validation surface

The Evaluator's own calibration is tracked over time. If the Evaluator consistently passes outputs that turn out wrong (or rejects outputs that would have been right), that's a signal the rubric or its application has drifted.

This review happens annually (in v1.0 phase only — v0.1 doesn't have enough resolved outcomes for this signal). v0.1's job is to validate that the rubric is *applied* consistently; v1.0's job is to validate that what it measures *predicts*.
