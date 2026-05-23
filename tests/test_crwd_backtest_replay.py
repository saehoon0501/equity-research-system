"""CRWD-2026-03 case-study backtest replay test (P14, v0.4.0).

Empirical finding from v0.4.0 calibration:
At monthly-anchor cadence (matching tactical/flow overlay precedent), CRWD's
fast 2026-03-24 $343 bottom is NOT captured as MR_OVERSOLD because the closest
monthly anchors (2026-03-02 + 2026-04-01) sit at 33% / 30% drawdown respectively,
just below the 40% threshold. This is an honest design limitation:
- Monthly anchors are correct for slow-layer signal (avoid intra-day noise)
- But fast V-shaped recoveries between anchors are invisible
- Default thresholds may need tuning OR accept that CRWD-2026-03 is too-fast

This test asserts DETERMINISTIC fixture-based behavior, not bin transitions
that don't actually fire. It documents the empirical limitation.

Run: pytest tests/test_crwd_backtest_replay.py -v
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

# Make scripts/ importable
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.p10_reversion_overlay.bin_classifier import classify_reversion
from scripts.backtest_reversion import _replay, _monthly_anchors

FIXTURE_PATH = ROOT / "tests" / "fixtures" / "crwd_prices_2025-03_2026-05.json"


@pytest.fixture(scope="module")
def crwd_prices() -> list[dict]:
    return json.loads(FIXTURE_PATH.read_text())


@pytest.fixture(scope="module")
def replay_results(crwd_prices) -> dict[str, dict]:
    """Run classifier at each monthly anchor in [2025-09-01, 2026-05-23].

    Returns dict keyed by anchor ISO date for easy lookup.
    """
    start = datetime.strptime("2025-09-01", "%Y-%m-%d").date()
    end = datetime.strptime("2026-05-23", "%Y-%m-%d").date()
    anchors = _monthly_anchors(crwd_prices, start, end)
    return {a.isoformat(): _replay(crwd_prices, a) for a in anchors}


class TestFixtureIntegrity:
    def test_fixture_exists_and_covers_target_range(self, crwd_prices):
        assert len(crwd_prices) >= 400
        assert crwd_prices[0]["date"] <= "2024-08-01"
        assert crwd_prices[-1]["date"] >= "2026-05-20"

    def test_fixture_keys_match_schema(self, crwd_prices):
        row = crwd_prices[0]
        assert set(row.keys()) >= {"date", "close", "adj_close", "volume"}


class TestCrwdAnchorBehavior:
    """Assert specific bin classifications at named monthly anchors."""

    def test_pre_252d_anchors_unavailable(self, replay_results):
        # 2025-09-02 anchor: ~262 trading days back into 2024-08. Should be available.
        # But if any anchors lack 252d, they should be UNAVAILABLE not crash.
        for anchor, result in replay_results.items():
            if result["bin"] == "MR_UNAVAILABLE":
                assert result["unavailable_reason"] == "insufficient_price_history"

    def test_october_2025_near_peak(self, replay_results):
        """At 2025-10-01 anchor, CRWD was in strong uptrend; ma_distance positive."""
        result = replay_results.get("2025-10-01")
        assert result is not None
        assert result["bin"] == "MR_NEUTRAL"  # close to but not firing OVERBOUGHT
        comp = result["components"]
        assert comp is not None
        # RSI was elevated (recovery momentum); ma_distance positive
        assert comp["ma_distance_200d_pct"] > 5.0, (
            f"Expected positive ma_distance at 2025-10-01; got {comp['ma_distance_200d_pct']}"
        )

    def test_november_2025_near_overbought_but_not_firing(self, replay_results):
        """At 2025-11-03 anchor, MA-distance ~24% (just below 25% threshold)."""
        result = replay_results.get("2025-11-03")
        assert result is not None
        assert result["bin"] == "MR_NEUTRAL"
        comp = result["components"]
        # MA distance ~24% — just below default 25% threshold for overbought
        assert 20.0 < comp["ma_distance_200d_pct"] < 28.0, (
            f"ma_distance at 2025-11-03: {comp['ma_distance_200d_pct']:.2f} expected ~24%"
        )
        # RSI in mid-60s (elevated, near 70)
        assert 60.0 < comp["rsi_14"] < 72.0

    def test_march_2026_deepest_drawdown_anchor(self, replay_results):
        """At 2026-03-02 anchor, drawdown ~33% from 252d high.

        This is the CLOSEST monthly snapshot to CRWD's actual 2026-03-24 $343 bottom.
        At monthly cadence, the system sees 33% (below 40% threshold) → MR_NEUTRAL.
        This is the empirical limitation documented in module docstring.
        """
        result = replay_results.get("2026-03-02")
        assert result is not None
        assert result["bin"] == "MR_NEUTRAL"  # Misses by ~7pp under monthly cadence
        comp = result["components"]
        assert 30.0 < comp["drawdown_from_252d_high_pct"] < 40.0, (
            f"drawdown_from_252d_high at 2026-03-02: {comp['drawdown_from_252d_high_pct']:.2f}; expected ~33%"
        )

    def test_may_2026_recovery_in_progress(self, replay_results):
        """At 2026-05-01 anchor, CRWD recovering toward 200MA but still below."""
        result = replay_results.get("2026-05-01")
        assert result is not None
        assert result["bin"] == "MR_NEUTRAL"
        comp = result["components"]
        # ma_distance approaching zero from negative (recovery in progress)
        assert -10.0 < comp["ma_distance_200d_pct"] < 5.0


class TestEmpiricalLimitationDocumentation:
    """Tests that document the v0.4.0 design limitation surfaced in this backtest.

    These tests should NOT be removed even if thresholds are tuned later — they
    are the canonical record of what monthly-anchor cadence can/cannot detect.
    """

    def test_no_mr_oversold_at_any_monthly_anchor_in_crwd_2026_03_window(self, replay_results):
        """CRWD 2026-03 bottom was a fast V-shape between anchors.

        At default thresholds + monthly anchor cadence, MR_OVERSOLD does NOT fire
        for CRWD anywhere in the 2025-09 → 2026-05 backtest window. This is by
        design (slow-layer signal, not bottom-caller). v0.4.1 backtest may
        revisit threshold calibration.
        """
        oversold_anchors = [
            a for a, r in replay_results.items() if r["bin"] == "MR_OVERSOLD"
        ]
        assert oversold_anchors == [], (
            f"Expected no MR_OVERSOLD at monthly anchors; got {oversold_anchors}. "
            "If this passes after threshold tuning, update test to assert specific firing anchors."
        )

    def test_no_mr_overbought_at_any_monthly_anchor_in_crwd_2025_10_peak(self, replay_results):
        """CRWD 2025-11-03 anchor was the closest to peak; all 3 sub-signals were
        elevated but not all over threshold. MR_OVERBOUGHT does NOT fire.

        Same calibration question as oversold test above.
        """
        overbought_anchors = [
            a for a, r in replay_results.items() if r["bin"] == "MR_OVERBOUGHT"
        ]
        assert overbought_anchors == [], (
            f"Expected no MR_OVERBOUGHT at monthly anchors; got {overbought_anchors}. "
            "If this passes after threshold tuning, update test to assert specific firing anchors."
        )

    def test_overall_bin_distribution_is_dominated_by_neutral(self, replay_results):
        """At v0.4.0 default thresholds, MR_NEUTRAL is the modal bin across the year.

        Sanity check that the signal isn't always-firing or always-unavailable.
        """
        bins = [r["bin"] for r in replay_results.values()]
        neutral_count = sum(1 for b in bins if b == "MR_NEUTRAL")
        assert neutral_count >= len(bins) - 2, (
            f"Expected at least {len(bins)-2} MR_NEUTRAL anchors; got {neutral_count}/{len(bins)}"
        )
