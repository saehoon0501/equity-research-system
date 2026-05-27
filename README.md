# Equity Research System

A two-layer investment research system combining LLM-driven watchlist research (slow layer) with quantitative timing/sizing overlay (execution layer). US equities, multi-month horizon, real-money individual investor at small size.

**Goal:** pick good stocks under the discipline of mechanical contamination defense, calibration-driven sizing, and the v2-final substantive commitments.

**Implementation pattern (decision 6):** an agent-harness around Claude Code. Claude Code is the brain — it holds the orchestration logic, runs prompts, invokes subagents, makes routing decisions through conversational reasoning and slash commands. Code, where it exists, is a *tool* or *sub-system* that Claude Code consumes, never an orchestrator of it.

**Status:** v0.1 build. Step-driven (no calendar; see [`BUILD_LOG.md`](BUILD_LOG.md) decision 5).

**Substrate:** Claude Code (Path A — see [`BUILD_LOG.md`](BUILD_LOG.md) decision 1).

> **2026-05 — packaged as the `equity-research` Claude Code plugin + decision-7 scope collapse + stakeholder regroup.**
> The surface is now the single `/research-company` workflow (+ `/evaluate`); off-critical-path
> machinery (daily-monitor, alerts, drift, premortem, sizing/disposition/watchlist, backtesting,
> governance ceremonies, `/run`) was removed (recoverable via git history). The operator UI
> (`dashboard/`) and the `/research-company` pipeline are retained; `src/` is grouped by stakeholder
> (see [`STAKEHOLDERS.md`](STAKEHOLDERS.md)).
> The "12 commands / `/run` orchestrator" and `backtesting/` descriptions below are **historical**.
> Authoritative current structure: [`.claude/README.md`](.claude/README.md) and the derived sweep
> [`docs/decision-7-sweep-set.md`](docs/decision-7-sweep-set.md).

---

## Documents

Design documents in `docs/` (canonical for substantive details — DDL, agent prompts, gate criteria, anti-patterns):

- **[`v2-final-spec.md`](docs/v2-final-spec.md)** — Component specification. Slow/fast layer separation, agent definitions, quant models, evaluation framework, infrastructure spine.
- **[`phasing-plan.md`](docs/phasing-plan.md)** — v0.1 / v0.5 / v1.0 phasing with phase gates and kill criteria.
- **[`implementation-sequencing.md`](docs/implementation-sequencing.md)** — Original dated build plan; calendar/commitment sections are *no longer the operator's protocol* (per decision 5). Substantive sections (DDL, scope substance, anti-patterns) remain canonical.
- **[`harness-reference.md`](docs/harness-reference.md)** — Claude Code architecture reference.

The build is governed by **[`BUILD_LOG.md`](BUILD_LOG.md)** — the project's operational ledger. Step list, architectural decisions, external-dependency status. No weekly cadence; updated when steps complete.

---

## Architectural commitments (preserved from v2-final)

- **Slow/fast layer separation with strict watchlist contract.** Execution layer can only act on names the watchlist layer has approved.
- **Mechanical contamination defense via Evidence Index.** Every dated claim must cite a row that resolves to a real source predating the claim's resolution date. Mechanical, not semantic — invariant to model choice.
- **Process vs outcome rubric separation.** Process rubrics enforced as hard gates at output time via the Evaluator subagent. LearningLoop (Phase 2, deferred) optimizes against outcome rubrics only — has zero access to process scores as features.
- **Counterfactual ledger.** First-class object measuring system performance against simple baselines (SPY, equal-weight watchlist, sector-matched, 60/40).
- **PASS as default.** CompanyDeepDive's `recommended_action` defaults to PASS; BUY requires earned conviction.
- **Hard human-approval gate on trades.** No automated trading authority granted to any agent.
- **Calibration-driven sizing.** Quarter-Kelly default, adjusted within bounded floor (1/8) / ceiling (1/2 Kelly) based on Brier-score trends over rolling 90-day windows.
- **Wide P10/P90 ranges.** With realized-volatility honesty floor.
- **Thesis-pillar-fail trigger as highest-priority exit signal.** Never tax-suppressed.

---

## Architectural decisions (summary; see [`BUILD_LOG.md`](BUILD_LOG.md) for full rationale + reversibility paths)

1. **Path A.** All agents on Anthropic via Claude Code. Model-family diversity defense (v2-final §1.3) deliberately not enforced. Reversibility trigger: post-cutoff degradation >20% at Checkpoint 3.
2. **Data API abstraction — deferred.** Pluggable interface; provider commitment deferred until needed.
3. **Agent harness substrate = Claude Code subagents** (replaces v2-final §4.3's LangGraph proposal).
4. **Skills-only operational interface.** No Python orchestration layer; operator runs everything through slash commands.
5. **Step-driven build, no timeline.** No build clock, no weekly entries, no kill threshold, no §9.3 commitment statement.
6. **Claude Code is the brain; code is a tool, not an orchestrator.** Positive inverse of decision 4. Agent-harness pattern around Claude Code. Python lives in skill helpers (`src/skills/<command>/`) and MCP server implementations (`src/mcp/<server>/`) — leaf logic only, never control flow.

---

## Architecture (`.claude/`)

The system runs entirely through Claude Code's slash-command + subagent + reference layout:

- **`/run` — master orchestrator** that wraps all other slash commands. Most days, this is the only command typed.
- **12 specialized slash commands** — independently invocable: `/research-company`, `/daily-monitor`, `/macro-cycle`, `/evaluate`, `/quarterly-reunderwrite`, `/entry-check`, `/exit-check`, `/size`, `/checkpoint`, `/wash-sale-harvest`, `/backtest`. (`/weekly-buildlog` deprecated under decision 5.)
- **3 subagents** — context isolation where it matters: `company-deep-dive`, `bear-case`, `evaluator`.
- **References** — `evidence-index-schema.md`, `contamination-check.md`, `process-rubric.md`, `mcp-required.md`, plus equity-research-specific protocols and 7 industry addenda.

The bull/bear adversarial isolation (CompanyDeepDive vs BearCase) is preserved through subagent context boundaries, not Python orchestration. See [`.claude/README.md`](.claude/README.md) for the full three-layer architecture.

## Where Python code lives (per decision 6)

Code is leaf-level and lives in two places only:

1. **Skill implementations** — Python helpers a slash command needs beyond conversational reasoning (deterministic transformations, numerical computation, format checks). `src/skills/<command-name>/` (created when first needed).
2. **MCP server implementations** — Python (or any language) wrapping an external service into MCP-compatible tools. `src/mcp/<server-name>/` or external packages consumed via `.mcp.json`.

There is **no orchestrator code**. Slash commands invoke subagents and run wrapper logic conversationally; subagents are markdown prompts in `.claude/agents/`; persistence is via `mcp__postgres`. If you find yourself writing a Python file that doesn't fit "skill helper" or "MCP server," step back — under decision 6 it likely shouldn't exist.

---

## Phase scope

### v0.1 (current — paper-only foundation)

Step list in [`BUILD_LOG.md`](BUILD_LOG.md):
- Tier 1 — Substrate (DBs, MCPs, runtime config)
- Tier 2 — Conventions (Evidence Index, contamination check, process rubric, append-only persistence; tested with synthetic data)
- Checkpoint 1 — Substrate + Conventions Live
- Tier 3 — Agents (CompanyDeepDive / BearCase / Evaluator / PMSupervisor on a known-historical name)
- Checkpoint 2 — Agents Working End-to-End
- Tier 4 — Application (live data + Sharadar + backtest + ≥30 sample memos)
- Checkpoint 3 — Strategy Validated (v0.1 → v0.5 advancement decision per `docs/phasing-plan.md` §2.5)

C3 gate combines structural correctness (mechanical conventions audit clean, false-pass count = 0) with substantive correctness (post-cutoff Sharpe degradation <20%, DSR > 0.5, PBO < 50%, counterfactual baselines beaten).

### v0.5 (after C3 advancement — duration 9–12 months)

Limited real money. Full agent stack (6 agents). Watchlist limited to 3–5 names at extra-high conviction bar (≥0.7 final_conviction). 10–20% of intended capital. Validates operational machinery — reconciliation, safety rails, daily orchestration, calibration tracking.

### v1.0 (after v0.5 — open-ended; month-18 evaluation)

Full deployment. 30–50 names. Full capital. The alpha question, asked honestly only after v0.1 and v0.5 have validated that the system has earned the right to ask it.

---

## Repo structure

```
equity-research-system/
├── BUILD_LOG.md                    # Operational ledger (step list + architectural decisions)
├── README.md                       # This file
├── .claude/                        # Slash commands + subagents + references (decision 4 substrate)
│   ├── README.md                   # Three-layer architecture documentation
│   ├── commands/                   # 12 slash commands (operator entry points)
│   ├── agents/                     # 3 subagents (CompanyDeepDive, BearCase, Evaluator)
│   └── references/                 # Cross-cutting reference content
│       └── industry-addenda/       # Banks, REITs, biotech, insurance, energy, software, hardware
├── checkpoints/                    # C1, C2, C3 written artifacts (when produced)
├── docs/                           # Design documents (canonical for substance)
│   ├── v2-final-spec.md
│   ├── phasing-plan.md
│   ├── implementation-sequencing.md
│   └── harness-reference.md
├── src/                            # Python (per decision 6: leaf logic only, never orchestrator)
│   ├── skills/                     # Skill helpers for slash commands (created when first needed)
│   ├── mcp/                        # MCP server implementations (created when first needed)
│   ├── data_layer/                 # Pluggable data layer (Tier 4)
│   ├── evidence_index/             # Evidence Index DDL + access (Tier 2)
│   └── backtesting/                # BacktestingFramework (Tier 4)
├── tests/
└── memos/                          # Sample memos generated in Tier 4
```

---

## How to read this repo if you're returning to it tired

1. Read **[`BUILD_LOG.md`](BUILD_LOG.md)** first. Decisions 1–6 tell you what was architecturally committed to and why. The step list tells you where you are.
2. **[`.claude/README.md`](.claude/README.md)** explains the slash command + subagent + reference layout.
3. **`checkpoints/`** has the formal pass/fail artifacts for each step boundary. If a checkpoint says ✗ on a criterion, that's the criterion that failed. Do not argue around it.
4. **[`docs/phasing-plan.md`](docs/phasing-plan.md)** §6 names the substantive failure modes the structure protects against.

Decision 6 is the load-bearing one for "how is this implemented?" — Claude Code is the brain. If you find yourself writing a Python orchestrator, you're violating it; the right fallback is documented in decision 6's reversibility note (revert to code-as-orchestrator only if mechanical conventions can't be enforced reliably under the agent-harness pattern).

The thresholds in `docs/phasing-plan.md` §2.5 are written so motivated reasoning can't relax them. If you want to soften something while reading, that's the threshold doing its job. Tighten, don't relax.

---

## Status board

External dependencies:
- [x] Anthropic runtime resolved (Claude Code, Path A — decision 1)
- [x] TimescaleDB + Postgres provisioned (local Docker)
- [ ] Sharadar Core Fundamentals applied (before Tier 4)
- [ ] Price/news data provider committed (before Tier 4)

Build progress (per [`BUILD_LOG.md`](BUILD_LOG.md) tiered step list):
- [ ] Tier 1: Substrate
- [ ] Tier 2: Conventions
- [ ] Checkpoint 1
- [ ] Tier 3: Agents
- [ ] Checkpoint 2
- [ ] Tier 4: Application
- [ ] Checkpoint 3 + v0.1 → v0.5 advancement decision
