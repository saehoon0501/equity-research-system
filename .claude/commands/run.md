---
description: Master orchestrator that wraps all skills into one workflow. Auto-detects current phase (v0.1 build vs v0.5+ operations) and routes to appropriate sub-commands. v0.1 surfaces step status; v0.5/v1.0 runs the daily/weekly/monthly/quarterly operational cadences. Use this as the single entry point to operate the system.
argument-hint: [briefing|status|launch-gates|today] (default: briefing)
---

# /run

Single entry point to operate the equity-research system. Per v3 spec
Section 5.4 — auto-detects current phase from Postgres state and renders
the appropriate operator briefing. Render-only: surfaces work, never
auto-executes downstream commands.

## Arguments

`[mode]` — optional. Default: `briefing`.

- **`briefing`** (default) — full operator briefing: phase, gates or
  cadence actions, pending decisions, alerts, system health.
- **`status`** — phase status only (key/value lines, no markdown).
- **`launch-gates`** — Section 7 launch-gate status grid (any phase).
- **`today`** — today's recommended cadence actions (v0.1-active+).

## Procedure

### 1. Pre-flight checks

- `mcp__postgres` connected (load-bearing — every phase predicate reads
  Postgres).
- Either `psycopg` (v3) or `psycopg2` available in the Python environment
  running the CLI.

### 2. Invoke the renderer

The slash command shells out to the Python module via Bash:

```bash
python -m src.orchestrator.cli              # full briefing
python -m src.orchestrator.cli status       # phase only
python -m src.orchestrator.cli launch-gates # Section 7 gate grid
python -m src.orchestrator.cli today        # cadence actions today
```

The CLI prints terminal-rendered Markdown. Render the output as-is to
the operator.

Exit code mapping:
- `0` — success
- `4` — bad arguments
- `5` — environment / driver missing

### 3. Phase detection (no operator config)

The orchestrator infers phase from observable Postgres state:

| Phase | Trigger |
|---|---|
| `v0.1-launch-readiness` | launch gates not all green / launch_readiness_log unsigned |
| `v0.1-active` | launched; < 50 resolved predictions; < 540 days since launch |
| `v0.5-active` | ≥ 50 resolved predictions OR ≥ 540 days since launch (Section 8.1) |
| `v1.0-active` | parameters_active contains real_money_execution = LIVE |

Detection is defensive: missing tables (e.g., early v0.1 builds) default
to `v0.1-launch-readiness` rather than raising.

### 4. Briefing structure

**v0.1-launch-readiness** — surfaces the Section 7 gate grid:
- Section 7.1: 11 hard gates (functional correctness)
- Section 7.2: 6 calibration gates (≥80%/≥90% targets)
- Section 7.3: 6 operator sign-off attestations
- Section 7.3a: 10 walkthrough launch gates

Each gate shows status (`PASS` / `FAIL` / `PENDING`) + evidence link
(when recorded in `launch_readiness_log`). Operator records PASS via
`/launch-confirm <gate_name>`.

**v0.1-active+** — surfaces cadence actions:
- **Daily** (post-market close + 30 min): `/daily-monitor`, `/alerts`,
  `/system-health`
- **Mode-tuned per ticker** (P5+P6+P7 emit cycle): Mode B weekly Mon
  open / Mode B' every 3d / Mode C daily
- **Quarterly** (Q-end): `/parameters-review`,
  `/premortem --cadence-floor`, catalog hygiene 10% audit
- **Annual** (Jan 1): full peak-pain catalog audit, materiality drift
  gold-standard refresh

Plus, in every active phase:
- Pending operator decisions (anchor-drift forced reviews,
  counterfactual-veto overrides, mode reclassification proposals)
- Unread alert summary (links to `/alerts`)
- System health summary (links to `/system-health`)

### 5. Examples

Full briefing (default):
```
/run
```

Phase status only (machine-friendly key/value):
```
/run status
```

Launch gate grid:
```
/run launch-gates
```

Today's cadence actions (v0.1-active+):
```
/run today
```

## What `/run` does NOT do

- **No auto-execution.** Briefing surfaces work; the operator triggers
  each downstream slash command (`/daily-monitor`, `/alerts`,
  `/parameters-review`, etc.) manually.
- **No trade execution.** Per v3 Section 1.4, the system does not
  execute trades. v0.1 is research/recommendation only.
- **No gate auto-marking.** Section 7 gates flip green only when the
  operator runs `/launch-confirm <gate_name>` which writes to
  `launch_readiness_log`.
- **No state writes.** Read-only across all subcommands.
- **No bypass of `/spec-approve` / `/launch-confirm`.** The orchestrator
  reflects state but does not initiate spec or launch sign-off.

## Failure modes

- **Postgres unreachable** — CLI exits with driver error; operator must
  resolve before any phase decision can be made.
- **Missing tables** (early v0.1) — phase falls back to
  `v0.1-launch-readiness` with explanatory `reason`; gate grid renders
  all PENDING.
- **Bad subcommand** — exit code 4 with helpful message.

## Reference

- v3 spec: `docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md`
  Section 5.4 (slash commands), Section 7 (launch gates), Section 8.1
  (v0.5+ activation triggers).
- Module: `src/orchestrator/` (phase_detector, v01_launch_status,
  v01_active_routing, operator_briefing, cli).
- Companion commands: `/audit-trail`, `/alerts`, `/ack`, `/system-health`,
  `/disposition`, `/research-company`, `/parameters-review`, `/premortem`,
  `/spec-approve`, `/launch-confirm`.
