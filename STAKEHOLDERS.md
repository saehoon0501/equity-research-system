# Stakeholder map

The system is organized by **stakeholder** — each pipeline role owns its agent spec, its Python
module(s), its envelope/gate code, and its tests. `/research-company` (the orchestrator) wires them
together; see `.claude/commands/research-company.md`.

Dispatch is **by agent name** (`Agent(pm-supervisor, …)`), which is location-independent — Claude
Code resolves subagents by the `name:` frontmatter field, scanning `.claude/agents/` recursively
(per Claude Code sub-agents docs). Python is imported by module path (`src.<stakeholder>.…`), run
from the repo root.

| Stakeholder | Agent spec (`.claude/agents/`) | Python (`src/`) | Tests (`tests/`) |
|---|---|---|---|
| **orchestrator** | — (`.claude/commands/research-company.md`) | — | `tests/integration/*` |
| **analysts** | `analysts/quantitative-analyst.md`, `analysts/strategic-analyst.md` | — (consume MCP + briefs) | `tests/contract/{quantitative_analyst,strategic_analyst}/` |
| **overlays** | `overlays/tactical-overlay.md`, `overlays/flow-overlay.md`, `overlays/mean-reversion-overlay.md` | `src/overlays/{tactical,flow,reversion}/` | `tests/unit/overlays/{tactical,flow}/`, `tests/test_p10_reversion_overlay.py`, `tests/test_reversion_envelope_shape.py`, `tests/contract/{tactical_overlay,flow_overlay}/` |
| **catalyst** | `catalyst/catalyst-scout.md` | — (MCP: polygon, macro_stack, edgar) | `tests/contract/catalyst_scout/` |
| **supervisor** | `supervisor/pm-supervisor.md` | `src/supervisor/` (recommendation emitter, conviction rollup, sizing, hysteresis, catalyst-flow modifier) | `tests/unit/supervisor/`, `tests/contract/pm_supervisor/` |
| **eval** | `eval/evaluator.md` | `src/eval/` (`scorer.py` outer-ring + `gates/` = HG-* envelope/shape validators), `src/mcp/contamination_check/` | `tests/unit/eval/gates/` |
| **shared infra** | — | `src/shared/{agent_harness,data_layer,evidence_index,audit_trail,regime_sidecar,mode_classifier}/` | `tests/unit/shared/*`, `tests/unit/mcp/` |
| **external adapters** | — | `src/mcp/{postgres,contamination_check,edgar,market_data,yfinance,fundamentals,fred,polygon,macro_stack}/` | `tests/unit/mcp/` |
| **operator UI** | — | `dashboard/` (Vite `research-dashboard`; `npm run dev` → `:5173`) | — |

`dashboard/` is the operator's read view across all stakeholders: its Vite dev-server plugin
(`dashboard/vite.config.ts`) serves `/__api/*` by reading `memos/`+`memos/envelopes/`,
`.claude/agents/` (recursively), `logs/validation_attempts.jsonl`, and the DB via
`docker exec equity-research-db psql`. It imports no `src/` Python, so the stakeholder regroup
doesn't touch it. Requires the DB container up + `npm install` in `dashboard/`.

## Pipeline flow (who runs when)

```
/research-company TICKER
  §1.5  parameter snapshot (orchestrator)            → run_parameters_snapshot
  §2    Stage 1 briefs + parallel dispatch:
          analysts (quant, strategic) · overlays (tactical, flow)   [reversion = standalone]
  §2.5  CDD integration (orchestrator, inline)
  §3.7  catalyst                                     → catalyst-scout envelope
  §4    supervisor (synthesis + stress-test + sleeve-cap gate)      → execution_recommendation
  §4.5  eval (single end-gate: contamination + process rubric)
```

## Cross-stakeholder dependencies (load-bearing imports)

- `overlays/tactical` → `shared/regime_sidecar.fred_client` (risk-free-rate resolution)
- `overlays/flow`, `overlays/reversion` → `overlays/tactical.bin_classifier` (monthly-anchor helper)
- `supervisor` → `shared/audit_trail.hmac_verify` (signs `execution_recommendations`)
- `shared/agent_harness` → `eval/gates` (HG-* validators run by the PostToolUse hook
  `scripts/post_agent_validate.sh` → `src.shared.agent_harness.orchestrator_step`)
- `eval/gates.catalyst_modifier_composition_check` → `supervisor.catalyst_flow_modifier` (HG-34 re-derivation)

## Conventions

- `src/overlays/` and `src/shared/` are namespace dirs (no `__init__.py`); the leaf packages keep theirs.
- `src/mcp/` and `docs/` are intentionally **not** regrouped: MCP servers are external adapters (a
  group of their own, and moving them churns `.mcp.json`); docs are heavily path-cited.
- `db/migrations/*.sql` and `BUILD_LOG.md` retain pre-move path mentions as written-time-accurate
  history (immutable record).
