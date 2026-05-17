# v2 Orchestrator Refactor — Consensus Document

**Date:** 2026-05-12
**Session purpose:** Lock the architectural refactor for the v2 orchestrator after empirical confirmation that Claude Code blocks nested subagent dispatch.
**Status:** LOCKED. All Tier-A investment-decision-logic dimensions resolved. Implementation can proceed.
**Session protocol:** `/grill-me option 1 vs option 2` — single-section format, 4 consensus questions.

---

## 1. Triggering finding

On 2026-05-12, a cold-start MU dispatch test on the patched `cdd-lead` subagent failed at first sub-dispatch with platform error:

> `"No such tool available: Task. Task is not available inside subagents."`

Claude Code blocks nested subagent dispatch on this build. Subagents cannot spawn subagents regardless of frontmatter `Agent` grants. The v2 architecture — `cdd-lead` dispatching `search-agent` + `quantitative-analyst` + `strategic-analyst` as sub-subagents — is structurally incompatible.

**Source memory files:**
- `feedback_subagent_no_nested_dispatch.md` — platform fact + exact error string
- `project_pending_mu_test_run.md` — Attempt 2 diagnostic
- `project_agents_missing_Agent_tool.md` — original hypothesis (frontmatter-missing) marked falsified

---

## 2. Operator profile (captured during session)

- **Optimization preference:** Simplicity over complexity. Explicitly stated during push-back #1 override.
- **Acceptable risk:** Wider contamination surface + reduced gating in exchange for fewer moving parts. Operator chose to absorb stacked-risk pattern (Items #2 + #6 reinforce each other's risk) rather than carry it as design complexity.
- **YAGNI bias:** Confirmed by Q3 — declined to build standalone `/cdd` for a hypothetical future need.

---

## 3. The position (refined form)

Refactor `/research-company` so all orchestration runs at the main Claude Code session level. Retire `cdd-lead.md` and `search-agent.md`. Each remaining analyst (`quantitative-analyst`, `strategic-analyst`, `bear-case`, `catalyst-scout`) becomes a self-contained first-level subagent with direct data-fetch MCP grants. Evaluator runs once at the end. `pm-supervisor` unchanged.

Architecturally this is **Option 2 (Promote orchestrator to main)** with the search-agent decision swung toward inlining (Option 1's data-fetch collapse, applied to data-fetch only — specialists themselves remain split).

---

## 4. Locked consensus items

### Consensus Item #1 — Specialist split preserved
**Claim:** The `quantitative-analyst` ⟷ `strategic-analyst` separation is load-bearing for investment-decision quality. Damodaran/Mauboussin valuation frameworks and Helmer/Mauboussin moat frameworks must remain in dedicated subagents with dedicated prompts.
**Reasoning:** Framework prompts are deep and non-overlapping; collapsing them into one CDD generalist would degrade both valuation and moat analysis quality.
**Parameter:** Both `quantitative-analyst.md` and `strategic-analyst.md` survive the refactor as first-level subagents.

### Consensus Item #2 — search-agent retired; MCPs inlined into each specialist
**Claim:** `search-agent.md` is deleted. Each specialist gets direct grants on edgar + yfinance + fred + market_data + fundamentals MCPs (+ polygon for catalyst-scout) and absorbs source-routing knowledge into its own prompt body.
**Reasoning:** Operator chose simplicity of main-session orchestration loop (4 dispatches per run vs. 5+ chained dispatches) over the structural contamination boundary that search-agent's separation provided.
**Parameter:** Each specialist's frontmatter `tools:` line grows from `~3 tools` (postgres only) to `~18 tools`.
**Noted-risk-acknowledged:**
- Contamination check surface widens 2.5x (4 agents × ~18 tools = ~72 grants vs. current ~28).
- Source-routing knowledge becomes duplicated across 4 prompts; will drift on the order of weeks unless actively maintained.
- Concrete failure mode flagged: raw 10-K text in quant's context can anchor terminal-growth assumptions in narrative DCF.
- Operator accepted these risks for orchestration simplicity. Mitigation deferred to ops-monitoring, not design-time gating.

### Consensus Item #3 — cdd-lead.md retired; logic absorbed into /research-company
**Claim:** `cdd-lead.md` is deleted. Stage 1 + Stage 2 orchestration logic moves into the prompt body of `/research-company` (`.claude/commands/research-company.md` or similar). No standalone `/cdd` slash command.
**Reasoning:** YAGNI — operator does not currently need CDD-only-on-a-name capability; extract later if that need materializes.
**Parameter:** One slash command (`/research-company`) is the single entry point for full investment research.

### Consensus Item #4 (derived) — bear-case + catalyst-scout get the same inlining treatment
**Claim:** `bear-case.md` and `catalyst-scout.md` get direct MCP grants (same set as quant + strategic, plus polygon for catalyst-scout) and their "dispatch search-agent" prompt-body instructions are rewritten to do data-fetch directly.
**Reasoning:** Both currently declare nested dispatch and are broken under the platform rule; same fix pattern as Item #2.
**Parameter:** Both files get rewritten frontmatters + rewritten data-fetch prompt sections.

### Consensus Item #5 (derived) — pm-supervisor + evaluator unchanged
**Claim:** `pm-supervisor.md` and `evaluator.md` remain as first-level subagents with their current frontmatters and prompt bodies.
**Reasoning:** Neither dispatches sub-subagents (pm-supervisor only synthesizes existing memos; evaluator only runs rubrics + contamination checks). Both compatible with the platform rule as-is.
**Parameter:** No file changes.

### Consensus Item #6 — Evaluator runs once, on pm-supervisor's final output only
**Claim:** Evaluator gating is reduced from "every named memo type" (current behavior per evaluator skill description) to "pm-supervisor's final output only" within `/research-company` runs.
**Reasoning:** Operator chose maximum simplicity. Stacked-risk warning was visible at decision time (Item #2 already widened contamination surface 2.5x; Item #6 further reduces structural gating); operator accepted.
**Parameter:** Inside `/research-company`, the evaluator subagent is dispatched exactly once, after pm-supervisor returns its ADD/WATCH/PASS/REJECT decision.
**Noted-risk-acknowledged:**
- Late detection: contamination originating in quant/strategic propagates through bear-case → catalyst-scout → pm-supervisor before being caught. Whole run is wasted; failure localization requires manual triage of each memo.
- Stacks with Item #2 — both the per-agent data-fetch boundary AND the per-memo gating boundary are weakened in the same refactor. Mitigation deferred to ops-monitoring.
- The evaluator's other invocation contexts (MacroCycle, DailyMonitor outside `/research-company`) are unaffected — they continue gating as today.

---

## 5. Critical architectural findings

### Finding A — Subagent topology is single-level on this Claude Code build
Locked as durable platform fact in `feedback_subagent_no_nested_dispatch.md`. Any future agent definition whose prompt body contains "Dispatch via Agent" or "dispatch sub-subagent" is architecturally invalid and must be flagged. The evaluator HG-13 check from `project_agents_missing_Agent_tool.md` should be inverted accordingly: instead of "must have Agent in tools", the rule becomes "subagent prompt body must not declare Agent dispatch."

### Finding B — Main-session context is now a finite resource for /research-company runs
With orchestration in main session, each `/research-company` run accumulates state across stages (Stage 1 brief construction → quant + strategic memos → integrated CDD memo → bear-case + catalyst-scout memos → pm-supervisor synthesis). The system needs a discipline for managing this — likely intermediate-memo persistence to disk (already implied by `analyst_briefs` / `research_essentials` / `evidence_index` schemas) — so that the main session can offload state between stages. This is implementation-detail, not Tier-A; flagged here so it's not forgotten.

### Finding C — The contamination check's load-bearing assumption may need re-validation
The evaluator skill description names the mechanical contamination check as "the load-bearing protection under Path A." With Item #2 widening the contamination surface 2.5x and Item #6 reducing gate count, the check is now operating in a different regime than it was designed for. Recommended (not locked, but flagged): a one-shot validation that the check still catches the specific failure modes it was designed to catch under the new architecture. Spec author should confirm.

---

## 6. Design changes from prior baseline

| Component | Before (v2 design as of 2026-05-11) | After (this refactor) |
|---|---|---|
| `cdd-lead.md` | Subagent orchestrator dispatching search + quant + strategic | RETIRED; logic absorbed into `/research-company` |
| `search-agent.md` | First-level subagent owning all data-fetch MCPs | RETIRED; MCPs distributed to each specialist |
| `quantitative-analyst.md` | Subagent with postgres MCPs only; dispatches search-agent | Subagent with postgres + edgar + yfinance + fred + market_data + fundamentals (~18 tools); does own data-fetch |
| `strategic-analyst.md` | Subagent with postgres MCPs only; dispatches search-agent | Subagent with same widened MCP set; does own data-fetch |
| `bear-case.md` | Subagent dispatching search-agent | Subagent with widened MCP set; does own data-fetch |
| `catalyst-scout.md` | Subagent dispatching search-agent + polygon | Subagent with widened MCP set + polygon; does own data-fetch |
| `pm-supervisor.md` | First-level subagent, synthesis only | UNCHANGED |
| `evaluator.md` | First-level subagent, gates many memo types | UNCHANGED at file level; INVOCATION reduced inside `/research-company` to once-at-end |
| `/research-company` | Slash command dispatching cdd-lead → bear-case → pm-supervisor | Rewritten; main-session orchestrator handling all 4 specialist dispatches + final pm-supervisor + single final evaluator gate |

---

## 7. Deferred items (out of scope for this consensus; track separately)

| Item | Activation trigger |
|---|---|
| Cleanup of 2 orphaned MU briefs from 2026-05-11 dry run (analyst_briefs rows `42efaa17-...` quant + `749f3add-...` strategic) | Before next end-to-end MU test |
| Concrete main-session context management strategy (intermediate-memo persistence cadence, /clear discipline between stages) | When `/research-company` is reimplemented |
| Evaluator HG-13 redesign — "subagent prompt body must not declare Agent dispatch" mechanical check | When evaluator gate definitions are next edited |
| Standalone `/cdd` slash command extraction | If operator ever needs CDD-only on a name |
| Contamination check re-validation under widened surface (Finding C) | Before first live trade decision routed through refactored `/research-company` |
| `feedback_subagent_mcp_scoping.md` update — note that the `claude --resume` bullet remains true but is no longer the binding constraint; platform rule is | Memory hygiene pass |

---

## 8. What's locked vs what's open

**Locked (Tier-A investment-decision-logic):**
- Orchestrator location: main session (Item #1, #3)
- Specialist split: preserved (Item #1)
- search-agent fate: retired, inlined (Item #2)
- cdd-lead fate: retired, absorbed (Item #3)
- bear-case + catalyst-scout treatment: same inlining (Item #4)
- pm-supervisor + evaluator file structure: unchanged (Item #5)
- Evaluator gate placement inside /research-company: once at end (Item #6)

**Open (Tier-B/C implementation details — punch-list, not /grill-me-worthy):**
- Concrete `/research-company` prompt body content (port Stage 1 + Stage 2 logic from cdd-lead.md)
- Concrete MCP grant lists per specialist (the ~18-tool sets, written out exactly)
- Concrete source-routing prompt sections per specialist (the inlined routing knowledge)
- Migration order: which file to edit first, regression tests between edits
- Operator cleanup of the 2 orphaned MU briefs (delete vs preserve as test fixtures)

---

## 9. Handoff

Section closed. Document at `docs/v2-orchestrator-refactor-consensus.md`. Ready for implementation, which can begin with the `quantitative-analyst.md` frontmatter + prompt rewrite (lowest-risk single file to validate the inlining pattern before propagating to strategic + bear-case + catalyst-scout).

Or another `/grill-me` topic if operator wants to lock something else first.
