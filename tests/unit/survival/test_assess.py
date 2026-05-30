"""Task 4.1 — observable proof for ``src.survival.gate.assess`` (the no-order
standing monitor).

Proves THIS task's observable. The broad standing-monitor suite is task 5.3;
here we prove the four behaviors the task enumerates plus the cross-cutting
invariants:

  * **Margin breach → tightened (never loosened) grade + reduce/flatten
    directives + margin_breach/safe_mode_entered events** (R1.5, R8). A breach of
    the safe-mode buffer (but above stop-out) escalates to HALT_NEW + REDUCE; a
    breach at/below the stop-out line escalates to FLATTEN + FLATTEN directives.
  * **Monotonic latch (R8.3, design line 202):** a tripped grade NEVER
    auto-loosens — starting from FLATTEN with a now-clean margin keeps FLATTEN; a
    transient blip that trips a grade stays latched on the next clean call. Grade
    is the rank-max of (input grade, condition grade) via the centralized
    ``grade_rank`` — compared by integer rank, never by string.
  * **Closure path (R6):** a closure within ``flatten_lead_seconds`` with open
    levered exposure emits FLATTEN directives, then RE-CHECKS the flat
    post-condition; if positions remain it ESCALATES to FLATTEN grade and records
    a ``flat_verify_failed`` event (we assert the escalation + the event, not
    merely that a directive was emitted). The already-flat closure case proves
    the re-check is real (not always-true): no directives, no escalation, no
    event.
  * **No halt branch (R7, real-time detection out of boundary):** ``assess`` has
    no halt/``trading_status`` input and emits NO halt-triggered freeze / flatten
    / alert under any input — a synthetic mid-session "halt" surfaces only as its
    account-level margin consequence, routing through the margin / safe-mode path.
  * **Kill switch:** an engaged kill switch emits a ``FREEZE_ENTRIES`` directive
    and carries ``kill_switch_engaged`` through unchanged (``assess`` never
    engages/disengages it — operator-only, R9.3).
  * **Determinism (R11.1):** identical ``(state, op_state, params, clock)`` →
    identical ``AssessDirective`` (no wall-clock reads — closure-imminence comes
    from ``clock``, ``entered_at``/snapshots are built only from inputs).

Pure unit test — no LLM / MCP / DB (P14, R11.2).
"""

from __future__ import annotations

import dataclasses
import importlib
import inspect
from datetime import datetime

import pytest

from src.survival.params import DEFAULTS
from src.survival.types import (
    AccountState,
    ClockState,
    OperationalState,
    Position,
    ReduceDirective,
    SurvivalEvent,
    grade_rank,
)


# --------------------------------------------------------------------------- #
# Helpers.                                                                     #
# --------------------------------------------------------------------------- #

def _gate_module():
    return importlib.import_module("src.survival.gate")


def _assess(**kwargs):
    return _gate_module().assess(**kwargs)


def _position(*, symbol: str = "AAPL", direction: str = "LONG",
              volume: float = 10.0, position_id: str = "p1",
              used_margin: float = 500.0) -> Position:
    return Position(
        position_id=position_id,
        symbol=symbol,
        direction=direction,
        volume=volume,
        avg_open_price=100.0,
        used_margin=used_margin,
        unrealized_pnl=0.0,
    )


def _account(*, activated: bool = True, positions=None,
             equity: float = 100_000.0, used_margin: float = 1_000.0) -> AccountState:
    """A synthetic AccountState. Default margin level is huge (equity/used_margin
    ×100 = 10000%), so the margin step does not bind unless a test deliberately
    starves it (low equity / high used_margin)."""
    return AccountState(
        activated=activated,
        equity=equity,
        used_margin=used_margin,
        free_margin=equity - used_margin,
        margin_level=999_999.0,
        balance=equity,
        stop_out_level=50.0,
        positions=list(positions or []),
    )


def _op(*, kill_switch: bool = False, grade: str = "NONE",
        entered_at=None, triggered_by=None) -> OperationalState:
    return OperationalState(
        kill_switch_engaged=kill_switch,
        safe_mode_grade=grade,
        entered_at=entered_at,
        triggered_by=triggered_by,
    )


def _clock(*, session_open: bool = True,
           seconds_to_next_closure=None) -> ClockState:
    return ClockState(
        session_open=session_open,
        seconds_to_next_closure=seconds_to_next_closure,
    )


def _params(**overrides):
    return dataclasses.replace(DEFAULTS, **overrides)


def _event_types(directive) -> list[str]:
    return [e.event_type for e in directive.events]


def _directive_kinds(directive) -> list[str]:
    return [d.kind for d in directive.reduce_directives]


# Default params: stop_out=50, buffer=100. A margin level in (50, 100] breaches
# the buffer but not stop-out (HALT_NEW band); a level <= 50 breaches stop-out
# (FLATTEN band); a level > 100 is clean.
#
# margin level = equity / used_margin * 100. To put the level at L%, set
# used_margin = equity * 100 / L.
def _state_at_margin_level(level_pct: float, *, positions=None,
                           equity: float = 100_000.0) -> AccountState:
    used = equity * 100.0 / level_pct
    return _account(equity=equity, used_margin=used, positions=positions)


# --------------------------------------------------------------------------- #
# Clean / no-op path.                                                          #
# --------------------------------------------------------------------------- #

def test_clean_state_emits_no_directives_and_carries_grade_unchanged():
    """A healthy account, no kill switch, no closure imminence → no directives,
    no events, grade unchanged (NONE in → NONE out)."""
    state = _account()  # margin level 10000% — clean
    op = _op(grade="NONE")
    out = _assess(state=state, op_state=op, params=_params(), clock=_clock())
    assert out.reduce_directives == []
    assert out.events == []
    assert out.next_op_state.safe_mode_grade == "NONE"
    assert out.next_op_state.kill_switch_engaged is False


# --------------------------------------------------------------------------- #
# Margin path (R1.5 / R8) — escalation + events + band→grade mapping.          #
# --------------------------------------------------------------------------- #

def test_buffer_breach_above_stopout_escalates_to_halt_new_with_reduce():
    """Margin level in the danger band (stop-out < level <= buffer) → HALT_NEW
    grade + a REDUCE directive + margin_breach/safe_mode_entered events."""
    state = _state_at_margin_level(75.0)  # 50 < 75 <= 100 → buffer breach only
    op = _op(grade="NONE")
    out = _assess(state=state, op_state=op, params=_params(), clock=_clock())

    assert out.next_op_state.safe_mode_grade == "HALT_NEW"
    assert "REDUCE" in _directive_kinds(out)
    assert "margin_breach" in _event_types(out)
    assert "safe_mode_entered" in _event_types(out)
    # grade tightened (rank increased) from the NONE input.
    assert grade_rank(out.next_op_state.safe_mode_grade) > grade_rank("NONE")


def test_stopout_breach_escalates_to_flatten_with_flatten_directives():
    """Margin level at/below the stop-out line → FLATTEN grade + FLATTEN
    directive(s) + margin_breach/safe_mode_entered events."""
    pos = _position()
    state = _state_at_margin_level(40.0, positions=[pos])  # 40 <= 50 → stop-out breach
    op = _op(grade="NONE")
    out = _assess(state=state, op_state=op, params=_params(), clock=_clock())

    assert out.next_op_state.safe_mode_grade == "FLATTEN"
    assert "FLATTEN" in _directive_kinds(out)
    assert "margin_breach" in _event_types(out)
    assert "safe_mode_entered" in _event_types(out)


def test_margin_breach_tightens_grade_from_a_lighter_input():
    """A TIGHTEN-grade input with a stop-out breach escalates to FLATTEN (the
    rank-max wins; tightened, never loosened)."""
    state = _state_at_margin_level(40.0)
    op = _op(grade="TIGHTEN")
    out = _assess(state=state, op_state=op, params=_params(), clock=_clock())
    assert out.next_op_state.safe_mode_grade == "FLATTEN"
    assert grade_rank(out.next_op_state.safe_mode_grade) > grade_rank("TIGHTEN")


# --------------------------------------------------------------------------- #
# Monotonic latch (R8.3) — grade NEVER auto-loosens.                           #
# --------------------------------------------------------------------------- #

def test_latched_flatten_grade_survives_a_now_clean_margin():
    """Starting from a tripped FLATTEN with a NOW-clean margin → grade stays
    FLATTEN (never auto-loosens; loosening is the operator/after-market path)."""
    state = _account()  # margin level 10000% — clean
    op = _op(grade="FLATTEN")
    out = _assess(state=state, op_state=op, params=_params(), clock=_clock())
    assert out.next_op_state.safe_mode_grade == "FLATTEN"


def test_transient_blip_grade_stays_latched_on_next_clean_call():
    """A transient margin blip trips HALT_NEW; the next (clean) call keeps the
    latched HALT_NEW grade — proving the rank-max latches across calls."""
    params = _params()
    # Call 1: a buffer breach trips HALT_NEW.
    blip = _state_at_margin_level(75.0)
    out1 = _assess(state=blip, op_state=_op(grade="NONE"), params=params, clock=_clock())
    assert out1.next_op_state.safe_mode_grade == "HALT_NEW"
    # Call 2: margin is now clean, but the daemon carried the tripped grade
    # through as the fresh op-state. It must NOT auto-loosen.
    out2 = _assess(state=_account(), op_state=out1.next_op_state,
                   params=params, clock=_clock())
    assert out2.next_op_state.safe_mode_grade == "HALT_NEW"


def test_grade_never_decreases_when_input_outranks_condition():
    """Input FLATTEN + a lighter (buffer-only) breach condition → stays FLATTEN
    (input rank wins; never down to HALT_NEW)."""
    state = _state_at_margin_level(75.0)  # condition grade HALT_NEW
    op = _op(grade="FLATTEN")             # input outranks
    out = _assess(state=state, op_state=op, params=_params(), clock=_clock())
    assert out.next_op_state.safe_mode_grade == "FLATTEN"


# --------------------------------------------------------------------------- #
# Closure path (R6) — flatten + re-check + escalation.                         #
# --------------------------------------------------------------------------- #

def test_closure_imminent_with_open_exposure_flattens_and_escalates():
    """Closure within flatten_lead_seconds + open levered position → FLATTEN
    directives AND, because the re-checked flat post-condition still fails
    (positions remain in this fixed state), the grade escalates to FLATTEN and a
    flat_verify_failed event is recorded. We assert the ESCALATION + event, not
    merely that a directive was emitted."""
    pos = _position(symbol="MSFT", volume=5.0)
    state = _account(positions=[pos])  # clean margin; closure is the trigger
    clock = _clock(seconds_to_next_closure=120.0)  # within the 300s default lead
    out = _assess(state=state, op_state=_op(grade="NONE"), params=_params(), clock=clock)

    assert "FLATTEN" in _directive_kinds(out)
    # ESCALATION (not just a directive):
    assert out.next_op_state.safe_mode_grade == "FLATTEN"
    assert "flat_verify_failed" in _event_types(out)


def test_closure_imminent_already_flat_does_not_escalate():
    """The re-check is REAL, not always-true: closure imminent but the account is
    ALREADY flat (no positions) → no FLATTEN directive, no escalation, no
    flat_verify_failed event (grade stays NONE)."""
    state = _account(positions=[])  # already flat
    clock = _clock(seconds_to_next_closure=120.0)
    out = _assess(state=state, op_state=_op(grade="NONE"), params=_params(), clock=clock)

    assert "FLATTEN" not in _directive_kinds(out)
    assert "flat_verify_failed" not in _event_types(out)
    assert out.next_op_state.safe_mode_grade == "NONE"


def test_closure_outside_lead_window_does_not_flatten():
    """A closure beyond flatten_lead_seconds with open exposure → no flatten yet
    (the closure path only fires inside the lead window)."""
    pos = _position()
    state = _account(positions=[pos])
    clock = _clock(seconds_to_next_closure=10_000.0)  # well beyond the 300s lead
    out = _assess(state=state, op_state=_op(grade="NONE"), params=_params(), clock=clock)
    assert "FLATTEN" not in _directive_kinds(out)
    assert out.next_op_state.safe_mode_grade == "NONE"


def test_no_closure_scheduled_does_not_flatten():
    """seconds_to_next_closure is None (no closure known) with open exposure → no
    flatten (closure-imminence is the trigger, not the mere holding of exposure)."""
    pos = _position()
    state = _account(positions=[pos])
    out = _assess(state=state, op_state=_op(grade="NONE"), params=_params(),
                  clock=_clock(seconds_to_next_closure=None))
    assert "FLATTEN" not in _directive_kinds(out)
    assert out.next_op_state.safe_mode_grade == "NONE"


# --------------------------------------------------------------------------- #
# No halt branch (R7) — no halt input, no halt-triggered directive.            #
# --------------------------------------------------------------------------- #

def test_assess_exposes_no_halt_input():
    """``assess`` has no halt / trading_status parameter (R7 — real-time
    per-instrument halt detection is out of boundary)."""
    sig = inspect.signature(_gate_module().assess)
    param_names = set(sig.parameters)
    assert param_names == {"state", "op_state", "params", "clock"}
    for forbidden in ("trading_status", "halt", "halted", "is_halted"):
        assert forbidden not in param_names


def test_synthetic_mid_session_halt_emits_no_halt_specific_directive():
    """A synthetic mid-session 'halt' scenario (session open, no closure imminent,
    a held name) is INVISIBLE to assess except via its account-level margin
    consequence. With a clean margin there is nothing for assess to do — and
    crucially NO halt-specific freeze/flatten/alert is emitted under any input."""
    pos = _position(symbol="HALTED", volume=3.0)
    state = _account(positions=[pos])  # clean margin
    clock = _clock(session_open=True, seconds_to_next_closure=None)
    out = _assess(state=state, op_state=_op(grade="NONE"), params=_params(), clock=clock)

    # No directive at all (clean margin, no closure). No FLATTEN_AT_REOPEN kind
    # exists in the type at all (R7); the live kinds present must not include any
    # halt-keyed action.
    assert out.reduce_directives == []
    assert out.events == []
    # The grade is unchanged — no halt-triggered de-risk.
    assert out.next_op_state.safe_mode_grade == "NONE"


def test_held_name_margin_move_routes_through_margin_path():
    """A held name moving against the book (the only way a halt is observable)
    manifests purely as a margin consequence → it routes through the
    margin/safe-mode path, NOT a halt branch. The event is margin_breach, never a
    halt event."""
    pos = _position(symbol="HALTED", volume=3.0, used_margin=2_000.0)
    # The held name has moved against the book → margin level driven into breach.
    state = _state_at_margin_level(40.0, positions=[pos])
    out = _assess(state=state, op_state=_op(grade="NONE"), params=_params(), clock=_clock())

    assert "margin_breach" in _event_types(out)
    # No halt-specific event type leaks in.
    for e in out.events:
        assert "halt" not in e.event_type.lower()


# --------------------------------------------------------------------------- #
# Kill switch — FREEZE_ENTRIES + carried through unchanged.                    #
# --------------------------------------------------------------------------- #

def test_kill_switch_engaged_emits_freeze_entries_and_carries_through():
    """An engaged kill switch → a FREEZE_ENTRIES directive; ``kill_switch_engaged``
    is carried through UNCHANGED (assess never engages/disengages — operator-only,
    R9.3)."""
    state = _account()
    op = _op(kill_switch=True, grade="NONE")
    out = _assess(state=state, op_state=op, params=_params(), clock=_clock())
    assert "FREEZE_ENTRIES" in _directive_kinds(out)
    assert out.next_op_state.kill_switch_engaged is True


def test_assess_never_disengages_kill_switch():
    """assess carries an engaged kill switch through — it cannot turn it off."""
    out = _assess(state=_account(), op_state=_op(kill_switch=True),
                  params=_params(), clock=_clock())
    assert out.next_op_state.kill_switch_engaged is True


# --------------------------------------------------------------------------- #
# Conditions accumulate — no condition masks another (P6/P7).                  #
# --------------------------------------------------------------------------- #

def test_kill_switch_does_not_mask_margin_breach():
    """A kill switch engaged AND a stop-out margin breach co-fire: the FREEZE
    directive does NOT short-circuit/hide the margin breach. Both the
    FREEZE_ENTRIES directive and the margin escalation (FLATTEN grade +
    margin_breach event) are present."""
    state = _state_at_margin_level(40.0)  # stop-out breach
    op = _op(kill_switch=True, grade="NONE")
    out = _assess(state=state, op_state=op, params=_params(), clock=_clock())

    assert "FREEZE_ENTRIES" in _directive_kinds(out)
    assert out.next_op_state.safe_mode_grade == "FLATTEN"
    assert "margin_breach" in _event_types(out)
    assert out.next_op_state.kill_switch_engaged is True


def test_margin_and_closure_both_fire_most_severe_grade_wins():
    """A buffer-only margin breach (HALT_NEW) AND an imminent closure with open
    exposure (FLATTEN) co-fire → the most-severe grade (FLATTEN) wins; both the
    margin and the closure events are recorded."""
    pos = _position(volume=5.0)
    state = _state_at_margin_level(75.0, positions=[pos])  # buffer breach → HALT_NEW band
    clock = _clock(seconds_to_next_closure=120.0)          # closure → FLATTEN band
    out = _assess(state=state, op_state=_op(grade="NONE"), params=_params(), clock=clock)

    assert out.next_op_state.safe_mode_grade == "FLATTEN"
    assert "margin_breach" in _event_types(out)
    assert "flat_verify_failed" in _event_types(out)


# --------------------------------------------------------------------------- #
# Degraded state fails toward more protection (never "all clear").             #
# --------------------------------------------------------------------------- #

def test_degraded_nan_equity_escalates_toward_flatten():
    """A degraded AccountState (NaN equity) must escalate toward reduce/flatten +
    safe-mode, NEVER toward 'all clear'. (check_margin_distance coerces NaN equity
    → 0.0 level → stop-out breach → FLATTEN.)"""
    state = _account(equity=float("nan"), used_margin=1_000.0)
    out = _assess(state=state, op_state=_op(grade="NONE"), params=_params(), clock=_clock())
    assert out.next_op_state.safe_mode_grade == "FLATTEN"
    assert "margin_breach" in _event_types(out)


def test_degraded_nan_state_is_still_deterministic():
    """Determinism must hold for ALL inputs (R11.1), INCLUDING the degraded
    NaN-equity case the spec names — the emitted account_snapshot must not embed a
    raw NaN (NaN != NaN would break equality and is not valid JSONB). Non-finite
    numerics are coerced to the None sentinel, so two identical calls compare
    equal."""
    state = _account(equity=float("nan"), used_margin=1_000.0)
    kwargs = dict(state=state, op_state=_op(grade="NONE"),
                  params=_params(), clock=_clock())
    out_a = _assess(**kwargs)
    out_b = _assess(**kwargs)
    assert out_a == out_b
    # The degraded equity surfaces as None (JSON-safe), never a raw NaN, in the
    # event snapshot.
    for e in out_a.events:
        assert e.account_snapshot["equity"] is None


# --------------------------------------------------------------------------- #
# Determinism (R11.1) + no wall-clock stamping.                                #
# --------------------------------------------------------------------------- #

def test_identical_inputs_yield_identical_directive():
    """Identical (state, op_state, params, clock) → identical AssessDirective.
    Requires no wall-clock reads: entered_at/account_snapshot must be built from
    inputs only, never datetime.now()."""
    kwargs = dict(
        state=_state_at_margin_level(40.0, positions=[_position()]),
        op_state=_op(grade="NONE"),
        params=_params(),
        clock=_clock(seconds_to_next_closure=120.0),
    )
    assert _assess(**kwargs) == _assess(**kwargs)


def test_clean_path_is_deterministic_with_carried_entered_at():
    """An op-state carrying an entered_at timestamp is carried through unchanged
    (assess does not re-stamp with now()), so two calls compare equal."""
    stamped = _op(grade="HALT_NEW", entered_at=datetime(2026, 5, 30, 12, 0, 0),
                  triggered_by="prior_margin_breach")
    kwargs = dict(state=_account(), op_state=stamped, params=_params(), clock=_clock())
    out_a = _assess(**kwargs)
    out_b = _assess(**kwargs)
    assert out_a == out_b
    # Latched grade carried through; entered_at not clobbered by now().
    assert out_a.next_op_state.safe_mode_grade == "HALT_NEW"
