---
description: Guided weekly BUILD_LOG.md entry creation per implementation-sequencing.md §3.2 schema. Captures planned scope, actual scope, slips, buffer status, costs, pace judgment.
argument-hint: (no arguments — runs against current week)
---

# /weekly-buildlog

Per implementation-sequencing.md §3.3:

> End of every week, BUILD_LOG entry written before the week closes. Even on weeks where the entry is "scope completed as planned, no slips, no notes." Especially on those weeks. The entry takes 10 minutes. Skipping it is the first signal of over-commitment.

This command guides the operator through writing that entry.

## Procedure

### 1. Determine current week

Read BUILD_LOG.md. Find the most recent week entry. Determine current week N (week 1 starts on Date X = 2026-04-26).

If today is end-of-week (Friday/Saturday for FTE; Sunday for evenings track if that's the boundary), this is the entry for week N. If a week N entry already exists with content, this is week N+1 in progress.

### 2. Pull planned scope from implementation-sequencing.md

Read `docs/implementation-sequencing.md` for the operating model's track (FTE or evenings per BUILD_LOG.md Day 1):

For FTE track week N:
- Scope per §4 of implementation-sequencing.md
- End-of-week test definition

For evenings track week N:
- Scope per §5 of implementation-sequencing.md

### 3. Prompt operator for actual progress

Walk through the planned scope items one by one. For each:
- Did this complete? (yes/no/partial)
- If no/partial: what slipped, why?

For each slip:
- Recovery plan: which buffer week absorbs this?
- Documented in BUILD_LOG, not silently absorbed

### 4. Capture buffer status

Per implementation-sequencing.md §7.2:

FTE track buffer weeks: 5, 9, post-week-13
Evenings track buffer weeks: 8, 13, 21–22

For each buffer week (if relevant for current schedule position):
- Unused?
- Consumed by what?

### 5. Capture cost data

Pull current month's running cost from cost-tracker (or estimate if MCP not yet integrated).

```
Cost spent this week: $X
Running monthly cost: $Y
Projected v0.5 monthly cost based on current trajectory: $Z (vs $400 cap)
```

### 6. Pace judgment

Three options:
- **On pace**: planned scope completed, no slips, buffer not consumed
- **Behind**: some scope slipped; named buffer being consumed
- **Kill threshold becoming relevant**: significant slip; recovery plan unclear; less than 4 weeks of margin remaining

Evidence for the judgment is required (specific items, not vibes).

### 7. Capture notes/decisions

Anything worth capturing for future-tired-you:
- Design decisions made this week
- Surprises (good or bad) discovered
- References to documents/discussions that would matter at v0.5+
- Anti-patterns observed and what to remember

### 8. Append to BUILD_LOG.md

Use the schema from implementation-sequencing.md §3.2:

```markdown
## Week N: [date range]

**Planned scope:**
- [from §4 or §5 week-N spec]

**Actual scope completed:**
- ✓/✗ [each planned item]

**Slipped scope (if any):**
- [item, reason for slip, recovery plan: which buffer week absorbs this]

**Buffer status:**
- Week 5 buffer: unused / consumed by [item]
- Week 9 buffer: ...

**Cost spent this week:** $X (running total: $Y)
**Projected v0.5 monthly cost based on current trajectory:** $Z (vs $400 cap)

**Pace judgment:** on pace / behind / kill threshold becoming relevant
**Evidence for judgment:** [specific, not vibes]

**Notes / decisions:** [anything worth capturing for future-tired-you]
```

### 9. Verify entry written

Confirm the entry is appended to BUILD_LOG.md and the file is saved. Operator should commit the change with a message like `BUILD_LOG: week N entry`.

## Why this command exists

Per implementation-sequencing.md §10.4:

> 10.4 — Skipping BUILD_LOG entries on smooth weeks.
> Specific case: weeks 1, 2, 3 went well; entries skipped because "nothing to report"; baseline is missing when rough weeks need context.
> Prevented by: §3.3 hard rule that entries are written every week regardless of progress; §8.2 anti-pattern named explicitly.

The hard rule is the discipline. This command makes it easy to follow.

## Edge case: missed weeks

If multiple weeks have been missed since the last BUILD_LOG entry, this command runs separately for each missed week, in chronological order. Even if the operator can't fully reconstruct what happened in a missed week, they record what they can recall + flag the gap. A documented gap is honest; a silent skip is silent absorption.

## Cost

Negligible — operator-driven, mostly conversation. Some MCP queries for cost tracking.
