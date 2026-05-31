"""Account/clock INPUT assembly — the survival ``assess``/``admit`` state seam.

Boundary: account_state (Requirements 5, 10; design §"System Flows" lines 174-216
"assemble FRESH ``AccountState`` + ``ClockState`` from broker readouts each tick").

What this module is
-------------------
A **pure projection** turning the broker readouts (``broker.get_positions`` +
``broker.get_account_assets``) into the two survival *input* contracts the
``loop`` feeds ``survival.assess`` / ``survival.admit`` each tick:

  * :func:`build_account_state` → the survival ``AccountState`` (8 fields) — the
    account-level view ``assess`` (the standing monitor) and ``admit`` consume.
  * :func:`build_clock_state` → the survival ``ClockState`` (2 fields) — the
    closure-imminence + session inputs the pure core cannot read off a wall clock
    (survival R6/R11.2). v0.1 default: ``session_open=True``,
    ``seconds_to_next_closure=None`` (no live session-calendar wiring yet).

This is the daemon's own **input assembly**, NOT a survival recompute (Req 10.2,
exactly like ``evaluation.py``'s ``OrderEvaluation`` projection): survival owns
the *verdict*; the daemon owns producing the *inputs*. The freshness guarantee
(Req 5.2) is the loop's — it calls this each tick off a fresh broker readout so
``assess``/``admit`` never see a pinned-stale account.

The two-type readout (G4 — the load-bearing seam)
-------------------------------------------------
``broker.get_positions`` returns the **broker** ``Position`` (``Direction`` enum,
consumed by ``order_builder`` for the venue submit). ``survival.AccountState``
needs the **survival** ``Position`` (``direction: str``) — string-equal but
type-distinct from the SAME readout. :func:`_to_survival_position` adapts one to
the other: it copies ``position_id`` / ``symbol`` / ``volume`` /
``avg_open_price`` / ``used_margin`` / ``unrealized_pnl`` verbatim and projects
``direction`` = the broker ``Direction`` enum's ``.value`` str — EXACTLY the
``orchestrator._direction_str`` / ``_to_survival_order`` projection (one
direction-projection convention across the daemon, never two).

Reject-leaning on malformed input (mirrors ``evaluation.py``)
-------------------------------------------------------------
The account-activation flag is sourced from the broker ``AccountAssets`` /
mt5-account status the caller threads in as ``activated``; a missing / malformed
broker assets readout is the caller's responsibility to surface. Within this
projection, a malformed position (a non-string direction that has no ``.value``,
a missing field) raises rather than silently fabricating a degenerate position —
a position that cannot be projected is never dropped (which would under-report
exposure and read as "more flat than the venue is", the dangerous fail-open
direction for the standing monitor). On a **broker readout failure mid-tick** the
loop's edge-path try/except fails toward minimum exposure (Req 1.5); this module
therefore **raises** on a bad readout rather than returning a degenerate
``AccountState`` — never a flat-looking book the monitor would under-react to.

Pure leaf (P1): stdlib + the survival types it populates + the broker_seam types
it reads. No ``gate`` / ``params`` logic, no numpy, no MCP, no DB. Deterministic
and isolatable (P14).
"""

from __future__ import annotations

from typing import Any, Sequence

# The broker readout type this projection READS (the venue Position with the
# Direction enum). Imported through the daemon's single broker seam (task 1.4),
# never the flat broker package directly.
from src.reactive.daemon.broker_seam import Position as BrokerPosition

# The survival INPUT contracts this projection POPULATES. Importing only the
# types (never gate/params logic) keeps this a pure input assembly, not a
# survival recompute (Req 10.2) — mirrors evaluation.py's single-type import.
from src.survival.types import (
    AccountState,
    ClockState,
    Position as SurvivalPosition,
)

__all__ = [
    "build_account_state",
    "build_clock_state",
]


def _direction_str(direction: Any) -> str:
    """The broker ``Direction`` as a plain ``.value`` str.

    EXACTLY the ``orchestrator._direction_str`` projection — one direction
    string-projection convention across the daemon (the survival ``Position`` and
    the survival ``ProposedOrder`` both carry ``direction: str``, projected the
    same way so a position and its closing order can never disagree on the side
    string). A bare str passes through; a ``Direction`` enum yields its ``.value``.
    """
    value = getattr(direction, "value", direction)
    return str(value)


def _to_survival_position(position: BrokerPosition) -> SurvivalPosition:
    """Adapt a broker ``Position`` → the survival ``Position`` (G4 — distinct
    types from the SAME readout).

    The two types share their field *names* but are deliberately distinct
    (``broker.Position.direction`` is the ``Direction`` enum the ``order_builder``
    venue-submit needs; ``survival.Position.direction`` is a plain ``str`` the
    standing monitor classifies on). This copies the six shared scalars
    (``position_id`` / ``symbol`` / ``volume`` / ``avg_open_price`` /
    ``used_margin`` / ``unrealized_pnl``) **verbatim** and projects ``direction``
    through :func:`_direction_str` (the same enum→``.value`` projection
    ``orchestrator._to_survival_order`` uses), so the account the monitor sees and
    the order the venue submits agree on the side by construction.

    Reject-leaning (mirrors ``evaluation.py``): a position that cannot be projected
    (a missing scalar field, a direction with no ``.value`` that is not a str)
    raises — the standing monitor must never silently drop a held position (which
    would under-report exposure and read as more flat than the venue is, the
    fail-open direction for ``assess``).
    """
    return SurvivalPosition(
        position_id=position.position_id,
        symbol=position.symbol,
        direction=_direction_str(position.direction),
        volume=position.volume,
        avg_open_price=position.avg_open_price,
        used_margin=position.used_margin,
        unrealized_pnl=position.unrealized_pnl,
    )


def build_account_state(
    assets: Any,
    broker_positions: Sequence[BrokerPosition],
    *,
    activated: bool,
) -> AccountState:
    """Project the broker readouts → the survival ``AccountState`` (8 fields).

    Pure + deterministic (P14): no I/O, reads only its arguments. The account-level
    scalars are copied verbatim from the broker ``AccountAssets`` readout (the
    venue-authoritative figures — the daemon never substitutes a self-computed
    mark, Req 10.2); the ``positions`` list is each broker ``Position`` adapted to
    the survival ``Position`` via :func:`_to_survival_position`.

    Reject-leaning on malformed input (mirrors ``evaluation.py``): a broker
    ``assets`` readout missing a required field, or a position that cannot be
    projected, raises here. The loop calls this inside the per-tick edge path, so a
    raise is caught by ``run_cycle``'s fail-toward-minimum-exposure handler
    (Req 1.5) — the open is rejected, the de-risk directives still flow. A
    degenerate ``AccountState`` (e.g. one silently missing positions, so the
    monitor reads the book as flat) is NEVER returned: under-reporting exposure is
    the fail-open direction for the standing monitor.

    Args:
        assets: the broker ``AccountAssets`` readout (``broker.get_account_assets``)
            — the venue-authoritative equity / used / free margin / margin_level /
            balance / stop_out_level. Read verbatim (Req 10.2).
        broker_positions: the broker ``Position`` list (``broker.get_positions``) —
            adapted to the survival ``Position`` (G4); an empty book → an empty
            ``positions`` list (a flat book that is genuinely flat, not a
            swallowed readout failure — the loop surfaces a readout failure by the
            readout call itself raising before this is reached).
        activated: the account-activation flag (sourced from the broker
            mt5-account ``status`` by the caller). ``assess``/``admit`` read it as
            the survival ``AccountState.activated`` — an inactive account rejects
            every open (``gate.admit`` ``not_activated``).

    Returns:
        A frozen survival ``AccountState`` the loop feeds ``assess`` / ``admit``.
    """
    positions = [_to_survival_position(p) for p in broker_positions]
    return AccountState(
        activated=activated,
        equity=assets.equity,
        used_margin=assets.used_margin,
        free_margin=assets.free_margin,
        margin_level=assets.margin_level,
        balance=assets.balance,
        stop_out_level=assets.stop_out_level,
        positions=positions,
    )


def build_clock_state() -> ClockState:
    """Build the v0.1 default survival ``ClockState`` (2 fields).

    Pure + deterministic (P14): takes no input. The survival pure core cannot read
    a wall clock (R6/R11.2), so the daemon supplies the closure-imminence + session
    as *inputs*. v0.1 has no live session-calendar wiring (a tracked follow-on, the
    flat-before-close ``assess`` path keys off ``seconds_to_next_closure``), so the
    default is:

      * ``session_open=True`` — the daemon evaluates during an assumed-open session;
      * ``seconds_to_next_closure=None`` — no closure scheduled / known, so the
        closure-imminence flatten path is dormant until the session calendar lands.

    Returns:
        The v0.1 default frozen survival ``ClockState``.
    """
    return ClockState(session_open=True, seconds_to_next_closure=None)
