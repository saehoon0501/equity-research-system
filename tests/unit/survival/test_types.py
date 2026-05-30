"""Task 1.1 — contract/vocabulary proof for ``src.survival.types``.

Proves the task-1.1 observable: the full set of typed contracts imports
cleanly and type-checks; the fixed vocabularies equal the design's sets; the
``Position`` type carries no trading-status/halt field (R7); ``BindingConstraint``
has no ``halt_freeze`` (R7); ``ReduceDirective.kind`` has no ``FLATTEN_AT_REOPEN``
(R7); ``AdmitDecision`` exposes ``binding_constraint``; ``AssessDirective``
exposes ``events``.

Pure unit test — no LLM / MCP / DB. Annotations are lazy strings under the
module's ``from __future__ import annotations`` convention, so type assertions
go through ``typing.get_type_hints`` / ``typing.get_args`` rather than raw
``__annotations__`` string comparison.
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import importlib
import typing

import pytest


# --------------------------------------------------------------------------- #
# Imports clean (the core "imports cleanly" half of the observable).          #
# --------------------------------------------------------------------------- #

def test_module_imports_cleanly():
    mod = importlib.import_module("src.survival.types")
    expected = {
        "SafeModeGrade",
        "BindingConstraint",
        "Position",
        "AccountState",
        "ClockState",
        "ProposedOrder",
        "OperationalState",
        "AdmitDecision",
        "AssessDirective",
        "ReduceDirective",
        "SurvivalEvent",
    }
    missing = expected - set(dir(mod))
    assert not missing, f"types module missing public contracts: {sorted(missing)}"


def _types_module():
    return importlib.import_module("src.survival.types")


# --------------------------------------------------------------------------- #
# Fixed vocabularies equal the design's sets exactly.                          #
# --------------------------------------------------------------------------- #

def test_safe_mode_grade_vocabulary():
    t = _types_module()
    assert set(typing.get_args(t.SafeModeGrade)) == {
        "NONE",
        "TIGHTEN",
        "HALT_NEW",
        "FLATTEN",
    }


def test_binding_constraint_vocabulary_no_halt_freeze():
    t = _types_module()
    args = set(typing.get_args(t.BindingConstraint))
    assert args == {
        "kill_switch",
        "safe_mode",
        "not_activated",
        "universe",
        "entry_exclusion",
        "margin_distance",
        "funding_cap",
        "size_limit",
        "missing_sl",
    }
    # R7: real-time halt detection out of boundary — no halt_freeze constraint.
    assert "halt_freeze" not in args


def test_reduce_directive_kind_vocabulary_no_flatten_at_reopen():
    t = _types_module()
    hints = typing.get_type_hints(t.ReduceDirective)
    kinds = set(typing.get_args(hints["kind"]))
    assert kinds == {"FLATTEN", "REDUCE", "FREEZE_ENTRIES"}
    # R7: halt path removed — no flatten-at-reopen directive.
    assert "FLATTEN_AT_REOPEN" not in kinds


def test_proposed_order_intent_vocabulary():
    t = _types_module()
    hints = typing.get_type_hints(t.ProposedOrder)
    assert set(typing.get_args(hints["intent"])) == {"BUY", "TRIM", "SELL"}


def test_admit_decision_outcome_vocabulary():
    t = _types_module()
    hints = typing.get_type_hints(t.AdmitDecision)
    assert set(typing.get_args(hints["decision"])) == {"ALLOW", "REJECT"}


# --------------------------------------------------------------------------- #
# Field sets — exact equality so a re-added forbidden field fails the test.    #
# --------------------------------------------------------------------------- #

def _field_names(cls) -> set[str]:
    return {f.name for f in dataclasses.fields(cls)}


def test_position_fields_mirror_broker_no_trading_status():
    t = _types_module()
    fields = _field_names(t.Position)
    assert fields == {
        "position_id",
        "symbol",
        "direction",
        "volume",
        "avg_open_price",  # broker field name, not "open_price"
        "used_margin",
        "unrealized_pnl",
    }
    # R7: no trading-status / halt-adjacent field on the broker-mirrored Position.
    assert "trading_status" not in fields
    assert "open_price" not in fields  # renamed to avg_open_price per seam reconciliation
    assert not any("halt" in f for f in fields)


def test_account_state_fields():
    t = _types_module()
    assert _field_names(t.AccountState) == {
        "activated",
        "equity",
        "used_margin",
        "free_margin",
        "margin_level",
        "balance",
        "stop_out_level",
        "positions",
    }


def test_clock_state_fields():
    t = _types_module()
    assert _field_names(t.ClockState) == {
        "session_open",
        "seconds_to_next_closure",
    }


def test_proposed_order_fields():
    t = _types_module()
    assert _field_names(t.ProposedOrder) == {
        "symbol",
        "intent",
        "direction",
        "volume",
        "stop_loss",
    }


def test_operational_state_fields():
    t = _types_module()
    assert _field_names(t.OperationalState) == {
        "kill_switch_engaged",
        "safe_mode_grade",
        "entered_at",
        "triggered_by",
    }


def test_admit_decision_fields_expose_binding_constraint():
    t = _types_module()
    fields = _field_names(t.AdmitDecision)
    assert fields == {
        "decision",
        "binding_constraint",
        "advisory_max_volume",
        "reason",
    }
    assert "binding_constraint" in fields  # inspectable by consumer (R11.3, R2)


def test_assess_directive_fields_expose_events():
    t = _types_module()
    fields = _field_names(t.AssessDirective)
    assert fields == {
        "next_op_state",
        "reduce_directives",
        "events",
    }
    assert "events" in fields  # anomaly-queue events inspectable (R8)


def test_reduce_directive_fields():
    t = _types_module()
    assert _field_names(t.ReduceDirective) == {
        "kind",
        "symbol",
        "target_volume",
        "reason",
    }


def test_survival_event_fields():
    t = _types_module()
    assert _field_names(t.SurvivalEvent) == {
        "event_type",
        "ticker",
        "detail",
        "account_snapshot",
    }


# --------------------------------------------------------------------------- #
# All contracts are frozen dataclasses (immutable decision objects).          #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "name",
    [
        "Position",
        "AccountState",
        "ClockState",
        "ProposedOrder",
        "OperationalState",
        "AdmitDecision",
        "AssessDirective",
        "ReduceDirective",
        "SurvivalEvent",
    ],
)
def test_contracts_are_frozen_dataclasses(name):
    t = _types_module()
    cls = getattr(t, name)
    assert dataclasses.is_dataclass(cls), f"{name} is not a dataclass"
    params = getattr(cls, "__dataclass_params__")
    assert params.frozen, f"{name} dataclass must be frozen"


# --------------------------------------------------------------------------- #
# "type-checks" half of the observable: forward refs resolve for every        #
# contract under future-annotations (catches a typo / missing import that a   #
# bare import would not, because annotations are lazy strings).               #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "name",
    [
        "Position",
        "AccountState",
        "ClockState",
        "ProposedOrder",
        "OperationalState",
        "AdmitDecision",
        "AssessDirective",
        "ReduceDirective",
        "SurvivalEvent",
    ],
)
def test_type_hints_resolve(name):
    t = _types_module()
    hints = typing.get_type_hints(getattr(t, name))
    assert hints, f"{name} resolved to empty type hints"


# --------------------------------------------------------------------------- #
# Construct + inspect: a consumer can build the objects and read the           #
# decision-driving fields (R11.3 inspectability, end to end).                 #
# --------------------------------------------------------------------------- #

def test_construct_and_inspect_decision_and_directive():
    t = _types_module()

    pos = t.Position(
        position_id="p1",
        symbol="AAPL",
        direction="LONG",
        volume=10.0,
        avg_open_price=150.0,
        used_margin=300.0,
        unrealized_pnl=12.5,
    )
    acct = t.AccountState(
        activated=True,
        equity=1000.0,
        used_margin=300.0,
        free_margin=700.0,
        margin_level=3.33,
        balance=1000.0,
        stop_out_level=0.5,
        positions=[pos],
    )
    op = t.OperationalState(
        kill_switch_engaged=False,
        safe_mode_grade="NONE",
        entered_at=_dt.datetime(2026, 5, 30, tzinfo=_dt.timezone.utc),
        triggered_by=None,
    )
    clock = t.ClockState(session_open=True, seconds_to_next_closure=3600.0)
    order = t.ProposedOrder(
        symbol="AAPL",
        intent="BUY",
        direction="LONG",
        volume=5.0,
        stop_loss=145.0,
    )

    decision = t.AdmitDecision(
        decision="REJECT",
        binding_constraint="margin_distance",
        advisory_max_volume=2.0,
        reason="projected margin below safe-mode buffer",
    )
    # consumer can inspect the binding constraint that drove the decision.
    assert decision.decision == "REJECT"
    assert decision.binding_constraint == "margin_distance"
    assert decision.advisory_max_volume == 2.0

    ev = t.SurvivalEvent(
        event_type="margin_breach",
        ticker="AAPL",
        detail="margin level below buffer",
        account_snapshot={"margin_level": 0.55},
    )
    red = t.ReduceDirective(
        kind="FLATTEN",
        symbol="AAPL",
        target_volume=0.0,
        reason="closure imminent",
    )
    directive = t.AssessDirective(
        next_op_state=op,
        reduce_directives=[red],
        events=[ev],
    )
    # consumer can inspect the emitted events + directives.
    assert directive.events == [ev]
    assert directive.reduce_directives[0].kind == "FLATTEN"
    assert directive.next_op_state is op

    # frozen: mutation is rejected.
    with pytest.raises(dataclasses.FrozenInstanceError):
        order.volume = 99.0  # type: ignore[misc]
    assert clock.seconds_to_next_closure == 3600.0
    assert acct.positions[0].avg_open_price == 150.0


# --------------------------------------------------------------------------- #
# Inner-ring isolation: no LLM / MCP / DB import path in the types module.     #
# --------------------------------------------------------------------------- #

def test_no_forbidden_imports_in_types_source():
    import inspect

    t = _types_module()
    source = inspect.getsource(t)
    forbidden = ("anthropic", "psycopg", "sqlalchemy", "mcp", "asyncpg", "openai")
    for token in forbidden:
        assert token not in source, f"types.py must not import {token!r}"
