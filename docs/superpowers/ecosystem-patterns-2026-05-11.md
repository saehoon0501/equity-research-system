# Claude Code Ecosystem Patterns — Inventory and Status

**Date:** 2026-05-11.
**Inputs:** Three parallel research-agent reports against `disler/claude-code-hooks-mastery`, `anthropics/skills` spec (Dec 2025), `wshobson/agents`, `VoltAgent/awesome-claude-code-subagents`, `SuperClaude_Framework`, `oraios/serena`, `thedotmack/claude-mem`, `github/spec-kit`, `bmad-code-org/BMAD-METHOD`, `eyaltoledano/claude-task-master`.
**Audience:** operator (deciding which to adopt next).

Each pattern below carries a status:
- ✅ = already adopted today (no action)
- 🟢 = drafted in this session, awaiting operator review
- ⏳ = pending operator decision (medium-risk; touches gating or schema)
- ❌ = skip (low fit for this system)

---

## A. Hooks + verification

### A1. `PostToolUse` hook → automatic contamination_check on subagent outputs
Source: `disler/claude-code-hooks-mastery` post_tool_use.py.
Idea: filter `tool_name == "Task"`, invoke `mcp__contamination_check__verify` against `tool_response`, exit 2 on contamination so stderr is fed back to Claude and the run is forced to retry without persisting.
Impact: closes the bypass window where a contaminated brief could be read by `cdd-lead` before Stage-2 rejection. Uniform across all 4 subagents.
**Status: ⏳ pending operator review.** Medium-high risk — changes when/where gating fires. Needs `.claude/hooks/post_tool_use.py` + `.claude/settings.json` registration. Recommend pilot on one subagent (`bear-case`) before full rollout.

### A2. `SubagentStop` hook → Postgres event log
Source: `disler/claude-code-hooks-multi-agent-observability` send_event.py.
Idea: on every subagent stop, insert to a new `subagent_events` table `(session_id, agent_id, agent_role, hook_event_type, payload JSONB, hmac_chain, timestamp)`.
Impact: uniform event stream for evaluator gates + tamper-evident chain.
**Status: ⏳ pending operator review.** Requires a new migration (next sequential after 022). Low semantic risk but adds persistence load.

### A3. `PreToolUse` hook → block destructive Bash + unapproved MCP writes
Idea: single `.claude/hooks/pre_tool_use.py` for (a) `rm -rf` / `git push --force` / `DROP TABLE` (b) `mcp__postgres__execute` write-side calls outside an allowlist (analyst_briefs, research_essentials, evidence_index, subagent_events).
Impact: enforces "subagents must not arbitrarily mutate Postgres" as a transport rule.
**Status: ⏳ pending operator review.** Low semantic risk; high blast radius if allowlist is misconfigured.

### A4. Split evaluator hard gates: deterministic Python validators + LLM soft scores
Source: Anthropic Skills Dec-2025 spec ("traditional programming is more reliable than token generation").
Idea: HG-1..HG-6 become Python validators bundled as a skill (`evaluator/validators/hg{N}.py`); HG-7..HG-12 stay LLM-judged but with a **different model family** than the generator (Opus generates → Sonnet judges) to break correlated failure.
Impact: largest measurable reduction in gate variance. Sonnet-judges-Opus also partially recovers the Path A model-family-diversity defense the system explicitly waived.
**Status: ⏳ pending operator review.** Touches evaluator.md substantively; needs grill-me session.

### A5. Skills-bundled deterministic validators (general pattern)
Same source. Anything mechanical (citation density, banned phrases, schema conformance) should be code not LLM.
**Status: ✅ partially adopted today.** Mechanical contamination check via `mcp__contamination_check__verify` is exactly this pattern. Extend to more HGs in A4.

---

## B. Skill + subagent structural patterns

### B1. Three-tier progressive disclosure (metadata / SKILL.md body / `references/`)
Source: official `anthropics/skills` Dec-2025 spec; PDF skill exemplifies the pattern.
Idea: SKILL.md body stays <500 lines; rubric tables and worked examples move to `.claude/references/<skill>/`. References stay one level deep.
Impact: every line above 500 in a SKILL.md is paid on every activation. Heaviest current skills: `cdd-lead.md` (240 lines), `evaluator.md` (286 lines), `bear-case.md` (297 lines), `wash-sale-harvest.md` (212 lines), `research-company.md` (204 lines), `backtest.md` (191 lines). Most are already in spec; only `evaluator.md` materially exceeds the 200-line "ergonomic" threshold.
**Status: 🟢 partial precedent already exists** (`.claude/references/empirical/peak-pain-archetypes/`, `industry-addenda/`, `analyst-context-templates/`). Operator decides whether to push further refactor on `evaluator.md` specifically.

### B2. Description-as-trigger: "Use when..." + keywords
Source: Anthropic Skills spec; wshobson's `Use PROACTIVELY when...` convention.
Idea: skill descriptions should lead with explicit invocation keywords so Claude self-routes.
Impact: a quick scan of `.claude/commands/` shows most descriptions already follow "Use when..." (good) but a few cite v3 sections rather than triggers (e.g. some carry "Per v3 spec §X.Y" at the front). Cosmetic improvement at best.
**Status: ✅ largely adopted today.** Skip unless a specific skill is mis-routing.

### B3. `model:` frontmatter for tier routing
Source: wshobson `model: inherit`; VoltAgent `model: sonnet`.
Idea: pin `evaluator` / `cdd-lead` / `bear-case` to opus; `search-agent` to sonnet; document explicitly.
Impact: matches current implicit behavior, becomes explicit + auditable. Cost-routing if combined with `claude-code-router` later.
**Status: ⏳ pending operator decision.** Decide policy (opus vs inherit) before adding frontmatter — adding `inherit` would be a noop documentation change.

### B4. Central symbols / abbreviations table
Source: SuperClaude `MODE_Token_Efficiency.md`.
Idea: `.claude/references/symbols.md` defining recurring shorthand (M-2/M-3, B/B'/C modes, watchlist statuses) so skills don't redefine inline.
**Status: ❌ skip in v0.1.** Premature. Operator hasn't expressed pain around context bloat on these specific symbols. Revisit if `ccusage` shows context burn from repeated glossary definitions.

### B5. Plugin-style folder grouping for `.claude/commands/`
Source: wshobson `plugins/<domain>/{agents,commands,skills}/`.
Idea: regroup as `.claude/commands/{operations,research,governance,risk}/`.
**Status: ❌ skip.** Pure ergonomics; would require updating every `/skill` invocation in BUILD_LOG, specs, attestations. Not worth the churn.

---

## C. Memory + spec workflow patterns

### C1. Constitution as single canonical rules file
Source: `github/spec-kit` `.specify/memory/constitution.md`.
**Status: 🟢 drafted this session at `docs/superpowers/constitution.md` v0.** Awaiting operator review via `/spec-approve constitution v0.1`.

### C2. Hierarchical topic paths in `research_essentials`
Source: `oraios/serena` `.serena/memories/<topic>/<subtopic>.md`.
Idea: add `topic_path TEXT` (e.g. `sector/semis/cyclicality`, `company/NVDA/moat`) so cross-ticker durable lessons (sector mental models, macro priors) don't pollute per-ticker briefs.
**Status: ⏳ pending operator review.** Requires schema migration (next after 022). High fit for the cdd-lead Stage-2 "distill essentials" step.

### C3. Lifecycle-hook write-back to `evidence_index`
Source: `thedotmack/claude-mem`.
Idea: `PostToolUse` on `mcp__edgar__get_filing_text` / `mcp__market_data__get_news` auto-appends to `evidence_index` keyed by `(ticker, claim_hash, citation_url)`.
Impact: closes the leak where citations are read by search-agent but never reach `evidence_index` because the analyst forgot to write.
**Status: ⏳ pending operator review.** Subsumes part of A1's hook scaffolding — design together.

### C4. Phase-sliced documents + `pipeline-status.yaml`
Source: BMAD-METHOD.
Idea: `briefs/<ticker>/<date>/{cdd.md, bear.md, pm.md}` + `research_pipeline_status` Postgres table.
**Status: ❌ skip.** The system already persists analyst_briefs + execution_recommendations. Adding a filesystem mirror is duplication.

### C5. `testStrategy` column on `predictions`
Source: `eyaltoledano/claude-task-master` task schema.
Idea: every prediction declares its falsification test upfront. Pre-registered, not after-the-fact.
**Status: ⏳ pending operator review.** Strong fit for the calibration-loop discipline already wired in `counterfactual_ledger`. Small migration + an HG addition ("HG-13: prediction has testStrategy"). Worth a `/grill-me` session.

---

## Recommended next 3 actions (operator-decision order)

1. **Review and `/spec-approve` the constitution v0** drafted at `docs/superpowers/constitution.md`. Edit freely — the v0 captures what is observable; v0.1 captures what operator endorses.
2. **Decide on pattern A1 + C3 together** (PostToolUse contamination check + auto evidence_index write-back). They share hook scaffolding. Recommend `/grill-me` session.
3. **Decide on pattern C5** (testStrategy on predictions). Smallest schema change with the biggest discipline payoff for the calibration loop.

Defer A4, B3, C2 to a second round after #1–3 land.
