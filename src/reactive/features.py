"""Reactive Signal Model: the daily-bar feature adapter (`features`).

Task 2.1. Reduces a daily-bar history (plus SPY closes + the risk-free yield) to
the days-to-weeks family votes by **reusing** the existing deterministic overlay
cores and the ATR indicator — building no new feature math where a tested core
exists (design §Existing Architecture Analysis, R1):

- trend   (tactical / Antonacci): `src.overlays.tactical.bin_classifier.classify`
- flow    (CTA-proximity):        `src.overlays.flow.bin_classifier.classify_flow`
- meanrev (reversion):            `src.overlays.reversion.bin_classifier.classify_reversion`
- ATR + closes:                   `src.micro.indicators.atr` / `.closes` / `.sma`

Each core's heterogeneous output is mapped to a **signed directional vote ∈ [−1,+1]**
under the documented convention (`+1 ⇒ favors LONG`, `−1 ⇒ favors SHORT`):

| family  | core output                              | → vote                                  |
|---------|------------------------------------------|-----------------------------------------|
| trend   | `bin ∈ {positive,neutral,negative,unavailable}` | positive→+1, neutral→0, negative→−1, unavailable→0 |
| flow    | `components.composite_score_normalized ∈ [−1,+1]` | direct pass-through (already signed/in-range) |
| meanrev | `bin ∈ {MR_OVERSOLD,MR_NEUTRAL,MR_OVERBOUGHT,MR_UNAVAILABLE}` | **MR_OVERSOLD→+1** (oversold⇒bounce⇒bullish, CONTRARIAN), **MR_OVERBOUGHT→−1**, MR_NEUTRAL→0, MR_UNAVAILABLE→0 |

`trend_strength ∈ [0,1] = abs(flow_vote)` — the continuous trend-conviction signal
used downstream (`signal_model`) to dampen mean-reversion (design §Feature adapter).

Magnitude-type raw features (drawdown, MA-distance) are additionally expressed in
**daily-ATR units** for the substrate (Req 1.2). The reused percent components are
kept verbatim in `raw` for telemetry reconstructability (design 161/223).

**Failure ownership (design §Feature adapter "Failure ownership"):** this module
OWNS the history-length and ATR-computability checks and returns a typed
`FeatureFailure(reason ∈ {insufficient_history, degenerate_features})` — it NEVER
raises. `invalid_direction` is NOT owned here (that is `decide`, task 2.4).

Pure leaf (P1, R8): imports the overlay/indicator leaf libs only — no LLM, no MCP,
no DB. Intraday-microstructure and fundamental/slow-layer inputs are excluded by
construction (only the daily cores are consulted; R1.3/R1.4). Dependency direction
(design §Allowed Dependencies): `types → params → features → signal_model`;
`FeatureSet` is the features→signal_model internal contract and lives HERE (it is
not part of the completed `types` contract, task 1.1).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from src.micro.indicators import atr as _atr
from src.micro.indicators import closes as _closes
from src.micro.indicators import sma as _sma
from src.overlays.flow.bin_classifier import classify_flow
from src.overlays.reversion.bin_classifier import classify_reversion
from src.overlays.tactical.bin_classifier import classify as classify_tactical
from src.reactive.types import Bar, FeatureFailure

# The longest reused lookback window (252d drawdown / 200d MA / 12mo momentum).
# Both the ticker and SPY histories must reach it for the relative signals.
LONGEST_WINDOW = 252
# The 200d MA window used for the ATR-normalized MA-distance magnitude feature.
MA_LONG_WINDOW = 200


@dataclass(frozen=True)
class FeatureSet:
    """The computed days-to-weeks feature set (features → signal_model contract).

    `trend_vote` / `flow_vote` / `meanrev_vote` are signed votes ∈ [−1,+1]
    (`+1 ⇒ favors LONG`). `trend_strength ∈ [0,1] = abs(flow_vote)`. `raw` carries
    the reused continuous components + ATR-normalized magnitudes for the telemetry
    substrate (design §Data Models). Frozen so a returned feature set is immutable
    and the determinism contract (R8.1) holds. Discriminated against `FeatureFailure`
    by `isinstance` in `decide` (task 2.4).
    """

    trend_vote: float
    flow_vote: float
    meanrev_vote: float
    trend_strength: float
    raw: dict


# --- Vote maps (sign convention is load-bearing) ----------------------------

_TACTICAL_VOTE = {"positive": 1.0, "neutral": 0.0, "negative": -1.0}
# CONTRARIAN: oversold is a +1 (LONG-favoring) vote — easy to invert, unit-tested.
_REVERSION_VOTE = {"MR_OVERSOLD": 1.0, "MR_NEUTRAL": 0.0, "MR_OVERBOUGHT": -1.0}


def compute_features(
    ticker_bars: Sequence[Bar],
    spy_close: Sequence[float],
    rf_yield_pct: float | None,
    atr_period: int = 14,
) -> FeatureSet | FeatureFailure:
    """Compute the days-to-weeks feature set, or a typed failure (never raises).

    Args:
        ticker_bars: chronologically-ordered daily OHLCV bars (index [-1] = most
            recent). Feeds `indicators.atr` directly and supplies the ticker
            adj-close array (via `indicators.closes`) the overlay cores consume.
        spy_close: SPY adjusted-close series (the relative-to-market benchmark for
            the tactical + flow cores). Index [-1] = most recent.
        rf_yield_pct: risk-free DGS1 yield (percent) for the tactical absolute-
            momentum gate, or None. `None` makes tactical *abstain* (vote 0) when
            history is otherwise sufficient — it is NOT a failure.
        atr_period: ATR lookback (default 14 daily bars).

    Returns:
        `FeatureSet` on success, else `FeatureFailure(reason=...)` for
        `insufficient_history` (history shorter than the longest reused window)
        or `degenerate_features` (ATR uncomputable / zero → cannot normalize).
    """
    # --- Gate 0: Bar-key validation (design line 177 precondition) ----------
    # The "never raise" contract is unconditional, and the design assigns
    # Bar-key validation to THIS boundary. A bar missing an OHLC key would
    # otherwise KeyError downstream (e.g. `_atr` reading a prior `close` on a
    # bar that passed `_closes`' high/low-only filter). Map malformed bars to
    # `degenerate_features` (features are non-computable) rather than raising.
    for b in ticker_bars:
        for key in ("open", "high", "low", "close", "volume"):
            if b.get(key) is None:
                return FeatureFailure(reason="degenerate_features")

    # --- Gate 1: history length (this module owns insufficient_history) -----
    # Need the longest reused window on BOTH the ticker bars and SPY closes
    # (252 covers the 252d drawdown / 200d MA / 12mo momentum; ≫ the 15 bars
    # the 14-period ATR needs, so no separate ATR-length gate is required).
    ticker_closes = _closes(ticker_bars)
    if (
        len(ticker_bars) < LONGEST_WINDOW
        or len(ticker_closes) < LONGEST_WINDOW
        or len(spy_close) < LONGEST_WINDOW
    ):
        return FeatureFailure(reason="insufficient_history")

    # --- Gate 2: ATR computability (this module owns degenerate_features) ---
    # Compute ATR once, BEFORE any normalization division. None (insufficient
    # bars for the window) or zero (flat series, no range) → cannot normalize.
    atr_val = _atr(ticker_bars, atr_period)
    if atr_val is None or atr_val == 0.0:
        return FeatureFailure(reason="degenerate_features")

    spy_list = [float(c) for c in spy_close]

    # --- Core → signed votes ------------------------------------------------
    # trend (tactical): bin-only; unavailable (incl. rf None) → abstain (0).
    tactical = classify_tactical(ticker_closes, spy_list, rf_yield_pct)
    tactical_bin = tactical["bin"]
    trend_vote = _TACTICAL_VOTE.get(tactical_bin, 0.0)

    # flow (CTA-proximity): continuous composite passed straight through. When
    # the core is unavailable its `components` is None → abstain (0).
    flow = classify_flow(ticker_closes, spy_list)
    flow_components = flow.get("components")
    flow_vote = (
        float(flow_components["composite_score_normalized"])
        if flow_components is not None
        else 0.0
    )

    # meanrev (reversion): categorical bin → contrarian vote; unavailable → 0.
    reversion = classify_reversion(ticker_closes)
    reversion_bin = reversion["bin"]
    meanrev_vote = _REVERSION_VOTE.get(reversion_bin, 0.0)
    reversion_components = reversion.get("components") or {}

    # trend_strength = abs(flow_vote) ∈ [0,1] (design §Feature adapter rule).
    trend_strength = abs(flow_vote)

    # --- ATR-normalized magnitude features + raw substrate (Req 1.2) --------
    close = ticker_closes[-1]
    # 252d high is already computed by the reversion core — reuse, don't recompute.
    high_252 = reversion_components.get("252d_high")
    sma200 = _sma(ticker_closes, MA_LONG_WINDOW)

    # drawdown-from-high and MA-distance, expressed in daily-ATR units.
    drawdown_atr = (high_252 - close) / atr_val if high_252 is not None else None
    ma_distance_atr = (close - sma200) / atr_val if sma200 is not None else None

    raw: dict = {
        # Reused reversion continuous components (verbatim percents for telemetry).
        "rsi_14": reversion_components.get("rsi_14"),
        "drawdown_from_252d_high_pct": reversion_components.get(
            "drawdown_from_252d_high_pct"
        ),
        "bollinger_band_position": reversion_components.get("bollinger_band_position"),
        "ma_distance_200d_pct": reversion_components.get("ma_distance_200d_pct"),
        "252d_high": high_252,
        # Flow composite + tactical bin (the categorical trend signal).
        "flow_composite": flow_vote,
        "tactical_bin": tactical_bin,
        # ATR + the ATR-normalized magnitude features (Req 1.2 volatility units).
        "atr": atr_val,
        "drawdown_atr": drawdown_atr,
        "ma_distance_atr": ma_distance_atr,
    }

    return FeatureSet(
        trend_vote=trend_vote,
        flow_vote=flow_vote,
        meanrev_vote=meanrev_vote,
        trend_strength=trend_strength,
        raw=raw,
    )
