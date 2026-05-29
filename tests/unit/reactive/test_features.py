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


# ===========================================================================
# ADDED (task 3.2). Everything ABOVE this banner PRE-EXISTED from the task-2.1
# TDD pass. The 3.2 coverage-completion additions below are: (1) the leaf
# import-surface ISOLATION check (R8.2/R8.3 — the real gap, with a self-proving
# negative case), (2) explicit EXCLUSION-of-intraday/fundamental assertions
# traced to R1.3/R1.4, (3) the MR_UNAVAILABLE unreachable-path proof (P14
# reversion-core coverage documentation), and (4) additive DETERMINISM angles
# (input-immutability + multi-regime repeat-equality) that the single-input
# `a == b` above does not assert.
# ===========================================================================

import ast
import inspect
import sys
from pathlib import Path

import src.reactive.features as features_mod

# LLM/MCP/network/DB families that would break the "pure leaf, no LLM/MCP/live-DB"
# contract if imported DIRECTLY by features.py (R8.2). numpy/scipy/pandas are the
# reused CORES' transitive deps — legitimate downstream, but features.py must not
# import them directly (it passes plain Python lists/dicts to the cores). The
# stdlib allowlist below is the load-bearing general check; this list is the
# reviewer-legible guard against the named offenders (mirrors test_params.py).
_FORBIDDEN_IMPORT_SUBSTRINGS = (
    "psycopg",
    "sqlalchemy",
    "httpx",
    "requests",
    "urllib3",
    "aiohttp",
    "mcp",
    "llm",
    "anthropic",
    "openai",
    "boto3",
    "numpy",
    "scipy",
    "pandas",
)

# The EXACT intra-`src` modules features.py is permitted to depend on (design
# §Allowed Dependencies: the overlay cores + indicators.atr + reactive.types).
# Deliberately exact-match, NOT a `src.micro.*` / `src.overlays.*` prefix: a
# prefix allowlist would let `from src.micro.signal_model import ...` (the live
# INTRADAY model R1.3 excludes) or a future `src.reactive.db` slip through
# silently. Tightness here is what makes the isolation + exclusion tests
# non-vacuous.
_ALLOWED_SRC_MODULES = frozenset(
    {
        "src.micro.indicators",
        "src.overlays.flow.bin_classifier",
        "src.overlays.reversion.bin_classifier",
        "src.overlays.tactical.bin_classifier",
        "src.reactive.types",
    }
)


def _check_import_surface(source: str) -> list[str]:
    """Return a list of isolation violations for `source` (empty = clean).

    AST over the *source text* — NOT `sys.modules` — because the test harness
    itself loads numpy/scipy/httpx/pandas (see the validation command), so a
    `sys.modules` probe would be polluted and report false positives. This
    inspects what features.py actually declares as direct imports.

    A violation is any import whose top-level root is neither stdlib nor `src`,
    OR any `src.`-prefixed import not in the exact `_ALLOWED_SRC_MODULES` set.
    """
    allowed_roots = set(sys.stdlib_module_names) | {"__future__", "src"}
    violations: list[str] = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in allowed_roots:
                    violations.append(f"import {alias.name}")
                elif root == "src" and alias.name not in _ALLOWED_SRC_MODULES:
                    # Plain `import src.micro.signal_model` must be caught too —
                    # not only the `from ... import` form. The exact-allowlist is
                    # enforced in BOTH branches (else the intraday model could
                    # slip in via the plain-import style).
                    violations.append(f"import {alias.name} (src not in allowlist)")
        elif isinstance(node, ast.ImportFrom):
            if node.level != 0 or node.module is None:
                violations.append("relative import (level>0 or no module)")
                continue
            root = node.module.split(".")[0]
            if root not in allowed_roots:
                violations.append(f"from {node.module}")
            elif root == "src" and node.module not in _ALLOWED_SRC_MODULES:
                violations.append(f"from {node.module} (src not in allowlist)")
    return violations


# --- Isolation (R8.2 / R8.3): features.py's OWN import surface --------------


def test_features_module_import_surface_is_stdlib_plus_allowed_src_only():
    """R8.2/R8.3: features.py is a pure leaf. Its DIRECT import surface must be
    confined to stdlib + the exact allowed `src` cores (overlays / indicators /
    reactive.types) — no LLM/MCP/network/DB, and crucially no intraday
    `src.micro.signal_model` or any fundamental core. `sys.stdlib_module_names`
    is the robust general allowlist (catches ANY third-party import, incl.
    numpy/scipy/pandas, not only the enumerated offenders)."""
    source = Path(features_mod.__file__).read_text()
    violations = _check_import_surface(source)
    assert violations == [], (
        f"features.py has forbidden direct imports {violations} — breaks the "
        "pure-leaf isolation contract (R8.2/R8.3)"
    )


def test_features_import_surface_check_actually_catches_violations():
    """Self-proving: the isolation predicate is not vacuous — it FLAGS each
    forbidden form. Run it over a crafted bad source (without touching src/):
    a third-party import, the EXCLUDED intraday model, and a non-allowlisted
    `src` module must all be reported. If this test passes, the green result of
    the real-surface test above is meaningful."""
    bad_source = (
        "import numpy\n"
        "from src.micro.signal_model import softmax3\n"  # excluded intraday (from-form)
        "import src.micro.signal_model\n"  # excluded intraday (plain-import form)
        "from src.reactive.db import write_row\n"
        "import os\n"  # stdlib — must NOT be flagged
        "from src.micro.indicators import atr\n"  # allowed — must NOT be flagged
    )
    violations = _check_import_surface(bad_source)
    assert "import numpy" in violations
    assert "from src.micro.signal_model (src not in allowlist)" in violations
    # The plain `import src.micro.signal_model` form must ALSO be caught — the
    # exact-allowlist is enforced in both AST branches, not just `ImportFrom`.
    assert "import src.micro.signal_model (src not in allowlist)" in violations
    assert "from src.reactive.db (src not in allowlist)" in violations
    # The clean stdlib + allowed-src imports must NOT be reported.
    assert not any("os" in v for v in violations)
    assert not any("indicators" in v for v in violations)


def test_features_module_has_no_forbidden_io_imports():
    """R8.2: explicit, reviewer-legible guard against the named LLM/MCP/network/
    DB + heavy-numeric families as DIRECT features.py imports. Redundant with the
    stdlib allowlist above by design — documents that R8.2's specific offenders
    (incl. numpy/scipy/pandas, which are the cores' transitive deps, not
    features' own) are absent from the direct surface."""
    source = Path(features_mod.__file__).read_text()
    tree = ast.parse(source)
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])
    for root in roots:
        for forbidden in _FORBIDDEN_IMPORT_SUBSTRINGS:
            assert forbidden not in root, (
                f"features imports forbidden I/O/LLM/heavy-numeric family "
                f"{root!r} (matched {forbidden!r}) — violates R8.2 (no LLM/MCP/"
                "live-DB; numpy/scipy/pandas are the cores' transitive deps, not "
                "features' direct imports)"
            )


# --- Exclusion of intraday-microstructure / fundamental inputs (R1.3/R1.4) --


def test_excludes_intraday_and_fundamental_cores_by_import():
    """R1.3 (exclude intraday-microstructure inputs) / R1.4 (exclude fundamental
    or slow-layer prior): features.py consults ONLY the daily overlay cores +
    indicators.atr. It must NOT import the live intraday `src.micro.signal_model`
    (its microstructure features) nor any fundamentals core. Traced to R1.3/R1.4;
    enforced by the exact-match src allowlist (a prefix allowlist would let the
    intraday model through)."""
    source = Path(features_mod.__file__).read_text()
    tree = ast.parse(source)
    src_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.level == 0
        and node.module
        and node.module.split(".")[0] == "src"
    }
    # The intraday signal model and any fundamentals/edgar/yfinance core are out.
    assert "src.micro.signal_model" not in src_modules, (
        "features.py imports the live INTRADAY signal_model — R1.3 excludes "
        "intraday-microstructure inputs (the /micro module is a sibling, untouched)"
    )
    for m in src_modules:
        assert not any(
            tok in m for tok in ("fundamental", "edgar", "yfinance", "macro")
        ), f"features.py imports a fundamental/slow-layer core {m!r} — R1.4 excludes it"
    # Positive complement: every src import is one of the explicitly allowed cores.
    assert src_modules <= set(_ALLOWED_SRC_MODULES)


def test_compute_features_signature_takes_no_fundamental_inputs():
    """R1.3/R1.4: the input contract is exactly the daily-bar adapter's
    arguments — `ticker_bars`, `spy_close`, `rf_yield_pct`, `atr_period`. No
    intraday-microstructure feed and no fundamental/earnings/slow-layer input is
    accepted, so one cannot leak in via the call surface. Guards against a
    fundamental parameter being silently added later."""
    params = list(inspect.signature(compute_features).parameters)
    assert params == ["ticker_bars", "spy_close", "rf_yield_pct", "atr_period"]


# --- Reversion-core P14: MR_UNAVAILABLE is unreachable past the global gate --


def test_reversion_mr_unavailable_is_preempted_by_global_history_gate():
    """P14 reversion-core coverage / executable documentation: MR_UNAVAILABLE is
    the reversion core's insufficient-price-history bin. The core returns it only
    when `len(prices) < 252` — but `compute_features`' global insufficient_history
    gate ALSO trips at `len < LONGEST_WINDOW (252)` and short-circuits BEFORE any
    core is called. So MR_UNAVAILABLE is UNREACHABLE through `compute_features`
    (task 2.1's note). We do NOT fake it: assert the real core emits it on a short
    series, AND that the same short series makes `compute_features` fail globally
    with insufficient_history first. The other three reversion bins (MR_OVERSOLD,
    MR_OVERBOUGHT, MR_NEUTRAL) ARE exercised through compute_features above."""
    short_closes = _steady_uptrend(LOOKBACK - 1)  # 251 < 252
    # The reversion core itself returns the UNAVAILABLE bin on this short series.
    assert classify_reversion(short_closes)["bin"] == "MR_UNAVAILABLE"
    # But compute_features never reaches the core: the global gate pre-empts it.
    bars = _bars_from_closes(short_closes)
    spy = _steady_uptrend(LOOKBACK)
    result = compute_features(bars, spy, rf_yield_pct=4.0)
    assert isinstance(result, FeatureFailure)
    assert result.reason == "insufficient_history"


# --- Determinism (R8.1): additive angles beyond the single-input a==b above --


def test_determinism_does_not_mutate_inputs():
    """R8.1: `compute_features` reads its inputs by value and never mutates the
    caller's bars / SPY list. (The single-input `a == b` test above asserts
    repeat-equality but not input-immutability — a routine that sorted or
    appended in place could still return equal objects yet corrupt the caller.)"""
    closes = _oversold_closes()
    bars = _bars_from_closes(closes)
    spy = _flat_closes(300.0, LOOKBACK)
    bars_snapshot = [dict(b) for b in bars]
    spy_snapshot = list(spy)
    result = compute_features(bars, spy, rf_yield_pct=4.0)
    assert isinstance(result, FeatureSet)
    assert bars == bars_snapshot, "compute_features mutated the input bars"
    assert spy == spy_snapshot, "compute_features mutated the input SPY closes"


def test_determinism_repeat_equality_across_regimes():
    """R8.1: repeated calls on identical synthetic bars return identical
    FeatureSets across MULTIPLE distinct regimes (not just the one oversold case
    the existing single-input test uses) — extends the determinism guarantee to
    the oversold / overbought / uptrend bins."""
    for closes in (_oversold_closes(), _overbought_closes(), _steady_uptrend(LOOKBACK)):
        bars = _bars_from_closes(closes)
        spy = _flat_closes(300.0, LOOKBACK)
        a = compute_features(bars, spy, rf_yield_pct=4.0)
        b = compute_features(bars, spy, rf_yield_pct=4.0)
        assert isinstance(a, FeatureSet)
        assert a == b
