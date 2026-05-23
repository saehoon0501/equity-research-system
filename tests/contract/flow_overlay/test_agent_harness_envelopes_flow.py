"""Tests for src/agent_harness/envelopes/flow.py validate() — covers cross-field
predicates that the HG envelope shape validator does not enforce.
"""

from src.agent_harness.envelopes.flow import (
    FLOW_BIN_VALUES,
    FLOW_DISPOSITION_VALUES,
    REASONING_STEPS,
    SCHEMA,
    validate,
)


def _valid_envelope() -> dict:
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
        "frameworks_cited": [
            "moskowitz_ooi_pedersen_tsmom_2012",
            "antonacci_dual_momentum_2014",
            "donchian_55_20_turtle",
        ],
        "reasoning_path_taken": list(REASONING_STEPS),
    }


def test_valid_envelope_passes():
    result = validate(_valid_envelope())
    assert result.valid is True
    assert result.field_errors == []
    assert result.failed_predicates == []
    assert result.invalid_reasoning_steps == []


def test_predicate_top_bin_must_equal_cell_bin():
    """top-level flow_signal_bin must match flow_cell.flow_bin."""
    env = _valid_envelope()
    env["flow_signal_bin"] = "positive"
    env["flow_cell"]["flow_bin"] = "neutral"  # mismatch
    result = validate(env)
    assert result.valid is False
    assert "top_bin_equals_cell_bin" in result.failed_predicates


def test_predicate_unavailable_implies_reason():
    """flow_signal_bin == unavailable but unavailable_reason missing → fail."""
    env = _valid_envelope()
    env["flow_signal_bin"] = "unavailable"
    env["flow_cell"]["flow_bin"] = "unavailable"
    env["flow_cell"]["cell_disposition"] = "HOLD"
    env["unavailable_reason"] = None
    result = validate(env)
    assert result.valid is False
    assert "unavailable_implies_reason" in result.failed_predicates


def test_predicate_passes_with_valid_unavailable_reason():
    env = _valid_envelope()
    env["flow_signal_bin"] = "unavailable"
    env["flow_cell"]["flow_bin"] = "unavailable"
    env["flow_cell"]["cell_disposition"] = "HOLD"
    env["unavailable_reason"] = "insufficient_price_history"
    result = validate(env)
    assert result.valid is True


def test_invented_reasoning_step_rejected():
    env = _valid_envelope()
    env["reasoning_path_taken"] = list(REASONING_STEPS) + ["pretend_step_not_in_enum"]
    result = validate(env)
    assert result.valid is False
    assert "pretend_step_not_in_enum" in result.invalid_reasoning_steps


def test_schema_required_keys():
    """SCHEMA must require the load-bearing fields."""
    required = SCHEMA["required"]
    assert "flow_signal_bin" in required
    assert "flow_cell" in required
    assert "reasoning_path_taken" in required


def test_enum_surfaces_match_validator():
    """envelope/flow.py enums must match evaluator_gates/flow_envelope_shape.py."""
    from src.evaluator_gates.flow_envelope_shape import (
        FLOW_BIN_VALUES as HG_BIN,
        FLOW_DISPOSITION_VALUES as HG_DISP,
    )
    assert set(FLOW_BIN_VALUES) == set(HG_BIN)
    assert set(FLOW_DISPOSITION_VALUES) == set(HG_DISP)
