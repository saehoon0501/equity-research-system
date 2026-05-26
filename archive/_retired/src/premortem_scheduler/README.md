# premortem_scheduler

Pre-mortem cadence + event triggers per v3 spec Section 4.5 Q4
(`docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md`,
lines 514-528). Companion module to `anchor_drift/`.

## Calendar floor

| Mode | Floor |
|---|---|
| B | 180 days |
| B' | 120 days |
| C | 60 days |

`cadence.py` reads `MAX(premortem.premortem_date)` per ticker; new
names with no prior session are due immediately.

## Event triggers (force pre-mortem regardless of calendar)

| # | Trigger | Source signal |
|---|---|---|
| 1 | Thesis-confirmation event | calibration_events.event_type='thesis_confirmation' (auto-schedule within 7 days) |
| 2 | Consecutive M-2 events same name within 30 days | materiality_events tier='M-2' count >= 2 in window |
| 3 | First auto-tighten threshold crossed | drawdown vs benchmark >= mode-paired pp (B/SPY 5, B'/QQQ 7, C/IWO 10) |
| 4 | Mode reclassification proposed | mode_classifications.recheck_status='pending_review' — MANDATORY before commit (`blocking=True`) |

`scheduler.due = OR(calendar_floor, t1, t2, t3, t4)`. When `t4` fires
the result is marked `blocking=True` so the commit pipeline refuses to
advance until a `premortem` row is recorded.

## Devil's-advocate (LLM)

`devils_advocate.py` calls **Claude Opus** (`claude-opus-4-7`) per the
spec's "Opus required for high-stakes contestable judgment" rule
(Phase 4). Generates exactly 3 plausible failure modes, forced JSON
output. Schema:

```json
{
  "failure_modes": [
    {
      "mode": "...",
      "mechanism": "...",
      "leading_indicator": "...",
      "probability_estimate": 0.0,
      "kill_criterion_proposal": "..."
    }
  ]
}
```

Operator accepts/rejects each with rationale; counts roll up into
`llm_assist_metadata.operator_accepted_count` / `operator_rejected_count`
on the `premortem` row.

## CLI

```bash
# Bulk daily check
python -m premortem_scheduler.cli schedule-check
python -m premortem_scheduler.cli schedule-check --due-only

# One ticker
python -m premortem_scheduler.cli schedule-check --ticker NVDA --mode B_prime

# Record a completed session
python -m premortem_scheduler.cli record --ticker NVDA \
    --trigger calendar_floor --mode B_prime --input session.json
```

## Storage

One row per session into `premortem` (`012_v3_premortem.sql`,
append-only). Operator-authored JSONB blobs are HMAC-signed (using the
shared `WATCHLIST_HMAC_SECRET`) and the signature stored inside
`llm_assist_metadata.payload_hmac`.

## Integration with `anchor_drift`

- Anchor-drift Channel 1 (pillar drift) trigger frequently coincides
  with consecutive M-2 events — Trigger 2 here will fire pre-mortem
  when both surface together.
- Anchor-drift forced_review and pre-mortem are separate ledgers; the
  operator UI surfaces both side-by-side when a name has a triggered
  drift channel + a due pre-mortem.
- Mode reclassification (Phase 4 Q5 in `mode_classifier.recheck`)
  writes `recheck_status='pending_review'`; Trigger 4 here gates the
  commit until a premortem row exists.

## NOT implemented here

- Push alert delivery (Wave C).
- Counterfactual veto (Wave C).
- Mode reclassification logic itself (`mode_classifier.recheck`).
