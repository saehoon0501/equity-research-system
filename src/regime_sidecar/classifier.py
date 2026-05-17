"""S0 daily classification orchestrator.

Per v3 spec §4.1. Calls each of the 6 dimension fetchers in turn, collects
their `DimensionResult`s, and returns a dict keyed by dimension_id. The
caller (CLI / persistence layer) is responsible for writing the results to
`regime_classification_history`.

Equal-weight headline at v0.1: this module does NOT compute a single
combined regime score. Per v3 §4.1, headline weighting is "pure 1/6
equal-weight"; each dimension is persisted independently and downstream
consumers (P4 Macro-Regime agent, P8 daily monitor) read the latest row
per dimension from the `regime_state` view.

BB-pseudo-BMA+ shadow weights (v0.5+) are NOT computed here.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import date

from src.regime_sidecar.dimensions import (
    dim1_credit_ebp,
    dim2_cycle_ntfs,
    dim3_vol_vrp,
    dim4_mp_liquidity,
    dim5_dollar,
    dim6_stock_bond_corr,
)
from src.regime_sidecar.types import DimensionResult


logger = logging.getLogger(__name__)


# Order matters: dimension_id is dictated by the spec / migration 005.
DIMENSION_FETCHERS = [
    (1, dim1_credit_ebp.compute),
    (2, dim2_cycle_ntfs.compute),
    (3, dim3_vol_vrp.compute),
    (4, dim4_mp_liquidity.compute),
    (5, dim5_dollar.compute),
    (6, dim6_stock_bond_corr.compute),
]


def run_daily_classification(
    asof_date: date,
    history_days: int = 365,
) -> dict[int, DimensionResult]:
    """Run all 6 dimension fetchers for `asof_date`.

    Args:
        asof_date: classification date.
        history_days: history window in calendar days for BOCPD seeding.
            Cold-start defaults to 365 (T-12mo per §7.5).

    Returns:
        Dict mapping dimension_id (1..6) → DimensionResult.

    Per v3 §7.5 error handling: a single dimension failure is captured as
    a warning on a synthetic neutral DimensionResult; the orchestrator
    does NOT raise. Hard stops are decided by the caller (CLI / cron) based
    on the total number of failures.
    """
    results: dict[int, DimensionResult] = {}
    for dim_id, fetch in DIMENSION_FETCHERS:
        try:
            res = fetch(asof_date, history_days=history_days)
            results[dim_id] = res
        except Exception as exc:  # noqa: BLE001 — capture any provider error
            logger.exception("dimension %d failed: %s", dim_id, exc)
            # Synthesize a degraded neutral result so the persistence layer
            # always writes 6 rows — downstream queries assume one row per
            # (date, dim_id). We tag the warning so degraded-mode flag can
            # propagate in execution_context.risk_flags per §7.5 item 4.
            results[dim_id] = _degraded_result(dim_id, asof_date, str(exc))
    return results


def _degraded_result(dim_id: int, asof_date: date, reason: str) -> DimensionResult:
    """Synthesize a neutral DimensionResult when a fetcher raises."""
    name_map = {
        1: ("credit_ebp", "benign"),
        2: ("cycle_2y3m_slope", "late_cycle"),
        3: ("vol_vrp", "normal"),
        4: ("mp_liquidity", "neutral"),
        5: ("dollar_dtwexbgs", "neutral"),
        6: ("stock_bond_corr", "neutral"),
    }
    name, fallback_state = name_map[dim_id]
    return DimensionResult(
        dimension_id=dim_id,
        dimension_name=name,
        classification_date=asof_date,
        state_probabilities={fallback_state: 1.0},
        headline_state=fallback_state,
        bocpd_change_probability=0.0,
        bocpd_short_run_mass=0.0,
        raw_inputs={"degraded": True, "reason": reason},
        history_length_days=0,
        validation_depth="DEGRADED",
        warnings=[f"fetcher_failed:{reason}"],
    )


def to_serializable(results: dict[int, DimensionResult]) -> dict[int, dict]:
    """Convert results to plain dicts (e.g., for JSON dump / logging)."""
    out: dict[int, dict] = {}
    for k, v in results.items():
        d = asdict(v)
        d["classification_date"] = v.classification_date.isoformat()
        out[k] = d
    return out
