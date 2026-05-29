"""Reactive Signal Model: the pinned parameter snapshot, defaults, and the
tighten-only threshold resolver.

The model consumes parameters **by value** — a `ParamSnapshot` pinned at the
start of a run (P2), never re-resolved against live `parameters_active`
mid-run (R6.2). This module declares that snapshot shape, a module-constant
`DEFAULTS` for the inner ring, and `effective_threshold` — the *tighten-only*
runtime-override resolver (R6.3/R6.4): a runtime threshold HIGHER than the
snapshot is applied, a LOWER one is rejected and the snapshot threshold
retained. It never fits, tunes, or computes parameters or calibration metrics
(R6.5/R7.4) — those are owned by `walkforward-tuning-loop`.

Dependency direction is strict (design §Allowed Dependencies):
`types -> params -> features -> signal_model`. `Weights` and
`CalibrationEvidence` are REUSED from `src.reactive.types` (task 1.1) — imported
here, never redefined (that would invert the types→params direction).

Pure leaf (P1): stdlib + the sibling `types` module only — no numpy, no MCP,
no DB. Deterministic and isolatable (R8).
"""

from __future__ import annotations

from dataclasses import dataclass

from src.reactive.types import CalibrationEvidence, Weights


@dataclass(frozen=True)
class ParamSnapshot:
    """The active, pinned parameter snapshot consumed by value (R6.1, P2).

    Frozen (immutable) so a run cannot mutate ground truth mid-flight. The
    `walkforward-tuning-loop` produces tuned values and `execution-daemon`
    pins/passes the snapshot; this model only *consumes* it. `code_version` /
    `param_version` are byte-identical to the landed telemetry
    `CorrelationKeys` typed columns (design line 223) — they flow onto the
    `DecisionSubstrate` and promote to the `decision_process_trace` row.
    `calibration` is *exposed* here, never computed (R7.4).
    """

    weights: Weights
    temperature: float
    threshold: float
    calibration: CalibrationEvidence
    code_version: str
    param_version: str


# --- Module-constant defaults (the inner ring; R6.1) -----------------------

# Near-equal base weights (R1.5) normalized so `w_trend + w_flow + w_meanrev`
# sums to exactly 1.0 in IEEE754 (0.34 + 0.33 + 0.33), keeping the aggregate
# score `s ∈ [-1, +1]`. No single family dominates the combined signal.
_DEFAULT_WEIGHTS = Weights(w_trend=0.34, w_flow=0.33, w_meanrev=0.33)

DEFAULTS: ParamSnapshot = ParamSnapshot(
    weights=_DEFAULT_WEIGHTS,
    # Prior temperature: an un-fit positive scale for the logistic; the tuning
    # loop establishes the calibrated value downstream (design §Probability).
    temperature=1.0,
    # Prior decision threshold ∈ (0, 1): compared against the logistic
    # probability; a conservative-Edge prior, tuned downstream.
    threshold=0.55,
    # Calibration is UNESTABLISHED at the inner ring — exposed, never computed
    # here (R7.4 / design §params Invariants: DEFAULTS.calibration == None).
    calibration=CalibrationEvidence(brier=None, reliability=None),
    code_version="reactive-signal-model@v0.1",
    param_version="defaults@v0.1",
)


def effective_threshold(snapshot: ParamSnapshot, runtime: float | None) -> float:
    """Resolve the threshold actually applied — *tighten-only* (R6.3/R6.4).

    Returns `snapshot.threshold` when `runtime is None`; otherwise
    `max(snapshot.threshold, runtime)`. A runtime override HIGHER than the
    snapshot threshold is applied (de-risking allowed); a LOWER one is rejected
    and the snapshot threshold retained (loosening forbidden, P7). The result
    is NEVER below `snapshot.threshold`. This is a pure resolution of two
    passed values — it does not re-resolve from live state (R6.2) and does not
    fit/tune/compute any parameter (R6.5).
    """
    if runtime is None:
        return snapshot.threshold
    return max(snapshot.threshold, runtime)
