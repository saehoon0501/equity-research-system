"""P0-1 backward-compat + new-field validation tests.

Proves the additive insight-quality fields (reasoning_trace, axis_a,
axis_b, gate_decision, calibration_emission) VALIDATE on the flow and
tactical envelopes (the two with top-level ``additionalProperties: False``)
WITHOUT breaking pre-existing envelopes that omit them entirely.

Also smoke-checks the new ``reversion`` envelope module and the P0-10
``ScoreProvider`` / ``GateDecision`` interface stubs.
"""
from __future__ import annotations

from copy import deepcopy

from src.agent_harness.envelopes import flow as flow_env
from src.agent_harness.envelopes import reversion as reversion_env
from src.agent_harness.envelopes import tactical as tactical_env


# ---------- canonical valid envelopes (no new fields) ------------------


def _flow_envelope() -> dict:
    return {
        "ticker": "GOOGL",
        "as_of_date": "2026-05-23",
        "run_id": "00000000-0000-0000-0000-000000000000",
        "flow_signal_bin": "positive",
        "unavailable_reason": None,
        "components": {
            "ticker_score": 3,
            "market_score": 2,
            "composite_score_normalized": 0.625,
        },
        "flow_cell": {
            "conviction": "HIGH",
            "flow_bin": "positive",
            "cell_size_pct": 6.0,
            "cell_disposition": "BUY-HIGH",
        },
        "frameworks_cited": ["donchian_55_20_turtle"],
        "reasoning_path_taken": list(flow_env.REASONING_STEPS),
    }


def _tactical_envelope() -> dict:
    return {
        "ticker": "AAPL",
        "as_of_date": "2026-05-23",
        "run_id": "00000000-0000-0000-0000-000000000000",
        "tactical_signal_bin": "positive",
        "rf_degenerate": False,
        "unavailable_reason": None,
        "tactical_cell": {
            "conviction": "HIGH",
            "tactical_bin": "positive",
            "cell_size_pct": 6.0,
            "cell_disposition": "BUY-HIGH",
        },
        "frameworks_cited": ["antonacci_dual_momentum_2014"],
        "reasoning_path_taken": list(tactical_env.REASONING_STEPS),
    }


def _reversion_envelope() -> dict:
    # standalone-mode, MR_NEUTRAL — reversion_cell null per v0.4.0.
    return {
        "ticker": "NVDA",
        "as_of_date": "2026-05-23",
        "run_id": "00000000-0000-0000-0000-000000000000",
        "reversion_signal_bin": "MR_NEUTRAL",
        "audit_mode": "standalone",
        "reversion_cell": None,
        "unavailable_reason": None,
        "frameworks_cited": ["bollinger_bands"],
        "reasoning_path_taken": list(reversion_env.REASONING_STEPS),
    }


# Fully-populated additive blocks (P0-1).
def _new_fields() -> dict:
    return {
        "reasoning_trace": [
            {"op": "load_ticker_prices", "rationale": "fetched 252d window"},
            {"op": "emit_envelope", "rationale": "serialized result"},
        ],
        "axis_a": {"faithfulness": 0.91, "citation_precision": 1.0, "mode": "advisory"},
        "axis_b": {"roscoe": 0.7, "novelty_percentile": 0.4, "mode": "advisory"},
        "gate_decision": {
            "verdict": "PASS",
            "deterministic": {"shape": "pass"},
            "advisory": {"judge": "agree"},
        },
        "calibration_emission": {
            "rec_id": "rec-123",
            "as_of_ts": "2026-05-23T00:00:00Z",
            "primary_horizon": "30d",
            "benchmark_id": "SPY",
            "p_beat_benchmark": 0.62,
            "label_method_version": "v1",
            "continuous_score": 0.71,
            "model_version": "claude-opus-4-7-20260101",
        },
    }


# ---------- backward-compat: old envelopes still validate --------------


def test_flow_envelope_without_new_fields_still_valid():
    result = flow_env.validate(_flow_envelope())
    assert result.valid is True, result.to_result_dict()


def test_tactical_envelope_without_new_fields_still_valid():
    result = tactical_env.validate(_tactical_envelope())
    assert result.valid is True, result.to_result_dict()


# ---------- new fields VALIDATE (not just "old tests pass") ------------


def test_flow_envelope_with_new_fields_validates():
    env = deepcopy(_flow_envelope())
    env.update(_new_fields())
    result = flow_env.validate(env)
    assert result.valid is True, result.to_result_dict()
    assert result.field_errors == []


def test_tactical_envelope_with_new_fields_validates():
    env = deepcopy(_tactical_envelope())
    env.update(_new_fields())
    result = tactical_env.validate(env)
    assert result.valid is True, result.to_result_dict()
    assert result.field_errors == []


def test_new_fields_present_in_flow_and_tactical_schema():
    for mod in (flow_env, tactical_env, reversion_env):
        props = mod.SCHEMA["properties"]
        for key in (
            "reasoning_trace",
            "axis_a",
            "axis_b",
            "gate_decision",
            "calibration_emission",
        ):
            assert key in props, f"{mod.__name__} missing {key} in properties"
            # OPTIONAL: none must be in required.
            assert key not in mod.SCHEMA["required"], (
                f"{mod.__name__}: {key} must NOT be required"
            )


def test_new_fields_nullable_do_not_break_validation():
    # Explicit nulls for every optional new block must still validate.
    env = deepcopy(_flow_envelope())
    env.update(
        {
            "reasoning_trace": None,
            "axis_a": None,
            "axis_b": None,
            "gate_decision": None,
            "calibration_emission": None,
        }
    )
    result = flow_env.validate(env)
    assert result.valid is True, result.to_result_dict()


# ---------- A2: list-form schema types enforce nested validation -------
#
# Regression for finding A2: REASONING_TRACE_SCHEMA declares
# type=["array","null"] (the LIST form), and its items declare
# required=["op","rationale"]. The old _validate_object compared
# schema.get("type") == "array" literally, so the list form skipped the
# items/required recursion entirely — malformed nested entries passed
# unchecked. After the fix, the nested shape IS enforced.


def test_reasoning_trace_entry_missing_rationale_now_fails():
    env = deepcopy(_flow_envelope())
    env["reasoning_trace"] = [
        {"op": "load_ticker_prices", "rationale": "fetched 252d window"},
        {"op": "emit_envelope"},  # missing required 'rationale'
    ]
    result = flow_env.validate(env)
    assert result.valid is False, result.to_result_dict()
    assert any("rationale" in e.path for e in result.field_errors), result.to_result_dict()


def test_reasoning_trace_non_dict_item_now_fails():
    env = deepcopy(_flow_envelope())
    env["reasoning_trace"] = [
        {"op": "load_ticker_prices", "rationale": "ok"},
        "not-a-dict",  # non-dict item — items schema is type=object
    ]
    result = flow_env.validate(env)
    assert result.valid is False, result.to_result_dict()


def test_reasoning_trace_well_formed_still_passes():
    env = deepcopy(_flow_envelope())
    env["reasoning_trace"] = [
        {"op": "load_ticker_prices", "rationale": "fetched 252d window"},
        {"op": "emit_envelope", "rationale": "serialized result"},
    ]
    result = flow_env.validate(env)
    assert result.valid is True, result.to_result_dict()
    assert result.field_errors == []


def test_reasoning_trace_null_still_passes():
    env = deepcopy(_flow_envelope())
    env["reasoning_trace"] = None
    result = flow_env.validate(env)
    assert result.valid is True, result.to_result_dict()


# ---------- new reversion envelope module ------------------------------


def test_reversion_envelope_validates():
    result = reversion_env.validate(_reversion_envelope())
    assert result.valid is True, result.to_result_dict()


def test_reversion_envelope_with_new_fields_validates():
    env = deepcopy(_reversion_envelope())
    env.update(_new_fields())
    result = reversion_env.validate(env)
    assert result.valid is True, result.to_result_dict()


def test_reversion_reuses_existing_contract():
    # Must reuse, not recreate: ReversionSignal is the p10 dataclass.
    from src.p10_reversion_overlay.contracts import ReversionSignal as Canonical

    assert reversion_env.ReversionSignal is Canonical


def test_reversion_unavailable_predicate():
    env = deepcopy(_reversion_envelope())
    env["reversion_signal_bin"] = "MR_UNAVAILABLE"
    env["unavailable_reason"] = None  # missing reason → predicate fails
    result = reversion_env.validate(env)
    assert result.valid is False
    assert "unavailable_implies_reason" in result.failed_predicates


# ---------- P0-10 interface stubs --------------------------------------


def test_scoring_contracts_import_and_typecheck():
    from src.scoring import GateDecision, ScoreProvider, ScoreResult
    from src.scoring.contracts import GateVerdict, ScoreMode

    # ScoreProvider is a runtime-checkable Protocol.
    class _DummyScorer:
        def score(self, envelope):  # noqa: ARG002
            return ScoreResult(block_name="axis_a", scores={}, mode="advisory")

    assert isinstance(_DummyScorer(), ScoreProvider)

    # TypedDicts construct as plain dicts.
    gd: GateDecision = {"verdict": "PASS", "deterministic": {}, "advisory": {}}
    assert gd["verdict"] == "PASS"
    # Literal aliases exist.
    assert "PASS" in GateVerdict.__args__  # type: ignore[attr-defined]
    assert "gate" in ScoreMode.__args__  # type: ignore[attr-defined]
