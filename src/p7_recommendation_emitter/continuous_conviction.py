"""Continuous conviction score — v0.5 upgrade (v3 spec §6.4).

The v0.1 conviction rollup (`conviction_rollup.py`) emits a discrete
HIGH/MEDIUM/LOW band. v0.5 adds a *continuous* score in [0, 1] derived
from the same inputs so:
    * the composable sizing formula can multiply by a smooth conviction
      multiplier instead of stepping on band boundaries
    * Brier-haircut becomes a continuous attenuation rather than a discrete
      demote
    * the band hysteresis (Phase 4 Q7) operates on score-distance rather
      than band-flip count

The score is a weighted average of four normalized component signals.
Equal weights at v0.5-entry; per spec §6.4, weights recalibrate
empirically once N≥50 outcomes per cell accrue.

Signal components (each in [0, 1], higher = more bullish):

    debate    : debate_add_count / debate_total
    kills     : 1 if kills_fired==0; 0.5 if exactly 1; 0 if ≥2
    cf_balance: max(0, (survivor - non_survivor) / 3 + 0.5)
                — 3 SURVIVOR & 0 NON-SURV → 1.0
                — 0 SURVIVOR & 3 NON-SURV → 0.0
                — balanced → 0.5
    drift     : 1 - (anchor_drift_channels_triggered / 3)

The score is stored in `execution_recommendations.conviction_breakdown`
JSONB under key `continuous_score`; the discrete bucket continues to be
the canonical operator-facing band per spec §4.6.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.p7_recommendation_emitter.conviction_rollup import (
    ConvictionInputs,
    _count_survivor,
)

# Equal weights at v0.5-entry. Per spec §6.4, recalibrated against
# recommendation_outcomes once N≥50 outcomes per cell exist. We deliberately
# expose this as a module constant so the recalibration job can write back
# directly without circular imports.
DEFAULT_COMPONENT_WEIGHTS: dict[str, float] = {
    "debate": 0.25,
    "kills": 0.25,
    "cf_balance": 0.25,
    "drift": 0.25,
}


@dataclass(frozen=True)
class ContinuousConviction:
    """Score + per-component breakdown."""

    score: float                      # in [0, 1]
    components: dict[str, float]      # raw component values
    weights: dict[str, float]         # weights actually applied

    def to_payload(self) -> dict:
        return {
            "continuous_score": round(self.score, 4),
            "components": {k: round(v, 4) for k, v in self.components.items()},
            "weights": {k: round(v, 4) for k, v in self.weights.items()},
        }


# --------------------------------------------------------------------------- #
# Component helpers                                                           #
# --------------------------------------------------------------------------- #


def _debate_component(inp: ConvictionInputs) -> float:
    if inp.debate_total <= 0:
        return 0.0
    return inp.debate_add_count / inp.debate_total


def _kills_component(inp: ConvictionInputs) -> float:
    if inp.kills_fired <= 0:
        return 1.0
    if inp.kills_fired == 1:
        return 0.5
    return 0.0


def _cf_balance_component(inp: ConvictionInputs) -> float:
    survivor, non_survivor = _count_survivor(inp.counterfactual_top_3)
    # net ∈ [-3, 3]; map to [-0.5, 0.5] then shift to [0, 1].
    net = (survivor - non_survivor) / 3.0
    raw = 0.5 + net * 0.5
    return max(0.0, min(1.0, raw))


def _drift_component(inp: ConvictionInputs) -> float:
    triggered = inp.anchor_drift_channels_triggered
    return max(0.0, min(1.0, 1.0 - triggered / 3.0))


# --------------------------------------------------------------------------- #
# Main entrypoint                                                             #
# --------------------------------------------------------------------------- #


def score_conviction(
    inp: ConvictionInputs,
    *,
    weights: Optional[dict[str, float]] = None,
) -> ContinuousConviction:
    """Score conviction in [0, 1].

    Args:
        inp: same inputs as the discrete-bucket rollup. Validation is
            light here — the discrete rollup performs the strict validation
            and is expected to run first; this scorer should be tolerant
            so it can also operate on shadow-mode replays.
        weights: per-component weights; default = DEFAULT_COMPONENT_WEIGHTS.
            If a partial dict is provided, missing weights default to 0
            and the weights are renormalized to sum to 1.0.

    Returns:
        ContinuousConviction.
    """
    components = {
        "debate": _debate_component(inp),
        "kills": _kills_component(inp),
        "cf_balance": _cf_balance_component(inp),
        "drift": _drift_component(inp),
    }

    w = dict(weights or DEFAULT_COMPONENT_WEIGHTS)
    # Drop unknown keys, default missing to 0.0
    w = {k: float(w.get(k, 0.0)) for k in components}
    total_w = sum(w.values())
    if total_w <= 0:
        # All-zero weights → fall back to default to avoid /0
        w = dict(DEFAULT_COMPONENT_WEIGHTS)
        total_w = sum(w.values())
    w = {k: v / total_w for k, v in w.items()}

    score = sum(components[k] * w[k] for k in components)
    score = max(0.0, min(1.0, score))

    return ContinuousConviction(
        score=score,
        components=components,
        weights=w,
    )
