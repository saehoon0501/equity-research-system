---
description: Full investment research flow on a US equity. Main-session orchestrator runs Stage 1 + Stage 2 CDD inline, then dispatches catalyst-scout, then pm-supervisor (which now carries the adversarial pressure-test responsibility), then a single final evaluator gate. Output is an execution recommendation (BUY / HOLD / TRIM / SELL — canonical 4-bin per HIGH-4 consensus 2026-05-16) with conviction score and recommended size band.
argument-hint: <ticker>
---

# /research-company

**Goal:** orchestrate a full slow-layer research run on `<ticker>` and emit one execution recommendation (BUY/HOLD/TRIM/SELL).

**Architecture:** main session runs 2-stage CDD inline → parallel dispatch quant + strategic specialists → integrate → catalyst-scout → pm-supervisor (synthesis + adversarial stress-test) → evaluator (single end-gate). Adversarial pressure: §4 pm-supervisor §2.6 stress-test (claim inversion), §4.5 evaluator contamination check. (§3.5 counterfactual-veto retrieval retired 2026-05-17 — see BUILD_LOG.)

Refactor provenance (cdd-lead retired, bear-case retired, search-agent retired): BUILD_LOG.md.

## Tier-1 validation — Layer 2 PostToolUse hook (2026-05-16)

**Every `Agent()` dispatch in this flow is auto-validated by the PostToolUse hook configured in `.claude/settings.local.json` → `scripts/post_agent_validate.sh`.** The hook fires automatically after each return; you do NOT need to invoke `scripts/validate_envelope.sh` per-dispatch (the only remaining manual call is §2.5.7 for the main-session-emitted CDD memo, which has no Agent() to hook into).

**Three things the orchestrator MUST do for the hook to function:**

1. **Generate a `run_id`** at the start of the run (`uuidgen` or any deterministic source — record it in your scratch state).
2. **Include `run_id: <uuid>` in every dispatch prompt body** (the hook greps the dispatch prompt for this line to locate the envelope). Missing → hook blocks with feedback.
3. **(Optional) Write a context sidecar** at `memos/envelopes/<agent>__<run_id>.context.json` BEFORE the Agent() call to pass `--case-ids` / `--catalyst-indicators` / `--resolve-evidence-db` to the validator. Absent context sidecar → validator runs without those optional flags.

**On hook block (exit 2):** Claude Code surfaces the hook's stderr as a user-feedback message. The orchestrator must address the message before proceeding. For RETRY, stderr contains a `--- BEGIN DELTA PROMPT ---` fence; extract its contents and re-dispatch the same agent with the delta-prompt as the new prompt body (atomic per-attempt; max 3 attempts enforced by the Python state machine). For ESCALATE, halt the run and surface the audit trail.

**Subagent contract (load-bearing):** each pipeline subagent (`quantitative-analyst`, `strategic-analyst`, `catalyst-scout`, `pm-supervisor`) MUST persist its structured envelope to `memos/envelopes/<agent_name>__<run_id>.json` before returning. Halt-and-degrade (e.g., catalyst-scout on polygon offline) writes an empty sidecar `<agent_name>__<run_id>.degraded` instead, which the hook recognizes as a valid skip. See each agent spec's "Envelope persistence" section for the protocol.

## Argument

`<ticker>` — required. The US-listed equity ticker to research.

## Procedure

### 1. Pre-flight checks

Verify required MCPs are connected:
- `mcp__edgar` for filings (Item 1, 1A, MD&A, 8-Ks, XBRL company facts)
- `mcp__market_data` for prices, news, real-time quote
- `mcp__yfinance` for consensus estimates, target prices, holders, peer comps, calendar, recommendations
- `mcp__postgres` for `evidence_index`, `research_essentials`, and `analyst_briefs` writes
- `mcp__fundamentals` for Sharadar PIT depth (load-bearing for D-5 forensic resolution)
- `mcp__fred` for macro context
- `mcp__polygon` for options positioning (consumed by `catalyst-scout`)
- `mcp__macro_stack` for cycle/regime context (consumed by `catalyst-scout`)

Required tables (verify on first pre-flight via `mcp__postgres__schema_info`): `research_essentials` (migration 027), `analyst_briefs` (migration 028).

If any required MCP or table is missing, halt and tell the operator which one. Do not proceed with degraded data.

### 2. Stage 1 — main-session pre-dispatch + brief generation

Run inline in the main session (formerly cdd-lead Stage 1):

1. **Tier classify** (HARD BRANCH) per the rubric below. Pull `mcp__fundamentals__get_fundamentals({ticker}, kind='PIT', n_quarters=8)` and `mcp__edgar__get_company_facts({ticker})` for revenue + op income history when needed. Default to the more conservative tier on ambiguity.

   ```
   core_fundamental
     - trailing 12mo revenue > $1B
     - AND positive op income in ≥4 of last 8 quarters
     - AND public for ≥10 years
     - examples: AAPL, MSFT, JPM, KO, JNJ

   thematic_growth
     - trailing 12mo revenue > $100M
     - AND (volatile/negative op income OR <10y public OR sector ∈ {high-growth tech, EV, semis with cyclicality, biotech with approved products})
     - examples: TSLA, PLTR, MRVL, COIN, ARM

   speculative_optionality
     - trailing 12mo revenue < $100M OR pre-revenue
     - OR sector ∈ {quantum, fusion, pre-clinical biotech, frontier autonomy, neuromorphic}
     - examples: IONQ, QUBT, RGTI, JOBY, PLUG
   ```

2. **Sector identify** — free-form (no fixed taxonomy). Call `mcp__edgar__get_filing_text({ticker}, form='10-K', section='Item 1')` for the business description; cross-reference recent news via `mcp__market_data__get_news({ticker})`. Surface SIC code for reference but do not constrain to it. Output a free-form sector label (e.g. 'infrastructure SaaS', 'memory semiconductors with HBM AI-leverage carve-out').

3. **Read prior `analyst_briefs` rows** for this ticker:

   ```sql
   SELECT brief_id, brief_type, content, sources_used, essentials_referenced,
          created_at, sector_identification, tier
   FROM analyst_briefs
   WHERE ticker = $1 AND brief_type IN ('quantitative', 'strategic')
   ORDER BY created_at DESC
   LIMIT 2
   ```

   - 0 rows: **cold-start** path (full sector-context sweep below)
   - 1-2 rows: **warm-start** path (delta sweep against the prior brief's `created_at`)

4. **Read `research_essentials`** filtered by topic_tags:

   ```sql
   SELECT key, content, confidence, last_updated
   FROM research_essentials
   WHERE topic_tags && ARRAY[<sector>, <tier>, <relevant framework_keys>]::TEXT[]
   ORDER BY confidence DESC, last_updated DESC
   LIMIT 20
   ```

   Filter to `confidence >= 3` for load-bearing use; mark `confidence < 3` as "preliminary, must re-verify."

5. **Pull fresh context directly via MCP** — main session does its own data-fetch (formerly delegated to search-agent):

   **Cold-start sweep (8-12 MCP calls):**
   - `mcp__edgar__get_company_facts({ticker})` — XBRL fundamentals + segments
   - `mcp__edgar__get_filing_text({ticker}, form='10-K', section='Item 1')` + `'Item 1A'` — business + risk factors
   - `mcp__fundamentals__get_fundamentals({ticker}, kind='PIT', n_quarters=16)` — Sharadar PIT depth
   - `mcp__yfinance__get_peer_comps({ticker})` then `mcp__yfinance__get_consensus_estimates` per peer — peer multiples
   - `mcp__yfinance__get_consensus_estimates({ticker})` + `mcp__yfinance__get_target_prices({ticker})`
   - `mcp__market_data__get_news({ticker})` — last 90d strategic developments
   - `mcp__market_data__get_real_time_quote({ticker})` + `mcp__market_data__get_prices({ticker}, lookback=90)` — D-1 mandatory 90d sanity check
   - `mcp__fred__get_series(<sector-relevant ID>)` — yield curve for banks, WTI for E&P, etc.

   **Warm-start delta sweep (4-6 MCP calls):** since `prior_brief.created_at`, focus on `mcp__market_data__get_news` + `mcp__edgar__get_filings({ticker}, lookback_days=N)` + `mcp__yfinance__get_recommendations({ticker})` delta + new peer additions.

5b. **KPI anchor pre-fetch (load-bearing for falsifier construction — post-CRWD-2026-05-16 fix)** — the orchestrator MUST fetch the most-recent earnings press release (the latest earnings-bearing 8-K Ex 99.1) and surface tier-and-sector-specific KPI baselines AS NUMBERED CURRENT VALUES (with date + primary-source citation) in brief §2 — NOT as "metrics to watch." This prevents the downstream analyst from setting bull/bear falsifier thresholds at levels that are already pre-cleared or already-tripped by reported actuals.

   **Procedure:**
   1. `mcp__edgar__get_filings({ticker, form_type: '8-K', limit: 10})` → identify the latest earnings-bearing 8-K (Item 2.02 typically; for off-calendar fiscal years, scan the last 4 8-Ks for the one referencing the most recent fiscal-quarter-end).
   2. `mcp__edgar__get_filing_text` on the corresponding Exhibit 99.1 URL (the press release document — look for `xex991.htm` or `ex991.htm` suffix).
   3. Parse for sector-relevant KPI disclosures per the tier × sector matrix below.
   4. INSERT each parsed value into `evidence_index` (returns UUIDs) and surface in brief §2 with primary citation + evidence_index_ref.

   **Tier × sector KPI anchor matrix (load-bearing keys to surface):**

   - **thematic_growth + SaaS / cybersec / observability:** module adoption % (5+/6+/7+/8+ if reported), NRR / Net Dollar-Based Retention, Gross Retention, Ending ARR, Net New ARR YoY %, RPO / cRPO, FCF margin, Non-GAAP OM, Non-GAAP subscription gross margin, Falcon-Flex-equivalent platform-pricing ARR if disclosed
   - **thematic_growth + semis:** bit growth YoY, ASP YoY, gross margin range (cycle context), capex / sales, HBM mix % of memory revenue, foundry utilization if disclosed
   - **thematic_growth + EV / autos:** deliveries QoQ + YoY, ASP $, regulatory credits revenue, automotive gross margin ex-credits, energy storage GWh
   - **core_fundamental + banks:** NIM, efficiency ratio, NPL ratio, CET1, ROTE, net charge-off rate, deposit cost
   - **core_fundamental + consumer (CPG/retail):** organic sales growth, gross margin, A&P %, FX impact, comparable-store sales, gross-margin bridge
   - **core_fundamental + hyperscaler / mega-cap tech:** capex / sales, hyperscaler segment YoY ($ basis), AI segment revenue if disclosed, segment-level operating margin, cloud RPO
   - **E&P / commodity:** production (boe/d, kbpd), realized $/boe, F&D cost, hedged %, debt/cash flow
   - **biotech:** pipeline phase status by candidate, royalty terms on approved products, cash runway months, sponsored-trial spend % of revenue
   - **speculative_optionality:** milestone tree (no numerical KPI anchor — the framework discipline is qualitative milestone-resolution, not metric thresholds)

   **Brief §2 format requirement (example — CRWD-style):**

   ```
   ## Section 2: Revenue decomposition guidance + CURRENT REPORTED KPI ANCHORS

   ### Section 2.0 — KPI Anchors (anti-stale-falsifier discipline)

   Latest reported values as of {YYYY-MM-DD fiscal-period-end} per
   {ticker} Q{N} FY{YY} press release (8-K Ex 99.1 filed {YYYY-MM-DD},
   accession {accession-number}):

   - Ending ARR: $X.XB
   - Net New ARR YoY: +XX% ($X.XB Q4 record / $X.XB FY)
   - NRR (DBNR): XX%
   - Gross Retention: XX%
   - Module adoption: XX% (6+ modules), XX% (7+), XX% (8+)
   - Falcon-Flex-equivalent ARR: $X.XXB (+XX% YoY)
   - FCF margin: XX% FY26
   - Non-GAAP OM: XX% FY26
   - Non-GAAP subscription gross margin: XX%
   - RPO: $X.XB

   Source: SEC EDGAR primary filing — evidence_index_refs: [...]

   ### Section 2.1 — Drivers to surface (existing template content follows)
   ```

   **Failure mode this prevents:** without §2.0 KPI Anchors, the analyst can construct a bull falsifier threshold below the already-reported value (pre-cleared falsifier). The Anchors block surfaces realized values before the analyst writes thresholds. See BUILD_LOG.md (CRWD 2026-05-16).

   **Sector-fit out-of-band:** if no KPI anchor matrix row matches the ticker's sector (genuinely novel category), surface a free-form list of the 5-10 most company-relevant operating metrics CRWD-style disclosed in the latest 8-K Ex 99.1, with the same date + primary-citation + evidence_index_ref discipline. Do not skip §2.0.

   **Cost:** one additional `mcp__edgar__get_filing_text` call per run (the 8-K Ex 99.1 fetch). The 8-K cover is typically returned by the existing `mcp__edgar__get_filings` call in step 5; only the Ex 99.1 text fetch is incremental.

6. **Build briefs** — read templates:
   ```
   Read .claude/references/analyst-context-templates/quantitative.md
   Read .claude/references/analyst-context-templates/strategic.md
   ```

   For each template, fill each section with sector- and company-specific content drawn from:
   - The 5-framework core canon (always applies — `Read .claude/references/canonical-frameworks.md`)
   - Selected research_essentials (from step 4)
   - Fresh MCP findings (from step 5)
   - (warm-start only) prior brief content + delta
   - Tier classification (from step 1)

   Each brief: ~1500-2500 tokens.

7. **Compute `delta_summary`** (warm-start only):

   > Tier {unchanged | core→thematic|...}.
   > Sector {unchanged | reclassified semis→AI-native}.
   > New peers {list}.
   > Material news since prior: {bullets}.
   > Framework-application changes: {e.g., "capital allocation grade upgraded B→A on $25B buyback completion"}.
   > Stale items from prior brief: {bullets}.

   Cold-start: `delta_summary` is NULL.

8. **Persist briefs**:

   ```sql
   INSERT INTO analyst_briefs
     (ticker, run_id, brief_type, tier, sector_identification,
      content, sources_used, essentials_referenced, prior_brief_id, delta_summary)
   VALUES
     ($ticker, $run_id, 'quantitative', $tier, $sector,
      $quant_brief_content, $quant_sources, $essentials_keys,
      $prior_quant_id, $delta_summary),
     ($ticker, $run_id, 'strategic', $tier, $sector,
      $strat_brief_content, $strat_sources, $essentials_keys,
      $prior_strat_id, $delta_summary)
   RETURNING brief_id, brief_type;
   ```

   Capture the returned `brief_id` values for tracking.

9. **Dispatch `quantitative-analyst` + `strategic-analyst` in parallel** via the Task tool. In ONE message. **v0.2 dispatch-prompt requirements (Overlays 1-5):** the prompts MUST explicitly surface the new required outputs so analysts don't silently regress to v1.1 schemas. **Both prompts MUST include `run_id: <uuid>` on a dedicated line so the PostToolUse hook can locate the persisted envelope at `memos/envelopes/<agent>__<run_id>.json`.**

   ```
   Agent(quantitative-analyst, "run_id: <uuid>\n\n<full quant brief content from step 6>\n\nProduce your memo per agent definition. Cite frameworks by short-key. v0.2 REQUIRED OUTPUTS: (a) `outside_view` block with intuitive_growth_pct, reference_class_growth_mean_pct via 2-tier cohort lookup, corrected_growth_pct using r=0.20, corrected_divergence_pp (Overlay 3+4); (b) `reinvestment_moat` block with incremental_roic_3y/5y, deployable_runway_years_est, quality_label A/B/C/D unless capital-light or speculative (Overlay 2); (c) `bull_case_narrative` AND `bear_case_narrative` blocks with helmer_power_anchor (snake_case, must match strategic memo) / structural_impairment_anchor, distinct_arc_description, falsifying_observable, falsifier_resolution_date (Overlay 5). Tier-conditional: speculative_optionality SKIPS all of (a)(b)(c) per agent definition. If you cite a helmer_power_anchor while strategic brief is not yet persisted, emit placeholder PENDING_STRATEGIC_RESOLUTION. PERSIST your memo to memos/envelopes/quantitative-analyst__<run_id>.json before returning.")

   Agent(strategic-analyst, "run_id: <uuid>\n\n<full strategic brief content from step 6>\n\nProduce your memo per agent definition. Cite frameworks by short-key. v0.2 REQUIRED OUTPUTS: (a) `helmer_powers_evidence[]` with power_name in canonical snake_case enum {scale_economies | network_economies | counter_positioning | switching_costs | branding | cornered_resource | process_power}, benefit_cashflow_effect, barrier_to_arbitrage, AND ≥2 primary-source citations per Power (evidence_index rows with source_quality_tier ≤ 2) — Powers without the evidence floor go to powers_assessed_not_held (Overlay 1). Buybacks bucket in capital allocation: anchor on prior_reverse_dcf_implied_value from warm-start brief OR self-computed multiple-vs-trailing-5y-median (quant memo's reverse-DCF is parallel-dispatched and not yet emitted). PERSIST your memo to memos/envelopes/strategic-analyst__<run_id>.json before returning.")
   ```

   Wait for both returns.

   **Tier-1 validation:** the PostToolUse hook (see top-of-file note) fires automatically after each agent return. It runs HG-29 quant_memo_shape + HG-26 evidence UUIDs + HG-27 outside-view blend on the quant memo, and HG-30 strategic_memo_shape + HG-26 on the strategic memo. On a RETRY block, re-dispatch the same agent with the hook's delta-prompt as the new prompt body (preserving the `run_id: <uuid>` line). Independent state files per agent: `logs/validation_state/<run_id>__quantitative-analyst.json` and `..__strategic-analyst.json`.

### 2.5. Stage 2 — main-session integration + verification + essentials distillation

After both analyst memos return, run inline in main session (formerly cdd-lead Stage 2):

1. **Integrate** the quant + strategic memos. Resolve cross-references that were deferred at parallel-dispatch time:
   - **v0.2 helmer_power_anchor resolution (Overlay 1+5):** if `quant.bull_case_narrative.helmer_power_anchor == "PENDING_STRATEGIC_RESOLUTION"`, replace with a real `power_name` from `strategic.helmer_powers_evidence[].power_name`. The replacement must satisfy: (a) canonical snake_case form, (b) the named Power has ≥2 primary-source citations in strategic memo. If no Power in strategic memo passes the evidence floor → leave anchor as PENDING_STRATEGIC_RESOLUTION and downgrade the bull case to a "speculative-bull" narrative without structural-justification anchor (this will fail evaluator HG-15 unless tier exempts; flag for re-emit).
   - **Buybacks cross-reference (I-5 fix):** strategic-analyst's capital-allocation grade on buybacks now uses self-computed multiple anchors (parallel dispatch); cross-check against quant memo's reverse-DCF implied_value at integration time and surface any disagreement in `integrated_thesis.key_open_questions`.

2. **Verify load-bearing claims directly via MCP** — for any claim either analyst flagged "thin" or that contradicts the prior brief, pull primary source confirmation:
   - Numerical claim → `mcp__fundamentals__get_fundamentals` + `mcp__edgar__get_company_facts` (D-5 forensic resolution: both must agree)
   - Filing quote → `mcp__edgar__get_filing_text` with offset reads for >50K-char filings (D-2)
   - News-only claim → `mcp__market_data__get_news` + `mcp__edgar__get_filings` press-attribution grep (D-3)

3. **Distill 0-3 durable cross-company learnings** → UPSERT INTO research_essentials (increment confidence on reaffirmation):

   ```sql
   INSERT INTO research_essentials (key, content, topic_tags, source_run_ids, confidence)
   VALUES ($key, $content, ARRAY[$tags], ARRAY[$run_id], 1)
   ON CONFLICT (key) DO UPDATE SET
     content = EXCLUDED.content,
     source_run_ids = research_essentials.source_run_ids || EXCLUDED.source_run_ids,
     confidence = research_essentials.confidence + 1,
     last_updated = now();
   ```

4. **Banned-outputs check** — scan integrated memo for: Stovall rotation, PEG-only ranking, ARK point targets, Fed-without-HFI, tier-violations (point targets for thematic, DCF for speculative). Restructure before emitting.

5. **Populate evidence_index** — for every numerical/dated/named-fact claim, INSERT a row per `.claude/references/evidence-index-schema.md`.

6. **Emit unified CDD memo** with this v1.2 schema (Overlay 1-5 fields surfaced):

   ```yaml
   ticker: <ticker>
   run_id: <uuid>
   tier: <classification>
   sector_identification: <free-form>
   brief_metadata:
     cold_start: <bool>
     prior_quant_brief_id: <uuid | null>
     prior_strat_brief_id: <uuid | null>
     delta_summary: <text | null>
     current_quant_brief_id: <uuid>
     current_strat_brief_id: <uuid>
   quality_gate:
     passes: <bool>
     piotroski_f_score: <int>
     altman_z_double_prime: <float>
     recommended_disposition_if_failed: SELL
   quantitative_analyst_memo: <inline or reference>
   strategic_analyst_memo: <inline or reference>
   # v0.2 Overlay surfacing (mirrored from upstream memos for pm-supervisor consumption):
   outside_view_summary:  # from quant memo (Overlays 3+4)
     intuitive_growth_pct: <float | "N/A speculative skip">
     reference_class_growth_mean_pct: <float>
     reference_source: <"base_rates_cohort_refined.<cohort_name>" | "mauboussin_base_rates_2016_generic_fallback" | "N/A speculative skip">
     cohort_values_placeholder: <bool>
     r_coefficient_used: 0.20
     corrected_growth_pct: <float>
     corrected_divergence_pp: <float>
   reinvestment_moat_summary:  # from quant memo (Overlay 2)
     quality_label: <"A | B | C | D | N/A capital-light | SKIPPED — speculative">
     incremental_roic_3y_trailing_pct: <float | "N/A">
     deployable_runway_years_est: <int | "N/A">
   helmer_powers_summary:  # from strategic memo (Overlay 1)
     powers_held_with_evidence: [<list of power_name in snake_case>]
     n_powers_at_evidence_floor: <int>  # count of powers with ≥2 primary citations at source_quality_tier ≤ 2
   narrative_dcf_summary:  # from quant memo (Overlay 5) — N/A for speculative
     bull_helmer_power_anchor: <power_name | "PENDING_STRATEGIC_RESOLUTION" | "N/A speculative">
     bull_falsifying_observable: <string | "N/A">
     bear_structural_impairment_anchor: <string | "N/A">
     bear_falsifying_observable: <string | "N/A">
   integrated_thesis:
     summary: <2-3 sentences>
     key_supporting_findings: [<list>]
     key_open_questions: [<list>]
   verification_results: [<list of verifies/contradicts>]
   essentials_distilled: [<keys UPSERTed>]
   evidence_index_rows_added: <int>
   banned_outputs_check: {...}
   disposition_recommendation: BUY | HOLD | TRIM | SELL   # canonical 4-bin per HIGH-4 consensus 2026-05-16; same enum pm-supervisor §8 emits as summary_code. pm-supervisor consumes this as a candidate intent (downstream synthesis can DOWNGRADE via sleeve cap / veto / LOW conviction / stress-test failure, but does NOT upgrade)
   ```

   Persist this integrated memo to disk (intermediate-memo persistence — main-session context budget discipline) and pass it as input to §3 + §3.7 + §4.

#### 2.5.7 Tier-1 validation hook for CDD integrated memo (Flavor A wiring — 2026-05-16)

The CDD memo is emitted by the main session (no subagent), but it still requires Tier-1 shape validation before being passed downstream:

```bash
scripts/validate_envelope.sh \
    --envelope memos/<TICKER>_cdd_<run_id>.json \
    --artifact-type cdd_memo \
    --run-id <run_id> \
    --agent-type cdd-integration-stage2 \
    --attempt-cost-usd 0.50
```

Because the main session is the "agent" here, RETRY semantics differ slightly: instead of re-dispatching an `Agent()` call, the orchestrator re-emits the CDD memo inline using the delta-prompt as a self-instruction (the orchestrator's own LLM patches the YAML/JSON it just wrote). Same 3-attempt cap.

**What HG-32 catches:** missing overlay-surface blocks (outside_view_summary, reinvestment_moat_summary, helmer_powers_summary, narrative_dcf_summary), banned_outputs_check missing or unstructured, invalid disposition_recommendation enum value, missing brief_metadata / quality_gate / integrated_thesis sub-keys.

If ESCALATE: this is a structural defect in the integration logic itself, not an agent regression — surface the audit trail and let the operator triage the orchestrator prompt rather than retrying mechanically.

**Why main-session orchestration**: 2026-05-12 architectural refactor — see `docs/v2-orchestrator-refactor-consensus.md`. Subagents cannot dispatch subagents on this Claude Code build, so the orchestrator logic must live at main-session level. Specialist split (quant ⟷ strategic) is preserved because Damodaran/Mauboussin valuation frameworks and Helmer/Mauboussin moat frameworks remain non-overlapping skill sets. The `analyst_briefs` linked-list enables warm-start delta detection; `research_essentials` cache turns each run into a learning event for the next.

### 3. (deleted — bear-case subagent removed 2026-05-12)

The dedicated `bear-case` adversarial subagent has been retired. Adversarial pressure now lives in two places:
- §4 pm-supervisor stress-test pass (claim-level inversion of the integrated CDD memo's load-bearing assertions, before synthesis)
- §4.5 evaluator contamination check (process-level guardrail)

If the operator wants a deeper adversarial pass, the historical `bear-case.md.removed-20260512` agent definition is preserved in `.claude/agents/` for reference and can be re-spawned ad-hoc as a one-off `Agent(general-purpose, ...)` with that prompt body.

### 3.5. (RETIRED 2026-05-17 — counterfactual-veto retrieval removed)

The peak_pain_archetypes / counterfactual_veto FEATURE-analog retrieval mechanism has been retired. Rationale: archetype matching anchored bear-DCFs at NON-SURVIVOR drawdown magnitudes regardless of falsifier clearance, producing structural HOLD bias on names that had already cleared the cited bear arcs (e.g., GOOGL Q1 FY26). Adversarial pressure for analog-based displacement-thesis pressure-testing is now handled by §4 pm-supervisor §2.6 stress-test (mechanism + falsifying-observable framing) rather than named historical analogs. See BUILD_LOG.md for the full removal rationale.

### 3.6. Mode classifier — provisional

Compute provisional mode from realized vol bands (B = ≤30% vol; B' = 30-55%; C = 55%+). Full 3-stage classifier with LLM tiebreaker is invoked at watchlist-add time, not here.

### 3.7. Dispatch `catalyst-scout` subagent

Dispatch `catalyst-scout` via Task tool. (Previously ran in parallel with `bear-case`; bear-case is now retired per §3, so catalyst-scout runs solo at this stage.) It consumes the integrated CDD memo from §2.5 as input.

Inputs passed:
- `ticker`
- `tier` (from Stage 1)
- `sector` (free-form label from Stage 1)
- `cdd_integrated_memo` (from §2.5)
- `mode` (B / B' / C from §3.6)

CatalystScout returns:
- Forward 90-day catalyst calendar (named, dated events with `kpi_impact` and `confidence`)
- Positioning panel (IV term structure + P/C ratio + unusual-activity, tier-conditional depth)
- Cross-section sentiment readings (BofA FMS, AAII, Investors Intelligence, NAAIM)
- A single `conviction_modifier` of `{direction: +1 | 0 | -1, magnitude: low | medium | high, reason: string}`

**Tier-conditional cost:**
- `core_fundamental` — light positioning → ~$6-12
- `thematic_growth` — full positioning panel + sentiment sweep → ~$15-30
- `speculative_optionality` — full panel + extra unusual_activity scrutiny → ~$20-40

If `mcp__polygon` is offline, catalyst-scout halts and reports; pm-supervisor accepts `catalyst_scout_memo = null` and proceeds with `catalyst_modifier_applied = "0 (catalyst-scout offline)"` per its §1 input-handling rule.

Note: per Consensus Item #6 (2026-05-12), catalyst-scout output is NOT individually gated by evaluator.

**Dispatch prompt MUST include `run_id: <uuid>`** so the PostToolUse hook can locate the envelope at `memos/envelopes/catalyst-scout__<run_id>.json`. Tier-1 validation (HG-31 catalyst_memo_shape, incorporating HG-24 sentiment-degradation re-count) fires automatically on return; polygon-offline halt-and-degrade writes `memos/envelopes/catalyst-scout__<run_id>.degraded` instead of an envelope and the hook treats it as a valid skip.

### 4. Dispatch `pm-supervisor` subagent

Dispatch `pm-supervisor` via Task tool. Pass as inputs:

1. **Integrated CDD memo** (from §2.5)
2. **mode classification** (from §3.6)
3. **catalyst-scout output** (from §3.7; pass `null` only if catalyst-scout halted on polygon offline)

**New responsibility (post bear-case removal 2026-05-12):** pm-supervisor MUST run an adversarial stress-test pass on the integrated CDD memo before synthesis — invert each load-bearing claim (margin assumption, moat strength, capital allocation grade, terminal value) and ask "what evidence would falsify this, and is it surfaced?" Concerns surfaced by this pass feed into the LOW-conviction trigger logic the same way bear-case findings used to.

pm-supervisor enforces the 4-tier sleeve caps (core ≤80%, thematic ≤25%, speculative ≤8%) as a **HARD GATE that runs BEFORE conviction rollup**. If a proposed ADD would breach a cap, the decision is downgraded to WATCH with a `sleeve_cap_violation` block citing the headroom remaining. Conviction rollup precedence (LOW > HIGH > MEDIUM per v3 §4.6 Phase 4 Q2), tier-aware overlays, mode-conditional sizing, and banned-outputs check all live inside the agent — see `.claude/agents/pm-supervisor.md`.

pm-supervisor emits a single JSON envelope (`decision`, `conviction`, `size_band`, `tier`, `mode`, `sleeve_cap_check`, `conviction_rationale`, `catalyst_modifier_applied`, optional `sleeve_reference`, `evidence_index_refs`). It also persists the recommendation to `execution_recommendations` and to `counterfactual_ledger` (universal write per Consensus Item #4).

**Dispatch prompt MUST include `run_id: <uuid>`** so the PostToolUse hook can locate the envelope at `memos/envelopes/pm-supervisor__<run_id>.json`. **Pass optional --catalyst-indicators via a context sidecar** written to `memos/envelopes/pm-supervisor__<run_id>.context.json` BEFORE dispatching the Agent() call:

```json
{
  "catalyst_indicators": "<path-to-§3.7-sentiment-indicators.json or null>",
  "resolve_evidence_db": true
}
```

The hook reads the sidecar and forwards values to the validator. Absence is fine (validator runs without those optional flags).

**Tier-1 validation runs BEFORE §4.5 evaluator.** On RETRY, re-dispatch pm-supervisor with the hook's delta-prompt as the new prompt body (preserving the `run_id: <uuid>` line). Max 3 attempts; the state machine owns stuck-loop fingerprint detection and cost-ledger enforcement.

**What the hook catches deterministically (no LLM eval needed):**

- HG-23 envelope shape: missing/forbidden top-level keys, missing sub-keys in `tl_dr` / `report` / `audit_trail_hint`, invalid `summary_code` enum value.
- HG-25 sizing math: conviction × mode → expected band mismatch; speculative-tier headroom clip; non-BUY zero-band invariant.
- HG-26 evidence UUIDs: `evidence_index_refs` empty / non-UUID / placeholder / duplicate / (with `resolve_evidence_db=true` in the sidecar) unresolved against `evidence_index`.
- HG-27 outside-view blend math: `corrected = intuitive*(1-r) + reference*r` consistency, including the AMZN raw==corrected signature.
- HG-28 (RETIRED 2026-05-17 — counterfactual top-3 bucket schema check removed alongside §3.5 retrieval).
- HG-24 sentiment_data_degraded: cross-check emitted flag vs the deterministic re-count from the catalyst-indicators path in the context sidecar.

**Why before §4.5:** the LLM evaluator is expensive ($3-6) and probabilistic. The hook reserves it for the semantic checks (contamination, narrative coherence, evidence sufficiency).

### 4.5. Single evaluator gate (Consensus Item #6 — locked 2026-05-12)

Dispatch `evaluator` via Task tool on the pm-supervisor output ONLY. The gate runs once, at the end, on the final synthesis.

- Mechanical contamination check on the integrated memo + catalyst-scout memo + pm-supervisor envelope
- Process-rubric scoring on pm-supervisor's decision (sleeve-cap correctness, conviction-rollup precedence, banned outputs, veto-reason completeness, **adversarial-pass completeness — replaces the former bear-case-presence check**)
- Hard-gate failures block release; soft scores feed calibration

If evaluator rejects: pm-supervisor revises (up to 3 rounds). If contamination check flags an upstream memo (quant/strategic/catalyst), the gate fails the entire run and the operator must triage which upstream agent produced the contamination.

### 5. Constraints on synthesis

Per `.claude/references/process-rubric.md`:

- **Cannot recommend BUY if unrebutted concerns are catastrophic** without explicit override-with-justification
- **Final conviction must be calibrated** against contributing agent calibration histories — overconfident sub-agents get haircut
- **Reasoning trace required** — every input must be visibly weighted

### 6. Persistence

Write to Postgres:
- The integrated CDD memo (versioned in JSONB; persisted in §2.5 step 6 to disk for context discipline, mirrored to DB here)
- Both analyst sub-memos (quantitative + strategic) referenced from integrated memo
- The catalyst-scout output
- The pm-supervisor decision
- `analyst_briefs` rows (already INSERTed in §2 step 8 — confirm 2 rows per run, linked-list intact via `prior_brief_id`)
- `research_essentials` UPSERTs (already done in §2.5 step 3)
- evidence_index rows (already populated in §2.5 step 5)
- Predictions DB entries (from the memo)
- Counterfactual Ledger entries (e.g., "if we had passed instead, SPY return from this date forward")

### 7. Output to operator

**HIGH-4 consensus 2026-05-16 (`docs/high-4-enum-drift-consensus.md`):** the prior 5-bin operator vocabulary (`ADD / WATCH / HOLD / PASS / REJECT`) is fully dissolved at BOTH the upstream CDD memo emission (§2.5 step 6 `disposition_recommendation`) AND the operator-facing output (this §7). The canonical 4-bin `BUY / HOLD / TRIM / SELL` is the single vocabulary across the entire chain — no per-layer translation tables, no enum drift. Monitoring is uniform for every ticker that completed `/research-company`, regardless of `summary_code` value (Consensus Item #2). `counterfactual_ledger` writes a row for every run, not just for SELL/TRIM outcomes (Consensus Item #4).

```
RESEARCH COMPLETE for <ticker>

FINAL DECISION: BUY / HOLD / TRIM / SELL
  (Canonical 4-bin per pm-supervisor §8 line 417. Per Consensus Item #3,
   the prior 5-bin operator vocabulary is retired. Lifecycle distinctions
   live at the postmortem-query layer, not the envelope schema.)
FINAL CONVICTION: HIGH / MEDIUM / LOW
RECOMMENDED SIZE BAND: X% – Y%   (zero for HOLD / TRIM / SELL)

[Display PMSupervisor reasoning trace]

ARTIFACTS:
- Integrated CDD memo: memos/<ticker>_cdd_<YYYY-MM-DD>.md
- CatalystScout output: <link or doc id>
- PM Report (operator-facing 6-dimension narrative; includes adversarial stress-test summary): memos/pm_reports/<TICKER>_pm_report_<YYYY-MM-DD>.md
- PM Recommendation (PostgreSQL `execution_recommendations` row; categorical bookkeeping that references the PM Report by path; does NOT duplicate the report body): row_id=<id>
- counterfactual_ledger rows: 4 (one per window: 90d / 1y / 3y / 5y; universal trigger per Consensus Item #4)
- Predictions tracked: <count>
- Evidence Index entries: <count>

NEXT STEPS:
- If BUY: run `/size <ticker>` for position sizing recommendation when ready to enter
- If HOLD: name remains under /daily-monitor sweep alongside all other researched tickers (uniform monitoring per Consensus Item #2). Re-evaluation triggers live in tl_dr.reevaluation_triggers (envelope field), not in a lifecycle bin.
- If TRIM: if a position is held, /size <ticker> --reduce computes the trim quantity; if no position is held, the row is informational only
- If SELL: if a position is held, exit it; if no position is held, the row is informational only
```

## Cost estimate (post-refactor)

Per the 2026-05-12 refactor:
- Stage 1 + Stage 2 main-session orchestration (no cdd-lead subagent): ~$3-8 (MCP calls + integration; main-session token use)
- quantitative-analyst on Sonnet with inlined MCPs: ~$10-18 per memo (parallel with strategic; does own data-fetch — wider MCP grant)
- strategic-analyst on Sonnet with inlined MCPs: ~$10-18 per memo (parallel)
- catalyst-scout on Sonnet (tier-conditional): ~$6-40 per run
- pm-supervisor on Sonnet (now includes adversarial stress-test pass): ~$8-15 (up from $5-10 to cover added responsibility)
- evaluator (once at end): ~$3-6

Total per `/research-company` invocation: ~$40-85 (cold-start). Warm-start runs 30-50% cheaper. Bear-case removal saves ~$12-20 per run; pm-supervisor takes on ~$3-5 of that for the adversarial pass; net savings ~$9-15 per run. Trade-off documented: dedicated adversarial pressure reduced from a separate-context independent agent to an embedded responsibility inside the synthesizer. See removal rationale in BUILD_LOG / auto-memory.

## When to use

- New candidate identified for watchlist
- Quarterly per-name re-underwrite (use `/quarterly-reunderwrite` instead which loops over held names)
- Materiality-3 escalation from DailyMonitor (full re-underwrite triggered)

## When NOT to use

- Casual research / curiosity (this is expensive; use ad-hoc reading instead)
- v0.1 sample memo generation against historical data — for historical sample generation, use the underlying specialist subagents directly with date-anchored backtest framing

## Architecture references

- `docs/v2-orchestrator-refactor-consensus.md` — the 6 locked consensus items from the 2026-05-12 /grill-me session that defined this refactor
- `feedback_subagent_no_nested_dispatch.md` (auto-memory) — platform fact that drove the refactor
- `project_pending_mu_test_run.md` (auto-memory) — MU test status across attempts
