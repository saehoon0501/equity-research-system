"""Pure-unit shape/contract tests for the Reactive Signal Model types.

Task 1.1 (reactive-signal-model). Asserts the named observables the parent's
import/shape check can't on its own: the fixed decision/failure vocabularies
equal the design's literals exactly, every contract exposes the specified
fields, and the dataclasses the design mandates frozen are actually frozen.
No LLM, MCP, or live DB — these are pure leaf type contracts (P1, R8).

Requirements: 2 (derived probability + carried calibration evidence),
3 (LONG/SHORT/HOLD vocab + caller direction echo), 4 (non-final flag),
5 (advisory sizing-hint field), 7 (calibration evidence + substrate exposure),
8 (deterministic, typed, isolatable contract).
"""

from __future__ import annotations

import dataclasses as d
from typing import get_args, get_type_hints

import pytest

from src.reactive.types import (
    Bar,
    CalibrationEvidence,
    Decision,
    DecisionSubstrate,
    Direction,
    FeatureFailure,
    Reason,
    ReactiveDecision,
    Weights,
)


# --- Fixed vocabularies (design §Types, R3.5) ----------------------------


def test_reason_literal_exact() -> None:
    members = get_args(Reason)
    assert set(members) == {
        "insufficient_history",
        "invalid_direction",
        "degenerate_features",
    }
    assert len(members) == 3  # no extras / dupes


def test_direction_literal_exact() -> None:
    members = get_args(Direction)
    assert set(members) == {"LONG", "SHORT"}
    assert len(members) == 2


def test_decision_literal_exact() -> None:
    members = get_args(Decision)
    assert set(members) == {"LONG", "SHORT", "HOLD"}
    assert len(members) == 3


# --- Bar TypedDict: OHLCV, structurally a dict (passes to indicators) -----


def test_bar_is_ohlcv_typeddict() -> None:
    # Structurally a dict so a Sequence[Bar] passes straight to indicators.atr.
    assert set(Bar.__annotations__) == {"open", "high", "low", "close", "volume"}
    assert set(getattr(Bar, "__required_keys__", Bar.__annotations__)) == {
        "open",
        "high",
        "low",
        "close",
        "volume",
    }
    bar: Bar = {"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 100.0}
    assert isinstance(bar, dict)  # structural dict, not a dataclass


# --- Field-shape assertions per contract ----------------------------------


def _names(cls: type) -> set[str]:
    return {f.name for f in d.fields(cls)}


def test_weights_fields() -> None:
    assert _names(Weights) == {"w_trend", "w_flow", "w_meanrev"}


def test_calibration_evidence_fields() -> None:
    assert _names(CalibrationEvidence) == {"brier", "reliability"}


def test_feature_failure_fields() -> None:
    assert _names(FeatureFailure) == {"reason"}


def test_decision_substrate_fields() -> None:
    assert _names(DecisionSubstrate) == {
        "feature_values",
        "probability",
        "effective_threshold",
        "code_version",
        "param_version",
        "calibration",
    }


def test_reactive_decision_fields() -> None:
    # R3 decision + echoed direction, R2 probability, R5 advisory sizing_hint,
    # R4 non_final flag, optional reason, R7 inspectable substrate.
    assert _names(ReactiveDecision) == {
        "decision",
        "direction_in",
        "probability",
        "sizing_hint",
        "non_final",
        "reason",
        "substrate",
    }


# --- Cross-spec name discipline (design line 223 revalidation trigger) -----


def test_substrate_correlation_keys_match_telemetry_schema() -> None:
    from src.reactive.telemetry.schema import CorrelationKeys

    ck = {f.name for f in d.fields(CorrelationKeys)}
    sub = _names(DecisionSubstrate)
    # code_version + param_version must be byte-identical to the landed
    # CorrelationKeys typed columns (mig 048 / schema.py).
    assert "code_version" in ck and "code_version" in sub
    assert "param_version" in ck and "param_version" in sub


# --- Frozen-ness (design mandates Weights + CalibrationEvidence frozen) ----


def test_weights_frozen() -> None:
    w = Weights(w_trend=0.34, w_flow=0.33, w_meanrev=0.33)
    with pytest.raises(d.FrozenInstanceError):
        w.w_trend = 0.5  # type: ignore[misc]


def test_calibration_evidence_frozen_and_nullable() -> None:
    ce = CalibrationEvidence(brier=None, reliability=None)
    assert ce.brier is None and ce.reliability is None
    with pytest.raises(d.FrozenInstanceError):
        ce.brier = 0.1  # type: ignore[misc]


def test_feature_failure_frozen() -> None:
    ff = FeatureFailure(reason="insufficient_history")
    assert ff.reason == "insufficient_history"
    with pytest.raises(d.FrozenInstanceError):
        ff.reason = "degenerate_features"  # type: ignore[misc]


def test_substrate_frozen() -> None:
    sub = DecisionSubstrate(
        feature_values={},
        probability=0.5,
        effective_threshold=0.5,
        code_version="c1",
        param_version="p1",
        calibration=CalibrationEvidence(brier=None, reliability=None),
    )
    with pytest.raises(d.FrozenInstanceError):
        sub.probability = 0.9  # type: ignore[misc]


def test_reactive_decision_frozen_and_constructs() -> None:
    rd = ReactiveDecision(
        decision="HOLD",
        direction_in="LONG",
        probability=0.5,
        sizing_hint=None,
        non_final=True,
        reason=None,
        substrate=DecisionSubstrate(
            feature_values={},
            probability=0.5,
            effective_threshold=0.5,
            code_version="c1",
            param_version="p1",
            calibration=CalibrationEvidence(brier=None, reliability=None),
        ),
    )
    assert rd.non_final is True
    assert rd.sizing_hint is None  # advisory field present, optional
    with pytest.raises(d.FrozenInstanceError):
        rd.decision = "LONG"  # type: ignore[misc]


# --- Type-hint contract: sizing_hint / reason optional, probability float --


def test_optional_and_scalar_annotations() -> None:
    rd_hints = get_type_hints(ReactiveDecision)
    # probability is a plain float (the early-HOLD value is a task-2.4 concern).
    assert rd_hints["probability"] is float
    # sizing_hint and reason are optional.
    assert type(None) in get_args(rd_hints["sizing_hint"])
    assert type(None) in get_args(rd_hints["reason"])
    assert rd_hints["non_final"] is bool

    ce_hints = get_type_hints(CalibrationEvidence)
    assert type(None) in get_args(ce_hints["brier"])
    assert type(None) in get_args(ce_hints["reliability"])
