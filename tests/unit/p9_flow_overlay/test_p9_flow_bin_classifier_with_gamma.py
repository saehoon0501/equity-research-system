"""v0.2 tests for classify_flow() with the optional gamma_regime input.

Includes the critical BACK-COMPAT TEST: calling classify_flow() without the
gamma_regime kwarg must produce bit-identical results to v0.1 (same composite
score, same bin, same component fields the v0.1 envelope contract requires).
"""

import pytest

from src.p9_flow_overlay.bin_classifier import (
    LOOKBACK_TRADING_DAYS,
    MAX_COMPOSITE_SCORE_V01,
    MAX_COMPOSITE_SCORE_V02,
    classify_flow,
    _gamma_score,
)
from tests.unit.p9_flow_overlay.test_p9_flow_bin_classifier import _series_with_trend  # noqa: F401


# ---------- _gamma_score helper ----------


def test_gamma_score_none_returns_zero():
    assert _gamma_score(None) == 0


def test_gamma_score_positive_bin():
    assert _gamma_score({"bin": "positive"}) == 1


def test_gamma_score_negative_bin():
    assert _gamma_score({"bin": "negative"}) == -1


def test_gamma_score_neutral_bin():
    assert _gamma_score({"bin": "neutral"}) == 0


def test_gamma_score_unknown_bin_defaults_zero():
    assert _gamma_score({"bin": "unavailable"}) == 0
    assert _gamma_score({"bin": "nonsense"}) == 0
    assert _gamma_score({}) == 0  # missing bin key


# ---------- v0.1 back-compat ----------


def test_back_compat_no_gamma_regime_identical_to_v01():
    """Calling without gamma_regime kwarg → bit-identical to v0.1.

    Specifically: composite_score_normalized uses MAX_COMPOSITE_SCORE_V01 (8),
    not V02 (9), AND the components dict shape matches v0.1 exactly — no
    `gamma_score` or `gamma_regime` keys present.
    """
    ticker = _series_with_trend(100.0, 130.0)
    spy = _series_with_trend(400.0, 460.0)

    result_v01_style = classify_flow(ticker, spy)
    # When no gamma_regime, divisor is V01 (8)
    expected_composite = (
        result_v01_style["components"]["ticker_score"]
        + result_v01_style["components"]["market_score"]
    ) / MAX_COMPOSITE_SCORE_V01
    assert result_v01_style["components"]["composite_score_normalized"] == pytest.approx(expected_composite)
    # Bit-identical v0.1 components dict shape: ONLY the 3 v0.1 keys; no gamma_* keys.
    assert set(result_v01_style["components"].keys()) == {
        "ticker_score",
        "market_score",
        "composite_score_normalized",
    }


def test_explicit_none_gamma_regime_same_as_omitted():
    """Passing gamma_regime=None explicitly = same as not passing at all."""
    ticker = _series_with_trend(100.0, 130.0)
    spy = _series_with_trend(400.0, 460.0)
    a = classify_flow(ticker, spy)
    b = classify_flow(ticker, spy, gamma_regime=None)
    assert a["bin"] == b["bin"]
    assert a["components"]["composite_score_normalized"] == b["components"]["composite_score_normalized"]


# ---------- v0.2 with gamma_regime ----------


def test_gamma_positive_amplifies_composite():
    """With ticker+SPY at +4/+4 (full bullish), adding positive gamma vote → ticker_score+market_score+gamma_score = 9/9 = 1.0."""
    ticker = _series_with_trend(100.0, 1000.0)  # +900% — definitively bullish
    spy = _series_with_trend(400.0, 4000.0)
    gamma = {"bin": "positive"}
    result = classify_flow(ticker, spy, gamma_regime=gamma)
    assert result["components"]["ticker_score"] == 4
    assert result["components"]["market_score"] == 4
    assert result["components"]["gamma_score"] == 1
    # composite = (4+4+1)/9 = 1.0
    assert result["components"]["composite_score_normalized"] == pytest.approx(1.0)
    assert result["bin"] == "positive"


def test_gamma_negative_dampens_composite():
    """Strong uptrend in price (+8/8) with negative gamma → composite = 7/9 ≈ 0.78."""
    ticker = _series_with_trend(100.0, 1000.0)
    spy = _series_with_trend(400.0, 4000.0)
    gamma = {"bin": "negative"}
    result = classify_flow(ticker, spy, gamma_regime=gamma)
    assert result["components"]["gamma_score"] == -1
    # composite = (4+4-1)/9 ≈ 0.778
    assert result["components"]["composite_score_normalized"] == pytest.approx(7.0 / 9.0)
    assert result["bin"] == "positive"  # still positive (0.778 > 0.5 threshold)


def test_gamma_regime_block_carried_through_to_components():
    """The gamma_regime dict is stored verbatim in components for downstream consumers."""
    ticker = _series_with_trend(100.0, 130.0)
    spy = _series_with_trend(400.0, 460.0)
    gamma = {
        "bin": "positive",
        "net_gex_at_spot": 5.4e9,
        "zero_gamma_distance_pct": -0.034,
        "dte_bucket_decomp": {"0DTE": 1.2e9, "1-7d": 3.0e9, "8-30d": 1.2e9},
        "dealer_sign_convention": "spotgamma",
        "regime_flip_signal_method": "zero_gamma_inflection",
    }
    result = classify_flow(ticker, spy, gamma_regime=gamma)
    assert result["components"]["gamma_regime"] == gamma


def test_unavailable_bin_when_ticker_history_short():
    """Insufficient price history short-circuits before gamma_regime check (unchanged from v0.1)."""
    short_series = [100.0] * 50
    spy = _series_with_trend(400.0, 460.0)
    gamma = {"bin": "positive"}  # would otherwise contribute
    result = classify_flow(short_series, spy, gamma_regime=gamma)
    assert result["bin"] == "unavailable"
    assert result["unavailable_reason"] == "insufficient_price_history"
    assert result["components"] is None  # nothing computed


# ---------- Boundary math ----------


def test_max_composite_constants():
    """V01 = 8, V02 = 9. Used to verify which divisor classify_flow picks."""
    assert MAX_COMPOSITE_SCORE_V01 == 8
    assert MAX_COMPOSITE_SCORE_V02 == 9
