"""Inner-ring test for the account/clock INPUT assembly (plan item #10).

Boundary: account_state (Requirements 5, 10). Asserts the projection the loop's
``build_and_run`` uses each tick to assemble FRESH survival ``AccountState`` +
``ClockState`` from the broker readouts (design §System-Flows lines 174-216) —
the daemon's own input assembly, NOT a survival recompute (Req 10.2, mirroring
``evaluation.py``'s ``OrderEvaluation`` projection):

  * the 8-field survival ``AccountState`` map (account scalars verbatim from the
    broker ``AccountAssets``; positions adapted from the broker readout);
  * the broker ``Direction`` enum → ``.value`` str projection on each position
    (EXACTLY ``orchestrator._direction_str`` / ``_to_survival_order``);
  * the ``activated`` threading;
  * the empty-positions / empty-book path;
  * the v0.1 default ``ClockState`` (``session_open=True``,
    ``seconds_to_next_closure=None``).

No DB / MCP / LLM (P14 inner ring): synthetic broker readouts + the real survival
types this projection populates.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.reactive.daemon.account_state import (
    build_account_state,
    build_clock_state,
)
from src.reactive.daemon.broker_seam import Direction, Position as BrokerPosition
from src.survival.types import (
    AccountState,
    ClockState,
    Position as SurvivalPosition,
)


# --------------------------------------------------------------------------- #
# A minimal broker AccountAssets stand-in (the 6 account-level scalars the      #
# projection copies verbatim). Field-shape-equal to broker.models.AccountAssets #
# without importing the flat broker package here.                               #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _FakeAssets:
    equity: float
    used_margin: float
    free_margin: float
    margin_level: float
    balance: float
    stop_out_level: float


def _assets(**overrides) -> _FakeAssets:
    base = dict(
        equity=100_000.0,
        used_margin=1_000.0,
        free_margin=99_000.0,
        margin_level=10_000.0,
        balance=100_000.0,
        stop_out_level=50.0,
    )
    base.update(overrides)
    return _FakeAssets(**base)


def _broker_position(
    *,
    position_id: str = "p1",
    symbol: str = "AAPL",
    direction: Direction = Direction.LONG,
    volume: float = 1.5,
    avg_open_price: float = 95.0,
    used_margin: float = 500.0,
    unrealized_pnl: float = -10.0,
) -> BrokerPosition:
    return BrokerPosition(
        position_id=position_id,
        symbol=symbol,
        direction=direction,
        volume=volume,
        avg_open_price=avg_open_price,
        used_margin=used_margin,
        unrealized_pnl=unrealized_pnl,
    )


# --------------------------------------------------------------------------- #
# 1. The 8-field AccountState map (account scalars verbatim).                   #
# --------------------------------------------------------------------------- #


def test_account_state_maps_all_eight_fields_verbatim() -> None:
    assets = _assets(
        equity=123_456.0,
        used_margin=7_890.0,
        free_margin=115_566.0,
        margin_level=1_565.0,
        balance=120_000.0,
        stop_out_level=40.0,
    )

    state = build_account_state(assets, [], activated=True)

    assert isinstance(state, AccountState)
    # All six account-level scalars are copied verbatim from the broker readout
    # (the venue-authoritative figures — never self-computed, Req 10.2).
    assert state.equity == 123_456.0
    assert state.used_margin == 7_890.0
    assert state.free_margin == 115_566.0
    assert state.margin_level == 1_565.0
    assert state.balance == 120_000.0
    assert state.stop_out_level == 40.0
    # activated threads through (8th field).
    assert state.activated is True
    # An empty book → an empty positions list (the 8th survival field).
    assert state.positions == []


# --------------------------------------------------------------------------- #
# 2. The Direction enum → str projection on each position.                     #
# --------------------------------------------------------------------------- #


def test_position_direction_enum_projects_to_value_str() -> None:
    """Each broker Position's ``Direction`` enum is projected to its ``.value``
    str — EXACTLY ``orchestrator._direction_str`` — and the six scalars copied."""
    state = build_account_state(
        _assets(),
        [
            _broker_position(direction=Direction.LONG, position_id="long-1"),
            _broker_position(direction=Direction.SHORT, position_id="short-1"),
        ],
        activated=True,
    )

    assert len(state.positions) == 2
    by_id = {p.position_id: p for p in state.positions}

    long_pos = by_id["long-1"]
    short_pos = by_id["short-1"]

    # Each adapted position is the SURVIVAL Position type, with a plain-str
    # direction (not the broker Direction enum).
    assert isinstance(long_pos, SurvivalPosition)
    assert long_pos.direction == "LONG"
    assert isinstance(long_pos.direction, str)
    assert not isinstance(long_pos.direction, Direction)
    assert short_pos.direction == "SHORT"

    # The six shared scalars are copied verbatim.
    assert long_pos.symbol == "AAPL"
    assert long_pos.volume == 1.5
    assert long_pos.avg_open_price == 95.0
    assert long_pos.used_margin == 500.0
    assert long_pos.unrealized_pnl == -10.0


def test_position_projection_matches_orchestrator_direction_str() -> None:
    """The position direction projection is the SAME convention as the
    orchestrator's order-direction projection (one convention, never two)."""
    from src.reactive.daemon import orchestrator

    state = build_account_state(
        _assets(), [_broker_position(direction=Direction.SHORT)], activated=True
    )
    assert state.positions[0].direction == orchestrator._direction_str(
        Direction.SHORT
    )


# --------------------------------------------------------------------------- #
# 3. ``activated`` threading (both directions).                                #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("activated", [True, False])
def test_activated_threads_through(activated: bool) -> None:
    state = build_account_state(_assets(), [], activated=activated)
    assert state.activated is activated


# --------------------------------------------------------------------------- #
# 4. Empty-positions / empty-book path.                                        #
# --------------------------------------------------------------------------- #


def test_empty_book_yields_empty_positions_not_an_error() -> None:
    """A genuinely-flat book (empty broker readout) → an empty positions list —
    a flat book that is really flat, not a swallowed readout failure."""
    state = build_account_state(_assets(), [], activated=True)
    assert state.positions == []
    # The account scalars still populate (a flat book is still a real account).
    assert state.equity == 100_000.0


# --------------------------------------------------------------------------- #
# 5. The v0.1 default ClockState.                                              #
# --------------------------------------------------------------------------- #


def test_clock_state_v0_1_default() -> None:
    clock = build_clock_state()
    assert isinstance(clock, ClockState)
    assert clock.session_open is True
    assert clock.seconds_to_next_closure is None


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
