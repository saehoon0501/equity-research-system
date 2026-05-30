"""Inner-ring test for trace assembly (task 3.3).

Boundary: trace_assembler (Requirement 4). Asserts the Observable from
tasks.md 3.3 + the §Components ``trace_assembler`` contract (design.md:48 /
366-367) + Requirements-Traceability rows 4.1-4.6 / 2.5, tested **against the
landed ``write_decision_trace(conn=None)`` dry-run** (the inner-ring seam — no
live DB, no MCP, no LLM, no ``src.survival``):

  * a synthetic decision yields a ``DecisionTraceRow`` carrying the **complete
    four-key correlation set** (run_id, code_version, param_version,
    walk_forward_window) — the run_id + window the model does NOT provide are
    injected from the epoch (Req 4.1/4.2);
  * a **client-minted ``trace_id``** is stamped and the ``event_ts`` is the
    **decision time**, not the write time (Req 4.3);
  * **re-assembly of the same decision is idempotent on ``trace_id``** — the
    same (epoch, decision, event_ts) yields the same trace_id, so a re-sent
    write is an ``ON CONFLICT`` no-op (Req 4.5);
  * a **confirmed fill links to its originating decision** via
    ``parent_trace_id`` and is attributed to the DECISION's walk-forward window
    (Req 4.4);
  * the **substrate maps** into the trace payload — ``feature_values`` →
    ``signal_values``, ``binding_constraint`` → ``gate_link``, derived
    ``liq_proximity`` / ``stop_out`` / ``declined`` (Req 4.6 / 2.5).

Pure + deterministic against synthetic ``EpochContext`` + ``ReactiveDecision`` +
survival fields + a synthetic broker fill — the assembled rows are validated by
the landed ``write_decision_trace(conn=None)`` / ``write_fill_outcome(conn=None)``
dry-run, which shapes the row to its ``decision_process_trace`` columns without
opening a connection.
"""

from __future__ import annotations

import pytest

from src.reactive.daemon.trace_assembler import (
    assemble_decision_trace,
    assemble_fill_outcome,
)
from src.reactive.daemon.types import EpochContext, PinnedParams
from src.reactive.params import DEFAULTS
from src.reactive.telemetry.schema import (
    CorrelationKeys,
    DecisionTraceRow,
    FillOutcomeRow,
)
from src.reactive.telemetry.trace_writer import (
    write_decision_trace,
    write_fill_outcome,
)
from src.reactive.types import (
    CalibrationEvidence,
    DecisionSubstrate,
    ReactiveDecision,
)

_RUN_ID = "11111111-1111-1111-1111-111111111111"
_CODE_VERSION = "reactive@codeV1"
_PARAM_VERSION = "reactive@paramV1"
_WINDOW = "bootstrap-epoch-1"
_EVENT_TS = "2026-05-30T14:30:00+00:00"
_SYMBOL = "AAPL"


# --- Synthetic fixtures ----------------------------------------------------


def _epoch() -> EpochContext:
    """An EpochContext carrying the four correlation key components (P3)."""
    return EpochContext(
        run_id=_RUN_ID,
        code_version=_CODE_VERSION,
        param_version=_PARAM_VERSION,
        walk_forward_window=_WINDOW,
        pinned_params=PinnedParams(reactive_snapshot=DEFAULTS, survival_snapshot={}),
    )


def _substrate(*, atr: float = 3.0) -> DecisionSubstrate:
    return DecisionSubstrate(
        feature_values={"trend_vote": 1.0, "drawdown_atr": 0.5, "atr": atr},
        probability=0.72,
        effective_threshold=DEFAULTS.threshold,
        code_version=_CODE_VERSION,
        param_version=_PARAM_VERSION,
        calibration=CalibrationEvidence(brier=None, reliability=None),
    )


def _decision(
    decision: str = "LONG",
    *,
    direction_in: str = "LONG",
    sizing_hint: float | None = 10.0,
) -> ReactiveDecision:
    return ReactiveDecision(
        decision=decision,  # type: ignore[arg-type]
        direction_in=direction_in,  # type: ignore[arg-type]
        probability=0.72,
        sizing_hint=sizing_hint,
        non_final=True,
        reason=None if decision != "HOLD" else "invalid_direction",
        substrate=_substrate(),
    )


# --- Four-key correlation + trace_id mint + decision-time event_ts ---------


def test_decision_trace_carries_four_correlation_keys_minted_id_and_decision_ts():
    """A synthetic decision → a DecisionTraceRow with all four correlation keys,
    a minted trace_id, and a decision-time event_ts (Req 4.1/4.2/4.3)."""
    row = assemble_decision_trace(
        epoch=_epoch(),
        decision=_decision(),
        symbol=_SYMBOL,
        event_ts=_EVENT_TS,
    )

    assert isinstance(row, DecisionTraceRow)
    # Four-key correlation set, injected from the epoch (run_id + window the
    # model does not provide; code/param the model emits, echoed on the epoch).
    assert isinstance(row.keys, CorrelationKeys)
    assert row.keys.run_id == _RUN_ID
    assert row.keys.code_version == _CODE_VERSION
    assert row.keys.param_version == _PARAM_VERSION
    assert row.keys.walk_forward_window == _WINDOW
    # A client-minted trace_id is stamped.
    assert isinstance(row.trace_id, str) and row.trace_id != ""
    # event_ts is the DECISION time, not the write time.
    assert row.event_ts == _EVENT_TS

    # The landed dry-run writer validates + shapes the row with no DB.
    shaped = write_decision_trace([row], conn=None)
    assert len(shaped) == 1
    shaped_row = shaped[0]
    assert shaped_row["kind"] == "decision"
    assert shaped_row["parent_trace_id"] is None
    assert shaped_row["run_id"] == _RUN_ID
    assert shaped_row["code_version"] == _CODE_VERSION
    assert shaped_row["param_version"] == _PARAM_VERSION
    assert shaped_row["walk_forward_window"] == _WINDOW
    assert shaped_row["event_ts"] == _EVENT_TS


# --- Idempotency on trace_id (Req 4.5) -------------------------------------


def test_reassembly_of_same_decision_is_idempotent_on_trace_id():
    """Re-assembling the SAME decision (same epoch, symbol, event_ts) mints the
    SAME trace_id — so a re-sent write is an ON CONFLICT no-op (Req 4.5)."""
    first = assemble_decision_trace(
        epoch=_epoch(), decision=_decision(), symbol=_SYMBOL, event_ts=_EVENT_TS
    )
    second = assemble_decision_trace(
        epoch=_epoch(), decision=_decision(), symbol=_SYMBOL, event_ts=_EVENT_TS
    )

    assert first.trace_id == second.trace_id


def test_distinct_decisions_get_distinct_trace_ids():
    """Two decisions that differ (different event_ts) mint distinct trace_ids —
    the idempotency key keys on the decision identity, not a constant."""
    first = assemble_decision_trace(
        epoch=_epoch(), decision=_decision(), symbol=_SYMBOL, event_ts=_EVENT_TS
    )
    second = assemble_decision_trace(
        epoch=_epoch(),
        decision=_decision(),
        symbol=_SYMBOL,
        event_ts="2026-05-30T14:30:05+00:00",
    )

    assert first.trace_id != second.trace_id


# --- Substrate mapping (Req 4.6) -------------------------------------------


def test_substrate_maps_into_trace_payload_with_gate_link_and_derived_fields():
    """substrate.feature_values → signal_values; binding_constraint → gate_link;
    derived liq_proximity / stop_out / declined in the payload (Req 4.6)."""
    row = assemble_decision_trace(
        epoch=_epoch(),
        decision=_decision("LONG"),
        symbol=_SYMBOL,
        event_ts=_EVENT_TS,
        binding_constraint="margin_distance",
        liq_proximity=0.42,
        stop_out=False,
    )

    trace = row.trace
    # substrate.feature_values surfaces as signal_values (the reconstructable
    # continuous components).
    assert trace["signal_values"] == {
        "trend_vote": 1.0,
        "drawdown_atr": 0.5,
        "atr": 3.0,
    }
    # binding_constraint → gate_link (the triggering survival link).
    assert trace["gate_link"] == "margin_distance"
    # probability + effective_threshold carried through for reconstruction.
    assert trace["probability"] == 0.72
    assert trace["effective_threshold"] == DEFAULTS.threshold
    # the decision label (P9 vocabulary) is recorded.
    assert trace["decision"] == "LONG"
    # derived survival-band indicators.
    assert trace["liq_proximity"] == 0.42
    assert trace["stop_out"] is False
    # an actionable (non-HOLD) decision is not declined.
    assert trace["declined"] is False


def test_hold_decision_is_recorded_as_declined():
    """A HOLD / sub-threshold decision is a declined trace (Req 2.5 / 4.6) — a
    decision row still recorded, marked declined, no fill."""
    row = assemble_decision_trace(
        epoch=_epoch(),
        decision=_decision("HOLD", sizing_hint=None),
        symbol=_SYMBOL,
        event_ts=_EVENT_TS,
    )

    assert row.trace["declined"] is True
    assert row.trace["decision"] == "HOLD"
    # Still a complete, writable decision row.
    shaped = write_decision_trace([row], conn=None)
    assert len(shaped) == 1


def test_no_binding_constraint_yields_null_gate_link():
    """When no survival constraint binds (e.g. an ALLOW open), gate_link is None
    — the field is present (reconstructable) but null."""
    row = assemble_decision_trace(
        epoch=_epoch(), decision=_decision("LONG"), symbol=_SYMBOL, event_ts=_EVENT_TS
    )

    assert "gate_link" in row.trace
    assert row.trace["gate_link"] is None


# --- Fill linking (Req 4.4) ------------------------------------------------


def test_confirmed_fill_links_to_parent_decision_and_decision_window():
    """A confirmed fill → a FillOutcomeRow linked to its originating decision via
    parent_trace_id and attributed to the DECISION's walk-forward window (Req 4.4)."""
    decision_row = assemble_decision_trace(
        epoch=_epoch(), decision=_decision("LONG"), symbol=_SYMBOL, event_ts=_EVENT_TS
    )

    fill_row = assemble_fill_outcome(
        epoch=_epoch(),
        parent_trace_id=decision_row.trace_id,
        event_ts="2026-05-30T14:30:02+00:00",  # the fill's own LATER landing time
        fill={
            "expected_price": 100.0,
            "actual_fill_price": 100.2,
            "slippage": 0.2,
            "fill_volume": 10.0,
        },
    )

    assert isinstance(fill_row, FillOutcomeRow)
    # Linked to its originating decision.
    assert fill_row.parent_trace_id == decision_row.trace_id
    # The fill carries the DECISION's window (attribution follows the decision),
    # even though its event_ts is a later landing time.
    assert fill_row.keys.walk_forward_window == _WINDOW
    assert fill_row.event_ts == "2026-05-30T14:30:02+00:00"
    # The fill payload is carried.
    assert fill_row.trace["actual_fill_price"] == 100.2
    assert fill_row.trace["slippage"] == 0.2

    # The landed dry-run fill writer validates + shapes the linked row.
    shaped = write_fill_outcome([fill_row], conn=None)
    assert len(shaped) == 1
    assert shaped[0]["kind"] == "fill"
    assert shaped[0]["parent_trace_id"] == decision_row.trace_id


def test_fill_with_empty_parent_is_rejected_by_writer():
    """A fill row must carry a non-empty parent_trace_id — the assembler refuses
    to mint a parent-less fill (the decision↔fill link is mandatory, Req 4.4)."""
    with pytest.raises(ValueError):
        assemble_fill_outcome(
            epoch=_epoch(),
            parent_trace_id="",
            event_ts=_EVENT_TS,
            fill={"actual_fill_price": 100.0},
        )
