---
description: Run the Evaluator process rubric against a specific output (memo, bear case, daily digest, etc.). Returns hard-gate pass/fail and soft scores.
argument-hint: <output-path-or-id>
---

# /evaluate

Manually invoke the Evaluator on an existing output. Useful for:
- Re-evaluating an output after rubric refinements
- Sample memo audit at Checkpoint 3 (per phasing-plan.md §2.5.2)
- Spot-checking memos that already passed during their original evaluation

## Argument

`<output-path-or-id>` — path to a memo file or Postgres ID of a stored memo/digest/critique.

## Procedure

### 1. Pre-flight checks

- `mcp__postgres` for Evidence Index lookup
- The output exists and is readable

### 2. Load output

If path: read the file.
If Postgres ID: query Postgres for the output content.

Determine output type from structure:
- CompanyDeepDive memo: has thesis_pillars, recommended_action, etc.
- PMSupervisor envelope: has decision, conviction, sleeve_cap_check, adversarial_stress_test (the latter is the post-2026-05-12 replacement for the retired BearCase output)
- DailyMonitor digest: has materiality_scores, escalations
- MacroCycle: has cycle_score, regime_classification
- Other: prompt operator for clarification

### 3. Invoke Evaluator subagent

Pass the output to the `evaluator` subagent via Task tool. The subagent runs:

1. Mechanical contamination check (HG-1) — Postgres queries against Evidence Index
2. Output-type-specific hard gates (HG-2 through HG-6)
3. If hard gates pass: soft scores (universal rubric + agent-specific)

### 4. Return verdict

```
EVALUATION RESULT for <output identifier>

HARD GATES:
  HG-1 Mechanical contamination check: PASS / FAIL
    [If FAIL: list of evidence_id failures and their specific issues]
  HG-2 Falsifiable predictions (CompanyDeepDive only): PASS / FAIL / N/A
  HG-3 Adversarial stress-test (PMSupervisor only; replaces former BearCase HG-3): PASS / FAIL / N/A
  HG-4 Every claim has Evidence Index reference: PASS / FAIL
  HG-5 Tax cost analysis (ExitSignal only): PASS / FAIL / N/A
  HG-6 Justifications (DailyMonitor only): PASS / FAIL / N/A

VERDICT: ACCEPTED | REJECTED

[If REJECTED:]
SPECIFIC FAILURE: <description>
RECOMMENDED REVISION: <what would pass>

[If ACCEPTED:]
SOFT SCORES (universal rubric):
  Falsifiability: X/10 — reasoning
  Source grounding: X/10 — reasoning (with source_quality_tier breakdown)
  Evidence-timestamping: X/10 — reasoning
  Calibrated uncertainty: X/10 — reasoning
  Reasoning transparency: X/10 — reasoning
  Counter-evidence acknowledgment: X/10 — reasoning

AGGREGATE SCORE: X/100
PASSES MINIMUM BAR: yes / no

FLAGS: [specific issues]
COMPARISON TO BASELINE: [stronger/weaker than agent's typical work]
```

### 5. Persistence

If invoked manually (this command), record the evaluation as a separate Evidence Index entry with `agent_id='evaluator-manual'`. This distinguishes manual re-evaluations from the synchronous gate evaluations that happen during agent output release.

## When to use

### Sample memo audit (Checkpoint 3)

Per phasing-plan.md §2.5.2, Checkpoint 3 includes manual audit of 50 randomly-sampled claims. The audit can use this command to re-evaluate sample memos.

```
For each of 50 randomly-sampled memos:
  /evaluate <memo>
  Note hard-gate result; flag any false-pass
```

### Rubric refinement testing

If the operator is considering a rubric change (annual review per phasing-plan.md §3.5), running the new rubric against historical outputs validates whether the change improves outcome prediction. This command can be invoked in that workflow with the proposed rubric loaded.

### Spot-check before consequential action

Before acting on a memo's recommendation (entering a position, e.g.), the operator can re-evaluate the memo to confirm it still passes — useful if some time has elapsed since the original eval.

## Cost

- Sonnet: ~$3-5 per evaluation (smaller than authoring)
- Opus (for hard-gate decisions): ~$8-15 per evaluation

## What this command does NOT do

- It does not modify the original output. The original memo's release status is unchanged. This is a re-evaluation.
- It does not auto-trigger any downstream action based on the verdict. The operator decides what to do with the result.
