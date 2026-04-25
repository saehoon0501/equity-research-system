---
description: Re-underwrite a held name (or all watchlist names) per v2-final §1.2 quarterly cadence. Triggered automatically by materiality-3 escalations from /daily-monitor; can also be invoked manually.
argument-hint: [ticker] (optional; if omitted, re-underwrites all held positions)
---

# /quarterly-reunderwrite

Per v2-final §1.2 cadence: full re-underwrite quarterly per held name. Also triggered ad-hoc on materiality-3 escalation per `.claude/commands/daily-monitor.md` workflow.

## Argument

`[ticker]` — optional.
- If specified: re-underwrite that single name
- If omitted: re-underwrite all held positions in sequence (typically scheduled quarterly)

## Procedure

### 1. Determine scope

If ticker provided: scope = single name.
If not: query Postgres for all held positions; scope = all.

For "all" mode, prioritize:
- Positions where last re-underwrite is approaching 90 days old
- Positions with recent materiality-3 escalations
- Positions with unresolved predictions due in next 30 days

### 2. For each ticker in scope: invoke /research-company

Each re-underwrite is essentially `/research-company <ticker>` with these differences:
- Existing thesis_pillars, target_price, and reviewable_predictions are surfaced as input context (not as prejudice — the agent should challenge them)
- Outcome of prior predictions (resolved or in-flight) are noted
- BearCase is run with explicit context: "this is a re-underwrite of an existing position; what has changed and what was missed?"

### 3. Compare new memo to prior

Side-by-side:
```
THESIS PILLARS — BEFORE vs AFTER:
  Pillar 1 (FY26 revenue ≥ $X): unchanged | revised | dropped | new
  Pillar 2: ...

TARGET PRICE — BEFORE vs AFTER:
  $X (Q3 2025) → $Y (Q4 2025): change = Z%

CONFIDENCE DISTRIBUTION:
  P10/P50/P90 vs prior: ...

CONVICTION:
  Prior: 0.68
  New: 0.74 (or 0.55 etc.)
  Driver of change: <evidence>
```

### 4. Re-underwrite decision

Based on the comparison + new memo + bear case:

- **CONTINUE HOLDING**: thesis intact, conviction maintained
- **HOLD WITH NOTE**: thesis mostly intact but specific concerns flagged for monitoring
- **REDUCE**: thesis weakened, recommend trimming position
- **EXIT**: thesis broken or materially weakened; recommend full exit

### 5. Cross-reference with `/exit-check`

If the re-underwrite recommendation is REDUCE or EXIT, also run `/exit-check <ticker>` to apply tax-aware logic and produce specific exit/trim recommendation per `.claude/references/exit-triggers.md`.

### 6. Persistence

Write to Postgres:
- New CompanyDeepDive memo (versioned; prior memo retained)
- New BearCase critique
- Re-underwrite decision record
- Updated thesis_pillars (or note pillars unchanged)
- Resolution of any in-flight predictions if applicable

### 7. Output

```
QUARTERLY RE-UNDERWRITE — <ticker>

PRIOR THESIS (date: <X>):
  - Pillar 1: <text> [STATUS: intact / weakened / broken / replaced]
  - Pillar 2: <text> ...
  - Target price: $X
  - Conviction: 0.X

NEW THESIS (date: today):
  - Pillar 1: <text>
  - Pillar 2: <text>
  - Target price: $X
  - Conviction: 0.X

KEY CHANGES:
  - <change 1 with cited evidence>
  - <change 2>

BEAR CASE UPDATE:
  - New unrebutted concerns: <list>
  - Pre-existing concerns resolved: <list>
  - Bear confidence: <X>

RE-UNDERWRITE DECISION: CONTINUE HOLDING | HOLD WITH NOTE | REDUCE | EXIT

[If REDUCE or EXIT:]
RECOMMENDED ACTION: <specific>
TAX COST ESTIMATE: $<X> (from /exit-check)

NEXT REVIEW DATE: <90 days from today, or sooner if specific catalyst>
```

## Re-underwrite cadence

- **Standard**: every 90 days per held position
- **Ad-hoc trigger**: materiality-3 escalation from /daily-monitor
- **End-of-quarter sweep**: typically run all positions in sequence at quarter-end as part of overall portfolio review

## Cost estimate

Per `/research-company`: ~$50-95 per ticker. For all-mode with 30-50 names quarterly: ~$1500-4750/quarter, or ~$500-1600/month. This is the largest single cost contributor in v0.5+; track in BUILD_LOG.md.

For v0.1, this command is not used in critical path (no held positions yet); used for testing.

## When NOT to use

- Within 30 days of last full re-underwrite of the same name (premature; thesis hasn't had time to play out)
- For names that aren't held (use `/research-company` for fresh research instead)
