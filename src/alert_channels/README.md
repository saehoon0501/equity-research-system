# alert_channels — multi-channel push-alert delivery

Per v3 spec sections:
- **Section 5.3** — Push alerts (multi-channel: email + Claude Code session push + `/alerts`)
- **Section 5.4** — Slash commands (`/alerts`, `/ack`, `/system-health`)
- **Section 7 PB#4** — Multi-channel architecture
- **Phase 4 Q9** — Failure-mode defaults (1m/5m/15m exponential retry; final-failure → session-push + system_errors logging)

## Module layout

```
src/alert_channels/
  __init__.py        — package constants (severity enum, retry schedule)
  email_sender.py    — SMTP one-shot send + system_errors logging
  session_push.py    — surface_unread_at_session_start + ack helpers + /alerts list
  queue_processor.py — daemon-style email-queue drain (1m/5m/15m backoff)
  system_health.py   — /system-health markdown body
  cli.py             — `python -m src.alert_channels.cli` entry point
  README.md          — this file
```

Slash-command markdown definitions live at `.claude/commands/alerts.md`,
`.claude/commands/ack.md`, and `.claude/commands/system-health.md` — they shell
out to the CLI subcommands here.

## Channel matrix

| Channel             | Triggers                            | Module                |
|---------------------|-------------------------------------|-----------------------|
| Email               | M-3 events only                     | `email_sender.py`     |
| Claude session push | Unread M-3 / M-2 since last session | `session_push.py`     |
| `/alerts`           | All current alerts (on-demand)      | `session_push.py` + CLI `list` |

## Operator setup — SMTP credentials

The email channel reads SMTP credentials from environment variables (loaded
from `.env` per the project convention). Add the following to `.env`:

```ini
# Push-alert email channel (alert_channels.email_sender)
ALERT_SMTP_HOST=smtp.gmail.com
ALERT_SMTP_PORT=587
ALERT_SMTP_USERNAME=your-account@gmail.com
ALERT_SMTP_PASSWORD=app-password-not-account-password
ALERT_SMTP_SENDER=your-account@gmail.com
ALERT_SMTP_RECIPIENT=operator@example.com
ALERT_SMTP_USE_TLS=1
```

Notes:
- For Gmail, use an **app password**, not the account password (Google
  blocks SMTP for "less secure apps"). Create one at
  https://myaccount.google.com/apppasswords.
- For non-Google providers, use SMTP submission port 587 with STARTTLS.
- `ALERT_SMTP_RECIPIENT` is the address that receives alerts. Single-operator
  v0.1 system per Section 5.5 — multi-recipient support deferred.

`SmtpConfig.from_env()` raises `RuntimeError` if any of the six required vars
is missing. `/system-health` does **not** explicitly check SMTP config (no
network calls in the read-only `/system-health` body); operator should run a
manual test send (below) on first setup.

## Test procedure

### 1. Smoke test (no DB, no real SMTP — pytest)

```bash
pytest tests/test_alert_channels.py -v
```

Covers:
- Email-render layout (subject + plain + HTML).
- Email idempotency (re-send blocked when `email_sent_at` already set).
- Phase 4 Q9 retry timing (eligibility window math).
- Final-failure path logs to `system_errors` with the expected source.
- `acknowledge` / `acknowledge_all` mutate only allowed columns.
- `surface_unread_at_session_start` ordering (severity DESC, created_at DESC).
- `/system-health` markdown rendering (with stub query layer).

### 2. End-to-end test send (real SMTP)

After `.env` is wired:

```bash
# Insert a synthetic M-3 alert directly:
psql -d equity_research <<'SQL'
INSERT INTO unread_alerts (severity, alert_type, ticker, summary, payload)
VALUES (3, 'materiality_m3', 'TEST', 'SMTP smoke test', '{}'::jsonb)
RETURNING alert_id;
SQL

# Drain the email queue once:
python -m src.alert_channels.cli process-email-queue

# Verify the row was sent:
psql -d equity_research -c \
  "SELECT alert_id, email_sent_at, email_send_attempts \
   FROM unread_alerts WHERE ticker = 'TEST'"

# Acknowledge the test row:
python -m src.alert_channels.cli ack <alert_id>
```

Exit code `0` from `process-email-queue` indicates a successful send (no
transient or final failures). Exit code `6` means at least one row failed
(check `system_errors` for the error_detail).

### 3. Session-start push verification

```bash
python -m src.alert_channels.cli surface-session
```

Should render a markdown header listing every unacknowledged alert sorted
severity-then-recency, with `claude_session_pushed_at` updated for each row.

### 4. /system-health verification

```bash
python -m src.alert_channels.cli system-health
```

Renders five sections (degraded MCPs, queued recoveries, push-alert backlog,
disputed catalog, last-7d errors). Always returns exit 0 — the command is
read-only and "degraded subsystem" is not a CLI failure.

## Cron wiring (production)

Add to crontab (or systemd timer) to drain the email queue every minute:

```cron
* * * * * cd /path/to/equity-research-system && \
    python -m src.alert_channels.cli process-email-queue \
    >> /var/log/alert_channels.log 2>&1
```

Each invocation drains ready rows once and exits. Phase 4 Q9 backoffs (1m/5m/15m)
are enforced inside `queue_processor._is_eligible_now`; running every minute is
safe — rows in their backoff window are skipped.

## Failure modes

| Symptom                           | Where to look                                  |
|-----------------------------------|------------------------------------------------|
| No emails after M-3 alert fires   | `system_errors` rows with source = `alert_channels.email_sender`; `/system-health` queue depth |
| Session push not surfacing alerts | `acknowledged_at` not yet set?  Run `surface-session` manually to confirm |
| `/ack` returns exit 2             | Alert already acknowledged, or wrong UUID — check `SELECT alert_id, acknowledged_at FROM unread_alerts WHERE alert_id = '<id>'` |
| SMTP auth failure                 | Check `system_errors.error_detail` — likely wrong app-password or `ALERT_SMTP_USE_TLS` mismatch |
| Email queue keeps growing         | After `MAX_EMAIL_ATTEMPTS` (4) attempts the row converts to "queued for session push" and stops re-sending — check `email_send_attempts >= 4` count via `/system-health` |

## Reference

- v3 spec: `docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md`
- Migrations: `db/migrations/009_v3_daily_monitor.sql`, `014_v3_system_health.sql`, `017_v3_alert_type_extension.sql`
- Producer: `src/l4_daily_monitor/refresh_emitter.py` (writes `unread_alerts` rows that this package delivers)
- Audit trail: `src/audit_trail/` (drill-down deep-link target)
