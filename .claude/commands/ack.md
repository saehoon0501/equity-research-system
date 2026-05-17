---
description: Acknowledge one or all unread push alerts. Updates unread_alerts.acknowledged_at; idempotent. Per v3 Section 5.3 + 5.4.
argument-hint: <alert_id | all>
---

# /ack

Operator acknowledgement of a push alert per v3 Section 5.3 (Push alerts) and Section 5.4 (slash commands).

Acknowledgement is the one-way state transition that removes an alert from the active backlog: it stops surfacing in `/alerts`, in the next Claude Code session-start push, and out of the `/system-health` "active push-alert backlog" counter. The row itself is preserved (state table; no DELETEs allowed).

## Arguments

`<alert_id | all>` — required.
- `<alert_id>` — UUID; acknowledge a single alert.
- `all` — acknowledge every currently-unacknowledged alert in one call.

## Procedure

### 1. Pre-flight

- `mcp__postgres` connected.
- Either `psycopg` or `psycopg2` available.

### 2. Invoke

```bash
# Single alert:
python -m src.alert_channels.cli ack <alert_id>

# Bulk:
python -m src.alert_channels.cli ack-all
```

The CLI prints a one-line result (e.g., `Acknowledged 8f2e1234-...` or `Acknowledged 7 alert(s)`).

Exit code mapping:
- `0` — success
- `2` — no unacknowledged alert with that id (idempotent: re-ack returns 2)
- `4` — bad arguments (e.g., not a valid UUID)

### 3. Examples

```
/ack 8f2e1234-aaaa-bbbb-cccc-dddddddddddd
/ack all
```

## Idempotency

Re-running `/ack <alert_id>` on an already-acknowledged alert returns exit 2 with a "no unacknowledged alert" message — it does NOT overwrite `acknowledged_at`. Initial-acknowledgement timestamp is preserved.

## What `/ack` does NOT do

- **No deletion.** `unread_alerts` rows persist; only `acknowledged_at` and `acknowledged_by` flip.
- **No alert resolution.** Acknowledgement clears the operator-attention queue; the underlying issue (e.g., a fired kill-criterion) still requires a separate workflow (`/audit-trail`, `/quarterly-reunderwrite`, etc.).
- **No system-error resolution.** A `system_error`-type alert acked here still has its `system_errors` row open (`resolved_at IS NULL`). Closure of that requires updating `system_errors.resolution + resolved_at` directly via the operations runbook.

## Reference

- v3 spec: `docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md` Section 5.3 (Push alerts — operator acknowledges), Section 5.4 (`/ack <alert_id>` / `/ack all`).
- Schema: `db/migrations/009_v3_daily_monitor.sql` (acknowledged_at + acknowledged_by columns; mutable per state-guard trigger).
- Module: `src/alert_channels/` (session_push.acknowledge / acknowledge_all).
