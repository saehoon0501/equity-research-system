"""Tests for tactical envelope HG validator (mirrors HG-31 catalyst_memo_shape)."""

import json
import subprocess
import sys

import pytest

from src.evaluator_gates.tactical_envelope_shape import (
    TACTICAL_BIN_VALUES,
    TACTICAL_DISPOSITION_VALUES,
    validate,
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
    result = validate(_valid_envelope())
    assert result.passed is True
    assert result.errors == []


def test_missing_top_level_key_fails():
    env = _valid_envelope()
    del env["tactical_signal_bin"]
    result = validate(env)
    assert result.passed is False
    assert any("tactical_signal_bin" in e for e in result.errors)


def test_invalid_tactical_bin_enum_fails():
    env = _valid_envelope()
    env["tactical_signal_bin"] = "BOGUS"
    result = validate(env)
    assert result.passed is False
    assert any("tactical_signal_bin invalid" in e for e in result.errors)


def test_inv_2_1_a_canonical_buy_rejected_at_validator():
    """INV-2.1-A: canonical 'BUY' in cell_disposition must be rejected."""
    env = _valid_envelope()
    env["tactical_cell"]["cell_disposition"] = "BUY"  # canonical, not tactical
    result = validate(env)
    assert result.passed is False
    assert any("INV-2.1-A" in e for e in result.errors)


def test_inv_2_1_a_canonical_trim_rejected():
    env = _valid_envelope()
    env["tactical_cell"]["cell_disposition"] = "TRIM"
    result = validate(env)
    assert result.passed is False
    assert any("cell_disposition" in e for e in result.errors)


def test_buy_high_disposition_accepted():
    env = _valid_envelope()
    env["tactical_cell"]["cell_disposition"] = "BUY-HIGH"
    assert validate(env).passed is True


def test_buy_med_disposition_accepted():
    env = _valid_envelope()
    env["tactical_cell"]["conviction"] = "MEDIUM"
    env["tactical_cell"]["tactical_bin"] = "positive"
    env["tactical_cell"]["cell_size_pct"] = 3.0
    env["tactical_cell"]["cell_disposition"] = "BUY-MED"
    assert validate(env).passed is True


def test_avoid_disposition_accepted():
    env = _valid_envelope()
    env["tactical_cell"]["conviction"] = "LOW"
    env["tactical_cell"]["tactical_bin"] = "negative"
    env["tactical_cell"]["cell_size_pct"] = 0.0
    env["tactical_cell"]["cell_disposition"] = "AVOID"
    assert validate(env).passed is True


def test_unavailable_bin_requires_reason():
    env = _valid_envelope()
    env["tactical_signal_bin"] = "unavailable"
    env["unavailable_reason"] = None
    result = validate(env)
    assert result.passed is False
    assert any("unavailable_reason" in e for e in result.errors)


def test_unavailable_with_valid_reason_passes():
    env = _valid_envelope()
    env["tactical_signal_bin"] = "unavailable"
    env["unavailable_reason"] = "insufficient_price_history"
    env["tactical_cell"]["tactical_bin"] = "unavailable"
    env["tactical_cell"]["cell_size_pct"] = 3.0  # band.min for HIGH unavailable
    env["tactical_cell"]["cell_disposition"] = "HOLD"
    assert validate(env).passed is True


def test_invalid_unavailable_reason_fails():
    env = _valid_envelope()
    env["tactical_signal_bin"] = "unavailable"
    env["unavailable_reason"] = "made_up_reason"
    result = validate(env)
    assert result.passed is False


def test_invalid_conviction_enum_fails():
    env = _valid_envelope()
    env["tactical_cell"]["conviction"] = "EXTREME"
    result = validate(env)
    assert result.passed is False
    assert any("conviction invalid" in e for e in result.errors)


def test_non_numeric_cell_size_pct_fails():
    env = _valid_envelope()
    env["tactical_cell"]["cell_size_pct"] = "6.0"  # string, not number
    result = validate(env)
    assert result.passed is False
    assert any("cell_size_pct" in e for e in result.errors)


def test_boolean_cell_size_pct_rejected():
    """Boolean is technically isinstance(int) — guard against True/False sneaking in."""
    env = _valid_envelope()
    env["tactical_cell"]["cell_size_pct"] = True
    result = validate(env)
    assert result.passed is False


def test_rf_degenerate_must_be_bool():
    env = _valid_envelope()
    env["rf_degenerate"] = "false"
    result = validate(env)
    assert result.passed is False
    assert any("rf_degenerate" in e for e in result.errors)


def test_tactical_cell_must_be_dict():
    env = _valid_envelope()
    env["tactical_cell"] = "not a dict"
    result = validate(env)
    assert result.passed is False


def test_missing_tactical_cell_subkey_fails():
    env = _valid_envelope()
    del env["tactical_cell"]["cell_disposition"]
    result = validate(env)
    assert result.passed is False
    assert any("tactical_cell.cell_disposition" in e for e in result.errors)


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
    assert "INV-2.1-A" in result.stderr
