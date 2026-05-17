---
description: Multi-horizon disposition view (Short ≤3mo / Mid 3-12mo / Long 12+mo) with mode-anchored primary horizon expanded; integrated mode-fit dashboard (Phase 4 Q5). Per v3 spec Section 4.6 Q2 + 5.4.
argument-hint: [--ticker <T>] [--mode B|B_prime|C] [--toggle-primary <T> <horizon>]
---

# /disposition

Operator-facing multi-horizon disposition view per v3 Section 4.6 Q2. Renders one row per watchlist name with three horizon columns (Short ≤3mo, Mid 3-12mo, Long 12+mo); the mode-anchored primary horizon is highlighted and its detail expanded by default. Supplementary mode-fit dashboard (Phase 4 Q5) surfaces per-name mode-vs-realized-vol drift status.

## Arguments

All optional; default invocation renders the full watchlist view.

- `--ticker <T>` — render expanded detail for a single name only.
- `--mode <B|B_prime|C>` — filter to one mode bin.
- `--toggle-primary <T> <horizon>` — override the mode-anchored default primary horizon for a name. `horizon ∈ {short, mid, long}`. Repeatable.
  - **Override is session-only** — not persisted across CLI invocations. Re-run `--toggle-primary` each time you want a non-default primary horizon.
  - The same ticker may not appear in `--toggle-primary` twice in a single invocation (CLI exits with code 4). Persistent operator overrides are deferred to v0.5+ (would write to a new `disposition_overrides` table keyed by `(operator_id, ticker)`).

## Procedure

### 1. Pre-flight checks

- `mcp__postgres` connected (load-bearing — `watchlist`, `positions`, `execution_recommendations`, `daily_refresh_log`, `mode_classifications`, and `mode_vol_checks` all live there).
- Either `psycopg` (v3) or `psycopg2` available in the Python environment running the CLI.
- View `current_disposition` exists (one-shot rollup; created by `src/disposition_view/postgres_view.sql`).

### 2. Invoke the renderer

The slash command shells out to the Python module via Bash:

```bash
python -m src.disposition_view.cli render
python -m src.disposition_view.cli render --ticker NVDA
python -m src.disposition_view.cli render --mode B_prime
python -m src.disposition_view.cli render --toggle-primary NVDA short
```

The CLI prints terminal-rendered Markdown directly. Render the output as-is to the operator.

Exit code mapping:
- `0` — success
- `2` — lookup error (ticker not in watchlist)
- `4` — bad arguments
- `5` — environment / driver missing

### 3. Disposition view UX (Section 4.6 Q2)

**Default invocation** (`/disposition`) — one row per watchlist name. Schema per name (Section 4.6 Q2):

```yaml
disposition_row:
  ticker: NVDA
  mode: B'
  primary_horizon: mid
  short_horizon: { signal, key_signal, detail_collapsed_by_default: true }
  mid_horizon:   { signal, key_signal, detail_expanded_by_default: true }   # PRIMARY
  long_horizon:  { signal, key_signal, detail_collapsed_by_default: true }
```

Mode → primary horizon mapping:
- **Mode B** → Long primary (compounding metrics + secular trend + strategic)
- **Mode B'** → Mid primary (thesis-pillar tracking + earnings cycles + positioning)
- **Mode C** → Short primary (catalyst-driven + near-term price action + tactical)

Primary horizon is marked with `*` in the table and rendered with detail expanded inline. Secondary horizons collapse inside `<details>` blocks the operator can expand.

**Manual primary toggle** (`--toggle-primary NVDA short`) — overrides the mode-anchored default for one name. Useful when the operator wants short-horizon scrutiny on a B-mode name during an event window. **Session-only**: the override applies only to this invocation; rerun the flag next time. Duplicate overrides for the same ticker in one invocation are rejected (exit 4).

**Per-ticker drill** (`--ticker NVDA`) — renders the single-name expanded view with all three horizons inline + integrated mode-fit dashboard for that name.

### 4. Mode-fit dashboard (Phase 4 Q5)

A supplementary section renders per-name `mode | realized_252d_vol | mode_band | last_confirmed_date | flag_status`.

Flag types:
- `pending_reclassification` — quarterly re-classification proposed; awaiting Section 6 Q4 pre-mortem and operator commit.
- `rule_output_mismatch` — quarterly rule classifier disagrees with stored mode; awaiting operator review.
- `vol_band_inconsistency` — realized 252d vol outside mode band for ≥2 consecutive semi-annual checks.
- `OK` — within band, last classification confirmed.

### 5. Examples

Full watchlist view:
```
/disposition
```

Filter to B-mode names only:
```
/disposition --mode B
```

Single-name detail:
```
/disposition --ticker NVDA
```

Override primary horizon for one name (event window):
```
/disposition --toggle-primary NVDA short
```

## What `/disposition` does NOT do

- **No writes.** Reads from `watchlist`, `positions`, `execution_recommendations`, `daily_refresh_log`, `mode_classifications`, `mode_vol_checks`. Recommendation emission happens in P5/P9 (Section 4.6).
- **No web UI.** v0.1 surface is terminal-rendered only. Web UI is deferred to v0.5+ per Section 5.4.
- **No reclassification trigger.** When `flag_status = pending_reclassification`, the dashboard surfaces the state — the actual reclassification commit goes through `/quarterly-reunderwrite` and Section 6 Q4 pre-mortem.

## Failure modes

- **Postgres unreachable** — CLI exits with driver error; halt and report.
- **ticker not in watchlist** — exit code 2; surface a helpful "no such ticker" message.
- **No watchlist names match filter** — empty section rendered with explanatory note.

## Reference

- v3 spec: `docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md` Section 4.6 Q2 (multi-horizon disposition view), Section 2.2 (mode silent-failure detection — Phase 4 Q5), Section 5.4 (slash commands).
- Schema: `db/migrations/007_v3_watchlist_positions.sql`, `008_v3_recommendations.sql`, `009_v3_daily_monitor.sql`, `010_v3_drift_detection.sql`.
- View: `src/disposition_view/postgres_view.sql` (`current_disposition`).
- Module: `src/disposition_view/` (loader.py, horizon_signals.py, mode_fit_dashboard.py, renderer.py, cli.py).
