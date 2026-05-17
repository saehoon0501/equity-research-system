---
description: Surface the layered drill-down audit for an execution recommendation. Top-level decision_path first; per-stage drill on demand; HMAC chain verification surfaces tamper-evidence as M-2 system event. Per v3 spec Section 5.2 + 5.4 + Section 7 Q4 lock.
argument-hint: <rec_id | ticker> [--stage <stage>] [--latest] [--verify]
---

# /audit-trail

Operator-facing audit drill-down per v3 Section 5.2 (Audit-mode UX). Renders the layered decision-path with `drill_link` per stage; verifies the HMAC-signed audit chain on demand.

## Arguments

`<rec_id | ticker>` — required. Either:
- a recommendation UUID (resolves directly), or
- a ticker symbol with `--latest` (resolves to that ticker's most recent recommendation).

Optional flags:
- `--stage <stage>` — drill into one stage. Allowed: `stage_1_mechanical`, `stage_2_debate`, `stage_3_kill_criteria`, `stage_4_counterfactual`, `materiality`.
- `--latest` — when the first argument is a ticker, resolve to its latest recommendation_id.
- `--verify` — render HMAC chain verification (signature + parent-pointer integrity).
- `--strict` — with `--verify`, fail when `AUDIT_HMAC_KEY` env var is unset (per Section 7 Q4 launch gate).

## Procedure

### 1. Pre-flight checks

- `mcp__postgres` connected (load-bearing — both `execution_recommendations` and `audit_provenance` live there).
- Either `psycopg` (v3) or `psycopg2` available in the Python environment running the CLI.
- For `--verify`: `AUDIT_HMAC_KEY` env var present (or proceed in unkeyed mode if `--strict` is not set).

### 2. Invoke the renderer

The slash command shells out to the Python module via Bash. Use the existing CLI:

```bash
python -m src.audit_trail.cli <rec_id> [--stage <stage>] [--latest <ticker>] [--verify]
```

The CLI prints terminal-rendered Markdown directly. Render the output as-is to the operator.

Exit code mapping:
- `0` — success
- `2` — lookup error (rec_id / ticker / stage not found)
- `3` — HMAC chain verification surfaced tamper-evidence — flag as M-2 system event per v3 Section 5.3 push-alert pipeline
- `4` — bad arguments
- `5` — environment / driver missing

### 3. Layered drill-down UX (Section 5.2)

**Default invocation** (`/audit-trail <rec_id>`) — renders the top-level summary:
- ticker, recommendation, conviction, date
- decision_path: one row per stage with one-line outcome + `drill_link` command
- versions: rule_engine, debate_prompt, model, parameters

The decision_path table includes a `Drill` column showing the exact slash-command invocation to drill into that stage. Operator clicks-through (or copies) to drill.

**Per-stage drill** (`/audit-trail <rec_id> --stage <stage>`) — renders the full audit_provenance row:
- Verbatim quotes (where present in payload)
- Agent outputs / iteration log (debate stage)
- Retrieval results (counterfactual stage)
- Kill-criteria evaluation chain (kill_criteria stage)
- Versions, parent_audit_id, hmac_signature (truncated)

**Latest by ticker** (`/audit-trail <ticker> --latest`) — resolves to the most recent recommendation_id by (date DESC, created_at DESC), then proceeds as above.

**HMAC verification** (`/audit-trail <rec_id> --verify`) — verifies:
- Each row's HMAC-SHA256 signature against canonical JSON payload
- `parent_audit_id` points to a prior row in the chain with `created_at` ≤ child

If any row fails verification: surface `TAMPER-EVIDENT` banner; flag as M-2 system event. Operator should `/ack` the alert and investigate. Per Section 7 Q4 launch gate, end-to-end chain validation is a hard gate.

### 4. Examples

Top-level summary for a known UUID:
```
/audit-trail 8f2e1234-aaaa-bbbb-cccc-dddddddddddd
```

Latest audit for a ticker:
```
/audit-trail AAPL --latest
```

Drill into the debate stage:
```
/audit-trail 8f2e1234-aaaa-bbbb-cccc-dddddddddddd --stage stage_2_debate
```

Verify the chain:
```
/audit-trail 8f2e1234-aaaa-bbbb-cccc-dddddddddddd --verify
```

Strict verify (CI / launch gate):
```
/audit-trail 8f2e1234-aaaa-bbbb-cccc-dddddddddddd --verify --strict
```

## What `/audit-trail` does NOT do

- **No replay.** Per v3 Section 7 Q4 PB on replay — replay capability is deferred to `/backtest` (which has its own walk-forward + embargo machinery). The operator can read the full audit, but cannot re-execute the decision through this command.
- **No web UI.** v0.1 surface is terminal-rendered only. Web UI is deferred to v0.5+.
- **No writes.** `audit_provenance` rows are append-only (enforced by Postgres trigger in migration 008). The recommendation emitter writes them; this command only renders.
- **No auto-acknowledge of tamper-evidence.** When `--verify` returns FAIL, the operator must explicitly investigate and decide on remediation. The system flags M-2 but does not silently proceed.

## Failure modes

- **Postgres unreachable** — CLI exits with driver error; halt and report.
- **rec_id / ticker not found** — exit code 2; surface a helpful "no such recommendation" message.
- **stage missing for that rec** — some stages may not have run (e.g., kill_criteria not fired); the top-level summary shows `_no row recorded_` and the drill command for that stage exits with `LookupError`.
- **HMAC key missing without --strict** — verification falls back to chain-pointer-only mode and clearly labels the result as `UNVERIFIED`.
- **HMAC signature mismatch** — render TAMPER-EVIDENT banner; exit code 3; caller should escalate to M-2.

## Reference

- v3 spec: `docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md` Section 5.2 (Audit-mode UX), Section 5.4 (slash commands), Section 7 Q4 (layered drill-down lock), Section 7.1 (HMAC chain validates end-to-end launch gate).
- Schema: `db/migrations/008_v3_recommendations.sql` (audit_provenance + execution_recommendations).
- Module: `src/audit_trail/` (renderer.py, loader.py, hmac_verify.py, cli.py).
