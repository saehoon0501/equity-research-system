# Harness Reference Architecture

**Status:** Week 6 prep reference
**Source:** Claude Code internal architecture (reference codebase at `/Users/sehoonbyun/Documents/clear-code`)
**Purpose:** Under Path A (BUILD_LOG.md Day 1), our agent harness is Claude Code's subagent infrastructure. We're not building a harness — we're plugging our load-bearing components into Claude Code's existing extension points. This document maps where each piece of our infrastructure attaches.
**When this doc is consumed:** Week 6 (FTE) / Week 9 (evenings) — Agent Harness Scaffolding

---

## 1. Reference architecture (Claude Code)

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                          ENTRY / BOOTSTRAP LAYER                              ║
╠══════════════════════════════════════════════════════════════════════════════╣
║   entrypoints/cli.tsx  ──►  main.tsx  ──►  (auth, settings, MCP, tools)      ║
║       (flag fast-path)        (full init + command dispatch)                  ║
╚══════════════════════════════════════════════════════════════════════════════╝
                                      │
              ┌───────────────────────┼───────────────────────┐
              ▼                       ▼                       ▼
      ╔═══════════════╗      ╔═══════════════╗       ╔═══════════════╗
      ║  REPL (Ink)   ║      ║  Print Mode   ║       ║   Bridge /    ║
      ║ screens/REPL  ║      ║  cli/print.ts ║       ║  Remote (CCR) ║
      ╚═══════════════╝      ╚═══════════════╝       ╚═══════════════╝
              │                       │                       │
              └───────────────────────┼───────────────────────┘
                                      ▼
╔══════════════════════════════════════════════════════════════════════════════╗
║                       AGENTIC LOOP — query.ts                                 ║
║   ┌────────────────────────────────────────────────────────────────────┐     ║
║   │  queryLoop():                                                       │     ║
║   │    1. sample model  ──►  2. extract tool uses  ──►  3. run tools    │     ║
║   │    ▲                                                  │             │     ║
║   │    │                                                  ▼             │     ║
║   │    └─── 5. continue / stop ◄── 4. attach results, maybe compact ────┘     ║
║   └────────────────────────────────────────────────────────────────────┘     ║
╚══════════════════════════════════════════════════════════════════════════════╝
       │                  │                   │                    │
       ▼                  ▼                   ▼                    ▼
 ┌───────────┐    ┌─────────────┐     ┌──────────────┐    ┌──────────────┐
 │ MODEL API │    │ TOOL DISPATCH│    │  COMPACTION  │    │    HOOKS     │
 │ services/ │    │ services/   │     │  services/   │    │   hooks/     │
 │ api/      │    │ tools/      │     │  compact/    │    │   utils/     │
 │ claude.ts │    │  ├ orchest. │     │   ├ auto     │    │   hooks/     │
 │           │    │  ├ Streaming│     │   ├ reactive │    │  ├ pre-sample│
 │ • streaming    │  │  Executor│     │   ├ snip     │    │  ├ post-samp │
 │ • caching │    │  └ exec     │     │   └ micro    │    │  ├ canUseTool│
 │ • betas   │    │             │     │              │    │  └ stop      │
 │ • thinking│    └──────┬──────┘     └──────────────┘    └──────────────┘
 └───────────┘           │
                         ▼
       ┌────────────────────────────────────────┐
       │           PERMISSION GATE              │
       │  utils/permissions/, useCanUseTool.tsx │
       │     mode: default | bypass | auto      │
       │     rules: settings + policy + plugins │
       └─────────────────┬──────────────────────┘
                         ▼
╔══════════════════════════════════════════════════════════════════════════════╗
║                              TOOL POOL — tools.ts                             ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Built-in tools/                          │  MCP federated tools              ║
║  ├ Bash        ├ FileEdit/Read/Write      │  services/mcp/                   ║
║  ├ AgentTool   ├ SkillTool                │   ├ client.ts (server pool)      ║
║  ├ TaskCreate/Get/List/Update/Output      │   ├ useManageMCPConnections      ║
║  ├ EnterPlanMode / ExitPlanMode           │   └ config.ts                    ║
║  ├ AskUserQuestion / TodoWrite            │                                  ║
║  ├ WebFetch / LSP / NotebookEdit          │  Skills:  tools/SkillTool/       ║
║  └ CronCreate/Delete/List, Sleep          │           skills/bundled/        ║
╚══════════════════════════════════════════════════════════════════════════════╝
                         │
                         ▼ (sub-agents spawn isolated query loops)
       ┌────────────────────────────────────────┐
       │      AgentTool / Coordinator           │
       │  utils/createSubagentContext.ts        │
       │  coordinator/coordinatorMode.ts        │
       └────────────────────────────────────────┘

╔══════════════════════════════════════════════════════════════════════════════╗
║                       CROSS-CUTTING SERVICES                                  ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  STATE          │  state/AppState.tsx, store.ts, onChangeAppState.ts         ║
║  MESSAGES       │  types/message.ts, utils/messages.ts (normalize, strip)    ║
║  CONTEXT        │  context.ts, constants/prompts.ts (system + CLAUDE.md)     ║
║  SESSIONS       │  sessionStorage, conversationRecovery, teleport            ║
║  AUTH           │  services/oauth/, keychain, trust dialogs                  ║
║  ANALYTICS      │  services/analytics/, cost-tracker, growthbook, OTel       ║
║  COMMANDS       │  commands.ts, messageQueueManager (slash + queue)          ║
║  RENDERING      │  ink/ (custom DOM, ANSI), structuredIO, print              ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

**The heart in one line:**

> `query.ts` is the loop: sample → tool_use → permission → execute → result → compact → repeat, with hooks firing at each transition and state mutations propagating through store to the REPL.

---

## 2. Why Path A leverages this

Path A's architectural commitment (BUILD_LOG.md Day 1) was: all agents run on Anthropic via Claude Code subagent infrastructure. The trade-off was losing model-family diversity for BearCase in exchange for operational simplicity.

This reference architecture is what the operational simplicity buys: a complete, well-engineered agentic harness with sample/tool-use/permission/execute/result/compact/hooks already implemented and tested. Building a Python+LangGraph equivalent of this — including the streaming model API, tool orchestration, permission gate, compaction strategies, and subagent isolation — would consume most of v0.1's 12-week budget by itself.

Path A's tax (no model diversity) is paid against the §4.2.5 mechanical Evidence Index check (invariant to model choice). Path A's dividend is this: we get a working harness on Day 1 of week 6, not week 6 + 4.

---

## 3. Extension-point mapping

Where each load-bearing component from the v2-final spec attaches to Claude Code's architecture.

### 3.1 Evidence Index write hook

**v2-final §4.3 requirement:** Mandatory Evidence Index write hook in agent harness — every claim auto-populates an Evidence Index row before output release.

**Attachment point:** `hooks/utils/hooks/` post-sample hook.

**Mechanism:**
1. Post-sample hook fires when subagent produces a structured output
2. Hook scans output for claims per the §4.2.5 definition rule (any sentence with numerical value, date, or specific named fact about a company beyond identity)
3. For each claim detected, write an Evidence Index row with: agent_id, agent_run_id, claim_text, claim_type, source_uri, source_date, source_quality_tier, surfaced_date
4. If a claim has no source_uri or source_date, the post-sample hook returns a structured rejection that loops back to the subagent for revision

**Implementation note:** the hook should not be a soft validator — it should be a hard gate. A subagent output without proper Evidence Index population is returned, not released downstream.

### 3.2 Mechanical contamination check

**v2-final §1.6 hard gate:** Any agent output where evidence_id references resolve to rows post-dating the claim → returned for revision.

**Attachment point:** `hooks/` post-sample, after Evidence Index write hook completes.

**Mechanism:**
1. After Evidence Index population, mechanical check queries: for every dated claim, does its source_date predate the claim's resolution date?
2. Resolution dates: for thesis predictions, the resolution_date in the prediction record. For historical claims (e.g., "ROIC of 18% over the last 5 years"), the surfaced_date.
3. If any claim fails the check, output is rejected with the specific evidence_id flagged.

**This is the load-bearing protection under Path A.** Model-family diversity for BearCase is not enforced; this mechanical check is what catches contamination regardless of which model produced the output. Implementation correctness here is the most important piece of the harness.

### 3.3 Process rubric grading

**v2-final §1.6 (Evaluator):** Grades outputs of all other agents on process rubrics in real time. Synchronously enforced before output release downstream.

**Attachment point:** `hooks/` post-sample, after mechanical contamination check.

**Mechanism:**
1. After mechanical check passes, post-sample hook spawns Evaluator subagent (different from the agent that produced the output)
2. Evaluator runs the universal process rubric (§3.1 of spec) against the output
3. Hard gates per §1.6: falsifiability, source grounding, evidence-timestamping, calibrated uncertainty, reasoning transparency, counter-evidence acknowledgment
4. Evaluator returns pass/fail + per-criterion scores
5. If fail, original output is returned to the original agent for revision

**Routing per §4.7:** Sonnet-class for routine outputs; Opus-class for hard-gate decisions (CompanyDeepDive memos, PMSupervisor decisions).

### 3.4 Trade execution human-approval gate

**v2-final §4.5 requirement:** All trade recommendations require explicit human approval. No automated trading API authority granted to any agent.

**Attachment point:** `utils/permissions/`, `useCanUseTool.tsx` — the existing permission gate.

**Mechanism:**
1. Any tool that would execute trades (against brokerage API) is configured to require permission mode
2. Permission policy denies auto-approval; every trade-related tool invocation triggers the human-approval flow
3. Daily summary of pending recommendations sent for review per spec §4.5
4. Hard kill switch is a single command that disables the tool category

**Implementation note:** v0.1 has no trades — but the permission policy should be configured from week 6 so the discipline is in place by v0.5 entry. The cost of misconfiguring permissions for the first time at v0.5 entry is worse than configuring early.

### 3.5 Subagent isolation per agent

**v2-final §1.2, 1.3, 1.4, 1.5, 1.6:** Six agents (CompanyDeepDive, BearCase, MacroCycle, PMSupervisor, DailyMonitor, Evaluator) operate independently with separate prompts and outputs.

**Attachment point:** `AgentTool` / `utils/createSubagentContext.ts` / `coordinator/coordinatorMode.ts`.

**Mechanism:**
1. Each of the six agents is implemented as a Claude Code subagent definition in `.claude/agents/<agent-name>.md`
2. YAML frontmatter specifies the agent's name, description (for activation), tools allowed, and any model routing override
3. System prompt enforces the agent's contract — for CompanyDeepDive, the mandatory failure_scenarios-first ordering
4. The orchestrator (typically the PMSupervisor flow or a daily-orchestration script) invokes subagents via the `Task` tool, which creates an isolated context per invocation

**Why this matters under Path A:** isolated subagent contexts are what give us the *isolation* property the bull/bear architecture needs — even though all agents run on the same model family, each has its own context, prompt, and output. The "sycophancy collapse" risk from same-family debate is mitigated by each agent never seeing the other's reasoning *during* its own context window. BearCase reads CompanyDeepDive's output as input data, but produces its critique in a fresh context.

### 3.6 Versioned prompts

**v2-final §4.3 requirement:** Versioned prompts (every prompt change creates a new version; outputs are tagged with the version that produced them).

**Attachment point:** Git history of `.claude/agents/*.md` files.

**Mechanism:**
1. Every prompt change is a git commit modifying the relevant subagent definition file
2. Output tagging: post-sample hook captures the file's current git SHA at invocation time and writes it into the agent_run record alongside the output
3. Reproducibility: any past output can be traced to the exact prompt that produced it via the SHA

**No separate prompt registry needed.** Git is the registry.

### 3.7 Token/cost tracking + budget monitoring

**v2-final §4.7 requirement:** Tiered routing per agent type; monthly inference budget cap of $400; auto-escalation alert at $500; hard cap at $600 halts non-essential agent runs.

**Attachment point:** `services/analytics/cost-tracker` (existing).

**Mechanism:**
1. Cost-tracker already records per-invocation token costs
2. We add a budget monitoring layer that:
   - Aggregates cost per agent type and per day
   - Projects monthly cost at current run rate
   - Triggers Slack/Discord alert at $500/mo projection
   - Halts non-essential agent runs (DailyMonitor Tier 1, scheduled re-underwrites) at $600/mo

**v0.1 cost target:** Per-memo cost measured against ≥30 sample memos at Checkpoint 3; projected v0.5 monthly cost reported in Checkpoint 3 artifact.

### 3.8 Compaction strategy

**v2-final §4.7 prompt caching:** Filings, transcripts, prior memos cached; only delta and prompt change per invocation.

**Attachment point:** `services/compact/` — the existing compaction service has auto/reactive/snip/micro strategies.

**Mechanism:**
1. Long-running context (filings, transcripts) goes into prompt cache via Anthropic's caching API
2. Compaction strategies handle the case when context exceeds the cache window
3. For CompanyDeepDive on a single company: filings + transcripts can be 100k+ tokens. Caching is what makes this affordable.

**Implementation note:** prompt caching configuration (cache key strategy, TTL, eviction) is set up in week 1 per §2.5 of implementation-sequencing.md, not week 6. Compaction strategies are tuned in week 7 when CompanyDeepDive prompt is being iterated.

---

## 4. What we don't extend

Some Claude Code components we use as-is, without extension:

- **Streaming model API** (`services/api/claude.ts`) — used as-is. Streaming, caching, betas, thinking all configured per call.
- **Tool dispatch** (`services/tools/`) — used as-is. We add tools (data layer adapters, Evidence Index queries, BacktestingFramework invocations) but don't modify the dispatch logic.
- **REPL / Print Mode / Bridge** — we use Print Mode for orchestration (daily heartbeat, scheduled runs). REPL is the dev-time interface. Bridge isn't relevant for v0.1.
- **MCP federated tools** — potentially relevant later (e.g., for Sharadar via an MCP server), but v0.1 uses direct Python integration through the data layer adapter pattern.
- **State store** (`state/AppState.tsx`, `store.ts`) — used as-is for ephemeral conversation state. Our Evidence Index, Predictions DB, and Counterfactual Ledger are external Postgres/TimescaleDB, not part of Claude Code's state.

---

## 5. Week-6 build plan

When week 6 starts (FTE: 2026-05-31 to 2026-06-06; evenings: roughly 2026-06-21 onward), the harness scaffolding work is:

1. **Day 1**: Create the six subagent definitions in `.claude/agents/` with placeholder system prompts. Verify they're invocable via the Task tool.
2. **Day 2**: Implement the post-sample hook scaffold with Evidence Index write integration. Test against a dummy claim.
3. **Day 3**: Implement the mechanical contamination check as the second post-sample step. Test against synthetic post-dating claims.
4. **Day 4**: Implement Evaluator-as-subagent invocation from the post-sample hook. Test the rejection-and-revision flow.
5. **Day 5**: Implement permission policy for trade-related tools (placeholder for v0.5; configured but not exercised in v0.1).
6. **End-of-week test:** Dummy subagent runs through the full hook chain — sample → Evidence Index write → contamination check → Evaluator → release-or-revise. End-to-end on a contrived test case.

**Scope discipline reminder:** Week 6 builds the harness scaffolding only. CompanyDeepDive prompt iteration is week 7. Industry-specific addenda are week 7. Sample memo generation is week 12. Don't compress.

---

## 6. Key question for week 6

The reference architecture's hooks layer (`hooks/utils/hooks/`) accepts pre-sample, post-sample, canUseTool, and stop hooks. **Open question for week 6 implementation:** does Claude Code's current public API expose these hooks for project-level customization, or do we need to wrap the harness at a different layer (e.g., a middleware around Task tool invocations)?

If hooks are accessible: the implementation in §3 is straightforward.

If hooks aren't accessible: the alternative is a Python wrapper that invokes Task and then runs Evidence Index write + mechanical check + Evaluator as post-processing on the returned output. Functionally equivalent; cleaner separation; slightly less integrated.

This question gets answered week 6 day 1 by inspecting Claude Code at `/Users/sehoonbyun/Documents/clear-code` for the relevant hook surface.

---

## 7. Reference

- **Source codebase:** `/Users/sehoonbyun/Documents/clear-code` (operator's local copy of Claude Code internals)
- **Architecture diagram source:** Provided by operator in conversation, archived as Day 1 reference
- **The single-line summary worth memorizing:**

> `query.ts` is the loop: sample → tool_use → permission → execute → result → compact → repeat, with hooks firing at each transition.

The post-sample transition is the chokepoint where our load-bearing infrastructure (Evidence Index write, mechanical contamination check, process rubric gate) attaches. That single attachment point carries most of the v2-final §4.3 mandatory hooks.
