-- =============================================================================
-- Migration: 037_externalize_wacc_erp
-- Purpose:   Externalize wacc.erp (central Damodaran implied ERP %) as a
--            sweep-able parameter row. Replaces the non-existent
--            .claude/references/damodaran_implied_erp_cache.json that
--            quantitative-analyst.md §3.9 documents but never created on disk.
--
--            Reference: /review-me INV-2 adjudication 2026-05-19 (Phase A.2)
--            + Phase 0d empirical finding: cache file documented but absent.
--            Unblocks A7 axis (central ERP) for any GOOGL-style perturbation
--            plan that wants to sweep WACC discount-rate sensitivity.
--
-- Schema choice:
--   - Single new row, tag=NULL (production governance).
--   - Value 4.60 reflects Damodaran's recent monthly implied-ERP range
--     (matches the value the LLM improvised during GOOGL canary e76a0750
--     since no on-disk cache was readable, and Damodaran's published series
--     has been in the 4.5-5.0% range through 2024-2025).
--   - Future cache refreshes (when DGS10 drift > erp_refresh_drift_bps)
--     should INSERT a new row with supersedes_version chain — same pattern
--     as the INV-2 adjudication override applied 2026-05-19 01:52 UTC.
--     Append-only trigger (parameters_guard()) blocks UPDATEs.
--
-- Dependencies:
--   - 033_parameters_seed_research_company (base seed + tag column).
--
-- How to apply:
--   psql -h 127.0.0.1 -p 5432 -U postgres -d equity_research \
--        -f db/migrations/037_externalize_wacc_erp.sql
--
-- Idempotency: NOT EXISTS guard on (parameter_key, tag IS NULL).
--
-- Consumer-side follow-up (NOT applied in this migration — needs its own
-- /review-me cycle before edits to load-bearing skill markdown):
--   - quantitative-analyst.md §3.9 should read ERP from parameters_active
--     instead of (non-existent) cache file. The DGS10-drift refresh logic
--     should move to an out-of-band refresh job or operator-manual INSERT.
--   - .claude/commands/research-company.md §1.5 Step 6 PARAMETERS_USED
--     header composer should add 'wacc.erp' to quantitative-analyst's
--     consumed namespace list.
-- =============================================================================

BEGIN;

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'wacc.erp', 'wacc', '4.60'::jsonb,
       'Damodaran implied equity risk premium percent (central value for WACC cost-of-equity computation: r_e = r_f + beta * ERP). Sweep-able anchor for A7-style axes in /research-company perturbation plans.',
       'Phase A.2 externalization per /review-me 2026-05-19 adjudication. Replaces non-existent .claude/references/damodaran_implied_erp_cache.json (documented at quantitative-analyst.md sec 3.9 but absent on disk; LLM improvised value during GOOGL canary e76a0750-6828-4698-86cc-0b7f9c196d4e). Seed value 4.60 matches Damodaran monthly implied-ERP series 2024-2025 range and the value the subagent improvised. Source: https://pages.stern.nyu.edu/~adamodar/ (monthly implied-ERP table; refresh via WebFetch plus new INSERT with supersedes_version when DGS10 drift exceeds wacc.erp_refresh_drift_bps per quantitative-analyst.md sec 3.9).',
       'phase_a_2_externalization_2026-05-19', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'wacc.erp' AND tag IS NULL);

COMMIT;
