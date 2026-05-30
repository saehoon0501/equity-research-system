"""Inner-ring test for order construction (task 3.2).

Boundary: order_builder (Requirements 11, 2). Asserts the Observable from
tasks.md 3.2 + the §Components ``order_builder`` contract (design.md:349-364):

  * a synthetic LONG decision + a flat book yields a ``Label.BUY`` ``ProposedOrder``
    with a price-level ``stop_loss`` (Req 11.1/11.3);
  * a **SHORT-open** yields ``Label.BUY`` + ``Direction.SHORT`` — the broker venue
    mapping (sell-to-open), **not** a ``SELL`` (Req 11.1, ``mappers.py``);
  * the protective ``stop_loss`` is a **price level** = ``reference_price ∓
    atr × stop_loss_atr_mult``, ``atr`` read from
    ``decision.substrate.feature_values["atr"]`` (Req 11.3); a LONG stop sits
    BELOW the reference, a SHORT stop ABOVE;
  * a **reduce** (decided side opposes the held position) emits a
    ``Label.TRIM``/``SELL`` order **targeting the held ``position_id``** (Req 11.4),
    with volume **clamped ≤ the held volume** — no flatten-then-flip in a single
    order (Req 11.6);
  * volume comes from ``sizing_hint`` **capped by the survival advisory** and
    never exceeds it (Req 11.2) — the advisory is threaded by the caller (the
    Phase-2 resize-on-advisory re-build, Req 3.5); the builder never computes it
    (Req 10.2);
  * a missing ``atr`` (a reactive-contract violation) hits the **None-guard**
    (defense-in-depth, CN-3) → ``None``;
  * **HOLD** (and any non-actionable decision) yields ``None`` (Req 2.5).

Pure + deterministic against synthetic ``ReactiveDecision`` + ``Position`` +
reference price — inner-ring: no LLM, no MCP, no live DB, no ``src.survival``
(P14). The ``survival.admit`` adaptation of the built ``ProposedOrder`` is the
Phase-2 cross-spec seam (task 4.1), out of scope here.
"""

from __future__ import annotations

import math

import pytest

from src.reactive.daemon.broker_seam import Direction, Label, Position
from src.reactive.daemon.order_builder import build_order
from src.reactive.daemon.types import ProposedOrder
from src.reactive.params import DEFAULTS
from src.reactive.types import (
    CalibrationEvidence,
    DecisionSubstrate,
    ReactiveDecision,
)

# The configured protective-stop multiplier the tests anchor on
# (config._DEFAULT_STOP_LOSS_ATR_MULT). The builder reads it off the params /
# config; the tests assert the resulting price level against this constant.
_ATR_MULT = 2.0
_ATR = 3.0
_REFERENCE = 100.0


# --- Synthetic decision builders ------------------------------------------


def _substrate(atr: float | None) -> DecisionSubstrate:
    """A DecisionSubstrate whose feature_values carries ``atr`` (the real path,
    ``features.py:192``) — or omits it to exercise the None-guard (CN-3)."""
    feature_values: dict = {"trend_vote": 1.0, "drawdown_atr": 0.5}
    if atr is not None:
        feature_values["atr"] = atr
    return DecisionSubstrate(
        feature_values=feature_values,
        probability=0.72,
        effective_threshold=DEFAULTS.threshold,
        code_version=DEFAULTS.code_version,
        param_version=DEFAULTS.param_version,
        calibration=CalibrationEvidence(brier=None, reliability=None),
    )


def _decision(
    decision: str,
    direction_in: str,
    *,
    sizing_hint: float | None,
    atr: float | None = _ATR,
) -> ReactiveDecision:
    """An actionable (or HOLD) ReactiveDecision with a controllable substrate."""
    return ReactiveDecision(
        decision=decision,  # type: ignore[arg-type]
        direction_in=direction_in,  # type: ignore[arg-type]
        probability=0.72,
        sizing_hint=sizing_hint,
        non_final=True,
        reason=None if decision != "HOLD" else "invalid_direction",
        substrate=_substrate(atr),
    )


def _position(
    position_id: str, symbol: str, direction: Direction, volume: float
) -> Position:
    """A broker readout Position (the state order_builder consumes — never
    inferred, Req 11.5)."""
    return Position(
        position_id=position_id,
        symbol=symbol,
        direction=direction,
        volume=volume,
        avg_open_price=_REFERENCE,
        used_margin=10.0,
        unrealized_pnl=0.0,
    )


def _pinned():
    """A PinnedParams whose reactive_snapshot is the inner-ring DEFAULTS."""
    from src.reactive.daemon.types import PinnedParams

    return PinnedParams(reactive_snapshot=DEFAULTS, survival_snapshot={})


# --- LONG-open ------------------------------------------------------------


def test_long_open_flat_book_yields_buy_long_with_price_level_stop():
    """A LONG decision + a flat book → BUY + Direction.LONG, stop BELOW ref."""
    decision = _decision("LONG", "LONG", sizing_hint=10.0)

    order = build_order(decision, [], _REFERENCE, _pinned(), symbol="AAPL")

    assert isinstance(order, ProposedOrder)
    assert order.symbol == "AAPL"
    assert order.intent is Label.BUY
    assert order.direction is Direction.LONG
    assert order.position_id is None  # an open, not a reduce
    assert order.volume == 10.0
    # stop_loss is a PRICE LEVEL = reference - atr*mult (long stop sits below).
    assert math.isclose(order.stop_loss, _REFERENCE - _ATR * _ATR_MULT)
    assert order.stop_loss < _REFERENCE


# --- SHORT-open (the headline: BUY + SHORT, NOT SELL) ---------------------


def test_short_open_yields_buy_plus_short_not_sell():
    """SHORT-open is the venue sell-to-open: BUY + Direction.SHORT (Req 11.1)."""
    decision = _decision("SHORT", "SHORT", sizing_hint=4.0)

    order = build_order(decision, [], _REFERENCE, _pinned(), symbol="AAPL")

    assert isinstance(order, ProposedOrder)
    # The headline contract: a SHORT open is BUY+SHORT, never a SELL.
    assert order.intent is Label.BUY
    assert order.intent is not Label.SELL
    assert order.direction is Direction.SHORT
    assert order.position_id is None
    # stop_loss above the reference for a short.
    assert math.isclose(order.stop_loss, _REFERENCE + _ATR * _ATR_MULT)
    assert order.stop_loss > _REFERENCE


# --- Reduce: clamp <= held, target the position_id ------------------------


def test_reduce_clamps_volume_to_held_and_targets_position_id():
    """A LONG decision against a held SHORT reduces the SHORT, clamped <= held,
    targeting its position_id — no flatten-then-flip in one order (Req 11.6)."""
    held = _position("POS-1", "AAPL", Direction.SHORT, volume=5.0)
    # sizing_hint far exceeds the held volume; the reduce must clamp to 5.0.
    decision = _decision("LONG", "LONG", sizing_hint=100.0)

    order = build_order(decision, [held], _REFERENCE, _pinned(), symbol="AAPL")

    assert isinstance(order, ProposedOrder)
    # A reduce/close uses TRIM/SELL and targets the specific held position.
    assert order.intent in (Label.TRIM, Label.SELL)
    assert order.position_id == "POS-1"
    # Clamped to held — never exceeds it (no flatten-then-flip).
    assert order.volume <= held.volume
    assert order.volume == 5.0


def test_reduce_full_close_uses_sell_when_sizing_meets_held():
    """A reduce sized at exactly the held volume is a full close (SELL)."""
    held = _position("POS-9", "AAPL", Direction.LONG, volume=8.0)
    # Decided side SHORT opposes the held LONG → reduce the LONG fully.
    decision = _decision("SHORT", "SHORT", sizing_hint=8.0)

    order = build_order(decision, [held], _REFERENCE, _pinned(), symbol="AAPL")

    assert isinstance(order, ProposedOrder)
    assert order.position_id == "POS-9"
    assert order.intent is Label.SELL  # full close
    assert order.volume == 8.0


# --- Volume cap by survival advisory --------------------------------------


def test_volume_capped_by_survival_advisory_never_exceeds():
    """Volume = sizing_hint capped by the survival advisory max (Req 11.2)."""
    decision = _decision("LONG", "LONG", sizing_hint=10.0)

    order = build_order(
        decision, [], _REFERENCE, _pinned(), advisory_max_volume=3.0
    )

    assert isinstance(order, ProposedOrder)
    # Capped at the advisory — never the larger sizing_hint.
    assert order.volume == 3.0
    assert order.volume <= 3.0


def test_advisory_does_not_upsize_a_smaller_sizing_hint():
    """The advisory is a CAP, not a floor — a smaller sizing_hint is unchanged
    (never-upsize, Req 2.4 / P7)."""
    decision = _decision("LONG", "LONG", sizing_hint=2.0)

    order = build_order(
        decision, [], _REFERENCE, _pinned(), advisory_max_volume=9.0
    )

    assert isinstance(order, ProposedOrder)
    assert order.volume == 2.0


# --- ATR None-guard (defense-in-depth, CN-3) ------------------------------


def test_missing_atr_hits_none_guard_returns_none():
    """An actionable decision whose substrate omits ``atr`` is a reactive-contract
    violation; the None-guard degrades to no-order (defense-in-depth, CN-3)."""
    decision = _decision("LONG", "LONG", sizing_hint=5.0, atr=None)

    order = build_order(decision, [], _REFERENCE, _pinned())

    assert order is None


# --- HOLD / non-actionable -> None ----------------------------------------


def test_hold_yields_none():
    """HOLD places no order — the orchestrator records a declined trace (Req 2.5)."""
    decision = _decision("HOLD", "LONG", sizing_hint=None)

    order = build_order(decision, [], _REFERENCE, _pinned())

    assert order is None


def test_actionable_with_no_sizing_hint_yields_none():
    """A sub-threshold/HOLD decision carries no sizing_hint (sizing_hint None on
    HOLD, ``reactive/types.py``); with nothing to size, no order is built."""
    # Defensive: an actionable label but a None sizing_hint cannot be sized.
    decision = _decision("LONG", "LONG", sizing_hint=None)

    order = build_order(decision, [], _REFERENCE, _pinned())

    assert order is None


# --- Position state is from broker readouts, never inferred (Req 11.5) -----


def test_unrelated_held_position_does_not_make_an_open_a_reduce():
    """A held position in a DIFFERENT symbol does not turn a same-symbol open
    into a reduce — the builder keys the reduce on the decided symbol's held
    position only (state from broker readouts, Req 11.5)."""
    other = _position("POS-OTHER", "MSFT", Direction.LONG, volume=5.0)
    decision = _decision("LONG", "LONG", sizing_hint=6.0)

    order = build_order(decision, [other], _REFERENCE, _pinned(), symbol="AAPL")

    assert isinstance(order, ProposedOrder)
    assert order.symbol == "AAPL"
    assert order.intent is Label.BUY  # an open, not a reduce
    assert order.position_id is None
