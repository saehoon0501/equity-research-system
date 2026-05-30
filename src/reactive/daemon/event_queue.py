"""Event-queue emit — the daemon's emit-only after-market hand-off (task 3.4).

Boundary: event_queue (Requirement 9 — specifically 9.1). Source of truth:
``.kiro/specs/execution-daemon/design.md`` §"Persistence — ``event_queue``"
(lines 317-318) + §"Data Models -> execution_daemon_event_queue (mig 051)"
(line 371) + §"Boundary Commitments -> The after-market event queue — emit side
only" (line 52) + Requirements-Traceability row 9.1 (line 267); the physical
table is ``db/migrations/051_execution_daemon_event_queue.sql``.

What this module is
-------------------
The daemon's **emit side** onto ``execution_daemon_event_queue``: a single
``emit_event`` that INSERTs ONE append-only row per call carrying a discriminated
``event_type`` (decision | fill | lifecycle | command | safe_mode | kill_switch,
Req 9.1) and a schema-free JSONB ``payload``. It follows the landed house
write idiom verbatim (``src/reactive/telemetry/trace_writer.py``): validate +
shape the row before touching any connection; ``conn=None`` is the **dry-run**
seam (return the shaped row, open NO connection); a live ``conn`` runs the
INSERT inside one ``conn.transaction()``.

The single-drainer drain contract (the load-bearing invariant)
--------------------------------------------------------------
This is an **EMIT-ONLY** surface. The daemon **NEVER drains** and this module
exposes **no drain path** (no SELECT, no ``drained_at`` UPDATE, no dequeue/clear):

  * ``drained_at`` is the table's ONLY mutable column and is set **NULL→value
    exactly once, EXCLUSIVELY by the single external drainer**
    (``walkforward-tuning-loop`` — the sole ``drained_at`` setter; design.md
    line 52 / 318, Data Models line 371). A daemon emit therefore must NOT
    even name ``drained_at`` — the shaped INSERT row carries only the
    client-supplied columns (``run_id`` / ``event_type`` / ``payload``);
    ``event_id`` + ``created_at`` take their DB defaults and ``drained_at``
    stays NULL until the drainer moves it once (migration 051 set-once guard).
  * If the in-session monitor needs in-session event visibility it uses a
    **read-only, non-draining SELECT** (out of this boundary; it must NOT
    become a second drainer — design.md "Open Questions / Risks").

A change to this single-drainer invariant (a second drainer, or the daemon
draining its own queue) is a named revalidation trigger (design.md
"Revalidation Triggers -> event-queue single-drainer").

Pure leaf (P1): stdlib (``json``) + the canonical JSONB serializer only — no
numpy, no MCP, no ``src.survival``. INSERT only; the writer issues no
UPDATE/DELETE (migration 051's guard enforces it at the DB too — defense in
depth). Inner-ring-tested against the ``conn=None`` dry-run (no live DB).
"""

from __future__ import annotations

import json
from typing import Any

from src.reactive.telemetry.trace_writer import _trace_json_default

__all__ = [
    "EVENT_TYPES",
    "emit_event",
]

# The discriminated event vocabulary — EXACTLY the migration-051 ``event_type``
# CHECK set (db/migrations/051:59-61) and the design Data Models enumeration
# (design.md line 371): decision / fill / lifecycle / command / safe_mode /
# kill_switch. An emit naming anything else is rejected fail-fast (the DB CHECK
# would reject it too — defense in depth).
EVENT_TYPES: tuple[str, ...] = (
    "decision",
    "fill",
    "lifecycle",
    "command",
    "safe_mode",
    "kill_switch",
)


# execution_daemon_event_queue client-supplied columns, in INSERT order. NOTE
# the deliberate ABSENCE of ``drained_at``: it is the single external drainer's
# set-once column (the daemon never writes it), and ``event_id`` + ``created_at``
# take their DB defaults (gen_random_uuid / now()), so the daemon supplies only
# run_id / event_type / payload (migration 051:56-65).
_INSERT_SQL = """
    INSERT INTO execution_daemon_event_queue (
        run_id, event_type, payload
    ) VALUES (
        %s, %s, %s::jsonb
    )
    RETURNING event_id
"""


def _shape_event(*, run_id: str, event_type: str, payload: dict) -> dict[str, Any]:
    """Project an emit call to the ``execution_daemon_event_queue`` column dict.

    Client-supplied columns only (migration 051). ``payload`` stays as the
    schema-free JSONB dict here; it is JSON-serialized at INSERT time. The dict
    deliberately omits ``drained_at`` — the daemon never sets it (single-drainer
    invariant); a value here would either break the column set or pre-stamp a
    drain the daemon must never perform.
    """
    return {
        "run_id": run_id,
        "event_type": event_type,
        "payload": payload,
    }


def emit_event(
    *,
    run_id: str,
    event_type: str,
    payload: dict[str, Any],
    conn: Any = None,
) -> list[dict]:
    """Emit ONE append-only event to ``execution_daemon_event_queue`` (Req 9.1).

    EMIT ONLY — INSERTs a single row and **never** drains, never sets
    ``drained_at`` (the single external drainer owns that set-once column). The
    row is validated + shaped before any connection is touched (fail-fast); a
    bad ``event_type`` or empty ``run_id`` raises before any INSERT.

    Args:
        run_id: the epoch_id (``execution_daemon_epoch.epoch_id``, P3) in effect
            on the emitting tick — the same run_id carried on the decision
            trace. ``NOT NULL`` in migration 051; required (truthy) here.
        event_type: one of :data:`EVENT_TYPES` (the migration-051 CHECK set).
        payload: the schema-free JSONB event body (decision/fill/lifecycle/
            command/safe_mode/kill_switch fields) — serialized with the
            canonical ``_trace_json_default`` (datetime/date/UUID/Decimal/numpy)
            at INSERT time.
        conn: a psycopg connection. ``None`` ⟹ **dry-run**: validate + shape
            only, NO write, NO connection opened (mirrors the landed
            ``write_decision_trace``).

    Returns:
        A one-element list with the shaped row-dict (the client-supplied
        columns; never ``drained_at``). On dry-run: the shaped row (nothing
        written). On a live write: the shaped row (the INSERT always writes —
        ``event_id`` is server-minted, so there is no idempotency conflict, the
        same shape is returned).

    Raises:
        ValueError: ``event_type`` is not a known emit kind, or ``run_id`` is
            missing/empty. Raised before ANY INSERT, so a bad emit never
            produces a partial write.
    """
    if event_type not in EVENT_TYPES:
        raise ValueError(
            f"emit_event: unknown event_type {event_type!r}; expected one of "
            f"{EVENT_TYPES}"
        )
    if run_id is None or (isinstance(run_id, str) and run_id.strip() == ""):
        raise ValueError(
            "emit_event: missing run_id (the epoch correlation key is NOT NULL; "
            "every event carries the emitting tick's run_id)"
        )

    shaped = _shape_event(run_id=run_id, event_type=event_type, payload=payload)

    if conn is None:
        return [shaped]  # dry-run: shaped row, nothing written, no conn opened

    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                _INSERT_SQL,
                (
                    shaped["run_id"],
                    shaped["event_type"],
                    json.dumps(shaped["payload"], default=_trace_json_default),
                ),
            )
            # event_id is server-minted; consume RETURNING to confirm the write.
            cur.fetchone()
    return [shaped]
