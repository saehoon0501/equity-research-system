"""Inner-ring test for event-queue emit (task 3.4).

Boundary: event_queue (Requirement 9 — specifically 9.1). Asserts the Observable
from tasks.md 3.4 + the §"Persistence — ``event_queue``" contract
(design.md:317-318) + the §"Data Models -> execution_daemon_event_queue"
single-drainer / emit-only invariant + migration 051, tested **against the
``conn=None`` dry-run** (the inner-ring seam — no live DB, no MCP, no LLM,
no ``src.survival``):

  * emitting an event builds **exactly one INSERT row** with the migration-051
    client-supplied columns (run_id, event_type, payload) and **never writes
    ``drained_at``** — the daemon is the emit side only; ``drained_at`` is set
    EXCLUSIVELY by the single external drainer (walkforward-tuning-loop), so the
    daemon's shaped row must not carry it (Req 9.1 / design Data Models);
  * the module **exposes no drain path** — no public name implies draining /
    marking-drained / clearing the queue (the daemon never drains);
  * the ``conn=None`` dry-run shape assertion — the shaped row mirrors the
    landed trace_writer dry-run idiom (validate + shape, no connection opened).

Pure + deterministic against synthetic event payloads; the emit is validated by
the ``conn=None`` dry-run path which shapes the row to its
``execution_daemon_event_queue`` columns without opening a connection.
"""

from __future__ import annotations

import inspect

import pytest

import src.reactive.daemon.event_queue as event_queue_module
from src.reactive.daemon.event_queue import (
    EVENT_TYPES,
    emit_event,
)

_RUN_ID = "22222222-2222-2222-2222-222222222222"


# --- The six emit-able event types (migration 051 CHECK + design Data Models) --


def test_event_types_match_migration_051_check() -> None:
    """The emit-able event vocabulary IS the migration-051 CHECK set (Req 9.1).

    decision | fill | lifecycle | command | safe_mode | kill_switch — exactly
    the six discriminated kinds the table's ``event_type`` CHECK admits.
    """
    assert EVENT_TYPES == (
        "decision",
        "fill",
        "lifecycle",
        "command",
        "safe_mode",
        "kill_switch",
    )


@pytest.mark.parametrize("event_type", [
    "decision",
    "fill",
    "lifecycle",
    "command",
    "safe_mode",
    "kill_switch",
])
def test_emit_builds_one_insert_row_per_event_type(event_type: str) -> None:
    """Emitting any of the six event types builds exactly ONE shaped INSERT row.

    Observable: "emitting an event INSERTs one row". On the ``conn=None``
    dry-run the shaped row is returned (nothing written), carrying the
    client-supplied migration-051 columns.
    """
    shaped = emit_event(
        run_id=_RUN_ID,
        event_type=event_type,
        payload={"k": "v"},
        conn=None,
    )
    assert isinstance(shaped, list)
    assert len(shaped) == 1
    row = shaped[0]
    assert row["run_id"] == _RUN_ID
    assert row["event_type"] == event_type
    assert row["payload"] == {"k": "v"}


def test_emit_never_writes_drained_at() -> None:
    """The shaped emit row NEVER carries ``drained_at`` (single-drainer invariant).

    Observable: "never writes ``drained_at``". ``drained_at`` is the sole
    mutable column, set EXCLUSIVELY by the external drainer
    (walkforward-tuning-loop); the daemon emits only, so a shaped emit row must
    not name it at all (a value here would either fail the migration-051 column
    set or, worse, pre-stamp a drain the daemon must never perform).
    """
    shaped = emit_event(
        run_id=_RUN_ID,
        event_type="decision",
        payload={"decision": "LONG"},
        conn=None,
    )
    row = shaped[0]
    assert "drained_at" not in row


def test_emit_rejects_unknown_event_type() -> None:
    """An event_type outside the migration-051 CHECK set is rejected fail-fast.

    A bad discriminator must raise before any INSERT (fail-fast, the
    trace_writer idiom) rather than producing a row the DB CHECK would reject.
    """
    with pytest.raises(ValueError):
        emit_event(
            run_id=_RUN_ID,
            event_type="not_a_real_event",
            payload={},
            conn=None,
        )


def test_emit_rejects_missing_run_id() -> None:
    """A missing/empty run_id is rejected fail-fast (the correlation key is NOT NULL).

    ``run_id`` is ``NOT NULL`` in migration 051 (the epoch correlation key); an
    emit with no run_id must raise before any INSERT, not defer to the DB.
    """
    with pytest.raises(ValueError):
        emit_event(
            run_id="",
            event_type="decision",
            payload={},
            conn=None,
        )


def test_module_exposes_no_drain_path() -> None:
    """The module exposes NO drain path (the daemon never drains, Req 9.1).

    Observable: "the module exposes no drain path". No public callable name may
    imply draining / marking-drained / clearing the queue — ``drained_at`` is
    set exclusively by the single external drainer (walkforward-tuning-loop),
    out of the daemon's boundary.
    """
    public_names = [
        name
        for name, _obj in inspect.getmembers(event_queue_module)
        if not name.startswith("_")
    ]
    forbidden_substrings = ("drain", "dequeue", "consume", "watermark", "clear")
    offenders = [
        name
        for name in public_names
        if any(sub in name.lower() for sub in forbidden_substrings)
    ]
    assert offenders == [], (
        f"event_queue must expose no drain path; found drain-like public "
        f"names: {offenders}"
    )


def test_emit_event_signature_takes_caller_passed_conn() -> None:
    """``emit_event`` takes a caller-passed ``conn`` defaulting to None (dry-run).

    The daemon owns its connection (§14.10) and passes it explicitly; ``conn=None``
    is the inner-ring dry-run seam (mirrors the landed trace_writer).
    """
    sig = inspect.signature(emit_event)
    assert "conn" in sig.parameters
    assert sig.parameters["conn"].default is None


def test_payload_serializes_non_native_json_types() -> None:
    """A payload with non-native JSON types (e.g. Decimal) shapes without error.

    The payload is schema-free JSONB; the daemon's emit fields (Decimal sizes,
    datetimes, UUIDs, numpy scalars) must shape cleanly — the dry-run carries
    the raw payload, the live INSERT serializes it with the canonical default.
    """
    from decimal import Decimal

    shaped = emit_event(
        run_id=_RUN_ID,
        event_type="fill",
        payload={"fill_volume": Decimal("1.5")},
        conn=None,
    )
    assert shaped[0]["payload"] == {"fill_volume": Decimal("1.5")}
