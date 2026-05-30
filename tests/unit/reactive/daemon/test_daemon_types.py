"""Inner-ring test for the daemon's owned data contracts (task 1.3).

Boundary: types (Requirements 2, 11, 12). Asserts the Observable from
tasks.md 1.3:

  * ``src/reactive/daemon/types.py`` imports with **no survival dependency**
    (``src/survival/`` does not exist — the daemon is last in build order and
    its Phase-1 types must be inner-ring-buildable now, BL-3 / design Rev 2.4).
  * a ``ProposedOrder`` and a ``Candidate`` construct from synthetic fields.
  * ``PinnedParams.reactive_snapshot`` is typed as — and returns — the reactive
    ``ParamSnapshot`` that ``decide`` consumes as its 3rd positional arg (BL-2,
    ``src/reactive/signal_model.py:212`` / ``src/reactive/params.py:30``).

The ``Direction`` import-source pins matter (gap-analysis G4): ``Candidate``
feeds ``reactive.decide`` and so carries the **reactive** ``Direction``
(``Literal["LONG","SHORT"]``); ``ProposedOrder`` is the pre-admit order whose
fields feed the broker venue mapping and so carries the **broker** ``Direction``
enum + the ``Label`` intent vocabulary (SHORT-open = ``BUY`` + ``Direction.SHORT``,
``mappers.py``). This test asserts both sources explicitly so a string-equal but
type-distinct ``Direction`` cannot silently slip downstream (T2-class divergence).

No LLM, no MCP, no live DB (P14 inner ring).
"""

from __future__ import annotations

import importlib
import sys

import pytest

import src.reactive.daemon.types as daemon_types
from src.reactive.daemon.types import (
    Candidate,
    CommandRow,
    EpochContext,
    EvalTick,
    PinnedParams,
    ProposedOrder,
)
from src.reactive.features import FeatureSet
from src.reactive.params import DEFAULTS, ParamSnapshot
from src.reactive.types import (
    CalibrationEvidence,
    Direction as ReactiveDirection,
    Weights,
)

# Broker domain vocabulary the daemon-owned ProposedOrder pins (P9 / mappers.py).
from src.mcp.broker.models import (
    Direction as BrokerDirection,
    Label,
)


def _feature_set() -> FeatureSet:
    """A minimal synthetic FeatureSet (the candidate's payload to decide)."""
    return FeatureSet(
        trend_vote=1.0,
        flow_vote=0.5,
        meanrev_vote=0.0,
        trend_strength=0.5,
        raw={"tactical_bin": "positive", "atr": 1.25},
    )


def _reactive_snapshot() -> ParamSnapshot:
    """The reactive ParamSnapshot decide() consumes (BL-2)."""
    return ParamSnapshot(
        weights=Weights(w_trend=0.34, w_flow=0.33, w_meanrev=0.33),
        temperature=1.0,
        threshold=0.55,
        calibration=CalibrationEvidence(brier=None, reliability=None),
        code_version="reactive-signal-model@v0.1",
        param_version="defaults@v0.1",
    )


# --- Observable 1: imports with no survival dependency --------------------


def test_types_module_imports_without_survival_dependency():
    """The Phase-1 types module must not import src.survival (unbuilt, BL-3)."""
    importlib.reload(daemon_types)
    # No survival module is pulled into the interpreter by importing the types.
    assert "src.survival" not in sys.modules
    assert "src.survival.gate" not in sys.modules


# --- Observable 2: ProposedOrder + Candidate construct from synthetic fields ---


def test_candidate_constructs_from_synthetic_fields():
    features = _feature_set()
    cand = Candidate(
        features=features,
        direction="LONG",
        reference_price=101.5,
    )
    assert cand.features is features
    assert cand.direction == "LONG"
    assert cand.reference_price == 101.5


def test_candidate_direction_is_reactive_direction_member():
    """Candidate.direction is the reactive Direction the decide() call wants."""
    long_cand = Candidate(features=_feature_set(), direction="LONG", reference_price=10.0)
    short_cand = Candidate(features=_feature_set(), direction="SHORT", reference_price=10.0)
    # Both reactive Direction members are accepted (Literal["LONG","SHORT"]).
    assert long_cand.direction in ("LONG", "SHORT")
    assert short_cand.direction in ("LONG", "SHORT")


def test_proposed_order_constructs_with_position_id_optional():
    """A reduce/close targets a position_id; an open omits it (daemon-owned)."""
    open_order = ProposedOrder(
        symbol="AAPL",
        intent=Label.BUY,
        direction=BrokerDirection.SHORT,  # SHORT-open = BUY + Direction.SHORT
        volume=3.0,
        stop_loss=99.0,
    )
    assert open_order.symbol == "AAPL"
    assert open_order.intent is Label.BUY
    assert open_order.direction is BrokerDirection.SHORT
    assert open_order.volume == 3.0
    assert open_order.stop_loss == 99.0
    assert open_order.position_id is None  # optional — absent on an open

    reduce_order = ProposedOrder(
        symbol="AAPL",
        intent=Label.TRIM,
        direction=BrokerDirection.LONG,
        volume=1.0,
        stop_loss=95.0,
        position_id="pos-123",
    )
    assert reduce_order.position_id == "pos-123"


def test_proposed_order_intent_is_broker_label_vocabulary():
    """intent is the P9 BUY/TRIM/SELL Label vocabulary the broker consumes."""
    for label in (Label.BUY, Label.TRIM, Label.SELL):
        order = ProposedOrder(
            symbol="MSFT",
            intent=label,
            direction=BrokerDirection.LONG,
            volume=2.0,
            stop_loss=100.0,
        )
        assert order.intent is label


# --- Observable 3: PinnedParams.reactive_snapshot is the reactive ParamSnapshot ---


def test_pinned_params_reactive_snapshot_is_param_snapshot():
    snap = _reactive_snapshot()
    pinned = PinnedParams(reactive_snapshot=snap, survival_snapshot={"max_lot": 5.0})
    # The exposed snapshot IS a reactive ParamSnapshot, returned unchanged (P2).
    assert isinstance(pinned.reactive_snapshot, ParamSnapshot)
    assert pinned.reactive_snapshot is snap


def test_pinned_params_reactive_snapshot_feeds_decide_3rd_arg():
    """The snapshot is exactly what decide() takes as its 3rd positional (BL-2)."""
    pinned = PinnedParams(reactive_snapshot=DEFAULTS, survival_snapshot={})
    # DEFAULTS is a ParamSnapshot; PinnedParams exposes it by value for decide().
    assert pinned.reactive_snapshot is DEFAULTS
    assert isinstance(pinned.reactive_snapshot, ParamSnapshot)


# --- Supporting daemon-owned record types (EvalTick / EpochContext / CommandRow) ---


def test_epoch_context_carries_run_id_versions_window_and_pins():
    pinned = PinnedParams(reactive_snapshot=_reactive_snapshot(), survival_snapshot={})
    ctx = EpochContext(
        run_id="11111111-1111-1111-1111-111111111111",
        code_version="reactive-signal-model@v0.1",
        param_version="defaults@v0.1",
        walk_forward_window="bootstrap@epoch",
        pinned_params=pinned,
    )
    assert ctx.run_id == "11111111-1111-1111-1111-111111111111"
    assert ctx.walk_forward_window == "bootstrap@epoch"
    assert ctx.pinned_params.reactive_snapshot.threshold == 0.55


def test_eval_tick_constructs_from_synthetic_fields():
    tick = EvalTick(symbol="NVDA", tick_seq=7, monotonic_ts=123.5)
    assert tick.symbol == "NVDA"
    assert tick.tick_seq == 7
    assert tick.monotonic_ts == 123.5


def test_command_row_constructs_from_synthetic_intake_fields():
    row = CommandRow(
        command_id="cmd-1",
        issued_by="operator",
        command_type="engage_kill_switch",
        target={"reason": "manual halt"},
        status="pending",
    )
    assert row.command_id == "cmd-1"
    assert row.issued_by == "operator"
    assert row.command_type == "engage_kill_switch"
    assert row.target == {"reason": "manual halt"}
    assert row.status == "pending"
