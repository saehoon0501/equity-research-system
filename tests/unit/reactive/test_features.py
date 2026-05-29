"""Inner-ring unit tests for the daily-bar feature adapter (`src.reactive.features`).

Task 2.1 / 3.2. Covers (design §Feature adapter, §Testing Strategy):
- core→vote mapping incl. the reversion **sign-mirror** (oversold→+1, overbought→−1),
- `trend_strength == abs(flow_vote)`,
- ATR-normalization of magnitude features (Req 1.2),
- insufficient-history → `FeatureFailure(insufficient_history)`,
- degenerate / zero-ATR → `FeatureFailure(degenerate_features)`,
- unavailable-core abstain (→ 0 vote) — incl. tactical `rf_yield_pct is None`,
- exclusion of intraday-microstructure / fundamental inputs (by construction),
- votes provably ∈ [−1,+1].

No mocks, no LLM/MCP/DB (P14, R8). Synthetic daily bars only, constructed so the
real reused cores (`src.overlays.*`, `src.micro.indicators.atr`) hit known bins.
"""

from __future__ import annotations

import pytest

from src.overlays.flow.bin_classifier import classify_flow
from src.overlays.reversion.bin_classifier import classify_reversion
from src.overlays.tactical.bin_classifier import classify
from src.reactive.features import FeatureSet, compute_features
from src.reactive.types import Bar, FeatureFailure

# --- Synthetic-bar builders -------------------------------------------------

LOOKBACK = 252  # the longest reused window (252d drawdown / 200d MA / 12mo momentum)


def _bar(close: float, *, high: float | None = None, low: float | None = None) -> Bar:
    """A daily OHLCV bar with a small symmetric intrabar range (for non-zero ATR)."""
    hi = high if high is not None else close * 1.01
    lo = low if low is not None else close * 0.99
    return {"open": close, "high": hi, "low": lo, "close": close, "volume": 1_000_000.0}


def _bars_from_closes(closes: list[float]) -> list[Bar]:
    return [_bar(c) for c in closes]


def _flat_bars(value: float, n: int) -> list[Bar]:
    """n bars with all OHLC == value → zero true range → atr == 0 (degenerate)."""
    return [{"open": value, "high": value, "low": value, "close": value, "volume": 1.0}
            for _ in range(n)]


def _steady_uptrend(n: int, start: float = 100.0, step: float = 0.5) -> list[float]:
    """Monotone rising closes — strong positive momentum / above MAs / upper Donchian."""
    return [start + step * i for i in range(n)]


def _steady_downtrend(n: int, start: float = 200.0, step: float = 0.5) -> list[float]:
    return [start - step * i for i in range(n)]


def _flat_closes(value: float, n: int) -> list[float]:
    return [value for _ in range(n)]


def _oversold_closes() -> list[float]:
    """A 252-bar series engineered to trip the reversion OVERSOLD AND-gate:
    drawdown_from_252d_high >= 40% AND rsi_14 <= 30 AND bollinger <= -2sigma.

    Strategy (verified against the real `classify_reversion`): high plateau →
    moderate decline → a flat low run (small 20d stdev) → ONE sharp gap-down on
    the final bar so the close sits far below the 20d MA in sigma terms
    (bb ≤ −2σ) while the deep drawdown (>40%) and all-negative recent deltas
    (rsi ≈ 0) also fire.
    """
    plateau = [200.0] * 40
    decline = [200.0 - (80.0 * (i + 1) / 150) for i in range(150)]  # → ~120
    low_run = [decline[-1]] * (LOOKBACK - 40 - 150 - 1)  # tiny recent stdev
    final = [low_run[-1] * 0.80]  # sharp single drop on the last bar
    return plateau + decline + low_run + final


def _overbought_closes() -> list[float]:
    """A 252-bar series engineered to trip the reversion OVERBOUGHT AND-gate:
    rsi_14 >= 70 AND bollinger >= +2sigma AND ma_distance_200d >= 25%.

    Strategy (verified against the real `classify_reversion`): low plateau →
    moderate rise → a flat high run → ONE sharp gap-up on the final bar so the
    close sits far above both the 20d MA (bb ≥ +2σ) and the 200d MA
    (ma_distance ≥ 25%), with all-positive recent deltas (rsi ≈ 100).
    """
    plateau = [100.0] * 40
    rise = [100.0 + (20.0 * (i + 1) / 150) for i in range(150)]  # → ~120
    high_run = [rise[-1]] * (LOOKBACK - 40 - 150 - 1)
    final = [high_run[-1] * 1.45]  # sharp single jump on the last bar
    return plateau + rise + high_run + final


# --- RED-phase / smoke: the adapter exists and returns the right union ------


def test_compute_features_returns_featureset_on_sufficient_history():
    closes = _steady_uptrend(LOOKBACK)
    bars = _bars_from_closes(closes)
    spy = _steady_uptrend(LOOKBACK, start=300.0, step=0.2)
    result = compute_features(bars, spy, rf_yield_pct=4.0)
    assert isinstance(result, FeatureSet)


# --- Vote mapping: tactical bin → ±1/0 --------------------------------------


def test_tactical_positive_bin_maps_to_plus_one():
    # Ticker strongly outperforms SPY and rf → tactical "positive" → +1.
    ticker = _steady_uptrend(LOOKBACK, start=100.0, step=1.0)
    spy = _flat_closes(300.0, LOOKBACK)  # SPY flat → ticker relative return high
    bars = _bars_from_closes(ticker)
    # Confirm the real core produces the bin we expect (guards a vacuous test).
    assert classify(ticker, spy, 4.0)["bin"] == "positive"
    result = compute_features(bars, spy, rf_yield_pct=4.0)
    assert isinstance(result, FeatureSet)
    assert result.trend_vote == 1.0


def test_tactical_negative_bin_maps_to_minus_one():
    ticker = _steady_downtrend(LOOKBACK, start=200.0, step=0.4)
    spy = _flat_closes(300.0, LOOKBACK)
    bars = _bars_from_closes(ticker)
    assert classify(ticker, spy, 4.0)["bin"] == "negative"
    result = compute_features(bars, spy, rf_yield_pct=4.0)
    assert isinstance(result, FeatureSet)
    assert result.trend_vote == -1.0


def test_tactical_unavailable_rf_none_abstains_to_zero():
    # rf_yield_pct=None makes tactical "unavailable" (rf_resolver_staleness) but
    # history is sufficient → NOT a failure; tactical abstains → trend_vote 0.
    ticker = _steady_uptrend(LOOKBACK, start=100.0, step=1.0)
    spy = _flat_closes(300.0, LOOKBACK)
    bars = _bars_from_closes(ticker)
    assert classify(ticker, spy, None)["bin"] == "unavailable"
    result = compute_features(bars, spy, rf_yield_pct=None)
    assert isinstance(result, FeatureSet)
    assert result.trend_vote == 0.0


# --- Vote mapping: flow composite passed through ----------------------------


def test_flow_vote_is_composite_score_normalized_passthrough():
    ticker = _steady_uptrend(LOOKBACK, start=100.0, step=1.0)
    spy = _steady_uptrend(LOOKBACK, start=300.0, step=1.0)
    bars = _bars_from_closes(ticker)
    expected = classify_flow(ticker, spy)["components"]["composite_score_normalized"]
    result = compute_features(bars, spy, rf_yield_pct=4.0)
    assert isinstance(result, FeatureSet)
    assert result.flow_vote == expected
    assert -1.0 <= result.flow_vote <= 1.0


def test_flow_flat_series_composite_zero():
    # NOTE: post-history-gate, the flow core's `components is None` (unavailable)
    # path is UNREACHABLE — flow needs >=252 SPY, the same threshold the global
    # insufficient_history gate enforces, so a short SPY fails globally first.
    # The reachable abstain path is tactical (rf=None), covered above. Here we
    # assert the flat-series passthrough: all flow sub-signal votes 0 → composite
    # exactly 0 → flow_vote 0 (NOT an abstain, a genuine 0 composite).
    ticker = _flat_closes(100.0, LOOKBACK)
    spy = _flat_closes(300.0, LOOKBACK)
    bars = _bars_from_closes(ticker)
    assert classify_flow(ticker, spy)["components"]["composite_score_normalized"] == 0.0
    result = compute_features(bars, spy, rf_yield_pct=4.0)
    assert isinstance(result, FeatureSet)
    assert result.flow_vote == 0.0


# --- Vote mapping: reversion SIGN-MIRROR (load-bearing) ---------------------


def test_reversion_sign_mirror_oversold_is_bullish_plus_one():
    """OVERSOLD ⇒ expect bounce ⇒ +1 (LONG-favoring). This test FAILS if the sign
    is inverted to −1. First assert the real core actually returns MR_OVERSOLD so
    the sign assertion is not vacuous."""
    closes = _oversold_closes()
    bars = _bars_from_closes(closes)
    spy = _flat_closes(300.0, LOOKBACK)
    assert classify_reversion(closes)["bin"] == "MR_OVERSOLD"  # not vacuous
    result = compute_features(bars, spy, rf_yield_pct=4.0)
    assert isinstance(result, FeatureSet)
    assert result.meanrev_vote == 1.0, "OVERSOLD must map to +1 (contrarian/bullish)"


def test_reversion_sign_mirror_overbought_is_bearish_minus_one():
    closes = _overbought_closes()
    bars = _bars_from_closes(closes)
    spy = _flat_closes(300.0, LOOKBACK)
    assert classify_reversion(closes)["bin"] == "MR_OVERBOUGHT"  # not vacuous
    result = compute_features(bars, spy, rf_yield_pct=4.0)
    assert isinstance(result, FeatureSet)
    assert result.meanrev_vote == -1.0, "OVERBOUGHT must map to −1 (contrarian/bearish)"


def test_reversion_neutral_maps_to_zero():
    closes = _steady_uptrend(LOOKBACK, start=100.0, step=0.1)  # mild → MR_NEUTRAL
    bars = _bars_from_closes(closes)
    spy = _flat_closes(300.0, LOOKBACK)
    assert classify_reversion(closes)["bin"] == "MR_NEUTRAL"
    result = compute_features(bars, spy, rf_yield_pct=4.0)
    assert isinstance(result, FeatureSet)
    assert result.meanrev_vote == 0.0


# --- trend_strength == abs(flow_vote) ---------------------------------------


def test_trend_strength_equals_abs_flow_vote():
    ticker = _steady_uptrend(LOOKBACK, start=100.0, step=1.0)
    spy = _steady_uptrend(LOOKBACK, start=300.0, step=1.0)
    bars = _bars_from_closes(ticker)
    result = compute_features(bars, spy, rf_yield_pct=4.0)
    assert isinstance(result, FeatureSet)
    assert result.trend_strength == abs(result.flow_vote)
    assert 0.0 <= result.trend_strength <= 1.0


# --- ATR normalization of magnitude features (Req 1.2) ----------------------


def test_atr_normalized_magnitudes_are_magnitude_over_atr():
    """Req 1.2: magnitude features (drawdown, MA-distance) expressed in daily-ATR
    units. Assert the normalized keys equal raw-magnitude / atr."""
    from src.micro.indicators import atr as atr_fn
    from src.micro.indicators import sma

    closes = _oversold_closes()  # a real, sizeable drawdown to normalize
    bars = _bars_from_closes(closes)
    spy = _flat_closes(300.0, LOOKBACK)
    result = compute_features(bars, spy, rf_yield_pct=4.0)
    assert isinstance(result, FeatureSet)

    raw = result.raw
    atr_val = atr_fn(bars, 14)
    assert atr_val is not None and atr_val > 0
    assert raw["atr"] == atr_val

    # drawdown in absolute price terms = 252d_high − close; normalized = /atr.
    high_252 = raw["252d_high"]
    close = closes[-1]
    expected_dd_atr = (high_252 - close) / atr_val
    assert raw["drawdown_atr"] == pytest.approx(expected_dd_atr)

    # ma-distance in absolute price terms = close − sma200; normalized = /atr.
    sma200 = sma(closes, 200)
    expected_ma_atr = (close - sma200) / atr_val
    assert raw["ma_distance_atr"] == pytest.approx(expected_ma_atr)


def test_raw_carries_reused_continuous_components_for_substrate():
    """design 161/223: `raw` exposes the reversion percent components, flow
    composite, tactical bin, and atr for the telemetry substrate."""
    closes = _oversold_closes()
    bars = _bars_from_closes(closes)
    spy = _flat_closes(300.0, LOOKBACK)
    result = compute_features(bars, spy, rf_yield_pct=4.0)
    assert isinstance(result, FeatureSet)
    raw = result.raw
    for key in (
        "rsi_14",
        "drawdown_from_252d_high_pct",
        "bollinger_band_position",
        "ma_distance_200d_pct",
        "flow_composite",
        "tactical_bin",
        "atr",
    ):
        assert key in raw, f"raw missing substrate key {key!r}"


# --- Failure ownership: insufficient_history / degenerate_features ----------


def test_short_ticker_history_returns_insufficient_history():
    closes = _steady_uptrend(LOOKBACK - 1)  # one short of the longest window
    bars = _bars_from_closes(closes)
    spy = _steady_uptrend(LOOKBACK)
    result = compute_features(bars, spy, rf_yield_pct=4.0)
    assert isinstance(result, FeatureFailure)
    assert result.reason == "insufficient_history"


def test_short_spy_history_returns_insufficient_history():
    closes = _steady_uptrend(LOOKBACK)
    bars = _bars_from_closes(closes)
    spy = _steady_uptrend(LOOKBACK - 1)  # SPY too short for the relative signals
    result = compute_features(bars, spy, rf_yield_pct=4.0)
    assert isinstance(result, FeatureFailure)
    assert result.reason == "insufficient_history"


def test_zero_atr_returns_degenerate_features():
    # Flat OHLC → every true range is 0 → atr == 0 → cannot ATR-normalize.
    bars = _flat_bars(100.0, LOOKBACK)
    spy = _flat_closes(300.0, LOOKBACK)
    result = compute_features(bars, spy, rf_yield_pct=4.0)
    assert isinstance(result, FeatureFailure)
    assert result.reason == "degenerate_features"


def test_malformed_bar_missing_key_returns_degenerate_not_raise():
    # The "never raise" contract is unconditional and design line 177 assigns
    # Bar-key validation to this boundary. A bar with high+low but no `close`
    # survives `_closes`' high/low-only filter (len stays 252) and would KeyError
    # in `_atr` — the boundary guard must catch it as degenerate_features.
    bars = _bars_from_closes(_steady_uptrend(LOOKBACK + 1))
    bars[100] = {"open": 100.0, "high": 101.0, "low": 99.0, "volume": 1.0}  # no close
    spy = _steady_uptrend(LOOKBACK + 1)
    result = compute_features(bars, spy, rf_yield_pct=4.0)  # must not raise
    assert isinstance(result, FeatureFailure)
    assert result.reason == "degenerate_features"


def test_failures_never_raise():
    # Both failure paths must return a FeatureFailure, never raise.
    short = compute_features(_bars_from_closes(_steady_uptrend(10)),
                             _steady_uptrend(10), rf_yield_pct=4.0)
    assert isinstance(short, FeatureFailure)
    degenerate = compute_features(_flat_bars(50.0, LOOKBACK),
                                  _flat_closes(300.0, LOOKBACK), rf_yield_pct=4.0)
    assert isinstance(degenerate, FeatureFailure)


# --- Votes provably in range ------------------------------------------------


def test_all_votes_within_unit_interval():
    for closes, spy in (
        (_steady_uptrend(LOOKBACK), _steady_downtrend(LOOKBACK, start=400.0)),
        (_steady_downtrend(LOOKBACK), _steady_uptrend(LOOKBACK, start=100.0)),
        (_oversold_closes(), _flat_closes(300.0, LOOKBACK)),
        (_overbought_closes(), _flat_closes(300.0, LOOKBACK)),
    ):
        bars = _bars_from_closes(closes)
        result = compute_features(bars, spy, rf_yield_pct=4.0)
        assert isinstance(result, FeatureSet)
        for v in (result.trend_vote, result.flow_vote, result.meanrev_vote):
            assert -1.0 <= v <= 1.0
        assert 0.0 <= result.trend_strength <= 1.0


# --- Determinism (R8.1) -----------------------------------------------------


def test_determinism_identical_inputs_identical_featureset():
    closes = _oversold_closes()
    bars = _bars_from_closes(closes)
    spy = _flat_closes(300.0, LOOKBACK)
    a = compute_features(bars, spy, rf_yield_pct=4.0)
    b = compute_features(bars, spy, rf_yield_pct=4.0)
    assert a == b
