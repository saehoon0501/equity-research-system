"""Inner-ring unit tests for HG-36 reversion_envelope_shape validator (P14, v0.4.0)."""
from __future__ import annotations

import pytest

from src.eval.gates.reversion_envelope_shape import (
    validate_reversion_envelope_shape,
)


def _make_valid_envelope(**overrides) -> dict:
    """Minimal valid envelope (audit_mode=standalone, MR_NEUTRAL)."""
    base = {
        "ticker": "CRWD",
        "as_of_date": "2026-05-23",
        "run_id": "d32a5a26-5043-4a58-b611-61c104c5aa43",
        "reversion_signal_bin": "MR_NEUTRAL",
        "audit_mode": "standalone",
        "reversion_cell": None,
        "frameworks_cited": ["debondt_thaler_1985_long_term_reversal"],
        "components": {
            "drawdown_from_252d_high_pct": 5.2,
            "rsi_14": 68.4,
            "bollinger_band_position": 1.34,
            "ma_distance_200d_pct": 28.7,
            "252d_high": 700.0,
            "prior_close": 663.46,
        },
        "sub_signal_fires": {
            "drawdown_threshold": False,
            "rsi_oversold": False,
            "rsi_overbought": False,
            "bollinger_lower_extreme": False,
            "bollinger_upper_extreme": False,
        },
        "unavailable_reason": None,
    }
    base.update(overrides)
    return base


class TestValidEnvelopes:
    def test_minimal_valid_standalone_envelope_passes(self):
        env = _make_valid_envelope()
        result = validate_reversion_envelope_shape(env)
        assert result.valid is True
        assert not result.missing_top_level
        assert not result.invalid_enum_values

    def test_mr_unavailable_with_reason_passes(self):
        env = _make_valid_envelope(
            reversion_signal_bin="MR_UNAVAILABLE",
            unavailable_reason="insufficient_price_history",
            components=None,
            sub_signal_fires=None,
        )
        result = validate_reversion_envelope_shape(env)
        assert result.valid is True

    def test_mr_oversold_with_all_fires_passes(self):
        env = _make_valid_envelope(
            reversion_signal_bin="MR_OVERSOLD",
            sub_signal_fires={
                "drawdown_threshold": True,
                "rsi_oversold": True,
                "rsi_overbought": False,
                "bollinger_lower_extreme": True,
                "bollinger_upper_extreme": False,
            },
        )
        result = validate_reversion_envelope_shape(env)
        assert result.valid is True

    def test_snapshot_mode_with_uuid_and_hash_passes(self):
        env = _make_valid_envelope(
            audit_mode="snapshot",
            parameters_version_max="fe4f9bea-4d73-4664-92fe-c2d677e0d82f",
            effective_parameters_hash="7b6ea46e7ec01780c2e9a9e3e1b2f940f8aa061da52eaf66487885fa8df3df76",
        )
        result = validate_reversion_envelope_shape(env)
        assert result.valid is True


class TestInvalidShapes:
    def test_non_dict_input_invalid(self):
        result = validate_reversion_envelope_shape("not a dict")
        assert result.valid is False
        assert any("must be dict" in n for n in result.notes)

    def test_missing_top_level_key(self):
        env = _make_valid_envelope()
        del env["ticker"]
        result = validate_reversion_envelope_shape(env)
        assert result.valid is False
        assert "ticker" in result.missing_top_level

    def test_invalid_bin_value(self):
        env = _make_valid_envelope(reversion_signal_bin="INVALID")
        result = validate_reversion_envelope_shape(env)
        assert result.valid is False
        assert any("reversion_signal_bin" in v for v in result.invalid_enum_values)


class TestAuditModeContract:
    def test_invalid_audit_mode_enum(self):
        env = _make_valid_envelope(audit_mode="something_else")
        result = validate_reversion_envelope_shape(env)
        assert result.valid is False
        assert result.invalid_audit_mode == "something_else"

    def test_standalone_with_pvm_present_violates(self):
        env = _make_valid_envelope(
            parameters_version_max="fe4f9bea-4d73-4664-92fe-c2d677e0d82f",
        )
        result = validate_reversion_envelope_shape(env)
        assert result.valid is False
        assert any("standalone" in v.lower() and "parameters_version_max" in v.lower()
                   for v in result.audit_mode_field_violations)

    def test_standalone_with_hash_present_violates(self):
        env = _make_valid_envelope(
            effective_parameters_hash="7b6ea46e7ec01780c2e9a9e3e1b2f940f8aa061da52eaf66487885fa8df3df76",
        )
        result = validate_reversion_envelope_shape(env)
        assert result.valid is False
        assert any("standalone" in v.lower() and "effective_parameters_hash" in v.lower()
                   for v in result.audit_mode_field_violations)

    def test_snapshot_missing_pvm_violates(self):
        env = _make_valid_envelope(
            audit_mode="snapshot",
            effective_parameters_hash="7b6ea46e7ec01780c2e9a9e3e1b2f940f8aa061da52eaf66487885fa8df3df76",
        )
        result = validate_reversion_envelope_shape(env)
        assert result.valid is False
        assert any("parameters_version_max" in v for v in result.audit_mode_field_violations)

    def test_snapshot_missing_hash_violates(self):
        env = _make_valid_envelope(
            audit_mode="snapshot",
            parameters_version_max="fe4f9bea-4d73-4664-92fe-c2d677e0d82f",
        )
        result = validate_reversion_envelope_shape(env)
        assert result.valid is False
        assert any("effective_parameters_hash" in v for v in result.audit_mode_field_violations)

    def test_snapshot_with_bad_uuid_format(self):
        env = _make_valid_envelope(
            audit_mode="snapshot",
            parameters_version_max="not-a-uuid",
            effective_parameters_hash="7b6ea46e7ec01780c2e9a9e3e1b2f940f8aa061da52eaf66487885fa8df3df76",
        )
        result = validate_reversion_envelope_shape(env)
        assert result.valid is False
        assert any("UUID" in v for v in result.audit_mode_field_violations)

    def test_snapshot_with_bad_hash_format(self):
        env = _make_valid_envelope(
            audit_mode="snapshot",
            parameters_version_max="fe4f9bea-4d73-4664-92fe-c2d677e0d82f",
            effective_parameters_hash="too-short",
        )
        result = validate_reversion_envelope_shape(env)
        assert result.valid is False
        assert any("64-char hex" in v for v in result.audit_mode_field_violations)


class TestReversionCellPlaceholder:
    def test_reversion_cell_non_null_fails(self):
        env = _make_valid_envelope(reversion_cell={"cell_size_pct": 1.5})
        result = validate_reversion_envelope_shape(env)
        assert result.valid is False
        assert result.reversion_cell_non_null is True


class TestInv36A:
    def test_unavailable_bin_without_reason_violates(self):
        env = _make_valid_envelope(
            reversion_signal_bin="MR_UNAVAILABLE",
            unavailable_reason=None,
            components=None,
            sub_signal_fires=None,
        )
        result = validate_reversion_envelope_shape(env)
        assert result.valid is False
        assert result.inv_3_6_a_violation is True
        assert result.missing_unavailable_reason is True

    def test_neutral_bin_with_reason_violates(self):
        env = _make_valid_envelope(unavailable_reason="insufficient_price_history")
        result = validate_reversion_envelope_shape(env)
        assert result.valid is False
        assert result.inv_3_6_a_violation is True

    def test_invalid_unavailable_reason_enum(self):
        env = _make_valid_envelope(
            reversion_signal_bin="MR_UNAVAILABLE",
            unavailable_reason="not_a_real_reason",
            components=None,
            sub_signal_fires=None,
        )
        result = validate_reversion_envelope_shape(env)
        assert result.valid is False
        assert result.invalid_unavailable_reason == "not_a_real_reason"


class TestInv36B:
    def test_oversold_bin_without_drawdown_fire_violates(self):
        env = _make_valid_envelope(
            reversion_signal_bin="MR_OVERSOLD",
            sub_signal_fires={
                "drawdown_threshold": False,  # MISSING required fire
                "rsi_oversold": True,
                "rsi_overbought": False,
                "bollinger_lower_extreme": True,
                "bollinger_upper_extreme": False,
            },
        )
        result = validate_reversion_envelope_shape(env)
        assert result.valid is False
        assert any("drawdown_threshold" in v for v in result.inv_3_6_b_violation)

    def test_overbought_bin_without_rsi_fire_violates(self):
        env = _make_valid_envelope(
            reversion_signal_bin="MR_OVERBOUGHT",
            sub_signal_fires={
                "drawdown_threshold": False,
                "rsi_oversold": False,
                "rsi_overbought": False,  # MISSING required fire
                "bollinger_lower_extreme": False,
                "bollinger_upper_extreme": True,
            },
        )
        result = validate_reversion_envelope_shape(env)
        assert result.valid is False
        assert any("rsi_overbought" in v for v in result.inv_3_6_b_violation)


class TestComponentsAndFiresPresence:
    def test_missing_components_key(self):
        env = _make_valid_envelope()
        del env["components"]["rsi_14"]
        result = validate_reversion_envelope_shape(env)
        assert result.valid is False
        assert "rsi_14" in result.missing_components_keys

    def test_missing_sub_signal_fires_key(self):
        env = _make_valid_envelope()
        del env["sub_signal_fires"]["drawdown_threshold"]
        result = validate_reversion_envelope_shape(env)
        assert result.valid is False
        assert "drawdown_threshold" in result.missing_sub_signal_fires
