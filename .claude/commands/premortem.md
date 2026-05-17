---
description: Trigger or surface a pre-mortem session per v3 §4.5 Q4 — mode-tuned cadence (B 180d / B' 120d / C 60d) + 4 event triggers (thesis-confirmation, consecutive M-2, auto-tighten threshold, mode reclass). LLM devil's-advocate (Opus) generates 3 plausible failure modes operator may have missed.
argument-hint: <ticker> [--mode B|B_prime|C] [--check] [--record --input <session.json>] [--trigger <name>]
---

# /premortem

Operator-facing pre-mortem entry point per v3 spec Section 4.5 Q4 + Section 5.4. Two modes:

1. **Schedule-check** (default with `--check`): query whether a pre-mortem is currently due for the ticker. Surfaces cadence + each event trigger.
2. **Record** (with `--record --input <session.json>`): persist a completed pre-mortem session to the `premortem` table with HMAC signature.

This wraps the existing `src.premortem_scheduler.cli` module — see its docstring for the full session-JSON contract.

## Arguments

`<ticker>` — required.

Optional flags:
- `--mode <B|B_prime|C>` — required when `<ticker>` is provided alone (no DB lookup at v0.1 from the CLI surface).
- `--check` — schedule-check mode (default if no `--record`).
- `--record` — record-completion mode; requires `--trigger` + `--input`.
- `--trigger <name>` — one of `calendar_floor`, `thesis_confirmation`, `consecutive_m2`, `auto_tighten`, `mode_reclass`. Required with `--record`.
- `--input <session.json>` — path to JSON session file. Required with `--record`.
- `--no-persist` — dry-run record (computes HMAC but skips DB write).
- `--as-of <ISO>` — override "now" for cadence checks (testing).

## Procedure

### 1. Pre-flight checks

- `mcp__postgres` connected (load-bearing for record mode; `premortem` table lives there).
- `psycopg` (v3) or `psycopg2` available in the CLI environment.
- `PREMORTEM_HMAC_SECRET` env var set when recording (canonical-payload contract from `src/audit_trail/hmac_verify.py`).

### 2. Schedule-check mode

Wraps `python -m src.premortem_scheduler.cli schedule-check --ticker <T> --mode <M>`. Returns JSON with cadence due-date, each event-trigger result, and a `due` boolean.

```bash
/premortem NVDA --mode B_prime --check
```

### 3. Record mode

Wraps `python -m src.premortem_scheduler.cli record --ticker <T> --trigger <name> --mode <M> --input session.json`. Writes to `premortem` table with `PREMORTEM_HMAC_SECRET`-signed `hmac_signature` (migration 016 column).

`session.json` shape (per CLI docstring):
```json
{
  "operator_imagined_failure_modes": [...],
  "thesis_pillars_revisited":        [...],
  "net_thesis_strength":             0.62,
  "operator_accepted_count":         2,
  "operator_rejected_count":         1,
  "days_since_last_premortem":       128,
  "llm_assist": {
    "model": "claude-opus-4-7",
    "failure_modes": [...]
  }
}
```

### 4. LLM devil's-advocate role (Section 4.5 Q4)

When the operator wants the system to generate failure modes before the structured session, use:

```bash
python -m src.premortem_scheduler.devils_advocate --ticker <T> --mode <M>
```

Output: 3 plausible failure modes (Opus) the operator may have missed. Operator accepts/rejects each in the structured session; counts go in `operator_accepted_count` / `operator_rejected_count`.

### 5. Cadence floors (mode-tuned)

| Mode | Calendar floor |
|---|---|
| B  | 180 days |
| B' | 120 days |
| C  |  60 days |

### 6. Event triggers (force pre-mortem regardless of calendar)

1. Thesis-confirmation event — paradoxically dangerous moment.
2. Consecutive M-2 events on same name within 30 days.
3. First auto-tighten threshold crossed (B/S&P 5pp, B'/QQQ 7pp, C/IWO 10pp).
4. Mode reclassification proposed → mandatory before commit.

## Examples

Check whether NVDA is due:
```
/premortem NVDA --mode B_prime --check
```

Record a completed session:
```
/premortem NVDA --record --trigger calendar_floor --mode B_prime --input session.json
```

Dry-run record (HMAC + validation only, no DB write):
```
/premortem NVDA --record --trigger mode_reclass --mode B_prime --input session.json --no-persist
```

## What `/premortem` does NOT do

- **No automatic LLM session.** The `--check` flag returns due-state only; the operator runs the structured session manually with the devil's-advocate output as a starting point.
- **No batch-mode across watchlist.** Use `python -m src.premortem_scheduler.cli schedule-check` (no `--ticker`) for full-watchlist cadence sweep.
- **No retroactive HMAC signing.** Once written, rows are append-only with their original signature.

## Failure modes

- **Postgres unreachable** — record mode exits with driver error; `--no-persist` is the workaround for offline validation.
- **Invalid trigger value** — exit code 3 (validation error) with allowed set listed.
- **Bad JSON in `--input`** — exit code 1 (IO error) with the specific parse fault.
- **`PREMORTEM_HMAC_SECRET` unset on record** — recorder logs a warning and proceeds with empty HMAC (M-2 system event when verifier later detects).

## Reference

- v3 spec: `docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md` Section 4.5 Q4 (cadence + triggers), Section 5.4 (slash commands), Section 6 Q4 (LLM devil's-advocate role).
- Schema: `db/migrations/012_v3_premortem.sql`, `db/migrations/016_v3_hmac_columns.sql` (HMAC promotion).
- Module: `src/premortem_scheduler/` (cadence.py, event_triggers.py, scheduler.py, devils_advocate.py, recorder.py, hmac.py, cli.py).
