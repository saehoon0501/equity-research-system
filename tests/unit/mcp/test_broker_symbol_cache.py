"""Unit tests for the symbol metadata cache + ticker mapping (Task 3.1).

Covers the design "symbol_cache" component (Domain layer). Requirements: 3.3,
4.1, 4.2, 5.1.

What the symbol_cache owns (per design "symbol_cache & mappers (summary)" +
Architecture map ``symbol_cache <- gate_client + mappers``):

- Build the tradable-symbol set from the PUBLIC ``GET /tradfi/symbols`` (session
  ``status`` open/closed, ``trade_mode``, ``next_open_time``, ``price_precision``,
  ``category_id``, ``symbol``), restricted to the US-stock CFD category
  (``config.US_STOCK_CATEGORY_ID`` = 2). Anything outside that category is
  excluded / rejected (Req 4.2).
- Map + validate instruments by US TICKER only; the venue free-text
  ``symbol_desc`` is NEVER used for identity (Req 4.1 — the reference warns
  ``AAPL`` -> "American Airlines").
- Cache per-symbol enforcement metadata from the AUTHENTICATED
  ``GET /tradfi/symbols/detail?symbols=`` in batches of <=10 symbols (leverage,
  min/max order volume, swap rates, price precision). Merge the public session
  status (open/closed + next_open_time) with the authenticated detail into ONE
  ``SymbolInfo`` per ticker.
- Hold per-symbol swap/financing rates (Req 3.3) and surface ``leverage`` +
  ``trade_mode`` so the validation layer (Task 3.2) can reject disabled /
  sub-floor-leverage names (Req 5.1 — the cache SURFACES the data; 3.2 rejects).
- Freshness/refresh: refresh on a validation MISS (unknown/stale ticker) so
  trade_mode / session status stay current.

Dependency injection seam: ``SymbolCache`` takes a ``gate_client`` (the real
transport module) plus an injectable ``transport=`` so tests drive it with the
Task 1.4 ``make_mock_transport(...)`` — no live venue, no direct httpx, no
re-parsing (it reuses ``mappers.parse_symbols_detail``).

Test-run mechanism (canonical broker pytest command):
    PYTHONSAFEPATH=1 uv run --directory src/mcp/broker python -m pytest \\
        tests/unit/mcp/test_broker_symbol_cache.py -q

The broker runs in its own uv venv (carries ``mcp`` / ``httpx``); the repo root is
NOT on ``sys.path``. This test loads the broker modules by path (importlib-by-path
under unique aliases), loading ``models`` FIRST under its canonical alias so the
dependent modules' ``from models import ...`` reuse the SAME class objects (enum /
isinstance identity holds), mirroring ``test_broker_mappers.py``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# Repo root: tests/unit/mcp/test_broker_symbol_cache.py -> parents[3] == repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_BROKER_DIR = _REPO_ROOT / "src" / "mcp" / "broker"
# symbol_cache + its deps do by-name sibling imports (`import config`,
# `from models import ...`, `import mappers`) — exactly the production posture
# (`python server.py` with the broker dir on sys.path[0]). The broker uv venv does
# NOT put the broker dir on sys.path, so seed it here so the sibling imports
# resolve (mirrors how server.py would be launched).
if str(_BROKER_DIR) not in sys.path:
    sys.path.insert(0, str(_BROKER_DIR))


def _load_by_path(alias: str, path: Path):
    spec = importlib.util.spec_from_file_location(alias, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    spec.loader.exec_module(module)
    return module


# The 1.4 mock transport + fixture loader (the injectable-transport seam).
_FAKES_PATH = _REPO_ROOT / "tests" / "unit" / "mcp" / "broker_gate_fakes.py"
broker_gate_fakes = _load_by_path("broker_gate_fakes", _FAKES_PATH)

# LOAD-BEARING ordering (see tasks.md Implementation Notes / Task 2.2 note):
# load ``models`` FIRST under its CANONICAL alias so every dependent module's
# ``from models import ...`` reuses THIS instance (one canonical set of
# classes/enums -> isinstance/identity holds). Then config, mappers (deps of
# symbol_cache), then the unit-under-test.
broker_models = _load_by_path("models", _BROKER_DIR / "models.py")
broker_config = _load_by_path("config", _BROKER_DIR / "config.py")
broker_mappers = _load_by_path("mappers", _BROKER_DIR / "mappers.py")
gate_client = _load_by_path("broker_gate_client", _BROKER_DIR / "gate_client.py")
symbol_cache = _load_by_path("broker_symbol_cache", _BROKER_DIR / "symbol_cache.py")

SymbolInfo = broker_models.SymbolInfo
RejectionReason = broker_models.RejectionReason
RejectionCode = broker_models.RejectionCode
US_STOCK_CATEGORY_ID = broker_config.US_STOCK_CATEGORY_ID

load_fixture = broker_gate_fakes.load_fixture


# --------------------------------------------------------------------------- #
# Helpers / fixtures.
# --------------------------------------------------------------------------- #


def _set_creds(monkeypatch, key: str = "k-test", secret: str = "s-test") -> None:
    """symbols/detail is authenticated — gate_client resolves creds fresh."""
    monkeypatch.setenv("GATE_API_KEY", key)
    monkeypatch.setenv("GATE_API_SECRET", secret)


def _make_cache(transport):
    """Construct a SymbolCache with the real gate_client module wired to an
    injected (mock) transport — the dependency-injection seam under test."""
    return symbol_cache.SymbolCache(gate_client=gate_client, transport=transport)


def _is_rejection(obj) -> bool:
    return isinstance(obj, RejectionReason)


# --------------------------------------------------------------------------- #
# Purity / boundary guard — no direct httpx, gate_client is INJECTED.
# --------------------------------------------------------------------------- #


def test_symbol_cache_does_not_import_httpx_directly():
    """The cache speaks to the venue through the injected gate_client, never via a
    direct httpx import / a self-constructed client (design: symbol_cache <-
    gate_client; the transport seam is gate_client's)."""
    assert not hasattr(symbol_cache, "httpx"), (
        "symbol_cache must not import httpx directly; it uses the injected gate_client"
    )


# --------------------------------------------------------------------------- #
# Known ticker resolves to MERGED metadata (public session + auth detail).
# Requirements 3.3, 5.1 (data surfaced).
# --------------------------------------------------------------------------- #


def test_known_ticker_resolves_with_merged_session_and_detail(monkeypatch):
    """A known in-category ticker resolves to one SymbolInfo merging the PUBLIC
    session status (open/closed + next_open_time, from /tradfi/symbols) with the
    AUTHENTICATED detail (leverage / volume bounds / swap rates, from
    /tradfi/symbols/detail)."""
    _set_creds(monkeypatch)
    cache = _make_cache(broker_gate_fakes.make_mock_transport())

    info = cache.resolve("AAPL")

    assert isinstance(info, SymbolInfo), f"expected SymbolInfo, got {info!r}"
    assert info.ticker == "AAPL"
    assert info.category == str(US_STOCK_CATEGORY_ID)
    # --- session status merged in from the PUBLIC /tradfi/symbols feed ---
    assert info.status == "open"
    assert info.next_open_time == 0
    # --- enforcement metadata merged in from the AUTHENTICATED detail feed ---
    assert info.leverage == 5.0
    assert info.trade_mode == "4"  # full trading (surfaced for 5.1/1.11)
    assert info.min_order_volume == 0.01
    assert info.max_order_volume == 100.0
    assert info.price_precision == 2


def test_resolution_surfaces_per_symbol_swap_rates(monkeypatch):
    """Req 3.3: the cache holds per-symbol financing/swap rates (buy + sell) so a
    downstream consumer can read them — they are NOT assumed constant."""
    _set_creds(monkeypatch)
    cache = _make_cache(broker_gate_fakes.make_mock_transport())

    info = cache.resolve("AAPL")

    assert isinstance(info, SymbolInfo)
    # Verbatim venue swap rates parsed at the boundary (string -> float).
    assert info.buy_swap_rate == -0.0021
    assert info.sell_swap_rate == -0.0008


def test_resolution_surfaces_leverage_and_trade_mode_for_validation(monkeypatch):
    """Req 5.1: the cache SURFACES leverage + trade_mode (it does not itself
    reject); validation (3.2) consumes them to reject disabled / sub-floor names.
    A closed-session, lower-leverage name (TSLA: trade_mode 3 close-only,
    leverage 3) still resolves with that data exposed."""
    _set_creds(monkeypatch)
    cache = _make_cache(broker_gate_fakes.make_mock_transport())

    info = cache.resolve("TSLA")

    assert isinstance(info, SymbolInfo)
    assert info.leverage == 3.0
    assert info.trade_mode == "3"  # close-only — surfaced, not rejected here
    # session status merged from the public feed: TSLA is closed w/ a next open.
    assert info.status == "closed"
    assert info.next_open_time == 1748620800


# --------------------------------------------------------------------------- #
# Out-of-category symbol is excluded / rejected. Requirement 4.2.
#
# LOAD-BEARING ISOLATION (kiro-review Check 11). The DEFAULT fixtures hide the
# category filter: the public symbols.json lists EURUSD (category 1) but the
# authenticated symbols_detail.json has NO EURUSD row, so even with the category
# filter DELETED, EURUSD would have no detail row to parse and the merge would
# drop it anyway — the FIXTURE GAP, not the filter, would exclude it, so a
# regression that removed the filter would ship green. To make these tests fail
# IFF the filter is removed, we override BOTH venue feeds so EURUSD has a PUBLIC
# /tradfi/symbols row AND an authenticated /tradfi/symbols/detail row carrying
# category_id=1. With both present, the ONLY thing keeping EURUSD out of the
# tradable set / making it resolve to OUT_OF_CATEGORY is the category filter
# itself: delete the filter and EURUSD parses into a SymbolInfo, merges, and
# would enter tradable_symbols() / resolve to a SymbolInfo.
# --------------------------------------------------------------------------- #


def _detail_row(symbol: str, *, category_id: int, desc: str = "") -> dict:
    """A full /tradfi/symbols/detail row that parses into a SymbolInfo (mirrors
    the symbols_detail.json fixture shape). ``category_id`` is carried verbatim so
    an out-of-category name is INDISTINGUISHABLE from an in-category one to every
    step EXCEPT the category filter — that's what makes the filter load-bearing."""
    return {
        "symbol": symbol,
        "symbol_desc": desc or f"{symbol} desc",
        "category_id": category_id,
        "trade_mode": 4,
        "max_order_volume": "100",
        "min_order_volume": "0.01",
        "contract_volume": "1",
        "leverage": "5",
        "price_precision": "2",
        "price_sl_level": "0.5",
        "swap_cost_type": "1",
        "buy_swap_cost_rate": "-0.0021",
        "sell_swap_cost_rate": "-0.0008",
        "swap_cost_3day": "3",
        "trade_timezone": "America/New_York",
    }


def _public_row(symbol: str, *, category_id: int, desc: str = "") -> dict:
    """A /tradfi/symbols (public) universe row, mirroring symbols.json."""
    return {
        "symbol": symbol,
        "symbol_desc": desc or f"{symbol} desc",
        "category_id": category_id,
        "status": "open",
        "trade_mode": 4,
        "next_open_time": 0,
        "price_precision": "2",
        "settlement_currency": "USD",
    }


def _universe_with_resolvable_eurusd():
    """Override feeds where the out-of-category name (EURUSD, category 1) is FULLY
    resolvable but for the filter: it has BOTH a public row AND a detail row. The
    in-category names (AAPL, MSFT) are present in both feeds too. Returns the
    ``overrides=`` map for ``make_mock_transport`` (public + detail).

    Defeats the fixture-gap escape hatch (default symbols_detail.json lacks any
    EURUSD row): IF the category filter were removed, EURUSD's detail row WOULD
    parse + merge and EURUSD would leak into the tradable set / resolve.
    """
    public = [
        _public_row("AAPL", category_id=2, desc="Apple Inc."),
        _public_row("MSFT", category_id=2, desc="Microsoft Corporation"),
        _public_row("EURUSD", category_id=1, desc="Euro / US Dollar"),
    ]
    detail = [
        _detail_row("AAPL", category_id=2, desc="Apple Inc."),
        _detail_row("MSFT", category_id=2, desc="Microsoft Corporation"),
        # The load-bearing row: EURUSD has a detail row, so the fixture gap can
        # no longer be what drops it — only the category filter can.
        _detail_row("EURUSD", category_id=1, desc="Euro / US Dollar"),
    ]
    return {
        ("GET", "/tradfi/symbols"): public,
        ("GET", "/tradfi/symbols/detail"): detail,
    }


def test_out_of_category_symbol_is_rejected(monkeypatch):
    """Req 4.2: EURUSD is category 1 (Forex), outside the US-stock CFD category
    (2). It must be excluded from the tradable set and a resolve() returns a
    structured rejection, never a SymbolInfo.

    LOAD-BEARING: EURUSD is given BOTH a public row AND a detail row (category 1),
    so it is fully parseable — the ONLY thing that excludes it is the category
    filter. (With the default fixtures, the missing EURUSD detail row would drop
    it regardless, so this test would pass even with the filter deleted.)"""
    _set_creds(monkeypatch)
    cache = _make_cache(
        broker_gate_fakes.make_mock_transport(
            overrides=_universe_with_resolvable_eurusd()
        )
    )

    result = cache.resolve("EURUSD")

    assert _is_rejection(result), f"expected rejection for EURUSD, got {result!r}"
    assert result.code == RejectionCode.OUT_OF_CATEGORY


def test_tradable_set_excludes_out_of_category(monkeypatch):
    """Req 4.2: the built tradable-symbol set holds only US-stock-category names;
    a Forex name never appears in it.

    LOAD-BEARING: EURUSD has BOTH a public AND a detail row (category 1), so it
    would parse + merge into the tradable set IF the category filter were removed.
    The filter — not a fixture gap — is what keeps it out, so deleting the filter
    fails this test."""
    _set_creds(monkeypatch)
    cache = _make_cache(
        broker_gate_fakes.make_mock_transport(
            overrides=_universe_with_resolvable_eurusd()
        )
    )

    symbols = cache.tradable_symbols()

    tickers = {s.ticker for s in symbols}
    assert "AAPL" in tickers and "MSFT" in tickers
    assert "EURUSD" not in tickers, "Forex (category 1) must be excluded"
    assert all(s.category == str(US_STOCK_CATEGORY_ID) for s in symbols)


def test_unknown_ticker_is_rejected(monkeypatch):
    """A ticker absent from the venue universe resolves to a structured
    UNKNOWN_SYMBOL rejection (after a refresh-on-miss attempt), never a guess."""
    _set_creds(monkeypatch)
    cache = _make_cache(broker_gate_fakes.make_mock_transport())

    result = cache.resolve("NOPE")

    assert _is_rejection(result)
    assert result.code == RejectionCode.UNKNOWN_SYMBOL


# --------------------------------------------------------------------------- #
# Identity is TICKER-ONLY — a misleading description never changes resolution.
# Requirement 4.1.
# --------------------------------------------------------------------------- #


def test_identity_is_ticker_only_misleading_description_ignored(monkeypatch):
    """Req 4.1: identity is the US ticker, NEVER the free-text symbol_desc. Inject
    a venue universe where AAPL's description is a WRONG company ("American
    Airlines") — resolution by ticker "AAPL" must still return the AAPL row, and
    a lookup by the description text must NOT resolve to it."""
    _set_creds(monkeypatch)
    # Universe with a deliberately misleading description on AAPL.
    misleading_symbols = [
        {
            "symbol": "AAPL",
            "symbol_desc": "American Airlines Group",  # ⚠ wrong company
            "category_id": 2,
            "status": "open",
            "trade_mode": 4,
            "next_open_time": 0,
            "price_precision": "2",
            "settlement_currency": "USD",
        }
    ]
    misleading_detail = [
        {
            "symbol": "AAPL",
            "symbol_desc": "American Airlines Group",  # ⚠ wrong company
            "category_id": 2,
            "trade_mode": 4,
            "max_order_volume": "100",
            "min_order_volume": "0.01",
            "contract_volume": "1",
            "leverage": "5",
            "price_precision": "2",
            "price_sl_level": "0.5",
            "swap_cost_type": "1",
            "buy_swap_cost_rate": "-0.0021",
            "sell_swap_cost_rate": "-0.0008",
            "swap_cost_3day": "3",
            "trade_timezone": "America/New_York",
        }
    ]
    transport = broker_gate_fakes.make_mock_transport(
        overrides={
            ("GET", "/tradfi/symbols"): misleading_symbols,
            ("GET", "/tradfi/symbols/detail"): misleading_detail,
        }
    )
    cache = _make_cache(transport)

    # Resolution by TICKER works regardless of the wrong description.
    info = cache.resolve("AAPL")
    assert isinstance(info, SymbolInfo)
    assert info.ticker == "AAPL"

    # Resolution by the DESCRIPTION text must NOT resolve to AAPL (identity is the
    # ticker only — the description is never an identity key).
    by_desc = cache.resolve("American Airlines Group")
    assert _is_rejection(by_desc), (
        "the free-text description must never be an identity key (Req 4.1)"
    )


# --------------------------------------------------------------------------- #
# Detail is fetched in batches of <=10 symbols. design Performance & Scalability.
# --------------------------------------------------------------------------- #


def test_detail_fetched_in_batches_of_at_most_ten(monkeypatch):
    """The authenticated /tradfi/symbols/detail read is batched <=10 symbols per
    call (design: ~45 calls for 441 names). Build a 23-name in-category universe
    and assert every detail request carries no more than 10 symbols, and that all
    23 are covered across the batches."""
    _set_creds(monkeypatch)

    # 23 synthetic in-category tickers -> expect ceil(23/10) = 3 detail calls.
    tickers = [f"SYM{i:02d}" for i in range(23)]
    big_symbols = [
        {
            "symbol": t,
            "symbol_desc": f"{t} Corp",
            "category_id": 2,
            "status": "open",
            "trade_mode": 4,
            "next_open_time": 0,
            "price_precision": "2",
            "settlement_currency": "USD",
        }
        for t in tickers
    ]
    big_detail = [
        {
            "symbol": t,
            "symbol_desc": f"{t} Corp",
            "category_id": 2,
            "trade_mode": 4,
            "max_order_volume": "100",
            "min_order_volume": "0.01",
            "contract_volume": "1",
            "leverage": "5",
            "price_precision": "2",
            "price_sl_level": "0.5",
            "swap_cost_type": "1",
            "buy_swap_cost_rate": "-0.0021",
            "sell_swap_cost_rate": "-0.0008",
            "swap_cost_3day": "3",
            "trade_timezone": "America/New_York",
        }
        for t in tickers
    ]

    detail_batch_sizes: list[int] = []
    seen_symbols: set[str] = set()

    def handler(request):
        import httpx as _httpx  # local to the test harness; NOT a cache import

        path = request.url.path
        if path.startswith("/api/v4"):
            path = path[len("/api/v4") :]
        if path == "/tradfi/symbols":
            return _httpx.Response(200, json=big_symbols)
        if path == "/tradfi/symbols/detail":
            raw = request.url.params.get("symbols", "")
            batch = [s for s in raw.split(",") if s]
            detail_batch_sizes.append(len(batch))
            seen_symbols.update(batch)
            wanted = set(batch)
            return _httpx.Response(
                200, json=[d for d in big_detail if d["symbol"] in wanted]
            )
        return _httpx.Response(404, json={"label": "NOT_FOUND", "message": path})

    import httpx

    transport = httpx.MockTransport(handler)
    cache = _make_cache(transport)

    # Force a full build of the universe + all detail.
    symbols = cache.tradable_symbols()

    assert len(symbols) == 23
    assert detail_batch_sizes, "no detail batches were issued"
    assert all(n <= 10 for n in detail_batch_sizes), (
        f"a detail batch exceeded 10 symbols: {detail_batch_sizes}"
    )
    assert seen_symbols == set(tickers), "not every symbol was covered by a batch"


# --------------------------------------------------------------------------- #
# Refresh-on-miss repopulates the cache. design freshness/refresh policy.
# --------------------------------------------------------------------------- #


def test_refresh_on_miss_repopulates_the_cache(monkeypatch):
    """A validation miss (an unknown ticker that LATER appears at the venue)
    triggers a refresh that repopulates the cache so the now-present ticker
    resolves. First the venue knows only AAPL; after the venue gains GOOG, a
    resolve("GOOG") miss refreshes and then resolves."""
    _set_creds(monkeypatch)

    aapl_sym = {
        "symbol": "AAPL",
        "symbol_desc": "Apple Inc.",
        "category_id": 2,
        "status": "open",
        "trade_mode": 4,
        "next_open_time": 0,
        "price_precision": "2",
        "settlement_currency": "USD",
    }
    goog_sym = {
        "symbol": "GOOG",
        "symbol_desc": "Alphabet Inc.",
        "category_id": 2,
        "status": "open",
        "trade_mode": 4,
        "next_open_time": 0,
        "price_precision": "2",
        "settlement_currency": "USD",
    }

    def _detail_row(sym):
        return {
            "symbol": sym["symbol"],
            "symbol_desc": sym["symbol_desc"],
            "category_id": 2,
            "trade_mode": 4,
            "max_order_volume": "100",
            "min_order_volume": "0.01",
            "contract_volume": "1",
            "leverage": "5",
            "price_precision": "2",
            "price_sl_level": "0.5",
            "swap_cost_type": "1",
            "buy_swap_cost_rate": "-0.0021",
            "sell_swap_cost_rate": "-0.0008",
            "swap_cost_3day": "3",
            "trade_timezone": "America/New_York",
        }

    # Mutable venue state: GOOG appears only after the flag flips.
    venue = {"has_goog": False}

    def handler(request):
        import httpx as _httpx

        path = request.url.path
        if path.startswith("/api/v4"):
            path = path[len("/api/v4") :]
        universe = [aapl_sym] + ([goog_sym] if venue["has_goog"] else [])
        if path == "/tradfi/symbols":
            return _httpx.Response(200, json=universe)
        if path == "/tradfi/symbols/detail":
            raw = request.url.params.get("symbols", "")
            wanted = {s for s in raw.split(",") if s}
            rows = [_detail_row(s) for s in universe if s["symbol"] in wanted]
            return _httpx.Response(200, json=rows)
        return _httpx.Response(404, json={"label": "NOT_FOUND", "message": path})

    import httpx

    transport = httpx.MockTransport(handler)
    cache = _make_cache(transport)

    # First build: GOOG not present -> resolve misses with a structured rejection.
    first = cache.resolve("GOOG")
    assert _is_rejection(first)
    assert first.code == RejectionCode.UNKNOWN_SYMBOL

    # Venue now lists GOOG. A fresh miss must trigger a refresh that repopulates.
    venue["has_goog"] = True
    second = cache.resolve("GOOG")
    assert isinstance(second, SymbolInfo), (
        "refresh-on-miss must repopulate so the now-present ticker resolves"
    )
    assert second.ticker == "GOOG"
    assert second.leverage == 5.0


def test_resolve_after_build_uses_cache_without_refetch(monkeypatch):
    """A KNOWN ticker resolves from the cache without forcing a venue refresh on
    every call (freshness window): after the first build, a second resolve of a
    cached, present ticker issues no new /tradfi/symbols call."""
    _set_creds(monkeypatch)

    universe = [
        {
            "symbol": "AAPL",
            "symbol_desc": "Apple Inc.",
            "category_id": 2,
            "status": "open",
            "trade_mode": 4,
            "next_open_time": 0,
            "price_precision": "2",
            "settlement_currency": "USD",
        }
    ]
    detail = [
        {
            "symbol": "AAPL",
            "symbol_desc": "Apple Inc.",
            "category_id": 2,
            "trade_mode": 4,
            "max_order_volume": "100",
            "min_order_volume": "0.01",
            "contract_volume": "1",
            "leverage": "5",
            "price_precision": "2",
            "price_sl_level": "0.5",
            "swap_cost_type": "1",
            "buy_swap_cost_rate": "-0.0021",
            "sell_swap_cost_rate": "-0.0008",
            "swap_cost_3day": "3",
            "trade_timezone": "America/New_York",
        }
    ]
    universe_calls = {"n": 0}

    def handler(request):
        import httpx as _httpx

        path = request.url.path
        if path.startswith("/api/v4"):
            path = path[len("/api/v4") :]
        if path == "/tradfi/symbols":
            universe_calls["n"] += 1
            return _httpx.Response(200, json=universe)
        if path == "/tradfi/symbols/detail":
            return _httpx.Response(200, json=detail)
        return _httpx.Response(404, json={"label": "NOT_FOUND", "message": path})

    import httpx

    transport = httpx.MockTransport(handler)
    cache = _make_cache(transport)

    first = cache.resolve("AAPL")
    assert isinstance(first, SymbolInfo)
    calls_after_first = universe_calls["n"]
    assert calls_after_first >= 1

    # A second resolve of the cached ticker must not re-hit the universe endpoint.
    second = cache.resolve("AAPL")
    assert isinstance(second, SymbolInfo)
    assert universe_calls["n"] == calls_after_first, (
        "a cached-ticker hit must not force a venue refresh (freshness window)"
    )


# --------------------------------------------------------------------------- #
# Transport failure surfaces structurally (never raises out of the cache).
# --------------------------------------------------------------------------- #


def test_auth_failure_surfaces_structured_rejection(monkeypatch):
    """If the authenticated detail/universe read fails (auth), the cache surfaces
    a structured rejection rather than raising — the conservative posture (the
    cache never builds a tradable set it could not authenticate)."""
    _set_creds(monkeypatch)
    transport = broker_gate_fakes.make_mock_transport(fail="auth")
    cache = _make_cache(transport)

    result = cache.resolve("AAPL")
    assert _is_rejection(result), f"expected a structured rejection, got {result!r}"
