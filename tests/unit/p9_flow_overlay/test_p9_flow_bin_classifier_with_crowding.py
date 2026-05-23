"""v0.3 tests for classify_flow() with the optional crowding_warning input.

Includes the critical BACK-COMPAT TESTS:
- classify_flow() without crowding_warning kwarg: bit-identical to v0.2
- classify_flow() with crowding_warning AND gamma_regime both None: bit-identical to v0.1
- classify_flow() with crowding_warning={warning: False}: composite identical to no-crowding-kwarg
  (asymmetric signal: warning=False contributes 0, never alters composite numerator)
"""
from __future__ import annotations

import pytest

from src.p9_flow_overlay.bin_classifier import (
    MAX_COMPOSITE_SCORE_V01,
    MAX_COMPOSITE_SCORE_V02,
    MAX_COMPOSITE_SCORE_V03,
    classify_flow,
    _crowding_score,
)
from tests.unit.p9_flow_overlay.test_p9_flow_bin_classifier import _series_with_trend  # noqa: F401


# ---------- _crowding_score helper ----------


def test_crowding_score_none_returns_zero():
    assert _crowding_score(None) == 0


def test_crowding_score_warning_true_returns_neg_one():
    assert _crowding_score({"warning": True}) == -1


def test_crowding_score_warning_false_returns_zero():
    assert _crowding_score({"warning": False}) == 0


def test_crowding_score_missing_warning_returns_zero():
    # Defensive: missing key => 0 (asymmetric — never +1)
    assert _crowding_score({}) == 0


def test_crowding_score_non_true_truthy_returns_zero():
    # Strict True check — "true" string, 1, etc. all return 0
    assert _crowding_score({"warning": "true"}) == 0
    assert _crowding_score({"warning": 1}) == 0


# ---------- Back-compat: bit-identical v0.2 when crowding_warning=None ----------


def test_no_crowding_kwarg_identical_to_v02():
    """Calling without crowding_warning => bit-identical to v0.2 behavior."""
    ticker = _series_with_trend(100.0, 130.0)
    spy = _series_with_trend(400.0, 460.0)

    a = classify_flow(ticker, spy)  # v0.2 path
    b = classify_flow(ticker, spy, crowding_warning=None)  # explicit None

    assert a["bin"] == b["bin"]
    assert a["components"] == b["components"]
    # Confirm no crowding-related keys leaked when crowding_warning=None
    assert "crowding" not in a["components"]
    assert "crowding_score" not in a["components"]


def test_no_kwargs_identical_to_v01_shape():
    """v0.1 back-compat: with neither gamma_regime nor crowding, components dict has only 3 v0.1 keys."""
    ticker = _series_with_trend(100.0, 130.0)
    spy = _series_with_trend(400.0, 460.0)

    out = classify_flow(ticker, spy)
    assert set(out["components"].keys()) == {
        "ticker_score",
        "market_score",
        "composite_score_normalized",
    }


# ---------- Asymmetric -1 contribution ----------


def test_warning_true_lowers_composite_by_inverse_max():
    """warning=True must subtract exactly 1 from composite numerator (no gamma_regime)."""
    ticker = _series_with_trend(100.0, 1000.0)  # max bullish
    spy = _series_with_trend(400.0, 4000.0)

    no_crowd = classify_flow(ticker, spy)
    with_warn = classify_flow(ticker, spy, crowding_warning={"warning": True})

    # ticker_score and market_score should be identical
    assert no_crowd["components"]["ticker_score"] == with_warn["components"]["ticker_score"]
    assert no_crowd["components"]["market_score"] == with_warn["components"]["market_score"]

    # composite should drop by exactly 1 / MAX_COMPOSITE_SCORE_V01
    expected_drop = 1.0 / MAX_COMPOSITE_SCORE_V01
    actual_drop = (
        no_crowd["components"]["composite_score_normalized"]
        - with_warn["components"]["composite_score_normalized"]
    )
    assert actual_drop == pytest.approx(expected_drop)

    # New v0.3 keys must be present when crowding_warning is provided
    assert with_warn["components"]["crowding_score"] == -1
    assert with_warn["components"]["crowding"] == {"warning": True}


def test_warning_false_does_not_affect_composite():
    """warning=False is bit-identical to no-warning in composite numerator."""
    ticker = _series_with_trend(100.0, 130.0)
    spy = _series_with_trend(400.0, 460.0)

    no_crowd = classify_flow(ticker, spy)
    with_no_warn = classify_flow(ticker, spy, crowding_warning={"warning": False})

    assert (
        no_crowd["components"]["composite_score_normalized"]
        == with_no_warn["components"]["composite_score_normalized"]
    )
    # But crowding block IS emitted when kwarg provided
    assert with_no_warn["components"]["crowding_score"] == 0
    assert with_no_warn["components"]["crowding"] == {"warning": False}


# ---------- Interaction with gamma_regime ----------


def test_warning_true_with_gamma_positive_uses_v02_divisor():
    """When both gamma_regime and crowding_warning provided, divisor = V02 (9)."""
    ticker = _series_with_trend(100.0, 1000.0)
    spy = _series_with_trend(400.0, 4000.0)
    gamma = {"bin": "positive"}

    out = classify_flow(ticker, spy, gamma_regime=gamma, crowding_warning={"warning": True})
    # ceiling preserved at +1 (gamma adds +1; crowding subtracts 1 → cancels)
    # numerator = 4 + 4 + 1 - 1 = 8, divisor = 9 → composite = 8/9
    assert out["components"]["composite_score_normalized"] == pytest.approx(8 / 9)
    assert out["components"]["gamma_score"] == 1
    assert out["components"]["crowding_score"] == -1


def test_max_v03_equals_max_v02():
    """Ceiling preservation invariant: MAX_COMPOSITE_SCORE_V03 == MAX_COMPOSITE_SCORE_V02."""
    assert MAX_COMPOSITE_SCORE_V03 == MAX_COMPOSITE_SCORE_V02 == 9


# ---------- Floor extends but ceiling preserved ----------


def test_full_bearish_with_crowding_at_floor():
    """Max bearish ticker + market + gamma_negative + crowding=True = composite floor."""
    ticker = _series_with_trend(1000.0, 100.0)  # max bearish
    spy = _series_with_trend(4000.0, 400.0)
    gamma_neg = {"bin": "negative"}

    out = classify_flow(
        ticker, spy, gamma_regime=gamma_neg, crowding_warning={"warning": True}
    )
    # numerator = -4 - 4 - 1 - 1 = -10, divisor = 9 → composite = -10/9 ≈ -1.111
    # (floor extends past -1.0 — asymmetric design accepts this; bin clamps to negative)
    assert out["components"]["composite_score_normalized"] == pytest.approx(-10 / 9)
    assert out["bin"] == "negative"


def test_full_bullish_with_warning_does_not_exceed_ceiling():
    """Max bullish + gamma_positive + warning=True: ceiling preserved at exactly +1 minus 1/9."""
    ticker = _series_with_trend(100.0, 1000.0)
    spy = _series_with_trend(400.0, 4000.0)
    gamma_pos = {"bin": "positive"}

    out = classify_flow(
        ticker, spy, gamma_regime=gamma_pos, crowding_warning={"warning": True}
    )
    # numerator = 4 + 4 + 1 - 1 = 8, divisor = 9
    assert out["components"]["composite_score_normalized"] == pytest.approx(8 / 9)
    # max possible (warning=False) would be 9/9 = 1.0 — confirm asymmetry
    out_no_warn = classify_flow(
        ticker, spy, gamma_regime=gamma_pos, crowding_warning={"warning": False}
    )
    assert out_no_warn["components"]["composite_score_normalized"] == pytest.approx(1.0)
