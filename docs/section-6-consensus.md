# Section 6 Consensus — L4 View-Refresh Discipline

**Date:** 2026-04-29
**Status:** In progress
**Scope:** P8 daily monitor + view-refresh cadence + materiality routing + behavioral disciplines (anchor-drift, premortem, capitulation triggers)

---

## Q1 — What does P8 emit per watchlist name per day? **[LOCKED]**

**Decision:** (b) Materiality score + structured event log per name.

**Schema:**

```yaml
daily_refresh_log:
  date: 2026-04-30
  ticker: NVDA
  mode: B'
  materiality: 2     # M-1 / M-2 / M-3
  events:
    - type: "earnings_call_remark"
      source_id: "earnings_q1_fy27"
      timestamp: 2026-04-30T20:30:00Z
      verbatim_quote: "We see capex moderation in second-half customers"
      impact: "Reduces growth dimension; check vs scenario A kill criteria"
      cited_kill_criterion_id: "scenario_A.kill_3"
    - type: "smart_money_signal"
      source_id: "13F_filing_xyz"
      ...
  regime_context_at_eval:
    S0_classification: "late_cycle_high_vol"
    relevant_dimensions: ["vol", "credit"]
  recommended_action: "P4 partial reunderwrite — Macro-Regime + Quality agents only"
  llm_call_metadata:
    model: claude-sonnet-4-6     # Default for materiality-1 / materiality-2
    prompt_version: "L4-daily-refresh-v0.1"
    tier_escalated_to_opus: false
```

**Model constraint (operator-locked):** Sonnet or Opus only. NO Haiku.

| Materiality | Default model | Rationale |
|---|---|---|
| M-1 (no action) | claude-sonnet-4-6 | Sonnet is the floor — Haiku is rejected because misclassification of M-2 events as M-1 is the dominant failure mode and Haiku has insufficient reasoning depth on contestable judgments (verbatim-quote interpretation, impact assessment vs kill-criterion linkage). |
| M-2 (targeted update) | claude-sonnet-4-6 | Sonnet handles structured event log + impact reasoning + kill-criterion match. |
| M-3 (full re-underwrite trigger) | claude-opus-4-7 | Opus escalation when materiality-3 detected — drives full P4 re-run with all 5 debate styles. Higher reasoning depth for high-stakes path. |

**Sibling update required:** `.claude/references/daily-monitor-tier-routing.md` (existing v2-final tier-1 Haiku reference) needs a note that Section 6 Q1 lock overrides Haiku routing for the L4 daily-refresh path. Tier-1 Haiku may still be valid for non-L4 lighter-touch surfaces (e.g., raw-news ingestion pre-classification) but NOT for materiality classification or structured event log emission.

**Why structured event log (not just score, not full mini-report):**
- (a) score-only loses traceability — can't audit *why* materiality was 2 vs 1; can't reconstruct the call later.
- (c) full mini-report is wasteful at materiality-1 (most days) and creates anchoring bias when materiality is genuinely low.
- (b) gives auditability where it matters (every event with verbatim quote + source_id + impact narrative + kill-criterion link) without burning tokens on no-news days. Aligns with FDA GMLP P9 audit-trail principle and Section 5 Q1 pinpoint-cite enforcement.

**Cross-references:**
- Section 4 Q3 hybrid kill-criteria — `cited_kill_criterion_id` is the linkage point.
- Section 5 Q1 pinpoint-cite enforcement — `verbatim_quote` is mandatory; missing quote → defaults to materiality-1 + flag.
- Section 3 Q3 BOCPD regime escalation — `regime_context_at_eval` snapshots S0 dimensions at evaluation time so retrospective audit can detect regime-induced drift in materiality calls.
- Section 1 PMSupervisor must NOT force consensus — daily-refresh log is per-name, not aggregated; PMSupervisor reads logs and decides routing without collapsing dissent.

**Implementation handoff:**
- Code: `src/skills/p8-daily-monitor/refresh_emitter.py`
- Storage: Postgres `daily_refresh_log` table (one row per ticker per day)
- Schema versioned via `parameters` table (prompt_version field)
- Materiality classifier: structured-output JSON schema with rating ∈ {M-1, M-2, M-3} + confidence + verbatim_quote + cited_kill_criterion_id + impact rationale (≤2 sentences)

---

## Q2 — Materiality routing rules **[LOCKED]**

**Decision:** (b) Hybrid — predetermined floor + LLM-judge can escalate within bounded middle.

**Routing rules:**

| Tier | Action | LLM-judge role |
|---|---|---|
| M-1 | No-op, log only | None — bypassed |
| M-2 | P4 partial re-underwrite; LLM judge picks 2-4 of 5 debate agents based on event type + cited kill-criterion + regime context | Bounded selection within {Value, Growth, Quality-Moat, Macro-Regime, Quant-Technical}; defaults to event-type lookup table if judge confidence < 0.6 |
| M-3 | P4 full 5-agent re-underwrite + operator alert | Cannot downgrade to partial; can only flag additional context for PMSupervisor synthesis |

**Event-type → default agent lookup (M-2 fallback when judge confidence low):**

| Event type | Default agents (2 of 5) |
|---|---|
| Earnings call remark / EPS surprise | Quality-Moat + Growth |
| Macro print (CPI, NFP, Fed) | Macro-Regime + Value |
| Smart-money signal (13F, insider trade) | Quality-Moat + Quant-Technical |
| Sector rotation / peer move | Macro-Regime + Quant-Technical |
| Regulatory / litigation | Quality-Moat + Value |
| Product / capex / M&A announcement | Growth + Value |
| Credit-event / spread blowout | Macro-Regime + Value |

**Why hybrid (not strict, not full LLM):**
- Strict (a) misses cross-cutting events — e.g., a regulatory headwind buried in an earnings call hits 4 agents, not the 2 the table prescribes for "earnings remark."
- Full LLM (c) collapses materiality + routing into one judgment, recreating the anchoring failure mode Section 5 Q1 fixed via stage isolation.
- Hybrid gives **auditable predetermined floor** (M-3 always full + operator alert; M-2 has fallback table) while letting the judge handle the contestable middle (which 2-4 agents on M-2). Confidence < 0.6 → judge defers to lookup table; auditable both directions.

**Schema additions to daily_refresh_log:**

```yaml
routing_decision:
  tier: M-2
  selected_agents: ["Quality-Moat", "Growth", "Macro-Regime"]
  judge_confidence: 0.78
  defaulted_to_table: false
  rationale: "Earnings remark referenced regulatory exposure → Macro-Regime added beyond default Q+G pair"
  judge_model: claude-sonnet-4-6
  judge_prompt_version: "L4-routing-judge-v0.1"
```

**Cross-references:**
- Section 5 Q1 stage isolation principle preserved — materiality classification (Q1) and routing (Q2) are SEPARATE LLM calls; routing judge does NOT see materiality reasoning, only the final tier + event log.
- Section 1 5-style debate composition — routing operates on the same 5 agents.
- Section 4 Q7 full scenario set passed to Macro-Regime — routing respects this; if Macro-Regime is selected, it gets the full P2 scenario set, not just the triggering event.

**Implementation handoff:**
- Code: `src/skills/p8-daily-monitor/routing_judge.py`
- Lookup table: `src/skills/p8-daily-monitor/event_type_routing.yaml` (versioned)
- Judge model: Sonnet for M-2 routing decisions; never Haiku.



## Q3 — Hold-through-vs-cut-fast polarity per mode **[LOCKED]**

**Decision:** (b) Mode-tuned kill-criteria thresholds.

**Disposition logic per mode:**

### Mode B (steady compounder — KO, COST, V)
**Bias:** hold-through. Single-quarter miss does NOT kill.

Cut when ANY of:
1. ≥2 kill-criteria fired (composite signal)
2. Thesis-defining moat erosion verbatim-confirmed in primary source (10-K, earnings call, regulatory filing)
3. Drawdown vs S&P 500 > 10pp sustained ≥3 quarters

### Mode B' (growth compounder — NVDA, AMD, GOOGL)
**Bias:** moderate. Single thesis-defining kill is enough.

Cut when ANY of:
1. ≥1 thesis-defining kill-criterion fired (e.g., growth-rate floor breached, key customer loss)
2. Growth-rate inflection > -50% YoY 2 consecutive quarters
3. Drawdown vs QQQ > 12pp sustained ≥2 quarters

### Mode C (thematic — RKLB, IONQ)
**Bias:** cut-fast. Narrative collapse beats fundamentals.

Cut when ANY of:
1. Any kill-criterion fired (no compositing required)
2. BOCPD regime-change probability > 0.7 against thesis (Section 3 Q3)
3. Drawdown vs IWO/ARKK > 15pp sustained ≥1 quarter
4. Smart-money exit signal verified (S4 sidecar — ≥2 of {13F coordinated exit, insider sells > 6mo lookback, short-interest spike > 2σ})

**Schema additions to daily_refresh_log:**

```yaml
disposition_evaluation:
  mode: B'
  kill_criteria_fired:
    - id: "scenario_A.kill_3"
      verbatim_quote: "..."
      source_id: "earnings_q1_fy27"
  drawdown_vs_benchmark:
    benchmark: QQQ
    relative_dd_pp: 8.2
    sustained_quarters: 1
  regime_change_probability: 0.45
  smart_money_signal: null
  recommendation: HOLD
  rationale: "1 kill-criterion fired but not thesis-defining; drawdown 8.2pp < 12pp threshold and only 1 quarter sustained"
  trigger_threshold_version: "L4-disposition-v0.1"
```

**Why mode-tuned (not symmetric, not continuous score):**
- Symmetric (a) destroys the mode-aware discipline locked in Section 1 — B's edge IS willingness to absorb single-quarter noise; C's edge IS exiting fast before thematic narrative collapses.
- Continuous score (c) hides disposition logic in opaque weights; same Section 3 Q2 reasoning that rejected gradient optimization at small N. Equal-weight floor + tier threshold is more robust at watchlist size.
- Mode-tuned (b) makes each mode's polarity explicit, auditable, and versioned — `/parameters-review` can detect threshold drift.

**Cross-references:**
- Section 1 mode-aware discipline lock — disposition thresholds operationalize it
- Section 1 relative-to-benchmark drawdown triggers (B/S&P 5pp, B'/QQQ 7pp, C/IWO 10pp) — those are auto-tighten triggers (sizing reduction); these are CUT triggers (full exit). Cut thresholds intentionally wider than auto-tighten thresholds (10pp/12pp/15pp vs 5pp/7pp/10pp); auto-tighten fires first.
- Section 4 Q3 hybrid kill-criteria — kill-criterion IDs are the linkage point
- Section 3 Q3 BOCPD — regime-change probability feeds Mode C
- L7 smart-money lane — S4 sidecar signal feeds Mode C

**Implementation handoff:**
- Code: `src/skills/p8-daily-monitor/disposition_evaluator.py`
- Thresholds: `parameters` table, mode-keyed; versioned per /parameters-review
- Sustained-quarter logic: rolling window over per-day daily_refresh_log entries



## Q4 — Pre-mortem cadence and triggering events **[LOCKED]**

**Decision:** (c) Hybrid — mode-tuned calendar floor + event triggers.

**Calendar floor (mandatory pre-mortem refresh):**

| Mode | Cadence | Rationale |
|---|---|---|
| B (steady compounder) | Every 180 days | Long-horizon drift detection (AAPL-2018 / KO-2014 slow-erosion problem); compounders rarely fire single-event triggers |
| B' (growth compounder) | Every 120 days | Faster narrative cycle; growth-rate inflections accumulate over 4 quarters |
| C (thematic) | Every 60 days | Thematic narratives degrade fastest; pre-mortem cadence matches cut-fast bias from Q3 |

**Event triggers (force pre-mortem regardless of calendar):**

1. **Thesis-confirmation event** — paradoxically the most dangerous moment. When earnings or product event explicitly confirms a thesis pillar, P8 auto-schedules pre-mortem within 7 days. Klein 2007 finds confirmation-induced anchoring is the dominant late-stage failure pattern.
2. **Consecutive M-2 events on same name within 30 days** — accumulating mid-tier signals often precede an M-3 event; pre-mortem catches it before the cascade.
3. **First auto-tighten threshold crossed** — drawdown vs benchmark hits Section 1 sizing-reduction trigger (B/S&P 5pp, B'/QQQ 7pp, C/IWO 10pp). Triggers pre-mortem before the wider Q3 cut threshold is reached.
4. **Mode reclassification proposed** — if PMSupervisor flags name for B↔B' or B'↔C mode reclassification (Section 1 single-mode-per-name AI decides rule), pre-mortem mandatory before reclassification commits.

**Pre-mortem schema:**

```yaml
premortem:
  ticker: NVDA
  date: 2026-04-30
  trigger: "calendar_floor"  # or thesis_confirmation / consecutive_m2 / auto_tighten / mode_reclass
  days_since_last_premortem: 124
  operator_imagined_failure_modes:
    - mode: "Customer concentration unwind — top 4 hyperscalers cut capex 40% in 2027"
      probability_estimate: 0.15
      kill_criterion_added: true
      kill_criterion_id: "scenario_C.kill_1_new"
    - mode: "Compute-efficiency breakthrough makes current architecture obsolete"
      probability_estimate: 0.08
      kill_criterion_added: false
      rationale_for_skip: "Too speculative; below 10% probability floor"
  thesis_pillars_revisited:
    - pillar: "Hyperscaler capex sustained > $200B/yr through 2028"
      still_holds: true
      confidence_delta: -0.05  # since last pre-mortem
      verbatim_evidence: "..."
  net_thesis_strength: 0.82  # vs 0.85 prior
  llm_assist_metadata:
    model: claude-opus-4-7   # Opus for pre-mortem — high reasoning depth required
    role: "devil's-advocate prompt — generate 3 plausible failure modes operator may have missed"
    operator_accepted_count: 1
    operator_rejected_count: 2
```

**LLM role in pre-mortem:**
- LLM is **devil's-advocate assistant**, not author. Operator writes the pre-mortem; LLM generates 3 plausible failure modes operator may have missed.
- Model: Opus (high-stakes contestable judgment; Sonnet floor too shallow for cross-domain failure-mode generation).
- Operator accepts/rejects each LLM-generated mode with rationale logged.

**Why hybrid (not pure time, not pure event, not operator-driven):**
- Pure time (a) wastes operator attention on quiet names; pre-mortem fatigue degrades quality.
- Pure event (b) misses long-horizon slow erosion that never trips a single-event threshold (AAPL-2018, KO-2014).
- Operator-driven (d) relies on the exact discipline humans most often skip when feeling confident — defeats the point.
- Hybrid (c) gives mandatory floor + responsive triggers; mode-tuned cadence matches Q3 polarity.

**Cross-references:**
- Section 1 mode-aware discipline + auto-tighten triggers — pre-mortem fires at first auto-tighten, before cut-threshold
- Section 4 Q3 kill-criteria — pre-mortem can ADD new kill-criteria (write-back path)
- Section 1 PMSupervisor — mode reclassification proposal triggers pre-mortem before commit
- L4 lane — pre-mortem is the canonical L4 view-refresh discipline ritual

**Implementation handoff:**
- Code: `src/skills/p8-daily-monitor/premortem_scheduler.py`
- Storage: `premortem` Postgres table; one row per (ticker, date) tuple
- Cadence parameters: `parameters` table, mode-keyed
- Devil's-advocate LLM prompt: `src/skills/p8-daily-monitor/prompts/premortem_devils_advocate.md`



## Q5 — Anchor-drift defense **[LOCKED]**

**Decision:** (d) Hybrid — automated drift detection + outcome divergence + periodic re-read.

**Three independent drift-detection channels (any triggers operator review):**

### Channel 1 — Automated thesis-pillar drift (diff-based)
- P3 lock writes immutable `thesis_pillars_original` to memo (Postgres `memos` table; original_pillars JSONB column with HMAC signature)
- On every M-2 / M-3 event, LLM (Sonnet) diffs current operating thesis pillars vs original
- Drift score = cumulative |confidence_delta| + count of pillars softened/rewritten / total pillars
- Trigger: drift score > 0.25 → force operator review against ORIGINAL pillars

### Channel 2 — Outcome divergence (quantitative)
- P3 lock writes immutable `scenario_A_base_projections` (revenue, gross margin, FCF) for T+1, T+2, T+3
- On every quarterly earnings, P8 computes actuals vs original base-case projections
- Trigger: any of {revenue, gross margin, FCF} deviates > 25% from original base-case → force review

### Channel 3 — Periodic forced re-read (time-based)
- Cadence matches Q4 pre-mortem floor: B = 180 days, B' = 120 days, C = 60 days
- P8 displays original thesis pillars verbatim alongside current; operator must explicitly acknowledge or revise
- Trigger: scheduled cadence elapsed → force review

**Schema additions to daily_refresh_log:**

```yaml
anchor_drift_check:
  date: 2026-04-30
  ticker: NVDA
  channel_1_pillar_drift:
    drift_score: 0.31
    pillars_softened: ["pillar_2_hyperscaler_capex_durability"]
    pillars_rewritten: []
    diff_llm_model: claude-sonnet-4-6
    triggered: true
  channel_2_outcome_divergence:
    last_earnings: 2026-04-25
    revenue_actual_vs_original_proj: -8.2
    gross_margin_actual_vs_original_proj: -2.1
    fcf_actual_vs_original_proj: -12.0
    triggered: false  # all <25%
  channel_3_periodic_reread:
    last_reread: 2026-01-05
    days_elapsed: 114
    cadence_threshold_days: 120
    triggered: false  # 114 < 120
  any_triggered: true
  forced_review:
    type: "original_thesis_reread"
    surfaced_to: "operator"
    operator_acknowledged_at: null
    operator_decision: pending
```

**Operator-review flow when triggered:**
1. P8 surfaces alert to operator with diff (original vs current thesis pillars)
2. Operator must choose:
   - **Reaffirm original** — current thesis stays; logged as "operator-validated against original"
   - **Revise with rationale** — operator writes verbatim rationale for each pillar change; new pillar version recorded with HMAC chain back to original
   - **Cut position** — proceeds to Q3 disposition logic (forced cut overrides hold-bias)
3. No-op default is BLOCKED — operator cannot dismiss without explicit choice + rationale

**Why hybrid (not single-channel):**
- Channel 1 alone misses "fake-resilient thesis" — verbiage looks unchanged but reality has diverged.
- Channel 2 alone misses qualitative thesis erosion (regulatory shift, narrative change) that doesn't show in quarterly numbers.
- Channel 3 alone is slow — 180 days of drift can accumulate before the check fires.
- Hybrid catches all three drift channels: operator-edited (1) + reality-diverging (2) + operator-blind-spot (3).

**Cross-references:**
- Section 1 PMSupervisor must NOT force consensus — drift channels are independent signals; PMSupervisor synthesizes without collapsing dissent
- Section 4 Q1 structured branches — `thesis_pillars_original` and `scenario_A_base_projections` are emitted at P3 lock with HMAC signature
- Section 5 Q1 pinpoint-cite enforcement — operator's "revise with rationale" requires verbatim source citation matching same standard
- Q4 pre-mortem cadence — same calendar floor; pre-mortem and anchor-drift re-read can fire in same session
- Q3 disposition — "cut position" choice routes through Q3 mode-tuned cut logic

**Implementation handoff:**
- Code: `src/skills/p8-daily-monitor/anchor_drift_detector.py`
- Storage: `anchor_drift_checks` Postgres table; immutable `thesis_pillars_original` JSONB on `memos` table
- HMAC signature ensures original cannot be silently mutated post-lock
- Operator review surface: `/parameters-review` extended with anchor-drift queue tab



## Q6 — Capitulation triggers **[LOCKED]**

**Decision:** (d') Hybrid — cooling-off floor + mode-tuned multi-source + counterfactual VETO authority.

**Distinguishes "genuine kill at peak pain" from "behavioral capitulation you'll regret in 6 months."** Empirical motivation: Odean 1998 finds retail investors who sell at drawdown peaks underperform "diamond-hands" by ~3.4% over next 12 months, yet thematic names hitting >50% drawdown have only ~15% recovery rate (vs 65% for B/B'). Mode polarity matters; counterfactual structural-feature similarity at peak pain is the tiebreaker.

**At peak pain (drawdown vs benchmark > 2× the Q3 cut threshold):**

### Layer 1 — Cooling-off floor (universal, mode-tuned duration)
| Mode | Cooling-off |
|---|---|
| B | 72h |
| B' | 48h |
| C | 24h |

### Layer 2 — Multi-source confirmation (mode-tuned, fires even on Mode C at 2× threshold)
- ≥2 INDEPENDENT kill-criteria fired (BOCPD-correlated triggers collapse to 1 per Section 3 Q3)
- Verbatim primary-source confirmation (10-K, earnings call, regulatory filing, audited disclosure)
- Operator pre-mortem completed within last 30 days (Q4 cadence)

If any missing → cut blocked; operator must escalate or wait.

### Layer 3 — Counterfactual VETO (new — applies all modes including C)
- Section 5 mechanical retrieval queries the **peak-pain archetype catalog** (third archetype category alongside entry-time-success and fraud-failure) using structural features at the peak-pain moment
- Catalog uses TWO-LAYER schema (universal-core 0.7 weight + sector-extensions 0.3 weight when sectors match)
- TBD outcomes excluded from active retrieval; auto-graduate when resolved
- **Veto rules:**
  - If ≥2 of top-3 are SURVIVOR archetype → cut requires explicit operator override (cannot auto-execute; surfaces top-3 matches with verbatim feature comparison)
  - If ≥2 of top-3 are NON-SURVIVOR archetype → cut proceeds per mode polarity
  - If mixed → operator review required
- Veto authority operates ON TOP of mode polarity — can block Mode-C cut-fast bias when survivor pattern dominates (the PLTR-2022 problem)
- Validation: archetype-coverage agreement on 15-case test set (≥80% within ±1; ≥90% on canonical cases)

### Layer 3 veto re-fire policy — Hybrid single-fire + materiality-driven refresh

To prevent the veto from becoming a permanent hold trap OR being defeated by operator-override fatigue:

- **Single-fire per peak-pain event:** Once veto fires on a name, it does NOT re-fire on additional drawdown of the SAME name until either (a) name recovers above original 2× cut threshold, OR (b) materiality-3 event triggers structural-feature refresh
- **M-3-driven refresh:** When Q1 materiality classification escalates to M-3 (e.g., founder departure, cash-runway material change, thesis-pillar break), Q6 peak-pain feature extraction re-runs and counterfactual retrieval re-executes
  - If new top-3 has changed archetype mix → veto re-evaluates per current rules
  - If new top-3 unchanged → veto status unchanged (single-fire still in effect)
- **Why hybrid:** ties veto re-evaluation to ACTUAL structural-feature signal (M-3 = new data refreshing snapshot) rather than time or drawdown depth alone. Drawdown depth alone shouldn't reset veto (a survivor in deep pain may need months to inflect); feature change should
- **Edge case — "founder departed at -85%":** founder-departure event = M-3 materiality → triggers Q6 feature refresh → SURVIVOR pattern weakens (founder_in_place flips to "departed") → top-3 matches shift toward NON-SURVIVOR archetype → veto releases automatically

Schema additions:
```yaml
veto_lifecycle:
  veto_id: uuid
  initial_fire_date: 2026-04-30
  initial_top_3: [...]
  status: active   # active / released-by-recovery / released-by-feature-shift / overridden-by-operator
  m3_refreshes:
    - date: 2026-08-15
      trigger: founder_departure
      new_top_3: [...]
      new_archetype_distribution: { survivor: 0, non_survivor: 2, mixed: 1 }
      veto_status_after: released-by-feature-shift
  operator_override:
    occurred: false
    rationale: null
```

**Peak-pain structural-feature schema (distinct from entry-time features):**
- Founder/insider equity stake direction during drawdown (increasing / flat / decreasing)
- Cash runway at current burn rate (>24mo / 12-24mo / <12mo)
- Customer NPS / cohort retention trend (holding / eroding / collapsed)
- Product engagement metrics decoupling from price (yes / no / N/A)
- Industry structural tailwind state (intact / weakening / reversed)
- Founder/key-person still in place (yes / departed)
- Margin trajectory at trough (improving / stable / deteriorating)
- Revenue still growing at trough (yes / flat / declining)

These features are the discriminators. Catalog construction must populate them at the historical peak-pain moment, not entry.

**Schema additions to disposition_evaluation:**

```yaml
peak_pain_evaluation:
  triggered: true
  drawdown_vs_benchmark_pp: 28.4
  cut_threshold_pp: 12       # Q3 mode B' threshold
  multiple_of_threshold: 2.37
  cooling_off:
    duration_h: 48
    started_at: 2026-04-30T16:00:00Z
    expires_at: 2026-05-02T16:00:00Z
  multi_source_confirmation:
    independent_kill_criteria_count: 1   # growth + multiple-compression collapsed by BOCPD as 1
    verbatim_primary_source: false
    operator_premortem_within_30d: true
    all_satisfied: false
    cut_blocked_reason: "Only 1 independent kill-criterion + missing verbatim primary-source"
  counterfactual_retrieval:
    catalog_queried: peak_pain_archetypes_v0_1
    top_3_matches:
      - case_id: NVDA-2008
        archetype: SURVIVOR
        similarity: 0.81
        matching_features: [founder_in_place, insider_stake_holding, real_revenue_growing, industry_tailwind_intact]
      - case_id: AMD-2014
        archetype: SURVIVOR
        similarity: 0.74
        matching_features: [founder_replaced_by_competent_operator, cash_runway_24mo, product_engagement_holding]
      - case_id: AAPL-1997
        archetype: SURVIVOR
        similarity: 0.71
        matching_features: [founder_returned, sticky_customer_base, real_revenue]
    survivor_count_in_top_3: 3
    non_survivor_count_in_top_3: 0
    ndcg_at_3: 0.78
    veto_invoked: true
    cut_status: requires_explicit_operator_override
    operator_decision: pending
```

**Catalog build dependency for v0.1 launch:**
- Peak-pain archetype catalog (target: ~25-40 cases, balanced survivors and non-survivors across sectors)
- Structural features extracted at peak-pain moment using Section 5 Q3 3-LLM iterative-consensus pipeline
- Calibration: extends Section 5 Q6 test set with 10-15 peak-pain stratified cases
- **Research sprint dispatched 2026-04-29 — 14 parallel subagents covering tech/SaaS, semis, consumer-discretionary, consumer-brands, fintech, biotech, industrial, energy, comms-media, international/EM, EV/autos, REITs, recent-IPO/SPAC, crypto-adjacent**

**Cross-references:**
- Section 1 mode-aware discipline + relative-to-benchmark drawdown — 2× threshold here is wider than auto-tighten (Section 1) and wider than Q3 cut threshold; layered defense at increasing pain levels
- Section 3 Q3 BOCPD — used to test independence of kill-criteria
- Section 4 Q3 hybrid kill-criteria — `cited_kill_criterion_id` linkage feeds independence check
- Section 5 Q3 3-LLM iterative-consensus extraction — same pipeline applied to peak-pain catalog construction
- Section 5 Q4 event-driven adds — peak-pain catalog gets new entries when names hit >50% drawdown and the resolution becomes known
- Section 5 Q6 ~50-case test set — extends with peak-pain stratified cases
- Section 6 Q4 pre-mortem cadence — pre-mortem within 30 days is a multi-source-confirmation requirement
- L7 smart-money lane — insider stake direction is L7 telemetry; feeds peak-pain feature extraction

**Implementation handoff:**
- Code: `src/skills/p8-daily-monitor/peak_pain_evaluator.py`
- Catalog storage: `peak_pain_archetypes` Postgres table; HMAC-signed; versioned
- Veto authority: cannot be silently bypassed — operator override requires explicit reason logged + verbatim citation of why this case differs from survivor matches
- Prompt versioning: peak-pain feature-extraction prompt at `src/skills/p8-daily-monitor/prompts/peak_pain_features_v0_1.md`

---

## Section 6 — All 6 questions LOCKED.

| Q | Decision | Status |
|---|---|---|
| Q1 | Materiality + structured event log per name (Sonnet/Opus, no Haiku) | LOCKED |
| Q2 | Hybrid routing (predetermined floor + LLM judge for M-2 middle) | LOCKED |
| Q3 | Mode-tuned cut thresholds (B hold-bias / B' moderate / C cut-fast) | LOCKED |
| Q4 | Hybrid pre-mortem (mode-tuned calendar floor + 4 event triggers) | LOCKED |
| Q5 | Hybrid anchor-drift (3 independent channels) | LOCKED |
| Q6 | (d') Cooling-off + multi-source + counterfactual VETO authority | LOCKED |

**Outstanding work:** peak-pain archetype catalog construction (research sprint dispatched).


---

**Status:** Q1 locked. Proceeding to Q2.
