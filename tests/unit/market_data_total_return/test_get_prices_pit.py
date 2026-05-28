"""Unit tests for get_prices PIT (`as_of`) + mode plumbing (P0-7), yfinance path.

yfinance is required only to import the server module (importorskip). We do NOT
hit the network: `yf.Ticker(...).history` is monkeypatched to return a tiny
fixed pandas DataFrame, and POSTGRES_* env is cleared so persistence no-ops.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytest.importorskip("yfinance", reason="market_data server imports yfinance at load")
pd = pytest.importorskip("pandas")

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SERVER_PATH = _REPO_ROOT / "src/mcp/market_data/server.py"


def _load_server(monkeypatch):
    # Force the yfinance fallback path (no polygon) for deterministic behaviour.
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "yfinance")
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)
    for v in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"):
        monkeypatch.delenv(v, raising=False)
    spec = importlib.util.spec_from_file_location("market_data_pit_under_test", _SERVER_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["market_data_pit_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def _fake_history_df():
    idx = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    return pd.DataFrame(
        {
            "Open": [100.0, 101.0, 102.0],
            "High": [100.0, 101.0, 102.0],
            "Low": [100.0, 101.0, 102.0],
            "Close": [100.0, 101.0, 102.0],
            "Adj Close": [99.0, 100.5, 102.0],
            "Volume": [10, 11, 12],
        },
        index=idx,
    )


class _FakeTicker:
    def __init__(self, *a, **k):
        pass

    def history(self, *a, **k):
        return _fake_history_df()


def test_mode_invalid_raises(monkeypatch):
    mod = _load_server(monkeypatch)
    monkeypatch.setattr(mod.yf, "Ticker", _FakeTicker)
    with pytest.raises(ValueError):
        mod.get_prices("AAPL", "2024-01-01", "2024-01-31", mode="bogus")


def test_split_only_default_shape_preserved(monkeypatch):
    mod = _load_server(monkeypatch)
    monkeypatch.setattr(mod.yf, "Ticker", _FakeTicker)
    out = mod.get_prices("AAPL", "2024-01-01", "2024-01-31")
    assert out["mode"] == "split_only"
    assert out["as_of"] is None
    assert out["rowcount"] == 3
    r0 = out["rows"][0]
    # Legacy fields intact.
    for k in ("date", "open", "high", "low", "close", "adj_close", "volume"):
        assert k in r0
    # total_return_close present but null in split_only mode.
    assert r0["total_return_close"] is None


def test_total_return_mode_surfaces_adj_close(monkeypatch):
    mod = _load_server(monkeypatch)
    monkeypatch.setattr(mod.yf, "Ticker", _FakeTicker)
    out = mod.get_prices("AAPL", "2024-01-01", "2024-01-31", mode="total_return")
    assert out["mode"] == "total_return"
    # yfinance Adj Close IS total-return adjusted; surfaced as total_return_close.
    assert out["rows"][0]["total_return_close"] == pytest.approx(99.0)
    assert out["rows"][2]["total_return_close"] == pytest.approx(102.0)


def test_as_of_drops_future_bars(monkeypatch):
    """as_of guard: bars dated after as_of must be dropped (no look-ahead)."""
    mod = _load_server(monkeypatch)
    monkeypatch.setattr(mod.yf, "Ticker", _FakeTicker)
    out = mod.get_prices("AAPL", "2024-01-01", "2024-01-31", as_of="2024-01-03")
    dates = [r["date"] for r in out["rows"]]
    assert dates == ["2024-01-02", "2024-01-03"]
    assert out["rowcount"] == 2
    assert out["as_of"] == "2024-01-03"


def test_as_of_none_keeps_all(monkeypatch):
    mod = _load_server(monkeypatch)
    monkeypatch.setattr(mod.yf, "Ticker", _FakeTicker)
    out = mod.get_prices("AAPL", "2024-01-01", "2024-01-31", as_of=None)
    assert out["rowcount"] == 3
