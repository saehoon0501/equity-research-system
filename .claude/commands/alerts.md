---
description: List unacknowledged push alerts (M-2 + M-3) from the unread_alerts queue. Supports filtering by severity, ticker, type, or since-timestamp. Per v3 Section 5.3 + 5.4.
argument-hint: [--severity 2|3] [--ticker TKR] [--type ALERT_TYPE] [--since ISO_TS]
---

# /alerts

On-demand review of the push-alert backlog per v3 Section 5.3 (Push alerts — multi-channel) and Section 5.4 (slash commands). The same rows surface automatically at Claude Code session start; this command is for ad-hoc review during a session.

## Arguments

All optional. Filters compose (AND).

- `--severity <2|3>` — restrict to one severity. M-3 = act; M-2 = watch.
- `--ticker <TKR>` — single-ticker filter.
- `--type <ALERT_TYPE>` — one of the closed enum values from `unread_alerts.alert_type` (e.g., `materiality_m3`, `counterfactual_veto`, `anchor_drift`, `kill_criterion`, `mode_reclass`, `drawdown_2x_threshold`, `materiality_m2`, `calibration_drift`, `system_error`).
- `--since <ISO_TS>` — only alerts `created_at >= <ts>` (UTC ISO-8601).

## Procedure

### 1. Pre-flight

- `mcp__postgres` connected.
- Either `psycopg` (v3) or `psycopg2` available in the Python environment.

### 2. Invoke the renderer

```bash
python -m src.alert_channels.cli list \
    [--severity 2|3] [--ticker TKR] [--type T] [--since ISO]
```

The CLI prints terminal-rendered Markdown directly. Render the output as-is to the operator.

### 3. Acknowledge follow-ups

Each alert listing carries the `alert_id` UUID and (when applicable) a `drill: /audit-trail <rec_id>` deep-link. Operator should:
- Investigate the M-3 entries first (highest severity).
- For each addressed alert, run `/ack <alert_id>` (or `/ack all` once everything has been triaged).
- For drill-down on the underlying recommendation, use the surfaced `/audit-trail` command.

## Default ordering

Severity DESC, then `created_at` DESC. Newest M-3 first; oldest acknowledged-pending M-2 last.

## What `/alerts` does NOT do

- **No acknowledgement.** Listing is read-only — must invoke `/ack` separately.
- **No deletion.** `unread_alerts` is a state table; rows are never deleted (per migration 009 trigger).
- **No notification dispatch.** Email + Claude Code session push are owned by `process-email-queue` and `surface-session` respectively.

## Reference

- v3 spec: `docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md` Section 5.3 (Push alerts), Section 5.4 (slash commands), Section 7 PB#4 (multi-channel architecture).
- Schema: `db/migrations/009_v3_daily_monitor.sql` + `017_v3_alert_type_extension.sql`.
- Module: `src/alert_channels/` (session_push.py, cli.py).
