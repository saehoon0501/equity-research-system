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

Required tables (verify on first pre-flight via `mcp__postgres__schema_info`): `research_essentials` (migration 027), `analyst_briefs` (migration 028), `parameters` + `parameters_active` view (migration 004 + 033), `run_parameters_snapshot` (migration 034).

If any required MCP or table is missing, halt and tell the operator which one. Do not proceed with degraded data.

### 1.5. Parameter snapshot + invariant validation (HARD GATE — runs BEFORE any data work)

**Purpose:** every numeric threshold consumed by /research-company subagents (sleeve caps, conviction bands, mode multipliers, tier cutoffs, quality gates, DCF sensitivity bounds, catalyst-scout signal thresholds, evaluator gate values) is sourced from the `parameters_active` view in postgres — NOT from hardcoded literals in skill markdown. This block pins a single snapshot for the entire 5-stage chain, validates lockstep invariants, persists the snapshot, and composes per-subagent PARAMETERS_USED header blocks. Per /review-me v7-final convergence 2026-05-18.

**Architectural contract:** the PARAMETERS_USED header block injected into each subagent's dispatch prompt is **ground truth**. If a numeric appears in both the header block and the agent's prose instructions, the **block wins**. Agents must cite the block, not the prose.

**Step 0 — Parse args (TICKER extraction).**

The Claude Code slash-command harness substitutes `$1` in this spec body with the **entire args string** (e.g. `GOOGL --as-of-tag=722b... --as-of-tag-sig=c637... --as-of-tag-issued-at=1779114639`), not just the first positional token. The orchestrator MUST therefore parse the ticker out of the args string before issuing any ticker-keyed SQL.

Set:
```
TICKER = uppercase(first_space_delimited_token_of("$1"))
```

Equivalent shell: `TICKER=$(echo "$1" | cut -d' ' -f1 | tr '[:lower:]' '[:upper:]')`. (Note: `cut` rather than `awk '{print $1}'` because awk's `$1` field reference would collide with the harness's `$1` substitution — both would be rewritten to the full args string, breaking the awk command.)

`$TICKER` is the canonical ticker identifier for the remainder of this run. Every SQL in this spec that previously read `$1` as the ticker has been hardened to read `$TICKER` instead; do NOT use bare `$1` in orchestrator-executed SQL (it expands to the full args string and corrupts queries — see post-mortem in BUILD_LOG.md for the GOOGL-2026-05-18 sweep-run defect that motivated this guard). If a SQL example in this spec still contains `$1`, treat it as documentation of bind-parameter notation in OTHER agents' queries (e.g. evaluator's HG-25), not as something the orchestrator should execute verbatim.

**Step 1 — Generate run_id.** Use `uuidgen` or any deterministic UUID source. Record as `RUN_ID`. This same `run_id` flows into every dispatch prompt body (per §0 hook contract) AND into the snapshot row INSERT (Step 4 below) AND into the evaluator dispatch (§4.5 — see "Evaluator parity injection" below).

**Step 2 — Resolve `--as-of-tag` arg (sweep test runs only).**

If the operator invoked `/research-company TICKER --as-of-tag=<value> --as-of-tag-sig=<hex> --as-of-tag-issued-at=<unix>`, the PreToolUse hook at `scripts/research_company_as_of_tag_gate.sh` has ALREADY validated the HMAC sig and time window before this orchestrator runs. By the time you read this, the args are either valid or the dispatch was aborted with exit 2. Record `TAG = "<value>"`, `TAG_SIG = "<hex>"`, `TAG_ISSUED_AT = <unix>` for the Step 4 INSERT. If no `--as-of-tag` arg is present, `TAG = NULL` (production run).

**Step 3 — Snapshot in a single REPEATABLE READ transaction.** Execute via `mcp__postgres__query`:

```sql
BEGIN ISOLATION LEVEL REPEATABLE READ;
SELECT parameter_key, value, version_id
FROM parameters_active
WHERE parameter_namespace IN (
    'sizing','tier_classification','quality_gate','dcf','outside_view',
    'wacc','reinvestment_moat','catalyst_scout','mode','evaluator','falsifier'
);
COMMIT;
```

(If `TAG IS NOT NULL`, replace `parameters_active`'s default `tag IS NULL` filter by querying the underlying `parameters` table with `WHERE tag = $TAG` plus the standard DISTINCT ON / latest-effective_at logic. The PreToolUse hook has already validated authorization.)

Record the returned rowset as `SNAPSHOT_ROWS`. This is the **canonical input** for the entire run. The invariant validator (Step 5) and the per-subagent PARAMETERS_USED composer (Step 6) MUST both iterate over `SNAPSHOT_ROWS` in-memory; **do NOT re-query `parameters_active` mid-run** — that would defeat REPEATABLE READ's snapshot guarantee.

**Step 4 — Compute hash, INSERT snapshot row.**

```
EFFECTIVE_MAP = { row.parameter_key: row.value for row in SNAPSHOT_ROWS }
EFFECTIVE_JSON = canonical_json(EFFECTIVE_MAP)  # sort_keys=True, separators=(',', ':')
EFFECTIVE_HASH = sha256(EFFECTIVE_JSON).hexdigest()
PARAMETERS_VERSION_MAX = max(row.version_id for row in SNAPSHOT_ROWS)

INSERT INTO run_parameters_snapshot (
    run_id, ticker, parameters_version_max,
    effective_parameters_jsonb, effective_parameters_hash,
    tag, tag_signature, tag_issued_at_unix
) VALUES (
    RUN_ID, $TICKER, PARAMETERS_VERSION_MAX,
    EFFECTIVE_JSON::jsonb, EFFECTIVE_HASH,
    TAG, TAG_SIG, TAG_ISSUED_AT
);
```

**Step 5 — Invariant validator (3 named INVs; runs against `SNAPSHOT_ROWS` in-memory only).**

INV-1 (reinvestment_moat monotonic ordering — HARD FAIL):
```
require: spread_A >= spread_B >= spread_C
require: runway_A >= runway_B >= runway_C
where:
  spread_A = EFFECTIVE_MAP['reinvestment_moat.label_A.min_roic_spread_pp']
  spread_B = EFFECTIVE_MAP['reinvestment_moat.label_B.min_roic_spread_pp']
  spread_C = EFFECTIVE_MAP['reinvestment_moat.label_C.min_roic_spread_pp']
  (same for *.min_runway_years)
```
On violation: HARD FAIL with named code INV-1. Execute the terminal UPDATE inline:
```sql
UPDATE run_parameters_snapshot
SET run_ended_at = NOW(),
    run_status   = 'failed_INV-1'
WHERE run_id = $RUN_ID;
```
If that UPDATE itself fails (DB transient), the orchestrator still halts and surfaces the violation; the orphan row is finalized post-hoc by `scripts/reconcile_orphan_snapshots.sh` to `'failed_uncaught'`. Log the UPDATE failure to `system_errors` for operator visibility:
```sql
INSERT INTO system_errors (source, error_type, error_detail, blocked_decision) VALUES (
  'research_company_orchestrator',
  'snapshot_update_failed',
  json_build_object('run_id', $RUN_ID, 'intended_status', 'failed_INV-1', 'stage', 'inv_1_terminal_update')::text,
  'research_company_' || $TICKER || '_' || to_char($RUN_STARTED_AT, 'YYYY-MM-DD"T"HH24:MI:SS')
);
```
Surface the violation to operator. Exit.

INV-2 (RETIRED per /review-me 2026-05-19): formerly checked `wacc.erp_sensitivity_band_bps / wacc.erp_refresh_drift_bps == 2.0` as a SOFT WARN. Adjudicated TUNABLE — the two parameters serve unrelated functions (cache-refresh trigger vs output sensitivity band) and the 2.0 ratio is coincidental, not methodologically required. ERP-DGS10 monthly coupling regression (slope ~0.3-0.5, R²<0.3) falsifies the load-bearing "50bps DGS10 = 50bps ERP staleness" interpretation. Validator now skips directly from INV-1 to INV-3. See `docs/superpowers/audits/2026-05-18-parameter-externalization-phase3-audit-checklist.md` § INV-2 disambiguation slot (RESOLVED 2026-05-19) for the full adjudication.

INV-3 (austere DCF fade triple sanity — HARD FAIL):
```
require: EFFECTIVE_MAP['dcf.austere_growth_fade_years'] <= EFFECTIVE_MAP['dcf.austere_roic_fade_years']
require: 0 <= EFFECTIVE_MAP['dcf.austere_terminal_growth_dgs10_premium_pct'] <= 5
```
On violation: HARD FAIL with named code INV-3. Execute the terminal UPDATE inline:
```sql
UPDATE run_parameters_snapshot
SET run_ended_at = NOW(),
    run_status   = 'failed_INV-3'
WHERE run_id = $RUN_ID;
```
If that UPDATE itself fails, log to `system_errors` and rely on the reconcile-script fallback (symmetric to INV-1):
```sql
INSERT INTO system_errors (source, error_type, error_detail, blocked_decision) VALUES (
  'research_company_orchestrator',
  'snapshot_update_failed',
  json_build_object('run_id', $RUN_ID, 'intended_status', 'failed_INV-3', 'stage', 'inv_3_terminal_update')::text,
  'research_company_' || $TICKER || '_' || to_char($RUN_STARTED_AT, 'YYYY-MM-DD"T"HH24:MI:SS')
);
```
Surface the violation to operator. Exit.

**Step 6 — Compose per-subagent PARAMETERS_USED header blocks.** Filter `EFFECTIVE_MAP` per subagent namespace consumption:

- `quantitative-analyst` consumes: `quality_gate.*`, `dcf.*`, `outside_view.*`, `wacc.*`, `reinvestment_moat.*`, `falsifier.*`, plus **(v0.2)** `flow.erp_add_bps.gamma_<bin>` — orchestrator reads `gamma_regime.bin` from flow-overlay envelope (Stage 1) and scopes the corresponding `flow.erp_add_bps.gamma_positive|neutral|negative` value into quant-only block. Strategic-analyst PARAMETERS_USED block does NOT receive `flow.erp_add_bps.*` (architectural invariant — strategic is regime-blind per `feedback_llm_schemas_validation_not_interface.md` style).
- `strategic-analyst` consumes: `evaluator.gate.helmer_*` (for citation-floor self-check)
- `tactical-overlay` consumes: `tactical.*`, `tactical_disposition.*`, `tactical_cell.*`, plus `sizing.conviction_band.HIGH.{min,max}_pct` + `sizing.conviction_band.MEDIUM.{min,max}_pct` (band-position selector reads existing band params per Section 2 v3-final Plan A v3 — no new sizing rows)
- `flow-overlay` consumes: `flow.*`, `flow_disposition.*`, `flow_cell.*`, plus `sizing.conviction_band.HIGH.{min,max}_pct` + `sizing.conviction_band.MEDIUM.{min,max}_pct` (reuses the same band params as tactical-overlay; no new sizing rows). v0.1 CTA-proximity sub-signal only — gamma/GEX inputs are v0.2, crowding inputs are v0.3.
- `catalyst-scout` consumes: `catalyst_scout.*`
- `pm-supervisor` consumes: `sizing.*`, `mode.*`, `dcf.thematic_growth_implied_vs_historical_cagr_cap_ratio`, plus `outside_view.divergence_alert_pp` (§2.6 stress-test routing), plus **(v0.2)** `sizing.tech_axis_bullish_score_min` (externalized TECH axis cutoff for 6-signal world), plus reads tactical-overlay envelope at `memos/envelopes/tactical-overlay__<run_id>.json` AND flow-overlay envelope at `memos/envelopes/flow-overlay__<run_id>.json` for tactical_signal_bin + tactical_cell + flow_signal_bin + flow_cell surfacing per Section 1 #4 soft-modulator
- `evaluator` consumes: `evaluator.gate.*`, `quality_gate.*`, `falsifier.max_resolution_horizon_months`, `dcf.reconciliation_divergence_pct_floor`

Each per-subagent header block has this exact shape (injected at the TOP of the dispatch prompt body, before `run_id: <uuid>`):

```
=== PARAMETERS_USED (parameters_version_max: <uuid>, effective_parameters_hash: <hex>, tag: <NULL|sweep_xxx>) ===
<key.path>: <value>
<key.path>: <value>
...
=== END PARAMETERS_USED ===

[GROUND TRUTH] If a numeric appears in both the block above and the prose
instructions below, the block wins. Cite the block, not the prose.
```

**Step 7 — Failure modes (DB-unreachable hard-fail, inherits evaluator.md §HG-1).**

If `mcp__postgres__query` fails at Step 3 (snapshot SELECT) → HARD FAIL the run with code `MCP_POSTGRES_UNREACHABLE_AT_SNAPSHOT`. Same precedent as evaluator.md:861 ("If `mcp__postgres` is not connected, you cannot run mechanical contamination check. In this case: REJECT all outputs by default."). No fallback to hardcoded literals. No cached snapshot bypass. Surface to operator with the message "parameters table unreachable; rerun when DB recovers."

If `INSERT INTO run_parameters_snapshot` fails at Step 4 → same hard-fail discipline.

**Evaluator parity injection (preview — §4.5 actually injects).** When you reach §4.5 evaluator dispatch, you MUST inject `run_id: <RUN_ID>` into the evaluator prompt body AND write a sidecar at `memos/envelopes/evaluator__<RUN_ID>.context.json` carrying `{run_id, run_parameters_snapshot_id, parameters_version_max, effective_parameters_hash}`. The evaluator's HG-25 (Phase 5 gate) performs a DB roundtrip `SELECT 1 FROM run_parameters_snapshot WHERE run_id = :run_id` to confirm the chain context. Without injected run_id, evaluator soft-warns (standalone /evaluate carve-out); with run_id present but no matching DB row, evaluator HARD REJECTs as spoofed.

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
   WHERE ticker = $TICKER AND brief_type IN ('quantitative', 'strategic')
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

9. **Dispatch `quantitative-analyst` + `strategic-analyst` + `tactical-overlay` + `flow-overlay` in parallel** via the Task tool. In ONE message. **v0.2 dispatch-prompt requirements (Overlays 1-5):** the prompts MUST explicitly surface the new required outputs so analysts don't silently regress to v1.1 schemas. **All four prompts MUST include `run_id: <uuid>` on a dedicated line so the PostToolUse hook can locate the persisted envelope at `memos/envelopes/<agent>__<run_id>.json`.** **AND all four prompts MUST be prefixed with the per-subagent PARAMETERS_USED header block composed in §1.5 Step 6.** Quantitative-analyst's block carries `quality_gate.*`, `dcf.*`, `outside_view.*`, `wacc.*`, `reinvestment_moat.*`, `falsifier.*` keys; strategic-analyst's block carries `evaluator.gate.helmer_*` keys; tactical-overlay's block carries `tactical.*`, `tactical_disposition.*`, `tactical_cell.*`, plus `sizing.conviction_band.{HIGH,MEDIUM}.{min,max}_pct` (per Section 2 v3-final + Section 2.1 v5-final); flow-overlay's block carries `flow.*`, `flow_disposition.*`, `flow_cell.*`, plus `sizing.conviction_band.{HIGH,MEDIUM}.{min,max}_pct` (v0.1 CTA-proximity sub-signal only). The agent's first action MUST be to honor the block per the [GROUND TRUTH] instruction.

   ```
   Agent(quantitative-analyst, "<PARAMETERS_USED block from §1.5 Step 6 filtered to quant namespaces>\n\nrun_id: <uuid>\n\n<full quant brief content from step 6>\n\nProduce your memo per agent definition. Cite frameworks by short-key. v0.2 REQUIRED OUTPUTS: (a) `outside_view` block with intuitive_growth_pct, reference_class_growth_mean_pct via 2-tier cohort lookup, corrected_growth_pct using r=PARAMETERS_USED['outside_view.bayesian_shrinkage_r'], corrected_divergence_pp (Overlay 3+4); (b) `reinvestment_moat` block with incremental_roic_3y/5y, deployable_runway_years_est, quality_label A/B/C/D applied per PARAMETERS_USED['reinvestment_moat.label_*'] thresholds unless capital-light or speculative (Overlay 2); (c) `bull_case_narrative` AND `bear_case_narrative` blocks with helmer_power_anchor (snake_case, must match strategic memo) / structural_impairment_anchor, distinct_arc_description, falsifying_observable, falsifier_resolution_date within PARAMETERS_USED['falsifier.max_resolution_horizon_months'] forward (Overlay 5). Tier-conditional: speculative_optionality SKIPS all of (a)(b)(c) per agent definition. If you cite a helmer_power_anchor while strategic brief is not yet persisted, emit placeholder PENDING_STRATEGIC_RESOLUTION. PERSIST your memo to memos/envelopes/quantitative-analyst__<run_id>.json before returning.")

   Agent(strategic-analyst, "<PARAMETERS_USED block from §1.5 Step 6 filtered to strategic namespaces>\n\nrun_id: <uuid>\n\n<full strategic brief content from step 6>\n\nProduce your memo per agent definition. Cite frameworks by short-key. v0.2 REQUIRED OUTPUTS: (a) `helmer_powers_evidence[]` with power_name in canonical snake_case enum {scale_economies | network_economies | counter_positioning | switching_costs | branding | cornered_resource | process_power}, benefit_cashflow_effect, barrier_to_arbitrage, AND >= PARAMETERS_USED['evaluator.gate.helmer_min_primary_source_citations'] primary-source citations per Power (evidence_index rows with source_quality_tier <= PARAMETERS_USED['evaluator.gate.helmer_max_source_quality_tier']) — Powers without the evidence floor go to powers_assessed_not_held (Overlay 1). Buybacks bucket in capital allocation: anchor on prior_reverse_dcf_implied_value from warm-start brief OR self-computed multiple-vs-trailing-5y-median (quant memo's reverse-DCF is parallel-dispatched and not yet emitted). PERSIST your memo to memos/envelopes/strategic-analyst__<run_id>.json before returning.")

   Agent(tactical-overlay, "<PARAMETERS_USED block from §1.5 Step 6 filtered to tactical namespaces>\n\nrun_id: <uuid>\n\nticker: <TICKER>\nas_of_date: <as_of_date>\ntier: <tier>\nsector: <sector>\nmode: <mode>\n\nProduce your envelope per agent definition. Algorithm: (1) snap as_of_date to monthly anchor (first_trading_day_of_month, prior-month close), (2) fetch 12mo prices for ticker + SPY via mcp__market_data__get_prices, (3) fetch DGS1 window via mcp__fred__get_series sized per INV-B6, (4) call src/p8_tactical_overlay/bin_classifier.py::classify() with the fetched data, (5) emit envelope per src/evaluator_gates/tactical_envelope_shape.py schema. PARAMETERS_USED block wins over any prose numerics. tactical_cell may be null at Stage 1 if conviction is not yet emitted by pm-supervisor — pm-supervisor's Stage 3 completes the cell. INV-2.1-A: cell_disposition MUST be in {HOLD, BUY-HIGH, BUY-MED, AVOID}; NEVER emit canonical BUY/TRIM/SELL. PERSIST envelope to memos/envelopes/tactical-overlay__<run_id>.json before returning.")

   Agent(flow-overlay, "<PARAMETERS_USED block from §1.5 Step 6 filtered to flow namespaces>\n\nrun_id: <uuid>\n\nticker: <TICKER>\nas_of_date: <as_of_date>\ntier: <tier>\nsector: <sector>\nmode: <mode>\n\nProduce your envelope per agent definition. v0.1 scope: CTA-proximity sub-signal only (TSMOM + MA-distance + Donchian, ticker + SPY). Algorithm: (1) snap as_of_date to monthly anchor (reuse first_trading_day_of_month from src.p8_tactical_overlay.bin_classifier), (2) fetch 12mo prices for ticker + SPY via mcp__market_data__get_prices, (3) call src/p9_flow_overlay/bin_classifier.py::classify_flow() with the fetched data, (4) emit envelope per src/evaluator_gates/flow_envelope_shape.py schema. PARAMETERS_USED block wins over any prose numerics. flow_cell may be null at Stage 1 if conviction is not yet emitted by pm-supervisor — pm-supervisor's Stage 3 completes the cell. INV-FLOW-2.1-A: cell_disposition MUST be in {HOLD, BUY-HIGH, BUY-MED, AVOID}; NEVER emit canonical BUY/TRIM/SELL. Do NOT attempt gamma/GEX or crowding (SI/13F) computation — those are v0.2/v0.3 surfaces; halt and report if dispatch context contains them. PERSIST envelope to memos/envelopes/flow-overlay__<run_id>.json before returning.")
   ```

   Wait for all four returns.

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

**Dispatch prompt MUST include `run_id: <uuid>`** so the PostToolUse hook can locate the envelope at `memos/envelopes/catalyst-scout__<run_id>.json`. **AND the dispatch prompt MUST be prefixed with the PARAMETERS_USED header block composed in §1.5 Step 6, filtered to `catalyst_scout.*` namespace.** The agent's first action MUST be to honor the block per the [GROUND TRUTH] instruction (block wins over prose on any numeric threshold). Tier-1 validation (HG-31 catalyst_memo_shape, incorporating HG-24 sentiment-degradation re-count) fires automatically on return; polygon-offline halt-and-degrade writes `memos/envelopes/catalyst-scout__<run_id>.degraded` instead of an envelope and the hook treats it as a valid skip.

### 4. Dispatch `pm-supervisor` subagent

Dispatch `pm-supervisor` via Task tool. Pass as inputs:

1. **Integrated CDD memo** (from §2.5)
2. **mode classification** (from §3.6)
3. **catalyst-scout output** (from §3.7; pass `null` only if catalyst-scout halted on polygon offline)

**New responsibility (post bear-case removal 2026-05-12):** pm-supervisor MUST run an adversarial stress-test pass on the integrated CDD memo before synthesis — invert each load-bearing claim (margin assumption, moat strength, capital allocation grade, terminal value) and ask "what evidence would falsify this, and is it surfaced?" Concerns surfaced by this pass feed into the LOW-conviction trigger logic the same way bear-case findings used to.

pm-supervisor enforces the 4-tier sleeve caps (core ≤80%, thematic ≤25%, speculative ≤8%) as a **HARD GATE that runs BEFORE conviction rollup**. If a proposed ADD would breach a cap, the decision is downgraded to WATCH with a `sleeve_cap_violation` block citing the headroom remaining. Conviction rollup precedence (LOW > HIGH > MEDIUM per v3 §4.6 Phase 4 Q2), tier-aware overlays, mode-conditional sizing, and banned-outputs check all live inside the agent — see `.claude/agents/pm-supervisor.md`.

pm-supervisor emits a single JSON envelope (`decision`, `conviction`, `size_band`, `tier`, `mode`, `sleeve_cap_check`, `conviction_rationale`, `catalyst_modifier_applied`, optional `sleeve_reference`, `evidence_index_refs`). It also persists the recommendation to `execution_recommendations` and to `counterfactual_ledger` (universal write per Consensus Item #4).

**Tactical overlay surfacing (Section 2 v3-final + Section 2.1 v5-final):** pm-supervisor reads the tactical-overlay envelope at `memos/envelopes/tactical-overlay__<run_id>.json` and surfaces the tactical fields alongside its own emission in the final operator-facing report — `tactical_signal_bin`, `tactical_cell.cell_size_pct`, `tactical_cell.cell_disposition` (one of `BUY-HIGH | BUY-MED | HOLD | AVOID` per INV-2.1-A disjoint enum). Neither tactical nor pm overrides the other; both visible per Section 1 #4 soft-modulator. If pm-supervisor's emission produced a non-null `conviction` and tactical-overlay emitted `tactical_cell: null` (Stage 1 timing race), pm-supervisor completes the cell at Stage 3 via `src/p8_tactical_overlay/overlay.py::tactical_cell_size_pct + tactical_disposition`. The symmetric renderer (3 disagreement cases — downward OVERRIDE, upward DIVERGENCE, COMPARATOR) + LOW-CONVICTION VETO label are emitted in the final report per the Section 2.1 v5-final spec.

**Flow overlay surfacing (v0.1 — CTA-proximity sub-signal):** pm-supervisor also reads the flow-overlay envelope at `memos/envelopes/flow-overlay__<run_id>.json` and surfaces `flow_signal_bin`, `flow_cell.cell_size_pct`, `flow_cell.cell_disposition` (one of `BUY-HIGH | BUY-MED | HOLD | AVOID` per INV-FLOW-2.1-A disjoint enum) alongside the tactical fields. Same soft-modulator pattern as tactical: neither flow nor pm overrides the other; both visible. If pm-supervisor's emission produced a non-null `conviction` and flow-overlay emitted `flow_cell: null` (Stage 1 timing race), pm-supervisor completes the cell at Stage 3 via `src/p9_flow_overlay/overlay.py::flow_cell_size_pct + flow_disposition`. The flow_signal_bin feeds §7.6 Decision Cell Matrix TECH axis as one additional BULLISH/BEARISH vote (positive → BULLISH; negative → BEARISH; neutral/unavailable → no vote), and the §6 catalyst_modifier_applied line extends to cite the flow contribution alongside catalyst-scout's direction. v0.1 surfacing only — v0.2 will extend with `flow_modifier.erp_add_bps` injection into quantitative-analyst's WACC computation, and v0.3 will surface single-name crowding flags.

**Dispatch prompt MUST include `run_id: <uuid>`** so the PostToolUse hook can locate the envelope at `memos/envelopes/pm-supervisor__<run_id>.json`. **AND the dispatch prompt MUST be prefixed with the PARAMETERS_USED header block composed in §1.5 Step 6, filtered to `sizing.*`, `mode.*`, `dcf.thematic_growth_implied_vs_historical_cagr_cap_ratio`, and `outside_view.divergence_alert_pp` (the §2.6 stress-test routing threshold).** This is the heaviest parameter-consuming subagent — sleeve caps, conviction bands, mode multipliers, catalyst modifier bounds all live in the header block. **Pass optional --catalyst-indicators via a context sidecar** written to `memos/envelopes/pm-supervisor__<run_id>.context.json` BEFORE dispatching the Agent() call:

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
- **HG-34 (v0.2) catalyst+flow modifier composition determinism:** re-derive pm-supervisor's emitted `catalyst_modifier_applied` audit string from upstream catalyst-scout + flow-overlay envelopes via `src.p7_recommendation_emitter.catalyst_flow_modifier.compose_catalyst_flow_modifier()` and reject on bit-identical drift. Inputs to the gate: (a) `catalyst-scout__<run_id>.json` envelope (or None if catalyst-scout offline), (b) `flow-overlay__<run_id>.json` envelope (or None if flow-overlay offline), (c) parameters_active snapshot dict, (d) pm-supervisor envelope (required). The context sidecar at `memos/envelopes/pm-supervisor__<run_id>.context.json` MUST surface the params_snapshot path so the hook can pass it into `validate_all(..., params_snapshot=...)`.

**Why before §4.5:** the LLM evaluator is expensive ($3-6) and probabilistic. The hook reserves it for the semantic checks (contamination, narrative coherence, evidence sufficiency).

### 4.5. Single evaluator gate (Consensus Item #6 — locked 2026-05-12)

Dispatch `evaluator` via Task tool on the pm-supervisor output ONLY. The gate runs once, at the end, on the final synthesis.

- Mechanical contamination check on the integrated memo + catalyst-scout memo + pm-supervisor envelope
- Process-rubric scoring on pm-supervisor's decision (sleeve-cap correctness, conviction-rollup precedence, banned outputs, veto-reason completeness, **adversarial-pass completeness — replaces the former bear-case-presence check**)
- Hard-gate failures block release; soft scores feed calibration

If evaluator rejects: pm-supervisor revises (up to 3 rounds). If contamination check flags an upstream memo (quant/strategic/catalyst), the gate fails the entire run and the operator must triage which upstream agent produced the contamination.

**Terminal-status inventory (§4.5 has 3 distinct terminal-UPDATE sites — per /review-me v7 convergence 2026-05-18):** (a) contamination check fail → `failed_contamination`, (b) evaluator HG fail post-revision-exhaustion → `rejected`, (c) evaluator dispatch infra fail → `failed_evaluator_dispatch`. Any new terminal status added here MUST update this inventory + the mig 034 canonical list + the audit-checklist canonical list. Each UPDATE site mirrors the §1.5 INV / §6.5 happy-path fallback pattern (system_errors on UPDATE failure → reconcile script finalizes orphan to `failed_uncaught`).

**Site (a) — contamination check fail:** if the contamination check fails the entire run (split from `'rejected'` per /review-me v7 — was previously conflated):

```sql
UPDATE run_parameters_snapshot
SET run_ended_at = NOW(),
    run_status   = 'failed_contamination'
WHERE run_id = $RUN_ID;
```
On UPDATE failure:
```sql
INSERT INTO system_errors (source, error_type, error_detail, blocked_decision) VALUES (
  'research_company_orchestrator',
  'snapshot_update_failed',
  json_build_object('run_id', $RUN_ID, 'intended_status', 'failed_contamination', 'stage', 'contamination_terminal_update')::text,
  'research_company_' || $TICKER || '_' || to_char($RUN_STARTED_AT, 'YYYY-MM-DD"T"HH24:MI:SS')
);
```
Surface to operator; halt.

**Site (b) — evaluator HG fail post-revision-exhaustion:** if all 3 revision rounds exhaust without an evaluator PASS:

```sql
UPDATE run_parameters_snapshot
SET run_ended_at = NOW(),
    run_status   = 'rejected'
WHERE run_id = $RUN_ID;
```
On UPDATE failure:
```sql
INSERT INTO system_errors (source, error_type, error_detail, blocked_decision) VALUES (
  'research_company_orchestrator',
  'snapshot_update_failed',
  json_build_object('run_id', $RUN_ID, 'intended_status', 'rejected', 'stage', 'hg_fail_terminal_update')::text,
  'research_company_' || $TICKER || '_' || to_char($RUN_STARTED_AT, 'YYYY-MM-DD"T"HH24:MI:SS')
);
```
Surface to operator; halt.

**Site (c) — evaluator dispatch infra fail:** if the evaluator dispatch itself fails (Task tool error, sidecar write failure, subagent crash):

```sql
UPDATE run_parameters_snapshot
SET run_ended_at = NOW(),
    run_status   = 'failed_evaluator_dispatch'
WHERE run_id = $RUN_ID;
```
On UPDATE failure:
```sql
INSERT INTO system_errors (source, error_type, error_detail, blocked_decision) VALUES (
  'research_company_orchestrator',
  'snapshot_update_failed',
  json_build_object('run_id', $RUN_ID, 'intended_status', 'failed_evaluator_dispatch', 'stage', 'dispatch_fail_terminal_update')::text,
  'research_company_' || $TICKER || '_' || to_char($RUN_STARTED_AT, 'YYYY-MM-DD"T"HH24:MI:SS')
);
```
Surface to operator; halt.

This matches the symmetric pattern of §1.5 INV-1/INV-3 HARD FAIL and §6.5 happy-path. Without these inline UPDATEs, terminal-reject runs leave `run_ended_at` NULL, indistinguishable from in-flight runs at the snapshot-table level. mig 034's state-guard explicitly permits the 2-column UPDATE.

**Evaluator dispatch contract (per /review-me v7-final C13 + Q4 sidecar parity):**

1. **Inject `run_id: <RUN_ID>` into the evaluator prompt body** — same pattern as pm-supervisor dispatch above. The evaluator's HG-25 reads this line and performs a DB roundtrip `SELECT 1 FROM run_parameters_snapshot WHERE run_id = :run_id`; absent or unresolved → REJECT or soft-warn per HG-25 rules.
2. **Prefix the prompt with the PARAMETERS_USED header block** composed in §1.5 Step 6, filtered to evaluator namespace consumption (`evaluator.gate.*`, `quality_gate.*`, `falsifier.max_resolution_horizon_months`, `dcf.reconciliation_divergence_pct_floor`). Evaluator's HG-* mechanical gates that previously read hardcoded literals now read from this block (block wins over prose).
3. **Write a context sidecar BEFORE dispatch** at `memos/envelopes/evaluator__<RUN_ID>.context.json`:
   ```json
   {
     "run_id": "<RUN_ID>",
     "run_parameters_snapshot_id": "<RUN_ID>",
     "parameters_version_max": "<PARAMETERS_VERSION_MAX from §1.5 Step 4>",
     "effective_parameters_hash": "<EFFECTIVE_HASH from §1.5 Step 4>"
   }
   ```
   The sidecar serves as defense-in-depth (if the prompt-grep regression-breaks, the evaluator can fall back to the sidecar for snapshot lookup) AND as the carrier of context for HG-25's DB roundtrip verification.

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

### 6.5. Close the run_parameters_snapshot row (HAPPY-PATH RUN COMPLETION)

After §4.5 evaluator passes AND §6 persistence completes, close out the snapshot row that was INSERTed in §1.5 Step 4:

```sql
UPDATE run_parameters_snapshot
SET run_ended_at = NOW(),
    run_status   = 'completed'
WHERE run_id = $RUN_ID;
```

This makes downstream queries like "which research runs are still in-flight vs. completed?" answerable via the snapshot table. mig 034's state-guard explicitly permits this 2-column UPDATE (every other column is immutable post-INSERT — see mig 034 `run_parameters_snapshot_guard`).

**Failure-path symmetry:** the §1.5 invariant validator (INV-1 / INV-3 HARD FAIL paths) writes `run_ended_at + run_status = 'failed_INV-1' | 'failed_INV-3'` at termination; §4.5 evaluator REJECT path (above) writes `run_status = 'rejected'` analogously; this §6.5 happy-path UPDATE writes `run_status = 'completed'`. All three terminal paths now close the snapshot row, making in-flight vs. terminated distinguishable at the table level. Per /review-me post-apply iterations 1+2 defects #13 + #15.

If this UPDATE itself fails (DB unreachable), the run still emits §7 output to operator. Log the failure to `system_errors` for visibility (symmetric to §1.5 INV / §4.5 sites):

```sql
INSERT INTO system_errors (source, error_type, error_detail, blocked_decision) VALUES (
  'research_company_orchestrator',
  'snapshot_update_failed',
  json_build_object('run_id', $RUN_ID, 'intended_status', 'completed', 'stage', 'happy_path_terminal_update')::text,
  'research_company_' || $TICKER || '_' || to_char($RUN_STARTED_AT, 'YYYY-MM-DD"T"HH24:MI:SS')
);
```

The orphan `run_ended_at IS NULL` row is finalized post-hoc by `scripts/reconcile_orphan_snapshots.sh` to `'failed_uncaught'`.

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
