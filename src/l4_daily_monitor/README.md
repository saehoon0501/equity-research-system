# L4 / P8 — Daily Monitor

Critical-path component for v0.1 per `docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md` Section 4.5 (lines 458-512).

The daily monitor is the **slow-loop heartbeat**: once per trading day per watchlist ticker we sweep the world for events, classify materiality (M-1 / M-2 / M-3) with an LLM judge, route the verdict to the appropriate downstream agents, and evaluate the mode-tuned cut thresholds.

## Pipeline

```
event_ingestor          (1) pull events for (ticker, date)
  -> materiality_classifier (2) Sonnet judge -> M-{1,2,3}; Opus on M-3
    -> router               (3) hybrid floor + LLM agent picker
      -> cut_evaluator      (4) Section 4.5 Q3 mode-tuned cut thresholds
        -> refresh_emitter  (5) write daily_refresh_log + materiality_events
                                + unread_alerts (M-2/M-3 only)
```

Quarterly: `drift_detector` runs Phase 4 Q8 against a rolling 30-event operator gold standard.

## Module layout

| File | Purpose |
|---|---|
| `__init__.py` | Constants: model ids, agent table, materiality int↔label map |
| `event_ingestor.py` | Pull events per (ticker, date) across 7 source classes |
| `materiality_classifier.py` | LLM judge — Sonnet default, Opus M-3 escalation |
| `router.py` | Section 4.5 Q2 hybrid floor + agent picker |
| `cut_evaluator.py` | Section 4.5 Q3 mode-tuned cut thresholds (B / B' / C) |
| `refresh_emitter.py` | Orchestrates pipeline + persists 3 tables |
| `drift_detector.py` | Phase 4 Q8 quarterly drift watch (Cohen's kappa + P50/P90) |
| `cli.py` | `python -m l4_daily_monitor.cli refresh \| drift-check` |

## Model constraint (operator-locked)

Per Section 4.5: **Sonnet or Opus only. NO Haiku.**

- M-1 / M-2 classification: `claude-sonnet-4-6`
- M-3 escalation re-validation: `claude-opus-4-7`
- M-2 agent picker: `claude-sonnet-4-6`

## Materiality routing (Section 4.5 Q2)

| Tier | Action | LLM-judge role |
|---|---|---|
| M-1 | No-op, log only | None |
| M-2 | P4 partial re-underwrite; LLM picks 2-4 of 5 agents | Bounded selection; falls back to event-type lookup if confidence < 0.6 |
| M-3 | P4 full 5-agent re-underwrite + operator alert | Cannot downgrade |

### Event-type → agent fallback table

| Event class | Default agents |
|---|---|
| Earnings call / EPS surprise | Quality + Growth |
| Macro print | Macro-Regime + Value |
| Smart-money signal (13F/13G/13D) | Quality + Quant-Technical |
| Sector rotation / peer move | Macro-Regime + Quant-Technical |
| Regulatory / litigation | Quality + Value |
| Product / capex / M&A | Growth + Value |
| Credit-event / spread blowout | Macro-Regime + Value |

## Cut thresholds (Section 4.5 Q3)

| Mode | Cut conditions |
|---|---|
| **B (steady)** | (i) ≥2 kill-criteria fired OR (ii) thesis-defining moat erosion verbatim-confirmed OR (iii) drawdown vs S&P > 10pp ≥3 quarters |
| **B' (growth)** | (i) ≥1 thesis-defining kill-criterion fired OR (ii) growth-rate inflection > -50% YoY 2 consec quarters OR (iii) drawdown vs QQQ > 12pp ≥2 quarters |
| **C (thematic)** | (i) any kill-criterion fired OR (ii) BOCPD against thesis > 0.7 OR (iii) drawdown vs IWO/ARKK > 15pp ≥1 quarter OR (iv) smart-money exit signal verified |

## Drift detection cadence

Per Section 6.2 + Phase 4 Q8: **quarterly** with a rolling 30-event gold standard re-rated by the operator. Hard floors:
- Sample size N ≥ 30 (DB CHECK).
- Cohen's kappa ≥ 0.61 (Section 7.2 launch gate).
- Confidence-distribution P50/P90 shifts > 0.1 → flag.
- 2 consecutive quarters below floor → fires M-2 system event.

## CLI

```bash
# Daily refresh — full watchlist
python -m l4_daily_monitor.cli refresh --date 2026-04-30

# Single ticker
python -m l4_daily_monitor.cli refresh --date 2026-04-30 --ticker NVDA

# Dry run (no DB writes)
python -m l4_daily_monitor.cli refresh --date 2026-04-30 --ticker NVDA --dry-run

# Quarterly drift check
python -m l4_daily_monitor.cli drift-check --period 2026-Q4 \
    --gold-standard-json gold_2026q4.json
```

## Persistence

Writes to three tables (migrations 009, 010):
- `daily_refresh_log` — append-only; one row per (ticker, date)
- `materiality_events` — append-only; one row per LLM-classified event
- `unread_alerts` — STATE table; M-2/M-3 only
- `materiality_classifier_drift` — append-only; quarterly drift rows

## Audit-trail discipline (Section 6 Q1)

Every M-2/M-3 verdict carries a **verbatim quote** that is a substring of the event's `raw_text`. The classifier rejects (downgrade to M-1 + flag) any verdict that fails the substring check. This is non-negotiable: without verbatim citations the system cannot defend its fires in `/parameters-review`.

## v0.5+ deferrals

Out-of-scope here (handled by separate Wave B/C subagents):
- Anchor-drift detection (Section 4.5 Q5 — separate module)
- Pre-mortem scheduler (Section 4.5 Q4)
- Counterfactual veto (Section 4.5 Q6)
- Push-alert delivery channels (email + Claude Code session push)
