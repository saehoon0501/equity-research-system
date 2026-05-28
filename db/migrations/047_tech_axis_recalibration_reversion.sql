-- 047_tech_axis_recalibration_reversion.sql
-- -----------------------------------------------------------------------------
-- Recalibrate sizing.tech_axis_bullish_score_min: 4 -> 5
--
-- WHY: The insight-quality enhancement (P0-1) wired mean-reversion-overlay into
-- pm-supervisor as a 7th *symmetric* TECH-axis signal (contrarian polarity). The
-- prior cutoff 4 (mig 040) was set for a 6-symmetric-signal world: BULLISH fired
-- at >=4/6 (~67% of the +6 ceiling). With a 7th symmetric signal the ceiling is
-- +7, so the OLD cutoff 4 silently relaxes the bar to 4/7 (~57%) -> more spurious
-- BULLISH verdicts in the uncalibrated interim.
--
-- Bumping to 5 restores a conservative bar (5/7 ~= 71%, slightly TIGHTER than the
-- original 67% -> errs toward fewer false BUYs, the safe direction). This is the
-- INTERIM value; mig 040's own rationale already anticipated it: "Real
-- CTA-proximity + gamma signals are correlated under stress so actual calibration
-- may need >=+5." The empirically-calibrated value will be set later by the WS-4
-- eval->update loop (resolver -> Brier/log-loss -> parameters recalibration at
-- N>=50/cell), which supersedes this interim default.
--
-- MECHANISM: parameters_active = DISTINCT ON (parameter_key) ... WHERE tag IS NULL
-- ORDER BY effective_at DESC. A new tag-NULL row with effective_at=NOW() (> the
-- 040 row) becomes the active value. Append-only; the 040 row is retained as
-- history. Idempotent: guarded on the new value (5) so re-runs do not duplicate.
-- -----------------------------------------------------------------------------

BEGIN;

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'sizing.tech_axis_bullish_score_min', 'sizing', '5'::jsonb,
       'TECH axis BULLISH cutoff: tech_axis_score >= this value triggers BULLISH. Recalibrated 4->5 for the 7-symmetric-signal world after mean-reversion-overlay was added as a contrarian TECH input (insight-quality P0-1). 5/7 (~71%) restores a conservative bar vs the relaxed 4/7 (~57%). INTERIM value pending WS-4 eval->update calibration.',
       'Insight-quality enhancement P0-1 tail: 7th TECH signal (reversion) raised the ceiling +6->+7; cutoff bumped 4->5 to preserve a conservative BULLISH bar. Supersedes mig 040 launch default (4). Will be re-tuned empirically by the WS-4 calibration loop.',
       'insight_quality_p0_2026-05-27', NULL
WHERE NOT EXISTS (
    SELECT 1 FROM parameters
    WHERE parameter_key = 'sizing.tech_axis_bullish_score_min'
      AND value = '5'::jsonb
      AND tag IS NULL
);

COMMIT;

-- Verify the active value flipped to 5:
--   SELECT value FROM parameters_active WHERE parameter_key = 'sizing.tech_axis_bullish_score_min';
--   Expected: 5
-- Confirm history retained (>=2 tag-NULL rows: the 040 '4' and this '5'):
--   SELECT value, effective_at FROM parameters
--   WHERE parameter_key = 'sizing.tech_axis_bullish_score_min' AND tag IS NULL
--   ORDER BY effective_at;
