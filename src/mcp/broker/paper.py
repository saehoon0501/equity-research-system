"""Paper/dry-run simulator (Task 3.3).

Source of truth: ``.kiro/specs/broker-cfd-adapter/design.md`` — the ``paper``
Components row ("Simulation layer"), the Architecture map (``paper -> mappers``
and ``paper -> gate_client``; ``paper`` does NOT import ``validation``), the
System Flows "paper mode" branch, and the Overview/Boundary (paper-only v0.1).
Requirement 8.2 (the venue has NO native dry-run mode, so paper mode is
simulated in-adapter: skip the order POST, price from the ticker bid/ask).

Layer position (``models -> config -> gate_client -> {mappers, symbol_cache} ->
validation -> paper -> core -> server``): ``paper`` sits just above
``validation`` and just below ``core``. It imports ONLY ``models``, ``mappers``,
and ``gate_client`` (the layers above it). It deliberately does NOT import
``validation`` — per the design and tasks.md 3.3, this component does not run
validation; ``core`` sequences validate-then-simulate so paper coverage exercises
the IDENTICAL validation + mapping path as a live send.

What this layer owns
--------------------
Given a VALIDATED ``OrderIntent`` and the current venue bid/ask, return a
structured ``OrderResult(status="simulated", ...)`` priced from the bid/ask
WITHOUT invoking the venue order-create / position-close operation. It issues NO
POST to ``/tradfi/orders`` or ``/tradfi/positions/{id}/close`` — that is the
whole point of paper mode (Req 8.1/8.2). The only venue I/O it may perform is an
OPTIONAL read-only GET on ``/tradfi/symbols/{s}/tickers`` to fetch bid/ask when
the caller does not pass them in.

Pricing rule (side-aware) — REUSES ``mappers.map_decision_to_action`` to derive
the venue side rather than re-deriving the counterintuitive 1=SELL/2=BUY
inversion here (single source of truth for the side-enum guard, per ``mappers``):

* BUY + LONG  -> buy-to-open  (venue ``side`` 2 = SIDE_BUY)  -> fills at the ASK.
* BUY + SHORT -> sell-to-open (venue ``side`` 1 = SIDE_SELL) -> fills at the BID.
* TRIM/SELL closing a LONG  -> sell-to-close -> fills at the BID.
* TRIM/SELL closing a SHORT -> buy-to-close  -> fills at the ASK.

(The marketable side always crosses the spread the conservative way: a buy lifts
the ASK, a sell hits the BID. A close's marketable side is the OPPOSITE of the
position's direction — closing a long sells, closing a short buys.)

``fill_volume`` is the REQUESTED volume, surfaced verbatim — this adapter never
invents or upsizes a volume (Req 7.1 posture). For a full SELL (no request
``volume``), the closed position's volume is surfaced when the caller supplies it
(``position_volume``); otherwise ``fill_volume`` stays ``None`` (the close
request, not a fabricated number). ``order_id``/``position_id`` are left ``None``
— a simulation creates no venue ids.
"""

from __future__ import annotations

from typing import Optional

import httpx

# Domain types — imported BY NAME (production posture: broker dir on sys.path[0]).
from models import Direction, Label, OrderIntent, OrderResult

# Reused layers above ``paper`` in the dependency direction. ``mappers`` derives
# the venue side (no local re-derivation of the side-enum inversion);
# ``gate_client`` is the read-only ticker fetch seam (injectable transport).
import gate_client as _gate_client
import mappers

# NOTE: ``validation`` is intentionally NOT imported (design: paper does not run
# validation; core sequences validate-then-simulate).


def _fill_price_from_action(intent: OrderIntent, *, bid: float, ask: float) -> float:
    """Pick the simulated fill price from bid/ask using the mapped venue action.

    Reuses ``mappers.map_decision_to_action`` so the 1=SELL/2=BUY side-enum guard
    lives in exactly one place. The marketable side crosses the spread the
    conservative way.
    """
    if intent.decision is Label.BUY:
        # Reuse the mapper to derive the open side (LONG=buy=side 2 -> ASK;
        # SHORT=sell=side 1 -> BID). Read the side off the mapped venue body.
        action = mappers.map_decision_to_action(intent)
        side = action.body.get("side")
        return ask if side == mappers.SIDE_BUY else bid

    # TRIM / SELL = close. The marketable side is the OPPOSITE of the position's
    # direction: closing a LONG sells (-> BID); closing a SHORT buys (-> ASK).
    # (We still call the mapper so the close action is exercised on the identical
    # path live uses, even though the close body carries no side field.)
    mappers.map_decision_to_action(intent)
    return bid if intent.direction is Direction.LONG else ask


def _fill_volume(intent: OrderIntent, *, position_volume: Optional[float]) -> Optional[float]:
    """The simulated fill volume = the REQUESTED volume, verbatim (never upsized).

    BUY / TRIM carry an explicit request ``volume``. A full SELL carries none
    (``close_volume`` null = full close); surface the closed position's volume
    when the caller supplies it, else ``None`` (do not fabricate a number).
    """
    if intent.volume is not None:
        return intent.volume
    return position_volume


def simulate(
    intent: OrderIntent,
    *,
    bid: Optional[float] = None,
    ask: Optional[float] = None,
    position_volume: Optional[float] = None,
    transport: Optional[httpx.BaseTransport] = None,
) -> OrderResult:
    """Simulate a VALIDATED ``OrderIntent`` against the current bid/ask (Req 8.2).

    Parameters
    ----------
    intent:
        A fully-specified, already-validated ``OrderIntent`` (this layer does NOT
        re-validate — ``core`` runs the chain first).
    bid, ask:
        The current venue bid/ask. If BOTH are omitted, they are fetched via an
        injected read-only GET on ``/tradfi/symbols/{symbol}/tickers`` (still NO
        order POST). Passing them in keeps the simulator a pure function.
    position_volume:
        For a full SELL (no request volume), the closed position's volume, if the
        caller knows it — surfaced verbatim as ``fill_volume`` (never invented).
    transport:
        Injectable ``httpx.BaseTransport`` for the optional ticker fetch (tests
        pass the Task 1.4 ``make_mock_transport(...)``); production passes ``None``.

    Returns
    -------
    ``OrderResult(status="simulated", fill_price=<priced from bid/ask>,
    fill_volume=<requested volume>, raw=<ticker bid/ask>)``. NEVER issues a venue
    order-create / position-close POST.
    """
    if bid is None and ask is None:
        bid, ask = _fetch_bid_ask(intent.symbol, transport=transport)

    if bid is None or ask is None:
        # Defensive: a half-specified bid/ask is a programming error from the
        # caller. We surface a structured simulated result with no price rather
        # than guessing or transmitting anything.
        raise ValueError(
            "simulate requires both bid and ask, or neither (to fetch); "
            f"got bid={bid!r}, ask={ask!r}"
        )

    fill_price = _fill_price_from_action(intent, bid=bid, ask=ask)
    fill_volume = _fill_volume(intent, position_volume=position_volume)

    return OrderResult(
        status="simulated",
        order_id=None,  # a simulation creates no venue order id.
        position_id=intent.position_id,  # echo the caller's id for a close.
        fill_price=fill_price,
        fill_volume=fill_volume,
        raw={
            "simulated": True,
            "bid": bid,
            "ask": ask,
            "priced_side": "ask" if fill_price == ask else "bid",
        },
    )


def _fetch_bid_ask(
    symbol: str, *, transport: Optional[httpx.BaseTransport]
) -> tuple[Optional[float], Optional[float]]:
    """Read-only GET on ``/tradfi/symbols/{symbol}/tickers`` -> (bid, ask).

    Issues a single signed GET (NO order POST). On any transport error the
    bid/ask come back ``None`` so the caller surfaces the programming/availability
    gap rather than transmitting anything. Venue numerics arrive as strings; we
    parse to float at this boundary (P13 — the adapter validates its own types).
    """
    outcome = _gate_client.get(
        f"/tradfi/symbols/{symbol}/tickers", transport=transport
    )
    if getattr(outcome, "ok", False) is not True:
        return None, None
    data = outcome.data
    if not isinstance(data, dict):
        return None, None
    bid = data.get("bid_price")
    ask = data.get("ask_price")
    return (
        float(bid) if bid is not None else None,
        float(ask) if ask is not None else None,
    )


__all__ = ["simulate"]
