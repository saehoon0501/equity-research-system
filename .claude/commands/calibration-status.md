# /calibration-status

Surfaces v0.5 calibration-corpus health: N resolved at each horizon,
current Brier per cell, current per-style believability, distance-to-v0.5
activation, and shadow-mode hooks. Read-only.

## Argument

None.

## Procedure

1. Pre-flight: `mcp__postgres` connected.
2. Shell out:
   ```bash
   python -m src.calibration.cli status
   ```
3. The CLI prints (in order):

   ```
   PHASE: v0.1-active   (resolved=N; days_since_launch=K)
   FEATURES (live=●  shadow=○):
     ○ brier_haircut
     ○ believability_weighting
     ○ bb_regime_weights
     ○ composable_sizing
     ○ continuous_conviction

   RESOLVED OUTCOMES:
     T+30d : <n>
     T+90d : <n>     (v0.5 trigger ≥ 50)
     T+1y  : <n>

   BRIER (90d, global):
     N      : <n>
     Brier  : <x.xxx>     (random baseline 0.250)
     mean_p : <x.xxx>
     mean_y : <x.xxx>

   BRIER (90d, by mode):
     B       : N=<n>  Brier=<x.xxx>
     B_prime : N=<n>  Brier=<x.xxx>
     C       : N=<n>  Brier=<x.xxx>

   BELIEVABILITY (per-style, 90d, BUY-only):
     value           : N=<n>  Brier=<x.xxx>  weight=<x.xxx>
     growth          : N=<n>  Brier=<x.xxx>  weight=<x.xxx>
     ...

   OPERATOR vs SYSTEM (per cell, 90d):
     <mode> / <materiality> / <rec>:  N_sys=<n>  N_ovr=<n>
                                       sys_brier=<x.xxx>  op_brier=<x.xxx>
                                       operator_better=<bool>
   ```

## Activation guidance

- **Brier > 0.25**: calibration is degrading. v0.5 haircut would demote
  conviction by `(Brier - 0.25) / 0.05` band-steps.
- **operator_better=TRUE in any cell**: per spec §6.0 the v0.5 calibration
  sign convention inverts in that cell — formula will train *against* the
  operator's bias, not toward.

## Failure modes

- **Postgres unreachable** — exits 5.
- **Empty corpus (no resolved outcomes)** — prints zeros and a hint that
  `/resolve-outcomes` should run first.

## Reference

- v3 spec §6.0 (calibration-circularity defense), §6.4 (upgrade paths)
- Modules: `src/calibration/brier.py`, `src/calibration/believability.py`,
  `src/orchestrator/v05_activation.py`
- Migration: `db/migrations/025_v3_system_vs_operator_brier_view.sql`
- Companion: `/resolve-outcomes`, `/parameters-review`
