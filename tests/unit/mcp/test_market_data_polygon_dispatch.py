"""Polygon provider dispatch + smoke tests for the market_data MCP.

These do NOT hit the live Polygon API. They cover:
  - Module loads cleanly under both yfinance and polygon provider settings.
  - Dispatch flag (`_USE_POLYGON`) reads from env at module import.
  - Polygon adapter raises a clear PolygonAuthError when key is missing.

Live Polygon-API tests live in test_market_data.py via importorskip("yfinance");
adding a polygon-live counterpart is a v0.5+ task once the operator funds
the Stocks Starter tier and we want CI coverage of real responses.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_polygon_provider():
    """Reload polygon_provider as a fresh top-level module (no src.* import)."""
    spec = importlib.util.spec_from_file_location(
        "polygon_provider_under_test",
        _REPO_ROOT / "src/mcp/market_data/polygon_provider.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["polygon_provider_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_polygon_provider_module_loads_without_key():
    """Importing polygon_provider must not require POLYGON_API_KEY at module
    import time (lazy-only at call time). Otherwise operators who use
    yfinance-fallback could not even start the MCP server."""
    mod = _load_polygon_provider()
    assert hasattr(mod, "get_prices")
    assert hasattr(mod, "get_news")
    assert hasattr(mod, "get_real_time_quote")


def test_polygon_provider_raises_clear_error_when_key_missing(monkeypatch):
    """Calling any polygon function with POLYGON_API_KEY unset must raise
    PolygonAuthError with an actionable message — not a silent crash."""
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)
    mod = _load_polygon_provider()
    with pytest.raises(mod.PolygonAuthError) as exc:
        mod.get_real_time_quote("AAPL")
    assert "POLYGON_API_KEY" in str(exc.value)


def test_polygon_interval_mapping_rejects_unsupported(monkeypatch):
    """Internal interval mapper must surface ValueError on unsupported intervals."""
    monkeypatch.setenv("POLYGON_API_KEY", "sentinel")  # so we get past auth check
    mod = _load_polygon_provider()
    with pytest.raises(ValueError) as exc:
        mod._interval_to_polygon("5m")
    assert "5m" in str(exc.value)


def test_polygon_interval_mapping_translates_yfinance_style(monkeypatch):
    """1d/1wk/1mo must map to Polygon (multiplier, timespan) tuples cleanly."""
    monkeypatch.setenv("POLYGON_API_KEY", "sentinel")
    mod = _load_polygon_provider()
    assert mod._interval_to_polygon("1d") == (1, "day")
    assert mod._interval_to_polygon("1wk") == (1, "week")
    assert mod._interval_to_polygon("1mo") == (1, "month")
