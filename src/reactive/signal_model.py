"""Reactive Signal Model: the decision core (`signal_model`).

Task 2.2 — the **directional aggregation** of the family votes and the **signed
projection** onto the caller-supplied direction. This is the front half of the
pure deterministic pipeline (design §Architecture Pattern):

    features → [aggregate → signed projection] → 2-class logistic → threshold → decide

Tasks 2.3/2.4 (and 3.3) EXTEND this module with the logistic `P(direction
correct)`, the tighten-only threshold, the `ReactiveDecision`/substrate, and the
`decide(...)` entry point. The two functions here are deliberately standalone and
side-effect-free so that future `decide()` composes them — there is no placeholder
`decide` here (that would cross the 2.3/2.4 boundary and fake-green the threshold).

**Aggregation rule (design §"Decision core — `signal_model`"):**

    s = w_t·trend_vote + w_f·flow_vote + w_m·(meanrev_vote · (1 − trend_strength))

- near-equal base weights, **normalized to Σw = 1** (enforced by `params`), so the
  aggregate `s ∈ [−1,+1]` (each vote ∈ [−1,+1], the damping factor ∈ [0,1]);
- the mean-reversion term is **dampened by trend strength** — in a strong trend
  (`trend_strength → 1`) mean-reversion recedes (`(1−1)=0`); in a range
  (`trend_strength → 0`) it contributes at full weight;
- a cross-family conflict that **survives** the damping (e.g. trend `+1` vs
  meanrev `−1` with `trend_strength≈0`) cancels to `s ≈ 0` — the conservative-Edge
  default that becomes `P ≈ 0.5 → HOLD` downstream (an Edge-link prudence, NOT a
  Survive mechanism; Survive is enforced lexicographically above by `survival-gate`).

**Signed projection (design §System Flows / §Probability derivation):**

    signed = s if direction == LONG else −s

Direction is a **pure input** — `aggregate_score` does not even take it, and
`project` only flips a sign. The model **never selects or flips** the side
(R3.2/R4.3); it confirms the caller-supplied direction downstream only when the
probability clears the threshold, else HOLD.

`trend_strength` is read from the `FeatureSet` (its single owner is `features.py`,
which defines it as `abs(flow_vote)` in v0.1 — design flags a tactical+flow-blend
refinement); this module does NOT recompute it, so the source of truth stays one.

Pure leaf (P1, R8): stdlib + the sibling `features`/`params`/`types` contracts
only — no numpy needed (pure arithmetic), no LLM, no MCP, no DB. Deterministic and
isolatable (R8.1). Dependency direction (design §Allowed Dependencies):
`types → params → features → signal_model`; nothing here imports upward.
"""

from __future__ import annotations

from src.reactive.features import FeatureSet
from src.reactive.params import Weights
from src.reactive.types import Direction


def aggregate_score(features: FeatureSet, weights: Weights) -> float:
    """Aggregate the signed family votes into a directional score `s ∈ [−1,+1]`.

    Applies the design's aggregation rule:

        s = w_t·trend_vote + w_f·flow_vote
            + w_m·(meanrev_vote · (1 − trend_strength))

    The mean-reversion vote is dampened by `features.trend_strength` (read from
    the `FeatureSet`, never recomputed here — `features.py` owns that definition).
    With normalized near-equal weights (`Σw = 1`, enforced by `params`) and votes
    ∈ [−1,+1] and a damping factor ∈ [0,1], the result is bounded `|s| ≤ 1`.

    Direction is NOT a parameter: this function cannot and does not select or flip
    the side (R3.2). The side is applied later by `project`.

    Args:
        features: the computed `FeatureSet` (signed votes + `trend_strength`).
        weights: the near-equal, normalized base weights (Σ = 1).

    Returns:
        The directional aggregate `s ∈ [−1,+1]` (`+ ⇒ favors LONG`).
    """
    damped_meanrev = features.meanrev_vote * (1.0 - features.trend_strength)
    return (
        weights.w_trend * features.trend_vote
        + weights.w_flow * features.flow_vote
        + weights.w_meanrev * damped_meanrev
    )


def project(s: float, direction: Direction) -> float:
    """Project the directional aggregate onto the caller-supplied direction.

        signed = s if direction == LONG else −s

    A pure sign flip: a LONG-favoring aggregate (`s > 0`) is favorable for a LONG
    caller (`signed > 0`) and unfavorable for a SHORT caller (`signed < 0`). The
    direction is a pure input that only chooses the sign — it never selects or
    flips the side, and `s == 0` projects to `0` for both directions (no edge ⇒
    no side). The result inherits `s`'s bound, so `|signed| ≤ 1` when `|s| ≤ 1`.

    Args:
        s: the directional aggregate from `aggregate_score` (`+ ⇒ favors LONG`).
        direction: the caller-supplied side ("LONG" or "SHORT").

    Returns:
        `signed`, oriented so that `signed > 0` favors the caller's direction.
    """
    return s if direction == "LONG" else -s
