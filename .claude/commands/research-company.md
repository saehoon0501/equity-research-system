---
description: Full investment research flow on a US equity. Orchestrates CompanyDeepDive → BearCase → PMSupervisor in sequence. Each runs as isolated subagent. Output is a watchlist decision (ADD / REJECT / WATCH) with conviction score and recommended size band. Use when operator wants research on a specific ticker.
argument-hint: <ticker>
---

# /research-company

Orchestrates the full slow-layer research flow on a single ticker. The output is a watchlist decision based on a triangulation of bull (CompanyDeepDive), bear (BearCase), and synthesizer (PMSupervisor in main context) views.

## Argument

`<ticker>` — required. The US-listed equity ticker to research.

## Procedure

### 1. Pre-flight checks

Verify required MCPs are connected:
- `mcp__edgar` (or HTTP fallback to data.sec.gov) for filings
- `mcp__market_data` for prices, news, peer set
- `mcp__postgres` for Evidence Index and Predictions DB writes
- `mcp__fundamentals` (optional but recommended; fall back to EDGAR XBRL with explicit caveat if missing)

If any required MCP is missing, halt and tell the operator which one. Do not proceed with degraded data.

### 2. CompanyDeepDive subagent

Invoke the `company-deep-dive` subagent via Task tool with the ticker. The subagent:
- Loads references (evidence-index-schema, process-rubric, contamination-check, industry-addenda if applicable)
- Gathers inputs via MCP
- Authors the memo in mandatory order (failure_scenarios first)
- Populates Evidence Index for every claim
- Submits to Evaluator (as part of subagent post-processing)

If Evaluator rejects: subagent revises; up to 3 rounds; halt if not passing.

### 3. BearCase subagent

Invoke the `bear-case` subagent via Task tool. Pass the CompanyDeepDive memo as input. The subagent:
- Loads references
- Independently re-examines raw data (does NOT rely solely on bull memo's citations)
- Produces bear thesis with attacks-per-pillar, unrebutted concerns, valuation attack, historical analogs
- Submits to Evaluator

If Evaluator rejects (e.g., empty unrebutted_concerns): subagent revises.

### 4. PMSupervisor synthesis (this command's main context)

PMSupervisor logic runs in the operator's main context (not as a subagent — it's a synthesis of inputs already produced). The synthesis:

- Take the CompanyDeepDive BUY memo
- Take the BearCase dissent log
- Pull current watchlist composition (Postgres) for portfolio fit assessment
- Pull MacroCycleAgent latest output (cycle context)
- Pull historical calibration scores for both contributing agents

Produce a final decision:

```
TICKER: <ticker>
FINAL DECISION: ADD / REJECT / WATCH
FINAL CONVICTION: <0–1>
  Conviction haircut applied: <yes/no, basis on calibration history>
RECOMMENDED SIZE BAND: <X% – Y% of portfolio>
DISSENT ACKNOWLEDGMENT:
  - Unrebutted concern 1: <description> — accepted because <reasoning>
  - Unrebutted concern 2: <...>
POSITION CAVEATS:
  - <e.g., "only at sub-$X price", "halve size if VIX > 25">
REASONING TRACE:
  - How CompanyDeepDive memo weighted: ...
  - How BearCase concerns weighted: ...
  - How macro cycle modulated: ...
  - How calibration history modulated: ...
```

### 5. Constraints on synthesis

Per `.claude/references/process-rubric.md`:

- **Cannot ADD if unrebutted concerns are catastrophic** without explicit override-with-justification
- **Final conviction must be calibrated** against contributing agent calibration histories — overconfident sub-agents get haircut
- **Reasoning trace required** — every input must be visibly weighted

### 6. Persistence

Write to Postgres:
- The CompanyDeepDive memo (versioned in JSONB)
- The BearCase critique
- The PMSupervisor decision
- Any new Predictions DB entries (predictions from the memo)
- Any new Counterfactual Ledger entries (e.g., "if we had passed instead, what would SPY return be from this date forward")

Write to BUILD_LOG.md:
- Brief weekly note of new research conducted (if appropriate)

### 7. Output to operator

```
RESEARCH COMPLETE for <ticker>

FINAL DECISION: ADD / REJECT / WATCH
FINAL CONVICTION: X
RECOMMENDED SIZE BAND: X% – Y%

[Display PMSupervisor reasoning trace]

ARTIFACTS:
- CompanyDeepDive memo: <link or doc id>
- BearCase critique: <link or doc id>
- PMSupervisor decision: <link or doc id>
- Predictions tracked: <count>
- Evidence Index entries: <count>

NEXT STEPS:
- If ADD: run `/size <ticker>` for position sizing recommendation when ready to enter
- If WATCH: re-evaluate at <next review date or trigger>
- If REJECT: documented; counterfactual ledger will track this name's performance for postmortem
```

## Cost estimate

Per v2-final §4.7 routing tiers:
- CompanyDeepDive on Sonnet: ~$25-50 per memo (with caching)
- BearCase on Sonnet: ~$15-25
- Evaluator on Sonnet/Opus mix: ~$10-20
- Synthesis (this command's main context): minimal

Total per `/research-company` invocation: ~$50-95. Per BUILD_LOG.md cost model, v0.5 expects ~3 invocations/month plus quarterly re-underwrites.

## When to use

- New candidate identified for watchlist
- Quarterly per-name re-underwrite (use `/quarterly-reunderwrite` instead which loops over held names)
- Materiality-3 escalation from DailyMonitor (full re-underwrite triggered)

## When NOT to use

- Casual research / curiosity (this is expensive; use ad-hoc reading instead)
- v0.1 sample memo generation against historical data — this command targets current research; for historical sample generation, the underlying CompanyDeepDive subagent is invoked with date-anchored backtest framing
