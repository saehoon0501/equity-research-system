"""S0 regime sidecar — daily 6-dimension regime classification with BOCPD.

Per v3 spec Section 4.1 (L1 / S0 — Regime sidecar) and Section 3.3 (data-source
mapping). This package is critical-path component #1 in v0.1 implementation
(Section 7.4 critical path, item 2 after Postgres schema).

The 6 Tier-1 dimensions (per Section 3 Q1 lock):

    1. credit_ebp        — Excess Bond Premium (Gilchrist-Zakrajšek 2012)
    2. cycle_2y3m_slope  — DGS2-DGS3MO CMT slope (Engstrom-Sharpe NTFS deferred to v0.5+)
    3. vol_vrp           — Variance Risk Premium (Bollerslev-Tauchen-Zhou 2009)
    4. mp_liquidity      — Monetary-policy / liquidity composite
    5. dollar_dtwexbgs   — Trade-Weighted Broad Dollar
    6. stock_bond_corr   — Stock-bond correlation, Forbes-Rigobon corrected

4 method overlays (per Section 4.1):

    1. BOCPD                                — Adams-MacKay 2007. Dual-signal
                                                architecture (operator-locked):
                                                * canonical marginal
                                                  P(r_t=0|x_{1:t}) — academic
                                                  / audit traceability
                                                * cumulative short-run mass
                                                  P(r_t<10|x_{1:t}) — primary
                                                  firing signal (drives
                                                  M-2/M-3 per §4.1 thresholds).
                                                Both first-class.
    2. Forbes-Rigobon vol-conditional       — applied to dim 6 only
    3. Surprises (actual − consensus)        — flagged deferred_to_v0.5 in
                                                dims 1, 2, 4 raw_inputs
    4. MSGARCH (R)                           — deferred to v0.5+

Weighting at v0.1: pure equal-weight (1/6 per dimension). pseudo-BMA+ is
deferred to v0.5+ (Section 4.1 upgrade path).

Public surface (orchestrated by `classifier.run_daily_classification`):

    {dimension_id: {
        state_probabilities: {...},
        headline_state: str,
        bocpd_change_probability: float,   # canonical marginal (audit)
        bocpd_short_run_mass: float,       # firing signal
        raw_inputs: {...},
        history_length_days: int,
    }}

Persistence: `persistence.write_classifications` writes to
`regime_classification_history` per migration 005_v3_regime.sql.

CLI: `python -m src.regime_sidecar.cli --date YYYY-MM-DD [--cold-start]`.
"""

from __future__ import annotations

from . import bocpd, classifier, forbes_rigobon, persistence

__all__ = [
    "classifier",
    "persistence",
    "bocpd",
    "forbes_rigobon",
]
