# Operator Reference — v3.0

**Status:** authoritative for v0.1 operations.
**Companion to:** `docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md` (v3 spec, frozen 2026-04-29).
**Audience:** the operator, reading cold. Assumes familiarity with the v3 spec but not with the implementation.

This document consolidates everything the operator needs to drive the system day-to-day: slash commands, schema fields, watchlist operations, setup procedure, daily/quarterly/annual cadences, failure-mode reference, and operator-locked exclusions. Per Section 5.5 of the v3 spec, onboarding is documentation-only — there is no setup wizard. Read this and the v3 spec; everything else lives in the section consensus docs (`docs/section-N-consensus.md`) for full Q&A provenance.

---

## 1. Slash command reference

The system is operated entirely through slash commands. All commands listed below have a corresponding `.claude/commands/<name>.md` definition; commands flagged **(deferred)** are spec-mandated but not yet implemented at v0.1. The 12 implemented commands cover the entire daily operational loop.

### 1.1 Master orchestrator

| Command | `/run [auto\|daily\|weekly\|monthly\|quarterly\|build\|status]` |
|---|---|
| **Purpose** | Single entry point. Auto-detects phase (v0.1 build / v0.5+ operations) from `BUILD_LOG.md` and dispatches to the correct sub-cadence. v0.1 surfaces step status; v0.5+ runs daily/weekly/monthly/quarterly cadences. |
| **When to use** | Every session-start. The default workflow. |
| **Example** | `/run` (auto-detect) · `/run status` (read-only, no execution) |
| **Expected output** | Phase header, step progress, checkpoint readiness, external-dependency status, next-action recommendations. |
| **Reference** | `.claude/commands/run.md` · BUILD_LOG decision 5 |

### 1.2 Daily operations

| Command | `/daily-monitor` |
|---|---|
| **Purpose** | The slow layer's daily heartbeat. Sweeps news + filings for every watchlist name, applies two-tier classification (Tier 1 Sonnet → Tier 2 Sonnet/Opus), produces the daily digest, fires M-3 escalations. (Note: the spec mandates Sonnet/Opus only — no Haiku — per Section 4.5 Q1 model constraint.) |
| **When to use** | Daily, post-market close + 30 min. |
| **Example** | `/daily-monitor` (no arguments — runs against full watchlist) |
| **Expected output** | Per-ticker materiality scores + justifications, cross-cutting observations, escalations, predictions resolved today, calibration trends, upcoming catalysts. |
| **Reference** | `.claude/commands/daily-monitor.md` · v3 spec §4.5 |

| Command | `/disposition [--ticker <T>] [--mode B\|B_prime\|C] [--toggle-primary <T> <horizon>]` |
|---|---|
| **Purpose** | Multi-horizon disposition view: Short ≤3mo / Mid 3-12mo / Long 12+mo, with mode-anchored primary horizon expanded by default (B → Long, B' → Mid, C → Short). Integrated mode-fit dashboard renders per-name `mode \| realized_252d_vol \| mode_band \| flag_status`. |
| **When to use** | Daily, after `/daily-monitor`, to see current state of every watchlist name. Also when triaging mode-vol-band drift. |
| **Example** | `/disposition` · `/disposition --ticker NVDA` · `/disposition --mode B_prime` · `/disposition --toggle-primary NVDA short` (session-only override) |
| **Expected output** | One row per watchlist name with three horizon columns; mode-fit dashboard at the bottom flagging `pending_reclassification` / `rule_output_mismatch` / `vol_band_inconsistency`. |
| **Reference** | `.claude/commands/disposition.md` · v3 spec §4.6 Q2, §2.2 (mode silent-failure detection) |

### 1.3 Audit + alerts

| Command | `/audit-trail <rec_id \| ticker> [--stage <stage>] [--latest] [--verify] [--strict]` |
|---|---|
| **Purpose** | Layered drill-down audit per Section 5.2. Top-level `decision_path` with `drill_link` per stage; per-stage drill on demand; HMAC chain verification on demand. Tamper-evidence surfaces as M-2 system event. |
| **When to use** | When operator wants to inspect why a recommendation was made — debate stage, kill-criteria stage, counterfactual veto stage, materiality classification. Also for HMAC-chain integrity checks (launch gate). |
| **Example** | `/audit-trail 8f2e1234-...` (top-level) · `/audit-trail AAPL --latest` (resolve to most recent rec) · `/audit-trail 8f2e1234-... --stage stage_2_debate` · `/audit-trail 8f2e1234-... --verify --strict` |
| **Expected output** | Top-level summary or per-stage drill payload; with `--verify`, a chain-validation banner (`UNVERIFIED` / `VERIFIED` / `TAMPER-EVIDENT`). |
| **Reference** | `.claude/commands/audit-trail.md` · v3 spec §5.2, §7 Q4 |

| Command | `/alerts [--severity 2\|3] [--ticker TKR] [--type ALERT_TYPE] [--since ISO_TS]` |
|---|---|
| **Purpose** | List unacknowledged push alerts (M-2 + M-3) from the `unread_alerts` queue. Same rows surface automatically at session-start; `/alerts` is for ad-hoc review. |
| **When to use** | Whenever operator wants to triage backlog. |
| **Example** | `/alerts` · `/alerts --severity 3` · `/alerts --type counterfactual_veto` |
| **Expected output** | Markdown list ordered by severity DESC then `created_at` DESC, with `alert_id` and `drill: /audit-trail <rec_id>` deep-link per row. |
| **Reference** | `.claude/commands/alerts.md` · v3 spec §5.3 |

| Command | `/ack <alert_id \| all>` |
|---|---|
| **Purpose** | Acknowledge an alert (single or bulk). Idempotent. Updates `unread_alerts.acknowledged_at` + `acknowledged_by`; never deletes. |
| **When to use** | After triaging an M-2 / M-3 surfaced by `/alerts`. |
| **Example** | `/ack 8f2e1234-aaaa-bbbb-cccc-dddddddddddd` · `/ack all` |
| **Expected output** | `Acknowledged <id>` or `Acknowledged N alert(s)`. Re-acking returns exit 2 with "no unacknowledged alert" message. |
| **Reference** | `.claude/commands/ack.md` · v3 spec §5.3 |

| Command | `/system-health` |
|---|---|
| **Purpose** | Single page of "what's broken / what's queued". Degraded MCPs, queued recoveries (email queue depth, queued-for-session-push), active push-alert backlog, disputed catalog entries, `system_errors` last 7 days. |
| **When to use** | End-of-day; before invoking any downstream command that might be silently impaired. |
| **Example** | `/system-health` (no arguments) |
| **Expected output** | Markdown block, top-to-bottom: degraded MCPs → queues → backlog → catalog disputes → 7-day error grouping. Read-only — no mutations. |
| **Reference** | `.claude/commands/system-health.md` · v3 spec §5.4, §7.5, Phase 4 Q9 |

### 1.4 Research + intervention

| Command | `/research-company <ticker>` |
|---|---|
| **Purpose** | Manual P3 + P4 funnel invocation. Orchestrates CompanyDeepDive → BearCase → PMSupervisor on a single name. Output is a watchlist decision (ADD / REJECT / WATCH) with conviction and recommended size band. |
| **When to use** | New candidate identified for watchlist; M-3 escalation forces re-underwrite; ad-hoc operator request. |
| **Example** | `/research-company NVDA` |
| **Expected output** | Final decision + conviction + size band + dissent acknowledgement + reasoning trace + artifact pointers. Cost: ~$50-95 per invocation. |
| **Reference** | `.claude/commands/research-company.md` · v3 spec §4.3, §4.8 |

| Command | `/wash-sale-harvest <ticker>` |
|---|---|
| **Purpose** | Operator-driven tax-aware decisions. Three legitimate paths: cash gap / non-substantially-identical proxy / disclosure. Per v2-final §2.3. |
| **When to use** | Held position currently at a loss + operator wants to harvest. System does NOT auto-surface; operator initiates. |
| **Example** | `/wash-sale-harvest NVDA` |
| **Expected output** | Pre-sale window scan, post-sale window plan, path recommendation. |
| **Reference** | `.claude/commands/wash-sale-harvest.md` |

| Command | `/premortem <ticker>` |
|---|---|
| **Purpose** | Trigger or surface a pre-mortem session per v3 §4.5 Q4. Mode-tuned cadence (B 180d / B' 120d / C 60d) + 4 event triggers (thesis-confirmation, consecutive M-2, auto-tighten threshold, mode reclass). LLM devil's-advocate (Opus) generates 3 plausible failure modes operator may have missed. |
| **When to use** | Cadence-driven (auto) or on-demand when operator wants to stress-test a watchlist thesis. |
| **Example** | `/premortem NVDA` |
| **Expected output** | 3 devil's-advocate failure modes + HMAC-signed `premortem` row written via `PREMORTEM_HMAC_SECRET`. |
| **Reference** | `.claude/commands/premortem.md` · v3 spec §4.5 Q4, §5.4 |

### 1.5 Spec-mandated commands not yet implemented (deferred)

The v3 spec §5.4 lists four additional slash commands. Wave D.4 cleanup landed minimal markdown wrappers for all four; the full structured workflows remain deferred to v0.5+.

| Command | Status | Workaround |
|---|---|---|
| `/parameters-review` **(v0.1 STUB)** | Spec §5.4, §6.3. Cadence-driven parameter recalibration; system proposes, operator approves. | v0.1 surface = read-only summary + override-pattern suggest only. Full proposal generation (90-day counterfactual ledger + parameter-vs-outcome attribution + approve/modify/reject UI) deferred to v0.5+. See `src/parameters_review/README.md`. |
| `/spec-approve <version>` **(v0.1 minimal)** | Spec §5.4, §8 sign-off. Operator sign-off on spec revisions. | Wave D.4 wrapper writes an HMAC-attested attestation to `docs/superpowers/specs/v<version>-signoff-attestation.md` matching the v3.0 template. `--verify` mode (HMAC chain replay against attestation content) deferred to v0.5+. |
| `/launch-confirm <gate_name>` **(v0.1 minimal)** | Spec §5.4, §7.3. Operator sign-off on launch gates. | Wave D.4 wrapper appends an HMAC-attested row to `docs/superpowers/launch-readiness-log.md` (append-only). `--verify` mode deferred to v0.5+. |

### 1.6 Other implemented slash commands (carried from v2-final)

The following commands predate v3 and remain operational. They are not on the v3 §5.4 critical surface but are useful tools.

| Command | Purpose |
|---|---|
| `/entry-check <ticker>` | EntryTimingModel evaluation; returns STRONG_ENTRY / ENTRY_OK / WAIT / DO_NOT_ENTER + invalidation level. Per v2-final §2.2. |
| `/exit-check <ticker>` | ExitSignalModel for held position; returns NONE / TRIM / FULL_EXIT / WAIT_FOR_LT_THRESHOLD with tax-cost estimate. Per v2-final §2.3. |
| `/size <ticker>` | PositionSizingModel recommendation; returns dollar size + weight % with full sizing decomposition. Per v2-final §2.4. |
| `/macro-cycle` | Macro/cycle view refresh. Quarterly full update; monthly delta; daily on major regime indicators. |
| `/quarterly-reunderwrite [<ticker>]` | Re-underwrite a held name (or all watchlist names). Triggered automatically by M-3 escalations from `/daily-monitor`; can also be invoked manually. |
| `/backtest <memo>` | BacktestingFramework on a memo or memo set. DSR + PBO + pre/post-cutoff Sharpe split. Per v2-final §2.6. Some paths deferred pending Sharadar PIT. |
| `/evaluate <output>` | Run the Evaluator process rubric against a specific output. Returns hard-gate pass/fail + soft scores. |
| `/checkpoint <N>` | Guided checkpoint artifact creation for v0.1 phase gates per `implementation-sequencing.md` §6. |
| `/grill-me` | Structured Q&A consensus session for design decisions. |

---

## 2. Schema field reference

Postgres tables, grouped by purpose. Every table has at minimum: `parameters_version` (FK to `parameters`), `created_at`, and an audit fingerprint where applicable. Append-only by default; per-table state-mutability rules called out below.

### 2.1 Decision-model state

#### `parameters` — migration 004

Versioned config. Append-only. One row per `(parameter_key, effective_at)` tuple. Active value at time T = the row with the latest `effective_at <= T`.

| Column | Type | Reads / writes |
|---|---|---|
| `version_id` | UUID PK | All v3 tables FK here |
| `parameter_key` | TEXT | Examples: `mode_classifier.thresholds`, `bocpd.firing_thresholds`, `peak_pain.retrieval.weights` |
| `value` | JSONB | Scalar / array / prompt text / weight matrix |
| `effective_at` | TIMESTAMPTZ | Activation timestamp |
| `description`, `change_rationale`, `approved_by` | TEXT | Mandatory; reconstruct WHY |

**Read by:** every module that needs config (mode_classifier, p3_mechanical_scorer, p4_debate, peak_pain_catalog, l4_daily_monitor, regime_sidecar). **Write by:** `/parameters-review` (deferred); manual `mcp__postgres__execute` at v0.1.

#### `regime_state` (view) — migration 005, 020, 021

Latest classification per dimension. Resolves Phase 2 Finding #16. A view over `regime_classification_history`.

#### `regime_classification_history` — migration 005, 020 (added `bocpd_short_run_mass`), 021 (renamed dim 2)

Append-only daily snapshot. One row per `(classification_date, dimension_id)` tuple. Six dimensions (1=EBP, 2=cycle_2y3m_slope, 3=VRP, 4=MP/liquidity, 5=DTWEXBGS, 6=stock-bond corr).

| Column | Type | Notes |
|---|---|---|
| `classification_date`, `dimension_id`, `dimension_name` | DATE / INT / TEXT | Composite key |
| `bocpd_change_probability` | NUMERIC | Canonical Adams-MacKay marginal `P(r_t=0|x_{1:t})`; audit / academic provenance only |
| `bocpd_short_run_mass` | NUMERIC | Cumulative `P(r_t<10|x_{1:t})`; PRIMARY firing signal (>0.7 sustained 2+d → M-2; >0.95 single-day → M-3 + alert) |
| `state_probabilities` | JSONB | Distribution per state (NOT a point classification) |
| `cold_start` | BOOLEAN | First 90 trading days flag |

**Read by:** `regime_sidecar`, `l4_daily_monitor.refresh_emitter`, `l4_daily_monitor.cut_evaluator` (Mode C). **Write by:** `regime_sidecar` daily run.

#### `scenarios` — migration 006

P2 probabilistic-scenario branches per trend theme. UPDATE allowed on (probability, kill_criteria_structured, last_updated_at) per Q5 revision cadence; DELETE blocked.

| Column | Type | Notes |
|---|---|---|
| `scenario_id` | UUID PK | Server-generated |
| `theme_id` | UUID | Stable handle for grouping siblings |
| `probability` | NUMERIC | Bounded [0.05, 0.95]; 0.05-step quantization; sibling sum = 1.0 (write-time linter) |
| `kill_criteria_structured` | JSONB | Array of {criterion_id, type, template_id, variable, comparator, threshold, deadline, ...} |
| `kill_criteria_narrative`, `value_drivers`, `regime_fit`, `key_dates_to_watch` | TEXT / JSONB | |

**Read by:** P2 scenario writer, kill-criteria firing scanner. **Write by:** P2 emitter (LLM regenerates on regime-shift / kill-fire / operator invocation).

#### `watchlist` — migration 007

P5 research-approved names. State table keyed by ticker. UPDATE allowed (conviction / mode / kill criteria revised over name's life); DELETE blocked.

| Column | Type | Notes |
|---|---|---|
| `ticker` | TEXT PK | Single-mode-per-name model |
| `mode` | TEXT | B / B' / C |
| `company_quality_flag` | TEXT | HIGH / STANDARD (conviction multiplier input) |
| `conviction`, `size_band_initial_pct`, `size_band_max_pct` | NUMERIC | |
| `thesis_pillars_original` + `thesis_pillars_original_hmac` | JSONB / TEXT | HMAC-signed at write time (`WATCHLIST_HMAC_SECRET`); anchor-drift channel-1 verifies untampered |
| `scenario_A_base_projections` + `scenario_A_base_projections_hmac` | JSONB / TEXT | Same HMAC contract; channel-2 outcome-divergence reads |
| `kill_criteria` | JSONB | |

**Read by:** `/disposition`, `/research-company`, `p6_disposition`, `anchor_drift`. **Write by:** `p5_watchlist.adder`, `watchlist.hmac_producer`.

#### `positions` — migration 007, 019 (`first_acquired` nullable)

Current portfolio state, synced from broker MCP. UNIQUE(ticker, broker, account_id_hash) — same name in two accounts gets two rows. UPDATE allowed (broker overwrites on poll); DELETE blocked.

| Column | Type | Notes |
|---|---|---|
| `ticker`, `broker`, `account_id_hash` | TEXT | Composite UNIQUE |
| `quantity`, `cost_basis`, `current_price`, `current_value` | NUMERIC | |
| `first_acquired` | DATE NULLABLE | Schwab does not return per-lot dates; nullable until position-history replay backfills |

**Read by:** `/disposition`, `p6_disposition`, `/wash-sale-harvest`. **Write by:** `mcp__broker__get_positions` poll loop.

### 2.2 Decision-event log

#### `execution_recommendations` — migration 008

P5/P9 emissions with full §4.6 Q1 schema + Phase 4 Q2 conviction rollup. Append-only EXCEPT narrow UPDATEs on conviction-pending state-machine columns.

| Column | Type | Notes |
|---|---|---|
| `recommendation_id` | UUID PK | |
| `ticker`, `date`, `recommendation` | TEXT / DATE / TEXT | recommendation ∈ {BUY, HOLD, TRIM, SELL} |
| `conviction` | TEXT | HIGH / MEDIUM / LOW (rollup precedence: LOW > HIGH > MEDIUM) |
| `conviction_breakdown` | JSONB | debate_consensus, kills_fired, counterfactual_top_3, mode_certainty, drift_channels |
| `mode` | TEXT | B / B' / C |
| `sizing_suggestion` | JSONB | initial_pct, max_pct, base_band, applied_overlays, net_multiplier, funding_required |
| `execution_context` | JSONB | current_price, fair_value_estimate, near_term_catalysts, suggested_pacing, technical_signals, risk_flags |
| `trigger_metadata` | JSONB | triggered_by ∈ {mode_cadence_floor, m2_event, m3_event, new_candidate} |
| `pending_transition`, `pending_target`, `flip_count_30d`, `frozen_pending_review` | conviction-hysteresis state machine | The only mutable columns |
| `audit_signature` | TEXT NOT NULL | HMAC-SHA256 over canonical row payload using `AUDIT_HMAC_KEY` |

**Read by:** `/audit-trail`, `/disposition`, `/alerts` (deep-link rec_id). **Write by:** `p7_recommendation_emitter.emitter`.

#### `position_history` — migration 007

Append-only ledger of every fill / dividend / split / transfer. UPDATE + DELETE blocked.

| Column | Type | Notes |
|---|---|---|
| `event_id` | UUID PK | |
| `ticker`, `event_type`, `event_timestamp` | TEXT / TEXT / TIMESTAMPTZ | event_type ∈ {BUY, SELL, DIVIDEND, SPLIT, TRANSFER} |
| `quantity`, `price`, `cash_amount` | NUMERIC | |
| `recommendation_ref` | UUID NULLABLE | FK to `execution_recommendations`; null on operator override / manual fill |
| `divergence_from_recommendation` | JSONB | Captures suggested-vs-actual diff |

**Read by:** `fill_divergence` capture, position cost-basis replay. **Write by:** `mcp__broker__poll_for_fills`.

#### `audit_provenance` — migration 008

Per-stage structured log with HMAC chain. Fully append-only. Each row carries `parent_audit_id` pointing to a prior chain row (chain-pointer integrity).

| Column | Type | Notes |
|---|---|---|
| `audit_id` | UUID PK | |
| `recommendation_id` | UUID FK | |
| `stage` | TEXT | stage_1_mechanical / stage_2_debate / stage_3_kill_criteria / stage_4_counterfactual / materiality |
| `payload` | JSONB | Verbatim quotes, agent outputs, retrieval results, kill-criteria evaluation chain |
| `parent_audit_id` | UUID NULLABLE | Chain pointer; created_at(parent) ≤ created_at(child) |
| `hmac_signature` | TEXT NOT NULL | HMAC over canonical payload + parent reference using `AUDIT_HMAC_KEY` |

**Read by:** `/audit-trail`. **Write by:** every stage emitter (`p3_mechanical_scorer`, `p4_debate`, `l4_daily_monitor`, `counterfactual_veto`).

#### `daily_refresh_log` — migration 009

One row per (ticker, date) tuple. Append-only.

| Column | Type | Notes |
|---|---|---|
| `date`, `ticker`, `mode` | DATE / TEXT / TEXT | |
| `materiality` | SMALLINT | 1 / 2 / 3 |
| `materiality_label` | TEXT GENERATED | `'M-1'` / `'M-2'` / `'M-3'` |
| `events`, `regime_context_at_eval`, `recommended_action`, `llm_call_metadata` | JSONB | Per §4.5 Q1 schema |

**Read by:** `/daily-monitor` (digest composition), `/disposition`. **Write by:** `l4_daily_monitor.refresh_emitter`.

#### `mode_classifications` — migration 008

Per-name layered classifier outputs (Stage 1 rule + Stage 2 quality flag + Stage 3 LLM tie-breaker). Append-only.

| Column | Type | Notes |
|---|---|---|
| `classification_id` | UUID PK | |
| `ticker`, `classified_at` | TEXT / TIMESTAMPTZ | |
| `bin` | TEXT | B / B' / C |
| `quality_flag` | TEXT | HIGH / STANDARD |
| `mode_certainty` | TEXT | rule_clean / llm_tiebreaker (annotation, NOT a conviction-bucket determinant) |
| `stage_outputs`, `evidence_quotes`, `prior_classification_id` | JSONB / JSONB / UUID | |

**Read by:** `p7_recommendation_emitter`, `/disposition` (mode-fit dashboard). **Write by:** `mode_classifier.orchestrator`.

#### `unread_alerts` — migration 009, 017 (alert-type extension)

Push-alert queue. State table — UPDATEs allowed only on (acknowledged_at, acknowledged_by, email_sent_at, email_send_attempts, claude_session_pushed_at). DELETE blocked.

| Column | Type | Notes |
|---|---|---|
| `alert_id` | UUID PK | |
| `ticker`, `severity`, `alert_type` | TEXT / SMALLINT / TEXT | severity ∈ {2, 3} only |
| `alert_type` enum | | `materiality_m3`, `counterfactual_veto`, `anchor_drift`, `kill_criterion`, `mode_reclass`, `drawdown_2x_threshold`, `materiality_m2` (added 017), `calibration_drift` (added 017), `system_error` |
| `payload`, `recommendation_id_ref` | JSONB / UUID | |
| `email_sent_at`, `email_send_attempts`, `acknowledged_at`, `acknowledged_by` | state | `MAX_EMAIL_ATTEMPTS=4` (DECISION LOCK; Phase 4 Q9) |

**Read by:** `/alerts`, `/system-health`, session-start push. **Write by:** `alert_channels.session_push`, `alert_channels.email_sender`.

#### `materiality_events` — migration 009

LLM-classified event log. One row per classification. Append-only.

| Column | Type | Notes |
|---|---|---|
| `event_id` | UUID PK | |
| `ticker`, `materiality`, `verbatim_quote`, `source_id` | composite | |
| `model`, `prompt_version` | TEXT | Sonnet/Opus only — no Haiku |

**Read by:** `materiality_classifier_drift`, `/audit-trail` (materiality stage). **Write by:** `l4_daily_monitor.materiality_classifier`.

#### `counterfactual_retrievals` — migration 011

Top-3 retrieval results per veto-trigger event. Append-only.

| Column | Type | Notes |
|---|---|---|
| `retrieval_id` | UUID PK | |
| `ticker`, `triggered_at`, `trigger_reason` | composite | |
| `top_3_case_ids` | TEXT[] | Catalog case IDs, btree-indexable |
| `archetype_distribution` | JSONB | `{"SURVIVOR": 2, "NON-SURVIVOR": 1}` |
| `veto_outcome` | TEXT | proceed / blocked / operator_review |

**Read by:** `counterfactual_veto.layer3_veto`, peak-pain catalog tail-validation lazy runner. **Write by:** `counterfactual_veto.retrieval`.

#### `veto_lifecycle` — migration 011

Section 6 Q6 PB#5 lifecycle states. Append-only; `m3_refreshes` JSONB array captures re-fire events.

#### `anchor_drift_checks` — migration 010

3-channel drift detector outputs. Append-only.

| Column | Type | Notes |
|---|---|---|
| `check_id` | UUID PK | |
| `ticker`, `checked_at` | composite | |
| `channel_1_pillar_drift` (LLM-diff), `channel_2_outcome_divergence` (quantitative), `channel_3_periodic_reread` (calendar floor) | JSONB each | |
| `any_triggered` | BOOLEAN | OR of the three |
| `forced_review` | JSONB | `operator_decision` ∈ {reaffirm, revise_with_rationale, cut, NULL=pending} per migration 018 |

**Read by:** `/disposition` flag computation. **Write by:** `anchor_drift.orchestrator`.

#### `anchor_drift_review_decisions` — migration 018

Sidecar table preserving anchor_drift_checks append-only invariant. Row presence = decision committed; absence = pending. Append-only.

#### `premortem` — migration 012, 016 (HMAC column promotion)

Mode-tuned cadence + event-trigger pre-mortem ledger. Append-only.

| Column | Type | Notes |
|---|---|---|
| `premortem_id` | UUID PK | |
| `ticker`, `triggered_by` | TEXT | triggered_by ∈ {calendar_floor, thesis_confirmation, consecutive_m2, auto_tighten, mode_reclass} |
| `failure_modes`, `operator_decisions`, `llm_assist_metadata` | JSONB | Opus required for high-stakes contestable judgment |
| `hmac_signature`, `signed_at` | TEXT / TIMESTAMPTZ | Promoted to first-class column in 016; signed using `PREMORTEM_HMAC_SECRET` |

**Read by:** `/disposition`, premortem cadence checker. **Write by:** `premortem_scheduler.recorder`.

### 2.3 Calibration capture

#### `operator_overrides` — migration 013

Every operator deviation from a system rec, with rationale + counterfactual baseline. Append-only.

#### `recommendation_outcomes` — migration 013

T+30d / T+90d / T+1y returns vs benchmark. STATE table — three resolution windows close at different times. GENERATED ALWAYS columns: `delta_vs_benchmark_30d/90d/1y`.

#### `override_outcomes` — migration 013

STATE — actual vs counterfactual baseline. GENERATED ALWAYS column: `operator_was_better`.

#### `debate_consensus_history` — migration 013

5-style outputs + dissents. Append-only snapshot per debate.

#### `fill_divergence` — migration 013

Suggested vs actual fill stats. Append-only. GENERATED ALWAYS column: `pct_divergence`.

#### `calibration_test_results` — migration 015

Periodic test runs against canonical gold-standard sets. Append-only. `catalog_version_hash` pins the catalog snapshot used.

#### `system_errors` — migration 014

MCP failures, retries, escalations. Append-mostly: UPDATE allowed only on (resolution, resolved_at, retry_count, escalated_to_alert). Per Section 7.5 / Section 8 Q6 — never silent-fail.

#### `mode_vol_checks` — migration 010

Phase 4 Q5 — semi-annual mode-implied-vol silent-failure detection. Append-only.

#### `materiality_classifier_drift` — migration 010

Phase 4 Q8 — quarterly drift watch + rolling 30-event gold standard + confidence-distribution monitoring. Append-only.

### 2.4 Catalogs

#### `peak_pain_archetypes` — migration 011, 016 (HMAC column promotion)

The catalog itself. ~160 cases across 15 sectors + 4 pre-2008 expansion eras. Two-layer schema: `universal_core_features` (6 mandatory features) + `sector_extensions` (per-sector tie-breaker).

| Column | Type | Notes |
|---|---|---|
| `case_id` | TEXT PK | Human-readable, e.g., 'NVDA-2008' |
| `universal_core_features`, `sector_extensions` | JSONB each | |
| `universal_core_consensus` | JSONB | Per-feature HIGH/LOW confidence (Phase 4 Q4 feature-typed) |
| `outcome` | TEXT | SURVIVOR / DILUTED-SURVIVOR / NON-SURVIVOR / TBD |
| `consensus_status` | TEXT | clean / disputed (excluded from active retrieval if disputed) |
| `last_touched_in_retrieval` | TIMESTAMPTZ | Hygiene marker |
| `hmac_signature`, `signed_at` | TEXT | Promoted in 016; `PEAK_PAIN_HMAC_KEY` |

**Read by:** `counterfactual_veto.retrieval` (similarity scoring), `/system-health` (disputed list). **Write by:** `peak_pain_catalog.persistence` (priority + lazy 3-LLM consensus).

#### `counterfactual_ledger` — migration 003

32 fraud-signature named cases + 10 archetypes. Pre-existing from v2-final (Tier 2).

---

## 3. Watchlist operations

The most common operator tasks, mapped to their entry points.

### 3.1 Add a name

1. `/research-company <ticker>` — runs the full P3 + P4 funnel.
2. If output is `ADD`: the `p5_watchlist.adder` writes a `watchlist` row with `mode`, `conviction`, `size_band_*`, `kill_criteria`, `thesis_pillars_original`, and `scenario_A_base_projections`. The HMAC fields are populated by `watchlist.hmac_producer` using `WATCHLIST_HMAC_SECRET`.
3. The name appears in `/disposition` immediately and starts receiving `/daily-monitor` sweeps the next session.

### 3.2 Reaffirm a thesis

When `anchor_drift_checks.any_triggered = true`, the operator must pick one of three terminal decisions (per migration 018: 'pending' is no longer valid):

- **Reaffirm** — operator writes a row to `anchor_drift_review_decisions` with `operator_decision='reaffirm'` plus rationale. The original `thesis_pillars_original` HMAC remains valid; the name continues normal cadence.
- **Revise with rationale** — operator updates the watchlist row's pillars + scenario_A projections (NEW HMAC will be computed at next write). The original pillars remain in the audit chain via `audit_provenance`. Verbatim citation is required in rationale.
- **Cut** — exit triggered through `/exit-check` or the P9 exit flow.

### 3.3 Cut a position

Cuts go through P9 exit logic. Three triggers:

1. **Mode-tuned cut threshold** (§4.5 Q3) — driven by `l4_daily_monitor.cut_evaluator`.
2. **Capitulation 2× threshold** (§4.5 Q6) — Layer 1 cooling-off → Layer 2 multi-source confirm → Layer 3 counterfactual veto. Veto can BLOCK cuts when ≥2 of top-3 archetypes are SURVIVOR (the PLTR-2022 problem).
3. **Operator override** — manual cut via the broker. The fill is detected by `mcp__broker__poll_for_fills`, written to `position_history`, and reconciled against any prior recommendation. Divergence captured in `fill_divergence`.

### 3.4 Override a recommendation

Whenever the operator's action diverges from `execution_recommendations`, an `operator_overrides` row is written with `rationale` + counterfactual baseline. The T+90d / T+1y outcomes resolve into `override_outcomes` and feed the `system_vs_operator_brier` view (per Phase 4 Q6) for cell-level calibration sign convention. If a cell shows >50% override AND negative-Brier, an M-2 system event fires.

### 3.5 Reclassify mode

Two paths:

1. **Per-name quarterly re-classification** — `mode_classifier.recheck` runs Stage 1 against current data. If output disagrees with stored mode, `/disposition` flags `rule_output_mismatch` and a pre-mortem becomes mandatory (§4.5 Q4 trigger 4) before the new mode commits to `watchlist`.
2. **Mode-implied-vol semi-annual check** — `mode_vol_checks` rows; >2σ outside mode band for 2 consecutive checks → `vol_band_inconsistency` flag.

Single-mode-per-name watchlist data model (§2.2) — same name cannot have two modes simultaneously. Pre-mortem mandatory before commit.

---

## 4. Setup procedure

First-time operator tasks, in order. Each item maps directly to a §7.1 hard launch gate or §7.3 sign-off.

### 4.1 Apply Postgres migrations 001-022

```sh
# From repo root, with .env populated:
for f in db/migrations/0{01..22}_*.sql; do
  PGPASSWORD="$POSTGRES_PASSWORD" psql \
    -h 127.0.0.1 -p "$POSTGRES_PORT" \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -v ON_ERROR_STOP=1 -f "$f"
done
```

All migrations are idempotent (`CREATE TABLE IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS` / `DROP TRIGGER IF EXISTS`). Re-run safe.

### 4.2 Broker MCP — REMOVED FROM v0.1 PLAN (2026-05-01)

`broker_mcp_oauth` was removed from the launch gate set per operator decision 2026-05-01. Operator's actual venue is Gate.io tokenized US equities (xStocks via Backed Assets / Jersey SPV); the conventional brokerage architecture (Schwab OAuth → positions endpoint) doesn't fit. v0.1 operates research-only without an automated broker connection — operator manually maintains `watchlist` rows when they trade.

`src/mcp/broker_mcp/` code is retained as a scaffold for v0.5+ revival (either a `CryptoExchangeAdapter` for Gate.io's public REST/WebSocket API or a Plaid-based positions feed). No setup steps required at v0.1.

Effects on launch gates: count is **32** (was 33). See `docs/superpowers/launch-readiness-log.md` for HMAC-attested record.

### 4.3 Set HMAC secrets in `.env`

Four distinct scopes (each module's HMAC scope is independent; ALL share the canonical-payload contract implemented in `src/audit_trail/hmac_verify.py`). All four are enumerated in `.env.example` (Wave D.4 cleanup) — copy that file to `.env` and fill in generated values:

```
AUDIT_HMAC_KEY=                # audit_provenance + execution_recommendations
PEAK_PAIN_HMAC_KEY=            # peak_pain_archetypes
PREMORTEM_HMAC_SECRET=         # premortem
WATCHLIST_HMAC_SECRET=         # watchlist (thesis_pillars_original + scenario_A_base_projections)
```

Generation hint (run once per scope):

```
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Distinct scopes on purpose: a key compromise in one subsystem does not invalidate others.

### 4.4 Set SMTP credentials in `.env`

Per Section 7.1 hard gate ("Push alert email channel sends test email successfully").

```
ALERT_SMTP_HOST=smtp.gmail.com
ALERT_SMTP_PORT=587
ALERT_SMTP_USERNAME=your-account@gmail.com
ALERT_SMTP_PASSWORD=<gmail-app-password>            # NOT account password
ALERT_SMTP_SENDER=your-account@gmail.com
ALERT_SMTP_RECIPIENT=your-account@gmail.com
ALERT_SMTP_USE_TLS=1
```

Gmail rejects account passwords for SMTP; create an app password at <https://myaccount.google.com/apppasswords>.

### 4.5 Run peak-pain catalog priority subset

Per Section 7.2 calibration gate ("Peak-pain catalog priority-subset (~45 cases) at HIGH consensus on ≥95% of universal-core features").

```sh
python -m src.peak_pain_catalog.cli priority-run
```

Runs 3-LLM iterative-consensus validation on the ~45 priority cases (15 calibration test + 30 canonical archetypes). Lazy validation handles the remaining ~115 tail cases on first-retrieval (per Phase 4 Q4).

### 4.6 Calibrate materiality classifier kappa

Per Section 7.2 calibration gate ("L4 materiality classifier inter-rater agreement ≥0.61 Cohen's kappa vs operator gold-standard on 30 historical events").

Operator pre-rates 30 historical events (M-1 / M-2 / M-3) by hand; system runs the classifier; compute Cohen's kappa. Result writes to `materiality_classifier_drift` as the rolling-30-event gold-standard baseline. Re-rated each quarter.

### 4.7 Operator launch-gate sign-off

Per Section 7.3 (operator sign-off block). At v0.1, sign-off is recorded by:

1. Manual checked checkbox in spec §7.1 / §7.2 / §7.3.
2. Note appended to `BUILD_LOG.md` (Notes section).

The `/launch-confirm <gate_name>` slash-command wrapper is deferred (see §1.5).

---

## 5. Daily operator flow

What to do each day. The flow assumes v0.5+ operations (post-launch); v0.1 build phase uses `/run build` instead.

### 5.1 Session start

1. **Open Claude Code session.** Unread alerts auto-push at session-start (per Section 5.3 — Claude Code session push channel). If any are present, triage them first.
2. `/alerts` — full list of unacknowledged M-2 + M-3 backlog. Default ordering: severity DESC, then created_at DESC. Investigate M-3 first.
3. For each addressed alert, `/ack <alert_id>` (or `/ack all` once everything's been triaged).

### 5.2 Mid-day operations

4. `/disposition` — full watchlist with multi-horizon view + mode-fit dashboard. Look for flags: `pending_reclassification`, `rule_output_mismatch`, `vol_band_inconsistency`.
5. Drill into specific names:
   - `/disposition --ticker <T>` — single-name expanded view.
   - `/audit-trail <T> --latest` — most recent recommendation provenance.
   - `/audit-trail <rec_id> --stage <stage>` — specific stage drill.
6. **Confirm fills.** Auto-detected via broker MCP per Section 7 Q5; review `position_history` rows from the last poll. Operator-driven fills get reconciled to `fill_divergence` automatically.

### 5.3 Post-market close + 30 min

7. `/daily-monitor` — slow-layer heartbeat. Fires escalations + writes `daily_refresh_log`.
8. Triage any M-3 escalations from the digest.
9. `/system-health` — degraded MCPs, queues, errors. If anything is queued or degraded, address before next session.

---

## 6. Quarterly + annual cadences

| Cadence | Action |
|---|---|
| **Quarterly** | `/parameters-review` (deferred — manual review at v0.1) — system proposes, operator approves. Pulls counterfactual ledger for last 90d; runs missed-winners / false-positives / mode-classification accuracy / drawdown-vs-benchmark analysis; generates proposed parameter changes; operator approves / modifies / rejects each. |
| **Quarterly** | Peak-pain catalog 10% audit — operator reviews stratified sample (50% not-touched-in-12mo / 25% TBD-near-24mo / 25% random). Drift escalation: ≥20% reclassification → full catalog audit + M-2 event. |
| **Quarterly** | Mode classifier per-name re-classification — `mode_classifier.recheck` against current data; mismatch → operator review + pre-mortem. |
| **Quarterly** | Materiality classifier drift watch — N≥30 + rolling 30-event gold standard re-rated each quarter + confidence-distribution P50/P90 shift monitoring (Phase 4 Q8). |
| **Annual (Jan 1)** | Full peak-pain catalog audit (the 10% sample plus a refresh of the gold-standard set). |
| **Semi-annual (Jan + Jul)** | Mode-implied-vol check — 252d realized vol; >2σ outside mode band for 2 consecutive checks → `mode_vol_checks` flag. |
| **Annual** | Falsifiability check (§8.3) — B-mode 5x+ missed-winners count; C-mode net vs S&P 500. |

---

## 7. Failure-mode reference

What to expect when things break. Behavior is operator-locked per Section 7.5 + Phase 4 Q9.

| Failure | Behavior |
|---|---|
| **Postgres unreachable mid-recommendation** | Local fallback queue captures the recommendation payload. Recommendations carry `degraded: true` + reason. Hard stop if multiple MCPs fail simultaneously OR Postgres unreachable persists → maintenance mode → suppress recommendation output. |
| **Broker MCP rate-limited** | `degraded_broker` flag attached to sizing output. If degradation persists >24h on Mode C → M-2 system event (Mode C is most cadence-sensitive; B/B' tolerate 24h staleness silently). |
| **Email send failure** | Exponential retry up to `MAX_EMAIL_ATTEMPTS=4` (DECISION LOCK; Phase 4 Q9). On final failure: alert queues for next-session push and `system_errors` logs the SMTP fault. `/system-health` surfaces "queued-for-session-push" count. |
| **First MCP/external API failure** | Retry once with 30s backoff. Logged to `system_errors`. |
| **Second MCP failure** | Escalate to operator alert (M-2 system-level event). Never silent-fail. |
| **Lane down** | If any L1-L4 lane down, recommendations carry `degraded: true` flag with reason. |
| **3-LLM consensus exceeds 5-iteration cap** | Catalog row tagged `consensus_status: disputed`; excluded from active retrieval; counted toward 5% allowable miss in Section 7.2 launch gate. Surfaces in `/system-health` "disputed catalog entries". |
| **HMAC chain tamper-evidence** | `/audit-trail --verify` returns `TAMPER-EVIDENT`; exit code 3; M-2 system event fires. Operator must investigate before proceeding. |
| **anchor_drift triggered** | Operator must pick reaffirm / revise-with-rationale / cut (no-op default BLOCKED per migration 018). |

---

## 8. Out-of-scope (operator-locked exclusions)

Per spec §1.4 + §8.2. The system explicitly does NOT do these things; do not request features in these areas without revisiting the spec lock.

- **Trade execution** — operator manually executes via broker. The broker MCP is read-only; there is no `place_order` tool and there will not be one at v0.1.
- **Portfolio-level concerns** — concentration risk, sector exposure, mode-mix balance, correlation matrix, cash-as-portfolio-policy. Aggregation across names is the operator's job; system is per-name only.
- **Behavioral risk overlays** — overconfidence streak detection, loss-aversion drift detection. Re-evaluable if portfolio surfaces are added at v0.5+.
- **Currency handling for ADRs** — engineering detail; treat as USD-equivalent.
- **Dividend reinvestment policy** — operator decides outside the system.
- **Corporate actions** — engineering detail; broker MCP feeds reality (BUY / SELL / DIVIDEND / SPLIT / TRANSFER events).

---

## 9. Cross-references

| Topic | Authoritative source |
|---|---|
| v3 spec (frozen 2026-04-29) | `docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md` |
| Sign-off attestation | `docs/superpowers/specs/v3.0-signoff-attestation.md` |
| Section consensus docs (Q&A provenance) | `docs/section-{1..8}-consensus.md` |
| Build log + architectural decisions | `BUILD_LOG.md` |
| MCP tool-scoping rule (subagents) | `feedback_subagent_mcp_scoping.md` (auto-memory) |
| Peak-pain catalog v0.1 | `.claude/references/empirical/peak-pain-archetypes/catalog-v0.1.md` |
| Subagent definitions | `.claude/agents/{company-deep-dive,bear-case,evaluator}.md` |
| Slash command definitions | `.claude/commands/*.md` |
| Module READMEs | `src/<module>/README.md` (where present) |

---

**End of operator reference.** For Q&A provenance on any specific decision, read the relevant section consensus doc; for failure-mode root causes, read the relevant module's README; for spec changes post-v3.0, expect a v3.1+ companion document with explicit change-log per §8 PB#1.
