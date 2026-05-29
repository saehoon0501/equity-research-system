"""Unit tests for the paper/dry-run simulator (Task 3.3).

Covers the design "paper" component (Simulation layer) + Requirement 8.2:

- Given a VALIDATED ``OrderIntent`` and the current ticker bid/ask, return a
  structured ``OrderResult(status="simulated", ...)`` priced from the venue
  bid/ask WITHOUT invoking the venue order-create / position-close operation
  (no POST to ``/tradfi/orders`` or ``/tradfi/positions/{id}/close``).
- Pricing by side (reusing ``mappers`` to derive the venue action/side, never
  re-deriving the 1=SELL/2=BUY inversion locally):
  * BUY + LONG  (buy-to-open,  side 2) fills at the ASK.
  * BUY + SHORT (sell-to-open, side 1) fills at the BID.
  * TRIM/SELL closing a LONG  fills at the BID (sell-to-close).
  * TRIM/SELL closing a SHORT fills at the ASK (buy-to-close).
- ``status`` is ``"simulated"`` (never ``"filled"``).
- ``fill_volume`` equals the REQUESTED volume — never invented / upsized (Req
  7.1 posture); a full SELL surfaces the closed position's volume if available,
  else the close-request volume.
- This component does NOT run validation (core sequences validate->simulate);
  it remains unit-testable against the Task 1.4 mock and issues NO order POST.

Test-run mechanism (canonical broker pytest command):
    PYTHONSAFEPATH=1 uv run --directory src/mcp/broker python -m pytest \\
        tests/unit/mcp/test_broker_paper.py -q

The broker runs in its own uv venv (carries ``mcp`` / ``httpx``); the repo root is
NOT on ``sys.path``. This test loads ``paper.py`` and its dependencies by path
(importlib-by-path, under unique module aliases) to avoid module-name collisions,
mirroring ``test_broker_mappers.py`` / ``test_broker_gate_client.py``. The
LOAD-BEARING ordering rule (tasks.md Implementation Notes 2.2): load ``models.py``
under its CANONICAL alias ``models`` FIRST so every dependent module's
``from models import ...`` reuses the SAME module instance (identity checks hold).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import httpx
import pytest

# Repo root: tests/unit/mcp/test_broker_paper.py -> parents[3] == repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_BROKER_DIR = _REPO_ROOT / "src" / "mcp" / "broker"
# paper / mappers / gate_client do by-name sibling imports (`from models import
# ...`, `import config`) — exactly the production posture (`python server.py`
# runs with the broker dir on sys.path[0]). The broker uv venv does NOT put the
# broker dir on sys.path, so seed it here so the sibling imports resolve.
if str(_BROKER_DIR) not in sys.path:
    sys.path.insert(0, str(_BROKER_DIR))


def _load_by_path(alias: str, path: Path):
    spec = importlib.util.spec_from_file_location(alias, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    spec.loader.exec_module(module)
    return module


# The 1.4 mock transport + fixture loader (we inject this and assert NO POST).
_FAKES_PATH = _REPO_ROOT / "tests" / "unit" / "mcp" / "broker_gate_fakes.py"
broker_gate_fakes = _load_by_path("broker_gate_fakes", _FAKES_PATH)

# LOAD-BEARING: load the domain types FIRST under the canonical alias ``models``
# so the mapper / paper modules' ``from models import ...`` reuse THIS instance
# (one canonical set of enums/dataclasses; identity checks do not spuriously fail).
broker_models = _load_by_path("models", _BROKER_DIR / "models.py")

# Dependencies the paper simulator reuses. Loaded so they share the ``models``
# instance above. ``gate_client`` does `import config` so config must resolve too.
_load_by_path("config", _BROKER_DIR / "config.py")
gate_client = _load_by_path("gate_client", _BROKER_DIR / "gate_client.py")
mappers = _load_by_path("mappers", _BROKER_DIR / "mappers.py")

# The unit-under-test (its `from models import ...` / `import mappers` reuse the
# instances above).
paper = _load_by_path("broker_paper", _BROKER_DIR / "paper.py")

Label = broker_models.Label
Direction = broker_models.Direction
OrderType = broker_models.OrderType
OrderIntent = broker_models.OrderIntent
OrderResult = broker_models.OrderResult


# Ticker bid/ask from the recorded fixture (tests/fixtures/gate/symbol_tickers.json).
_TICKER = broker_gate_fakes.load_fixture("symbol_tickers.json")
_BID = float(_TICKER["bid_price"])  # 212.34
_ASK = float(_TICKER["ask_price"])  # 212.41


# --------------------------------------------------------------------------- #
# A transport that RECORDS every request so we can assert NO order/close POST.
# --------------------------------------------------------------------------- #


class _RecordingTransport(httpx.BaseTransport):
    """Wraps the 1.4 mock transport, recording (method, path) of every request.

    A leaked order-create / position-close POST would show up here; the paper
    simulator must issue ZERO POSTs to ``/tradfi/orders`` or
    ``/tradfi/positions/{id}/close``.
    """

    def __init__(self) -> None:
        self._inner = broker_gate_fakes.make_mock_transport()
        self.requests: list[tuple[str, str]] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.startswith("/api/v4"):
            path = path[len("/api/v4"):]
        self.requests.append((request.method.upper(), path))
        return self._inner.handle_request(request)

    def order_or_close_posts(self) -> list[tuple[str, str]]:
        return [
            (m, p)
            for (m, p) in self.requests
            if m == "POST"
            and (p == "/tradfi/orders" or p.endswith("/close"))
        ]


def _buy_long() -> OrderIntent:
    return OrderIntent(
        decision=Label.BUY, symbol="AAPL", direction=Direction.LONG, volume=1.0
    )


def _buy_short() -> OrderIntent:
    return OrderIntent(
        decision=Label.BUY, symbol="AAPL", direction=Direction.SHORT, volume=2.0
    )


def _trim_long() -> OrderIntent:
    return OrderIntent(
        decision=Label.TRIM,
        symbol="AAPL",
        direction=Direction.LONG,
        volume=0.5,
        position_id="POS-500001",
    )


def _sell_long() -> OrderIntent:
    return OrderIntent(
        decision=Label.SELL,
        symbol="AAPL",
        direction=Direction.LONG,
        position_id="POS-500001",
    )


def _sell_short() -> OrderIntent:
    return OrderIntent(
        decision=Label.SELL,
        symbol="AAPL",
        direction=Direction.SHORT,
        position_id="POS-500002",
    )


# --------------------------------------------------------------------------- #
# Status — always "simulated", never "filled".
# --------------------------------------------------------------------------- #


def test_buy_long_returns_simulated_status_not_filled():
    result = paper.simulate(_buy_long(), bid=_BID, ask=_ASK)
    assert isinstance(result, OrderResult)
    assert result.status == "simulated"
    assert result.status != "filled"


# --------------------------------------------------------------------------- #
# Pricing by side (reuses mappers to derive the venue side).
# --------------------------------------------------------------------------- #


def test_buy_long_fills_at_ask():
    """BUY + LONG = buy-to-open (side 2) -> fills at the ASK."""
    result = paper.simulate(_buy_long(), bid=_BID, ask=_ASK)
    assert result.fill_price == _ASK
    assert result.fill_price != _BID  # load-bearing: wrong side would fail


def test_buy_short_fills_at_bid():
    """BUY + SHORT = sell-to-open (side 1) -> fills at the BID."""
    result = paper.simulate(_buy_short(), bid=_BID, ask=_ASK)
    assert result.fill_price == _BID
    assert result.fill_price != _ASK  # load-bearing: wrong side would fail


def test_trim_close_long_fills_at_bid():
    """TRIM closing a LONG = sell-to-close -> fills at the BID."""
    result = paper.simulate(_trim_long(), bid=_BID, ask=_ASK)
    assert result.fill_price == _BID
    assert result.fill_price != _ASK


def test_sell_close_short_fills_at_ask():
    """SELL closing a SHORT = buy-to-close -> fills at the ASK."""
    result = paper.simulate(_sell_short(), bid=_BID, ask=_ASK)
    assert result.fill_price == _ASK
    assert result.fill_price != _BID


# --------------------------------------------------------------------------- #
# fill_volume = requested volume; never invented / upsized.
# --------------------------------------------------------------------------- #


def test_buy_fill_volume_equals_requested_volume():
    result = paper.simulate(_buy_short(), bid=_BID, ask=_ASK)
    assert result.fill_volume == 2.0  # the requested volume, verbatim


def test_trim_fill_volume_equals_requested_partial_volume():
    result = paper.simulate(_trim_long(), bid=_BID, ask=_ASK)
    assert result.fill_volume == 0.5


def test_full_sell_surfaces_closed_position_volume_when_available():
    """A full SELL has no request volume; when the closed position's volume is
    supplied it is surfaced (never upsized / invented)."""
    result = paper.simulate(
        _sell_long(), bid=_BID, ask=_ASK, position_volume=1.0
    )
    assert result.fill_volume == 1.0


def test_full_sell_without_position_volume_does_not_invent_a_volume():
    """With no request volume and no known position volume, the simulator must
    NOT fabricate a fill_volume (it surfaces the close request: None)."""
    result = paper.simulate(_sell_long(), bid=_BID, ask=_ASK)
    assert result.fill_volume is None


# --------------------------------------------------------------------------- #
# CRUCIAL: paper mode issues NO order-create / position-close POST.
# --------------------------------------------------------------------------- #


def test_buy_issues_no_order_post():
    rec = _RecordingTransport()
    paper.simulate(_buy_long(), bid=_BID, ask=_ASK, transport=rec)
    assert rec.order_or_close_posts() == [], (
        f"paper mode leaked a venue order/close POST: {rec.requests!r}"
    )


def test_close_issues_no_close_post():
    rec = _RecordingTransport()
    paper.simulate(_sell_long(), bid=_BID, ask=_ASK, transport=rec)
    assert rec.order_or_close_posts() == [], (
        f"paper mode leaked a venue close POST: {rec.requests!r}"
    )


def test_simulate_with_fetched_bid_ask_still_issues_no_order_post(monkeypatch):
    """If the simulator fetches bid/ask via the injected gate_client GET, it may
    issue a GET on /tradfi/symbols/{s}/tickers — but STILL no order/close POST."""
    monkeypatch.setenv("GATE_API_KEY", "k-test")
    monkeypatch.setenv("GATE_API_SECRET", "s-test")
    rec = _RecordingTransport()
    result = paper.simulate(_buy_long(), transport=rec)
    assert result.status == "simulated"
    assert result.fill_price == _ASK  # priced from the fetched ASK
    # No order-create / close POST leaked.
    assert rec.order_or_close_posts() == [], (
        f"paper mode leaked a venue order/close POST: {rec.requests!r}"
    )
    # The only request issued was the read-only tickers GET.
    assert all(m == "GET" for (m, _p) in rec.requests), rec.requests


# --------------------------------------------------------------------------- #
# Reuse of mappers (no local re-derivation of the side-enum inversion).
# --------------------------------------------------------------------------- #


def test_paper_reuses_mappers_action_for_side(monkeypatch):
    """The simulator must derive the side from ``mappers.map_decision_to_action``
    rather than re-deriving it. Monkeypatching the mapper flips the simulated
    price, proving the simulator routes through it."""
    real = mappers.map_decision_to_action

    def _swapped(intent):
        # Flip LONG<->SHORT so a BUY-long would map to a sell-to-open (side 1).
        flipped = broker_models.OrderIntent(
            decision=intent.decision,
            symbol=intent.symbol,
            direction=(
                Direction.SHORT
                if intent.direction is Direction.LONG
                else Direction.LONG
            ),
            volume=intent.volume,
            position_id=intent.position_id,
            order_type=intent.order_type,
            trigger_price=intent.trigger_price,
        )
        return real(flipped)

    monkeypatch.setattr(paper.mappers, "map_decision_to_action", _swapped)
    result = paper.simulate(_buy_long(), bid=_BID, ask=_ASK)
    # With the mapper swapped to sell-to-open, a BUY-long now prices at the BID.
    assert result.fill_price == _BID
