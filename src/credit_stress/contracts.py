"""Cross-module handoff contracts for the credit-stress block (WS-7.3).

Per the plan at
``docs/superpowers/plans/2026-05-27-insight-quality-enhancement-parallel-plan.md``
Phase 3 (OPTIONAL coverage gaps): WS-7.3 adds a ``credit_stress`` block to the
quantitative-analyst envelope covering interest coverage, the debt maturity
wall vs the current rate curve, and cash runway.

Structural mirror of ``src/p10_reversion_overlay/contracts.py`` — same
``Literal`` vocabulary discipline, same frozen-dataclass injectable seams.

The Python package here is the PURE COMPUTE layer. The live EDGAR (financials)
+ FRED (rate curve) fetch is the integration boundary owned by the
quantitative-analyst AGENT (``.claude/agents/quantitative-analyst.md``); this
module never makes network calls. All inputs are injectable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

# ---------------------------------------------------------------------------
# Vocabulary (Literal for static checking; .__args__ exposes values at runtime)
# ---------------------------------------------------------------------------

# Overall qualitative credit-stress flag.
CreditStressFlag = Literal["low", "elevated", "high", "unavailable"]

# Per-sub-metric status.
#   ok             — computed from sufficient inputs
#   unavailable    — a required input was missing/None; degrade gracefully
#   not_applicable — sub-metric is meaningless for this name (e.g. cash runway
#                    for a cash-GENERATIVE company with non-positive burn)
SubMetricStatus = Literal["ok", "unavailable", "not_applicable"]

# Qualitative risk level for the maturity-wall sub-metric.
MaturityWallRisk = Literal["low", "elevated", "high", "unavailable", "not_applicable"]


# ---------------------------------------------------------------------------
# Injectable input seams
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DebtMaturity:
    """One upcoming debt tranche (maturity bucket).

    ``years_to_maturity``  : float years from the as-of date to maturity.
    ``amount``             : principal coming due (same currency units as cash).
    ``coupon_rate_pct``    : the EXISTING coupon on this tranche, in percent
                             (e.g. 4.25 for 4.25%). Used to compute the refi
                             rate gap vs the current curve. May be None if the
                             coupon is unknown (treated as 0 gap contribution).
    """

    years_to_maturity: float
    amount: float
    coupon_rate_pct: Optional[float] = None


@dataclass(frozen=True)
class Financials:
    """Company financials seam (sourced LIVE from EDGAR by the agent layer).

    Every field is Optional so the compute layer can degrade gracefully when a
    line item is missing — a sub-metric depending on a None input is marked
    ``"unavailable"`` rather than raising.

    Units: ``ebit``, ``interest_expense``, ``cash``, ``quarterly_burn`` and
    every ``DebtMaturity.amount`` must share a common currency unit (the agent
    normalizes EDGAR facts before injection). Burn convention: ``quarterly_burn``
    is POSITIVE cash consumed per quarter; non-positive => cash generative.
    """

    ebit: Optional[float] = None
    interest_expense: Optional[float] = None
    cash: Optional[float] = None
    # Positive => cash consumed per quarter. <= 0 => cash generative.
    quarterly_burn: Optional[float] = None
    # Upcoming debt maturities (any order); empty list => no scheduled debt.
    debt_maturities: tuple[DebtMaturity, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class RateCurve:
    """Current rate curve seam (sourced LIVE from FRED by the agent layer).

    Tenor -> par/yield rate in PERCENT (e.g. {1.0: 5.30, 5.0: 4.10}). The
    refinancing rate for a maturing tranche is read at the nearest available
    tenor to that tranche's ``years_to_maturity`` (linear pick of closest
    point; no interpolation — keeps the compute deterministic and simple).
    """

    # tenor_years -> rate_pct
    points: dict[float, float] = field(default_factory=dict)

    def rate_at(self, years: float) -> Optional[float]:
        """Return the curve rate (pct) at the tenor nearest ``years``.

        Returns None when the curve carries no points (graceful degradation).
        """
        if not self.points:
            return None
        nearest = min(self.points.keys(), key=lambda t: abs(t - years))
        return self.points[nearest]


__all__ = [
    "CreditStressFlag",
    "SubMetricStatus",
    "MaturityWallRisk",
    "DebtMaturity",
    "Financials",
    "RateCurve",
]
