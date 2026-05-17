---
description: Unified system-health view — degraded MCPs, queued recoveries, disputed catalog entries, system_errors last 7 days, push-alert backlog. Per v3 Section 5.4 + Phase 4 Q9.
argument-hint: (no arguments)
---

# /system-health

Operator-facing observability surface per v3 Section 5.4 (slash commands) and Phase 4 Q9 (failure-mode defaults). Renders a single markdown block summarizing every degraded subsystem and queued recovery the operator should know about.

## Purpose

Single page of "what's broken / what's queued" so the operator has one place to check before invoking a downstream slash command (`/daily-monitor`, `/research-company`, etc.) that might be silently impaired.

## Sections rendered

1. **Degraded MCPs** — every `system_errors` source with at least one row where `resolved_at IS NULL`. Surfaces last-success timestamp per source.
2. **Queued recoveries**
   - Email queue depth — count of M-3 alerts pending email send (`email_sent_at IS NULL` AND `email_send_attempts < 3`).
   - Email queued-for-session-push — count of M-3 alerts that hit the retry cap and now ride the session-push channel only (Phase 4 Q9 final-failure path).
3. **Active push-alert backlog** — unread M-3 + unread M-2 counts.
4. **Disputed catalog entries** — peak-pain catalog rows excluded from retrieval (Section 6 hygiene). Shows count + ticker list. Returns 0 if the `peak_pain_catalog` table or `disputed` column hasn't yet been migrated.
5. **system_errors last 7 days** — count grouped by `source`, descending.

## Procedure

### 1. Pre-flight

- `mcp__postgres` connected.
- Either `psycopg` or `psycopg2` available.

### 2. Invoke

```bash
python -m src.alert_channels.cli system-health
```

The CLI prints terminal-rendered Markdown; render as-is.

Exit codes:
- `0` — success (regardless of how many degraded subsystems are surfaced — degraded ≠ command failure)
- `5` — driver missing

### 3. Triage flow

1. Read top to bottom.
2. For each degraded MCP: investigate the underlying error (`SELECT * FROM system_errors WHERE source = '<source>' AND resolved_at IS NULL ORDER BY timestamp_at DESC`).
3. For email queue depth >0: ensure `process-email-queue` is wired into cron (see `src/alert_channels/README.md`).
4. For queued-for-session-push >0: SMTP is confirmed broken; fix credentials or unblock the SMTP host before more M-3 events fire.
5. For unread M-3 backlog >0: invoke `/alerts --severity 3` and triage.

## Idempotency / side effects

`/system-health` is **read-only**. It does not mutate any table — repeated invocation is purely informational. There is no automatic resolution of degraded states.

## Reference

- v3 spec: `docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md` Section 5.4 (slash commands), Section 7.5 (cold-start + error handling), Phase 4 Q9 (failure-mode defaults).
- Schema: `db/migrations/014_v3_system_health.sql` (system_errors), `db/migrations/009_v3_daily_monitor.sql` (unread_alerts).
- Module: `src/alert_channels/system_health.py`.
