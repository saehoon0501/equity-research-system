# `.claude/` — the `equity-research` plugin surface

This directory is the operator interface to the equity research system. The project's goal is
unchanged from v2-final: pick good stocks under the discipline of mechanical contamination defense
and adversarial pressure-testing. Per BUILD_LOG decision 6, **Claude Code is the brain** — slash
commands and subagents hold the orchestration logic; Python (under repo-root `src/`) exists only as
leaf-level tools (MCP servers + skill helpers), never as an orchestrator.

As of the 2026-05-26 plugin restructure, the repo is packaged as a single Claude Code plugin,
`equity-research` (manifest at `.claude-plugin/plugin.json`). Scope was collapsed to the one
value-producing workflow per BUILD_LOG decision 7 (see `docs/decision-7-sweep-set.md`); all
off-critical-path machinery was archived to `archive/_retired/` (reversible).

## Layout

```
.claude-plugin/plugin.json   # plugin manifest (name, version, commands/agents/mcpServers paths)
.claude/
├── commands/                # operator entry points
│   ├── research-company.md  # 🎯 the orchestrator — full slow-layer run → BUY/HOLD/TRIM/SELL
│   └── evaluate.md          # Evaluator process-rubric grading of an output
├── agents/                  # subagents, grouped by stakeholder; dispatched BY NAME via Agent()
│   ├── analysts/            # quantitative-analyst.md, strategic-analyst.md
│   ├── overlays/           # tactical-overlay.md, flow-overlay.md, mean-reversion-overlay.md
│   ├── catalyst/           # catalyst-scout.md
│   ├── supervisor/         # pm-supervisor.md
│   └── eval/               # evaluator.md   (subdir path is cosmetic — identity = name: frontmatter)
├── references/              # cross-cutting procedural content, loaded via `Read` by path
├── settings.json            # tracked governance hooks (P8 — never move to settings.local.json)
└── settings.local.json      # local, gitignored (MCP enable-list, local perms)
```

Repo-root siblings the plugin depends on (unchanged, stay at root so module paths and hook scripts
resolve): `src/` (Python: MCP servers + leaf helpers), `scripts/` (hook + validation scripts),
`.mcp.json` (9 MCP servers), `db/` (migrations + init), `tests/`.

## The workflow

```
/research-company <TICKER>
```

Main-session orchestrator: §1.5 parameter snapshot (hard gate) → Stage 1 brief generation +
parallel dispatch of quantitative-analyst, strategic-analyst, tactical-overlay, flow-overlay →
Stage 2 CDD integration (inline) → catalyst-scout → pm-supervisor (synthesis + adversarial
stress-test + sleeve-cap gate) → single evaluator end-gate. Output: one execution recommendation
(BUY / HOLD / TRIM / SELL — canonical 4-bin) with conviction tier and size band.

`/evaluate <output>` runs the Evaluator process rubric standalone.

The full procedure (parameter-snapshot invariants, PARAMETERS_USED ground-truth blocks, envelope
persistence, PostToolUse hook validation, HG-* gates, terminal-status discipline) lives in
`commands/research-company.md` and the agent specs. See repo `CLAUDE.md` for the load-bearing
architectural principles (P1–P14, T1–T4).

## MCP integration

External services are reached only through MCP servers (`.mcp.json`), each implemented under
`src/mcp/<name>/` and launched via `uv`:
`postgres` (Evidence Index + append-only persistence), `contamination_check` (mechanical
claim-to-row resolution, attached inside `evaluator`), `edgar` (filings), `market_data`
(prices/news), `yfinance` (estimates/comps), `fundamentals` (Sharadar PIT, stub), `fred` (macro),
`polygon` (options positioning, consumed by catalyst-scout), `macro_stack` (cycle/regime context).

## Hooks

- **PreToolUse** (`scripts/research_company_as_of_tag_gate.sh`, in tracked `settings.json`) —
  HMAC-validates `--as-of-tag` sweep args before the orchestrator runs.
- **PostToolUse** (`scripts/post_agent_validate.sh` → `src/shared/agent_harness/orchestrator_step.py`) —
  locates each subagent envelope by `run_id`, runs the HG-* shape/math gates, and drives the
  fingerprint-dedup + cost-ledger + 3-strike retry/escalate state machine.

## Plugin loading note

A `.claude-plugin/plugin.json` is dormant during normal project use — Claude Code loads
`.claude/commands` + `.claude/agents` as project scope exactly as before. The manifest activates
the plugin only when explicitly installed or loaded (`claude --plugin-dir ./`), at which point it
provides the same commands/agents/MCP for distribution. (If the plugin is loaded *while* this repo
is also the active project, commands/agents may appear twice — once project-scoped, once as
`equity-research:<name>` — which is cosmetic, not breaking.)
