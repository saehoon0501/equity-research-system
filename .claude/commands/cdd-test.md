---
description: SCOPED TEST of the former cdd-lead Stage 1 + Stage 2 logic only (post-2026-05-12 refactor). Runs main-session orchestration through integrated CDD memo emission, then STOPS — does NOT dispatch catalyst-scout, pm-supervisor, or evaluator. (The bear-case subagent that this test originally skipped was retired in the same 2026-05-12 batch.) Use to validate the architectural refactor on a single ticker before spending on the full /research-company chain. Test scaffolding; safe to delete after validation.
argument-hint: <ticker>
---

# /cdd-test

**Purpose:** isolate the load-bearing architectural test from the 2026-05-12 v2 orchestrator refactor. The refactor moved cdd-lead's Stage 1 + Stage 2 orchestration into the main session and inlined search-agent's MCPs into each specialist. This test validates that this portion works end-to-end without spending on the downstream chain.

**Validates:**
1. Main session can dispatch `quantitative-analyst` + `strategic-analyst` as first-level subagents (the platform-block resolution from Consensus Item #1).
2. Specialists can use their inlined MCP grants (the Consensus Item #2 test — direct edgar/yfinance/fundamentals/fred/market_data without search-agent dispatch).
3. Stage 1 + Stage 2 orchestration logic ports correctly to main-session (the Consensus Item #3 test — absorbed into /research-company).
4. Integrated CDD memo gets emitted with the v1.1 schema and persists to `analyst_briefs` + `research_essentials` + `evidence_index`.

**Does NOT validate:**
- catalyst-scout (Consensus Item #4 — same inlining pattern, can be tested similarly later). The former bear-case subagent was retired 2026-05-12 and its responsibility absorbed into pm-supervisor §2.6.
- pm-supervisor synthesis (Consensus Item #5 — unchanged, but consumes outputs from skipped agents)
- Single-evaluator-at-end gate (Consensus Item #6)

## Argument

`<ticker>` — required. The US-listed equity ticker to run the scoped CDD on.

## Procedure

Execute steps 1–2.5 from `.claude/commands/research-company.md` verbatim, then **STOP**. Specifically:

### 1. Pre-flight checks

Verify these MCPs only (subset of /research-company's pre-flight, since polygon + macro_stack are not used by CDD stages):
- `mcp__edgar`
- `mcp__market_data`
- `mcp__yfinance`
- `mcp__postgres`
- `mcp__fundamentals`
- `mcp__fred`

Tables: `research_essentials` (migration 027), `analyst_briefs` (migration 028).

If any MCP or table is missing, halt and tell the operator which one.

### 2. Stage 1 (main-session pre-dispatch + brief generation)

Run all 9 steps of `/research-company.md` §2 verbatim:
1. Tier classify
2. Sector identify
3. Read prior `analyst_briefs`
4. Read `research_essentials`
5. Pull fresh context directly via MCP
6. Build briefs
7. Compute `delta_summary` (warm-start only)
8. Persist briefs to `analyst_briefs`
9. Dispatch `quantitative-analyst` + `strategic-analyst` in parallel via Task tool

### 2.5. Stage 2 (main-session integration + verification + essentials distillation)

Run all 6 steps of `/research-company.md` §2.5 verbatim:
1. Integrate quant + strategic memos
2. Verify load-bearing claims directly via MCP (D-5 forensic resolution as needed)
3. Distill durable cross-company learnings → UPSERT `research_essentials`
4. Banned-outputs check
5. Populate `evidence_index`
6. Emit unified CDD memo per v1.1 schema; persist to disk

### 3. STOP

After Stage 2 emits the integrated CDD memo, **stop execution**. Do NOT dispatch catalyst-scout, pm-supervisor, or evaluator. (Bear-case retired 2026-05-12; no longer dispatched anywhere.)

## Output to operator

```
SCOPED CDD TEST COMPLETE for <ticker>

ARCHITECTURE VALIDATION RESULTS:
- Main-session dispatch of quant + strategic: <succeeded | failed with reason>
- Specialist inlined MCPs reachable: <quant-side yes/no | strategic-side yes/no>
- Stage 1 brief generation: <succeeded | failed>
- Stage 2 integration: <succeeded | failed>
- Integrated memo schema: <conforms to v1.1 | mismatch>
- DB persistence: <analyst_briefs rows: N | research_essentials UPSERTs: M | evidence_index inserts: K>

INTEGRATED CDD MEMO:
<full memo per v1.1 schema>

NEXT STEPS:
- If everything succeeded: refactor is validated; safe to run full /research-company <ticker> for downstream chain test
- If anything failed: capture the failure mode, then triage — frontmatter issue, prompt-body drift, or platform-rule violation
```

## Cost estimate

Per the 2026-05-12 refactor:
- Stage 1 + Stage 2 main-session orchestration: ~$3-8
- quantitative-analyst on Sonnet with inlined MCPs: ~$10-18
- strategic-analyst on Sonnet with inlined MCPs: ~$10-18

Total: **~$25-45 cold-start**. Substantially less than full `/research-company` (~$50-100) because §3-§4.5 (bear/catalyst/pm/evaluator) are skipped.

## When to use

- Validate the v2 orchestrator refactor on the first test ticker (MU, per the 2026-05-12 plan)
- Iterate on specialist prompt bodies after stale "cdd-lead" textual references are cleaned up
- Smoke-test after any future edit to quantitative-analyst.md or strategic-analyst.md

## When to retire

Once the architecture is validated and the operator is confident the refactor works end-to-end, this scaffolding command can be deleted. The full `/research-company` is the production path; this is just the scoped test.

## Architecture references

- `docs/v2-orchestrator-refactor-consensus.md` — the 6 locked consensus items
- `.claude/commands/research-company.md` §2 + §2.5 — the source-of-truth steps this command executes
- `feedback_subagent_no_nested_dispatch.md` (auto-memory) — the platform fact that drove the refactor
