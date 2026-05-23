# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A two-layer equity research system: LLM-driven watchlist research (slow layer) + quantitative timing/sizing overlay (execution layer). US equities, multi-month horizon. **Claude Code is the brain** — slash commands and subagents hold the orchestration logic; Python exists only as leaf-level tools. Status: **v0.1 (paper-only)**, step-driven build with no calendar.

## Load-bearing reading order

1. `BUILD_LOG.md` — architectural decisions 1–6 and the current step list. Decision 6 governs "where does this code go?" Decision 1 (Path A) governs "which model runs this?"
2. `.claude/README.md` — three-layer architecture (commands / agents / references).
3. `docs/v2-orchestrator-refactor-consensus.md` — the 2026-05-12 refactor that produced today's architecture. Names the accepted risks operator chose not to mitigate at design time.
4. `docs/v2-final-spec.md` — canonical spec for substance (DDL, agent prompts, gate criteria).
5. `docs/phasing-plan.md` §2.5 — C3 gate thresholds. Tighten, don't relax.

## Bringing the system up

```sh
cp .env.example .env       # edit POSTGRES_PASSWORD, EDGAR_USER_AGENT, etc.
docker compose up -d
docker compose ps          # expect equity-research-db ... healthy
# MCP servers auto-launched by Claude Code per .mcp.json (each in src/mcp/<name>/, run via uv).
```

HMAC keys (AUDIT, PEAK_PAIN, PREMORTEM, WATCHLIST) have **distinct rotation lifetimes** — never share across scopes.

## Running tests

Repo-root `tests/conftest.py` loads `.env` before collection.

```sh
pytest tests/                          # default (integration_live auto-skipped)
pytest -m integration                  # slow end-to-end
pytest -m integration_live             # live-Postgres smoke; requires docker compose up
pytest tests/test_<name>.py::test_x    # single test
```

Markers `integration` + `integration_live` are registered in `tests/conftest.py`; live tests skip unless explicitly selected via `-m`.

---

## Architectural principles

These are the load-bearing rules of the system. Read them before changing anything structural.

### P1 — Markdown is the orchestrator; Python is a tool

Slash-command specs in `.claude/commands/` hold control flow. Python lives in two places only: **MCP server implementations** (`src/mcp/<server>/`, each with its own `pyproject.toml`, launched via `uv` per `.mcp.json`) and **skill helpers** (`src/skills/<command>/`, created when first needed). Agent prompts are markdown in `.claude/agents/`, versioned via git. If you find yourself writing a Python file that makes routing decisions or dispatches subagents, step back — it likely shouldn't exist.

`src/agent_harness/` is **not** an orchestrator despite the name. It is the per-attempt retry state machine consumed by the PostToolUse hook (see P5). Do not extend it with orchestration logic.

### P2 — Pin ground truth at the boundary; propagate by value

Every numeric threshold that drives a decision (sleeve caps, conviction bands, mode multipliers, DCF bounds, evaluator gate values) is snapshotted at the start of a run in a single REPEATABLE READ transaction, hashed + versioned, and prefixed to every downstream dispatch as a `PARAMETERS_USED` block. Contract: **block wins over prose** if a numeric appears in both. No downstream re-resolution against the live `parameters_active` view mid-run.

### P3 — One key threads everything: `run_id`

A `run_id: <uuid>` line in the dispatch prompt names the envelope file (`memos/envelopes/<agent>__<run_id>.json`), the context sidecar (`<agent>__<run_id>.context.json`), the validation state file, the DB row in `run_parameters_snapshot`, and the audit-log row. Hooks find work by grepping for it. Embed it in every `Agent()` dispatch.

### P4 — Persist between stages; don't prompt-chain

Subagent output → JSON envelope on disk **before return**. Cross-stage communication = file or DB row, never in-context handoff. Halt-and-degrade writes an empty `.degraded` sidecar at the same path, which hooks recognize as a valid skip. This lets main session offload state (finite context budget — see T3) and lets hooks see the artifact.

### P5 — PostToolUse hooks enforce what the spec only asks for

If a contract matters (envelope persisted, `run_id` present, shape valid, cost under ceiling), enforce it at the hook seam — the orchestrator cannot forget. `scripts/post_agent_validate.sh` fires after every `Agent` dispatch, locates the envelope by `run_id`, invokes `src/agent_harness/orchestrator_step.py` (deterministic state machine: fingerprint dedup + cost ledger + 3-strike cap; per-(run_id, agent) cumulative ceiling $60 default), exits 0 PASS / 10 RETRY (with delta-prompt on stderr) / 11 ESCALATE.

This is the canonical place for "logic too deterministic for LLM prose, but too small for a service": push it to Python, leave the re-dispatch decision in Claude Code.

### P6 — Defense in depth on terminal state

Every operation that can fail has a fallback, and the fallback has its own fallback. Terminal `run_parameters_snapshot.run_status` UPDATE → `system_errors` log if UPDATE itself fails → `scripts/reconcile_orphan_snapshots.sh` finalizes the orphan post-hoc to `failed_uncaught`. No silently-stuck `in_progress` rows.

### P7 — Decisions get more conservative downstream, never less

Upstream emits a candidate intent; downstream may downgrade (sleeve cap breach, counterfactual veto, LOW conviction, stress-test failure) but never upgrade. Example: CDD `disposition_recommendation` flows to pm-supervisor as a candidate the synthesizer can lower to HOLD but never raise to BUY. Gating is structural, not optional.

### P8 — Governance lives in tracked config; local cannot shadow it

Hooks belong in `.claude/settings.json` (committed), never `.claude/settings.local.json` (gitignored). `settings.local.json` shadows tracked settings and would silently disable governance. `scripts/hook_smoke_test.sh Test-AsOfTag` catches local-shadow drift.

### P9 — One canonical vocabulary at every layer

Define the enum once, reuse everywhere. BUY/HOLD/TRIM/SELL is the only decision vocabulary across CDD `disposition_recommendation`, pm-supervisor `summary_code`, operator-facing output, and `execution_recommendations` DB writes. No per-layer translation tables.

### P10 — Known asymmetries are documented, not "fixed"

Main session has no `Agent()` to hook into when it emits its own artifact (e.g., the integrated CDD memo at `/research-company` §2.5). The accepted seam is a manual `scripts/validate_envelope.sh` call with the orchestrator's own LLM patching the YAML on RETRY. **Do not subagent-ize CDD integration to make the asymmetry disappear** — you'll break the working pattern and introduce nested-dispatch (forbidden by T1).

### P11 — Each agent owns its envelope schema and its own HG validator

Do not propose a shared base envelope interface for multi-agent communication. LLM consumers read heterogeneous shapes natively; cross-agent persistent state goes through DB tables, not envelope inheritance. Each agent: own spec → own envelope → own HG validator in `src/evaluator_gates/`.

### P12 — Spec changes touching agent emission require a smoke test

Static checks and projection cannot catch shape divergences (object-vs-string, missing optional key, enum drift). After editing an agent spec, run a scoped live dispatch and inspect the persisted envelope's Python types before claiming the change merge-ready.

### P13 — `envelope_shape.py` (HG-23) is presence-only by design

The HG-23 envelope validator checks key presence, not value type. `NULLABLE_SUBKEYS` accepts any non-null value; `"string | null"` annotations in spec docs are narrative convention only. Operator decision 2026-05-23 made this gap intentional. Type-correctness is not guaranteed by HG-23 — don't assume it when designing downstream consumers; validate types yourself if you need them.

### P14 — Test surface is two concentric rings; build inner before outer

`/research-company` has two distinct test surfaces with a strict build order:

**Inner ring — per-step unit tests (refactor safety net).** Pure-unit tests for deterministic cores: sleeve-cap math, mode-classifier rules, tactical-overlay Antonacci signal, F-Score / Z'' / DCF math, evaluator rubric gates, envelope HG validators, DB append-only triggers. Contract / golden-envelope tests for LLM-driven subagent emissions (complement HG-23's presence-only validation per P13 with richer per-agent shape assertions). Goal: any subagent or layer can be refactored and verified in isolation in <1s, no LLM, no MCP, no live DB.

**Outer ring — Eval loop (price-vs-prediction).** Compares the final 4-bin label (per P9 vocabulary) against sector-ETF-excess returns at 90d / 1y / 3y / 5y horizons (HIGH-4 consensus 2026-05-16, Brinson-Fachler benchmark). Lives on `counterfactual_ledger` (mig 030, universal-write, append-only). Feeds calibration → parameter tweak → if persistent miss → model refinement or replacement.

**Build order is strict: inner ring first, outer ring sits on top.** An outer-ring miss is uninterpretable without inner-ring guarantees — you can't tell whether a calibration signal is a real model failure or a refactor regression. Do not wire outer-ring scoring against any component that lacks inner-ring coverage.

---

## Accepted tradeoffs (operator-acknowledged, not bugs)

### T1 — Main-session orchestration is platform-forced

Claude Code blocks nested subagent dispatch (`Task is not available inside subagents`). Frontmatter `Agent` grants pass static checks but have no runtime effect. The orchestrator therefore must live at main-session level (e.g., `/research-company`). Per `docs/v2-orchestrator-refactor-consensus.md`, the 2026-05-12 refactor accepted these unmitigated risks:
- **Contamination surface widened ~2.5x** (4 agents × ~18 MCP grants vs prior ~28 grants).
- **Source-routing knowledge duplicated** across 4 specialist prompts — drifts on weeks-timescale unless actively maintained.
- **Single end-gate evaluator** (Consensus Item #6) means upstream contamination propagates through every stage before detection.

Mitigation deferred to ops-monitoring, not design-time gating. Do not "fix" these by re-introducing nested-style topology.

### T2 — MCP grants in agent frontmatter must be tool-level

Use `mcp__edgar__get_company_facts`, never server-level shorthand `mcp__edgar`. Restart Claude Code after editing agent frontmatter — static check passes either way but the server-level form silently fails at runtime.

### T3 — Main-session context is finite for long flows

Stage 1 of `/research-company` inlines 8–12 MCP calls (cold-start) into main session — formerly delegated to a `search-agent` subagent, retired 2026-05-12. Adding more MCP calls to Stage 1 risks pushing past Claude Code's window. Use intermediate-memo persistence to disk between stages (per `analyst_briefs` / `research_essentials` / `evidence_index` schemas).

### T4 — Cost circuit-breaker is per-(run_id, agent), not per-run total

`orchestrator_step.py`'s `cost_ceiling_usd` (default $60) caps cumulative retries for a single (run_id, agent) pair. There is no per-run aggregate cap across all subagents. A `/research-company` run can spend $40–85 cold-start; nothing currently halts a runaway aggregate. Be aware when designing new chains.

---

## Project-specific don'ts

- Don't move prompts out of `.claude/agents/` into Python.
- Don't add a Python orchestrator (decision 6 / P1).
- Don't nest subagent dispatches (T1).
- Don't write server-level MCP grants in agent frontmatter (T2).
- Don't subagent-ize main-session integration steps to "use the hook" (P10).
- Don't propose shared base envelope interfaces (P11).
- Don't trust HG-23 for type-correctness (P13).
- Don't wire outer-ring (Eval-loop) scoring against any component lacking inner-ring unit-test coverage (P14).
- Don't relax C3 thresholds in `docs/phasing-plan.md` §2.5.
- Don't add Evidence Index fields "later" — schema is load-bearing for v0.5+.
- Don't add weekly-cadence machinery — decision 5 removed BUILD_LOG weekly entries and `/weekly-buildlog`.
