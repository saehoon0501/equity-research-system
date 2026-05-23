"""Tests for mcp__polygon__get_short_interest wrapper.

Uses unittest.mock to avoid hitting the live Polygon API. Covers:
- Happy path returning a single SI record
- ticker_not_found path (unknown ticker)
- Tier-insufficient path (NOT_AUTHORIZED response)
- Transport error path
- SDK missing list_short_interest method (older polygon-api-client versions)
- Malformed record (missing required fields)
"""
from __future__ import annotations

import importlib
import sys
import types
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _stub_polygon_module(monkeypatch):
    """Inject a fake `polygon` module so server.py can import RESTClient
    without requiring the polygon-api-client SDK to be installed in the
    test environment."""
    if "polygon" in sys.modules:
        yield
        return

    fake_pkg = types.ModuleType("polygon")

    class _FakeREST:
        def __init__(self, api_key=None):
            self.api_key = api_key

    fake_pkg.RESTClient = _FakeREST
    monkeypatch.setitem(sys.modules, "polygon", fake_pkg)
    yield


@pytest.fixture
def _polygon_env(monkeypatch):
    """Ensure POLYGON_API_KEY is set so _client() doesn't bail early."""
    monkeypatch.setenv("POLYGON_API_KEY", "test_key")


def _load_module():
    """Force a fresh import of the polygon server module."""
    if "src.mcp.polygon.server" in sys.modules:
        return importlib.reload(sys.modules["src.mcp.polygon.server"])
    return importlib.import_module("src.mcp.polygon.server")


def _build_short_interest_record(**overrides):
    """Build a fake SI record with attributes (mimics polygon SDK dataclass)."""
    rec = MagicMock()
    rec.short_interest = overrides.get("short_interest", 12_500_000)
    rec.days_to_cover = overrides.get("days_to_cover", 6.8)
    rec.settlement_date = overrides.get("settlement_date", "2026-05-15")
    rec.avg_daily_volume = overrides.get("avg_daily_volume", 1_840_000)
    return rec


# ---------- Happy path ----------


def test_happy_path_returns_canonical_shape(_polygon_env):
    mod = _load_module()
    client = MagicMock()
    client.list_short_interest.return_value = iter([_build_short_interest_record()])

    with patch.object(mod, "_client", return_value=client):
        with patch.object(mod, "_is_ticker_unknown", return_value=False):
            out = mod.get_short_interest("GME")

    assert out["ticker"] == "GME"
    assert out["short_interest"] == 12_500_000
    assert out["days_to_cover"] == pytest.approx(6.8)
    assert out["settlement_date"] == "2026-05-15"
    assert out["avg_daily_volume"] == 1_840_000
    assert out["source"] == "polygon_short_interest_v1"
    assert "retrieved_at" in out


# ---------- ticker_not_found paths ----------


def test_unknown_ticker_returns_ticker_not_found(_polygon_env):
    mod = _load_module()
    client = MagicMock()
    with patch.object(mod, "_client", return_value=client):
        with patch.object(mod, "_is_ticker_unknown", return_value=True):
            out = mod.get_short_interest("FAKE_TICKER_XYZ")
    assert out == {"ticker_not_found": True}


def test_empty_records_returns_ticker_not_found(_polygon_env):
    mod = _load_module()
    client = MagicMock()
    client.list_short_interest.return_value = iter([])  # no records

    with patch.object(mod, "_client", return_value=client):
        with patch.object(mod, "_is_ticker_unknown", return_value=False):
            out = mod.get_short_interest("THINLY_TRADED")
    assert out["ticker_not_found"] is True


# ---------- Tier-insufficient ----------


def test_tier_insufficient_routes_to_payload(_polygon_env):
    mod = _load_module()
    client = MagicMock()
    # Simulate Polygon SDK raising on NOT_AUTHORIZED
    client.list_short_interest.side_effect = RuntimeError("NOT_AUTHORIZED")

    with patch.object(mod, "_client", return_value=client):
        with patch.object(mod, "_is_ticker_unknown", return_value=False):
            out = mod.get_short_interest("AAPL")

    assert out["ticker_not_found"] is True
    assert out["error_class"] == "polygon_tier_insufficient"
    assert "upgrade_url" in out


def test_entitled_keyword_also_routes_tier_insufficient(_polygon_env):
    mod = _load_module()
    client = MagicMock()
    client.list_short_interest.side_effect = Exception(
        "Your plan is not entitled to this endpoint."
    )

    with patch.object(mod, "_client", return_value=client):
        with patch.object(mod, "_is_ticker_unknown", return_value=False):
            out = mod.get_short_interest("AAPL")
    assert out["error_class"] == "polygon_tier_insufficient"


# ---------- Other failure paths ----------


def test_generic_transport_error_returns_error_class(_polygon_env):
    mod = _load_module()
    client = MagicMock()
    client.list_short_interest.side_effect = ConnectionError("network unreachable")

    with patch.object(mod, "_client", return_value=client):
        with patch.object(mod, "_is_ticker_unknown", return_value=False):
            out = mod.get_short_interest("AAPL")
    assert out["ticker_not_found"] is True
    assert out["error_class"] == "short_interest_transport_error"


def test_sdk_missing_method_returns_canonical_error(_polygon_env):
    mod = _load_module()
    client = MagicMock(spec=[])  # no methods at all
    # Ensure list_short_interest attribute resolves to None
    del client.list_short_interest

    with patch.object(mod, "_client", return_value=client):
        with patch.object(mod, "_is_ticker_unknown", return_value=False):
            out = mod.get_short_interest("AAPL")
    assert out["ticker_not_found"] is True
    assert out["error_class"] == "polygon_sdk_missing_short_interest"


def test_malformed_record_returns_error(_polygon_env):
    mod = _load_module()
    rec = MagicMock()
    rec.short_interest = None
    rec.days_to_cover = None
    rec.settlement_date = None
    rec.avg_daily_volume = None

    client = MagicMock()
    client.list_short_interest.return_value = iter([rec])

    with patch.object(mod, "_client", return_value=client):
        with patch.object(mod, "_is_ticker_unknown", return_value=False):
            out = mod.get_short_interest("AAPL")
    assert out["ticker_not_found"] is True
    assert out["error_class"] == "short_interest_malformed_record"


def test_client_construction_failure_returns_ticker_not_found(_polygon_env):
    mod = _load_module()
    with patch.object(mod, "_client", side_effect=RuntimeError("API_KEY missing")):
        out = mod.get_short_interest("AAPL")
    assert out["ticker_not_found"] is True
    assert out["error_class"] == "RuntimeError"
