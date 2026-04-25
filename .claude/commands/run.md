---
description: Master orchestrator that wraps all skills into one workflow. Auto-detects current phase (v0.1 build vs v0.5+ operations) and cadence (daily/weekly/monthly/quarterly), then routes to appropriate sub-commands in the right order. Use this as the single daily entry point to operate the system.
argument-hint: [auto|daily|weekly|monthly|quarterly|build-day|status] (default: auto)
---

# /run

The single entry point to operate the equity research system. Wraps all 12 sub-commands and 3 subagents into a coherent workflow keyed to phase + calendar position.

The intent: the operator doesn't think "what command do I need today?" — they type `/run` and the orchestrator figures it out. Override with explicit modes when needed.

## Argument

`[mode]` — optional. Default: `auto`.

Modes:
- **`auto`** (default) — detect phase + calendar position, run what's due
- **`daily`** — force daily operating cadence
- **`weekly`** — force daily + weekly cadence
- **`monthly`** — force weekly + monthly cadence
- **`quarterly`** — force monthly + quarterly cadence
- **`build-day`** — v0.1 build phase: today's build work + BUILD_LOG entry
- **`status`** — read-only status report; no execution

## Phase detection

The orchestrator first reads `BUILD_LOG.md` to determine:
- Current phase: v0.1 (paper-only) / v0.5 (limited real money) / v1.0 (full deployment)
- Operating model: FTE / evenings (per Day-1 commitment)
- Build clock start date and current week N
- Whether all v0.1 phase gates have been passed (advancement to v0.5)
- Whether all v0.5 phase gates have been passed (advancement to v1.0)

If any of this is unclear or missing, `/run` halts and reports — the system needs the BUILD_LOG.md to be consistent before orchestration can proceed.

## v0.1 phase: build-focused workflow

In v0.1, the system has no live positions and no daily operating cadence in the v0.5/v1.0 sense. The "operating" workflow is the build cadence.

### `/run auto` in v0.1

1. **Determine current build week** from BUILD_LOG.md and today's date.

2. **Check what's due today** based on the FTE or evenings track week-by-week plan in `docs/implementation-sequencing.md`:
   - Is today end-of-week? If yes: weekly BUILD_LOG entry due
   - Is today a checkpoint date? If yes: checkpoint artifact due
   - Is today within a buffer week? Different scope guidance

3. **Surface today's planned scope** from the relevant week's section.

4. **Check status of external dependencies** that should be in flight:
   - Has Anthropic verification been captured?
   - Have databases been provisioned?
   - Is Sharadar application status known? (deferred per Day-1 decision)

5. **Surface outstanding Day-1 items if not yet complete:**
   - §9.3 commitment statement written?
   - Anthropic verification artifacts captured?
   - Database provisioning done?

6. **If end-of-week**: invoke `/weekly-buildlog`.

7. **If checkpoint date**: invoke `/checkpoint <N>` — but only if the planned scope items for the checkpoint are demonstrably complete. Otherwise surface "checkpoint due but scope not complete; run `/checkpoint <N>` after the gating work is done."

8. **Output unified status:**

```
RUN — v0.1 BUILD PHASE — Week N (date X to date Y)
Operating model: FTE / evenings

PHASE PROGRESS:
  Build clock: <today> (week <N> of 24-week kill threshold)
  Margin to kill threshold: <weeks remaining>

DAY-1 OUTSTANDING:
  □ §9.3 commitment statement: [written / not written]
  □ Anthropic verification: [captured / pending]
  □ Database provisioning: [done / pending]
  [If any pending: surface clearly as blocker for week 1 day 2+ work]

THIS WEEK'S SCOPE (from implementation-sequencing.md §4 or §5):
  - [item 1]: [status]
  - [item 2]: [status]
  ...

TODAY'S RECOMMENDED FOCUS:
  - [based on what's pending and what's earliest in the week]

UPCOMING:
  - End of week: <date> — weekly BUILD_LOG entry due (run /weekly-buildlog)
  - Next checkpoint: Checkpoint <N> on <date>
  - Buffer week: week <N> (<date>)

PACE JUDGMENT (last BUILD_LOG entry): <on pace / behind / kill threshold becoming relevant>

NEXT ACTIONS:
  - [actionable items]
```

### `/run build-day` in v0.1

Explicit "I'm working on the build today" mode:

1. Surface today's scope from the relevant week's plan
2. After operator does the work and reports completion: invoke `/weekly-buildlog` if end-of-week, or remind operator to run it then
3. Do not run any operational commands (no /daily-monitor, /macro-cycle, etc.) — those don't apply in v0.1

### `/run status` in v0.1

Read-only:
- Current week + days remaining in week
- Margin to kill threshold
- Outstanding Day-1 items
- This week's planned scope
- Pace judgment from last BUILD_LOG entry

No execution, no prompts. Just report.

### Phase boundaries in v0.1

- **End of week 4 (FTE) / week 7 (evenings):** prompt operator to run `/checkpoint 1` if not already done
- **End of week 8 (FTE) / week 12 (evenings):** prompt for `/checkpoint 2`
- **End of week 13 (FTE) / week 20 (evenings):** prompt for `/checkpoint 3`
- **If `/checkpoint 3` advancement = APPROVED:** congratulate; switch phase to v0.5; future `/run auto` invocations use v0.5 workflow
- **If `/checkpoint 3` advancement = BLOCKED:** surface the blockers; recovery mode

## v0.5 / v1.0 phase: operational workflow

In v0.5/v1.0, the system has live positions with a real daily cadence.

### `/run auto` in v0.5/v1.0

1. **Determine today's cadence triggers:**
   - Daily: always (if positions exist)
   - Weekly: today is end-of-week
   - Monthly: today is last business day of month
   - Quarterly: today is last business day of quarter

2. **Run cadence in order from highest to lowest:** quarterly first (if applicable), then monthly, weekly, daily. Some commands within each layer are idempotent — they'll detect prior runs from today and skip.

3. **Daily layer (always runs in v0.5/v1.0):**

   a. **Pre-flight check MCPs:**
      - `mcp__postgres` connected (load-bearing)
      - `mcp__edgar` connected
      - `mcp__market_data` connected
      - `mcp__brokerage` connected (v0.5+)
      - If any required MCP missing: halt and report

   b. **Run brokerage reconciliation:**
      - Per v2-final §4.5, market close + 1 hour
      - Compare system's expected positions vs brokerage actual
      - If reconciliation fails: enter READ_ONLY_MODE, halt further execution, alert operator

   c. **Resolution job:**
      - Resolve any predictions due today per `prediction-resolution.md`
      - Insert resolution records (append-only)
      - Update calibration history

   d. **Invoke `/daily-monitor`:**
      - Tier 1 + Tier 2 classification of news/filings
      - Surface materiality-3 escalations
      - For each escalation: prompt operator to consider `/quarterly-reunderwrite <ticker>`

   e. **Invoke `/exit-check <ticker>` for every held position:**
      - Tax-aware exit signal evaluation
      - Surface signals; do NOT auto-execute trades (per §4.5 hard human-approval gate)
      - For positions at a loss with stable thesis: surface optional `/wash-sale-harvest <ticker>` invocation

   f. **Invoke `/entry-check <ticker>` for any watchlist names with PMSupervisor approval but not currently held:**
      - Entry quality scoring
      - Surface STRONG_ENTRY signals; recommend operator run `/size <ticker>` next

4. **Weekly layer (if today is end-of-week):**

   a. **Invoke `/macro-cycle delta`** — refresh cycle/regime view
      - If regime changed: highlight prominently; sizing modifier shifted

   b. **Invoke `/weekly-buildlog`** — guided weekly entry per the BUILD_LOG.md schema

5. **Monthly layer (if today is end-of-month):**

   a. **Tax-loss harvest scan:**
      - Identify all positions down >15% with stable thesis
      - For each, surface `/wash-sale-harvest <ticker>` recommendation
      - Operator decides whether to execute

   b. **Counterfactual ledger quarterly summary** (if quarter-end approaching):
      - Aggregate per-agent attribution
      - Cumulative system performance vs counterfactual baselines

6. **Quarterly layer (if today is end-of-quarter):**

   a. **Invoke `/macro-cycle full`** — full structural cycle view rebuild

   b. **Invoke `/quarterly-reunderwrite`** (no ticker arg = all held positions) — full re-underwrite per held name
      - This is expensive ($1500-4750/quarter for 30-50 positions); flag the cost
      - Run sequentially per position; surface results

   c. **LearningLoop activation gate check** (v1.0 only):
      - Per phasing-plan.md §4.5: ≥90 resolved predictions, ≥10 closed positions with postmortems, regime diversity, strategy quality bar
      - If gates pass for first time: prompt operator to consider activation; activation is a one-way door

7. **Compose unified output:**

```
RUN — v0.5 OPERATING PHASE — <date>
Cadence layers run: daily | weekly | monthly | quarterly

DAILY:
  Reconciliation: PASS | FAIL (READ_ONLY_MODE if FAIL)
  Predictions resolved today: N
  Daily monitor digest: [summary; full output below]
    Materiality-3 escalations: [list or "none"]
    Score distribution: [breakdown]
  Exit signals: [list of held positions with non-NONE signals]
  Entry signals: [list of watchlist names with STRONG_ENTRY]

[If weekly: WEEKLY section with macro cycle update + buildlog confirmation]

[If monthly: MONTHLY section with harvest candidates + counterfactual summary]

[If quarterly: QUARTERLY section with re-underwrite results]

ACTIONS REQUIRING OPERATOR DECISION:
  1. [each requires explicit yes/no/defer]
  2. ...

COST TODAY: $X
RUNNING MONTHLY COST: $Y vs $400 budget cap

PACE / CALIBRATION:
  Per-agent calibration trends: [brief summary]
  Counterfactual ledger trend: [brief]
  Drawdown from peak: <if relevant>
```

### `/run daily` (force) in v0.5/v1.0

Skip phase detection; run only the daily layer above.

### `/run weekly` (force)

Run daily + weekly layers.

### `/run monthly` (force)

Run weekly + monthly.

### `/run quarterly` (force)

Run all four layers.

### `/run status` in v0.5/v1.0

Read-only:
- Current portfolio composition (from Postgres)
- Drawdown from peak
- Latest cycle score and aggressiveness modifier
- Per-agent calibration trends
- Counterfactual ledger summary
- Outstanding actions awaiting operator decision

## Idempotency

The orchestrator detects prior runs from today and avoids duplicating work:

- If `/daily-monitor` already ran successfully today: skip the run, surface yesterday's summary as "yesterday's last completed daily run"
- If `/weekly-buildlog` was completed this week: skip the prompt, confirm done
- If `/macro-cycle delta` ran this week: skip
- If `/quarterly-reunderwrite` ran this quarter: skip (full re-underwrite is expensive)

Force a re-run with explicit mode: `/run daily` re-runs daily even if already done.

## Read-only mode (status)

`/run status` is always safe — it reads but never executes. Use this when:
- Returning to the project after time away (orient yourself)
- Before a checkpoint to review what's accumulated
- During a calibration safety alert (calibration degrading two consecutive months)

## What `/run` does NOT do

- Does not auto-execute trades. Per v2-final §4.5 hard human-approval gate, all trade actions require explicit operator confirmation.
- Does not auto-approve materiality-3 escalations as thesis re-underwrites. The operator decides whether to invoke `/quarterly-reunderwrite <ticker>` after seeing the escalation.
- Does not auto-execute tax-loss harvests. Recommendations surfaced; operator executes manually with brokerage.
- Does not auto-activate LearningLoop. Activation is a one-way door per phasing-plan.md §4.5; requires explicit operator confirmation when gates pass.
- Does not skip the mechanical contamination check. Every memo produced through subagent invocation goes through the Evaluator hard gate; outputs that fail are returned for revision.
- Does not bypass the hard concentration limits. Position sizing recommendations are bounded by single-name (8%), sector (35%), top-5 (50%) caps regardless of model output.

## Cost guidance

- v0.1 daily / build-day: ~$0 — mostly orchestration of operator-driven work
- v0.5 daily: ~$3-5 (DailyMonitor Tier 1 + Tier 2 escalations + ExitSignals)
- v0.5 weekly day: ~$8-12 (daily + macro-cycle delta + buildlog)
- v0.5 monthly day: ~$12-20 (weekly + harvest scan)
- v0.5 quarterly day: ~$200-500 (monthly + macro-cycle full + quarterly-reunderwrite for all held positions; this is the cost spike)

The quarterly cost spike is the largest single contributor in v0.5/v1.0. Document in BUILD_LOG.md when invoked.

## When to invoke

**Daily** in v0.5/v1.0 — typical morning routine: `/run` (auto detects daily cadence)

**Weekly day** (Friday for FTE; Sunday for evenings) — `/run` will detect end-of-week and add weekly layer

**Monthly / quarterly** — `/run` detects calendar boundaries

**v0.1 build days** — `/run build-day` to focus on build work + BUILD_LOG cadence

**Returning after time away** — `/run status` first to orient; then `/run` to execute what's due

**Phase transitions** (v0.1 → v0.5, v0.5 → v1.0) — `/run` detects phase change after `/checkpoint` advancement decision; switches to new phase's workflow on next invocation

## Implementation note

This command is the orchestrator; it doesn't replace any sub-command. Each sub-command remains independently invocable. `/run` is the wrapper that knows the canonical sequencing. If the operator wants to run individual commands directly (e.g., `/research-company NVDA` ad-hoc), that path remains.

The orchestrator runs in main context (no subagent), so the operator sees its execution. Sub-commands invoked from within `/run` may spawn their own subagents (CompanyDeepDive, BearCase, Evaluator) — those isolations are preserved.

## Failure modes

- **MCP missing** mid-execution: halt the current cadence layer; report which MCP; do NOT attempt subsequent commands that depend on it
- **Sub-command error**: capture the error, log to BUILD_LOG.md, attempt to continue with remaining commands; surface failures in unified output
- **Cost cap hit mid-execution**: per v2-final §4.7, hard cap at $600/mo halts non-essential agent runs. `/run` will surface "cost cap reached; deferring remaining non-essential commands; daily-monitor + exit-check still ran (essential)"
- **Reconciliation failure**: enter READ_ONLY_MODE; do NOT proceed to any commands that could produce trade recommendations or modify state
