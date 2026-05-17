# Section 7 Consensus — L5 Execution Output + L6 Multi-Horizon Disposition

**Date:** 2026-04-29
**Status:** In progress

**Foundational reframe (operator-locked 2026-04-29):**
- The system does NOT execute trades.
- The operator manually executes based on system output.
- System goal: facilitate data aggregation + automate complex decision model using LLM and code; surface results to operator.
- Default operator-facing view: clean recommendation. Audit chain available on request, not surfaced by default. Matches FDA GMLP P9 transparency principle.

---

## Q1 — Execution-decision output schema **[LOCKED]**

**Decision:** (c) Recommendation + sizing + execution-context.

**Schema:**

```yaml
execution_recommendation:
  ticker: NVDA
  date: 2026-04-30
  recommendation: BUY      # BUY / HOLD / TRIM / SELL
  mode: B'
  sizing_suggestion:
    initial_position_pct: 2.0
    max_position_pct: 4.0
  execution_context:
    current_price: 158.32
    fair_value_estimate:
      point: 175.00
      range_low: 155.00
      range_high: 195.00
    near_term_catalysts:
      - { event: "Q3 earnings", date: 2026-05-15, importance: high }
      - { event: "Fed FOMC AI-capex commentary", date: 2026-05-07, importance: medium }
    suggested_pacing: "DCA over 21 days (Mode B' ride-along default)"
    technical_signals:
      ma_50d: 152.10
      ma_200d: 145.40
      rsi_14: 58.2
      atr_20: 6.40
    risk_flags:
      - "Sector vol elevated (VRP > 1σ); consider scaling pacing slower"
      - "Counterfactual sidecar: 0 SURVIVOR matches active for this name"
  audit_available: true   # full provenance chain hidden by default; surfaced on operator request
```

**Why (c) — recommendation + sizing + execution-context:**
- (a) binary-only under-utilizes funnel work; operator would have to manually re-aggregate
- (b) sizing without context forces operator to manually compile fair-value, catalysts, technicals — defeats data-aggregation goal
- (d) scenario-conditioned variants imply system predicts macro regime outcomes, conflicts with "no regime forecasting" principle
- (c) aggregates everything operator needs to act in one screen, without crossing into prediction-overreach. System aggregates; operator interprets.

**Data sources:**
- Current price + technicals: `mcp__market_data__get_real_time_quote` + `mcp__market_data__get_prices`
- Fair-value estimate: P3 thesis valuation outputs
- Catalysts: `mcp__market_data__get_news` + earnings calendar
- Risk flags: aggregated from S0 regime sidecar + S2 counterfactual sidecar + S4 smart-money sidecar
- Suggested pacing: mode-anchored default (Mode B/B' DCA-21d / Mode C wait-for-arrival)

**Cross-references:**
- Section 1 mode-aware discipline + sizing bands feed `sizing_suggestion`
- Section 4 Q1 structured branches feed `fair_value_estimate`
- Section 5 Q1 stage-isolation principle preserved — recommendation upstream, execution-context aggregation downstream
- Section 6 Q6 (d') counterfactual veto status feeds `risk_flags`

**Implementation handoff:**
- Code: `src/skills/p5-entry-output/recommendation_emitter.py` (and `p9-exit-output/`)
- Output stored: Postgres `execution_recommendations` table; one row per ticker per emission event
- Audit chain: separate `audit_provenance` table linked by recommendation UUID; not surfaced unless operator requests via `/audit-trail <recommendation_id>`

---

## Q2 — Multi-horizon disposition view **[LOCKED]**

**Decision:** (d) Combined unified-view + mode-anchored primary horizon.

**View structure:**
- Single screen lists all watchlist names; each row has three horizon columns (Short ≤3mo / Mid 3-12mo / Long 12+mo)
- Mode-anchored primary horizon is **highlighted/expanded by default**; secondary horizons compact/collapsed
- Mode → primary horizon mapping:
  - Mode B (steady compounder): Long primary
  - Mode B' (growth compounder): Mid primary
  - Mode C (thematic): Short primary
- Operator can manually toggle any name's primary horizon view

**Per-row schema:**

```yaml
disposition_row:
  ticker: NVDA
  mode: B'
  primary_horizon: mid
  short_horizon:
    signal: HOLD
    key_signal: "Earnings 2026-05-15 binary catalyst"
    detail_collapsed_by_default: true
  mid_horizon:                              # PRIMARY for Mode B'
    signal: "BUY (DCA active day 8 of 21)"
    key_signal: "Hyperscaler capex re-acceleration confirmed Q1; pillar 2 strengthening"
    detail_expanded_by_default: true
  long_horizon:
    signal: HOLD
    key_signal: "AI compute secular tailwind intact through 2030"
    detail_collapsed_by_default: true
```

**Why (d) — unified view + mode-anchored emphasis:**
- (a) three separate screens fragments operator attention; cross-horizon signals lost in switching
- (b) flat unified view ignores Section 1 mode-aware discipline (B's edge IS long-horizon thinking)
- (c) mode-anchored only hides cross-horizon signals when they matter (e.g., Mode B name with sharp short-horizon catalyst)
- (d) preserves both: full visibility (everything on one screen) + mode-aware emphasis (primary horizon = where mode's edge lives)

**Cross-references:**
- Section 1 mode-aware discipline → primary-horizon mapping
- Section 6 Q4 pre-mortem cadence (B 180d / B' 120d / C 60d) is mode-tuned for the same reason — short-horizon names need faster reflection
- Section 6 Q1 daily-refresh log feeds the per-row signals

**Implementation handoff:**
- Code: `src/skills/p8-daily-monitor/disposition_view.py`
- Output: rendered as Postgres view `current_disposition` joining `daily_refresh_log` + `execution_recommendations` + `positions`
- UI: terminal-rendered table by default (matches Claude Code CLI environment); web view at v0.5+

---

## Q3 — Trigger logic for entry/exit recommendations **[LOCKED]**

**Decision:** (d) Mode-tuned cadence + materiality interrupts + new-candidate immediate.

**Triggers for existing watchlist names:**

| Mode | Forced cadence floor | Materiality interrupts |
|---|---|---|
| B (steady compounder) | Weekly Monday open | M-2 or M-3 → immediate |
| B' (growth compounder) | Every 3 days | M-2 or M-3 → immediate |
| C (thematic) | Daily | M-2 or M-3 → immediate |

**Trigger for new candidates (not yet on watchlist):**
- Initial BUY recommendation fires upon completion of full P3 (mechanical scorer) → P4 (debate) funnel approval, regardless of cadence rules above
- New-candidate recommendation includes mode classification + initial sizing band + execution-context per Q1 schema

**Why (d) — mode-tuned + materiality interrupts:**
- (a) daily-refresh-everywhere produces recommendation noise; operator anchors to small daily changes; fatigue source
- (b) materiality-gated alone misses slow-drift cases (AAPL-2018 / KO-2014 erosion that never trips single M-2 event)
- (c) uniform-weekly hybrid ignores Section 1 mode-aware discipline (Mode C needs faster reflection than Mode B)
- (d) matches Section 6 Q4 pre-mortem cadence pattern; mode-tuned floors give right frequency per mode; materiality interrupts catch event-driven changes

**Schema additions to execution_recommendation:**

```yaml
trigger_metadata:
  triggered_by: "mode_cadence_floor"   # mode_cadence_floor / m2_event / m3_event / new_candidate
  cadence_floor_due_at: 2026-05-04T09:30:00Z
  materiality_event_ref: null
  prior_recommendation_date: 2026-04-30
  prior_recommendation: BUY
  changed_from_prior: false
```

`changed_from_prior` flag distinguishes "noise refresh" (rec unchanged) from "actionable update" (rec changed). UI presents the latter prominently; the former stays in audit log only.

**Cross-references:**
- Section 1 mode-aware discipline → cadence floors
- Section 6 Q1 materiality classification → interrupt triggers
- Section 6 Q4 pre-mortem cadence — same mode-tuned pattern

**Implementation handoff:**
- Code: `src/skills/p8-daily-monitor/recommendation_trigger.py`
- Cadence enforcement: cron-style scheduler keyed on mode + ticker; runs at market-open per cadence
- Materiality interrupt: triggered by `daily_refresh_log` write with `materiality >= M-2`

---

## Q4 — Audit-mode UX **[LOCKED]**

**Decision:** (b) Layered drill-down — audit summary with traceable detail per stage.

**Default operator-facing view:** clean recommendation per Q1 schema. No audit information.

**Audit-on-request view (operator runs `/audit-trail <rec_id>`):**

Top-level audit summary structure:

```yaml
audit_summary:
  recommendation_id: uuid
  ticker: NVDA
  recommendation: BUY
  date: 2026-04-30
  decision_path:
    stage_1_mechanical: { outcome: PROCEED, score: A (3/4), drill_link: /audit/stage1/<uuid> }
    stage_2_debate:    { consensus: BUY (4/5 styles), dissenter: "Quant-Technical (HOLD)", drill_link: /audit/stage2/<uuid> }
    stage_3_kill_criteria: { fired: 0 of 7, drill_link: /audit/kill/<uuid> }
    stage_4_counterfactual: { top_3_archetype: "3 SURVIVOR", veto_status: not_triggered, drill_link: /audit/cf/<uuid> }
    materiality: { classification: M-2, trigger: "earnings_call_remark", drill_link: /audit/mat/<uuid> }
  versions:
    rule_engine: 1.0.0
    debate_prompt: L4-debate-v0.1.0
    model: claude-opus-4-7
    parameters: params_v3
```

Each `drill_link` surfaces full audit data for that stage (verbatim quotes, agent outputs, 3-LLM iterative-consensus iterations, retrieval results, kill-criteria evaluation chain).

**Why (b) — layered drill-down:**
- (a) unified dump produces noise on confirmed-expected BUY recs; less useful than guided drill on contested ones
- (c) per-component pages fragment — auditing "why BUY?" traces mechanical → debate → counterfactual as one chain, not isolated subsystems
- (d) replayability introduces non-determinism (re-running with new params blurs "what actually happened" vs "what could happen"); goes to /backtest, not audit
- (b) matches FDA GMLP P9 + financial-reporting audit norms — summary-with-traceable-detail

**Cross-references:**
- Section 5 Q1 per-stage audit log → drill content
- Section 5 Q3 3-LLM iterative-consensus → per-feature audit
- Section 6 Q1 materiality classification → materiality drill
- Section 6 Q6 (d') counterfactual veto → counterfactual drill

**Implementation handoff:**
- Code: `src/skills/audit-trail/audit_renderer.py`
- Storage: `audit_provenance` Postgres table linked by recommendation UUID
- Slash command: `/audit-trail <rec_id>` and `/audit-trail <ticker> --latest`
- HMAC-signed audit chain ensures tamper-evidence (Section 5 Q1 audit_signature carry-through)

---

## Q5 — Position state source **[LOCKED]**

**Decision:** (a) Build a broker MCP — read-only positions endpoint. System polls; diffs against last-known positions to detect fills automatically. No operator paste/manual entry.

**Operator framing (corrected 2026-04-29):** "The system should be able to fetch price data from connected APIs. No need to wait for the feedback from the operator, can be automated." → fill detection is automated via connected API; broker MCP is the connected source for positions.

**Architecture:**

- New MCP: `mcp__broker__get_positions` (read-only)
- Polling cadence: tied to mode-tuned trigger cadence from Q3 (Mode B weekly, Mode B' every 3d, Mode C daily) — broker poll runs at same cadence
- Fill detection: diff current broker positions against last polled snapshot; new shares = inferred fill; price derived from market_data quote at fill timestamp (best-effort) OR broker-provided fill price if available
- Mark-to-market: `mcp__market_data__get_real_time_quote` for current value; existing capability
- Storage: Postgres `positions` table (current state) + `position_history` (append-only event log of fills)

**Schema:**

```yaml
positions:
  ticker: NVDA
  shares_held: 100
  cost_basis: 158.50
  cost_basis_method: FIFO
  first_acquired: 2026-04-30
  last_updated: 2026-04-30T16:00:00Z
  source: "broker_mcp"
  broker: "schwab"   # or ibkr / fidelity / etc.
  account_id_hash: <hashed>

position_history (append-only):
  event_id: uuid
  ticker: NVDA
  event_type: BUY | SELL | DIVIDEND | SPLIT | TRANSFER_IN | TRANSFER_OUT
  date: 2026-04-30
  shares_delta: +100
  price: 158.50
  detection_method: "broker_mcp_diff"
  recommendation_ref: <recommendation_uuid>   # null if discretionary fill not tied to system rec
  divergence_from_recommendation:
    suggested_initial_pct: 2.0
    actual_initial_pct: 1.95
    timing_lag_days: 0
```

**Why (a) — broker MCP direct:**
- (b) portfolio-tracker MCP requires operator to use Sharesight/Snowball; not assumed; adds dependency layer
- (c) file-based feed makes operator maintain manual export; same fragility (a) eliminates
- (d) postgres-as-canonical-source punts on the source-of-truth question; v0.1 still needs SOMETHING populating it
- (a) builds the right long-term answer once; ~1-2 weeks engineering for first broker (probably Schwab or IBKR given retail-API openness); subsequent brokers pluggable

**Cross-references:**
- Section 5 Q1 audit log → fill events feed `divergence_from_recommendation` for calibration tracking
- Section 6 Q3 mode-tuned cut thresholds → require accurate position weight from this state
- Section 7 Q1 execution-context → `current_position_pct` field populated from this state
- Section 7 Q2 disposition view → cost basis + unrealized P&L from this state

**Implementation handoff:**
- New MCP server: `src/mcp/broker_mcp/` (model after existing market_data MCP structure)
- First broker: operator-specified at implementation kickoff (defaults to Schwab if unspecified given API openness post-TDA acquisition)
- OAuth token storage via existing `.env` pattern
- Rate-limit handling: cache positions snapshot at mode-cadence-floor frequency; never poll faster than broker rate limit
- Tax-lot accounting: FIFO default; SpecID supported per fill record from broker

**Engineering risk:** broker API auth requires operator's broker credentials; OAuth flow + token refresh is the load-bearing fragility. Document setup procedure in `provider_verification/broker_<name>.md` per existing pattern.

---

---

## Pushback #1 — v0.1 scope kept full **[LOCKED]**

Operator selected (a): accept current v0.1 scope including broker MCP + audit UI + peak-pain catalog validation. ~4-6 week pre-launch period. Full system on launch day; no staged release.

---

## Pushback #2 — Sizing-band logic v0.1 + v0.5+ split **[LOCKED]**

**Decision:** (d) Static mode-anchored bands at v0.1 + composable formula at v0.5+ when calibration data accumulates.

**v0.1 mode-static bands:**

| Mode | Initial | Max |
|---|---|---|
| B (steady compounder) | 3% | 8% |
| B' (growth compounder) | 2% | 5% |
| C (thematic) | 1% | 3% |

**v0.1 hard overlays (apply to ALL modes):**

1. **Cash constraint:** `suggested_initial = min(mode_band, available_cash_pct)`. If cash < suggested_initial, system surfaces companion TRIM recommendation candidates (lowest-conviction current holdings) to fund the buy.
2. **Drawdown auto-tighten** (Section 1 relative-to-benchmark): if portfolio drawdown vs mode-benchmark exceeds threshold (B/S&P 5pp, B'/QQQ 7pp, C/IWO 10pp), `sizing × 0.5` until drawdown clears.
3. **S0 vol-elevated regime override:** if S0 vol dimension > +1σ, `sizing × 0.7` across all modes.

**v0.5+ composable formula (deferred):**
```
suggested_initial = mode_base_band[mode]
                  × conviction_multiplier (0.6-1.2 per debate consensus)
                  × regime_multiplier (0.5-1.0 per S0 vol/credit/cycle state)
                  × drawdown_tighten_multiplier (0.5-1.0 per current drawdown vs benchmark)
                  × cash_constraint (capped at available cash)
```

Multiplier ranges to be calibrated empirically once v0.1 has produced ≥3 months of recommendation+fill data with operator override-rationale logs.

**Why staged (a) → (d):**
- v0.1 (a) static mode bands acknowledge ignorance — same Section 3 Q2 equal-weight-at-small-N principle (Smith-Wallis 2009)
- Three hard overlays at v0.1 capture the most-load-bearing factors (cash, drawdown, regime vol) without compounding-multiplier risk
- Calibrated formula at v0.5+ matches Section 3 Q2 BB-pseudo-BMA+ upgrade pattern

**Schema additions:**
```yaml
sizing_suggestion:
  initial_pct: 1.4   # post-overlay
  max_pct: 3.5
  base_band: { initial: 2.0, max: 5.0 }   # mode B' default
  applied_overlays:
    - { name: cash_constraint, multiplier: 1.0, reason: "$5K cash sufficient" }
    - { name: drawdown_tighten, multiplier: 0.5, reason: "B' vs QQQ drawdown 8.2pp > 7pp threshold" }
    - { name: vol_regime, multiplier: 1.0, reason: "S0 vol +0.4σ within band" }
  net_multiplier: 0.5
  funding_required: false   # if cash_constraint binds → true; surfaces companion TRIM candidates
```

---

## Section 7 — All 5 questions LOCKED + 2 pushbacks resolved.

| Item | Decision | Status |
|---|---|---|
| Q1 | Execution-decision output: recommendation + sizing + execution-context | LOCKED |
| Q2 | Disposition view: unified + mode-anchored primary horizon | LOCKED |
| Q3 | Trigger logic: mode-tuned cadence + materiality interrupts + new-candidate immediate | LOCKED |
| Q4 | Audit-mode UX: layered drill-down (summary + per-stage drill links) | LOCKED |
| Q5 | Position state source: broker MCP (read-only); auto-detect fills | LOCKED |
| PB1 | v0.1 scope: full system, no staged release | LOCKED |
| PB2 | Sizing: mode-static bands + 3 overlays at v0.1; composable at v0.5+ | LOCKED |
| PB3 | Mode classification: rule-based primary + LLM tie-breaker on overlap | LOCKED |
| PB4 | Push alerts: multi-channel (email M-3 + Claude Code session push + /alerts pull) | LOCKED |
| PB5 | Conviction rollup: discrete HIGH/MED/LOW at v0.1; continuous score at v0.5+ | LOCKED |

---

## Pushback #5 — Top-level conviction indicator **[LOCKED]**

**Decision:** (d) Discrete bucket at v0.1 + continuous score at v0.5+.

**v0.1 — discrete bucket added to Q1 schema:**

```yaml
execution_recommendation:
  ticker: NVDA
  recommendation: BUY
  conviction: HIGH    # NEW top-level field — HIGH | MEDIUM | LOW
  ...
```

**Rollup rules (v0.1, deterministic):**

| Conviction | Required signals |
|---|---|
| HIGH | ≥4/5 debate consensus AND 0 kills fired AND ≥2 SURVIVOR matches in top-3 AND mode rule-clean (no LLM tie-breaker) AND 0 anchor-drift channels triggered |
| MEDIUM | Any one of: 3/5 debate OR 1 kill fired OR mixed counterfactual (1-2 SURVIVOR + 1-2 NON-SURVIVOR) OR mode classified via LLM tie-breaker OR 1 anchor-drift channel triggered |
| LOW | Any one of: <3/5 debate OR ≥2 kills fired OR ≥2 NON-SURVIVOR matches in top-3 OR ≥2 anchor-drift channels triggered |

**v0.5+ — continuous conviction_score (deferred):**

```
conviction_score = w_debate × debate_score
                 + w_kills × (1 - kills_fired_fraction)
                 + w_cf × cf_archetype_alignment_score
                 + w_mode × mode_certainty
                 + w_drift × (1 - drift_channels_triggered_fraction)
```

Weights calibrated empirically once v0.1 produces ≥3 months of recommendation+fill+outcome data; same calibration window as Pushback #2 sizing formula.

**Why (d) — staged discrete → continuous:**
- (a) no rollup defeats purpose of having all confidence signals — operator should not have to drill into audit for most-decision-relevant rollup
- (b) discrete-only at v0.1 is right granularity (HIGH/MED/LOW maps cleanly to operator sizing/timing decisions)
- (c) continuous at v0.1 has no calibration data; weights arbitrary; same Section 3 Q2 small-N problem (compounded weights at small N → arbitrary outputs)
- (d) ships discrete-bucket rollup (operator gets immediate signal) + upgrades to continuous when v0.1 calibration data accrues

**Schema additions:**

```yaml
execution_recommendation:
  recommendation: BUY
  conviction: HIGH
  conviction_breakdown:
    debate_consensus: "4/5 (Quant-Technical dissents HOLD)"
    kills_fired: "0 of 7"
    counterfactual_top_3: "3 SURVIVOR archetype"
    mode_certainty: "rule-clean (no LLM tie-breaker)"
    drift_channels: "0 of 3 triggered"
  ...
```

`conviction_breakdown` surfaces the underlying signals without requiring audit drill-down — same purpose as the conviction label, but with the per-component evidence.

**Cross-references:**
- Section 5 Q1 stage-2 debate consensus → debate signal
- Section 4 Q3 hybrid kill-criteria → kills signal
- Section 6 Q6 (d') counterfactual veto → counterfactual signal
- Pushback #3 mode classification → mode certainty signal
- Section 6 Q5 anchor-drift → drift channels signal
- Pushback #2 sizing-band → conviction_multiplier in v0.5+ formula consumes this rollup

**Implementation handoff:**
- Code: `src/skills/p5-entry-output/conviction_rollup.py`
- Stored alongside execution_recommendation in same Postgres table

---

## Section 7 — final summary

| Item | Decision | Status |
|---|---|---|
| Q1 | Execution-decision output: recommendation + sizing + execution-context + conviction | LOCKED |
| Q2 | Disposition view: unified + mode-anchored primary horizon | LOCKED |
| Q3 | Trigger logic: mode-tuned cadence + materiality interrupts + new-candidate immediate | LOCKED |
| Q4 | Audit-mode UX: layered drill-down (summary + per-stage drill links) | LOCKED |
| Q5 | Position state source: broker MCP (read-only); auto-detect fills | LOCKED |
| PB1 | v0.1 scope: full system, no staged release | LOCKED |
| PB2 | Sizing: mode-static bands + 3 overlays at v0.1; composable at v0.5+ | LOCKED |
| PB3 | Mode classification: rule-based primary + LLM tie-breaker on overlap | LOCKED |
| PB4 | Push alerts: multi-channel (email M-3 + Claude Code session push + /alerts pull) | LOCKED |
| PB5 | Conviction rollup: discrete HIGH/MED/LOW at v0.1; continuous score at v0.5+ | LOCKED |

---

## Pushback #4 — Multi-channel push alerts **[LOCKED]**

**Decision:** (d) Multi-channel — email real-time + Claude Code session push + slash-command pull.

**Channel architecture:**

| Channel | Purpose | Triggers | Operator state |
|---|---|---|---|
| Email | Real-time critical alerts | M-3 events only | Always-on |
| Claude Code session push | Catch-up at session start | Unread M-3/M-2 since last session | Session-bound |
| `/alerts` slash command | On-demand review | All current alerts | Pull-on-demand |

**M-3 events that trigger email push:**
- Counterfactual veto fires (Section 6 Q6 layer-3)
- Anchor-drift channel triggers (Section 6 Q5: pillar drift / outcome divergence / periodic re-read)
- Mode reclassification triggered (Section 6 Q4 trigger 4 / Pushback #3)
- Kill-criterion explicitly fired or disproven (Section 4 Q3)
- Drawdown crossing 2× cut threshold (Section 6 Q6 layer-1)
- Materiality classification = M-3 (Section 6 Q1)

**Email schema:**
```yaml
email_alert:
  to: <operator_email_from_env>
  subject: "[M-3] NVDA — Counterfactual veto fired (cut blocked)"
  body:
    ticker: NVDA
    alert_type: counterfactual_veto
    summary: "≥2 of top-3 retrieved cases are SURVIVOR archetype; cut requires explicit operator override"
    recommendation_summary: { current: HOLD, prior: SELL, sizing: ... }
    drill_link: "Run /audit-trail <rec_id> in Claude Code for full provenance"
    timestamp: 2026-04-30T21:00:00Z
```

**Claude Code session push schema:**

At session start, system queries `unread_alerts` table for M-3 + M-2 events not yet operator-acknowledged. Surfaces summary BEFORE any other interaction:

```
[2 unread M-3 alerts since last session 2026-04-29 18:00]

NVDA — Counterfactual veto fired 2026-04-30 21:00
  Cut blocked by ≥2 SURVIVOR matches. Run /audit-trail NVDA for details.

PLTR — Mode reclassification proposed 2026-04-30 09:30
  Rule-based: B'+C overlap → LLM tie-breaker recommends C → B' (downgrade).
  Pre-mortem required before commit. Run /premortem PLTR.

[3 unread M-2 alerts] — run /alerts for full list
```

Operator can acknowledge alerts via `/ack <alert_id>` or `/ack all`.

**`/alerts` slash command:** lists all unacknowledged alerts; supports filtering by ticker, severity, type, date.

**Engineering deferrability:**
- v0.1 (full): all 3 channels active
- v0.1 (constrained): if engineering pressure tight, ship Claude Code session push (c) + `/alerts` only; defer email (b) to v0.5+. Loses real-time-when-Claude-Code-not-open capability but covers session-bound operator workflow

**Why (d) — multi-channel:**
- (a) pull-only accepts 12-24 hour blindspots that defeat M-3 routing's purpose
- (b) email alone misses operators who don't check email reliably
- (c) session-push alone has session-open dependency; vacation = M-3 events sit
- (d) covers real-time (email), session-start catch-up (Claude Code), pull-on-demand (slash-command); each channel handles a different operator state

**Cross-references:**
- Section 6 Q1 materiality classification → triggers
- Section 6 Q2 hybrid routing → operator alert mechanism specified
- Section 7 Q3 trigger logic → recommendation update flows to push alert
- Section 7 Q4 audit-trail drill-link → present in alert payload

**Implementation handoff:**
- Code: `src/skills/p8-daily-monitor/alert_emitter.py` + `alert_channels/`
- Storage: `unread_alerts` Postgres table; alert acknowledgment via slash command updates row
- Email: SMTP via SendGrid OR plain SMTP with operator-configured creds in `.env`
- Session push: integrated into Claude Code session-start hook (existing pattern)
- Slash command: `/alerts`, `/ack <id>`, `/ack all`

---

## Pushback #3 — Mode classification logic **[LOCKED]**

**Decision:** (c) Hybrid — rule-based primary + LLM tie-breaker on overlap cases.

**Pipeline:**

1. **Rule-based primary classifier** (deterministic):
   - B: founder ≥10yr tenure + ROIIC > 15% sustained 5yr + GAAP profitable 5+yr
   - B': founder ≥5yr + revenue growth > 25% YoY 3yr + path-to-profit clear
   - C: rest (thematic, pre-profit, narrative-driven)

2. **Overlap detection:** if candidate hits criteria for >1 mode OR fails all 3 → routes to step 3.

3. **LLM tie-breaker** (only on overlap):
   - Single-attribute LLM call (Section 5 Q1 stage-isolation pattern)
   - Forced JSON output: `{mode: B/B'/C, confidence, rationale, evidence_quotes}`
   - Verbatim evidence citation required (no quote → defaults to most-conservative mode = C)
   - Self-consistency N=5 sampling at temp=0.7 (Section 5 Q1 lock)
   - Per-pattern rubric (Section 5 Q3 per-instance rubric pattern)

4. **Audit trail:**
   ```yaml
   mode_classification:
     ticker: PLTR
     final_mode: B'
     classification_method: llm_tiebreaker   # rule | llm_tiebreaker
     rule_outcomes:
       B_match: false
       B_prime_match: true   # founder + revenue growth thresholds met
       C_match: true         # narrative-driven, pre-profit
       overlap_detected: true
     llm_tiebreaker:
       model: claude-opus-4-7
       prompt_version: mode-classifier-v0.1
       rating: B'
       confidence: 0.78
       rationale: "Real revenue with sticky gov customers tips toward B' over C; pre-profit but clear path"
       evidence_quotes: [...]
       self_consistency: { samples: 5, median: B', unanimous: false (4/5) }
   ```

**Why (c) — hybrid:**
- (a) rule-based alone fails on PLTR-style overlap; arbitrary thresholds lock in errors mechanically
- (b) LLM alone introduces anchoring on the most consequential single per-name decision; same reason Section 5 Q1 isolated Stage-2 LLM from Stage-1
- (d) multi-mode probability vector violates Section 1 single-mode-per-name lock; complicates downstream
- (c) does the cheap deterministic work first (most candidates classify cleanly via rules) + LLM only fires on genuine overlap

**Cross-references:**
- Section 1 "single-mode-per-name; AI decides on overlap" → operationalized
- Section 5 Q1 stage-isolation + per-pattern rubric pattern reused
- Section 6 Q4 mode-reclassification trigger → if mode changes via tie-breaker re-run, pre-mortem mandatory before commit (already locked)
- Pushback #2 sizing band → consumes final mode

**Implementation handoff:**
- Code: `src/skills/p4-mode-classifier/`
  - `rule_classifier.py` (deterministic Python; thresholds in `parameters` table)
  - `llm_tiebreaker.py` (structured prompt + JSON validation)
- Storage: `mode_classifications` Postgres table; one row per (ticker, classification_event)
- Reclassification (Section 6 Q4 trigger): re-runs full pipeline; logs delta + triggers pre-mortem if mode changes
