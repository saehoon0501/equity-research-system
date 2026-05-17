---
description: Use when an operator-facing plan, design proposal, or architectural decision needs adversarial pressure-testing before execution. Run an iterative loop where a general-purpose reviewer subagent pressure-tests the plan, the system revises, and iteration continues until the reviewer signals "looks solid, no substantive issues" — producing a converged plan ready for execution-approval.
argument-hint: <plan-or-proposal-topic>
---

# /review-me

Run iterative adversarial review of `<plan>` until the reviewer signals consensus. Each iteration the system dispatches a fresh general-purpose agent with the current plan + accumulated context, applies substantive findings, and re-dispatches. The loop terminates only on an explicit "looks solid, no substantive issues" signal from the reviewer — not on the system's own assessment.

This protocol produced the v5-final convergence on the `/research-company` reproducibility-fix plan (5 iterations, 2026-05-17). Use it whenever a plan is non-trivial, when stakes prevent shipping the system's first draft, or when the operator wants external pressure-testing rather than operator-system back-and-forth (which `/grill-me` covers).

## When to use this skill

- A plan / design has been drafted and the operator wants pressure-testing before execution
- The system suspects its own plan has gaps but can't see them from inside
- Stakes prevent shipping the first draft without independent review
- The operator stated "review this" / "pressure-test this" / "check before execute"
- Multi-step implementation plans, schema migrations, architectural decisions
- After `/grill-me` locked a consensus document — review-me stress-tests the locked doc before execution

## When NOT to use this skill

- Simple tasks or fact-lookups (just answer)
- Plans where reviewer will only find polish-level nits (the loop wastes turns)
- Code review of an existing PR (use code-reviewer agent or `/review` instead)
- Operator-system alignment ambiguity (use `/grill-me` first — that's a different protocol)
- The plan is genuinely trivial (1-2 line edits) — don't over-engineer review of a one-liner

## Argument

`<plan-or-proposal-topic>` — required. The plan / decision to review. Can be:
- A draft already shared with the operator
- A consensus document produced by `/grill-me`
- A design proposal in conversation context

If multiple distinct plans, run `/review-me` per plan, not one combined.

## The Loop

### Step 1 — State the plan and context

Before dispatching iteration 1, the system writes (in its own response, not the reviewer prompt):
- **What is being reviewed** (1 sentence)
- **What evidence / investigation precedes this plan** (1-3 bullets — the reviewer needs grounding)
- **Operator preferences load-bearing on the review** (e.g., "minimal + simple", "avoid over-engineering") — these become explicit reviewer constraints

### Step 2 — Dispatch iteration 1

Use the `general-purpose` agent. The dispatch prompt must include:

1. **Context block (given, don't re-verify)** — investigation findings + ground facts the reviewer should treat as established. Saves the reviewer from re-running work.
2. **Plan v1 verbatim** — the actual plan with file:line citations, sizing estimates, dependencies.
3. **Specific review questions** — coverage / sequencing / step boundaries / unmentioned risks / citation spot-check / size estimates / omitted alternatives / hand-wavy claims.
4. **Explicit stopping signal** — "If vN is solid, say 'vN looks solid, no substantive issues' explicitly." This anchors the reviewer's exit condition.
5. **Word-count cap** — start at 600 words; tighten each iteration as plan stabilizes (500 → 400 → 350).

### Step 3 — Synthesize iteration N findings

In the system's own response (operator-visible):
- **Quote 2-3 of the most substantive catches verbatim** so the operator sees the review surface
- **Distinguish substantive vs polish.** Polish nits don't trigger another iteration on their own
- **Cite reviewer's specific corrections of system claims.** If the reviewer said "finding #7 mis-stated X," explicitly acknowledge — don't bury it

### Step 4 — Revise to v(N+1)

Apply every substantive finding. For each:
- **Direct fix** — change the plan
- **Reframe** — when reviewer caught the system was wrong about the problem (not just the solution)
- **Cut** — when reviewer flags over-engineering. Cutting scope counts as a revision.

If the reviewer's finding is wrong (rare), explain why in the next iteration's context block and let the next reviewer arbitrate. Don't silently dismiss.

### Step 5 — Dispatch iteration N+1

Same agent type (`general-purpose`), fresh dispatch (no SendMessage continuity needed — each reviewer is independent). The prompt must include:

- **Iteration log** — "Iteration N caught {issues}; v(N+1) addressed via {fixes}." Keeps reviewer focused on what's new, not re-relitigating closed items.
- **Plan v(N+1) verbatim**
- **Specific questions** — 1-2 of which target whether the v(N+1) fixes are sufficient (don't let the reviewer just acknowledge — make them spot-check)
- **Stopping-signal reminder**
- **Tighter word cap**

### Step 6 — Stop on the signal

The loop ends ONLY when the reviewer writes "v# looks solid, no substantive issues" (or an unambiguous equivalent). The system does not get to declare convergence unilaterally.

If the reviewer's last finding is genuinely a polish nit (style, naming, minor reordering), the system MAY incorporate it inline without dispatching another full iteration, then state the plan is closed.

### Step 7 — Produce the convergence record

After convergence, the system writes:

1. **Final plan (vN-final)** — the actual converged plan, ready for execution
2. **Convergence table** — columns: iteration / substantive issues caught / direction (added vs cut). The "direction" column is load-bearing — it surfaces when over-engineering crept in and got cut later
3. **Execution gate** — `AskUserQuestion` with 3-4 options (full execute / partial / verify-first / defer)

The convergence table prevents future-self from thinking "we converged immediately" — every iteration caught real things, that's why the loop exists.

## Stopping signals

| Reviewer says | Loop action |
|---|---|
| "vN looks solid, no substantive issues" | STOP — produce convergence record |
| Only nit-level findings (typos, naming, prose) | STOP — incorporate inline, produce convergence record |
| Substantive findings caught | Continue — revise, dispatch v(N+1) |
| Reviewer keeps finding new substantive issues across 6+ iterations | STOP — surface to operator. Something fundamental is wrong with the plan's framing |
| Reviewer's finding contradicts the prior reviewer's "looks solid" verdict | Continue 1 more iteration with both findings in the context block |

## Anti-creep guards

Operator preference for "minimal + simple" is a hard constraint, not a vibe. The system must:

- **Flag when reviewer findings drift to polish.** If iteration 4 catches "rename variable X to Y," that's not substantive. Don't continue purely on polish.
- **Score reviewer findings for over-engineering.** If the reviewer says "add caching layer / add new table / add new agent," apply the test: does the drift evidence actually require it? If no, surface "reviewer is suggesting scope creep" in the convergence record and decline the suggestion.
- **Cut steps when reviewer says cut.** Over the v1→v5 lifecycle, plans should typically shrink not grow. v4→v5 cutting 3 over-engineered items is a healthy signal.

## Convergence record format

```markdown
| Iteration | Substantive issues caught | Direction |
|---|---|---|
| v1 → v2 | <count> (<short list>) | added |
| v2 → v3 | <count> (<short list>) | added |
| v3 → v4 | <count> (<short list>) | added |
| v4 → v5 | <count> (<short list>) | **cut** |
| v5 | 0 substantive | converged |
```

Healthy convergence shows: monotonically decreasing issue counts, at least one "cut" iteration, terminating on explicit signal.

Unhealthy convergence shows: oscillating issue counts, no cuts (only additions), terminating because the operator stopped the loop manually.

## Reference: how the protocol ran on the drift-fix plan (2026-05-17)

**Plan reviewed:** 6-step plan to fix `/research-company` run-to-run reproducibility drift after investigating 4 tickers × 2-3 runs.

| Iteration | Reviewer caught | Action |
|---|---|---|
| v1 → v2 | 8 substantive (mis-stated override mechanics, CRWD evidence-graph drift unaddressed, run_id cohort missing, no grandfathering, hand-wavy "30-40%", premature TTL, Step 4 bundled, Step 5 bundled) | added — Steps 4/5 split, Step 6 reframed, measurement phase added |
| v2 → v3 | 8 substantive (canonical override list too narrow, evidence selection root cause, no seed/temp control, no rollup invocation check, no regression tests, baseline scope, schema migration coordination, function location implication) | added — predicates spec, Plan B pre-commit, baseline scope, rollback criteria |
| v3 → v4 | 6 substantive (Phase 0 ordering, validator schema underspecified, Step 6 retrieval determinism, baseline scope expansion, rollback metric undefined, schema-migration atomicity) | added — concrete validator predicates, deterministic candidate set, rollback metric |
| v4 → v5 | 3 substantive (Check D Plan B is over-engineering, `case_id` is fictional, Step 0a is moot) | **cut** — removed prompt-hash caching, fixed tiebreaker keys, deleted Step 0a |
| v5 | 0 substantive | **converged** — "v5 looks solid, no substantive issues" |

Total: 5 iterations, ~25 substantive catches, 1 cutting iteration, terminated on explicit reviewer signal. Plan shrank from "6 steps + cross-cutting" to "6 steps + smaller cross-cutting" while gaining concrete spec detail throughout.

Operator handoff: `AskUserQuestion` with execute / verify-first / Step-1-only / defer.

## Anti-patterns

- **Treating "no substantive issues" as the system's call.** It's the reviewer's call. Don't declare convergence after the system runs out of revision ideas.
- **Letting reviewer findings grow over time.** Healthy loop: issue counts decrease. Growing counts = the plan is moving the target.
- **Adding instead of cutting when reviewer flags over-engineering.** The right response to "this is creep" is to remove that step.
- **Re-litigating closed items.** Each iteration's prompt must include "Iteration N caught X; v(N+1) addressed via Y" so the reviewer doesn't re-open closed catches.
- **Using `/grill-me` and `/review-me` interchangeably.** `/grill-me` is operator-system alignment via Q&A (the operator is in the loop every round). `/review-me` is system-vs-reviewer pressure-testing (the operator gates entry and exit; the loop runs autonomously between).
- **Skipping the convergence record.** Without it, future-self forgets the plan was non-trivial and treats the converged version as obvious.
- **Continuing past 6-7 iterations.** If the loop won't converge, something is structurally wrong with the plan's framing. Surface to the operator and use `/grill-me` to re-align on what's actually being built.

## Output

The session produces three things:

1. **A converged plan** — ready for execution-approval; locked structure with file:line citations and concrete specs
2. **A convergence record** — table of iterations + issues caught + add/cut direction, surfaced to the operator
3. **An execution gate** — `AskUserQuestion` offering execute / partial-execute / verify-first / defer

If any of these is missing, the session isn't done.
