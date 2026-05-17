"""P7 sizing — Section 4.6 PB#2 v0.1 mode-static + 3 hard overlays.

Per v3 spec Section 4.6 lines 607-619 (Sizing v0.1)::

    | Mode | Initial | Max |
    |---|---|---|
    | B  | 3% | 8% |
    | B' | 2% | 5% |
    | C  | 1% | 3% |

    Hard overlays:
      1. Cash constraint: suggested_initial = min(mode_band, available_cash_pct);
         if cash < suggested_initial → surface companion TRIM candidates.
         funding_required = (cash binds).
      2. Drawdown auto-tighten: if portfolio drawdown vs benchmark > threshold
         (B/S&P 5pp, B'/QQQ 7pp, C/IWO 10pp), sizing × 0.5 until drawdown clears.
      3. S0 vol-elevated: if S0 vol dimension > +1σ, sizing × 0.7.

v0.5+ deferred: composable formula (weighted multipliers — conviction,
regime, drawdown, cash; calibrated empirically).

Returns ``SizingSuggestion`` matching the JSONB schema embedded in
``execution_recommendations.sizing_suggestion`` (Section 4.6 Q1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional


# Mode → base sizing band (initial%, max%) per Section 4.6 PB#2.
_MODE_BANDS: dict[str, tuple[float, float]] = {
    "B": (3.0, 8.0),
    "B_prime": (2.0, 5.0),
    "C": (1.0, 3.0),
}

# Drawdown auto-tighten thresholds in percentage points (relative-to-benchmark).
_DRAWDOWN_THRESHOLDS_PP: dict[str, float] = {
    "B": 5.0,
    "B_prime": 7.0,
    "C": 10.0,
}


@dataclass
class AppliedOverlay:
    """One overlay's applied multiplier + reason string."""

    name: str  # 'cash_constraint' | 'drawdown_tighten' | 'vol_regime'
    multiplier: float
    reason: str

    def to_payload(self) -> dict:
        return {
            "name": self.name,
            "multiplier": self.multiplier,
            "reason": self.reason,
        }


@dataclass
class SizingSuggestion:
    """Full sizing-suggestion envelope per Section 4.6 Q1."""

    initial_pct: float  # post-overlay (rounded to 0.1pp)
    max_pct: float  # post-overlay
    base_band: dict[str, float]  # {initial, max}
    applied_overlays: list[AppliedOverlay] = field(default_factory=list)
    net_multiplier: float = 1.0
    funding_required: bool = False  # True when cash constraint binds

    def to_payload(self) -> dict:
        return {
            "initial_pct": round(self.initial_pct, 2),
            "max_pct": round(self.max_pct, 2),
            "base_band": dict(self.base_band),
            "applied_overlays": [o.to_payload() for o in self.applied_overlays],
            "net_multiplier": round(self.net_multiplier, 4),
            "funding_required": self.funding_required,
        }


@dataclass
class SizingContext:
    """Inputs the sizing computation needs.

    available_cash_pct: cash as % of portfolio (0-100).
    portfolio_underperformance_pp_vs_bench: positive = underperforming
        benchmark by N percentage points in rolling Q. None = no draw-tighten.
    s0_vol_z: S0 vol-dimension z-score. >1.0 → overlay 3 fires.
    """

    mode: str
    available_cash_pct: Optional[float] = None
    portfolio_underperformance_pp_vs_bench: Optional[float] = None
    s0_vol_z: Optional[float] = None


# ---------------------------------------------------------------------------
# Overlay computation
# ---------------------------------------------------------------------------


def _band_for_mode(mode: str) -> tuple[float, float]:
    if mode not in _MODE_BANDS:
        raise ValueError(
            f"mode {mode!r} not in {tuple(_MODE_BANDS.keys())} — see Section 2.2"
        )
    return _MODE_BANDS[mode]


def _cash_overlay(
    initial_target_pct: float, available_cash_pct: Optional[float]
) -> tuple[AppliedOverlay, float, bool]:
    """Hard overlay 1 — cash constraint.

    Per Section 4.6:
        suggested_initial = min(mode_band, available_cash_pct);
        if cash binds → funding_required = true.

    Returns (overlay, multiplier_applied_to_initial_only, funding_required).

    Multiplier is applied to ``initial_pct`` only. ``max_pct`` is unaffected
    by cash (max is the ceiling reachable post-funding).
    """
    if available_cash_pct is None:
        return (
            AppliedOverlay(
                name="cash_constraint",
                multiplier=1.0,
                reason="available_cash_pct not provided — no cash overlay applied",
            ),
            1.0,
            False,
        )
    if available_cash_pct >= initial_target_pct:
        return (
            AppliedOverlay(
                name="cash_constraint",
                multiplier=1.0,
                reason=(
                    f"cash {available_cash_pct:.2f}% >= target initial "
                    f"{initial_target_pct:.2f}% — no constraint"
                ),
            ),
            1.0,
            False,
        )
    # Cash binds. Multiplier scales initial down to available cash.
    if initial_target_pct == 0:  # defensive
        return (
            AppliedOverlay(
                name="cash_constraint",
                multiplier=1.0,
                reason="initial_target_pct=0 — degenerate; pass-through",
            ),
            1.0,
            False,
        )
    mult = available_cash_pct / initial_target_pct
    return (
        AppliedOverlay(
            name="cash_constraint",
            multiplier=mult,
            reason=(
                f"cash {available_cash_pct:.2f}% < target initial "
                f"{initial_target_pct:.2f}% → funding_required=true; "
                "surface companion TRIM candidates per Section 4.6 PB#2 overlay 1"
            ),
        ),
        mult,
        True,
    )


def _drawdown_overlay(
    mode: str, underperformance_pp: Optional[float]
) -> AppliedOverlay:
    """Hard overlay 2 — drawdown auto-tighten.

    Per Section 4.6:
        if portfolio drawdown vs benchmark > threshold (B/S&P 5pp,
        B'/QQQ 7pp, C/IWO 10pp), sizing × 0.5 until drawdown clears.

    underperformance_pp: positive = underperforming benchmark by N pp.
    """
    threshold = _DRAWDOWN_THRESHOLDS_PP[mode]
    bench_name = {"B": "S&P 500", "B_prime": "QQQ", "C": "IWO/ARKK"}[mode]
    if underperformance_pp is None:
        return AppliedOverlay(
            name="drawdown_tighten",
            multiplier=1.0,
            reason=(
                f"portfolio_underperformance_pp_vs_bench not provided — "
                f"no drawdown overlay applied (mode {mode} threshold "
                f"vs {bench_name}: {threshold}pp)"
            ),
        )
    if underperformance_pp <= threshold:
        return AppliedOverlay(
            name="drawdown_tighten",
            multiplier=1.0,
            reason=(
                f"underperformance {underperformance_pp:.2f}pp <= threshold "
                f"{threshold:.1f}pp ({mode} vs {bench_name}) — no tighten"
            ),
        )
    return AppliedOverlay(
        name="drawdown_tighten",
        multiplier=0.5,
        reason=(
            f"underperformance {underperformance_pp:.2f}pp > threshold "
            f"{threshold:.1f}pp ({mode} vs {bench_name}) → sizing × 0.5 "
            "per Section 4.6 PB#2 overlay 2"
        ),
    )


def _vol_overlay(s0_vol_z: Optional[float]) -> AppliedOverlay:
    """Hard overlay 3 — S0 vol-elevated.

    Per Section 4.6: if S0 vol dimension > +1σ, sizing × 0.7.
    """
    if s0_vol_z is None:
        return AppliedOverlay(
            name="vol_regime",
            multiplier=1.0,
            reason="s0_vol_z not provided — no vol overlay applied",
        )
    if s0_vol_z <= 1.0:
        return AppliedOverlay(
            name="vol_regime",
            multiplier=1.0,
            reason=(
                f"S0 vol z={s0_vol_z:.2f} <= +1σ — no tighten"
            ),
        )
    return AppliedOverlay(
        name="vol_regime",
        multiplier=0.7,
        reason=(
            f"S0 vol z={s0_vol_z:.2f} > +1σ → sizing × 0.7 per "
            "Section 4.6 PB#2 overlay 3"
        ),
    )


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------


def compute_sizing(ctx: SizingContext) -> SizingSuggestion:
    """Compute SizingSuggestion per Section 4.6 PB#2 v0.1 + 3 hard overlays.

    Multiplier application:
      * drawdown × vol multipliers compound on BOTH initial_pct and max_pct.
      * cash multiplier applies ONLY to initial_pct (max is the post-funding
        ceiling — not constrained by today's cash).
      * net_multiplier = product of all overlay multipliers (computed from
        the initial_pct path; max_pct may not see the cash factor).

    Edge cases handled:
      - All overlay inputs None → multipliers all 1.0; funding_required false.
      - Cash exactly equals target → mult 1.0; funding_required false.
      - underperformance exactly at threshold → no tighten (strict ">").
      - vol_z exactly +1σ → no tighten (strict ">").
      - s0_vol_z heavily negative → unchanged (overlay only TIGHTENS, never
        loosens — v0.1 conservative; v0.5+ may permit relaxation).
      - Mode unknown → ValueError surfaced upward.
    """
    initial_band, max_band = _band_for_mode(ctx.mode)

    drawdown_ov = _drawdown_overlay(
        ctx.mode, ctx.portfolio_underperformance_pp_vs_bench
    )
    vol_ov = _vol_overlay(ctx.s0_vol_z)

    # Drawdown + vol compound on initial path; we apply them BEFORE cash
    # overlay so the cash check uses the already-tightened target.
    initial_after_dd_vol = initial_band * drawdown_ov.multiplier * vol_ov.multiplier
    max_after_dd_vol = max_band * drawdown_ov.multiplier * vol_ov.multiplier

    cash_ov, cash_mult_initial, funding_required = _cash_overlay(
        initial_after_dd_vol, ctx.available_cash_pct
    )

    initial_pct = initial_after_dd_vol * cash_mult_initial
    # max_pct does NOT include cash multiplier — see docstring.
    max_pct = max_after_dd_vol

    net_multiplier = (
        drawdown_ov.multiplier * vol_ov.multiplier * cash_mult_initial
    )

    return SizingSuggestion(
        initial_pct=initial_pct,
        max_pct=max_pct,
        base_band={"initial": initial_band, "max": max_band},
        applied_overlays=[cash_ov, drawdown_ov, vol_ov],
        net_multiplier=net_multiplier,
        funding_required=funding_required,
    )


__all__ = [
    "AppliedOverlay",
    "SizingContext",
    "SizingSuggestion",
    "compute_sizing",
]
