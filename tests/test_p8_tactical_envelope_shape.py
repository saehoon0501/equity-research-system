"""Tests for tactical envelope HG validator (mirrors HG-31 catalyst_memo_shape)."""

import json
import subprocess
import sys

from src.evaluator_gates.tactical_envelope_shape import (
    TACTICAL_BIN_VALUES,
    TACTICAL_DISPOSITION_VALUES,
    validate_tactical_envelope_shape,
)


def _valid_envelope() -> dict:
    return {
        "ticker": "GOOGL",
        "as_of_date": "2026-05-20",
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
    }


def test_valid_envelope_passes():
    result = validate_tactical_envelope_shape(_valid_envelope())
    assert result.valid is True
    assert result.missing_top_level == []
    assert result.invalid_enum_values == []
    assert result.invalid_cell_disposition is None


def test_missing_top_level_key_fails():
    env = _valid_envelope()
    del env["tactical_signal_bin"]
    result = validate_tactical_envelope_shape(env)
    assert result.valid is False
    assert "tactical_signal_bin" in result.missing_top_level


def test_invalid_tactical_bin_enum_fails():
    env = _valid_envelope()
    env["tactical_signal_bin"] = "BOGUS"
    result = validate_tactical_envelope_shape(env)
    assert result.valid is False
    assert any("tactical_signal_bin" in e for e in result.invalid_enum_values)


def test_inv_2_1_a_canonical_buy_rejected_at_validator():
    """INV-2.1-A: canonical 'BUY' in cell_disposition must be rejected."""
    env = _valid_envelope()
    env["tactical_cell"]["cell_disposition"] = "BUY"  # canonical, not tactical
    result = validate_tactical_envelope_shape(env)
    assert result.valid is False
    assert result.invalid_cell_disposition == "BUY"


def test_inv_2_1_a_canonical_trim_rejected():
    env = _valid_envelope()
    env["tactical_cell"]["cell_disposition"] = "TRIM"
    result = validate_tactical_envelope_shape(env)
    assert result.valid is False
    assert result.invalid_cell_disposition == "TRIM"


def test_buy_high_disposition_accepted():
    env = _valid_envelope()
    env["tactical_cell"]["cell_disposition"] = "BUY-HIGH"
    assert validate_tactical_envelope_shape(env).valid is True


def test_buy_med_disposition_accepted():
    env = _valid_envelope()
    env["tactical_cell"]["conviction"] = "MEDIUM"
    env["tactical_cell"]["tactical_bin"] = "positive"
    env["tactical_cell"]["cell_size_pct"] = 3.0
    env["tactical_cell"]["cell_disposition"] = "BUY-MED"
    assert validate_tactical_envelope_shape(env).valid is True


def test_avoid_disposition_accepted():
    env = _valid_envelope()
    env["tactical_cell"]["conviction"] = "LOW"
    env["tactical_cell"]["tactical_bin"] = "negative"
    env["tactical_cell"]["cell_size_pct"] = 0.0
    env["tactical_cell"]["cell_disposition"] = "AVOID"
    assert validate_tactical_envelope_shape(env).valid is True


def test_unavailable_bin_requires_reason():
    env = _valid_envelope()
    env["tactical_signal_bin"] = "unavailable"
    env["unavailable_reason"] = None
    result = validate_tactical_envelope_shape(env)
    assert result.valid is False
    assert result.missing_unavailable_reason is True


def test_unavailable_with_valid_reason_passes():
    env = _valid_envelope()
    env["tactical_signal_bin"] = "unavailable"
    env["unavailable_reason"] = "insufficient_price_history"
    env["tactical_cell"]["tactical_bin"] = "unavailable"
    env["tactical_cell"]["cell_size_pct"] = 3.0  # band.min for HIGH unavailable
    env["tactical_cell"]["cell_disposition"] = "HOLD"
    assert validate_tactical_envelope_shape(env).valid is True


def test_invalid_unavailable_reason_fails():
    env = _valid_envelope()
    env["tactical_signal_bin"] = "unavailable"
    env["unavailable_reason"] = "made_up_reason"
    result = validate_tactical_envelope_shape(env)
    assert result.valid is False
    assert result.invalid_unavailable_reason == "made_up_reason"


def test_invalid_conviction_enum_fails():
    env = _valid_envelope()
    env["tactical_cell"]["conviction"] = "EXTREME"
    result = validate_tactical_envelope_shape(env)
    assert result.valid is False
    assert result.invalid_conviction == "EXTREME"


def test_non_numeric_cell_size_pct_fails():
    env = _valid_envelope()
    env["tactical_cell"]["cell_size_pct"] = "6.0"  # string, not number
    result = validate_tactical_envelope_shape(env)
    assert result.valid is False
    assert result.invalid_cell_size_type == "str"


def test_boolean_cell_size_pct_rejected():
    """Boolean is technically isinstance(int) — guard against True/False sneaking in."""
    env = _valid_envelope()
    env["tactical_cell"]["cell_size_pct"] = True
    result = validate_tactical_envelope_shape(env)
    assert result.valid is False
    assert result.invalid_cell_size_type == "bool"


def test_rf_degenerate_must_be_bool():
    env = _valid_envelope()
    env["rf_degenerate"] = "false"
    result = validate_tactical_envelope_shape(env)
    assert result.valid is False
    assert result.rf_degenerate_not_bool is True


def test_tactical_cell_must_be_dict():
    env = _valid_envelope()
    env["tactical_cell"] = "not a dict"
    result = validate_tactical_envelope_shape(env)
    assert result.valid is False
    assert result.tactical_cell_not_dict is True


def test_missing_tactical_cell_subkey_fails():
    env = _valid_envelope()
    del env["tactical_cell"]["cell_disposition"]
    result = validate_tactical_envelope_shape(env)
    assert result.valid is False
    assert "cell_disposition" in result.missing_cell_subkeys


def test_non_dict_envelope_returns_invalid_with_note():
    result = validate_tactical_envelope_shape(["not", "a", "dict"])
    assert result.valid is False
    assert any("must be dict" in n for n in result.notes)


def test_disposition_enum_matches_contracts_module():
    """Cross-module consistency check: HG validator enum matches contracts.py enum."""
    from src.p8_tactical_overlay.contracts import TacticalDisposition
    assert TACTICAL_DISPOSITION_VALUES == frozenset(TacticalDisposition.__args__)


def test_bin_enum_matches_contracts_module():
    from src.p8_tactical_overlay.contracts import TacticalBin
    assert TACTICAL_BIN_VALUES == frozenset(TacticalBin.__args__)


def test_cli_exits_zero_on_valid_envelope():
    """CLI smoke test — invoke the module via subprocess and verify exit code."""
    env = _valid_envelope()
    result = subprocess.run(
        [sys.executable, "-m", "src.evaluator_gates.tactical_envelope_shape"],
        input=json.dumps(env),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"


def test_cli_exits_nonzero_on_invalid_envelope():
    env = _valid_envelope()
    env["tactical_cell"]["cell_disposition"] = "BUY"  # INV-2.1-A violation
    result = subprocess.run(
        [sys.executable, "-m", "src.evaluator_gates.tactical_envelope_shape"],
        input=json.dumps(env),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    # stdout JSON should carry invalid_cell_disposition
    parsed = json.loads(result.stdout)
    assert parsed["invalid_cell_disposition"] == "BUY"


def test_cli_unparseable_returns_two():
    result = subprocess.run(
        [sys.executable, "-m", "src.evaluator_gates.tactical_envelope_shape"],
        input="not json{",
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "unable to read/parse" in result.stderr
