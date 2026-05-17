# src/orchestrator

Master orchestrator for the equity-research system. Backs the `/run` slash
command per v3 spec Section 5.4.

## What it does

`/run` is the single entry point. It reads database state, auto-detects the
current operating phase, and renders an operator briefing covering:

- Current phase (`v0.1-launch-readiness` / `v0.1-active` / `v0.5-active` /
  `v1.0-active`) and the inputs that drove the decision
- For `v0.1-launch-readiness`: the full Section 7 launch-gate status grid
  (hard gates, calibration gates, operator sign-off, 10 walkthroughs)
- For `v0.1-active+`: the cadence actions due today
  (daily / mode-tuned / quarterly / annual)
- Pending operator decisions (anchor-drift forced reviews,
  counterfactual-veto overrides, mode reclassification proposals)
- Unread alert summary (links to `/alerts`)
- System health summary (links to `/system-health`)

**Render-only.** The orchestrator does NOT execute trades, auto-run
sub-commands, or modify state. The operator triggers each downstream
slash command manually after reading the briefing.

## Phase detection (no operator config)

Phase is inferred from observable Postgres state — never from an
operator-set flag.

| Phase | Trigger |
|---|---|
| `v0.1-launch-readiness` | `launch_readiness_log` not signed off / not all gates green |
| `v0.1-active` | launch signed off; `< 50` resolved predictions and `< 540` days since launch |
| `v0.5-active` | `≥ 50` resolved predictions OR `≥ 540` days since launch (Section 8.1) |
| `v1.0-active` | `parameters_active` shows `real_money_execution = LIVE` |

Detection is defensive: missing tables (e.g., during early v0.1 builds)
default the phase to `v0.1-launch-readiness` rather than raising.

## Modules

| File | Purpose |
|---|---|
| `phase_detector.py` | `detect_phase(conn)` → `PhaseSnapshot` |
| `v01_launch_status.py` | `collect_launch_gates(conn)` + grid renderer |
| `v01_active_routing.py` | `collect_scheduled_actions(conn)` + cadence renderer |
| `operator_briefing.py` | Top-level briefing assembly |
| `cli.py` | `python -m src.orchestrator.cli ...` |

## CLI

```
python -m src.orchestrator.cli              # full briefing
python -m src.orchestrator.cli status       # phase status only
python -m src.orchestrator.cli launch-gates # Section 7 gate grid
python -m src.orchestrator.cli today        # today's cadence actions
```

Connection wiring matches `src/audit_trail/cli.py`: reads `DATABASE_URL`
or `POSTGRES_*` env vars; tries `psycopg` (v3) then `psycopg2`.

## What it does NOT do

- Does not auto-execute sub-commands. Briefing surfaces work; operator
  initiates each manually.
- Does not modify migrations or write to any v0.1 table directly.
- Does not bypass the `/launch-confirm` gate flow — operator records gate
  PASS via `/launch-confirm <gate_name>` which writes
  `launch_readiness_log`.
- Does not poll calibration thresholds before activation. Section 8.1
  v0.5+ activation is reflected only when the database hits the trigger
  conditions.
