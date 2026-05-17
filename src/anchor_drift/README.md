# anchor_drift

3-channel anchor-drift detection per v3 spec Section 4.5 Q5
(`docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md`,
lines 530-536). Companion module to `premortem_scheduler/` — anchor-drift
triggers can fire a pre-mortem.

## Channels

| Channel | Type | Trigger | LLM |
|---|---|---|---|
| 1. Pillar drift | Diff-based | drift_score > 0.25 | Sonnet (structured diff) |
| 2. Outcome divergence | Quantitative | any of {revenue, gross_margin, FCF} deviates > 25% from base case | None |
| 3. Periodic re-read | Time-based | days_elapsed >= cadence (B 180d / B' 120d / C 60d) | None |

`any_triggered = OR` over the three. When any channel fires, the
operator MUST choose Reaffirm / Revise-with-rationale / Cut — the no-op
default is BLOCKED (forced_review.operator_decision starts at
`pending`; the application layer enforces resolution before unblocking
recommendations on the name).

## HMAC verification

The channels read `watchlist.thesis_pillars_original` and
`watchlist.scenario_A_base_projections`, which are HMAC-signed at P5
lock per Section 6.2 / migration 007. `hmac_verify.py` recomputes the
HMAC over canonical-JSON; mismatch is treated as drift (channel
triggers). Secret is read from `WATCHLIST_HMAC_SECRET`.

## Drift score (Channel 1)

```
drift_score = (sum(|confidence_delta|) + count(softened) + count(rewritten)) / total_pillars
```

Channel 1 calls Sonnet for the structured diff (forced JSON output).

## CLI

```bash
python -m anchor_drift.cli check --ticker NVDA
python -m anchor_drift.cli check --bulk
python -m anchor_drift.cli check --ticker NVDA --as-of 2026-04-29 --no-persist
```

## Storage

One row per `(ticker, check_date)` into `anchor_drift_checks`
(`010_v3_drift_detection.sql`). Append-only.

## Integration

- `mode_classifier`  — supplies `mode` (drives Channel 3 cadence).
- `premortem_scheduler` — anchor-drift trigger surfaces a pre-mortem
  via the cadence + event-trigger union (consecutive M-2 events on
  the same name; pillar drift can be the underlying cause).

## NOT implemented here

- Push alert delivery (Wave C).
- Counterfactual veto (Wave C).
- Mode reclassification logic itself (`mode_classifier.recheck`).
