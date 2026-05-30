"""Inner-ring tests for the version-pinned lifecycle + flat-before-close (task 4.3).

Boundary: ``lifecycle`` (Requirements 6, 8). These tests exercise the daemon's
lifecycle module against **synthetic** ``AccountState`` / ``OperationalState`` /
``SurvivalParameters`` / ``ClockState`` + the **REAL pure** ``survival.assess``
(no DB, no MCP, no LLM — P14). The two headline behaviors from the task
Observable:

  * an **in-window closure** executes flatten then verifies flat (escalating on a
    verify-flat failure — Req 6.1/6.2/6.3);
  * a **hot-swap** flips the whole param object atomically and leaves open
    positions on their **opening version** (Req 8.1/8.2/8.3), with survival
    applied at the **globally-tightest** level across coexisting versions (8.4),
    adopting the version ``commands`` selected (Req 9.4).

The broker submit + the DB writes are injected as synthetic seams (a recording
fake), so the lifecycle logic is verified in isolation; the loop (task 4.4) wires
the real ``broker.submit_decision`` / ``event_queue.emit_event`` / version-pin
writer.
"""

from __future__ import annotations

from typing import Any, Optional

import pytest

from src.reactive.daemon.broker_seam import Direction, Label, Position
from src.reactive.daemon.types import PinnedParams
from src.reactive.params import DEFAULTS as REACTIVE_DEFAULTS
from src.survival import gate as survival_gate
from src.survival.params import DEFAULTS as SURVIVAL_DEFAULTS
from src.survival.types import (
    AccountState,
    ClockState,
    OperationalState,
    Position as SurvivalPosition,
    ReduceDirective,
    SurvivalEvent,
)

from src.reactive.daemon import lifecycle


# --------------------------------------------------------------------------- #
# Synthetic fixtures.                                                          #
# --------------------------------------------------------------------------- #

_RUN_ID = "22222222-2222-2222-2222-222222222222"
_SYMBOL = "AAPL"


def _broker_position(
    *, position_id: str = "p-1", symbol: str = _SYMBOL,
    direction: Direction = Direction.LONG, volume: float = 1.5,
) -> Position:
    return Position(
        position_id=position_id,
        symbol=symbol,
        direction=direction,
        volume=volume,
        avg_open_price=100.0,
        used_margin=500.0,
        unrealized_pnl=0.0,
    )


def _survival_position(
    *, position_id: str = "p-1", symbol: str = _SYMBOL, volume: float = 1.5,
) -> SurvivalPosition:
    return SurvivalPosition(
        position_id=position_id,
        symbol=symbol,
        direction="LONG",
        volume=volume,
        avg_open_price=100.0,
        used_margin=500.0,
        unrealized_pnl=0.0,
    )


def _account_state(positions: Optional[list[SurvivalPosition]] = None) -> AccountState:
    return AccountState(
        activated=True,
        equity=100_000.0,
        used_margin=1_000.0,
        free_margin=99_000.0,
        margin_level=10_000.0,
        balance=100_000.0,
        stop_out_level=SURVIVAL_DEFAULTS.stop_out_level_pct,
        positions=positions or [],
    )


def _op_state(*, kill_switch: bool = False, grade: str = "NONE") -> OperationalState:
    return OperationalState(
        kill_switch_engaged=kill_switch,
        safe_mode_grade=grade,  # type: ignore[arg-type]
        entered_at=None,
        triggered_by=None,
    )


def _clock(seconds_to_next_closure: Optional[float]) -> ClockState:
    return ClockState(session_open=True, seconds_to_next_closure=seconds_to_next_closure)


def _pinned(version: str) -> PinnedParams:
    """A by-value PinnedParams tagged with a version marker in its survival map."""
    return PinnedParams(
        reactive_snapshot=REACTIVE_DEFAULTS,
        survival_snapshot={"version_marker": version},
    )


class _BrokerFake:
    """Records every ``submit_decision`` call and returns a configurable result.

    Mirrors the broker leaf ``submit_decision`` signature the lifecycle driver
    calls (``decision, symbol, direction, *, volume, position_id, stop_loss,
    runtime_mode, prior_queue_task_id``) loosely via kwargs — it only records.
    """

    def __init__(self, *, status: str = "simulated") -> None:
        self.calls: list[dict[str, Any]] = []
        self._status = status

    def submit_decision(self, decision, symbol, direction, **kwargs):
        self.calls.append(
            {
                "decision": decision,
                "symbol": symbol,
                "direction": direction,
                **kwargs,
            }
        )

        class _R:
            status = self._status

        return _R()


class _EventSinkFake:
    """Records persisted survival events (the event_queue emit seam)."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def emit(self, *, run_id, event_type, payload):
        self.events.append(
            {"run_id": run_id, "event_type": event_type, "payload": payload}
        )


class _VersionPinSinkFake:
    """Records version-pin open/close writes (the position_version writer seam)."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def write(self, *, run_id, venue_position_id, code_version, param_version, event):
        self.rows.append(
            {
                "run_id": run_id,
                "venue_position_id": venue_position_id,
                "code_version": code_version,
                "param_version": param_version,
                "event": event,
            }
        )


# --------------------------------------------------------------------------- #
# Flat-before-close action + verify-flat handshake (Req 6).                    #
# --------------------------------------------------------------------------- #


def test_in_window_closure_executes_flatten_then_verifies_flat_escalates_on_failure():
    """An in-window closure with open exposure: assess emits FLATTEN directives;
    the lifecycle EXECUTES them via the broker, RE-CHECKS the flat post-condition
    against the (still-open) state, and ESCALATES + records a verify-flat failure
    when the book is not flat afterward (Req 6.1/6.2/6.3)."""
    held = _survival_position(volume=1.5)
    account = _account_state(positions=[held])
    op_state = _op_state()
    # Closure within the flatten-lead window → assess emits a FLATTEN per position
    # + (because the fixed state is still not flat) a flat_verify_failed event.
    clock = _clock(seconds_to_next_closure=SURVIVAL_DEFAULTS.flatten_lead_seconds - 1.0)
    directive = survival_gate.assess(account, op_state, SURVIVAL_DEFAULTS, clock)

    assert any(d.kind == "FLATTEN" for d in directive.reduce_directives), (
        "precondition: assess must emit a FLATTEN directive in-window"
    )

    broker = _BrokerFake()
    # The broker returns simulated (no real position removal), so the post-flatten
    # account is STILL not flat → verify-flat fails → escalate.
    result = lifecycle.execute_de_risk_directives(
        directives=directive.reduce_directives,
        broker_positions=[_broker_position(volume=1.5)],
        post_flatten_account=account,  # still holds the position (broker is paper)
        submit_decision=broker.submit_decision,
    )

    # A flatten was actually submitted against the held position.
    assert len(broker.calls) >= 1
    flatten_call = broker.calls[0]
    assert flatten_call["symbol"] == _SYMBOL
    assert flatten_call["position_id"] == "p-1"
    # Net-reducing intent (SELL/TRIM), never a BUY open.
    assert flatten_call["decision"] in (Label.SELL, Label.TRIM)

    # Verify-flat failed (book not flat after flatten) → escalation recorded.
    assert result.flat_verified is False
    assert result.verify_flat_failed is True


def test_in_window_closure_verifies_flat_when_book_clears():
    """When the post-flatten account is genuinely flat, verify-flat PASSES and no
    verify-flat failure is recorded (Req 6.2)."""
    held = _survival_position(volume=1.5)
    account = _account_state(positions=[held])
    clock = _clock(seconds_to_next_closure=SURVIVAL_DEFAULTS.flatten_lead_seconds - 1.0)
    directive = survival_gate.assess(account, _op_state(), SURVIVAL_DEFAULTS, clock)

    broker = _BrokerFake()
    flat_account = _account_state(positions=[])  # broker actually closed it

    result = lifecycle.execute_de_risk_directives(
        directives=directive.reduce_directives,
        broker_positions=[_broker_position(volume=1.5)],
        post_flatten_account=flat_account,
        submit_decision=broker.submit_decision,
    )

    assert len(broker.calls) >= 1
    assert result.flat_verified is True
    assert result.verify_flat_failed is False


def test_freeze_entries_directive_submits_no_order():
    """A FREEZE_ENTRIES (account-wide, ``symbol=None``) directive is a control
    signal, not a venue action — the lifecycle does NOT submit an order for it."""
    directives = [
        ReduceDirective(
            kind="FREEZE_ENTRIES",
            symbol=None,
            target_volume=None,
            reason="kill switch engaged",
        )
    ]
    broker = _BrokerFake()
    result = lifecycle.execute_de_risk_directives(
        directives=directives,
        broker_positions=[],
        post_flatten_account=_account_state(positions=[]),
        submit_decision=broker.submit_decision,
    )
    assert broker.calls == []  # FREEZE_ENTRIES never routes a venue order
    assert result.verify_flat_failed is False


def test_account_wide_flatten_targets_every_held_position():
    """An account-wide FLATTEN (``symbol=None``) flattens EVERY held position."""
    directives = [
        ReduceDirective(
            kind="FLATTEN", symbol=None, target_volume=None, reason="account-wide flatten"
        )
    ]
    broker = _BrokerFake()
    positions = [
        _broker_position(position_id="p-1", symbol="AAPL", direction=Direction.LONG),
        _broker_position(position_id="p-2", symbol="MSFT", direction=Direction.SHORT),
    ]
    lifecycle.execute_de_risk_directives(
        directives=directives,
        broker_positions=positions,
        post_flatten_account=_account_state(positions=[]),
        submit_decision=broker.submit_decision,
    )
    targeted = {c["position_id"] for c in broker.calls}
    assert targeted == {"p-1", "p-2"}


def test_persist_assess_events_emits_each_survival_event():
    """``AssessDirective.events`` are each persisted to the event queue (Req 5.4)."""
    events = [
        SurvivalEvent(
            event_type="flat_verify_failed",
            ticker=None,
            detail="not flat",
            account_snapshot={"open_position_count": 1},
        ),
        SurvivalEvent(
            event_type="margin_breach",
            ticker="AAPL",
            detail="buffer breach",
            account_snapshot={"margin_level": 120.0},
        ),
    ]
    sink = _EventSinkFake()
    lifecycle.persist_assess_events(
        run_id=_RUN_ID, events=events, emit_event=sink.emit
    )
    assert len(sink.events) == 2
    kinds = [e["event_type"] for e in sink.events]
    # flat_verify_failed maps to a safe_mode/lifecycle queue kind; the survival
    # event_type travels in the payload.
    assert all(e["run_id"] == _RUN_ID for e in sink.events)
    assert sink.events[0]["payload"]["event_type"] == "flat_verify_failed"
    assert "safe_mode" in kinds or "lifecycle" in kinds


# --------------------------------------------------------------------------- #
# Version-pinned lifecycle + atomic hot-swap (Req 8).                          #
# --------------------------------------------------------------------------- #


def test_hot_swap_flips_whole_param_object_atomically():
    """A hot-swap replaces the WHOLE versioned param object (pointer-flip), never
    field-by-field (Req 8.1). The active version after the swap is the new one."""
    mgr = lifecycle.VersionManager(
        initial_run_id="run-v1",
        initial_code_version="cv-1",
        initial_param_version="pv-1",
        initial_params=_pinned("v1"),
    )
    before = mgr.active_params
    assert before.survival_snapshot["version_marker"] == "v1"

    mgr.hot_swap(
        run_id="run-v2",
        code_version="cv-2",
        param_version="pv-2",
        params=_pinned("v2"),
    )

    after = mgr.active_params
    # Whole-object flip: a brand-new object, not a mutated old one.
    assert after is not before
    assert after.survival_snapshot["version_marker"] == "v2"
    assert mgr.active_code_version == "cv-2"
    assert mgr.active_param_version == "pv-2"
    assert mgr.active_run_id == "run-v2"


def test_open_positions_stay_on_their_opening_version_after_hot_swap():
    """A position opened under v1 keeps v1's version pin after a v2 hot-swap; a
    position opened AFTER the swap takes v2 (Req 8.2/8.3)."""
    mgr = lifecycle.VersionManager(
        initial_run_id="run-v1",
        initial_code_version="cv-1",
        initial_param_version="pv-1",
        initial_params=_pinned("v1"),
    )
    # Open p-old under v1.
    pin_old = mgr.record_open("p-old")
    assert pin_old.code_version == "cv-1"
    assert pin_old.param_version == "pv-1"

    # Hot-swap to v2.
    mgr.hot_swap(
        run_id="run-v2",
        code_version="cv-2",
        param_version="pv-2",
        params=_pinned("v2"),
    )

    # p-old is STILL managed under v1 (its opening version) — not retroactively v2.
    assert mgr.version_for_position("p-old").code_version == "cv-1"
    assert mgr.version_for_position("p-old").param_version == "pv-1"

    # A NEW position opened after the swap takes v2.
    pin_new = mgr.record_open("p-new")
    assert pin_new.code_version == "cv-2"
    assert pin_new.param_version == "pv-2"
    assert mgr.version_for_position("p-new").param_version == "pv-2"


def test_record_open_and_close_emit_version_pin_rows():
    """``record_open`` / ``record_close`` write the version-pin open/close pair to
    ``execution_daemon_position_version`` via the injected writer (Req 8.2)."""
    sink = _VersionPinSinkFake()
    mgr = lifecycle.VersionManager(
        initial_run_id="run-v1",
        initial_code_version="cv-1",
        initial_param_version="pv-1",
        initial_params=_pinned("v1"),
        write_version_pin=sink.write,
    )
    mgr.record_open("p-1")
    mgr.record_close("p-1")

    assert [r["event"] for r in sink.rows] == ["opened", "closed"]
    opened, closed = sink.rows
    assert opened["venue_position_id"] == "p-1"
    assert opened["code_version"] == "cv-1"
    assert opened["param_version"] == "pv-1"
    # The close pins the SAME (opening) version — not a later one.
    assert closed["code_version"] == "cv-1"
    assert closed["param_version"] == "pv-1"
    assert closed["run_id"] == "run-v1"


def test_close_uses_opening_version_even_after_hot_swap():
    """Closing a position opened under v1 — after a v2 hot-swap — pins v1 (the
    OPENING version), never the active v2 (Req 8.3)."""
    sink = _VersionPinSinkFake()
    mgr = lifecycle.VersionManager(
        initial_run_id="run-v1",
        initial_code_version="cv-1",
        initial_param_version="pv-1",
        initial_params=_pinned("v1"),
        write_version_pin=sink.write,
    )
    mgr.record_open("p-old")
    mgr.hot_swap(
        run_id="run-v2",
        code_version="cv-2",
        param_version="pv-2",
        params=_pinned("v2"),
    )
    mgr.record_close("p-old")

    close_row = sink.rows[-1]
    assert close_row["event"] == "closed"
    assert close_row["code_version"] == "cv-1"  # opening version, not the active v2
    assert close_row["param_version"] == "pv-1"


def test_global_tightest_survive_across_coexisting_versions():
    """While positions opened under more than one version are open, survival
    constraints apply at the GLOBALLY-TIGHTEST level across all of them (Req 8.4).
    The tightest is min(per_order_size_max) / min(safe_mode_buffer is highest band)
    — here: the smallest per-order cap and the strictest (highest) safe-mode buffer
    across coexisting version param objects."""
    import dataclasses

    loose = dataclasses.replace(
        SURVIVAL_DEFAULTS, per_order_size_max=10.0, safe_mode_buffer_pct=120.0
    )
    tight = dataclasses.replace(
        SURVIVAL_DEFAULTS, per_order_size_max=3.0, safe_mode_buffer_pct=180.0
    )

    tightest = lifecycle.global_tightest([loose, tight])
    # per-order cap: the SMALLER cap binds (most conservative).
    assert tightest.per_order_size_max == 3.0
    # safe-mode buffer: the HIGHER buffer binds (triggers de-risk earlier).
    assert tightest.safe_mode_buffer_pct == 180.0


def test_global_tightest_single_version_is_that_version():
    """With one version open, the globally-tightest is that version's params."""
    tightest = lifecycle.global_tightest([SURVIVAL_DEFAULTS])
    assert tightest.per_order_size_max == SURVIVAL_DEFAULTS.per_order_size_max


def test_hot_swap_adopts_the_commands_selected_version():
    """The version ``commands`` selected (a ``select_validated_config`` recorded a
    pending version_id) is adopted at the next hot-swap (Req 9.4): the manager
    exposes the selected version id, and a swap clears it once adopted."""
    mgr = lifecycle.VersionManager(
        initial_run_id="run-v1",
        initial_code_version="cv-1",
        initial_param_version="pv-1",
        initial_params=_pinned("v1"),
    )
    # commands recorded a selection for the next hot-swap.
    mgr.select_version("validated-v2")
    assert mgr.pending_selected_version == "validated-v2"

    mgr.hot_swap(
        run_id="run-v2",
        code_version="cv-2",
        param_version="validated-v2",
        params=_pinned("v2"),
    )
    # Adopted → the pending selection is cleared (consumed by the swap).
    assert mgr.pending_selected_version is None
    assert mgr.active_param_version == "validated-v2"


def test_version_for_unknown_position_raises():
    """Asking for the version of a position never opened is a programming error —
    the manager never invents a version (it would corrupt management)."""
    mgr = lifecycle.VersionManager(
        initial_run_id="run-v1",
        initial_code_version="cv-1",
        initial_param_version="pv-1",
        initial_params=_pinned("v1"),
    )
    with pytest.raises(KeyError):
        mgr.version_for_position("never-opened")
