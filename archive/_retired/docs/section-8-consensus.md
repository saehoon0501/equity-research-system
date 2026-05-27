# Section 8 Consensus — v2-final Coexistence + Remaining Gaps

**Date:** 2026-04-29
**Status:** In progress
**Scope:** Reconcile Sections 1-7 locks against existing v2-final architecture spec; identify gaps, contradictions, migration concerns; produce coherent path to implementation.

---

## Q1 — Spec reconciliation approach **[LOCKED]**

**Decision:** (b) Versioned spec — produce a fresh v3 final spec.

**Approach:**
- Produce `docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md` as the new canonical architecture spec
- v3 reflects all locked decisions from Sections 1-7 (29 questions + 14 pushbacks across 7 sections)
- v2-final (`2026-04-26-empirical-foundation-design.md`) preserved as historical record; status header updated to "Superseded by v3"
- Section consensus docs (`section-1-consensus.md` through `section-7-consensus.md`) remain canonical for full provenance / Q&A context

**v3 spec structure (target ~30-50 pages):**

1. **Operating context** — operator profile, scale, goals, constraints (carry from v2-final §1.1, lightly updated)
2. **System architecture** — funnel + sidecars + 4-layer composition (carry from v2-final §2, refresh per Sections 2-7)
3. **Data layer** — MCPs (existing + broker MCP); Postgres schemas; data-source provenance (NEW per Section 5 + Section 7 Q5)
4. **Decision model**:
   - L1-L2 regime/macro lanes (per Section 3 locks)
   - L3 successful-companies + counterfactual catalog + peak-pain archetypes (per Section 5 + Section 6 Q6 + Pushbacks)
   - L4 view-refresh discipline (per Section 6)
   - L5/L6 execution output + multi-horizon disposition (per Section 7)
   - L7 smart-money sidecar (per Section 1)
   - L8 multi-style debate (per Section 1)
5. **Phase flow** — P1 trend → P9 exit, with cross-section linkages
6. **Operator surfaces** — recommendation output, disposition view, audit drill-down, push alerts (per Section 7 Q1/Q2/Q4 + Pushback #4)
7. **Calibration + drift** — per Section 3 Q3 BOCPD, Section 5 Q4 event-driven adds, Section 6 catalog hygiene, v0.5+ upgrade paths
8. **v0.1 launch gates** — pre-launch validation prerequisites (peak-pain catalog priority-subset 3-LLM consensus, broker MCP, calibration test set archetype-coverage, etc.)
9. **Open items + v0.5+ roadmap** — composable sizing formula, BB-pseudo-BMA+ weight optimization, peak-pain catalog tail validation, broker MCP for additional brokers, etc.

**Why (b) — fresh v3 spec:**
- (a) inline-revise v2-final loses lock traceability; consensus history disappears
- (c) consensus-docs-as-canonical places burden on engineer reading 7+ docs; cross-doc inconsistency risk
- (d) hybrid lean-summary defers the doc-consolidation work; engineers still need a single canonical spec
- (b) gives clean canonical reference; v2-final preserved as historical record; consensus docs remain for full Q&A provenance. Engineering team has one doc to read; auditors have full provenance trail

**Cross-references:**
- All Sections 1-7 consensus docs feed v3 content
- v2-final preserved per FDA GMLP P9 audit-trail principle (historical state recoverable)

**Implementation handoff:**
- Doc location: `docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md`
- Author after Section 8 fully closes (locks may emerge in remaining questions)
- v2-final header update: prepend "Status: SUPERSEDED by v3 (2026-04-29). Preserved for historical reference."

---

## Q2 — Implementation order + dependencies **[LOCKED]**

**Decision:** (d) Critical-path-first + parallelize independent work.

**Critical path (serial chain — blocks v0.1 launch):**

```
Postgres schema (foundation)
  ↓
L1-L2 regime sidecar (S0 6-dim + BOCPD)
  ↓
P3 mechanical scorer (Stage 1 + Stage 2 LLM rubric + Stage 3 linter)
  ↓
P4 debate orchestrator (5-style)
  ↓
Mode classifier (rule + LLM tie-breaker)
  ↓
L4 materiality classifier + Q3 routing
  ↓
P5 recommendation emitter (Q1 schema with conviction rollup)
  ↓
Push alert channels (Pushback #4 multi-channel)
```

**Parallel tracks (independent of critical path; can ship in parallel):**

| Parallel track | Description | Critical path dependency |
|---|---|---|
| Peak-pain catalog 3-LLM consensus validation | Run priority-subset (~45 cases) through Section 5 Q3 iterative consensus pipeline | Independent — runs offline; merges to retrieval at launch |
| Broker MCP build | Build first broker MCP (Schwab default per Section 7 Q5) | Independent — wires into positions table at launch |
| L8 multi-style debate prompts | Author 5 debate-style prompts + per-pattern rubrics | Joins P4 debate orchestrator |
| Counterfactual veto pipeline | Build retrieval + matching code | Joins L4 materiality at launch |
| Anchor-drift detector | 3 channels per Section 6 Q5 | Joins L4 materiality at launch |
| Pre-mortem scheduler | Mode-tuned cadence per Section 6 Q4 | Joins L4 daily-monitor at launch |
| Audit drill-down UI | Per Section 7 Q4 layered drill | Joins recommendation emitter at launch |
| Disposition view | Per Section 7 Q2 + Postgres view | Joins recommendation emitter + positions at launch |

**Why (d) — critical-path-first + parallel:**
- (a) bottom-up serial creates unnecessary delay; many components are independent
- (b) top-down with mock outputs creates integration churn when real outputs differ in shape
- (c) vertical slices add glue work without learning value when architecture is already locked
- (d) maximizes parallelism on independent work; critical path is actual blocker; matches engineering practice for multi-component systems with locked architecture

**Resource implication:** v0.1 ~4-6 weeks per Pushback #1; if 1 engineer running serial = ~10-12 weeks. Parallelism only helps if multiple engineers OR if some tracks (catalog validation, prompt authoring) can be operator-driven in parallel with engineering.

**Cross-references:**
- All Sections 1-7 component locks → critical path nodes
- Pushback #1 v0.1 full scope → critical path is the minimum chain to launch

**Implementation handoff:**
- Plan doc: `docs/superpowers/plans/2026-04-29-empirical-foundation-v3-implementation.md` (NEW)
- Includes Gantt-style timeline with critical path + parallel tracks
- Author concurrently with v3 spec (Q1 lock)

---

## Q3 — v0.1 launch gates + hard prerequisites **[LOCKED]**

**Decision:** (a) All-or-nothing checklist — any gate fail = no launch.

**Pre-launch checklist (every item must pass):**

### Hard gates (functional correctness)

- [ ] Postgres schema migrations applied + all required indexes created
- [ ] Broker MCP OAuth flow tested; token refresh validated
- [ ] Audit-trail HMAC chain validates end-to-end (Section 5 Q1 + Section 7 Q4)
- [ ] Push alert email channel sends test email successfully
- [ ] Push alert Claude Code session push surfaces unread alerts at session start
- [ ] `/alerts`, `/ack <id>`, `/audit-trail <rec_id>` slash commands all functional
- [ ] Recommendation emitter produces valid Q1 schema (zero missing required fields across 50 test invocations)
- [ ] Mode classifier produces output for 100% of watchlist names (rule + LLM tie-breaker both functional)
- [ ] L1-L2 regime sidecar producing all 6 S0 dimensions with BOCPD probabilities
- [ ] Materiality classifier producing M-1/M-2/M-3 outputs with verbatim-quote citations on 100% of test events
- [ ] Counterfactual veto pipeline retrieves top-3 + computes archetype distribution

### Calibration gates (quality)

- [ ] Peak-pain catalog priority-subset (~45 cases) at HIGH consensus on ≥95% of universal-core features
- [ ] Calibration test set (15 cases) archetype-coverage agreement ≥80% within ±1
- [ ] Canonical SURVIVOR test cases retrieve ≥2 SURVIVOR matches in top-3 in ≥90% of cases
- [ ] Canonical NON-SURVIVOR test cases retrieve ≥2 NON-SURVIVOR matches in top-3 in ≥90% of cases
- [ ] Mode classifier rule-clean rate ≥75% on watchlist
- [ ] L4 materiality classifier inter-rater agreement ≥0.61 Cohen's kappa vs operator gold-standard on 30 historical events

### Operator sign-off

- [ ] Operator reviewed peak-pain catalog priority-subset validation results
- [ ] Operator reviewed first 10 mode classifications for accuracy
- [ ] Operator reviewed first 10 recommendation outputs for sensibility
- [ ] Operator confirmed broker MCP positions match brokerage UI
- [ ] Operator confirmed push alert email + Claude Code session push reach correctly

**Why (a) — all-or-nothing:**
- (b) operator-judgment override defeats gates' calibration purpose
- (c) tiered hard/soft creates invisible permanent soft-gate-override state
- (d) (c) + auto-re-validation is operationally complex for marginal benefit
- (a) is consistent with operator's standing pattern of choosing rigorous over expedient

**Failure mode:** if any gate fails, launch holds; engineering team addresses; re-runs gate; operator re-validates. Documented in `docs/superpowers/launch-readiness-log.md` (NEW).

**Why acceptable per Pushback #1 (full v0.1 scope, no staged release):** operator already accepted long pre-launch period (~4-6 weeks). Hard checklist matches that posture. Soft-gate flexibility would be a backdoor to staged release that Pushback #1 explicitly rejected.

**Cross-references:**
- All Sections 1-7 lock → individual gates
- Section 7 Pushback #1 → consistent with full-scope launch posture
- Section 6 Q6 (d') validation → calibration gates

**Implementation handoff:**
- Doc: `docs/superpowers/launch-readiness-checklist.md` (NEW; living checklist updated as gates pass)
- Each gate is a runnable assertion (e.g., `pytest tests/launch_gate_<name>.py`)
- Operator sign-off captured via `/launch-confirm <gate_name>` slash command with timestamped attestation

---

## Q4 — Calibration data capture for v0.5+ upgrades **[LOCKED]**

**Decision:** (c) Capture everything + structured retrieval — every decision-event in typed Postgres tables.

**Tables (consolidated; some carry through from Sections 5-7 locks, some new):**

```yaml
# Already locked
execution_recommendations  # Section 7 Q1 + Pushback #5 conviction rollup
position_history           # Section 7 Q5
audit_provenance           # Section 7 Q4
daily_refresh_log          # Section 6 Q1
mode_classifications       # Section 7 Pushback #3
unread_alerts              # Section 7 Pushback #4
peak_pain_archetypes       # Section 6 Q6 catalog
counterfactual_retrievals  # NEW (Section 6 Q6 retrieval events)
materiality_events         # NEW (Section 6 Q1 event log)
veto_lifecycle             # NEW (Section 6 Q6 Pushback #5 lifecycle)
anchor_drift_checks        # NEW (Section 6 Q5)
premortem                  # NEW (Section 6 Q4)

# NEW for calibration capture
operator_overrides         # Every override (sizing, routing, veto, mode) with rationale + verbatim citation
recommendation_outcomes    # T+30d / T+90d / T+1y returns joined to original recommendation
regime_classification_history  # S0 6-dim + BOCPD per cycle, with later "actual regime" annotation
debate_consensus_history   # 5-style debate output + dissents per recommendation
fill_divergence            # Recommended vs actual fill divergence (timing lag, sizing %, price slippage)
calibration_test_results   # Periodic calibration runs against test sets (pre-launch + ongoing)
```

**Schema principles:**
- Append-only event log pattern (no UPDATE on historical rows; only INSERT)
- Every row: timestamp + version metadata (rule_engine_version, prompt_version, model_id, parameters_version)
- HMAC signature on rows that feed audit chain
- Indexed on (ticker, date) for time-series queries
- Retention: indefinite at v0.1 (storage cost negligible at operator scale; can revisit at v1.0+ if needed)

**v0.5+ upgrade analysis paths these tables enable:**

| Upgrade target | Source tables | Analysis |
|---|---|---|
| Composable sizing formula (Pushback #2) | operator_overrides + recommendation_outcomes + fill_divergence | Regress override-rationale + outcome on candidate multiplier inputs |
| BB-pseudo-BMA+ regime weights (Section 3 Q2) | regime_classification_history + recommendation_outcomes | Posterior weight optimization on historical regime predictions |
| Conviction continuous score (Pushback #5) | execution_recommendations.conviction_breakdown + recommendation_outcomes | Calibration of conviction-rollup-vs-realized-return |
| Peak-pain catalog tail validation | counterfactual_retrievals + recommendation_outcomes | First-retrieval events on tail cases trigger 3-LLM consensus |
| Mode classifier threshold refinement | mode_classifications (rule + LLM tie-breaker outputs) + recommendation_outcomes | Disagreement-case analysis |
| Materiality routing weights (Section 6 Q2) | operator_overrides on routing + recommendation_outcomes | Routing-decision quality |
| Counterfactual veto re-fire | veto_lifecycle + recommendation_outcomes | Lifecycle outcome tracking |

**Why (c) — capture everything + structured retrieval:**
- (a) per-upgrade-target capture under-captures; future analysis blocked
- (b) capture-everything-unstructured creates query overhead; defeats calibration purpose
- (d) explicit calibration_label tagging is premature optimization; we don't know which exact data points each upgrade will need
- (c) captures all + structured for SQL query; storage cost negligible; any future analysis path possible without re-instrumenting

**Cross-references:**
- Section 5 Q1 audit log → audit_provenance table
- Section 5 Q4 event-driven adds → materiality_events feeds catalog refresh
- Section 6 catalog hygiene → calibration_test_results feeds annual audit
- All Pushbacks → operator_overrides captures rationale for v0.5+ formula calibration

**Implementation handoff:**
- Code: schema in `src/db/migrations/0001_v0.1_calibration_tables.sql`
- Append-only write: enforced via Postgres triggers + row-level security
- HMAC signing: subset of rows per Section 5 Q1 + Section 7 Q4 + Section 6 Q5

---

## Q5 — Operator onboarding flow **[LOCKED]**

**Decision:** (a) Documentation-only.

**Onboarding artifacts:**
- v3 final spec (`docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md`) per Q1
- Slash-command reference: `docs/superpowers/operator-reference.md` (NEW; consolidated /<command> reference)
- Section consensus docs (1-7) for full Q&A provenance / deep dives
- README at `.claude/references/empirical/00-overview.md` (already exists; refresh post-v3)

**No setup wizard / no walkthrough at v0.1.** Operator reads spec + reference and self-directs.

**Why (a) — documentation-only:**
- Operator profile: engineer; has driven all architectural decisions in this consensus; high domain ownership
- (b)/(c)/(d) wizard/walkthrough is engineering effort that operator's profile doesn't warrant
- Documentation-only is consistent with the engineering culture this consensus has established (rigorous spec-first design)

**Re-evaluation:** if v0.5+ ever brings additional operators, Q5 re-opens for re-design with appropriate onboarding flow.

**Implementation handoff:**
- Doc: `docs/superpowers/operator-reference.md` (NEW; tabular reference of every slash command, schema field, watchlist operation)
- Author concurrently with v3 spec

---

## Q6 — Remaining gaps **[LOCKED]**

**Decision:** (b) Address cold-start + error handling philosophy at v0.1; defer rest.

**Operator scope clarification (locked):** portfolio-level concerns (concentration, sector exposure, mode-mix balance, correlation, cash-as-portfolio-policy) are **OUT OF SCOPE**. The system is per-name decision augmentation. Aggregation across names is the operator's job. Consistent with original system goal: "Facilitate data aggregation, automate the complex decision model using LLM and code. The operator only sees the result."

### Addressed at v0.1

#### Initial regime classification cold-start

At first system run (no historical S0 state in DB):
1. S0 sidecar runs full BOCPD on T-12mo of macro data (FRED + market_data MCPs)
2. Produces initial 6-dimension classification with BOCPD probabilities
3. Confidence flag = `cold_start: true` for first 90 days post-launch (BOCPD needs sustained history for HIGH confidence)
4. Cold-start period: regime overrides on sizing (Pushback #2 vol-elevated overlay) apply with `cold_start_caveat` annotation; operator sees this in execution_context risk_flags
5. After 90 days, system has sufficient history; cold_start flag clears

Schema:
```yaml
regime_classification_history:
  ...
  cold_start: true   # first 90 days
  history_length_days: 365  # T-12mo seed
```

#### Error handling philosophy

MCP / external API failures:
1. **First failure:** retry once with 30s backoff
2. **Second failure:** escalate to operator alert (M-2 system-level event); push via Pushback #4 channels
3. **Never silent-fail:** every failure logged to `system_errors` Postgres table with timestamp + error type + which MCP + which decision was blocked
4. **Degraded operation:** if any L1-L4 lane is down, recommendations carry `degraded: true` flag with reason; operator sees in risk_flags
5. **Hard stop:** if multiple MCPs fail simultaneously OR Postgres unreachable, system enters maintenance mode → suppresses recommendation output → all alerts route to operator

Schema:
```yaml
system_errors:
  error_id: uuid
  timestamp: 2026-04-30T14:30:00Z
  source: "mcp__edgar__get_filings"
  error_type: "rate_limit_exceeded"
  retry_count: 2
  escalated_to_alert: true
  blocked_decision: "P3 mechanical scorer for NVDA"
  resolution: "Retried after 5min; succeeded; recommendation produced 5min late"
```

### Deferred to v0.5+

| Item | Defer reason |
|---|---|
| Backup / disaster recovery for Postgres | Engineering ops; standard pg_dump cadence sufficient at v0.1 |
| Cost tracking (LLM API spend, broker rate limits) | Engineering ops; not architectural; can add metrics in implementation |
| Behavioral risk: overconfidence streak detection | Operator-meta pattern; out of scope per "per-name decision augmentation" framing |
| Behavioral risk: loss-aversion drift detection | Operator-meta pattern; out of scope |
| Tax-lot accounting beyond FIFO | FIFO default sufficient at v0.1; SpecID supported per fill |
| Currency handling for ADRs | Engineering detail; market_data MCP handles |
| Dividend reinvestment policy | Operator decides; not system |
| Corporate actions (splits, spin-offs) | Engineering detail; broker MCP feeds reality |
| Multi-operator support | Single-operator at v0.1 |
| Web UI for disposition view | Terminal sufficient; web UI at v0.5+ |

**Why (b) — cold-start + error handling at v0.1:**
- (a) defer-all leaves day-1 operator unable to bootstrap regime sidecar + system fails silently on MCP errors
- (c) all-gaps treats engineering ops as architectural; consensus fatigue for marginal gain
- (b) covers gaps that materially affect day-1 operator experience (regime cold-start, error visibility) + cleanly defers engineering ops + cleanly defers behavioral overlays per "per-name only" scope

**Cross-references:**
- Section 3 Q1 6-dimension S0 + Q3 BOCPD → cold-start operationalizes
- Pushback #4 push alerts → error escalation channel
- Section 7 Q1 risk_flags → cold_start_caveat + degraded flag surface

**Implementation handoff:**
- Cold-start: `src/skills/p1-trend/regime_cold_start.py`
- Error handling: `src/lib/mcp_retry.py` + `src/db/migrations/0002_system_errors_table.sql`
- Both components covered by hard launch gate (Q3) test suite

---

## Section 8 — final summary

| Item | Decision | Status |
|---|---|---|
| Q1 | Spec reconciliation: produce v3 fresh spec; v2-final preserved as historical | LOCKED |
| Q2 | Implementation: critical-path-first + parallelize independent work | LOCKED |
| Q3 | Launch gates: all-or-nothing checklist; any gate fail = no launch | LOCKED |
| Q4 | Calibration capture: capture everything + structured retrieval (typed Postgres tables) | LOCKED |
| Q5 | Operator onboarding: documentation-only (no setup wizard) | LOCKED |
| Q6 | Remaining gaps: cold-start + error handling at v0.1; portfolio-level OUT OF SCOPE; rest defer | LOCKED |
| PB1 | v3 spec authorship: BEFORE implementation; v3 is authoritative reference for engineering | LOCKED |
| PB2 | v3 authorship: explicit gap-detection sweep + parallel adversarial review | LOCKED |

---

## Pushback #2 — v3 cross-section gap detection **[LOCKED]**

**Decision:** (d) Explicit gap-detection sweep + parallel adversarial review.

**Authorship process (4 phases):**

### Phase 1 — Consolidation draft
- AI assistant generates v3.0-draft from Sections 1-7 consensus docs + Section 8 locks
- Output: complete v3 spec covering all sections per Q1 structure

### Phase 2 — Cross-section consistency audit (in-line gap detection)
- Same author runs systematic check:
  - Schema field name collisions across sections
  - Version-field inconsistencies (`prompt_version` vs `model_version` vs `parameters_version`)
  - Conflicting definitions of same concept (e.g., "kill-criterion fired" across S4 + S6)
  - Stale cross-references (e.g., S3 references "S5 lock pending" — verify post-S5)
  - Schema handoff mismatches (S5 outputs vs S6 inputs; S6 outputs vs S7 inputs)
  - Failure-mode gaps (Postgres unreachable; MCP rate limits; LLM timeout)
- Output: gap-findings doc surfaced for operator review

### Phase 3 — Parallel adversarial review (Bear-case style)
- Independent agent (subagent_type: bear-case) reviews v3.0-draft + gap-findings
- Adversarial mandate: actively hunt for inconsistencies, missing handoffs, unaddressed failure modes, hidden assumptions
- Output: adversarial-findings doc with specific section + line citations

### Phase 4 — Operator review + re-consolidation
- Operator reviews v3.0-draft + Phase-2 gap-findings + Phase-3 adversarial-findings
- Operator decides per finding: accept gap as v0.5+ deferral / re-open consensus question / no-action
- Re-consolidation incorporates all decisions
- Final v3.0 frozen with operator `/spec-approve v3.0` sign-off

**Why (d) — sweep + adversarial:**
- (a) standard consolidation surfaces obvious inconsistencies but misses subtle ones; given 29 questions + 14 pushbacks across 7 sections + 6 questions + 2 pushbacks in S8, subtle gaps are virtually certain
- (b) explicit sweep catches more but lacks adversarial pressure
- (c) adversarial alone misses systemic inconsistencies the bear-case agent isn't tuned for
- (d) layered defense matches operator's standing pattern + matches Section 1 bear-case independent-adversary architecture

**Engineering cost:**
- Phase 1: ~3-5 days (consolidation)
- Phase 2: ~1-2 days (consistency sweep)
- Phase 3: ~1-2 days (adversarial review, parallel to Phase 2)
- Phase 4: ~1 day (operator review + re-consolidation)
- Total: ~7-10 days; runs at the very front of critical path before any implementation

**Cross-references:**
- Section 1 bear-case independent adversary → Phase 3 reuses pattern
- All Sections 1-8 locks → Phase 1-2 sources
- Section 7 Q4 audit-trail HMAC → spec sign-off uses same attestation pattern

**Implementation handoff:**
- Phase 1 output: `docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.0-draft.md`
- Phase 2 output: `docs/superpowers/specs/v3.0-gap-findings.md`
- Phase 3 output: `docs/superpowers/specs/v3.0-adversarial-findings.md`
- Phase 4 output: final `docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md` + sign-off attestation

---

## Section 8 — closed.

10 architectural decisions across 6 questions + 2 pushbacks. All Sections 1-8 consensus complete.

**Total consensus across 8 sections:**
- Section 1: 8 items + 1 pushback
- Section 2: 5 wiring + 3 open-floor
- Section 3: 4 questions
- Section 4: 7 questions
- Section 5: 6 questions
- Section 6: 6 questions + 7 pushbacks
- Section 7: 5 questions + 5 pushbacks
- Section 8: 6 questions + 2 pushbacks

**~64 architectural locks total.**

**Next step:** v3 spec authorship (Phase 1-4 per Pushback #2). When operator initiates, AI runs Phase 1 consolidation draft → Phase 2 gap sweep → Phase 3 adversarial review (parallel) → Phase 4 operator review + sign-off → implementation begins.

---

## Pushback #1 — v3 spec authorship timing **[LOCKED]**

**Decision:** (a) v3 spec FIRST — author before any implementation code starts.

**Operator framing:** "v3 will be used for implementation." → spec is the authoritative source from which engineering reads. Code is generated against v3, not the other way around.

**Implications:**
- Adds ~1-2 weeks doc-authoring to critical path
- v0.1 launch projection moves from ~4-6 weeks to ~6-8 weeks
- Engineering team has single canonical reference; no consensus-doc-spelunking
- Implementation-vs-spec divergence (rare given consensus rigor) triggers spec update via formal change-control, not silent code-deviation

**Authorship process:**
1. Consolidation draft generated from Sections 1-7 consensus docs + Section 8 locks
2. Cross-section gap-detection pass — surface anything inconsistent or unaddressed
3. Operator review with formal sign-off
4. If sign-off approves → freeze v3.0; implementation begins
5. Any subsequent v3 revision (v3.1+) requires explicit operator change-control attestation

**Why (a) — spec-first:**
- Operator declared "v3 will be used for implementation" — code reads from spec
- (b) concurrent risks spec drift; final-sync passes are notoriously incomplete
- (c) post-hoc spec is just code documentation, not architecture
- (a) preserves design intent + engineering reads single source

**Cross-references:**
- Q1 v3 spec content + structure
- Q2 critical-path-first → spec authorship is now critical path step zero
- All Sections 1-7 + Section 8 locks → spec content sources

**Implementation handoff:**
- Doc: `docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md` (NEW)
- Authored by: AI assistant via consolidation pass; reviewed by operator
- Sign-off: operator runs `/spec-approve v3.0` (NEW slash-command); attestation logged with timestamp + HMAC
- Post-sign-off freeze: v3.0 immutable; subsequent revisions tracked as v3.1+ with change-log

---

## Phase 4 review — operator decisions on Phase 2 + Phase 3 findings

### Phase 4 Q1 — Mode classifier rule conflict resolution **[LOCKED]**

**Decision:** (d) Layered structure.

- **Stage 1 — Market-structural filter (Section 1 Item 1 thresholds):** establishes B/B'/C bin based on market_cap, vol, profitability, growth
- **Stage 2 — Company-quality refinement (Section 7 PB#3 criteria):** within the bin, applies founder-tenure + ROIIC + path-to-profit as quality flag (HIGH-quality / STANDARD)
- **Stage 3 — Overlap detection + LLM tie-breaker** (per PB#3 framework)

Mode (B/B'/C) drives sizing band, cadence, cut threshold, capitulation cooling-off, primary horizon view. Company-quality flag (HIGH/STANDARD) becomes a CONVICTION MULTIPLIER input — HIGH-quality compounders within same mode deserve higher conviction.

This preserves both rule systems' signal: market-structural defines the bin; company-quality discriminates within the bin. Resolves Phase 2 Finding #3.

### Phase 4 Q2 — Conviction MEDIUM trap fix **[LOCKED]**

**Decision:** (d) Decouple LLM tie-breaker AND allow ≤1 minor caveat among remaining conditions.

**Revised conviction rollup:**

- **HIGH** = ≥4/5 debate AND 0 kills fired AND ≥2 SURVIVOR matches in top-3 AND ≤1 of {1 anchor-drift channel triggered}
- **MEDIUM** = ANY ONE of {3/5 debate, 1 kill fired, mixed counterfactual (1-2 SURVIVOR + 1-2 NON-SURVIVOR), ≥2 anchor-drift channels triggered}
- **LOW** = ANY ONE of {<3/5 debate, ≥2 kills fired, ≥2 NON-SURVIVOR matches in top-3}

**`mode_certainty` becomes separate annotation field** (rule_clean | llm_tiebreaker), NOT a conviction-bucket determinant. Tie-breaker is classification difficulty, not evidence quality.

This resolves Phase 3 P0-3. PLTR-class overlap-case names can now reach HIGH conviction when evidence is strong; drift-channel noise tolerated up to 1 channel.


### Phase 4 Q3 — Walkthrough launch gates **[LOCKED]**

**Decision:** (c) All 10 walkthroughs as launch gates.

**Walkthrough launch gates (must pass before v0.1 implementation lock):**

| # | Case | Validates |
|---|---|---|
| 1 | PLTR-2022 | Counterfactual veto authority + Layer 1/2/3 capitulation defense + the motivating case |
| 2 | NVDA-2023 | Conviction rollup HIGH-gate (post Q2 fix); bull-case decision flow |
| 3 | SVB-March-2023 | Banks-B mode + M-3 deposit-flight + sector-extension matching |
| 4 | Cold-start day-1 | Anchor-drift channels behavior + cold-start cap on conviction |
| 5 | Mode reclassification + pre-mortem race | Pre-mortem cadence under reclassification (B'→C) |
| 6 | Override-rate >50% scenario | Override-rate dashboard surfaces pattern; system catches operator-bias |
| 7 | Catalog reclassification ripple | TBD→NON-SURVIVOR resolves; live retrievals re-evaluate |
| 8 | Broker MCP outage during M-3 | Sizing degraded-flag; staleness display; M-3 with stale positions |
| 9 | Conviction flip-flop | Hysteresis prevents noise (drift score 0.23↔0.28 oscillation) |
| 10 | Phase C judge silent miss | Judge confidence threshold; Phase C false-negative detection |

**Per-walkthrough deliverable:** `docs/superpowers/launch-walkthroughs/<case-name>.md` with:
- Input setup (state, dates, prices, kill-criteria, regime context)
- Expected behavior per architectural lock (referenced)
- Actual behavior produced by implementation
- Comparison + verdict (PASS / FAIL / OPERATOR-OVERRIDE-REQUIRED)
- HMAC-signed attestation

**Operator sign-off** via `/launch-confirm walkthrough_<case-name>`.

**Why (c) — all 10:**
- (a)/(b)/(d) defer operational walkthroughs (6-10) to post-launch drift monitoring
- Operator's standing pattern is rigorous-over-expedient; cases 6-10 are real failure modes the bear-case agent flagged
- All 10 require ~3-5 days of additional pre-launch work; small cost vs catching architectural failures
- Cases 6-10 stress-test the architecture in ways production usage may take 6-12 months to surface

**Resource implication:** ~3-5 days additional pre-launch work; total v0.1 timeline ~7-9 weeks.


### Phase 4 Q4 — 3-LLM consensus on ordinal features **[LOCKED]**

**Decision:** (d) Feature-typed rules — categorical exact-match; ordinal within-±1.

**Categorical features** (exact match required across all 3 LLMs):
- founder_in_place: yes / departed / replaced-by-competent
- founder_insider_stake_direction: increasing / flat / decreasing / departed
- All sector-specific categorical features (e.g., `moat_state: intact/weakening/leapfrogged`)

**Ordinal features** (within-±1 ordinal step counts as agreement):
- cash_runway: >24mo / 12-24mo / <12mo / distressed
- customer_engagement: holding / eroding / collapsed
- margin_trajectory: improving / stable / deteriorating
- revenue_trajectory: growing / flat / declining / pre-revenue
- industry_tailwind: intact / weakening / reversed / structural-decline
- All sector-specific ordinal features

**5-iteration cap** still applies. Persistent disagreement → tagged `consensus_status: disputed`, excluded from active retrieval (counted toward Section 7 launch gate's allowable miss in 5% threshold).

**Schema addition per case feature:**
```yaml
peak_pain_features:
  founder_in_place: yes
  founder_in_place_consensus: HIGH (exact-match 3/3)
  cash_runway: 12-24mo
  cash_runway_consensus: HIGH (within-±1 across {12-24mo, 12-24mo, <12mo})
  consensus_method: feature-typed-v0.1
```

This resolves Phase 2 Finding #7. Engineering can implement the consensus pipeline knowing categorical/ordinal distinction.


### Phase 4 Q5 — Mode classifier silent-failure detection **[LOCKED]**

**Decision:** (c) Comprehensive — per-name re-class quarterly + vol check semi-annually + launch gate 100% mode-confirmed + ongoing mode-fit dashboard.

**Per-name quarterly re-classification:**
- Runs Stage 1 rule classifier (Q1 layered architecture) against current data
- If rule output differs from currently stored mode → flag for operator review
- Mode change requires pre-mortem (Section 6 Q4 trigger 4)
- Output: `mode_classifications` table row with `recheck_status: confirmed | pending_review | reclassification_proposed`

**Mode-implied-vol check (semi-annual, every January + July):**
- Computes 252-day realized vol per name
- Compares against mode band per Section 2.2 (B <25%, B' 25-50%, C >50%)
- >2σ outside band for 2 consecutive checks → flag for operator review
- Output: `mode_vol_checks` table

**Launch gate addition:**
- Replace existing "Operator reviewed first 10 mode classifications" with **"100% of watchlist names mode-confirmed by operator"**
- Each name signed off via `/launch-confirm mode_<ticker>` slash command

**Mode-fit dashboard:**
- Integrated into `/disposition` view
- Per-row addition: `mode | realized_252d_vol | last_confirmed_date | flag_status`
- Surfaced flags: rule-output-mismatch / vol-band-inconsistency / pending-reclassification

This resolves Phase 3 P0-2.


### Phase 4 Q6 — Calibration circularity defense **[LOCKED]**

**Decision:** (c) Override-rate dashboard + Brier comparison + alert.

**New `override_outcomes` table:**
- Every operator override tagged with T+90d / T+1y outcome + counterfactual baseline ("what system's recommendation would have produced")
- Joined to `execution_recommendations` and `recommendation_outcomes`
- Append-only; HMAC-signed

**New `system_vs_operator_brier` Postgres view:**
- Computed monthly per (mode, materiality, recommendation_type) cell
- system_brier vs operator_brier
- N count per cell
- Direction-of-better flag

**Override-rate dashboard:**
- Surfaces in `/parameters-review` quarterly
- Shows rate per cell + Brier comparison + N
- Cells with >50% override AND negative-Brier flagged as M-2 system event

**v0.5+ formula calibration sign convention:**
- For cells where operator_brier < system_brier (operator is better) → calibration regresses TOWARD operator behavior (current locked behavior)
- For cells where operator_brier > system_brier (operator is worse) → calibration regresses AGAINST operator bias (inverts current locked behavior)
- Direction decided per cell, not globally

This resolves Phase 3 P1-1.


### Phase 4 Q7 — Conviction oscillation hysteresis **[LOCKED]**

**Decision:** (d) Symmetric 2-cadence persistence + flip-frequency tracking + auto-flag.

**Hysteresis rule:**
- Conviction transition (HIGH→MEDIUM, MEDIUM→LOW, MEDIUM→HIGH, LOW→MEDIUM) requires the transitioning condition to persist **2 consecutive cadence cycles**
- Symmetric in both directions (preserves anchor-drift defense; slow promotes prevent stale-HIGH on shifted evidence; slow demotes prevent noise demotes)

**Flip-frequency tracking:**
- Per-name `conviction_flip_count_30d` rolling
- >3 flips in 30 days → name escalates to operator review (M-2 system event)
- Auto-demote to MEDIUM and freeze until operator review completes

**Schema additions:**
```yaml
execution_recommendation:
  conviction: HIGH                                # current bucket post-hysteresis
  conviction_pending_transition: false            # true when demote/promote condition active but not yet 2-cadences-persisted
  conviction_pending_target: null                 # MEDIUM | LOW | HIGH if pending
  conviction_changed_from_prior: false
  conviction_flip_count_30d: 1
  conviction_frozen_pending_review: false
```

This resolves Phase 3 P1-2.


### Phase 4 Q8 — Materiality production drift detection **[LOCKED]**

**Decision:** (d) N≥30 quarterly + rolling moving gold-standard + confidence distribution monitoring as leading indicator.

**Quarterly drift watch (replaces locked N=10):**
- Sample size: N≥30 production events per quarter (not 10)
- Gold standard: **rolling 30 most-recent events re-rated by operator at each quarterly review** (not frozen launch set)
- Cohen's kappa computed against rolling window; threshold remains ≥0.61 per Section 6 launch gate
- If kappa < 0.61 on rolling window for 2 consecutive quarters → M-2 system event triggers `/parameters-review` for materiality classifier

**Confidence distribution monitoring (leading indicator):**
- Track P50 and P90 of LLM-judge confidence per quarter
- Per Section 6 Q2, judge confidence < 0.6 defaults to lookup table; rising rate of <0.6 cases = drift signal
- Flag if P50 or P90 shifts >0.1 between consecutive quarters

**New `materiality_classifier_drift` Postgres table:**
```yaml
quarterly_drift_check:
  date: 2026-Q4
  sample_size: 32
  rolling_gold_standard_events: [event_ids x30]
  kappa: 0.68
  confidence_p50: 0.74
  confidence_p90: 0.91
  delta_from_prior_quarter: { kappa: -0.05, conf_p50: -0.04, conf_p90: -0.02 }
  flags: []
```

Quarterly review surfaces in `/parameters-review`. Resolves Phase 3 P1-3.


### Phase 4 Q9 — Failure-mode defaults + system health visibility **[LOCKED]**

**Decision:** (b) Accept all 4 defaults + add `/system-health` slash command for unified visibility.

**Default behaviors (all locked):**

| Failure | Default behavior |
|---|---|
| Postgres unreachable mid-recommendation | Write JSON to local fallback queue (`/tmp/recommendation_emit_queue/`) + M-3 alert + resume on Postgres recovery with HMAC chain fork annotation |
| Broker MCP rate-limited during fill detection | Exponential backoff + degraded-broker flag on positions + M-2 alert if degraded >24h on Mode C name |
| Push-alert email send failure | Exponential retry (1min/5min/15min) → queue for next Claude Code session-start delivery as M-3 unread + log to system_errors |
| 3-LLM consensus exceeds 5-iteration cap | Tagged `consensus_status: disputed` + excluded from active retrieval + counted toward 5% allowable miss in Section 7 launch gate |

**`/system-health` slash command surfaces:**
- All currently-degraded MCPs + last-success timestamp
- Queued recoveries (Postgres fallback queue size, broker MCP retry count, email queue depth)
- Disputed catalog entries excluded from retrieval (count + ticker list)
- System errors in last 7 days (count by source)
- Active push-alert backlog

**Launch gate addition:** `/system-health` returns valid output; integrated into Section 7 hard gates.

This resolves Phase 2 Findings #10-13.

---

## Phase 4 — Closed.

| Q | Decision | Resolves |
|---|---|---|
| Q1 | Mode classifier: layered (S1 market-structural + S7 PB#3 quality refinement) | Phase 2 #3 |
| Q2 | Conviction rollup: decouple LLM tie-breaker + ≤1 minor caveat HIGH gate | Phase 3 P0-3 |
| Q3 | All 10 walkthroughs as launch gates | Phase 3 P0-1 + walkthroughs |
| Q4 | 3-LLM consensus: feature-typed (categorical exact / ordinal within-±1) | Phase 2 #7 |
| Q5 | Mode classifier silent-failure: per-name re-class quarterly + vol check semi-annually + launch gate 100% mode-confirmed + dashboard | Phase 3 P0-2 |
| Q6 | Calibration circularity: override-Brier + override-rate dashboard + per-cell calibration sign | Phase 3 P1-1 |
| Q7 | Conviction hysteresis: symmetric 2-cadence + flip-frequency tracking | Phase 3 P1-2 |
| Q8 | Materiality drift: N≥30 quarterly + rolling gold-standard + confidence distribution | Phase 3 P1-3 |
| Q9 | Failure-mode defaults + `/system-health` slash command | Phase 2 #10-13 |

**Documentation cleanup (low priority, v3.1-draft handles via default fixes):**
- Phase 2 #1: scrub NDCG@3 from section-6-consensus.md schema example (v3.0-draft already correct)
- Phase 2 #4: standardize `materiality` field as integer 1/2/3 + derived `materiality_label` (M-1/M-2/M-3) for display
- Phase 2 #5-6: standardize on `(model_id, model_version)` pair throughout schemas
- Phase 2 #16: clarify `regime_state` is Postgres view selecting latest from `regime_classification_history`

