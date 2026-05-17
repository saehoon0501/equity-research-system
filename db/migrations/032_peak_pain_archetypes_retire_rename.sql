-- =============================================================================
-- Migration: 032_peak_pain_archetypes_retire_rename
-- Purpose:   Rename `peak_pain_archetypes` to `peak_pain_archetypes_retired_20260517`
--            as the final phase (Phase 4) of the peak_pain_archetypes /
--            counterfactual_veto framework removal documented in BUILD_LOG.md
--            and `src/peak_pain_catalog/DEPRECATED.md` (2026-05-17).
--
-- Rationale: Named-historical-analog matching anchored bear-DCFs at NON-SURVIVOR
--            drawdown magnitudes regardless of Q1-falsifier clearance, producing
--            structural HOLD bias on names that had already cleared the cited
--            bear arcs (e.g., GOOGL Q1 FY26). Adversarial pressure for analog-
--            driven displacement-thesis testing is now handled by
--            pm-supervisor.md §2.6 stress-test using mechanism + falsifying-
--            observable framing rather than named historical analogs.
--
-- Pre-flight verification (executed 2026-05-17 in worktree
-- .claude/worktrees/peak-pain-exec on branch remove-peak-pain-archetypes):
--   grep "FROM peak_pain_archetypes" src/ --include="*.py" \
--     | grep -v "src/peak_pain_catalog/\|src/counterfactual_veto/"
--   → empty (no live SQL queries against the table outside deprecated subtrees)
--
-- Authorization: HMAC override granted by operator inline 2026-05-17 in lieu of
--            /spec-approve sign-off. Decision is recorded in this migration's
--            apply-time DB row.
--
-- Apply:
--   psql -h 127.0.0.1 -p 5432 -U postgres -d equity_research \
--     -f db/migrations/032_peak_pain_archetypes_retire_rename.sql
--
-- Dependencies:
--   - Migration 003 (counterfactual_ledger base table) and migration 011 (v3
--     counterfactual retrieval schema) must be applied first.
--   - PostgreSQL RENAME preserves columns + constraints + indexes + triggers
--     + foreign-key references, so this is a metadata-only operation.
--
-- Rollback procedure:
--   ALTER TABLE peak_pain_archetypes_retired_20260517 RENAME TO peak_pain_archetypes;
--   (executable as a one-liner; metadata-only; no row movement.)
--
-- Idempotency: NOT idempotent. Re-running this migration after success will
--   error with "relation peak_pain_archetypes does not exist". This is
--   acceptable for a one-shot rename; verify success via the post-condition
--   query at the bottom of this file.
--
-- Related dead table NOT renamed by this migration:
--   `counterfactual_retrievals` (13 cols) — §3.5 retrieval-history log; no
--   live writers post-Phase-3 (commit 0272451). Renaming this table requires
--   separate operator authorization since it was not in scope of the original
--   DEPRECATED.md plan. See `src/counterfactual_veto/DEPRECATED.md`.
-- =============================================================================

BEGIN;

-- Confirm pre-condition: table exists under original name.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'peak_pain_archetypes'
    ) THEN
        RAISE EXCEPTION
          'Pre-condition failed: peak_pain_archetypes does not exist. '
          'Migration 032 cannot proceed.';
    END IF;
END $$;

-- Rename the table.
ALTER TABLE peak_pain_archetypes
    RENAME TO peak_pain_archetypes_retired_20260517;

-- Confirm post-condition: rename succeeded.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name = 'peak_pain_archetypes_retired_20260517'
    ) THEN
        RAISE EXCEPTION 'Post-condition failed: rename did not take effect.';
    END IF;
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'peak_pain_archetypes'
    ) THEN
        RAISE EXCEPTION 'Post-condition failed: original name still exists.';
    END IF;
END $$;

COMMIT;
