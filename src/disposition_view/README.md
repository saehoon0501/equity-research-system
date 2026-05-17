# disposition_view — multi-horizon disposition + mode-fit dashboard

Per v3 spec sections:
- **Section 4.6 Q2** — Multi-horizon disposition view (Short / Mid / Long, mode-anchored primary expanded)
- **Section 5.4** — `/disposition` slash command
- **Phase 4 Q5** — Mode-fit dashboard (per-name mode vs realized 252d vol, last confirmed date, flag status)

## Module layout

```
src/disposition_view/
  __init__.py             — public re-exports
  loader.py               — Postgres query layer (read-only); DispositionRow + ModeFitRow
  horizon_signals.py      — derive Short / Mid / Long signals + key_signal text
  mode_fit_dashboard.py   — Phase 4 Q5 flag-status derivation
  renderer.py             — markdown renderers (multi-horizon table + per-row detail + dashboard)
  cli.py                  — `python -m src.disposition_view.cli` entry point
  postgres_view.sql       — `current_disposition` rollup view
  README.md               — this file
```

The `/disposition` slash command lives at `.claude/commands/disposition.md` and shells out to the CLI.

## Usage

Render full watchlist view:

```bash
python -m src.disposition_view.cli render
```

Filter to one mode:

```bash
python -m src.disposition_view.cli render --mode B_prime
```

Single-ticker drill:

```bash
python -m src.disposition_view.cli render --ticker NVDA
```

Override primary horizon for one name:

```bash
python -m src.disposition_view.cli render --toggle-primary NVDA short
```

## Design choices

### Markdown over a TUI library

The output target is the Claude Code session display + plain terminals. Both render Markdown — including pipe tables and `<details>/<summary>` collapsible blocks — natively. No third-party TUI library required (matches `src/audit_trail/` discipline).

### Mode → primary horizon

Mapping locked per Section 4.6 Q2:

| Mode | Primary horizon | Why |
|---|---|---|
| B   | Long  | Compounding metrics + secular trend + strategic |
| B'  | Mid   | Thesis-pillar tracking + earnings cycles + positioning |
| C   | Short | Catalyst-driven + near-term price action + tactical |

Operator can override per name with `--toggle-primary <T> <horizon>` (event windows, divergent thesis state, etc.).

**Override is session-only**: each `--toggle-primary` flag applies to a single CLI invocation only and is not persisted across runs. The CLI rejects duplicate ticker overrides in one invocation (exit code 4) — re-run with the desired override(s) each time. Persistent operator overrides (a `disposition_overrides` table keyed by `(operator_id, ticker)`) are deferred to v0.5+.

### Per-horizon signal derivation

`horizon_signals.py` derives `BUY / HOLD / TRIM / SELL` per horizon from the loaded sources:

- **Short** — materiality (M-3 → SELL, M-2 → TRIM), `last_refresh_action`, `near_term_catalysts` from `execution_context`.
- **Mid** — `recommendation` envelope (BUY/HOLD/TRIM/SELL) + `conviction_breakdown` (debate consensus, kills fired, counterfactual top-3) + sizing + fair-value.
- **Long** — `conviction_breakdown.drift_channels` (≥2 triggered → TRIM, NON-SURVIVOR + ≥2 triggered → SELL), `mode_certainty`, `regime_sensitivity`, `company_quality_flag`.

### Mode-fit flag precedence

Phase 4 Q5 flag types, most-severe first (`mode_fit_dashboard.derive_flag_status`):

1. `pending_reclassification` — `recheck_status = reclassification_proposed`
2. `rule_output_mismatch` — `recheck_status = pending_review`
3. `vol_band_inconsistency` — `mode_vol_checks.flagged = true`
4. `OK` — within band + last classification confirmed

Mirrored in SQL `flag_status` column on `current_disposition` view.

### Postgres view

`postgres_view.sql` materializes `current_disposition` — one row per watchlist name with all joins denormalized (latest recommendation, latest refresh, latest classification + last-confirmed, latest vol-check, aggregated positions, derived `flag_status` and `primary_horizon`). Read-only view; no maintenance / refresh job. Apply once with:

```bash
PGPASSWORD=... psql -h 127.0.0.1 -p 5432 -U equity_research_admin -d equity_research \
  -v ON_ERROR_STOP=1 -f src/disposition_view/postgres_view.sql
```

## What this module does NOT do

Per task scope (and v3 spec):

- **No web UI** — deferred to v0.5+.
- **No writes** — read-only against existing tables.
- **No reclassification commit** — `flag_status = pending_reclassification` surfaces the state; commit flows through `/quarterly-reunderwrite` + Section 6 Q4 pre-mortem.
- **No alert routing** — `/disposition` is a steady-state operator surface; alerts route through `/alerts` + the Section 5.3 push-alert pipeline.

## Tests

Smoke tests in `tests/test_disposition_view.py` — uses a hand-rolled fake Postgres connection (no live DB required). Verifies:

- Loader returns one DispositionRow per watchlist name.
- Mode → primary horizon mapping (B → long, B' → mid, C → short).
- Manual primary override.
- Per-horizon signal derivation (BUY / HOLD / TRIM / SELL routing).
- Mode-fit flag status precedence (pending_reclassification > rule_output_mismatch > vol_band_inconsistency > OK).
- Renderer emits the Section 4.6 Q2 schema (`primary_horizon`, `detail_expanded_by_default`, `detail_collapsed_by_default`).
- Mode filter (`--mode B`) and ticker filter (`--ticker NVDA`).

Run with `pytest tests/test_disposition_view.py`.

## Dependencies

Stdlib only (`json`, `argparse`, `dataclasses`, `uuid`, `datetime`).

The CLI optionally imports `psycopg` (v3) or `psycopg2` to open a real Postgres connection; both are optional at module level so the renderer/loader/derivation are unit-testable without a driver.
