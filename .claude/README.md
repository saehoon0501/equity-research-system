# .claude/ — Skills Layer for Claude Code

This directory is the operator interface to the equity research system. Per the post-Day-1 pivot (BUILD_LOG.md Day 1 revision), the agent harness is no longer a Python+LangGraph wrapper layer (v2-final §4.3 originally) — it's Claude Code itself, with skills + subagents + references organized here.

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

## Why this structure (under Path A, with skills-only revision)

**Path A (BUILD_LOG.md Day 1):** all agents on Anthropic via Claude Code subagent infrastructure. Mechanical Evidence Index check (§4.2.5) is the load-bearing protection.

**Skills-only revision (post-Day-1):** Operator runs the system entirely through Claude Code conversational interface. No Python orchestration layer. External systems (market APIs, fundamentals, filings, macro) connected via MCP servers (see `references/mcp-required.md`).

**Subagents preserved where isolation matters:**
- `agents/company-deep-dive.md` — produces investment memo with mandatory ordering
- `agents/bear-case.md` — adversarial counter-case (only sees bull memo as input, not its reasoning context)
- `agents/evaluator.md` — process rubric grading (separate context so it isn't biased by the agent it's grading)

Other components (DailyMonitor, MacroCycle, PMSupervisor) live as commands in main context — they don't have the bull/bear adversarial dependency that requires isolation.

## Operator workflows

### Master entry point: `/run`

**This is the single skill that wraps all other skills.** Most days, `/run` is the only command an operator types — it auto-detects phase (v0.1 build vs v0.5+ operations) and cadence (daily/weekly/monthly/quarterly) and routes to the appropriate sub-skills in the right order.

```
/run                  # auto-detect phase + cadence
/run status           # read-only status report
/run daily            # force daily cadence
/run weekly           # force daily + weekly
/run monthly          # force weekly + monthly
/run quarterly        # force all layers
/run build-day        # v0.1 explicit build mode
```

The orchestrator handles idempotency (won't re-run completed cadences), cost tracking, MCP availability checks, reconciliation, and unified output. It never auto-executes trades or auto-activates LearningLoop — those remain operator-confirmed actions.

The 12 individual slash commands below are still independently invocable for ad-hoc use; `/run` is the wrapper that knows the canonical sequencing.

### v0.1 (current — paper-only foundation)

Mostly relevant during validation:
- `/research-company <ticker>` — full memo flow on a historical name (for sample memo generation week 12)
- `/evaluate <memo-path>` — Evaluator process rubric grading
- `/weekly-buildlog` — guided weekly BUILD_LOG.md entry per implementation-sequencing.md §3.2
- `/checkpoint <1|2|3>` — guided phase gate evaluation per §6 of implementation sequencing

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

The skills assume MCP servers are connected for external systems. See `references/mcp-required.md` for the full list. Skills check for MCP availability and report missing connections gracefully — they don't silently fail.

Required MCP servers (operator wires up before the relevant skill is used):
- **Market data** (prices, news): Polygon / Finnhub / yfinance fallback chain
- **Filings**: SEC EDGAR (via edgartools)
- **Fundamentals (point-in-time)**: Sharadar Core Fundamentals via Nasdaq Data Link
- **Macro**: FRED
- **Persistence**: Postgres/TimescaleDB for Evidence Index, Predictions DB, Counterfactual Ledger
- **Brokerage** (v0.5+): for position reconciliation and trade execution gating

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
