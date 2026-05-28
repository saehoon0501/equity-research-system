"""Credit-stress / balance-sheet block (WS-7.3, Phase 3 OPTIONAL).

Backs the ``credit_stress`` block on the quantitative-analyst envelope:
interest coverage, debt maturity wall vs the current rate curve, and cash
runway. Pure compute layer with fully injectable EDGAR/FRED seams; the live
fetch is the integration boundary owned by the agent layer.

Per ``docs/superpowers/plans/2026-05-27-insight-quality-enhancement-parallel-plan.md``.
"""

from src.credit_stress.contracts import (
    DebtMaturity,
    Financials,
    RateCurve,
)
from src.credit_stress.credit_stress import (
    compute_cash_runway,
    compute_credit_stress,
    compute_interest_coverage,
    compute_maturity_wall,
)

__all__ = [
    "DebtMaturity",
    "Financials",
    "RateCurve",
    "compute_credit_stress",
    "compute_interest_coverage",
    "compute_maturity_wall",
    "compute_cash_runway",
]
