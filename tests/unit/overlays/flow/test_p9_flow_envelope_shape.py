"""Tests for flow envelope HG validator (mirrors test_p8_tactical_envelope_shape.py)."""

from src.eval.gates.flow_envelope_shape import (
    FLOW_BIN_VALUES,
    FLOW_DISPOSITION_VALUES,
    validate_flow_envelope_shape,
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
    }


def test_valid_envelope_passes():
    result = validate_flow_envelope_shape(_valid_envelope())
    assert result.valid is True
    assert result.missing_top_level == []
    assert result.invalid_enum_values == []
    assert result.invalid_cell_disposition is None


def test_missing_top_level_key_fails():
    env = _valid_envelope()
    del env["flow_signal_bin"]
    result = validate_flow_envelope_shape(env)
    assert result.valid is False
    assert "flow_signal_bin" in result.missing_top_level


def test_invalid_flow_bin_enum_fails():
    env = _valid_envelope()
    env["flow_signal_bin"] = "BOGUS"
    result = validate_flow_envelope_shape(env)
    assert result.valid is False
    assert any("flow_signal_bin" in e for e in result.invalid_enum_values)


def test_inv_flow_2_1_a_canonical_buy_rejected():
    """INV-FLOW-2.1-A: canonical 'BUY' in cell_disposition must be rejected."""
    env = _valid_envelope()
    env["flow_cell"]["cell_disposition"] = "BUY"
    result = validate_flow_envelope_shape(env)
    assert result.valid is False
    assert result.invalid_cell_disposition == "BUY"


def test_inv_flow_2_1_a_canonical_trim_rejected():
    env = _valid_envelope()
    env["flow_cell"]["cell_disposition"] = "TRIM"
    result = validate_flow_envelope_shape(env)
    assert result.valid is False
    assert result.invalid_cell_disposition == "TRIM"


def test_inv_flow_2_1_a_canonical_sell_rejected():
    env = _valid_envelope()
    env["flow_cell"]["cell_disposition"] = "SELL"
    result = validate_flow_envelope_shape(env)
    assert result.valid is False
    assert result.invalid_cell_disposition == "SELL"


def test_all_four_disposition_enum_values_accepted():
    for disp in FLOW_DISPOSITION_VALUES:
        env = _valid_envelope()
        env["flow_cell"]["cell_disposition"] = disp
        # Some dispositions imply different flow_bins for cross-field consistency,
        # but this validator only enforces enum + shape — predicate cross-field
        # checks live in src/shared/agent_harness/envelopes/flow.py.
        assert validate_flow_envelope_shape(env).valid is True, f"disposition {disp} unexpectedly rejected"


def test_unavailable_bin_without_reason_fails():
    env = _valid_envelope()
    env["flow_signal_bin"] = "unavailable"
    env["flow_cell"]["flow_bin"] = "unavailable"
    env["unavailable_reason"] = None  # explicit null when bin == unavailable
    result = validate_flow_envelope_shape(env)
    assert result.valid is False
    assert result.missing_unavailable_reason is True


def test_unavailable_bin_with_valid_reason_passes():
    env = _valid_envelope()
    env["flow_signal_bin"] = "unavailable"
    env["flow_cell"]["flow_bin"] = "unavailable"
    env["unavailable_reason"] = "insufficient_price_history"
    assert validate_flow_envelope_shape(env).valid is True


def test_unavailable_bin_with_invalid_reason_fails():
    env = _valid_envelope()
    env["flow_signal_bin"] = "unavailable"
    env["flow_cell"]["flow_bin"] = "unavailable"
    env["unavailable_reason"] = "made_up_reason"
    result = validate_flow_envelope_shape(env)
    assert result.valid is False
    assert result.invalid_unavailable_reason == "made_up_reason"


def test_invalid_conviction_fails():
    env = _valid_envelope()
    env["flow_cell"]["conviction"] = "MAYBE"
    result = validate_flow_envelope_shape(env)
    assert result.valid is False
    assert result.invalid_conviction == "MAYBE"


def test_non_dict_envelope_rejected():
    result = validate_flow_envelope_shape("not a dict")
    assert result.valid is False
    assert result.notes


def test_cell_size_pct_must_be_numeric():
    env = _valid_envelope()
    env["flow_cell"]["cell_size_pct"] = "six"
    result = validate_flow_envelope_shape(env)
    assert result.valid is False
    assert result.invalid_cell_size_type == "str"


def test_cell_size_pct_bool_rejected():
    """Booleans pass isinstance(int) — must be explicitly rejected."""
    env = _valid_envelope()
    env["flow_cell"]["cell_size_pct"] = True
    result = validate_flow_envelope_shape(env)
    assert result.valid is False
    assert result.invalid_cell_size_type == "bool"
