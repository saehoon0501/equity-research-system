---
description: Guided checkpoint artifact creation for v0.1 phase gates per implementation-sequencing.md §6. Walks through completion criteria with documented evidence; produces checkpoint_N.md committed to checkpoints/.
argument-hint: <1|2|3>
---

# /checkpoint

Per implementation-sequencing.md §6, each checkpoint produces a single document committed to `checkpoints/`. This command guides the operator through writing it.

## Argument

`<1|2|3>` — required. Which checkpoint to produce.

| Checkpoint | FTE date | Evenings date | Topic |
|---|---|---|---|
| 1 | end of week 4 (2026-05-23) | end of week 7 | Data Layer + Evidence Index Live |
| 2 | end of week 8 (2026-06-20) | end of week 12 (interim) | Agent Harness + CompanyDeepDive Producing Memos |
| 3 | end of week 13 (2026-07-25) | end of week 20 | Phase Gates Evaluated (full v0.1 → v0.5 advancement decision) |

## Procedure

### 1. Determine checkpoint scope

Read implementation-sequencing.md §6.1, §6.2, or §6.3 for the criteria specific to the checkpoint.

### 2. Walk operator through each criterion

For each completion criterion:
- Read the criterion text
- Ask: ✓ or ✗?
- If ✓: capture evidence (test output, file path, query result, screenshot reference, etc.)
- If ✗: capture what's missing and the recovery plan

### 3. Pace judgment

```
On pace / Behind / Kill threshold becoming relevant: [pick one]

Evidence for judgment: [specific, not vibes — e.g., "all 12 criteria met, 3 days
ahead of target" or "8 of 12 criteria met, Sharadar approval delayed from 5 days
to 11 days, week 5 buffer fully consumed"]
```

### 4. Buffer status

Capture consumption since last checkpoint.

### 5. For Checkpoint 1: Data Layer + Evidence Index Live

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

### 6. For Checkpoint 2: Agent Harness + CompanyDeepDive Producing Memos

For FTE track (full criteria):

```
□ Full agent harness operational (Path A: Claude Code subagents wired)
□ One memo end-to-end on a known-historical name
□ Evidence Index references populated correctly with mixed source quality tiers
□ Process rubric grading hook running (Evaluator subagent invokable)
□ Mechanical contamination check integrated into output release
□ Cost per memo measured and projected against monthly budget
```

For evenings interim:

```
□ Agent harness functional (does not need full polish)
□ One memo end-to-end completed (same bar as FTE)
□ Cost per memo measured (same bar)
□ VIABILITY JUDGMENT: At current pace, can Checkpoint 3 be met before week 24?
  Weeks elapsed: <N>
  Buffer consumed so far: <list>
  Remaining scope: BacktestingFramework + sample memos + gates
  Realistic week count to Checkpoint 3 from here: <estimate with reasoning>
  Margin to kill threshold: <computed>
  Decision: viable | marginal (renegotiate scope) | not viable (convene early)
```

### 7. For Checkpoint 3: Phase Gates Evaluated (the v0.1 → v0.5 decision)

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

### 8. Final judgment (Checkpoint 3 specific)

```
v0.1 → v0.5 advancement: APPROVED | BLOCKED

Reason: [reference specific gate failures or completion-checklist gaps]

If APPROVED: BUILD_LOG entry committing to v0.5 entry date.
If BLOCKED: BUILD_LOG entry documenting which gates failed, recovery plan, revised
target date for re-evaluation. If recovery would push past kill threshold, kill
criterion §2.6.4 has fired and v0.1 is concluded without advancement.
```

### 9. Notes for future-tired-you

Anything worth capturing — design decisions, surprises, references.

### 10. Write the artifact

Create `checkpoints/checkpoint_<N>.md` with all the above content. The artifact is the audit trail; future-tired-you reads this when questioning any v0.1 design decision.

### 11. Commit

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

- End of week 4 (FTE) / week 7 (evenings): `/checkpoint 1`
- End of week 8 (FTE) / week 12 (evenings): `/checkpoint 2`
- End of week 13 (FTE) / week 20 (evenings): `/checkpoint 3`

Off-schedule running is acceptable if a phase is extending. Document the extension in BUILD_LOG.md before running the checkpoint.

## Cost

Negligible — operator-driven, primarily conversation.
