---
description: Guided checkpoint artifact creation for v0.1 phase gates per implementation-sequencing.md §6. Walks through completion criteria with documented evidence; produces checkpoint_N.md committed to checkpoints/.
argument-hint: <1|2|3>
---

# /checkpoint

Per implementation-sequencing.md §6, each checkpoint produces a single document committed to `checkpoints/`. This command guides the operator through writing it.

## Argument

`<1|2|3>` — required. Which checkpoint to produce.

| Checkpoint | Step boundary (per BUILD_LOG.md) | Topic |
|---|---|---|
| 1 | After Foundation + Data Layer steps | Data Layer + Evidence Index Live |
| 2 | After Agent Harness steps | Agent Harness + CompanyDeepDive Producing Memos |
| 3 | After Backtesting + Sample Memo Generation steps | Phase Gates Evaluated (full v0.1 → v0.5 advancement decision) |

(Per BUILD_LOG.md decision 5, checkpoints fire at step boundaries, not on dates. Run a checkpoint when its gating step list is demonstrably complete.)

## Procedure

### 1. Determine checkpoint scope

Read implementation-sequencing.md §6.1, §6.2, or §6.3 for the criteria specific to the checkpoint.

### 2. Walk operator through each criterion

For each completion criterion:
- Read the criterion text
- Ask: ✓ or ✗?
- If ✓: capture evidence (test output, file path, query result, screenshot reference, etc.)
- If ✗: capture what's missing and the recovery plan

### 3. Step-completeness summary

(Per BUILD_LOG.md decision 5, no pace/buffer judgment — there's no calendar to be on or off.)

```
Step list status at this checkpoint:
- Steps complete: <list of [x] items in BUILD_LOG.md gating this checkpoint>
- Steps incomplete: <list of [ ] items still gating this checkpoint, if any>

Evidence: [specific — e.g., "all 12 criteria met; sample queries returning expected
results; mechanical contamination check rejecting one synthetic post-dating claim
and accepting one synthetic predating claim"]
```

### 4. For Checkpoint 1: Data Layer + Evidence Index Live

Criteria per implementation-sequencing.md §6.1:

```
□ TimescaleDB + Postgres provisioned and queryable
□ Sharadar account active with data integrity verified
□ Pluggable data layer (prices) tested with primary failure
□ edgartools fetching ≥3 historical filings
□ FRED integration returning known macro series
□ Evidence Index schema implemented with all v2-final fields
□ Append-only Predictions DB (deletion-attempt test fails)
□ Append-only Counterfactual Ledger (deletion-attempt fails)
□ Retention tiering tested with synthetic 8-quarter data
□ Mechanical contamination check rejects post-dating claims
□ Mechanical contamination check accepts predating claims
□ Provider verification artifacts captured
```

### 5. For Checkpoint 2: Agent Harness + CompanyDeepDive Producing Memos

```
□ Full agent harness operational (Path A: Claude Code subagents wired)
□ One memo end-to-end on a known-historical name
□ Evidence Index references populated correctly with mixed source quality tiers
□ Process rubric grading hook running (Evaluator subagent invokable)
□ Mechanical contamination check integrated into output release
□ Cost per memo measured and projected against monthly budget
```

(Per BUILD_LOG.md decision 5, no FTE/evenings track distinction and no "viability judgment vs. week-24 kill threshold" — those came with the dated cadence that's been removed. If progress to Checkpoint 3 stalls, the decision is to revise the BUILD_LOG step list, not to compute kill-threshold margin.)

### 6. For Checkpoint 3: Phase Gates Evaluated (the v0.1 → v0.5 decision)

Walk through phase gates from phasing-plan.md §2.5 mechanically:

```
### Gate 2.5.1 — Contamination defense validated
- Sample size: <N memos> (required ≥30)
- Pre-effective-cutoff Sharpe: <value>
- Post-effective-cutoff Sharpe: <value>
- Degradation ratio: <value> (required ≤20%)
- Pass / Fail / Kill criterion (≥40%) triggered: <pick one>

### Gate 2.5.2 — Mechanical contamination check coverage
- ≥99% of dated claims have valid Evidence Index references
- Manual audit of 50 random claims: false-pass count = <N> (required 0)
- Pass / Fail / Kill criterion (>2% false-pass) triggered: <pick one>

### Gate 2.5.3 — Backtest discipline
- DSR on post-cutoff sample: <value> (required >0.5)
- PBO: <value> (required <50%)
- Counterfactual baselines: SPY ✓/✗, equal-weight ✓/✗, sector-matched ✓/✗, 60/40 ✓/✗
- Pass / Fail / Kill criterion (counterfactuals beat system) triggered: <pick one>

### Gate 2.5.4 — Infrastructure soundness
- Append-only verified: ✓/✗
- Retention tiering tested with 8-quarter synthetic data: ✓/✗
- Pluggable data layer fallback chain tested: ✓/✗
- Pass / Fail: <pick one>

### Gate 2.5.5 — Cost model
- Per-memo inference cost: $X
- Projected v0.5 monthly cost: $Y (required ≤$400)
- Pass / Fail: <pick one>
```

Plus phase-completion checklist from phasing-plan.md §2.7.

### 7. Final judgment (Checkpoint 3 specific)

```
v0.1 → v0.5 advancement: APPROVED | BLOCKED

Reason: [reference specific gate failures or completion-checklist gaps]

If APPROVED: BUILD_LOG.md updated — phase flips to v0.5; operational cadences
(daily monitor / weekly macro / monthly harvest / quarterly re-underwrite)
become live.

If BLOCKED: BUILD_LOG.md updated — which gates failed, recovery plan, revised
step list. (Per BUILD_LOG decision 5, there is no kill threshold; the operator
decides whether to extend with a revised step list or sunset v0.1. Path A
reversal trigger from BUILD_LOG decision 1 — post-cutoff degradation >20% —
remains in force regardless.)
```

### 8. Notes

Anything worth capturing — design decisions, surprises, references.

### 9. Write the artifact

Create `checkpoints/checkpoint_<N>.md` with all the above content. The artifact is the audit trail; this is what gets re-read when any v0.1 design decision is later questioned.

### 10. Commit

`git add checkpoints/checkpoint_<N>.md`
`git commit -m "Checkpoint <N> evaluation"`

The artifact is committed to permanent record.

## Why this command exists

Per implementation-sequencing.md §10.5:

> 10.5 — Skipping checkpoint artifacts when criteria pass.
> Specific case: Checkpoint 1 goes smoothly, formal artifact feels redundant, audit trail is missing later.
> Prevented by: §6 requirement that artifacts are written regardless of pass/fail.

The artifact is the audit trail. The verbal "yeah it all worked" is not. This command makes the artifact mandatory and easy.

## When to use

Run a checkpoint when its gating step boundary in BUILD_LOG.md is demonstrably complete:

- `/checkpoint 1` — after Foundation + Data Layer steps are all `[x]`
- `/checkpoint 2` — after Agent Harness steps are all `[x]`
- `/checkpoint 3` — after Backtesting + Sample Memo Generation steps are all `[x]`

Per BUILD_LOG.md decision 5, there is no calendar trigger and no kill threshold. The artifact is still mandatory at each step boundary regardless of pass/fail (the audit trail is the load-bearing thing).

## Cost

Negligible — operator-driven, primarily conversation.
