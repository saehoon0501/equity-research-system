"""Inner-ring test for the paper-mode order lifecycle driver (task 4.2).

Boundary: orchestrator (Requirement 3). Asserts the Observable from tasks.md 4.2
+ the design §13 System-Flows submit branch (design.md:202-204) against a
**synthetic broker stub** standing in for ``broker.core.submit_decision`` — no
DB, no MCP, no live venue (P14):

  * an admitted order is **submitted at most once while pending** — a second
    drive against the same pending intent does NOT re-submit (Req 3.4 double-send
    guard);
  * the lifecycle reaches a **terminal outcome** (filled / simulated / rejected /
    unconfirmed) — the poll/reconcile drives to a terminal state (Req 3.2);
  * an **unconfirmed** result is surfaced AS unconfirmed and **never treated as
    filled** (Req 3.3);
  * **no live-transmission path is reachable in paper mode** — the driver forces a
    paper ``RuntimeMode`` so the broker can never route to ``_submit_live``
    (Req 3.1): the stub asserts it is invoked with ``paper_enabled=True`` and the
    driver carries no live branch.

The broker stub is a synthetic ``submit_decision`` recording its calls + the
``runtime_mode`` it was handed; it returns a scripted queue of ``OrderResult``s so
the poll loop can be driven to each terminal outcome deterministically (no sleep,
no spin). The daemon-owned ``ProposedOrder`` (with its ``position_id`` retained
for the submit, BL-3) is mapped to the broker submit args at this seam.
"""

from __future__ import annotations

from typing import Any, Optional

import pytest

from src.reactive.daemon.broker_seam import Direction, Label
from src.reactive.daemon.types import ProposedOrder

# Broker result shape (the terminal-outcome carrier). Imported through the same
# seam the daemon binds to — a value object, no transport.
from src.mcp.broker.models import OrderResult, RejectionCode, RejectionReason

# The unit under test (does not exist yet — RED).
from src.reactive.daemon import orchestrator


# --------------------------------------------------------------------------- #
# Synthetic fixtures.                                                          #
# --------------------------------------------------------------------------- #

_SYMBOL = "AAPL"
_REFERENCE = 100.0
_STOP = 94.0


def _open_order(volume: float = 0.5) -> ProposedOrder:
    """A daemon-owned BUY+LONG open (no position_id — an open targets none)."""
    return ProposedOrder(
        symbol=_SYMBOL,
        intent=Label.BUY,
        direction=Direction.LONG,
        volume=volume,
        stop_loss=_STOP,
        position_id=None,
    )


def _reduce_order(volume: float = 0.5) -> ProposedOrder:
    """A daemon-owned reduce/close (SELL on the held LONG, targets position_id)."""
    return ProposedOrder(
        symbol=_SYMBOL,
        intent=Label.SELL,
        direction=Direction.LONG,
        volume=volume,
        stop_loss=_STOP,
        position_id="POS-1",
    )


def _simulated(queue_task_id: Optional[str] = None) -> OrderResult:
    raw: dict[str, Any] = {"simulated": True}
    if queue_task_id is not None:
        raw["data"] = {"id": queue_task_id}
    return OrderResult(
        status="simulated",
        fill_price=_REFERENCE,
        fill_volume=0.5,
        raw=raw,
    )


def _filled() -> OrderResult:
    return OrderResult(
        status="filled",
        order_id="O-1",
        fill_price=_REFERENCE,
        fill_volume=0.5,
        raw={"finished": True},
    )


def _unconfirmed(queue_task_id: str = "Q-1") -> OrderResult:
    return OrderResult(
        status="unconfirmed",
        raw={"data": {"id": queue_task_id}, "unconfirmed": True},
    )


def _rejected() -> OrderResult:
    return OrderResult(
        status="rejected",
        reason=RejectionReason(
            code=RejectionCode.VOLUME_OUT_OF_BOUNDS, message="too big"
        ),
    )


class _BrokerStub:
    """Synthetic ``submit_decision`` recording call args + the runtime_mode.

    Returns a scripted queue of ``OrderResult``s (one per call) so the poll loop
    can be driven to a terminal outcome deterministically. Records every call's
    kwargs so the test asserts paper-mode routing + the double-send guard (a
    re-submit while pending is suppressed by the driver, so the stub sees only one
    call for a pending intent).
    """

    def __init__(self, results: list[OrderResult]):
        self._results = list(results)
        self.calls: list[dict[str, Any]] = []

    def submit_decision(self, decision, symbol, direction, **kwargs):
        self.calls.append(
            {
                "decision": decision,
                "symbol": symbol,
                "direction": direction,
                **kwargs,
            }
        )
        if self._results:
            return self._results.pop(0)
        # Exhausted script → an unconfirmed (the daemon must surface, not assume).
        return _unconfirmed()


# --------------------------------------------------------------------------- #
# 1. Paper-only routing: the driver forces paper_enabled=True (no live path).  #
# --------------------------------------------------------------------------- #


def test_paper_mode_forces_paper_runtime_no_live_path_reachable():
    """The driver must hand the broker a paper ``RuntimeMode`` so the live
    transmit path is unreachable in v0.1 (Req 3.1)."""
    stub = _BrokerStub([_simulated()])

    outcome = orchestrator.drive_paper_lifecycle(
        _open_order(),
        submit_decision=stub.submit_decision,
    )

    assert len(stub.calls) == 1
    runtime_mode = stub.calls[0].get("runtime_mode")
    assert runtime_mode is not None
    # Paper enabled → live_transmit_allowed() can never be True (all four 8.3
    # conditions can't hold while paper is on).
    assert runtime_mode.paper_enabled is True
    assert runtime_mode.live_transmit_allowed() is False
    assert outcome.status == "simulated"


def test_submit_maps_daemon_order_fields_to_broker_args():
    """The daemon ProposedOrder maps to the broker submit args: intent→decision
    Label, direction enum, volume, stop_loss, and (on a reduce) position_id."""
    stub = _BrokerStub([_simulated()])

    orchestrator.drive_paper_lifecycle(
        _reduce_order(volume=0.3),
        submit_decision=stub.submit_decision,
    )

    call = stub.calls[0]
    assert call["decision"] is Label.SELL
    assert call["symbol"] == _SYMBOL
    assert call["direction"] is Direction.LONG
    assert call["volume"] == 0.3
    assert call["stop_loss"] == _STOP
    # A reduce/close carries the position_id (retained on the daemon order for the
    # broker submit, BL-3).
    assert call["position_id"] == "POS-1"


# --------------------------------------------------------------------------- #
# 2. Terminal outcomes: poll/reconcile drives to a terminal state.            #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "result,expected_status,expected_filled",
    [
        (_simulated(), "simulated", False),
        (_filled(), "filled", True),
        (_rejected(), "rejected", False),
        (_unconfirmed(), "unconfirmed", False),
    ],
)
def test_drive_reaches_each_terminal_outcome(
    result, expected_status, expected_filled
):
    """submit→poll→reconcile reaches each terminal outcome and reports it
    (Req 3.2)."""
    stub = _BrokerStub([result])

    outcome = orchestrator.drive_paper_lifecycle(
        _open_order(),
        submit_decision=stub.submit_decision,
    )

    assert outcome.terminal is True
    assert outcome.status == expected_status
    assert outcome.is_filled is expected_filled
    # The broker OrderResult is surfaced verbatim for the trace/fill consumer.
    assert outcome.result is result


# --------------------------------------------------------------------------- #
# 3. Unconfirmed surfaced AS unconfirmed — never treated as filled (Req 3.3).  #
# --------------------------------------------------------------------------- #


def test_unconfirmed_is_surfaced_not_filled():
    stub = _BrokerStub([_unconfirmed()])

    outcome = orchestrator.drive_paper_lifecycle(
        _open_order(),
        submit_decision=stub.submit_decision,
    )

    assert outcome.status == "unconfirmed"
    # The headline invariant: unconfirmed is NEVER a fill.
    assert outcome.is_filled is False
    assert outcome.terminal is True


# --------------------------------------------------------------------------- #
# 4. Double-send guard: at most one submit while a confirmation is pending.    #
# --------------------------------------------------------------------------- #


def test_double_send_guard_suppresses_resubmit_while_pending():
    """While a submitted order's confirmation is pending (unconfirmed), a second
    drive for the SAME order intent must NOT issue a duplicate submission
    (Req 3.4)."""
    stub = _BrokerStub([_unconfirmed("Q-7"), _unconfirmed("Q-7")])
    guard = orchestrator.PaperSendGuard()
    order = _open_order()

    first = orchestrator.drive_paper_lifecycle(
        order, submit_decision=stub.submit_decision, guard=guard
    )
    # First drive submits once and surfaces unconfirmed (pending).
    assert first.status == "unconfirmed"
    assert len(stub.calls) == 1

    # A SECOND drive for the same pending intent must be suppressed — no new POST.
    second = orchestrator.drive_paper_lifecycle(
        order, submit_decision=stub.submit_decision, guard=guard
    )
    assert len(stub.calls) == 1  # still ONE — the guard suppressed the re-send
    assert second.status == "unconfirmed"
    assert second.is_filled is False


def test_terminal_outcome_clears_the_pending_guard():
    """Once an intent reaches a terminal CONFIRMED outcome (simulated/filled), the
    guard clears so a later, genuinely-new intent for the same symbol submits."""
    stub = _BrokerStub([_simulated(), _simulated()])
    guard = orchestrator.PaperSendGuard()
    order = _open_order()

    first = orchestrator.drive_paper_lifecycle(
        order, submit_decision=stub.submit_decision, guard=guard
    )
    assert first.status == "simulated"
    assert len(stub.calls) == 1

    # A terminal confirmed outcome is NOT pending → a later drive submits again.
    second = orchestrator.drive_paper_lifecycle(
        order, submit_decision=stub.submit_decision, guard=guard
    )
    assert len(stub.calls) == 2
    assert second.status == "simulated"


def test_distinct_intents_are_not_blocked_by_each_others_pending_state():
    """The guard keys on the order intent (symbol+side+intent+position): a pending
    intent must not suppress a DIFFERENT intent's submit."""
    stub = _BrokerStub([_unconfirmed("Q-A"), _simulated()])
    guard = orchestrator.PaperSendGuard()

    # An open (no position_id) goes unconfirmed → pending.
    orchestrator.drive_paper_lifecycle(
        _open_order(), submit_decision=stub.submit_decision, guard=guard
    )
    assert len(stub.calls) == 1

    # A DISTINCT intent (a reduce targeting a position) must still submit.
    orchestrator.drive_paper_lifecycle(
        _reduce_order(), submit_decision=stub.submit_decision, guard=guard
    )
    assert len(stub.calls) == 2


# --------------------------------------------------------------------------- #
# 5. No live path is constructed by the driver itself (Req 3.1 / Req 10).     #
# --------------------------------------------------------------------------- #


def test_driver_never_passes_a_live_capable_runtime_mode():
    """Defense-in-depth: across every order kind the driver only ever hands the
    broker a paper RuntimeMode whose live_transmit_allowed() is False."""
    for order, results in (
        (_open_order(), [_simulated()]),
        (_reduce_order(), [_filled()]),
        (_open_order(), [_unconfirmed()]),
    ):
        stub = _BrokerStub(results)
        orchestrator.drive_paper_lifecycle(
            order, submit_decision=stub.submit_decision
        )
        rm = stub.calls[0]["runtime_mode"]
        assert rm.paper_enabled is True
        assert rm.live_transmit_allowed() is False
