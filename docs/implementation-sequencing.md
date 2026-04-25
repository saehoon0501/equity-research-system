# v0.1 Implementation Sequencing Plan

**Status:** Implementation companion to v2-final-spec.md and phasing-plan.md
**Purpose:** Translate v0.1 phase scope into a week-by-week build plan with dated start, dated checkpoints, named buffer, and the documented-slip discipline that prevents silent timeline absorption
**Audience:** Energized-now-you on Day 1 — the version about to start build, who is tempted to take on more in week 1 than is sustainable, skip BUILD_LOG entries because there's real work to do, push through checkpoints because the build is going well, and add scope beyond what's specified.

---

## 0. What This Document Is For

The phasing doc was written for tired-future-you, the version six months in who is rationalizing why a gate doesn't apply. It pre-armed against under-commitment.

This document is symmetric. It's written for energized-now-you on Day 1. The failure mode here is over-commitment: taking on more than is sustainable, treating the schedule as a baseline rather than a target, treating BUILD_LOG.md as overhead rather than the artifact that prevents silent slip.

If you find yourself wanting to compress a week's scope while reading this Day 1, that's the schedule doing its job. Hold the line.

---

## 1. Operating Model and Calendar

### 1.1 Track resolution

**FTE track:** ≥40 hours/week. Realistic if you have dedicated time, contractor capacity, or a sabbatical-shaped block.

**Evenings track:** 10–15 hours/week, evenings and weekends around full-time work.

**Pre-planned acceleration windows allowed.** A vacation block or long-weekend acceleration documented in BUILD_LOG.md as part of the schedule on Day 1 is fine. Acceleration used as silent recovery after slip is the prohibited case. The discipline: acceleration is in the plan, not a private resource you draw on when behind.

In-flight track switching ("FTE for the first month, evenings after") is prohibited. It collapses into evenings track in practice with the schedule lying about it.

### 1.2 The dated start commitment

> **Build clock begins [Date X].** If external dependencies (§2) are not resolved by [Date X], the start date slips by exactly that delay and is documented in BUILD_LOG.md, not silently absorbed into week 1.

Every other date in this document is anchored to [Date X]. If [Date X] slips, every downstream date slips by exactly that amount and the BUILD_LOG records the shift.

### 1.3 Calendar anchors

| Anchor | FTE track | Evenings track |
|---|---|---|
| Build clock begins | Date X | Date X |
| Checkpoint 1 (data layer + Evidence Index live) | Date X + 4 weeks | Date X + 7 weeks |
| Checkpoint 2 (agent harness + memo end-to-end / evenings interim) | Date X + 8 weeks | Date X + 12 weeks |
| Checkpoint 3 generation phase (≥30 memos written) | Date X + 12 weeks | Date X + 19 weeks |
| Checkpoint 3 evaluation phase (backtest + audit + gates) | Date X + 13 weeks | Date X + 20 weeks |
| **Kill threshold** | Date X + 24 weeks | Date X + 24 weeks |

**FTE track buffer:** 11 weeks between Checkpoint 3 (evaluation phase) target and kill threshold. Generous.

**Evenings track buffer:** 4 weeks. **Thin.** A two-week slip at any earlier checkpoint puts the kill threshold at risk. The documented-slip discipline matters more on the evenings track.

### 1.4 Documented-slip protocol

When a week's deliverable is not complete by end-of-week:
1. BUILD_LOG.md entry written same day, naming what slipped and why
2. Recovery plan: the slipped scope is consumed by the next named buffer week (§7) explicitly
3. If buffer is exhausted: every subsequent date downstream slips by the same amount, written to BUILD_LOG.md
4. Kill threshold (Date X + 24 weeks) does not slip. If documented slip pushes Checkpoint 3 past Date X + 24 weeks, kill criterion §2.6.4 of phasing-plan.md has fired.

---

## 2. External Dependencies (Front-Loaded)

### 2.1 Sharadar Core Fundamentals

- **Where:** Nasdaq Data Link (data.nasdaq.com) — Sharadar Core US Fundamentals dataset
- **Lead time:** 3–7 business days for account approval
- **Cost:** $50–$150/month
- **Verification artifact:** API response showing successful authenticated query against `SF1` table
- **Why front-loaded:** BacktestingFramework (week 10–11) requires Sharadar; sample memo generation (week 12) requires it.

### 2.2 Provider training-data verification

**Anthropic API:**
- Default: zero-retention since 2023
- Verification artifact: console screenshot showing organization data-handling settings; T&C link captured with date stamp; sample API call with documented response headers

**OpenAI API:**
- Default: "no training on API data" since March 2023
- Verification artifact: organization settings screenshot; T&C link with date stamp; sample API call response

**Google Vertex AI / Gemini API:**
- **Vertex AI enterprise:** training-disabled by default
- **Gemini API consumer tier:** trains on inputs by default. **Do not use this surface.**
- Verification artifact: explicit documentation of which surface is in use

For all three: verification artifacts committed to `provider_verification/` directory with date stamps. v0.5 entry re-verification is the mechanical re-run of these checks.

### 2.3 API key procurement

For all providers in your routing config; keys stored in environment variables, never committed.

### 2.4 Database provisioning

**TimescaleDB + PostgreSQL:** local Docker setup or managed service. Required extensions: `timescaledb`, `pg_stat_statements`. Verification: hypertable creation test + JSONB write/read test.

### 2.5 Anthropic prompt caching configuration

Configure on Day 1, not at week 4. Cache key strategy: filings, transcripts, prior memos cached.

---

## 3. Day-Zero Artifacts

### 3.1 Repo structure

```
project-root/
├── BUILD_LOG.md
├── .claude/
│   └── agents/                     # Subagent definitions (built week 7+)
├── provider_verification/
│   ├── anthropic.md
│   ├── openai.md (or google.md)    # Skipped under Path A
│   ├── api_keys/                   # Sample API call responses (no keys)
│   └── artifacts/                  # Screenshots, T&C captures (gitignored)
├── checkpoints/                    # Empty initially; populated at C1, C2, C3
├── docs/
│   ├── v2-final-spec.md
│   ├── phasing-plan.md
│   └── implementation-sequencing.md
├── src/
│   ├── data_layer/                 # Built week 2
│   ├── evidence_index/             # Built week 3
│   ├── agent_harness/              # Built week 6 (Path A: Claude Code wrappers)
│   └── backtesting/                # Built weeks 10–11
├── tests/
├── memos/                          # Generated week 12 onward
└── README.md
```

### 3.2 BUILD_LOG.md schema

**Weekly entry template:**

```markdown
## Week N: [date range]

**Planned scope:**
- [from §4 or §5 week-N spec]

**Actual scope completed:**
- [tick / cross each planned item]

**Slipped scope (if any):**
- [item, reason for slip, recovery plan: which buffer week absorbs this]

**Buffer status:**
- Week 5 buffer: unused / consumed by [item]
- Week 9 buffer: ...

**Cost spent this week:** $X (running total: $Y)
**Projected v0.5 monthly cost based on current trajectory:** $Z (vs $400 cap)

**Pace judgment:** on pace / behind / kill threshold becoming relevant
**Evidence for judgment:** [specific, not vibes]

**Notes / decisions:** [anything worth capturing for future-tired-you]
```

### 3.3 The weekly-entry discipline

End of every week, BUILD_LOG entry written before the week closes. Even on weeks where the entry is "scope completed as planned, no slips, no notes." The entry takes 10 minutes. Skipping it is the first signal of over-commitment.

---

## 4. FTE Track: Week-by-Week Build Plan

### Week 1 — Foundation Setup

**Scope:**
- Repo initialized; BUILD_LOG.md committed Day 1
- TimescaleDB + PostgreSQL provisioned and tested
- Sharadar account application submitted (if not before [Date X])
- Provider verification artifacts captured
- API keys procured and tested
- Pluggable data layer interface designed (interface only, not implemented)
- Project structure established

**End-of-week test:** Provider verification artifacts in `provider_verification/`; databases queryable; BUILD_LOG entry for week 1 written.

### Week 2 — Data Layer Implementation

**Scope:**
- Pluggable data layer adapters (Polygon → Finnhub → yfinance → Stooq for prices)
- edgartools integration for filings
- FRED integration for macro
- Primary-source failure simulation tests

**End-of-week test:** `fetch_prices(ticker)` returns valid OHLCV with primary disabled; `fetch_filings` works against ≥3 known historical filings; `fetch_fred_series` works.

### Week 3 — Evidence Index + Append-Only Databases

**Scope:**
- Evidence Index schema implemented per v2-final §4.2.5 (including source_quality_tier)
- Predictions database with append-only constraint
- Counterfactual Ledger with append-only constraint
- Retention tiering tested with synthetic 8-quarter data
- Mechanical contamination check logic (claim text → Evidence Index row resolution; date-predating verification)

**End-of-week test:** Sample claim → row created with correct schema; deletion attempts fail; contamination check correctly rejects post-dating claims.

### Week 4 — CHECKPOINT 1: Data Layer + Evidence Index Live

**Scope:**
- Sharadar approved by now; integration completed
- Sharadar data integrity validation against ≥3 known delistings
- Checkpoint 1 artifact written per §6.1

**End-of-week test:** Checkpoint 1 written to `checkpoints/checkpoint_1.md`; on-pace/behind/kill-relevant judgment with evidence.

### Week 5 — BUFFER for Week 4 Work

**Purpose:** Catch Sharadar approval delays, late-discovered schema flaws.

If unused: BUILD_LOG explicitly notes "week 5 buffer unused; available for absorption later." Do not silently use it for additional scope.

### Week 6 — Agent Harness Scaffolding

**Scope (Path A: Claude Code subagents replace LangGraph):**
- Python wrappers around Claude Code subagent invocations
- Versioned prompts via git history of `.claude/agents/` files
- Token/cost tracking per invocation
- Process-rubric grading hook
- Provider training-data status check at startup
- Path A override acknowledgment replaces v2-final §4.3 model-family configuration check

**End-of-week test:** Dummy subagent runs through harness with cost tracked; startup check refuses to run with provider verification artifact missing.

### Week 7 — CompanyDeepDive Prompt + Ordering Enforcement

**Scope:**
- CompanyDeepDive prompt drafted (.claude/agents/company-deep-dive.md)
- Mandatory failure_scenarios-first ordering enforced
- Industry-specific addenda framework
- Output schema validation
- Mechanical contamination check integrated into output release

**End-of-week "good enough" bar (concrete):** Memo on a sample historical company that passes the mechanical contamination check, has properly populated Evidence Index references with mixed source quality tiers, and has the mandatory output ordering enforced. **Memo content quality is a week-12-onward concern measured against backtest outcomes, not a week-7 concern measured against intuition.**

### Week 8 — CHECKPOINT 2: Agent Harness + CompanyDeepDive Producing Memos

**Scope:**
- One memo end-to-end on a known-historical name
- Evidence Index references populated correctly with mixed source quality tiers
- Process rubric grading runs
- Cost per memo measured and projected
- Checkpoint 2 artifact written per §6.2

### Week 9 — BUFFER for Week 8 Work

### Week 10 — BacktestingFramework: Foundation

**Scope:**
- Walk-forward validation with embargo
- `effective_cutoff = stated_cutoff + 6 months`
- Pre-cutoff vs post-cutoff split
- Sharadar point-in-time fundamentals integration
- Realistic friction modeling (spread, market impact, commissions, tax)

### Week 11 — BacktestingFramework: Discipline Metrics

**Scope:**
- DSR with explicit trial reporting
- PBO
- Counterfactual baselines (SPY, equal-weight, sector-matched, 60/40)

### Week 12 — Sample Memo Generation Phase

**Scope (generation only, no evaluation):**
- Generate ≥30 historical CompanyDeepDive memos
  - Mix of mega-cap and mid-cap
  - Mix of pre-effective-cutoff and post-effective-cutoff entry dates
  - Each memo's reviewable_predictions tracked
- All 30 memos pass mechanical contamination check
- Backtest harness configured but **not yet run on full sample**

**End-of-week test:** 30 memos exist with valid mechanical-check passes; backtest configured for week 13 evaluation.

### Week 13 — CHECKPOINT 3: Backtest + Audit + Gate Evaluation

**Scope (evaluation phase — separated from generation per the Checkpoint 3 split):**
- Full BacktestingFramework run on the 30-memo sample
- Manual audit of 50 randomly-sampled claims against Evidence Index rows
- Phase gates evaluated per phasing-plan.md §2.5
- Checkpoint 3 artifact written per §6.3

**Why the split:** Generation (mostly waiting on agent runs) and evaluation (deep analytical attention) are different kinds of work. Bundling them into one week means either generation is rushed or evaluation is rushed.

**Margin to kill threshold from end of week 13:** 11 weeks. Generous.

---

## 5. Evenings Track: Week-by-Week Build Plan

Same milestones as FTE track at slower cadence; kill-threshold margin is thinner.

### Weeks 1–3 — Foundation Setup + Data Layer (Stretched)

- Week 1: repo, databases, provider verification, Sharadar application, API keys
- Week 2: data layer adapters (prices, filings, FRED)
- Week 3: data layer fallback testing + initial Evidence Index schema design

### Weeks 4–6 — Evidence Index + Append-Only Databases (Stretched)

- Week 4: Evidence Index schema implementation
- Week 5: Predictions DB + Counterfactual Ledger with append-only constraints
- Week 6: Retention tiering, mechanical contamination check logic, Sharadar delisting validation

### Week 7 — CHECKPOINT 1

### Week 8 — BUFFER (only buffer before Checkpoint 2)

### Weeks 9–11 — Agent Harness + CompanyDeepDive

- Week 9: Agent harness scaffolding (FTE week 6 scope, Path A subagent wrappers)
- Week 10: CompanyDeepDive prompt + ordering enforcement (FTE week 7 scope)
- Week 11: Industry addenda + first end-to-end memo

### Weeks 12–13 — Interim Phase (CHECKPOINT 2 INTERIM + Early Memo Production)

- Week 12: CHECKPOINT 2 INTERIM with reduced criteria (agent harness functional, one memo end-to-end, cost measured, viability judgment)
- Weeks 11–13 produce 3–6 memos at evenings cadence (clarifying earlier inconsistency)

**Decision tree for interim Checkpoint 2:**
- If on pace: continue to week 14
- If slipping: consume buffer week 8 (already used?) or week 13, evaluate at end of week 13
- If significantly behind: convene the kill-threshold conversation early

### Weeks 14–17 — BacktestingFramework

- Week 14: BacktestingFramework foundation
- Week 15: Sharadar point-in-time integration, friction modeling
- Week 16: DSR + PBO + counterfactual baselines
- Week 17: First backtest run on weeks 11–13 sample memos (3–6 memos, validate pipeline)

### Weeks 18–19 — Sample Memo Generation Phase

- Generate memos toward 30-memo target (typical evenings cadence ~5–8 memos/week)
- End of week 19: ≥30 memos exist; backtest configured but not yet run on full sample

### Week 20 — CHECKPOINT 3

- Full BacktestingFramework run on 30-memo sample
- Manual audit of 50 random claims
- Phase gates evaluated
- Checkpoint 3 artifact

**Margin to kill threshold:** 4 weeks. Thin.

### Weeks 21–22 — BUFFER + Sample Expansion

---

## 6. The Three Checkpoints (Written Artifacts)

Each checkpoint produces a single document committed to `checkpoints/`.

### 6.1 Checkpoint 1 — Data Layer + Evidence Index Live

**FTE: end of week 4. Evenings: end of week 7.**

**Required artifact: `checkpoints/checkpoint_1.md`**

Completion criteria checklist (each ✓/✗ with evidence):
- TimescaleDB + Postgres provisioned and queryable
- Sharadar account active with data integrity verified
- Pluggable data layer (prices) tested with primary failure
- edgartools fetching ≥3 historical filings
- FRED integration returning known macro series
- Evidence Index schema implemented with all v2-final fields
- Append-only Predictions DB (deletion-attempt test fails)
- Append-only Counterfactual Ledger (deletion-attempt fails)
- Retention tiering tested with synthetic 8-quarter data
- Mechanical contamination check rejects post-dating claims
- Mechanical contamination check accepts predating claims
- Provider verification artifacts captured

Plus: Pace judgment with evidence; Buffer status; Notes for future-tired-you.

### 6.2 Checkpoint 2 — Agent Harness + CompanyDeepDive Producing Memos

**FTE: end of week 8 (full criteria). Evenings: end of week 12 (interim, reduced criteria).**

For FTE: full agent harness, one memo end-to-end on a known-historical name, Evidence Index references populated correctly, process rubric grading hook running, cost per memo measured.

For evenings interim: agent harness functional, one memo end-to-end completed, cost per memo measured, **plus an explicit viability judgment** ("is this pace sustainable to Checkpoint 3 within the kill threshold?").

The viability judgment is the load-bearing addition for evenings track.

### 6.3 Checkpoint 3 — Phase Gates Evaluated

**FTE: end of week 13 (after Checkpoint 3 split). Evenings: end of week 20.**

**Required artifact: `checkpoints/checkpoint_3.md`**

Each phase gate from phasing-plan.md §2.5 evaluated mechanically. Pass / Fail / Kill criterion triggered for each. Final judgment: v0.1 → v0.5 advancement approved or blocked.

If approved: BUILD_LOG entry committing to v0.5 entry date.
If blocked: BUILD_LOG entry documenting which gates failed, recovery plan, revised target date. If recovery would push past kill threshold, kill criterion §2.6.4 has fired.

---

## 7. Buffer Time, Named

### 7.1 Two ways buffer hides itself

- **Padded estimates:** 20% padding on every week. Looks honest, isn't, because padding is silent.
- **End-of-timeline:** "weeks 11–12 are buffer." At week 6 you have no signal whether you're behind.

### 7.2 Named buffer schedule

**FTE track:**
- Week 5 (after Checkpoint 1): absorbs slips from weeks 1–4
- Week 9 (after Checkpoint 2): absorbs slips from weeks 6–8
- Implicit week 14+ absorption: between Checkpoint 3 evaluation end (week 13) and kill threshold (week 24)

**Evenings track:**
- Week 8 (after Checkpoint 1): absorbs slips from weeks 1–7
- Week 13 (after interim Checkpoint 2): absorbs slips from weeks 9–12
- Weeks 21–22 (between Checkpoint 3 target and kill threshold)

### 7.3 Buffer consumption rules

- Buffer consumed for slipped scope is documented in BUILD_LOG.md
- Buffer unused is documented as "available" — not silently absorbed
- Buffer cannot be borrowed from later weeks
- Buffer cannot be expanded in-flight; only legitimate expansion is documented schedule slip

---

## 8. Pre-Arming Against Over-Commitment

### 8.1 "I can do more in week 1 than the schedule says"

Week 1 scope is week 1 scope. If finished early, time is buffer or rest, not week 2 head start.

### 8.2 "BUILD_LOG.md is overhead; I'll catch up on entries when I have time"

End of every week, entry written before the week closes. 10 minutes maximum. Skipping is the first signal of over-commitment.

### 8.3 "The build is going well; I can push through the checkpoint without writing the artifact"

Checkpoint artifacts are written even when criteria pass cleanly. The artifact is the audit trail.

### 8.4 "While I'm here, let me add X"

Scope is what's in §4 or §5. Additions outside that scope go in a "v0.5 considerations" file.

### 8.5 "The kill threshold is far away; I have plenty of time"

The kill threshold is structural protection, not slack. Optimize for the target dates; the 24-week kill threshold is the boundary at which the project halts.

### 8.6 "Checkpoint 2 (interim) is for evenings track only"

FTE track Checkpoint 2 includes its own viability judgment. The judgment isn't only for evenings track.

---

## 9. The Day-One Commitment

### 9.1 The dated start

**[Date X] = ___________**

- Today's date: ___________
- Days from today to [Date X]: ___________
- External dependency status check: [list per §2]
- Operating model: FTE / evenings (no mixed-mode)

### 9.2 Day-1 first commit

The first commit message: `Initialize v0.1 build clock — start [Date X], operating model [FTE/evenings]`

The first commit's content includes:
- BUILD_LOG.md per §3.2 first-entry template
- `provider_verification/` directory with at least Anthropic verification artifact captured
- `checkpoints/` directory created (empty)
- `README.md` referencing this document and the v2-final spec

### 9.3 The commitment statement

Write this sentence in BUILD_LOG.md as the closing of the Day-1 entry, **in your own words**:

> "I commit to weekly BUILD_LOG entries, written checkpoint artifacts, documented slip not silent absorption, and scope discipline against in-flight additions. I commit to the named buffer not the silent buffer, to the dated start not the conditional start, to the kill threshold as a structural boundary not a budget. I acknowledge that the build process itself produces a record (BUILD_LOG, checkpoint artifacts, provider verification) that has standalone value regardless of whether v0.1 advances to v0.5 or hits the kill threshold. The threshold for these commitments is the moment they feel like overhead — that's when the discipline does its job."

The sentence is in your own words because the act of writing it is the commitment.

---

## 10. What This Document Protects Against

**10.1 — Silent absorption of [Date X] slip.** Prevented by §1.2 documented-slip protocol; BUILD_LOG.md tracking actual start date.

**10.2 — Padded-week-estimate buffer hiding.** Prevented by §7.1 explicit rejection; named buffer at specific weeks.

**10.3 — End-of-timeline buffer hiding.** Prevented by §7.2 explicit rejection; buffer placed immediately after work-heavy weeks.

**10.4 — Skipping BUILD_LOG entries on smooth weeks.** Prevented by §3.3 hard rule; §8.2 anti-pattern named.

**10.5 — Skipping checkpoint artifacts when criteria pass.** Prevented by §6 requirement that artifacts are written regardless of pass/fail.

**10.6 — Mid-build scope additions.** Prevented by §8.4; §1.4 documented-slip protocol surfaces scope additions as schedule slip.

**10.7 — Treating kill threshold as budget.** Prevented by §1.3 explicit framing; §8.5 anti-pattern named.

**10.8 — Skipping the evenings-track interim Checkpoint 2.** Prevented by §5 explicit requirement; §6.2 viability judgment as load-bearing artifact.

**10.9 — Mixed-mode operating model.** Prevented by §1.1 prohibition (with vacation acceleration carve-out); pick one track on Day 1.

**10.10 — Conditional start ("when ready") instead of dated start.** Prevented by §1.2 dated start commitment; §9.1 Day-1 action.

**10.11 — Borrowed buffer from later weeks.** Prevented by §7.3 explicit rule.

**10.12 — Optimizing the backtest output post-hoc.** Prevented by §4 week 11 anti-pattern; DSR with explicit trial reporting.

---

## 11. Summary

**Three Day-1 actions:**
1. Pick [Date X] and write it in BUILD_LOG.md
2. Pick operating model (FTE or evenings, not mixed) and write it in BUILD_LOG.md
3. Initiate every external dependency in §2 immediately

**Three load-bearing artifacts:**
- BUILD_LOG.md, weekly entries, every week, no exceptions
- Checkpoint artifacts (1, 2, 3), written regardless of pass/fail, mechanical not narrative
- Provider verification artifacts, captured Day 1, re-verified at v0.5 entry per phasing-plan.md

**Three operating principles:**
- Documented slip, not silent absorption
- Named buffer, not padded estimates or end-of-timeline buffer
- Scope discipline against in-flight additions

**One commitment statement:** §9.3 — written in your own words on Day 1.

**One acknowledgment:** the kill threshold at Date X + 24 weeks is structural protection, not budget.

---

The phasing doc and this implementation doc together are the contract between disciplined-now-you and the build. The threshold for whether the contract holds is the moment its discipline feels like overhead — that's when you find out whether you wrote it for the right audience.

Pick [Date X]. Commit BUILD_LOG.md. Begin.
