"""Horizon mapping — signal_type -> primary_horizon -> column. No t_plus_365."""

from __future__ import annotations

import pytest

from src.calibration import horizon as H


class TestPrimaryHorizon:
    def test_tactical_and_flow_map_to_30d(self):
        assert H.primary_horizon_for("tactical") == "30d"
        assert H.primary_horizon_for("flow") == "30d"

    def test_fundamental_default_90d(self):
        assert H.primary_horizon_for("fundamental") == "90d"

    def test_case_insensitive(self):
        assert H.primary_horizon_for("TACTICAL") == "30d"
        assert H.primary_horizon_for("  Fundamental ") == "90d"

    def test_unknown_signal_raises(self):
        with pytest.raises(ValueError):
            H.primary_horizon_for("astrology")


class TestHorizonsFor:
    def test_tactical_single_horizon(self):
        assert H.horizons_for("tactical") == ("30d",)

    def test_fundamental_multi_horizon_90d_and_1y(self):
        assert H.horizons_for("fundamental") == ("90d", "1y")


class TestColumnMapping:
    def test_legal_horizons_are_exactly_three(self):
        assert H.LEGAL_HORIZONS == ("30d", "90d", "1y")

    @pytest.mark.parametrize(
        "horizon,ret_col",
        [
            ("30d", "t_plus_30d_return"),
            ("90d", "t_plus_90d_return"),
            ("1y", "t_plus_1y_return"),
        ],
    )
    def test_return_column_resolves(self, horizon, ret_col):
        assert H.return_column_for(horizon) == ret_col

    def test_no_t_plus_365_anywhere(self):
        # The 365-day window IS '1y'; there must be no 't_plus_365' string.
        for h in H.LEGAL_HORIZONS:
            for col in H.columns_for(h):
                assert "365" not in col
        assert H.return_column_for("1y") == "t_plus_1y_return"

    def test_1y_window_is_365_calendar_days(self):
        assert H.window_days_for("1y") == 365
        assert H.window_days_for("30d") == 30
        assert H.window_days_for("90d") == 90

    def test_illegal_horizon_raises_no_365_key(self):
        with pytest.raises(ValueError):
            H.columns_for("365")
        with pytest.raises(ValueError):
            H.return_column_for("3y")

    def test_column_triple_shape(self):
        ret, bench, delta = H.columns_for("90d")
        assert (ret, bench, delta) == (
            "t_plus_90d_return",
            "benchmark_return_90d",
            "delta_vs_benchmark_90d",
        )
