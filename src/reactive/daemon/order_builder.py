"""Order construction — the pure decision→order translator (task 3.2).

Boundary: order_builder (Requirements 11, 2). Source of truth:
``.kiro/specs/execution-daemon/design.md`` §"Control — ``order_builder``"
(lines 349-364) + the Requirements-Traceability rows 11.1-11.6 / 2.2.

What this module is
-------------------
A **pure function, no I/O** turning a reactive ``ReactiveDecision`` + the current
broker-readout positions + the candidate's ``reference_price`` + the pinned
params into a single **daemon-owned ``ProposedOrder``** (``types.ProposedOrder``,
BL-3 — ``survival.admit`` reads its fields but does not own the type; the field
adaptation to survival's landed ``admit`` shape is the Phase-2 cross-spec seam,
task 4.1). Built daemon-side so this stays genuinely **Phase-1 inner-ring
testable** with no ``src.survival`` import (P14).

The §13 walk (design §System Flows) runs ``order_builder`` only on an
**actionable** decision (caller skips HOLD), after ``decide``, before the
per-order ``survival.admit`` veto. The order this builds is a *legal candidate*,
not a survival guarantee — ``admit`` still independently vetoes downstream.

Acceptance contract (Req 11.x)
------------------------------
* **11.1 intent + direction.** The order's ``intent`` (P9 ``Label`` BUY/TRIM/SELL)
  and ``direction`` (broker ``Direction``) together express open/reduce on the
  decided side. Opening short exposure is ``intent=BUY`` with ``Direction.SHORT``
  (the venue sell-to-open mapping, ``mappers.py``), **not** a ``SELL``. A
  ``SELL``/``TRIM`` is emitted only to **reduce/close an opposing held position**.
* **11.2 volume.** ``volume`` is the advisory ``sizing_hint`` **capped by the
  survival advisory max** (threaded by the caller — Phase-2 resize-on-advisory,
  Req 3.5 — since the daemon never *computes* a survival/sizing value, Req 10.2)
  and never exceeds it. The advisory is a **cap, not a floor** (never-upsize, P7).
* **11.3 stop_loss PRICE LEVEL.** ``stop_loss = reference_price ∓ (atr ×
  stop_loss_atr_mult)`` — BELOW the reference for a long, ABOVE for a short —
  reading ``atr`` from ``decision.substrate.feature_values["atr"]`` (the real
  landed path, ``features.py:192``). The SL is an **order parameter** the daemon
  owns (survival + reactive both disclaim it), so computing it is not a P7
  re-computation; it lets the order pass survival's mandatory-stop check by
  construction.
* **11.4 position targeting.** A reduce/close sets ``position_id`` to the specific
  held position; an open leaves it ``None``.
* **11.5 position state from broker readouts.** The held position is read from the
  passed ``positions`` (``broker.get_positions``) and **never inferred** — the
  reduce-vs-open branch keys only on a same-symbol held position.
* **11.6 clamp ≤ held; no flatten-then-flip.** A reduce clamps ``volume`` to the
  held volume in a single order; a same-symbol reversal (flatten, then open the
  other side) waits for a later post-flat tick (v0.1 forbids single-tick flip).

Defense-in-depth (CN-3): an *actionable* decision always carries ``atr`` (a
degenerate/absent ATR makes the reactive model emit HOLD upstream), so the
``None``-guard on ``atr`` fires **only on a reactive-contract violation** —
degrading to no-order rather than a stop-less order.

Pure leaf (P1): stdlib + the daemon/reactive/broker shape imports only — no
numpy, no MCP, no DB, no ``src.survival``. Deterministic and isolatable (P14).
"""

from __future__ import annotations

from typing import Optional

from src.reactive.daemon.broker_seam import Direction, Label, Position
from src.reactive.daemon.types import PinnedParams, ProposedOrder
from src.reactive.types import ReactiveDecision

# The protective-stop ATR multiplier default (config._DEFAULT_STOP_LOSS_ATR_MULT,
# Req 11.3). ``build_order`` is pure and takes the params object, not the full
# DaemonConfig — the multiplier is a small numeric the orchestrator threads via
# ``stop_loss_atr_mult``; this constant is the v0.1 default the daemon ships.
_DEFAULT_STOP_LOSS_ATR_MULT = 2.0

# The actionable decision vocabulary (R3.5): anything else (HOLD) is a no-order.
# ``ReactiveDecision.decision`` is the reactive ``Decision`` Literal
# ("LONG" | "SHORT" | "HOLD"); only the two directional labels reach an order.
_ACTIONABLE = ("LONG", "SHORT")

# The reactive decided side ↔ broker venue Direction. The reactive layer owns the
# side (§12.3); the broker ``Direction`` enum is the venue value object the
# ProposedOrder carries (SHORT-open = BUY + Direction.SHORT, ``mappers.py``).
_DECISION_TO_BROKER_DIRECTION = {
    "LONG": Direction.LONG,
    "SHORT": Direction.SHORT,
}


def _held_position_for_symbol(
    positions: list[Position], symbol: str
) -> Optional[Position]:
    """The single held position in ``symbol``, from broker readouts (Req 11.5).

    Returns ``None`` when the book is flat in this symbol. The daemon never
    *infers* position state — it reads it from the passed ``broker.get_positions``
    list. v0.1 manages one position per symbol (no scatter/gather across multiple
    same-symbol positions); the first match is the held position.
    """
    for pos in positions:
        if pos.symbol == symbol:
            return pos
    return None


def _capped_volume(
    sizing_hint: float, advisory_max_volume: Optional[float]
) -> float:
    """Volume = ``sizing_hint`` capped by the survival advisory (Req 11.2).

    The advisory is a **cap, not a floor** (never-upsize, P7/Req 2.4): a smaller
    ``sizing_hint`` is returned unchanged; a larger one is clamped to the
    advisory. ``None`` advisory = no survival cap known yet on this build (the
    initial build; the per-order ``admit`` veto + the Phase-2 resize-on-advisory
    re-build enforce the real cap, Req 3.5) — the daemon never *computes* the
    survival cap (Req 10.2).
    """
    if advisory_max_volume is None:
        return sizing_hint
    return min(sizing_hint, advisory_max_volume)


def _stop_loss_level(
    *, direction: str, reference_price: float, atr: float, stop_loss_atr_mult: float
) -> float:
    """The protective stop-loss **price level** (Req 11.3).

    ``reference_price - atr×mult`` for a long (stop below the entry reference),
    ``reference_price + atr×mult`` for a short (stop above). A price level, not a
    distance — so the constructed order passes survival's mandatory-stop check by
    construction. Anchored on the candidate's latest reference price (entry is
    unknown pre-fill in paper sim, design Open-Questions "Stop-loss reference
    anchor").
    """
    offset = atr * stop_loss_atr_mult
    if direction == "LONG":
        return reference_price - offset
    return reference_price + offset


def build_order(
    decision: ReactiveDecision,
    positions: list[Position],
    reference_price: float,
    params: PinnedParams,
    *,
    symbol: str = "",
    advisory_max_volume: Optional[float] = None,
    stop_loss_atr_mult: float = _DEFAULT_STOP_LOSS_ATR_MULT,
) -> Optional[ProposedOrder]:
    """Translate an actionable directional decision into a survival-legal order.

    Pure + deterministic (P14): no I/O, no ``src.survival`` import. Returns a
    daemon-owned ``ProposedOrder`` (BL-3) or ``None`` on HOLD / a non-sizable /
    a missing-ATR (reactive-contract-violation) decision.

    Args:
        decision: the ``ReactiveDecision`` from ``reactive.decide`` — caller has
            already skipped HOLD, but HOLD is re-guarded here (Req 2.5).
        positions: the current broker-readout positions (``broker.get_positions``)
            — the held state is read from here, never inferred (Req 11.5).
        reference_price: the candidate's surfaced last close (CN-4) — the
            stop-loss anchor, threaded by value (never re-fetched).
        params: the epoch-pinned ``PinnedParams`` (by value, P2). Reserved for the
            survival-namespace cap once survival lands; the multiplier is threaded
            via ``stop_loss_atr_mult`` to keep the function pure of config I/O.
        symbol: the decided symbol (carried by the candidate, ``assemble(symbol,
            …)``). Names the order and keys the reduce-vs-open branch (Req 11.5).
        advisory_max_volume: the survival per-order advisory cap (Req 11.2) — the
            caller threads it (the Phase-2 resize-on-advisory re-build, Req 3.5);
            ``None`` = no cap known on the initial build.
        stop_loss_atr_mult: the protective-stop multiplier (config, Req 11.3).

    Returns:
        A ``ProposedOrder`` (intent + direction + clamped volume + price-level
        stop + ``position_id`` on a reduce), or ``None`` (HOLD / non-sizable /
        missing ATR).
    """
    # HOLD / sub-threshold → no order (Req 2.5). The orchestrator records the
    # declined decision; the builder just declines to construct anything.
    if decision.decision not in _ACTIONABLE:
        return None

    # An actionable decision must carry a sizing_hint (None only on HOLD per the
    # reactive contract). With nothing to size, there is no order to build.
    sizing_hint = decision.sizing_hint
    if sizing_hint is None:
        return None

    # ATR from the REAL landed path (substrate.feature_values["atr"],
    # ``features.py:192``) — None-guard is defense-in-depth only (CN-3): an
    # actionable decision always carries it, so a None here is a reactive-contract
    # violation, degraded to no-order rather than a stop-less order.
    atr = decision.substrate.feature_values.get("atr")
    if atr is None:
        return None

    decided_side = decision.decision  # "LONG" | "SHORT" (actionable)
    stop_loss = _stop_loss_level(
        direction=decided_side,
        reference_price=reference_price,
        atr=atr,
        stop_loss_atr_mult=stop_loss_atr_mult,
    )

    held = _held_position_for_symbol(positions, symbol)

    # --- Reduce/close branch: the decided side OPPOSES a held position --------
    # A LONG decision against a held SHORT (or a SHORT against a held LONG)
    # reduces/closes the opposing position rather than opening fresh exposure.
    # Clamp the volume to the held volume in a single order — no flatten-then-flip
    # in v0.1 (Req 11.6); a same-symbol reversal is a later post-flat tick.
    if held is not None and held.direction is not _DECISION_TO_BROKER_DIRECTION[decided_side]:
        reduce_volume = min(sizing_hint, held.volume)
        # SELL = full close (volume meets the held), TRIM = partial reduce. The
        # close direction is the HELD position's side — closing it, not opening
        # the decided side (that flip waits for a post-flat tick).
        full_close = reduce_volume >= held.volume
        return ProposedOrder(
            symbol=symbol or held.symbol,
            intent=Label.SELL if full_close else Label.TRIM,
            direction=held.direction,
            volume=reduce_volume,
            stop_loss=stop_loss,
            position_id=held.position_id,
        )

    # --- Open/increase branch: open or add on the decided side ---------------
    # SHORT-open = BUY + Direction.SHORT (venue sell-to-open, ``mappers.py``) —
    # NOT a SELL (Req 11.1). Volume from sizing_hint capped by the survival
    # advisory (Req 11.2); position_id is None on an open (Req 11.4).
    volume = _capped_volume(sizing_hint, advisory_max_volume)
    return ProposedOrder(
        symbol=symbol,
        intent=Label.BUY,
        direction=_DECISION_TO_BROKER_DIRECTION[decided_side],
        volume=volume,
        stop_loss=stop_loss,
        position_id=None,
    )


__all__ = ["build_order"]
