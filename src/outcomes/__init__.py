"""Outcome resolution pipeline (v0.5 calibration substrate).

For each row in `execution_recommendations`, computes T+30 / T+90 / T+1y
returns vs benchmark and UPSERTs into `recommendation_outcomes`. The
resolver runs nightly (or on-demand via `python -m src.outcomes.cli`).

Why v0.5 hinges on this module:
    * `phase_detector._query_resolved_predictions` counts rows where
      `t_plus_90d_return IS NOT NULL`. Without the resolver, that count
      stays at 0 forever and v0.5 never auto-activates.
    * Brier-haircut, believability-weighted debate, BB-pseudo-BMA+
      regime weights, override-outcome circularity defense — every
      v0.5 deliverable consumes resolved outcomes.

Public surface:
    resolve_outcomes(conn, *, as_of, providers, dry_run) → ResolutionStats
    ResolutionStats — counts of windows resolved per horizon
"""

from src.outcomes.resolver import (
    ResolutionStats,
    Resolver,
    resolve_outcomes,
)

__all__ = [
    "ResolutionStats",
    "Resolver",
    "resolve_outcomes",
]
