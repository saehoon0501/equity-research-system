"""Pure-unit tests for the pinned parameter snapshot + tighten-only resolver.

Task 1.2 (reactive-signal-model). Asserts the observable params contract the
parent's import/shape check cannot: `DEFAULTS` instantiates frozen with every
field present and calibration both-None (unestablished at the inner ring,
Req 7.4 / design §params Invariants); the near-equal weights are normalized so
`Σw == 1` (Req 1.5); and `effective_threshold` is *tighten-only* (Req 6.3/6.4) —
a higher runtime override is applied, a lower one is rejected and the snapshot
threshold retained, and `None` returns the snapshot threshold unchanged.

`Weights` / `CalibrationEvidence` are REUSED from `src.reactive.types`
(task 1.1) — never redefined here (types → params dependency direction).

No LLM, MCP, or live DB — pure leaf config contract (P1, R8).
Task 3.1 will EXTEND this file with broader coverage; keep tests here.
"""

from __future__ import annotations

import dataclasses as d

import pytest

from src.reactive.params import DEFAULTS, ParamSnapshot, effective_threshold
from src.reactive.types import CalibrationEvidence, Weights


# --- DEFAULTS: frozen, all fields present, calibration unestablished -------


def test_defaults_is_param_snapshot_with_all_fields() -> None:
    assert isinstance(DEFAULTS, ParamSnapshot)
    assert {f.name for f in d.fields(ParamSnapshot)} == {
        "weights",
        "temperature",
        "threshold",
        "calibration",
        "code_version",
        "param_version",
    }


def test_defaults_field_types_and_values() -> None:
    assert isinstance(DEFAULTS.weights, Weights)
    assert isinstance(DEFAULTS.calibration, CalibrationEvidence)
    # temperature must be positive (it divides the logit downstream).
    assert DEFAULTS.temperature > 0
    # threshold is compared against a logistic probability ∈ (0, 1).
    assert 0.0 < DEFAULTS.threshold < 1.0
    # version tags present and non-empty (carried into the substrate).
    assert isinstance(DEFAULTS.code_version, str) and DEFAULTS.code_version
    assert isinstance(DEFAULTS.param_version, str) and DEFAULTS.param_version


def test_defaults_frozen() -> None:
    with pytest.raises(d.FrozenInstanceError):
        DEFAULTS.threshold = 0.99  # type: ignore[misc]


def test_defaults_calibration_both_none() -> None:
    # Unestablished at the inner ring — exposed, never computed here (R7.4).
    assert DEFAULTS.calibration.brier is None
    assert DEFAULTS.calibration.reliability is None


def test_defaults_weights_sum_to_one() -> None:
    # Near-equal, normalized so the aggregate score stays in [-1, +1] (R1.5).
    w = DEFAULTS.weights
    assert w.w_trend + w.w_flow + w.w_meanrev == pytest.approx(1.0)


def test_defaults_weights_near_equal() -> None:
    # No single family dominates the combined signal (R1.5): each near 1/3.
    w = DEFAULTS.weights
    for val in (w.w_trend, w.w_flow, w.w_meanrev):
        assert val == pytest.approx(1.0 / 3.0, abs=0.05)


# --- effective_threshold: tighten-only (R6.3/6.4) --------------------------


def test_effective_threshold_none_returns_snapshot() -> None:
    # No runtime override → snapshot threshold unchanged.
    assert effective_threshold(DEFAULTS, None) == DEFAULTS.threshold


def test_effective_threshold_higher_runtime_applied() -> None:
    # Runtime strictly above snapshot → the HIGHER (tighter) value applies.
    higher = DEFAULTS.threshold + 0.1
    assert effective_threshold(DEFAULTS, higher) == higher
    assert effective_threshold(DEFAULTS, higher) > DEFAULTS.threshold


def test_effective_threshold_lower_runtime_rejected() -> None:
    # Runtime strictly below snapshot → REJECTED; snapshot threshold retained.
    lower = DEFAULTS.threshold - 0.1
    assert effective_threshold(DEFAULTS, lower) == DEFAULTS.threshold


def test_effective_threshold_never_below_snapshot() -> None:
    # The tighten-only invariant across a sweep straddling the snapshot value.
    for runtime in (0.0, DEFAULTS.threshold - 0.2, DEFAULTS.threshold + 0.2, 1.0):
        assert effective_threshold(DEFAULTS, runtime) >= DEFAULTS.threshold
