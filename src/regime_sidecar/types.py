"""Shared types / dataclasses for the regime sidecar.

Per v3 spec §4.1. The `DimensionResult` shape is the contract between
dimension fetchers (`dimensions/*.py`) and the orchestrator (`classifier.py`)
+ the persistence layer (`persistence.py` -> `regime_classification_history`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


# Canonical dimension registry (v3 spec §4.1, migration 005_v3_regime.sql).
DIMENSION_REGISTRY: dict[int, str] = {
    1: "credit_ebp",
    # Dim 2: v0.1 ships (DGS2 - DGS3MO) CMT slope as the cycle indicator.
    # The Engstrom-Sharpe NTFS (zero-coupon-derived 6q-ahead 3mo forward
    # minus current 3mo spot) is the published edge form. Wiring the GSW
    # THREEFY1/THREEFY2 series (or neartermforwardspread.com CSV) is
    # deferred to v0.5+. Renamed from `cycle_ntfs` so we don't claim
    # Engstrom-Sharpe edge under a CMT proxy.
    2: "cycle_2y3m_slope",
    3: "vol_vrp",
    4: "mp_liquidity",
    5: "dollar_dtwexbgs",
    6: "stock_bond_corr",
}


@dataclass
class DimensionResult:
    """Per-dimension daily classification output.

    Maps 1:1 to a `regime_classification_history` row (one column = one
    field, except `parameters_version` / `rule_engine_version` / `cold_start`
    which the persistence layer attaches).

    Per v3 §4.1: each dimension produces a probability distribution per
    state, NOT a point classification. `headline_state = argmax(state_probabilities)`.
    """

    dimension_id: int
    dimension_name: str
    classification_date: date

    # state_name -> probability; sums to 1.0 (within float tolerance)
    state_probabilities: dict[str, float]

    # argmax over state_probabilities (denormalized for query speed)
    headline_state: str

    # BOCPD signal pair per operator-locked dual-signal architecture
    # (v3 §4.1 / §3 Q3). Both first-class fields:
    #
    # - bocpd_change_probability: canonical Adams-MacKay marginal
    #   P(r_t = 0 | x_{1:t}). Retained for academic rigor + audit
    #   traceability. Structurally pinned near hazard rate in steady
    #   state — does NOT systematically cross v3 §4.1 firing thresholds.
    # - bocpd_short_run_mass: cumulative posterior P(r_t < 10 | x_{1:t}).
    #   PRIMARY firing signal — drives M-2/M-3 firing per v3 §4.1
    #   thresholds (>0.7 sustained 2+d → M-2; >0.95 single-day → M-3).
    bocpd_change_probability: float
    bocpd_short_run_mass: float

    # The raw inputs the classification was computed from (replay / audit).
    raw_inputs: dict[str, Any]

    # Length of history used for the BOCPD computation. Drives cold-start
    # diagnostic ("did we have enough data?"); see §7.5.
    history_length_days: int

    # Validation-depth tag (v3 §4.1: annotation only at v0.1; not a numerical
    # multiplier). Provenance: which paper / dataset underpins this dim.
    validation_depth: str = ""

    # Optional warnings (e.g., stale data, fallback path used).
    warnings: list[str] = field(default_factory=list)
