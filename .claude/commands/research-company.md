---
description: Full investment research flow on a US equity. Orchestrates CompanyDeepDive → BearCase → PMSupervisor in sequence. Each runs as isolated subagent. Output is a watchlist decision (ADD / REJECT / WATCH) with conviction score and recommended size band. Use when operator wants research on a specific ticker.
argument-hint: <ticker>
---

# /research-company

Orchestrates the full slow-layer research flow on a single ticker. v1.1 uses a 4-agent ensemble: `cdd-lead` (2-stage orchestrator) dispatches `quantitative-analyst` + `strategic-analyst` in parallel (each receives a sector-specific brief built dynamically by cdd-lead Stage 1; analysts dispatch `search-agent` for data); `cdd-lead` Stage 2 integrates, verifies, distills durable learnings into `research_essentials`, and persists per-ticker briefs to `analyst_briefs`. Then `bear-case` (also dispatching `search-agent`) provides adversarial check with longitudinal anchoring against prior briefs. Finally `PMSupervisor` (in main context) synthesizes with macro/calibration context and emits ADD/WATCH/PASS/REJECT.

## Argument

`<ticker>` — required. The US-listed equity ticker to research.

## Procedure

### 1. Pre-flight checks

Verify required MCPs are connected:
- `mcp__edgar` (or HTTP fallback to data.sec.gov) for filings
- `mcp__market_data` for prices, news, peer set
- `mcp__yfinance` for consensus estimates, target prices, holders, peer comps (NEW v1.1)
- `mcp__postgres` for `evidence_index`, `research_essentials`, and `analyst_briefs` writes
- `mcp__fundamentals` (recommended; fall back to EDGAR XBRL with explicit caveat if missing)
- `mcp__fred` (used by search-agent for macro context)

Required tables (verify on first pre-flight via `mcp__postgres__schema_info`): `research_essentials` (migration 027), `analyst_briefs` (migration 028).

If any required MCP or table is missing, halt and tell the operator which one. Do not proceed with degraded data.

### 2. cdd-lead Stage 1 — pre-dispatch + brief generation + parallel analyst dispatch

Invoke the `cdd-lead` subagent via Task tool with the ticker. The subagent runs Stage 1 (8 steps):

1. **Tier classify** (HARD BRANCH) — `core_fundamental | thematic_growth | speculative_optionality` per the rubric in `.claude/agents/cdd-lead.md`. Determines which frameworks apply.
2. **Sector identify** — free-form (no fixed taxonomy). Dispatches search-agent against EDGAR Item 1 + recent news.
3. **Read prior `analyst_briefs`** for this ticker. If 0 rows: cold-start path (full sector-context sweep). If 1-2 rows: warm-start path (delta sweep against the prior brief's `created_at` timestamp).
4. **Read `research_essentials`** filtered by `topic_tags && {sector, tier, framework_keys}`. Confidence ≥3 = load-bearing; <3 = preliminary, must re-verify.
5. **Dispatch search-agent** for fresh sector context (cold-start: 8-12 calls; warm-start: 4-6 delta-focused calls).
6. **Build briefs** by filling `.claude/references/analyst-context-templates/{quantitative,strategic}.md` with sector- and company-specific content drawn from research_essentials + search findings + canonical-frameworks.md.
7. **Compute `delta_summary`** (warm-start only) — what changed since prior brief.
8. **Persist briefs** via INSERT INTO analyst_briefs (with `prior_brief_id` link if warm-start).

Then cdd-lead dispatches `quantitative-analyst` + `strategic-analyst` IN PARALLEL via the Agent tool. Each receives its brief in the dispatch prompt and produces a memo citing frameworks by `framework_key` short-keys (per `.claude/references/canonical-frameworks.md`).

### 2.5. cdd-lead Stage 2 — integration + verification + essentials distillation

Same agent context as Stage 1 (the lead-analyst subagent). After both analyst memos return:

1. **Integrate** the quant + strategic memos. Resolve cross-references (e.g., strategic-analyst's capital allocation grade on buybacks should reference quant-analyst's reverse-DCF implied_value).
2. **Dispatch search-agent for verification** — for any load-bearing claim either analyst flagged "thin" or that contradicts the prior brief, pull primary source confirmation/contradiction.
3. **Distill 0-3 durable cross-company learnings** → UPSERT INTO research_essentials (increment confidence on reaffirmation).
4. **Banned-outputs check** — Stovall rotation, PEG-only ranking, ARK point targets, Fed-without-HFI references; restructure if found.
5. **Populate evidence_index** for every numerical/dated/named-fact claim.
6. **Emit unified CDD memo** with all required v1.1 schema fields: `tier`, `sector_identification`, `brief_metadata`, `quality_gate`, `quantitative_analyst_memo`, `strategic_analyst_memo`, `integrated_thesis`, `verification_results`, `essentials_distilled`, `banned_outputs_check`, `disposition_recommendation`.

If Evaluator rejects (post-emit hook): cdd-lead revises; up to 3 rounds.

**Why the 4-agent ensemble (not monolithic CDD)**: Single-agent overload meant tier classification + 5 frameworks + sector context + integration + evidence_index population juggled in one context window. v1.1 splits along clean analytical lines. The `analyst_briefs` linked-list also enables warm-start delta detection (~30-50% token savings on repeat runs) and longitudinal drift audit ("how has our framing of NVDA evolved across the AI cycle?"). The `research_essentials` cache turns each run into a learning event for the next.

### 3. bear-case subagent (v1.1 wiring)

Invoke the `bear-case` subagent via Task tool. Pass cdd-lead's integrated CDD memo as input. The subagent:
- Loads canonical-frameworks.md
- Reads recent `analyst_briefs` for the ticker (longitudinal anchoring — the prior 2-4 briefs surface analytical drift the bear case should attack)
- Independently dispatches `search-agent` for adversarial evidence (no direct edgar/market_data/fundamentals grants in v1.1)
- Applies the 5-framework core canon ADVERSARIALLY (see §2.7 of bear-case.md)
- Enforces analog non-overlap with cdd-lead's strategic-analyst memo
- Submits to Evaluator

If Evaluator rejects (e.g., empty unrebutted_concerns, analog overlap, banned outputs): subagent revises.

### 3.5. Counterfactual veto retrieval (NEW — gap-fix 2026-05-01)

Run `src.counterfactual_veto.retrieval.retrieve_top_3` against the live `peak_pain_archetypes` table with the candidate's universal-core + sector-extension features extracted from the CompanyDeepDive memo. This is the load-bearing distinction between PRICE analogs (BearCase) and FEATURE analogs (system catalog). Without this step, /research-company materially under-uses the v3 architecture — the 45-row HMAC-signed catalog was built specifically for this lookup.

Inputs to the orchestrator-side retrieval call:
- `candidate_sector` — canonical sector from the memo (`tech_saas`, `semis_hardware`, etc.)
- `candidate_universal_core` — 6 universal-core feature values per the spec domain (founder_in_place, founder_insider_stake_direction, cash_runway, margin_trajectory, revenue_trajectory, industry_tailwind)
- `candidate_sector_extensions` — sector-specific feature dict
- `catalog` — loaded via `load_catalog_from_pg` (HMAC-verified)

Outputs:
- Top-3 RetrievalMatch objects with `case.case_id`, `case.outcome`, `similarity`, `universal_core_similarity`, `matching_features`
- `archetype_distribution(matches)` → SURVIVOR / DILUTED-SURVIVOR / NON-SURVIVOR counts
- HIGH-gate evaluation (Section 4.4 Q3 monotonic): ≥2 SURVIVOR-type → PROCEED; ≥2 NON-SURVIVOR → BLOCK; mixed → operator review

PMSupervisor consumes this in step 4 below — it MUST factor archetype distribution into the conviction rollup (LOW > HIGH > MEDIUM precedence per v3 §4.7).

### 3.6. Mode classifier — provisional (NEW — gap-fix 2026-05-01)

Compute provisional mode from realized vol bands (B = ≤30% vol; B' = 30-55%; C = 55%+). Full 3-stage classifier with LLM tiebreaker is invoked at watchlist-add time, not here — this provisional value just feeds PMSupervisor's sizing decision.

### 4. PMSupervisor synthesis (dispatched subagent — Flow B v2 Task 24)

Dispatch the `pm-supervisor` subagent via Task tool. Pass as inputs:

1. **cdd-lead integrated memo** (from §2.5)
2. **bear-case memo** (from §3)
3. **counterfactual-veto top-3 retrieval result** (from §3.5 — top-3 RetrievalMatch objects + archetype_distribution + HIGH-gate evaluation)
4. **mode classification** (from §3.6 — B / B' / C)
5. **catalyst-scout output** (from §3.7 when wired — pass `null` if catalyst-scout not yet enabled)

The pm-supervisor agent enforces the 4-tier sleeve caps (core ≤80%, thematic ≤25%, speculative ≤8%) as a **HARD GATE that runs BEFORE conviction rollup**. If a proposed ADD would breach a cap, the decision is downgraded to WATCH with a `sleeve_cap_violation` block citing the headroom remaining. Conviction rollup precedence (LOW > HIGH > MEDIUM per v3 §4.6 Phase 4 Q2), tier-aware overlays, mode-conditional sizing, and banned-outputs check all live inside the agent — see `.claude/agents/pm-supervisor.md` for the full procedure.

The agent emits a single JSON envelope (`decision`, `conviction`, `size_band`, `tier`, `mode`, `sleeve_cap_check`, `counterfactual_top3_summary`, `veto_reason`, `conviction_rationale`, `catalyst_modifier_applied`, optional `sleeve_reference`, `evidence_index_refs`). It also persists the recommendation to `execution_recommendations` (and on REJECT, `counterfactual_ledger`).

If Evaluator rejects the pm-supervisor output (banned outputs, missing sleeve_reference for speculative-tier, etc.): pm-supervisor revises; up to 3 rounds.

### 5. Constraints on synthesis

Per `.claude/references/process-rubric.md`:

- **Cannot ADD if unrebutted concerns are catastrophic** without explicit override-with-justification
- **Final conviction must be calibrated** against contributing agent calibration histories — overconfident sub-agents get haircut
- **Reasoning trace required** — every input must be visibly weighted

### 6. Persistence

Write to Postgres:
- The cdd-lead integrated CDD memo (versioned in JSONB)
- Both analyst sub-memos (quantitative + strategic) referenced from cdd-lead memo
- The bear-case critique
- The PMSupervisor decision
- `analyst_briefs` rows (already INSERTed by cdd-lead Stage 1 — confirm 2 rows per run, linked-list intact via `prior_brief_id`)
- `research_essentials` UPSERTs (already done by cdd-lead Stage 2)
- evidence_index rows (already populated by cdd-lead Stage 2)
- Predictions DB entries (from the memo)
- Counterfactual Ledger entries (e.g., "if we had passed instead, SPY return from this date forward")

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

Per v1.1 spec §16.7 + §1.4 cost note:
- cdd-lead (Stage 1 + Stage 2): ~$15-25 (orchestration + verification calls; postgres-only direct MCPs)
- search-agent dispatched ~5-10× per run: ~$10-20 (broad MCP surface)
- quantitative-analyst on Sonnet: ~$10-15 per memo (parallel with strategic; receives brief in prompt)
- strategic-analyst on Sonnet: ~$10-15 per memo (parallel)
- bear-case on Sonnet: ~$10-15 per memo
- Evaluator on Sonnet/Opus mix: ~$10-20
- Synthesis (this command's main context): minimal

Total per `/research-company` invocation: ~$60-110 (cold-start). Warm-start runs 30-50% cheaper because search-agent does delta-sweep instead of full sweep. Per BUILD_LOG.md cost model, v0.5 expects ~3 invocations/month plus quarterly re-underwrites.

## When to use

- New candidate identified for watchlist
- Quarterly per-name re-underwrite (use `/quarterly-reunderwrite` instead which loops over held names)
- Materiality-3 escalation from DailyMonitor (full re-underwrite triggered)

## When NOT to use

- Casual research / curiosity (this is expensive; use ad-hoc reading instead)
- v0.1 sample memo generation against historical data — this command targets current research; for historical sample generation, the underlying CompanyDeepDive subagent is invoked with date-anchored backtest framing
