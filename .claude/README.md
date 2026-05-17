# .claude/ — Slash Commands + Subagents + References

This directory is the operator interface to the equity research system. The project's goal is unchanged from v2-final: pick good stocks under the discipline of mechanical contamination defense, calibration-driven sizing, and the rest of the v2-final substantive commitments.

The *implementation pattern* (per BUILD_LOG.md decision 6) is an agent-harness around Claude Code: **Claude Code is the brain** — it holds the orchestration logic, runs prompts, invokes subagents, makes routing decisions through conversational reasoning and slash commands. Code, where it exists, is a *tool* or *sub-system* that Claude Code consumes — never an orchestrator of it.

That implementation pattern is what `.claude/` operationalizes:
- **Prompts** live in `.claude/agents/` markdown with YAML frontmatter, versioned via git history.
- **Slash commands** route operator intent into the right agent or workflow.
- **Subagents** provide context isolation for adversarial pairs and grading.
- **MCP servers** connect external services; Claude Code calls the MCP, the MCP wraps the underlying Python or external API.

There is no Python orchestrator. Where Python code does exist, it lives as leaf logic inside skill implementations (`src/skills/<command-name>/`) or as MCP server implementations (`src/mcp/<server-name>/`).

## Three-layer structure

```
.claude/
├── commands/              # Slash-command entry points (operator interface)
│   ├── run.md             # 🎯 Master orchestrator — wraps all other skills
│   └── <other>.md         # 12 specialized commands (still independently invocable)
├── agents/                # Subagents (isolated context for adversarial pairs + grading)
│   └── <name>.md          # Invoked by commands or other agents via Task tool
└── references/            # Cross-cutting reference content
    └── <topic>.md         # Loaded by Read when commands/agents need it
```

## Why this structure (under Path A, skills-only, decision 6 implementation pattern)

**Path A (decision 1):** all agents on Anthropic via Claude Code subagent infrastructure. Mechanical Evidence Index check is the load-bearing contamination protection (model-family diversity defense from v2-final §1.3 deliberately not enforced).

**Skills-only (decision 4):** operator runs the system entirely through Claude Code's conversational interface. No Python orchestration layer.

**Claude-Code-as-brain (decision 6):** positive inverse of decision 4. Slash commands and subagents *are* the orchestration. Python is a tool consumed via skill helpers and MCP servers; it does not orchestrate.

**Subagents preserved where isolation matters:**
- `agents/company-deep-dive.md` — produces investment memo with mandatory ordering (failure_scenarios first, thesis_pillars second per v2-final §1.2)
- `agents/bear-case.md` — adversarial counter-case (only sees bull memo as input, not the deep-dive's reasoning context)
- `agents/evaluator.md` — process rubric grading (separate context so it isn't biased by the agent it's grading)

Other components (DailyMonitor, MacroCycle, PMSupervisor) live as commands in main context — they don't have the bull/bear adversarial dependency that requires isolation.

## Operator workflows

### Master entry point: `/run`

**This is the single skill that wraps all other skills.** Most days, `/run` is the only command an operator types — it auto-detects phase (v0.1 build vs v0.5+ operations) and cadence (daily/weekly/monthly/quarterly) and routes to the appropriate sub-skills in the right order.

```
/run                  # auto-detect phase, surface what's due
/run status           # read-only status report
/run daily            # force daily cadence (v0.5/v1.0 only)
/run weekly           # force daily + weekly (v0.5/v1.0 only)
/run monthly          # force weekly + monthly (v0.5/v1.0 only)
/run quarterly        # force all layers (v0.5/v1.0 only)
/run build            # v0.1 step-status mode (alias of auto in v0.1)
```

The orchestrator handles idempotency (won't re-run completed cadences), cost tracking, MCP availability checks, reconciliation, and unified output. It never auto-executes trades or auto-activates LearningLoop — those remain operator-confirmed actions.

The 12 individual slash commands below are still independently invocable for ad-hoc use; `/run` is the wrapper that knows the canonical sequencing.

### v0.1 (current — paper-only foundation, step-driven per BUILD_LOG.md decision 5)

Mostly relevant during validation:
- `/research-company <ticker>` — full memo flow on a historical name (for sample memo generation step)
- `/evaluate <memo-path>` — Evaluator process rubric grading
- `/checkpoint <1|2|3>` — guided phase gate evaluation per §6 of `docs/implementation-sequencing.md`; fires at step boundaries, not on dates
- `/weekly-buildlog` — **DEPRECATED** under decision 5; weekly diary cadence removed. Update BUILD_LOG.md directly when steps complete or noteworthy decisions land.

### v0.5 (live, limited) and v1.0 (full deployment)

Daily, weekly, monthly, quarterly cadences per v2-final §4.4:
- `/daily-monitor` — daily news/filings sweep with Tier 1/Tier 2 classification
- `/macro-cycle [delta|full]` — weekly delta or quarterly full
- `/quarterly-reunderwrite [ticker]` — held-name re-underwrite
- `/entry-check <ticker>` — entry quality scoring
- `/exit-check <ticker>` — tax-aware exit signal evaluation
- `/size <ticker>` — position sizing recommendation
- `/wash-sale-harvest <ticker>` — tax-loss harvest with wash-sale path selection
- `/backtest <memo-set>` — BacktestingFramework run

## MCP integration

MCP is the system's external-service layer. Slash commands and subagents reach external systems through MCP servers; they do not call external APIs directly. Per decision 6, MCPs are the canonical pattern for tool/sub-system integration with Claude Code — the MCP wraps Python (or any language) adapter logic into MCP-compatible tools, and Claude Code calls the MCP.

See `references/mcp-required.md` for the full required-MCP list. Slash commands check for MCP availability and report missing connections gracefully — they don't silently fail.

Required MCP servers (operator wires up before the relevant skill is used):
- **Persistence** (load-bearing for Evidence Index + append-only conventions): Postgres/TimescaleDB — `mcp__postgres`
- **Filings**: SEC EDGAR (via edgartools) — `mcp__edgar`
- **Market data** (prices, news): Polygon / Finnhub / yfinance fallback chain — `mcp__market_data`
- **Fundamentals (point-in-time)**: Sharadar Core Fundamentals via Nasdaq Data Link — `mcp__fundamentals`
- **Macro**: FRED — `mcp__fred`
- **Brokerage** (v0.5+): for position reconciliation and trade execution gating — `mcp__brokerage`

## Where Python code lives (per decision 6)

Code, where it exists, is leaf-level and lives in two places only:

1. **Skill implementations** — Python helpers a slash command needs beyond conversational reasoning. Example: a deterministic transformation, a numerical calculation, an output-format check. The slash command is the interface; the Python helper is invoked from inside it. Helpers live in `src/skills/<command-name>/` (created when first needed; not pre-scaffolded).

2. **MCP server implementations** — Python (or any language) wrapping an external service into MCP-compatible tools. Lives outside this repo or in `src/mcp/<server-name>/`; the harness consumes via `.mcp.json` configuration.

There is **no orchestrator code**. Slash commands invoke subagents and run wrapper logic conversationally; subagents are markdown prompts in `.claude/agents/`; persistence is via `mcp__postgres`. If you find yourself writing a Python file that does not fit "skill helper" or "MCP server," step back — it likely shouldn't exist.

## Reference vs command distinction

- **Commands** (`.claude/commands/`): operator-facing entry points. One operator interaction = one slash command.
- **References** (`.claude/references/`): procedural content multiple commands share. Not invoked directly. Loaded via Read when relevant.

A command like `/research-company` invokes the `company-deep-dive` subagent, which loads `references/process-rubric.md` and `references/evidence-index-schema.md` to do its work. The references are the procedure manual; the agents are the workers; the commands are the operator's remote control.

## Status (Day 1+)

- [ ] All commands authored and committed
- [ ] All subagents authored and committed
- [ ] All references authored and committed
- [ ] MCP servers wired up by operator (separate task; see `references/mcp-required.md`)
- [ ] First end-to-end test: `/research-company <historical-ticker>` produces a memo that passes mechanical contamination check
