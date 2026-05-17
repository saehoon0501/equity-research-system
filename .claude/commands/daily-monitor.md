---
description: Daily heartbeat of the slow layer. Sweeps news/filings for all watchlist names with two-tier classification (Sonnet default → Opus M-3 escalation). Surfaces materiality-3 escalations and produces a daily digest. Run post-market close + 30 min.
argument-hint: (no arguments — runs against full watchlist)
---

# /daily-monitor

The slow layer's daily heartbeat. Reads everything that touched watchlist names or sectors in the last 24 hours, classifies materiality, and produces a digest.

## Procedure

### 1. Pre-flight checks

- `mcp__market_data` connected for news
- `mcp__edgar` connected for filings (8-K, Form 4, 13F)
- `mcp__postgres` connected for Predictions DB and Evidence Index reads/writes
- Watchlist must exist (initially empty in v0.1; populated as v0.5 proceeds)

**HIGH-4 consensus 2026-05-16 (Consensus Item #2 — uniform monitoring):** the "watchlist" for `/daily-monitor` purposes is the set of every ticker that has at least one row in `counterfactual_ledger` (i.e., every ticker that ever completed a `/research-company` run and emitted a `summary_code`). Monitoring is uniform across `summary_code` value — BUY/HOLD/TRIM/SELL tickers all get the same daily sweep. There is no "drops off the watchlist" semantic; the prior 5-bin lifecycle (ADD/WATCH/HOLD/PASS/REJECT) is dissolved.

The discovery query for the daily sweep:

```sql
SELECT DISTINCT ticker
FROM counterfactual_ledger
WHERE ticker IS NOT NULL
  AND summary_code IS NOT NULL;
```

If the result is empty, report and exit. Otherwise, run the sweep against every distinct ticker returned.

### 2. Gather inputs

- News for all watchlist names (last 24h) via mcp__market_data
- 8-K and other filings (last 24h) via mcp__edgar
- Earnings/macro calendar for next 5 trading days
- Significant macro events (Fed actions, geopolitical, commodity shocks) last 24h
- Watchlist composition with current thesis pillars per name (from Postgres)

### 3. Tier 1 classification (Haiku)

Per `.claude/references/daily-monitor-tier-routing.md`:

For each item:
1. Read item
2. Cross-reference watchlist names + thesis pillars
3. Apply scoring (0/1/2/3) per the schema in tier routing reference
4. Write justification (mandatory, even for zeros)

Tier 1 outputs flow to a queue; items scoring ≥2 auto-escalate.

### 4. Tier 2 classification (Sonnet) for escalations

For each item with Tier 1 score ≥ 2:
1. Read item with full thesis pillars context
2. Confirm or correct Tier 1 score
3. If confirmed score ≥ 2: enrich with materiality classification details
4. If confirmed score 3: produce specific actionable recommendation

Tier 2 confirmation absorbs Tier 1 false-negative risk.

### 5. Cross-cutting observations

Beyond per-name scoring, look for sector-level patterns:
- Multiple names hit by same regulatory event
- Sector-wide macro impact
- Cross-position correlation alerts
- Thematic affirmations or contradictions across watchlist

### 6. Resolution job (predictions due today)

Per `.claude/references/prediction-resolution.md`:

- Query Postgres: predictions with resolution_date = today (or earlier if missed)
- For each due prediction:
  - Fetch actual outcome (revenue figures, prices, regime, etc.)
  - Compute Brier score for probabilistic predictions
  - Insert resolution record (NOT update prediction; predictions are append-only)
  - Update per-agent calibration history view
- Surface resolutions in daily digest

### 7. Compose daily digest

```
DAILY MONITOR — <date>

WATCHLIST POSITIONS: N names tracked

ESCALATIONS (Tier 2 confirmed):
[None] OR [List of materiality-3 events with name, item, recommendation]

DIGEST BY POSITION:
<TICKER> [score 0/1/2/3]: <one-line summary> — <justification>
<TICKER> [score 0]: no material activity
...

CROSS-CUTTING OBSERVATIONS:
- <observation 1>
- <observation 2>

PREDICTIONS RESOLVED TODAY:
- <prediction>: predicted X; actual Y; Brier = Z
- ...

CALIBRATION TRENDS (rolling 90-day):
- CompanyDeepDive: Brier <X>, trend <direction>
- PMSupervisor adversarial stress-test: Brier <X>, trend <direction>  # post 2026-05-12 replaces BearCase calibration line
- ...

UPCOMING (next 5 trading days):
- <ticker> earnings: <date>
- Fed decision: <date>
- ...

COST: $X (Tier 1 + Tier 2 combined for today)
RUNNING MONTHLY COST: $Y vs $400 budget
```

### 8. Score-3 escalation actions

For each materiality-3 confirmed by Tier 2:

1. Notify operator via the command output (highlighted prominently)
2. Suggest follow-up: `/quarterly-reunderwrite <ticker>` for full re-underwrite
3. Flag in `BUILD_LOG.md` (Notes section) when the operator decides on a follow-up action
4. Increment escalations count for the day

Operator decides whether to execute the re-underwrite immediately or schedule.

### 9. Persistence

Write to Postgres:
- Materiality scores for every item (with justifications)
- Resolution records for resolved predictions
- Counterfactual ledger updates if positions had material days

### 10. Cost tracking

Update running monthly cost. If projected to exceed $400 budget cap or already above $500 alert threshold, flag in output.

## Hard gate

Per `.claude/references/process-rubric.md` HG-6: every materiality score must have written justification, including zeros. The Evaluator will reject digests missing justifications.

## False positive / false negative discipline

Per v2-final §1.5 success criteria, tracked over time:
- Score-3 events: target >70% require thesis revision (false positive rate <30%)
- Score-0 events: target >95% don't require revision (false negative rate <5%)
- Tier 2 escalation accuracy

These are not v0.1 evaluation criteria (need accumulated outcome data); they become v0.5 phase gate criteria.

## v0.1 vs v0.5 cadence

- **v0.1**: optional, used for testing the digest pipeline
- **v0.5**: daily, post-market close + 30 min cron
- **v1.0**: daily, with LearningLoop activated for prompt evolution
