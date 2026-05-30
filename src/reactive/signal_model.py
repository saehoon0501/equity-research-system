"""Reactive Signal Model: the decision core (`signal_model`).

Tasks 2.2 + 2.3 — the front half of the pure deterministic pipeline
(design §Architecture Pattern):

    features → [aggregate → signed projection → 2-class logistic] → threshold → decide

- 2.2 landed the **directional aggregation** (`aggregate_score`) of the family
  votes and the **signed projection** (`project`) onto the caller-supplied
  direction.
- 2.3 lands the **2-class logistic** (`probability`) deriving `P(direction
  correct)` from the projected score, and the **calibration-exposure** path
  (`expose_calibration`) that carries the snapshot's `CalibrationEvidence`
  through unchanged.

Task 2.4 (and 3.3) EXTEND this module with the tighten-only threshold, the
`ReactiveDecision`/substrate, and the `decide(...)` entry point that composes
these standalone functions. The functions here are deliberately standalone and
side-effect-free so that future `decide()` chains them
(`signed = project(aggregate_score(...), direction)` → `probability(signed,
snapshot.temperature)`) — there is no placeholder `decide`/threshold here (that
would cross the 2.4 boundary and fake-green the decision).

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

import math

from src.reactive.features import FeatureSet
from src.reactive.params import ParamSnapshot, Weights
from src.reactive.params import effective_threshold as _effective_threshold
from src.reactive.types import (
    CalibrationEvidence,
    DecisionSubstrate,
    Direction,
    FeatureFailure,
    ReactiveDecision,
)

# The valid caller-supplied directional sides (R3.1). Anything outside this set
# (None, lowercase, "BUY"/"SELL", a non-string) is `invalid_direction` — the
# reason `decide` OWNS (design §Feature adapter "Failure ownership").
_VALID_DIRECTIONS = ("LONG", "SHORT")


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


def probability(signed: float, temperature: float) -> float:
    """Derive `P(caller direction is the correct side)` via a 2-class logistic.

        P = 1 / (1 + exp(−signed / temperature))

    where `signed` is the 2.2 `project(...)` output (the directional aggregate
    oriented onto the caller-supplied side). This is a **model-derived**
    probability (a logistic over a deterministic score; P15 option (a)) — it is
    NOT asserted from qualitative reasoning. Properties (all unit-tested):

    - monotonic **increasing** in `signed` (more favorable score ⇒ higher P);
    - in the **open** interval `(0, 1)` for every finite `signed`;
    - `signed = 0 → 0.5` (no edge ⇒ even odds);
    - symmetric about 0.5: `P(signed) + P(−signed) == 1` (the LONG/SHORT mirror,
      combined with `project`'s sign flip);
    - lower `temperature` **sharpens** P (pushes it further from 0.5).

    The reference intraday `_softmax3` carried an explicit HOLD logit
    (conviction-deficit × liquidity); this model **drops it entirely** (design
    §"Probability derivation", Boundary line 28): HOLD comes ONLY from the
    `probability`-vs-threshold comparison downstream (task 2.4), never from a
    term inside the probability. Direction being caller-supplied, the long/short
    pair reduces to this single logistic.

    **Calibration is established downstream, not here.** Under inner-ring
    `DEFAULTS` the `temperature` is an un-fit prior, so this is a model-derived
    SCORE whose calibration is *unestablished* until `walkforward-tuning-loop`
    fits `temperature`/`weights` and computes Brier/reliability (R7.4). This
    function computes no calibration metric.

    Args:
        signed: the projected directional score (`+ ⇒ favors caller direction`),
            typically `project(aggregate_score(features, weights), direction)`.
            Bounded `|signed| ≤ 1` when the upstream votes are in range, so plain
            `math.exp` cannot overflow.
        temperature: the snapshot's logistic temperature (`> 0`; positivity is
            the `params` snapshot's contract, not re-validated here). Higher ⇒
            softer (P closer to 0.5); lower ⇒ sharper (P further from 0.5).

    Returns:
        `P ∈ (0, 1)` — the derived confidence the caller-supplied direction is
        the correct side.
    """
    return 1.0 / (1.0 + math.exp(-signed / temperature))


def expose_calibration(snapshot: ParamSnapshot) -> CalibrationEvidence:
    """Expose the snapshot's calibration evidence — carried through, never computed.

    Returns `snapshot.calibration` **unchanged** (the same object). The model
    *exposes* the calibration evidence the active snapshot carries (R2.4, R7.1)
    alongside the derived probability; it NEVER computes Brier/reliability over
    realized outcomes — that batch computation is owned by `walkforward-tuning-
    loop` (R7.4). At the inner ring (`DEFAULTS`) this is the unestablished
    `CalibrationEvidence(None, None)`; once the tuning loop closes the loop, the
    pinned snapshot carries the fitted values and they pass straight through.

    This is a deliberate identity pass-through (not a reconstruction): the
    returned object **is** `snapshot.calibration`, so nothing here mutates or
    fabricates a metric. (Task 2.4's `decide` places this evidence onto the
    `DecisionSubstrate` for telemetry.)

    Args:
        snapshot: the active, pinned `ParamSnapshot` consumed by value (P2).

    Returns:
        The snapshot's `CalibrationEvidence`, carried through unchanged.
    """
    return snapshot.calibration


# --- The public entry point: assemble the thresholded decision (task 2.4) ----

# Sentinel probability for the two abstain paths (invalid_direction /
# FeatureFailure) where no logistic is derived. The load-bearing discriminator
# is `reason is not None` (a sub-threshold HOLD has `reason=None` and a REAL
# derived `P`); this sentinel is non-load-bearing telemetry. `0.0` (not `0.5`)
# so it reads as "not derived" rather than a genuine no-edge derivation
# (`signed=0 → P=0.5` is a real main-path value).
_ABSTAIN_PROBABILITY = 0.0


def decide(
    features: FeatureSet | FeatureFailure,
    direction: Direction,
    snapshot: ParamSnapshot,
    runtime_threshold: float | None = None,
) -> ReactiveDecision:
    """The public Edge entry point: emit the thresholded LONG/SHORT/HOLD decision.

    Assembles the pure pipeline from the standalone 2.1–2.3 pieces — it does NOT
    reimplement them:

        s      = aggregate_score(features, snapshot.weights)   # 2.2
        signed = project(s, direction)                          # 2.2
        P      = probability(signed, snapshot.temperature)      # 2.3
        θ_eff  = params.effective_threshold(snapshot, runtime)  # tighten-only (R6)
        decision = direction if P > θ_eff else HOLD             # strict-`>` (R3.3/3.4)

    **Two abstain paths degrade to HOLD with a machine-readable `reason`** (never
    raises — design §Error Strategy), checked in this strict order:

    1. **`invalid_direction` (OWNED here, R3.6):** if `direction` is missing or not
       in {LONG, SHORT}, return HOLD + `reason="invalid_direction"` BEFORE touching
       `features` (so a malformed `features` is never read on this path). This is
       checked first, so an invalid direction wins even when `features` is also a
       `FeatureFailure`.
    2. **`FeatureFailure` → HOLD + its `reason`:** if `features` is a
       `FeatureFailure`, return HOLD carrying `features.reason` verbatim. `decide`
       **trusts the discriminator** and does NOT re-validate history/ATR (design
       §Feature adapter "Failure ownership" — `features` single-owns
       `insufficient_history`/`degenerate_features`).

    On the main path the decision is the caller direction iff `P > θ_eff`, else
    HOLD (R3.3/R3.4). The model NEVER selects or flips the side (R3.2/R4.3): the
    only outcomes are the caller's `direction` or HOLD.

    **Every decision is `non_final=True` (R4.1)** — a vetoable Edge candidate the
    higher lexicographic links (Survive/Preserve) can downgrade but never upgrade
    (P7). The model never inspects survival state (R4.2).

    **Sizing hint (advisory; R5):** when actionable (`decision != HOLD`) it is the
    distance the probability clears the effective threshold, `P − θ_eff` — a
    positive scalar that INCREASES with `P` above `θ_eff` (R5.1). It is *advisory*
    (a bare hint; the model enforces NO size and NO cap — R5.3/R5.4/R5.5) and is
    `None` on every HOLD path (R5.2 — no actionable hint).

    **Substrate (R7):** every returned `ReactiveDecision` carries a
    `DecisionSubstrate` with the feature `raw` values (or `{}` on abstain), the
    derived `P` (or the `_ABSTAIN_PROBABILITY` sentinel), the EFFECTIVE threshold
    actually applied, the consumed `code_version`/`param_version`, and the
    snapshot's `CalibrationEvidence` (exposed, never computed — R7.4). `θ_eff` is
    resolved ONCE at the top via `params.effective_threshold` and reused on all
    three paths, so it is honest telemetry even on the abstains.

    Determinism (R8.1): identical `(features, direction, snapshot,
    runtime_threshold)` → identical `ReactiveDecision`. Pure: stdlib + sibling
    contracts only — no LLM, no MCP, no DB.

    Args:
        features: the computed `FeatureSet`, or a `FeatureFailure` discriminator.
        direction: the caller-supplied side ("LONG"/"SHORT"); the model never
            selects it (R3.1/R3.2). Anything else ⇒ `invalid_direction`.
        snapshot: the active, pinned `ParamSnapshot` consumed by value (P2).
        runtime_threshold: an optional tighten-only override (R6.3/R6.4).

    Returns:
        The `ReactiveDecision` (decision, echoed `direction_in`, probability,
        sizing_hint, non_final, reason, substrate).
    """
    # θ_eff: resolved ONCE (tighten-only) and reused on every path so the
    # substrate's effective threshold is honest even on the abstains (R6/R7.3).
    eff_threshold = _effective_threshold(snapshot, runtime_threshold)
    calibration = expose_calibration(snapshot)

    def _hold_abstain(reason, feature_values: dict, prob: float) -> ReactiveDecision:
        """Build a non-final HOLD for an abstain path (no actionable sizing hint)."""
        return ReactiveDecision(
            decision="HOLD",
            direction_in=direction,
            probability=prob,
            sizing_hint=None,
            non_final=True,
            reason=reason,
            substrate=DecisionSubstrate(
                feature_values=feature_values,
                probability=prob,
                effective_threshold=eff_threshold,
                code_version=snapshot.code_version,
                param_version=snapshot.param_version,
                calibration=calibration,
            ),
        )

    # --- Abstain 1: invalid/missing direction (OWNED here; checked FIRST) ----
    # Guard runs before `features` is read, so a malformed `features` never
    # explodes on this path, and an invalid direction wins over a FeatureFailure.
    if direction not in _VALID_DIRECTIONS:
        return _hold_abstain(
            reason="invalid_direction",
            feature_values={},
            prob=_ABSTAIN_PROBABILITY,
        )

    # --- Abstain 2: FeatureFailure → HOLD + its reason (trust discriminator) -
    # No re-validation of history/ATR (design §Feature adapter failure-ownership).
    if isinstance(features, FeatureFailure):
        return _hold_abstain(
            reason=features.reason,
            feature_values={},
            prob=_ABSTAIN_PROBABILITY,
        )

    # --- Main path: aggregate → project → logistic → strict-`>` threshold ----
    s = aggregate_score(features, snapshot.weights)
    signed = project(s, direction)
    p = probability(signed, snapshot.temperature)

    if p > eff_threshold:
        decision: Direction = direction
        # Advisory sizing hint: increases with how far P clears θ_eff (R5.1).
        # A bare scalar — no size, no cap enforced (R5.3/R5.4/R5.5).
        sizing_hint: float | None = p - eff_threshold
    else:
        decision = "HOLD"  # P ≤ θ_eff (strict-`>`): sub-threshold HOLD (R3.4)
        sizing_hint = None  # no actionable hint on HOLD (R5.2)

    return ReactiveDecision(
        decision=decision,
        direction_in=direction,
        probability=p,
        sizing_hint=sizing_hint,
        non_final=True,  # always vetoable (R4.1); never escalates (P7)
        reason=None,  # a real derivation (incl. sub-threshold HOLD), not an abstain
        substrate=DecisionSubstrate(
            feature_values=features.raw,
            probability=p,
            effective_threshold=eff_threshold,
            code_version=snapshot.code_version,
            param_version=snapshot.param_version,
            calibration=calibration,
        ),
    )
