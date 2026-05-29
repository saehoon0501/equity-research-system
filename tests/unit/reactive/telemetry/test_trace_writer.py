"""Pure-unit tests for the Decision-Trace Telemetry writers (dry-run path).

Task 3.1 (decision-trace-telemetry). Asserts the design's "Testing Strategy ->
Unit (pure, <1s, no DB) — R9.1" cases against the ALREADY-IMPLEMENTED writers
(task 2.1): the `conn=None` dry-run returns the shaped row(s) and writes nothing,
and the boundary fail-fast rejections fire BEFORE any write. No LLM, no MCP, no
live DB — every case is `conn=None` / validation-only, so the suite runs sub-
second without a database (a write attempt on the dry-run path would AttributeError
on `None.transaction()`; a clean `list[dict]` return proves the no-write branch).

The writers are imported from the submodule, not the package root: `__init__.py`
re-exports only the schema types (consumers import the writers from their
submodule directly).

Requirements: 9.1 (append-only/validation verifiable by inner-ring tests without
LLM/MCP). Design: "Testing Strategy -> Unit (pure, <1s, no DB) — R9.1";
"Components and Interfaces -> trace_writer".
"""

from __future__ import annotations

import pytest

from src.reactive.telemetry import (
    CorrelationKeys,
    DecisionTraceRow,
    FillOutcomeRow,
)
from src.reactive.telemetry.trace_writer import (
    write_decision_trace,
    write_fill_outcome,
)


def _keys(walk_forward_window: str | None = "2026Q1") -> CorrelationKeys:
    return CorrelationKeys(
        run_id="00000000-0000-0000-0000-000000000000",
        code_version="c1",
        param_version="p1",
        walk_forward_window=walk_forward_window,
    )


def _decision_row(**overrides: object) -> DecisionTraceRow:
    base = {
        "trace_id": "dec-1",
        "keys": _keys(),
        "event_ts": "2026-05-29T00:00:00Z",
        "trace": {"gate_link": "Survive", "declined": False},
    }
    base.update(overrides)
    return DecisionTraceRow(**base)  # type: ignore[arg-type]


def _fill_row(**overrides: object) -> FillOutcomeRow:
    base = {
        "trace_id": "fill-1",
        "parent_trace_id": "dec-1",
        "keys": _keys(),
        "event_ts": "2026-05-29T00:01:00Z",
        "trace": {"expected_price": 100, "actual_fill_price": 101},
    }
    base.update(overrides)
    return FillOutcomeRow(**base)  # type: ignore[arg-type]


# --- Case 1: dry-run returns shaped row(s), writes nothing -------------------


def test_decision_dry_run_returns_shaped_row_writes_nothing() -> None:
    # conn=None ⟹ dry-run: validate + shape only, no connection opened.
    row = _decision_row()
    result = write_decision_trace([row], conn=None)

    # A non-empty list[dict] of shaped rows (nothing was written, but every
    # shaped row is returned for preview — design "trace_writer" postcondition).
    assert isinstance(result, list)
    assert len(result) == 1
    shaped = result[0]
    assert isinstance(shaped, dict)

    # Field-by-field: a dropped/renamed/mis-flattened field fails here. The
    # correlation keys are FLATTENED to top-level typed columns (_shape_row).
    assert shaped["trace_id"] == "dec-1"
    assert shaped["kind"] == "decision"
    assert shaped["parent_trace_id"] is None  # a decision row has no parent
    assert shaped["event_ts"] == "2026-05-29T00:00:00Z"
    assert shaped["run_id"] == row.keys.run_id
    assert shaped["code_version"] == "c1"
    assert shaped["param_version"] == "p1"
    assert shaped["walk_forward_window"] == "2026Q1"
    assert shaped["trace"] == {"gate_link": "Survive", "declined": False}


def test_fill_dry_run_returns_shaped_row_writes_nothing() -> None:
    row = _fill_row()
    result = write_fill_outcome([row], conn=None)

    assert isinstance(result, list)
    assert len(result) == 1
    shaped = result[0]
    assert isinstance(shaped, dict)

    assert shaped["trace_id"] == "fill-1"
    assert shaped["kind"] == "fill"
    assert shaped["parent_trace_id"] == "dec-1"  # fill carries its parent
    assert shaped["event_ts"] == "2026-05-29T00:01:00Z"
    assert shaped["run_id"] == row.keys.run_id
    assert shaped["walk_forward_window"] == "2026Q1"
    assert shaped["trace"] == {"expected_price": 100, "actual_fill_price": 101}


def test_dry_run_returns_every_row_in_batch() -> None:
    # The dry-run returns the WHOLE shaped batch (unlike a live write, which
    # returns only rows actually INSERTed). A batch of two yields two.
    rows = [_decision_row(trace_id="dec-1"), _decision_row(trace_id="dec-2")]
    result = write_decision_trace(rows, conn=None)
    assert [r["trace_id"] for r in result] == ["dec-1", "dec-2"]


# --- Case 2: fail-fast on a missing correlation key -------------------------


@pytest.mark.parametrize("missing_field", ["run_id", "code_version", "param_version"])
def test_decision_missing_required_correlation_key_raises(missing_field: str) -> None:
    bad_keys = CorrelationKeys(
        run_id="r",
        code_version="c",
        param_version="p",
        walk_forward_window="w",
    )
    # Rebuild with the chosen required key set to None (frozen dataclass).
    fields = {
        "run_id": bad_keys.run_id,
        "code_version": bad_keys.code_version,
        "param_version": bad_keys.param_version,
        "walk_forward_window": bad_keys.walk_forward_window,
    }
    fields[missing_field] = None
    keys = CorrelationKeys(**fields)  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        write_decision_trace([_decision_row(keys=keys)], conn=None)


def test_decision_empty_string_correlation_key_raises() -> None:
    # The validator treats a whitespace-only string as missing too.
    keys = CorrelationKeys(
        run_id="   ", code_version="c", param_version="p", walk_forward_window="w"
    )
    with pytest.raises(ValueError):
        write_decision_trace([_decision_row(keys=keys)], conn=None)


def test_fill_missing_required_correlation_key_raises() -> None:
    keys = CorrelationKeys(
        run_id="r", code_version=None, param_version="p", walk_forward_window="w"  # type: ignore[arg-type]
    )
    with pytest.raises(ValueError):
        write_fill_outcome([_fill_row(keys=keys)], conn=None)


def test_walk_forward_window_none_does_not_raise() -> None:
    # walk_forward_window is the ONLY nullable correlation key — proving the
    # validator is selective, not a blanket "all keys required".
    result = write_decision_trace(
        [_decision_row(keys=_keys(walk_forward_window=None))], conn=None
    )
    assert len(result) == 1
    assert result[0]["walk_forward_window"] is None


# --- Case 3: a fill requires a parent id ------------------------------------


def test_fill_missing_parent_trace_id_raises() -> None:
    with pytest.raises(ValueError):
        write_fill_outcome([_fill_row(parent_trace_id="")], conn=None)


def test_fill_whitespace_parent_trace_id_raises() -> None:
    with pytest.raises(ValueError):
        write_fill_outcome([_fill_row(parent_trace_id="   ")], conn=None)


# --- Case 4: a decision forbids a parent (wrong-kind guard) ------------------
#
# A DecisionTraceRow has NO parent_trace_id field at all, so "a decision forbids
# a parent" cannot be tested by constructing a decision-with-parent — the
# structural type already forbids it. The writer's real, assertable guard is the
# isinstance kind-check: handing a FillOutcomeRow (which carries a parent) to
# write_decision_trace is rejected BEFORE any write. (Task 3.1 explicitly
# sanctions this framing.)


def test_decision_writer_rejects_a_fill_row_wrong_kind() -> None:
    with pytest.raises(ValueError):
        write_decision_trace([_fill_row()], conn=None)  # type: ignore[list-item]


def test_fill_writer_rejects_a_decision_row_wrong_kind() -> None:
    # Symmetric reverse guard: the fill writer rejects a decision row.
    with pytest.raises(ValueError):
        write_fill_outcome([_decision_row()], conn=None)  # type: ignore[list-item]
