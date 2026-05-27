"""Pure-logic unit tests for the Polygon total-return reconstruction (P0-7).

Exercises the pure helpers in src/mcp/market_data/polygon_provider.py
(`_normalize_bars`, `_reconstruct_total_return`) with mocked bar/dividend data.
NO network and NO live Polygon key required. The live-API path (real bars /
real dividends matching a hand-computed figure for a real payer) is flagged for
manual verification in the report.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytest.importorskip("httpx", reason="polygon_provider imports httpx at module load")

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MOD_PATH = _REPO_ROOT / "src/mcp/market_data/polygon_provider.py"


def _load():
    spec = importlib.util.spec_from_file_location(
        "polygon_provider_tr_under_test", _MOD_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["polygon_provider_tr_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def _bar(ts_ms, c):
    return {"t": ts_ms, "o": c, "h": c, "l": c, "c": c, "v": 100}


# 2024-01-02, 2024-01-03, 2024-01-04 (ms epoch UTC, midnight)
_T0 = 1704153600000  # 2024-01-02
_T1 = 1704240000000  # 2024-01-03
_T2 = 1704326400000  # 2024-01-04


def test_normalize_bars_labels_split_adjusted_not_total_return():
    mod = _load()
    rows = mod._normalize_bars([_bar(_T0, 100.0), _bar(_T1, 110.0)])
    assert rows[0]["date"] == "2024-01-02"
    # The mislabel fix: `c` is split-adjusted; explicitly named, NOT claimed TR.
    assert rows[0]["close_split_adj"] == 100.0
    assert rows[0]["close"] == 100.0
    assert rows[0]["adj_close"] == 100.0  # back-compat alias == split-adj close
    # total_return_close stays null until reconstruction runs.
    assert rows[0]["total_return_close"] is None


def test_total_return_no_dividends_equals_split_only():
    """With zero dividends, total_return_close == close_split_adj for every row."""
    mod = _load()
    rows = mod._normalize_bars([_bar(_T0, 100.0), _bar(_T1, 110.0), _bar(_T2, 121.0)])
    out = mod._reconstruct_total_return(rows, dividends=[])
    for r in out:
        assert r["total_return_close"] == pytest.approx(r["close_split_adj"])


def test_total_return_reinvests_dividend():
    """A $2 dividend with ex-date on bar T1 (prior close 100) scales the index
    by (1 + 2/100) = 1.02 from T1 onward; price-only return understates TR."""
    mod = _load()
    rows = mod._normalize_bars([_bar(_T0, 100.0), _bar(_T1, 100.0), _bar(_T2, 100.0)])
    dividends = [{"ex_date": "2024-01-03", "cash_amount": 2.0}]
    out = mod._reconstruct_total_return(rows, dividends)

    # T0: anchor, no dividend yet.
    assert out[0]["total_return_close"] == pytest.approx(100.0)
    # T1 (ex-date): growth *= 1 + 2/100 = 1.02 => 100 * 1.02
    assert out[1]["total_return_close"] == pytest.approx(102.0)
    # T2: no new dividend, growth persists => still 102.
    assert out[2]["total_return_close"] == pytest.approx(102.0)

    # Hand-computed dividend-inclusive holding-period return over the window:
    tr_ratio = out[-1]["total_return_close"] / out[0]["total_return_close"]
    price_ratio = out[-1]["close_split_adj"] / out[0]["close_split_adj"]
    assert tr_ratio == pytest.approx(1.02)
    assert price_ratio == pytest.approx(1.0)
    assert tr_ratio > price_ratio  # TR captures the reinvested dividend


def test_total_return_ex_date_price_drop_matches_textbook():
    """Discriminating case: a flat-priced stock that drops by EXACTLY the
    dividend on ex-date must yield a total-return ratio of 1.0 (CRSP/Bloomberg
    convention TR_t = TR_{t-1} * (P_t + D_t) / P_{t-1}).

    Buy at $100; ex-date $2 dividend, Polygon split-adjusted close drops to $98
    (Polygon does NOT adjust for dividends); stays at $98. You got $2 back and
    the price is net flat => total return == 0%.
    """
    mod = _load()
    rows = mod._normalize_bars([_bar(_T0, 100.0), _bar(_T1, 98.0), _bar(_T2, 98.0)])
    out = mod._reconstruct_total_return(rows, [{"ex_date": "2024-01-03", "cash_amount": 2.0}])

    assert out[0]["total_return_close"] == pytest.approx(100.0)
    # T1 ex-date: 98 * (1 + 2/98) = 98 + 2 = 100 -> textbook (98+2)/100 * 100
    assert out[1]["total_return_close"] == pytest.approx(100.0)
    assert out[2]["total_return_close"] == pytest.approx(100.0)

    tr_ratio = out[-1]["total_return_close"] / out[0]["total_return_close"]
    assert tr_ratio == pytest.approx(1.0)  # net-zero TR, NOT 0.9996 (the buggy formula)


def test_total_return_empty_rows_safe():
    mod = _load()
    assert mod._reconstruct_total_return([], dividends=[{"ex_date": "x", "cash_amount": 1}]) == []


def test_total_return_accepts_polygon_ex_dividend_date_key():
    """Polygon's dividends payload uses 'ex_dividend_date'; helper accepts it."""
    mod = _load()
    rows = mod._normalize_bars([_bar(_T0, 50.0), _bar(_T1, 50.0)])
    out = mod._reconstruct_total_return(
        rows, [{"ex_dividend_date": "2024-01-03", "cash_amount": 5.0}]
    )
    # ex-date on T1, prior close 50 => *1.1 => 55
    assert out[1]["total_return_close"] == pytest.approx(55.0)
