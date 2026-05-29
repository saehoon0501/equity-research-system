"""Pure-unit shape/contract tests for the Decision-Trace Telemetry types.

Task 1.1 (decision-trace-telemetry). Asserts the named observables the
parent's import/shape check can't on its own: the frozen guarantee and the
parent-ref asymmetry (a `fill` carries `parent_trace_id`, a `decision` does
not). No DB, no MCP, no I/O — these are pure leaf types (P1). The writer's
runtime behavior is tested later in task 3.1.

Requirements: 1.4 (FillOutcomeRow surface), 3.1 (correlation keys),
8.2 (flexible `trace` payload alongside typed keys).
"""

from __future__ import annotations

import dataclasses as d

import pytest

from src.reactive.telemetry import (
    CorrelationKeys,
    DecisionTraceRow,
    FillOutcomeRow,
)


def _keys() -> CorrelationKeys:
    return CorrelationKeys(
        run_id="00000000-0000-0000-0000-000000000000",
        code_version="c1",
        param_version="p1",
        walk_forward_window="2026Q1",
    )


def test_correlation_keys_fields_and_nullable_window() -> None:
    # Requirement 3.1: the four typed correlation keys, in order.
    assert [f.name for f in d.fields(CorrelationKeys)] == [
        "run_id",
        "code_version",
        "param_version",
        "walk_forward_window",
    ]
    # walk_forward_window is nullable per the design contract.
    assert CorrelationKeys("r", "c", "p", None).walk_forward_window is None


def test_decision_row_shape() -> None:
    assert [f.name for f in d.fields(DecisionTraceRow)] == [
        "trace_id",
        "keys",
        "event_ts",
        "trace",
    ]


def test_fill_row_shape() -> None:
    # Requirement 1.4: the fill is a separate linked row, not a mutation.
    assert [f.name for f in d.fields(FillOutcomeRow)] == [
        "trace_id",
        "parent_trace_id",
        "keys",
        "event_ts",
        "trace",
    ]


def test_parent_ref_asymmetry() -> None:
    fill_fields = {f.name for f in d.fields(FillOutcomeRow)}
    decision_fields = {f.name for f in d.fields(DecisionTraceRow)}
    assert "parent_trace_id" in fill_fields
    assert "parent_trace_id" not in decision_fields


def test_rows_are_frozen() -> None:
    decision = DecisionTraceRow(
        trace_id="t", keys=_keys(), event_ts="2026-05-29T00:00:00Z", trace={}
    )
    fill = FillOutcomeRow(
        trace_id="f",
        parent_trace_id="t",
        keys=_keys(),
        event_ts="2026-05-29T00:01:00Z",
        trace={},
    )
    with pytest.raises(d.FrozenInstanceError):
        decision.trace_id = "x"  # type: ignore[misc]
    with pytest.raises(d.FrozenInstanceError):
        fill.parent_trace_id = "y"  # type: ignore[misc]
    with pytest.raises(d.FrozenInstanceError):
        _keys().run_id = "z"  # type: ignore[misc]


def test_trace_payload_is_a_flexible_mapping() -> None:
    # Requirement 8.2: per-decision detail rides in the JSONB `trace` blob,
    # so new signal fields need no type change here.
    payload = {"gate_link": "Survive", "signal_values": {"a": 1}, "declined": True}
    row = DecisionTraceRow(
        trace_id="t", keys=_keys(), event_ts="2026-05-29T00:00:00Z", trace=payload
    )
    assert row.trace["declined"] is True
