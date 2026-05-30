"""Trace assembly — the pure ReactiveDecision/fill → telemetry-row mapper (task 3.3).

Boundary: trace_assembler (Requirement 4). Source of truth:
``.kiro/specs/execution-daemon/design.md`` §"This Spec Owns → The telemetry row
assembly" (line 48) + §"Control — ``trace_assembler``" (line 366-367) + the
Requirements-Traceability rows 4.1-4.6 / 2.5.

What this module is
-------------------
A **pure mapping leaf** (no I/O) turning the daemon's per-tick decision evidence
— an epoch-pinned :class:`~src.reactive.daemon.types.EpochContext`, a reactive
``ReactiveDecision``, the survival ``binding_constraint`` + derived survival-band
indicators, and (on a confirmed fill) the broker fill — into the **landed
telemetry row types** the trace store consumes:
:class:`~src.reactive.telemetry.schema.DecisionTraceRow` and
:class:`~src.reactive.telemetry.schema.FillOutcomeRow`. The orchestrator (task
4.1) then passes the assembled rows to ``write_decision_trace`` /
``write_fill_outcome`` with the daemon's own ``conn``; this module owns the
**assembly**, never the write (P1 — the writer is the landed leaf, §14.10).

The contract (Req 4.x)
----------------------
* **4.1 complete four-key correlation.** Every assembled row carries the full
  :class:`CorrelationKeys` — ``run_id``, ``code_version``, ``param_version``,
  ``walk_forward_window`` — sourced from the ``EpochContext`` (P3: the epoch IS
  the correlation envelope).
* **4.2 inject the keys the model does not provide.** The signal model emits
  only ``code_version`` / ``param_version`` (on its substrate); the daemon
  injects the ``run_id`` + ``walk_forward_window`` from the epoch pin. The
  epoch's ``code_version`` / ``param_version`` are the authoritative correlation
  values (the substrate echoes the same, but the epoch is the pinned ground
  truth — P2).
* **4.3 client-minted trace_id + decision-time event_ts.** ``trace_id`` is
  minted client-side (Req 4.3 / 4.5 idempotency) and ``event_ts`` is stamped at
  **decision time** (the caller's tick time), never the write time.
* **4.4 fill linked + decision-window-attributed.** A confirmed fill is a
  SEPARATE linked row referencing the decision's ``trace_id`` via
  ``parent_trace_id``; its ``keys.walk_forward_window`` carries the DECISION's
  window (attribution follows the decision) even though its ``event_ts`` is the
  fill's own (possibly later) landing time.
* **4.5 idempotent on trace_id.** The decision ``trace_id`` is a **deterministic
  UUIDv5** over ``(run_id, symbol, event_ts)`` — re-assembling the SAME decision
  mints the SAME id, so a re-sent write is an ``ON CONFLICT (trace_id) DO
  NOTHING`` no-op (the writer's idempotency key).
* **4.6 reconstructable substrate.** The ``trace`` JSONB payload maps the
  decision substrate (``feature_values`` → ``signal_values``, ``probability``,
  ``effective_threshold``), the decision label (P9 vocabulary), the triggering
  survival link (``binding_constraint`` → ``gate_link``), and the derived
  ``liq_proximity`` / ``stop_out`` / ``declined`` indicators — sufficient to
  reconstruct the decision. A HOLD / sub-threshold decision is recorded as
  ``declined`` (Req 2.5) — still a decision row, just with no subsequent fill.

Pure leaf (P1): stdlib (``uuid``) + the daemon-owned types + the landed reactive
schema/decision shapes only — no numpy, no MCP, no DB, no ``src.survival``.
Deterministic + isolatable (P14): inner-ring-tested against the landed
``write_decision_trace(conn=None)`` / ``write_fill_outcome(conn=None)`` dry-run,
which validates + shapes the assembled rows with no connection opened.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from src.reactive.daemon.types import EpochContext
from src.reactive.telemetry.schema import (
    CorrelationKeys,
    DecisionTraceRow,
    FillOutcomeRow,
)
from src.reactive.types import ReactiveDecision

__all__ = [
    "assemble_decision_trace",
    "assemble_fill_outcome",
    "mint_decision_trace_id",
    "mint_fill_trace_id",
]

# A fixed namespace UUID for the daemon's client-minted trace ids. Deterministic
# UUIDv5 over (namespace, name) — so the SAME decision identity always mints the
# SAME trace_id (Req 4.5 idempotency), and the writer's ON CONFLICT (trace_id)
# silently no-ops a re-send. Generated once, hard-coded (a namespace constant,
# not a per-run value); never regenerate it — it pins the idempotency key.
_TRACE_NS = uuid.UUID("6f9b9d6e-7b2a-5c3d-8e1f-2a4b6c8d0e2f")

# The actionable decision vocabulary (R3.5/P9): anything else (HOLD or a
# sub-threshold no-op) is a DECLINED decision (Req 2.5/4.6) — still recorded.
_ACTIONABLE = ("LONG", "SHORT")


def _keys_from_epoch(
    epoch: EpochContext, *, walk_forward_window: str | None
) -> CorrelationKeys:
    """Build the four-key :class:`CorrelationKeys` from the epoch (Req 4.1/4.2).

    ``run_id`` + the ``walk_forward_window`` are the keys the signal model does
    NOT provide (Req 4.2) — both come from the epoch pin. ``code_version`` /
    ``param_version`` are the two keys the model emits, echoed onto the epoch and
    taken from the pinned epoch as the authoritative ground truth (P2).
    """
    return CorrelationKeys(
        run_id=epoch.run_id,
        code_version=epoch.code_version,
        param_version=epoch.param_version,
        walk_forward_window=walk_forward_window,
    )


def mint_decision_trace_id(run_id: str, symbol: str, event_ts: str) -> str:
    """Deterministically mint the decision's client-side ``trace_id`` (Req 4.3/4.5).

    A UUIDv5 over ``(run_id, symbol, event_ts)`` — the decision's identity within
    its epoch — so re-assembling the SAME decision yields the SAME id (idempotent
    re-send is a writer ON CONFLICT no-op), while a distinct decision (a later
    ``event_ts``, a different symbol, a different epoch) mints a distinct id. No
    wall-clock or randomness enters the id (a random ``uuid4`` would break Req 4.5).
    """
    name = f"{run_id}|{symbol}|{event_ts}"
    return str(uuid.uuid5(_TRACE_NS, name))


def mint_fill_trace_id(parent_trace_id: str, event_ts: str) -> str:
    """Deterministically mint a fill row's own ``trace_id`` (Req 4.4/4.5).

    A UUIDv5 over ``(parent_trace_id, event_ts)`` — the fill's identity (it
    resolves a specific decision at a specific landing time) — so a re-sent fill
    is idempotent on its own ``trace_id`` exactly as the decision row is. The
    fill row's ``trace_id`` is distinct from its ``parent_trace_id`` (the
    decision it links to).
    """
    name = f"fill|{parent_trace_id}|{event_ts}"
    return str(uuid.uuid5(_TRACE_NS, name))


def assemble_decision_trace(
    *,
    epoch: EpochContext,
    decision: ReactiveDecision,
    symbol: str,
    event_ts: str,
    binding_constraint: Optional[str] = None,
    liq_proximity: Optional[float] = None,
    stop_out: bool = False,
) -> DecisionTraceRow:
    """Map one daemon decision into a landed :class:`DecisionTraceRow` (Req 4.1-4.6).

    Pure + deterministic (P14): no I/O, no ``src.survival`` import. The returned
    row is consumable by ``write_decision_trace`` (the daemon passes its own
    ``conn``; ``conn=None`` is the inner-ring dry-run seam).

    Args:
        epoch: the pinned-param epoch (P3) — the correlation envelope supplying
            ``run_id`` / ``code_version`` / ``param_version`` /
            ``walk_forward_window`` (Req 4.1/4.2).
        decision: the ``ReactiveDecision`` from ``reactive.decide`` — its
            ``substrate`` maps into the reconstructable ``trace`` payload (Req
            4.6); a HOLD / sub-threshold decision is recorded as ``declined``
            (Req 2.5).
        symbol: the decided symbol — part of the decision's identity for the
            deterministic ``trace_id`` mint (Req 4.5).
        event_ts: the **decision time** (Req 4.3) — stamped onto the row, never
            the write time, and part of the ``trace_id`` identity.
        binding_constraint: the triggering survival link (the gate's
            ``binding_constraint``) → ``gate_link`` in the payload; ``None`` when
            no survival constraint binds (e.g. an ALLOW open).
        liq_proximity: the derived liquidation-proximity figure from the survival
            gate (Req 4.6 / 10.2 — the daemon never computes it, it carries the
            gate's value); ``None`` when not surfaced.
        stop_out: the derived stop-out indicator (Req 4.6).

    Returns:
        A :class:`DecisionTraceRow` with the full four-key correlation set, a
        deterministically-minted ``trace_id``, a decision-time ``event_ts``, and
        the reconstructable substrate/survival ``trace`` payload.
    """
    trace_id = mint_decision_trace_id(epoch.run_id, symbol, event_ts)
    keys = _keys_from_epoch(epoch, walk_forward_window=epoch.walk_forward_window)

    substrate = decision.substrate
    declined = decision.decision not in _ACTIONABLE

    # The reconstructable JSONB payload (Req 4.6): substrate → signal_values,
    # binding_constraint → gate_link, derived survival-band indicators. The
    # correlation keys stay typed on `keys` (the writer flattens them to columns)
    # — they are NOT duplicated into the freeform payload.
    trace: dict[str, Any] = {
        "decision": decision.decision,
        "direction_in": decision.direction_in,
        "signal_values": dict(substrate.feature_values),
        "probability": substrate.probability,
        "effective_threshold": substrate.effective_threshold,
        "sizing_hint": decision.sizing_hint,
        "gate_link": binding_constraint,
        "liq_proximity": liq_proximity,
        "stop_out": stop_out,
        "declined": declined,
        "reason": decision.reason,
    }

    return DecisionTraceRow(
        trace_id=trace_id,
        keys=keys,
        event_ts=event_ts,
        trace=trace,
    )


def assemble_fill_outcome(
    *,
    epoch: EpochContext,
    parent_trace_id: str,
    event_ts: str,
    fill: dict[str, Any],
) -> FillOutcomeRow:
    """Map a confirmed fill into a landed :class:`FillOutcomeRow` (Req 4.4).

    The fill is a SEPARATE row LINKED to its originating decision via
    ``parent_trace_id`` (never a mutation of the decision row). Its
    ``keys.walk_forward_window`` carries the DECISION's window (attribution
    follows the decision), while ``event_ts`` is the fill's own (possibly later)
    landing time.

    Args:
        epoch: the originating decision's epoch — supplies the correlation keys
            (the DECISION's window is attributed to the fill, Req 4.4).
        parent_trace_id: the decision row's ``trace_id`` this fill resolves —
            must be non-empty (the decision↔fill link is mandatory; the writer
            also FK-enforces resolvability).
        event_ts: the fill's own landing time (may fall in a later window than
            the decision; the late-fill firewall is a consumer predicate).
        fill: the fill payload — expected_price, actual_fill_price, slippage,
            fill_volume, counterparty_price (the freeform JSONB ``trace``).

    Returns:
        A :class:`FillOutcomeRow` linked to its parent and attributed to the
        decision's walk-forward window.

    Raises:
        ValueError: ``parent_trace_id`` is missing/empty — a fill cannot exist
            without the decision it resolves (Req 4.4). Raised here (fail-fast)
            in addition to the writer's own structural check.
    """
    if parent_trace_id is None or (
        isinstance(parent_trace_id, str) and parent_trace_id.strip() == ""
    ):
        raise ValueError(
            "assemble_fill_outcome: a fill requires a non-empty parent_trace_id "
            "(the decision row it resolves; the decision↔fill link is mandatory)"
        )

    trace_id = mint_fill_trace_id(parent_trace_id, event_ts)
    # Attribution follows the DECISION: the fill carries the decision's window
    # (Req 4.4), so the correlation keys come from the (decision's) epoch.
    keys = _keys_from_epoch(epoch, walk_forward_window=epoch.walk_forward_window)

    return FillOutcomeRow(
        trace_id=trace_id,
        parent_trace_id=parent_trace_id,
        keys=keys,
        event_ts=event_ts,
        trace=dict(fill),
    )
