# BUILD_LOG

The project's load-bearing journaling artifact. Every week ends with an entry. Every slip is documented here. Every checkpoint references back to entries here. See `docs/implementation-sequencing.md` §3.2 for schema.

---

## Day 1: 2026-04-26 (Sunday)

**Operating model:** FTE (~40 hours/week)

**Build clock begins:** 2026-04-26

### Calendar anchors

| Anchor | Date | Week |
|---|---|---|
| Build clock begins | 2026-04-26 | Week 1 start |
| Checkpoint 1 (data layer + Evidence Index live) | 2026-05-23 | End of week 4 |
| Checkpoint 2 (agent harness + memo end-to-end) | 2026-06-20 | End of week 8 |
| Checkpoint 3 generation phase (≥30 memos written) | 2026-07-18 | End of week 12 |
| Checkpoint 3 evaluation phase (backtest + audit + gates) | 2026-07-25 | End of week 13 |
| **Kill threshold** | **2026-10-10** | **End of week 24** |

**Margin between Checkpoint 3 (evaluation) target and kill threshold:** 11 weeks (FTE track default after Checkpoint 3 split per implementation-sequencing.md revisions).

### Buffer week schedule (FTE track)

- **Week 5** (2026-05-24 to 2026-05-30): absorbs slips from weeks 1–4
- **Week 9** (2026-06-21 to 2026-06-27): absorbs slips from weeks 6–8
- **Weeks 14+** (post-Checkpoint 3): margin to kill threshold; not freely consumable

### External dependencies status

| Dependency | Status | Target |
|---|---|---|
| Anthropic API access | PENDING | Capture verification artifact this week (week 1) |
| Anthropic API key | PENDING | Procure week 1 |
| TimescaleDB + Postgres | NOT PROVISIONED | Provision week 1 (local Docker) |
| Sharadar account | NOT APPLIED — DELIBERATELY DEFERRED | Apply week 9 (lands by week 10) |
| Price/news data provider | DEFERRED | Commit ~week 4 when sample data is needed |

### Architectural decisions (Day 1)

**1. Path A — override v2-final §1.3 model-family diversity mandate.**

All agents run on Anthropic via Claude Code subagent infrastructure. The model-family diversity defense for BearCase is deliberately not enforced.

*Rationale:* operational simplicity outweighs the secondary contamination defense. The primary defense — mechanical Evidence Index check via §4.2.5 — remains intact and is invariant to model choice. Both CompanyDeepDive and BearCase memos undergo the same mechanical claim-to-row resolution check; contamination protection does not depend on model diversity.

*What is lost:* the secondary semantic-judgment diversity that would catch contamination patterns visible to a different model family but not to Anthropic. The acceptance is that Anthropic's training-data contamination is the same for both agents, and the mechanical check (which is invariant) is the load-bearing defense.

*Reversibility:* if the contamination defense underperforms (post-cutoff degradation >20% at Checkpoint 3), the override is the first thing to revisit. Restoring §1.3 means routing BearCase through OpenAI or Google API directly, bypassing Claude Code for that one agent.

*Documented here, not silent.* The startup configuration check that v2-final §4.3 specifies is replaced with a documented acknowledgment of this override. The check would block this configuration otherwise.

**2. Data API abstraction — deliberate deferral.**

Pluggable data layer is built in week 2 with adapter interface and minimal stubs. Specific provider commitments deferred:

- **Price/news provider** (Polygon, Finnhub, yfinance, etc.): commit by week 4 when sample data is needed for early CompanyDeepDive testing
- **Sharadar Core Fundamentals**: defer application until week 9 (3–7 business day lead time means it lands by week 10 for BacktestingFramework integration)

*Rationale:* avoids week 1 silent absorption waiting on external dependencies. Documented here as deliberate deferral, not silent absorption.

*Risk:* if price/news provider selection drags past week 4, downstream sample memo generation is gated. Tracked as a hard week-4 deadline.

**3. Agent harness substrate — Claude Code subagents replace LangGraph.**

v2-final §4.3 specified LangGraph as the harness. Path A means the harness is Claude Code's subagent infrastructure (Task tool invocation, .claude/agents/ definitions). Supporting infrastructure — Evidence Index write hooks, mechanical contamination check, process rubric grading — is implemented as Python wrappers around subagent invocations and as post-processing on subagent outputs.

*What is preserved:* the mandatory Evidence Index write hook, the mechanical contamination check, the process rubric hard gates, the model-family configuration check (replaced with the Path A override acknowledgment), the versioned prompts.

*What changes operationally:* prompts live in .claude/agents/ markdown files with YAML frontmatter, not in a Python prompt registry. Versioning happens via git history of those files.

**4. Skills-only operational interface — post-Day-1 revision.**

Original Day-1 plan: Python orchestration layer wrapping Claude Code subagents (with the Python implementing the daily heartbeat, Evidence Index write hooks, mechanical contamination check, etc.).

Revised: pure Claude Code-native interface. The operator runs the system entirely through slash commands and subagent invocations. No Python orchestration layer. External systems (market APIs, fundamentals, filings, macro, persistence) connected via MCP servers. See `.claude/references/mcp-required.md` for the required MCP list.

*Architecture:*
- `.claude/commands/` — 12 slash command entry points (operator interface)
- `.claude/agents/` — 3 subagents where context isolation matters: CompanyDeepDive, BearCase, Evaluator
- `.claude/references/` — cross-cutting reference content loaded by commands and agents
- `.claude/README.md` — three-layer architecture documentation

*Why subagents preserved (not skills only):* The bull/bear adversarial pair (CompanyDeepDive vs BearCase) needs context isolation to avoid sycophancy collapse. Path A already weakened the v2-final §1.3 model-family diversity defense; running the pair in main shared context (no subagent isolation) would weaken it further. The three subagent contexts preserve what isolation we have.

*Implementation timeline impact:* The original v0.1 week 6 task was "agent harness scaffolding (Python wrappers around subagent calls)." Under skills-only, week 6 becomes: (a) end-to-end test that an operator can invoke `/research-company` and get back a memo through the full mechanical contamination check, (b) verification that the mechanical check is actually enforced as a hard gate in this skills-only architecture (open question: where does the post-sample hook attach when agents are subagents invoked from a slash command? Answered week 6 day 1 by inspecting Claude Code's hook surface or implementing as wrapper logic in the slash command itself).

*Reversibility:* if skills-only architecture proves unable to enforce the mechanical contamination check reliably, fall back to a thin Python wrapper in week 6 that orchestrates subagents and runs the post-sample hooks externally. The architectural commitments (mandatory Evidence Index population, mechanical check, process rubric hard gates) remain intact regardless of substrate.

### §9.3 commitment statement

> ⚠️ **TO BE WRITTEN BY OPERATOR IN OWN WORDS — DO NOT LEAVE BLANK**
>
> Per implementation-sequencing.md §9.3, this is written by you in your own words, not copied from the template. The act of writing it is the commitment.
>
> Cover, in your own phrasing:
> - Weekly BUILD_LOG entries even on smooth weeks
> - Written checkpoint artifacts, not self-assessment
> - Documented slip, not silent absorption
> - Scope discipline against in-flight additions
> - The kill threshold as structural boundary, not budget
> - The build process itself produces artifacts (BUILD_LOG, checkpoint artifacts, provider verification, design docs in the repo) with standalone value regardless of whether v0.1 advances to v0.5 or hits the kill threshold
>
> ---
>
> *[Operator: write your commitment statement here, then delete this placeholder block.]*

---

## Week 1: 2026-04-26 to 2026-05-02

**Planned scope (per implementation-sequencing.md §4):**

- [x] Repo initialized at /Users/sehoonbyun/Documents/equity-research-system; BUILD_LOG.md committed Day 1 with §3.2 first entry
- [x] Project structure established per §3.1
- [x] Day 1 first commit per §9.2 (BUILD_LOG.md, README.md, provider_verification/ scaffolding, checkpoints/ empty, docs/ with v2-final spec, phasing plan, implementation sequencing)
- [ ] TimescaleDB + PostgreSQL provisioned (local Docker) and tested
- [ ] Anthropic API verification artifact captured per implementation-sequencing.md §2.2
- [ ] Anthropic API key procured and tested
- [ ] Pluggable data layer interface designed (interface only, not implemented)
- [ ] §9.3 commitment statement written in operator's own words

**End-of-week test (target: 2026-05-02):**
- Anthropic verification artifact in `provider_verification/`
- Databases queryable (sample query against TimescaleDB hypertable + Postgres JSONB)
- Pluggable data layer interface documented
- BUILD_LOG entry for week 1 written
- Operator §9.3 commitment statement filled in

### Day 1 (2026-04-26) progress

- ✓ Directory created: `/Users/sehoonbyun/Documents/equity-research-system`
- ✓ Git initialized
- ✓ Directory structure per §3.1 created
- ✓ BUILD_LOG.md written (this file)
- ✓ README.md written
- ✓ .gitignore configured
- ✓ provider_verification/ scaffolding (Anthropic template only — Path A means no second provider)
- ✓ docs/ populated: v2-final-spec.md, phasing-plan.md, implementation-sequencing.md
- ✓ src/ structure with planning README
- ✓ checkpoints/ created (empty; populated at C1, C2, C3)
- ✓ §9.2 first commit (commit `de7000a`)
- ✓ docs/harness-reference.md added (commit `b6af330`) — Claude Code architecture as week-6 prep
- ✓ Skills-only pivot (decision 4 above) authored as full architecture:
  - `.claude/commands/` — 12 slash commands authored
  - `.claude/agents/` — 3 subagents authored (company-deep-dive, bear-case, evaluator)
  - `.claude/references/` — 13 reference files authored (Evidence Index schema, contamination check, process rubric, position sizing formula, exit triggers, prediction resolution, daily-monitor tier routing, MCP requirements, 7 industry addenda)
  - `.claude/README.md` — three-layer architecture documentation

**Notes:** This is the disciplined-now version of you. The repo's git history begins with discipline (BUILD_LOG.md + design docs + verification scaffolding) before any feature code. That ordering is intentional per implementation-sequencing.md §9.2.

The skills-only pivot (decision 4) is a substantial architectural change from the original Day-1 plan. It happened on Day 1 itself, before any week-1 build work started, so it doesn't count as a mid-build scope change. Documented here as the new baseline; future weeks reference this revised architecture.

**Outstanding Day 1 items still required from operator (unchanged by pivot):**
1. Write §9.3 commitment statement in own words (placeholder block in this file)
2. Capture Anthropic verification artifacts per `provider_verification/anthropic.md` checklist
3. Provision TimescaleDB + Postgres locally (Docker simplest)

After those land, week 1 day 2+ work begins. Under skills-only, week 1 work is leaner because there's no Python harness to scaffold:
- Database provisioning + Evidence Index DDL ready to apply
- Initial MCP wiring for Postgres
- Verify slash commands are discoverable by Claude Code at `.claude/commands/`

### Actual scope completed (end of week update — fill in 2026-05-02)

[TBD — fill in at end of week]

### Slipped scope (if any)

[TBD]

### Buffer status

- Week 5 buffer (2026-05-24 to 2026-05-30): unused
- Week 9 buffer (2026-06-21 to 2026-06-27): unused

### Cost spent this week

- API costs: $0 (running total: $0)
- Subscriptions: $0 (running total: $0)
- **Projected v0.5 monthly cost based on current trajectory:** TBD (vs $400 cap)

### Pace judgment

[TBD at end of week 1]

**Evidence for judgment:** [TBD]

### Notes / decisions

- Path A architectural decision committed and documented above. Reversibility path noted.
- Data API abstraction deferral committed and documented. Week-4 deadline for price/news provider tracked.
- Sharadar deferred to week 9 application. Calendar reminder: 2026-06-22 to 2026-06-28.
