# Prediction Resolution Procedure

Per v2-final §3.2 outcome rubrics. Used by daily orchestration (the resolution job that runs as part of `/daily-monitor` post-market close).

## What gets resolved

Every CompanyDeepDive memo includes ≥3 `reviewable_predictions` with explicit `resolution_date`. Examples:

```
prediction_id: <uuid>
agent_run_id: <memo's agent_run_id>
ticker: <ticker>
claim: "Revenue will exceed $X by FY26 Q4"
direction: positive
target_value: $X
resolution_date: 2026-12-31
confidence: 0.65
```

Other prediction sources:
- BearCase predictions (e.g., "Concern Y will materialize within 12 months")
- PMSupervisor predictions (less common; tied to portfolio-level claims)
- MacroCycle predictions (regime change probability claims)
- DailyMonitor materiality predictions (probabilistic; rare)

## Resolution job

Runs daily as part of `/daily-monitor`:

```
1. Query Predictions DB for predictions with resolution_date = today (or earlier if missed)
2. For each due prediction:
   a. Fetch the actual outcome (revenue, price, regime, etc.) via market data MCP
   b. Compare predicted vs actual; compute Brier score for probabilistic predictions
   c. Insert resolution record (does NOT update prediction; predictions are append-only)
   d. Update per-agent calibration history view
3. Surface resolutions in daily digest
4. If any resolution is anomalous (e.g., agent prediction flatly wrong with high confidence),
   surface as monitoring escalation
```

## Resolution record schema

```sql
CREATE TABLE prediction_resolutions (
    resolution_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    prediction_id        UUID NOT NULL,
    resolved_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    actual_outcome       TEXT NOT NULL,           -- description of what happened
    actual_value         NUMERIC,                  -- for numerical predictions
    direction_correct    BOOLEAN,                  -- for directional predictions
    brier_score          NUMERIC,                  -- for probabilistic predictions
    abs_error            NUMERIC,                  -- for point predictions
    source_uri           TEXT NOT NULL,            -- how was this resolved (filing, market data, etc.)
    source_date          DATE NOT NULL,
    resolution_evidence  TEXT,                     -- narrative explanation
    is_anomaly           BOOLEAN DEFAULT FALSE,    -- flag for monitoring
    
    -- Append-only constraint enforced via trigger
    CONSTRAINT fk_prediction FOREIGN KEY (prediction_id) REFERENCES predictions(prediction_id)
);
```

## Brier score for probabilistic predictions

For predictions with explicit probability values:

```
Brier = (predicted_probability - actual_outcome)²

Where:
  - predicted_probability ∈ [0, 1]
  - actual_outcome = 1 if event occurred, 0 if not
  - Lower is better; perfect calibration = 0
```

Per-agent rolling Brier (90-day window) feeds the PositionSizingModel calibration adjustment per `position-sizing-formula.md`.

## Resolution discipline (non-negotiable)

Per v2-final §3.2:

> Every prediction has scheduled resolution date. On that date, resolution job runs unconditionally. No "let me wait and see."

When the date hits, the prediction is scored. If the actual outcome is ambiguous (e.g., "Revenue grew approximately X" when the prediction was specific), the resolution job records the resolution as `direction_correct = NULL` and `actual_value` set to the best available estimate. The prediction is still "resolved" — the ambiguity is what gets recorded.

There is no "I'll resolve this later when more data is in." Predictions are tied to specific resolution dates set at memo creation time. If the memo's prediction was vague, that's a process-rubric failure that should have been caught at the Evaluator stage.

## Calibration data hygiene

Per phasing-plan.md §5.3:

- Predictions resolved during regime transitions are flagged (`is_anomaly = TRUE`)
- Predictions whose underlying source data was later revised are flagged
- Per-agent calibration is computed on rolling windows (90-day default), never lifetime
- Calibration drift detection runs at every phase boundary

The flagging doesn't disqualify the prediction from the calibration history — it adds context. Anomaly-flagged resolutions are weighted differently in the rolling Brier calculation (specifics: equal weight for now; tunable via annual rubric review per phasing-plan.md §3.5).

## Resolution evidence is itself an Evidence Index entry

When a prediction is resolved, the resolution evidence (e.g., "AAPL Q4 2026 10-Q shows revenue of $X, exceeding the $X-1B prediction by $1B") is itself a claim with a source. Per `evidence-index-schema.md`, this gets an Evidence Index row:

```
agent_id: 'resolution-job'
agent_run_id: <UUID for this resolution batch>
claim_text: <resolution evidence>
claim_type: 'dated_fact'
source_uri: <filing or data source>
source_date: <filing date>
source_quality_tier: 1 or 2 (regulatory or transcript)
related_thesis_id: <UUID of the predicting memo>
```

This makes resolution traceable — "what did we know about this resolution and where did we know it from?"

## Counterfactual ledger entries on resolution

When a prediction resolves, the counterfactual ledger gets a corresponding entry per v2-final §3.3:

```
For a thesis prediction (CompanyDeepDive):
  - Position outcome (after-tax return) vs SPY return over same period
  - Position outcome vs sector ETF over same period
  - Position outcome vs equal-weight watchlist over same period

For a macro prediction (MacroCycleAgent):
  - Sizing modifier impact on portfolio P&L over the regime
```

These entries feed the quarterly counterfactual report.

## Per-agent calibration view

A Postgres view aggregates resolution data per agent over rolling windows:

```sql
CREATE VIEW agent_calibration_90d AS
SELECT
    p.agent_id,
    COUNT(*) AS resolved_predictions,
    AVG(r.brier_score) AS mean_brier,
    AVG(r.abs_error) AS mean_abs_error,
    AVG(CASE WHEN r.direction_correct THEN 1.0 ELSE 0.0 END) AS direction_hit_rate,
    -- Brier trend
    AVG(CASE WHEN r.resolved_at >= NOW() - INTERVAL '30 days'
             THEN r.brier_score END) AS recent_brier,
    AVG(CASE WHEN r.resolved_at < NOW() - INTERVAL '30 days'
             AND r.resolved_at >= NOW() - INTERVAL '90 days'
             THEN r.brier_score END) AS prior_brier
FROM predictions p
JOIN prediction_resolutions r ON p.prediction_id = r.prediction_id
WHERE r.resolved_at >= NOW() - INTERVAL '90 days'
GROUP BY p.agent_id;
```

This view is queried by:
- PositionSizingModel for Kelly fraction calibration (`position-sizing-formula.md`)
- Phase gate evaluation at Checkpoint 3 (gate 2.5.2 — calibration data sufficiency... wait, this is v0.5 gate)
- Monthly review (LearningLoop substitute in v0.1)
- Annual rubric review (v1.0)

## Edge cases

### Prediction whose resolution depends on a delayed filing

If the resolution requires a filing that hasn't been filed yet by the resolution_date (e.g., 10-K filed 90 days after fiscal year end, but resolution_date set to fiscal year end), the resolution job records `direction_correct = NULL` with reason `awaiting_filing`. The job re-runs on each filing receipt; the next time the filing appears, full resolution is computed.

### Prediction resolving in operator's vacation/extended absence

Resolutions happen mechanically on the resolution job (cron). They don't require operator presence. Operator reviews the day's resolutions when they next check the daily digest. No backlog accumulates.

### Conflicting resolutions (same prediction resolved by multiple sources)

If two sources disagree (e.g., earnings press release vs 10-Q for same quarter; rare but possible due to revisions), the resolution job uses the later/more-authoritative source and notes the conflict in `resolution_evidence`. This becomes an `is_anomaly = TRUE` flag for monitoring.

### Self-resolving predictions (resolution before surfaced_date)

Per `contamination-check.md`: if a prediction's resolution_date is in the past at surfaced_date, the contamination check rejects the memo. Self-resolving predictions are incoherent and shouldn't pass into the Predictions DB in the first place.

## What this enables

The resolution loop is what makes the system honest over time:
- Per-agent calibration becomes empirical, not asserted
- Counterfactual baselines accumulate, exposing whether the system adds value
- Sample size grows toward the LearningLoop activation thresholds (≥90 resolved predictions, ≥10 closed positions per phasing-plan.md §4.5)
- Month-18 honest-answer rubric (phasing-plan.md §5.4) operates on real data
