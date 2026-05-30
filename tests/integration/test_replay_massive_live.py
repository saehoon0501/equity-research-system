"""`integration_live` Massive smoke — the four live-probe items (Task 4.2).

Requirements R4.1 (point-in-time fetch), R4.4 (delisted + pagination/coverage),
R6.1 (counterparty bid/ask quotes); design.md §"Testing Strategy → Integration
(`integration_live`, requires Massive Advanced/Business)" line 274 and tasks.md
4.2 (line 114-116). This is the live-probe GATE: it exercises the four items the
discovery brief left *unverified-in-research* against a REAL ``MassiveDataClient``
on a live Massive Advanced/Business account, so the operator confirms the data
contract before any candidate number is trusted.

The four probes (design line 274 / tasks line 115):
  1. SPY + a sample S&P 500 symbol resolve (daily bars come back non-empty).
  2. ``/v3/trades`` + ``/v3/quotes`` return rows for a past window.
  3. the splits / dividends / market-holidays reference endpoints answer **200,
     not 403** on the account tier (entitlement).
  4. a known delisted name returns OHLC over the window it traded.

DOUBLE-GATED, NEVER FIRES IN CI (the task's hard constraint — "must NOT run
live"):
  * ``pytestmark = integration_live`` → ``tests/conftest.py``'s
    ``pytest_collection_modifyitems`` attaches a skip marker to every
    ``integration_live`` item whenever ``-m`` does NOT contain
    ``integration_live``. A skip marker fires in *setup*, before any fixture or
    body runs — so the default ``pytest tests/`` (and any run without
    ``-m integration_live``) skips this module without ever touching the network.
    That is the safe verification path used to land this test.
  * a module-level ``skipif`` on a missing ``MASSIVE_API_KEY`` → even an explicit
    ``-m integration_live`` self-skips with a precise gap message rather than
    erroring on a keyless live attempt (tasks line 116 "or reports the precise
    gap"; the task brief: "auto-skipped unless `-m integration_live` + a live
    MASSIVE_API_KEY"). Live execution is OPERATOR-GATED on the key.

WHY RAW ``get()`` FOR SOME PROBES (not the typed DataPort methods):
  * ``fetch_trades`` / ``fetch_quotes`` use ``timestamp.lte=<day>`` + ``order=asc``
    + full ``next_url`` pagination, which for a liquid name walks the ENTIRE
    history up to that day (millions of rows → ``_MAX_PAGES``). For a *probe* we
    issue a single bounded request via the module-level :func:`get` (same real
    transport, same fresh ``apiKey`` injection — still the REAL client hitting
    live Massive) with ``timestamp.gte == timestamp.lte`` and a small ``limit``.
  * the entitlement probe (item 3) needs the raw status code: the typed methods
    *raise* ``DataFetchError`` on a 403 and lose the 200-vs-403 distinction the
    probe asserts. Raw :func:`get` returns a structured ``Result``/``Error`` that
    preserves ``status_code``.
The cheap, faithful bars probes (items 1 & 4) DO use the real
``MassiveDataClient`` methods (a bounded date range = a small fetch) so the test
exercises ``MassiveDataClient`` itself, per the task.

Presence/status-only assertions (non-empty, HTTP 200, no auth error) — NEVER
specific prices or row counts; live data drifts day to day.
"""

from __future__ import annotations

import os

import pytest

from src.reactive.replay.data_client import MassiveDataClient, get

# Gate 1: marker → conftest skip when not selected via `-m integration_live`.
# Gate 2: skipif → self-skip with a precise gap when no live key is present.
pytestmark = [
    pytest.mark.integration_live,
    pytest.mark.skipif(
        not (os.environ.get("MASSIVE_API_KEY") or "").strip(),
        reason="no live MASSIVE_API_KEY — Massive live-probe is operator-gated on the key",
    ),
]


# --------------------------------------------------------------------------- #
# Probe constants. Symbols/windows are deliberately past + named here so the
# operator can adjust them in one place; the *why* is in each comment. The four
# live-probe items are exactly the discovery-brief unverified-in-research set, so
# these constants are the things the operator confirms on the live run.
# --------------------------------------------------------------------------- #

# Item 1 — SPY (the index proxy the features adapter pairs every name against,
# src/reactive/features.py) + a large-cap S&P 500 constituent that has traded
# continuously for years (so any reasonable past window resolves).
_SPY = "SPY"
_SAMPLE_SP500 = "AAPL"

# A short, comfortably-in-depth past daily window (Advanced/Business tier holds
# years of history; this is well inside any plausible lookback).
_BARS_START = "2023-01-03"  # first NYSE session of 2023
_BARS_END = "2023-01-31"

# Item 2 — a single past trading day for the bounded trades/quotes probe. A
# regular NYSE session (Tue 2023-01-03 was the first 2023 session, fully open).
_TICK_DAY = "2023-01-03"

# Item 4 — a known delisted name over the window it actually traded. TWTR
# (Twitter) delisted 2022-10-28 on the Musk take-private; this 2021 window is
# squarely inside its active trading life, so OHLC must come back for a name the
# live universe no longer carries (R4.4 — delisted coverage). Operator may swap
# this for any name confirmed delisted with depth on the account tier.
_DELISTED = "TWTR"
_DELISTED_START = "2021-06-01"
_DELISTED_END = "2021-06-30"

# Item 3 — the Polygon/Massive market-holidays (calendar) endpoint. The typed
# client has no method for it (it is a probe-only entitlement check, not a
# DataPort fetch), so we hit the documented path directly. NOTE: this exact path
# is the Polygon-documented one and is itself part of the live-probe to confirm
# on the account tier; if Massive serves the calendar under a different path the
# operator updates it here.
_MARKET_HOLIDAYS_PATH = "/v1/marketstatus/upcoming"


def _client() -> MassiveDataClient:
    """A REAL ``MassiveDataClient`` (no injected transport → live Massive)."""
    return MassiveDataClient()


# --------------------------------------------------------------------------- #
# Probe 1 — SPY + a sample S&P 500 symbol resolve (R4.1).
# --------------------------------------------------------------------------- #


def test_spy_resolves_with_daily_bars():
    """SPY resolves: real ``fetch_daily_bars`` returns a non-empty bar list."""
    bars = _client().fetch_daily_bars(_SPY, _BARS_START, _BARS_END)
    assert isinstance(bars, list)
    assert len(bars) > 0, f"SPY returned no daily bars for {_BARS_START}..{_BARS_END}"


def test_sample_sp500_symbol_resolves_with_daily_bars():
    """A sample S&P 500 constituent resolves with non-empty daily bars (R4.1)."""
    bars = _client().fetch_daily_bars(_SAMPLE_SP500, _BARS_START, _BARS_END)
    assert isinstance(bars, list)
    assert len(bars) > 0, (
        f"{_SAMPLE_SP500} returned no daily bars for {_BARS_START}..{_BARS_END}"
    )


# --------------------------------------------------------------------------- #
# Probe 2 — /v3/trades + /v3/quotes return rows for a past window (R4.1, R6.1).
#
# Bounded single request via raw get() (gte==lte, small limit) so the live
# operator run does not walk the full pre-day history into _MAX_PAGES.
# --------------------------------------------------------------------------- #


def test_trades_endpoint_returns_rows_for_past_window():
    """``/v3/trades`` answers 200 with rows for a bounded past day (R4.1)."""
    out = get(
        f"/v3/trades/{_SAMPLE_SP500}",
        params={
            "timestamp.gte": _TICK_DAY,
            "timestamp.lte": _TICK_DAY,
            "order": "asc",
            "limit": 10,
        },
    )
    assert out.ok, f"/v3/trades failed: {getattr(out, 'error', out)}"
    assert out.status_code == 200
    results = out.data.get("results") if isinstance(out.data, dict) else None
    assert isinstance(results, list) and len(results) > 0, (
        f"/v3/trades returned no rows for {_SAMPLE_SP500} on {_TICK_DAY}"
    )


def test_quotes_endpoint_returns_rows_for_past_window():
    """``/v3/quotes`` answers 200 with NBBO bid/ask rows for a past day (R6.1)."""
    out = get(
        f"/v3/quotes/{_SAMPLE_SP500}",
        params={
            "timestamp.gte": _TICK_DAY,
            "timestamp.lte": _TICK_DAY,
            "order": "asc",
            "limit": 10,
        },
    )
    assert out.ok, f"/v3/quotes failed: {getattr(out, 'error', out)}"
    assert out.status_code == 200
    results = out.data.get("results") if isinstance(out.data, dict) else None
    assert isinstance(results, list) and len(results) > 0, (
        f"/v3/quotes returned no rows for {_SAMPLE_SP500} on {_TICK_DAY}"
    )


# --------------------------------------------------------------------------- #
# Probe 3 — splits / dividends / market-holidays answer 200, NOT 403 (entitlement).
#
# Raw get() so the raw status code is preserved (the typed methods RAISE on 403
# and lose the 200-vs-403 distinction this probe exists to assert).
# --------------------------------------------------------------------------- #


def test_splits_reference_endpoint_is_entitled():
    """``/v3/reference/splits`` answers 200 (not a 403 tier denial)."""
    out = get(
        "/v3/reference/splits",
        params={"ticker": _SAMPLE_SP500, "limit": 1},
    )
    assert out.ok and out.status_code == 200, (
        "splits reference must be entitled (200, not a 403 tier denial); "
        f"got status={getattr(out, 'status_code', None)} "
        f"class={getattr(out, 'error_class', None)} detail={getattr(out, 'error', None)}"
    )


def test_dividends_reference_endpoint_is_entitled():
    """``/v3/reference/dividends`` answers 200 (not a 403 tier denial)."""
    out = get(
        "/v3/reference/dividends",
        params={"ticker": _SAMPLE_SP500, "limit": 1},
    )
    assert out.ok and out.status_code == 200, (
        "dividends reference must be entitled (200, not a 403 tier denial); "
        f"got status={getattr(out, 'status_code', None)} "
        f"class={getattr(out, 'error_class', None)} detail={getattr(out, 'error', None)}"
    )


def test_market_holidays_reference_endpoint_is_entitled():
    """The market-holidays (calendar) endpoint answers 200 (not a 403 tier denial).

    The typed client has no method for the calendar — it is a probe-only
    entitlement check. The path itself (``_MARKET_HOLIDAYS_PATH``) is part of the
    live-probe: the operator confirms it on the account tier and updates the
    constant if Massive serves the calendar elsewhere.
    """
    out = get(_MARKET_HOLIDAYS_PATH)
    assert out.ok and out.status_code == 200, (
        "market-holidays/calendar must be entitled (200, not a 403 tier denial); "
        f"path={_MARKET_HOLIDAYS_PATH} "
        f"got status={getattr(out, 'status_code', None)} "
        f"class={getattr(out, 'error_class', None)} detail={getattr(out, 'error', None)}"
    )


# --------------------------------------------------------------------------- #
# Probe 4 — a known delisted name returns OHLC over its trading window (R4.4).
# --------------------------------------------------------------------------- #


def test_delisted_name_returns_ohlc_for_its_trading_window():
    """A delisted name returns OHLC over the window it actually traded (R4.4).

    Uses the real ``fetch_daily_bars`` over a window inside the name's active
    trading life — a name the live universe no longer carries must still return
    its historical bars (delisted coverage), the depth item the discovery brief
    left unverified.
    """
    bars = _client().fetch_daily_bars(_DELISTED, _DELISTED_START, _DELISTED_END)
    assert isinstance(bars, list)
    assert len(bars) > 0, (
        f"delisted {_DELISTED} returned no OHLC for its trading window "
        f"{_DELISTED_START}..{_DELISTED_END} — check delisted depth on the tier"
    )
    # Spot-check the OHLC shape on the first bar (presence-only, P13 — values drift).
    first = bars[0]
    assert isinstance(first, dict)
    for ohlc_key in ("o", "h", "l", "c"):
        assert ohlc_key in first, (
            f"delisted bar missing OHLC field {ohlc_key!r}: {sorted(first)}"
        )
