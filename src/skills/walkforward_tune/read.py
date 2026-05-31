"""Walkforward-tuning-loop ``read`` leaf — firewall-bounded model-trace read +
event-queue drain (task 2.5).

The read path for the fit's behavioral analysis (design §I/O & Audit Leaves →
``read``). Two functions, both pure-ish leaves (P1 — no MCP, no LLM, no
orchestration):

  * ``read_firewalled(keys, is_boundary, conn=None) -> ReadSet`` — wraps the
    LANDED telemetry reader ``reader.query_trace(filters={..., 'until':
    is_boundary})`` (the model trace) and drains the event queue, returning a
    ``ReadSet`` carrying the firewall-bounded trace slice + the drained anomaly
    events. The firewall predicate is ``until = is_boundary`` — the read
    excludes ``event_ts > is_boundary`` so no out-of-sample observation leaks
    into the fit (R2.1).
  * ``drain_events(conn=None) -> list[Event]`` — ``SELECT … FROM
    execution_daemon_event_queue WHERE drained_at IS NULL`` → build ``Event``s
    → ``UPDATE … SET drained_at = NOW() WHERE … AND drained_at IS NULL``,
    surfacing anomaly events (safe_mode / kill_switch / lifecycle) for the
    fit's behavioral analysis (R10.5). The set-once watermark makes the drain
    idempotent — a re-drain matches no rows (R10.2).

Boundary (design §Allowed Dependencies / §Out of Boundary):
  * Read (LANDED): ``reader.query_trace`` (the model trace) and the
    ``execution_daemon_event_queue.drained_at`` watermark (mig 051) — this loop
    is the SOLE external drainer; it does NOT own the queue's emit side.
  * It does **NOT** read the ``counterfactual_ledger`` (reactive P&L comes from
    the harness's ``OutcomeRecord``s, never the ledger) and does NOT fetch
    replay inputs (the consumed ``reactive-replay-harness`` fetches its own
    historical data).

``conn=None`` is the **dry-run** path (task 2.5 / design "conn=None dry-run
supported"). It opens NO connection and issues NO SQL — the trace_writer idiom
(``src/reactive/telemetry/trace_writer.py``: ``conn is None`` ⟹ dry-run, never
opens a socket), NOT the reader/persistence "open-my-own-connection" idiom. A
live read/drain therefore requires an explicit ``conn`` handed down by the
orchestrator. ``read_firewalled`` dry-run returns an empty, boundary-stamped
``ReadSet`` without touching the reader (whose own ``conn=None`` WOULD open a
live connection).

Strict dependency (design §"File Structure Plan → Dependency direction"):
``types → read``; ``read`` imports the LANDED ``reactive.telemetry.reader`` and
the owned ``types`` only. No other walkforward leaf is imported; no consumer
spec is imported.

Requirements: 2.1 (read only up to the IS boundary), 10.1 (reader-only
consumption — no ledger), 10.2 (drain not own emit; idempotent watermark),
10.5 (incorporate drained anomaly events into the fit's behavioral analysis).
"""

from __future__ import annotations

from typing import Any

from src.reactive.telemetry.reader import query_trace
from src.skills.walkforward_tune.types import Event, ReadSet

# Event-queue columns the drain SELECT projects, in order, so each result tuple
# zips back deterministically. Mirrors mig 051's `execution_daemon_event_queue`
# column set (event_id, run_id, event_type, payload, created_at). `drained_at`
# is not projected — the drain only reads undrained rows and then sets it.
_QUEUE_COLUMNS: tuple[str, ...] = (
    "event_id",
    "run_id",
    "event_type",
    "payload",
    "created_at",
)

# SELECT only the still-undrained rows. ORDER BY created_at gives a stable,
# replay-friendly ordering (oldest anomaly first), mirroring the reader's
# ORDER-BY discipline. No filter value is interpolated — the predicate is
# fixed (`drained_at IS NULL`), so there is nothing to bind.
_DRAIN_SELECT_SQL = (
    "SELECT event_id, run_id, event_type, payload, created_at "
    "FROM execution_daemon_event_queue "
    "WHERE drained_at IS NULL "
    "ORDER BY created_at"
)

# Mark exactly the drained event_ids, set-once (NULL -> value). The
# `AND drained_at IS NULL` keeps the UPDATE consistent with mig 051's set-once
# guard (a second write of an already-drained row is a no-op, never an error)
# and makes the watermark idempotent. The id list is ALWAYS bound with %s
# (an ANY(%s) array bind), never interpolated.
_DRAIN_UPDATE_SQL = (
    "UPDATE execution_daemon_event_queue "
    "SET drained_at = NOW() "
    "WHERE event_id = ANY(%s) AND drained_at IS NULL"
)


def drain_events(conn: Any = None) -> list[Event]:
    """Drain the after-market event queue: undrained rows → ``Event``s, then
    mark them drained.

    ``SELECT … WHERE drained_at IS NULL`` → build one ``Event`` per row →
    ``UPDATE … SET drained_at = NOW()`` for exactly those event_ids. The
    set-once watermark (mig 051) makes the drain idempotent: a subsequent drain
    matches no rows and returns ``[]`` (R10.2). The returned events are the
    anomaly events (safe_mode / kill_switch / lifecycle) surfaced to the fit's
    behavioral analysis (R10.5).

    Args:
        conn: a psycopg connection. ``None`` ⟹ the **dry-run** path: open no
            connection, issue no SQL, return ``[]`` (task 2.5 — "dry-run
            touches no DB"). A live drain requires an explicit ``conn`` from
            the orchestrator (unlike the reader, this leaf's ``conn=None`` does
            NOT open its own connection — the trace_writer idiom).

    Returns:
        The drained ``Event``s (empty on a dry-run or an empty queue).
    """
    if conn is None:
        # Dry-run: never touch the DB (no SELECT, no UPDATE, no connection).
        return []

    with conn.cursor() as cur:
        cur.execute(_DRAIN_SELECT_SQL)
        rows = cur.fetchall()

    events = [_row_to_event(dict(zip(_QUEUE_COLUMNS, row))) for row in rows]

    if not events:
        # Nothing undrained — do not fire a spurious watermark UPDATE.
        return []

    drained_ids = [e.event_id for e in events]
    # Wrap the watermark UPDATE in an explicit transaction (mirrors the sibling
    # write-leaves publish.py/audit.py + design.md's `_dsn()` + `.transaction()`
    # convention). On a non-autocommit connection a bare UPDATE rolls back at
    # connection close, re-fetching the same "undrained" rows next cycle — which
    # would defeat R10.2 idempotency at runtime. The transaction commits the
    # set-once watermark on clean exit.
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(_DRAIN_UPDATE_SQL, (drained_ids,))

    return events


def read_firewalled(
    keys: dict[str, Any],
    is_boundary: str,
    conn: Any = None,
) -> ReadSet:
    """Read the model trace up to the in-sample boundary + drain the queue.

    Wraps ``reader.query_trace(filters={**keys, 'until': is_boundary})`` — the
    ``until`` filter is the temporal firewall: the read excludes ``event_ts >
    is_boundary``, so no out-of-sample observation can leak into the fit
    (R2.1). The drained anomaly events are surfaced on the returned ``ReadSet``
    for the fit's behavioral analysis (R10.5).

    This leaf reads ONLY the model trace + the event queue — it does **not**
    read the ``counterfactual_ledger`` and does not fetch replay inputs (R10.1;
    reactive P&L comes from the harness's ``OutcomeRecord``s).

    Args:
        keys: the correlation-key filters to scope the read (any subset the
            reader whitelists — ``run_id`` / ``code_version`` / ``param_version``
            / ``walk_forward_window`` / ``kind``). ``until`` is added here from
            ``is_boundary``; do not pass it in ``keys``.
        is_boundary: the in-sample boundary ISO timestamp — becomes the reader's
            ``until`` bound (``event_ts <= is_boundary``), the firewall edge.
        conn: a psycopg connection. ``None`` ⟹ the **dry-run** path: touch no
            DB (open no connection, call neither the reader nor the drain) and
            return an empty, boundary-stamped ``ReadSet``. A live read requires
            an explicit ``conn`` (passed straight through to the reader and the
            drain). NB: ``query_trace``'s own ``conn=None`` WOULD open a live
            connection, so the dry-run path deliberately skips calling it.

    Returns:
        A ``ReadSet`` carrying ``is_boundary`` + the firewall-bounded trace
        slice (``trace_rows``) + the drained anomaly events (``drained_events``).
    """
    if conn is None:
        # Dry-run: no reader call, no drain, no connection. Stamp the boundary
        # so the (empty) ReadSet still records what it would have been bounded
        # by.
        return ReadSet(
            is_boundary=is_boundary,
            trace_rows=[],
            drained_events=[],
        )

    # Live: the IS boundary becomes the reader's `until` bound — the firewall.
    # `keys` carries only the correlation-key filters; never let a caller's
    # `until` override the boundary (the boundary is the firewall edge).
    filters: dict[str, Any] = {k: v for k, v in keys.items() if k != "until"}
    filters["until"] = is_boundary

    trace_rows = query_trace(filters=filters, conn=conn)
    drained = drain_events(conn=conn)

    return ReadSet(
        is_boundary=is_boundary,
        trace_rows=list(trace_rows),
        drained_events=drained,
    )


def _row_to_event(row: dict[str, Any]) -> Event:
    """Project one queue row dict to the owned ``Event`` shape.

    ``event_ts`` on ``Event`` is the time the event was queued — mapped from
    the queue's ``created_at`` (mig 051; the queue has no separate event_ts
    column, ``created_at`` IS the enqueue time). Coerced to ``str`` so ``Event``
    holds an ISO-string boundary-comparable value regardless of whether the
    driver hands back a ``datetime`` or a string.
    """
    created_at = row.get("created_at")
    return Event(
        event_id=str(row["event_id"]),
        event_type=row["event_type"],
        event_ts="" if created_at is None else str(created_at),
        payload=row.get("payload") or {},
    )


__all__ = [
    "read_firewalled",
    "drain_events",
]
