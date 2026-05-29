"""Decision-Trace Telemetry: the append-only write path (leaf, direct-psycopg).

Two append-only writers for the reactive CFD layer's per-decision MODEL trace,
following the repo's direct-psycopg convention (`_dsn()` + `.transaction()` +
`conn=None` dry-run; mirrors `src/supervisor/emitter.py::emit_recommendation`
and `src/shared/regime_sidecar/persistence.py`). Per the design's
"Components and Interfaces -> Telemetry leaf -> trace_writer":

  * `write_decision_trace(rows, conn=None)` writes kind='decision' rows.
  * `write_fill_outcome(rows, conn=None)` writes kind='fill' rows (each links
    to its decision via `parent_trace_id`).

Boundary (P1 / requirements 7.1-7.3): a leaf — direct psycopg, NO MCP, NO
account/survival reads, NO aggregates. INSERT only; the writer itself issues
no UPDATE/DELETE (migration 048's `decision_process_trace_guard` enforces it
at the DB too — defense in depth). Owns the write path, NOT the emission calls
(the execution-daemon calls these; §14.10, requirement 7.2).

RECONCILED RETURN CONTRACT (resolves a design/tasks ambiguity).
    design.md "trace_writer" Contracts says `-> int` (rows written); tasks.md
    2.1 says dry-run "returns the shaped row(s)" and live "returns the count
    actually written." Reconciled per the `emit_recommendation` idiom by
    returning ``list[dict]`` (the shaped row-dicts) in BOTH modes:
      * `conn is None` (dry-run): build + return the shaped row-dicts; NO
        INSERT, no connection opened (the dry-run path never touches a conn,
        exactly like the emitter — unlike `persistence.py`, `conn=None` here
        does NOT mean "open my own connection").
      * live (`conn` passed): `INSERT ... ON CONFLICT (trace_id) DO NOTHING
        RETURNING trace_id`; a shaped row is appended to the result ONLY when
        the INSERT actually wrote (RETURNING yields a row). Thus
        ``len(result)`` == count actually written, and an idempotent re-send of
        the same client-minted `trace_id` returns an empty list (0 written).
    A whole batch is validated before any INSERT, and the INSERTs run inside
    one `conn.transaction()` so a mid-batch DB error (e.g. an FK violation on
    an unresolvable `parent_trace_id`) rolls the batch back atomically.

Idempotency (requirement covered by `ON CONFLICT (trace_id) DO NOTHING`): the
client-minted `trace_id` is the idempotency key — a re-sent write is a no-op.
This addresses the broker G10 double-send residual (design.md trace_writer).
"""

from __future__ import annotations

import json
import os
from typing import Any

from src.reactive.telemetry.schema import (
    CorrelationKeys,
    DecisionTraceRow,
    FillOutcomeRow,
)
from src.shared.audit_trail.hmac_verify import _json_default


def _trace_json_default(o: Any) -> Any:
    """JSONB serializer for the freeform `trace` payload (requirement 8.2).

    Mirrors `src/supervisor/emitter.py`, which serializes its JSONB columns
    with `json.dumps(..., default=_json_default)` (the canonical handler from
    `src.shared.audit_trail.hmac_verify`, covering datetime/date/UUID/Decimal).
    The `trace` blob is deliberately schema-free, so the daemon's own design
    fields (`Decimal` slippage/counterparty_price, `datetime`/`date` signal
    timestamps, `UUID`, numpy scalars) must all serialize — otherwise a live
    INSERT raises `TypeError` even though the `conn=None` dry-run never calls
    `json.dumps` and silently passes preview (the reviewer's finding).

    numpy scalars are coerced via their `.item()` -> native-Python method,
    duck-typed so this leaf takes NO hard numpy import (the pure-unit suite
    runs without numpy installed); every other type delegates to the canonical
    `_json_default`. None of datetime/date/UUID/Decimal expose a callable
    `.item`, so the delegation order is safe.
    """
    item = getattr(o, "item", None)
    if callable(item):
        return item()  # numpy scalar -> native python scalar
    return _json_default(o)

# kind discriminator is type-encoded on the dataclass; each writer hardcodes its
# literal and isinstance-checks its input (design.md schema: "the Python *type*
# is the kind discriminator").
_KIND_DECISION = "decision"
_KIND_FILL = "fill"


def _dsn() -> str:
    """Build the Postgres DSN from env — mirrors
    `src/shared/regime_sidecar/persistence.py::_dsn()` exactly.

    Not used by the writers themselves (a live write requires a caller-passed
    `conn`; the daemon owns the connection per §14.10). Exposed so the
    writer's callers and tests share one DSN helper.
    """
    return (
        f"postgresql://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}"
        f"@{os.environ.get('POSTGRES_HOST', '127.0.0.1')}:{os.environ.get('POSTGRES_PORT', '5432')}"
        f"/{os.environ['POSTGRES_DB']}"
    )


def _validate_keys(keys: CorrelationKeys, *, where: str) -> None:
    """Fail-fast: reject a row whose correlation keys are incomplete.

    Per the design "Error Handling" + requirement 3.1: `run_id`,
    `code_version`, and `param_version` must all be present (truthy);
    `walk_forward_window` MAY be None (nullable column, design "Physical").
    """
    if not isinstance(keys, CorrelationKeys):
        raise ValueError(
            f"{where}: expected CorrelationKeys, got {type(keys).__name__}"
        )
    for field_name in ("run_id", "code_version", "param_version"):
        value = getattr(keys, field_name)
        if value is None or (isinstance(value, str) and value.strip() == ""):
            raise ValueError(
                f"{where}: missing correlation key '{field_name}' "
                "(run_id/code_version/param_version are required; "
                "walk_forward_window may be None)"
            )


def _shape_row(
    *,
    trace_id: str,
    kind: str,
    parent_trace_id: str | None,
    event_ts: str,
    keys: CorrelationKeys,
    trace: dict,
) -> dict[str, Any]:
    """Project a row dataclass to the `decision_process_trace` column dict.

    Column set per migration 048 (client-supplied columns only; `created_at`
    takes its DB default). Correlation keys are flattened to their typed
    columns; `trace` stays as the JSONB payload dict.
    """
    return {
        "trace_id": trace_id,
        "kind": kind,
        "parent_trace_id": parent_trace_id,
        "event_ts": event_ts,
        "run_id": keys.run_id,
        "code_version": keys.code_version,
        "param_version": keys.param_version,
        "walk_forward_window": keys.walk_forward_window,
        "trace": trace,
    }


# decision_process_trace client-supplied columns, in INSERT order (created_at
# takes its DB default per migration 048). ON CONFLICT on the client-minted
# trace_id is the idempotency key; RETURNING trace_id lets us count exactly the
# rows actually written (none on a conflicting re-send).
_INSERT_SQL = """
    INSERT INTO decision_process_trace (
        trace_id, kind, parent_trace_id, event_ts,
        run_id, code_version, param_version, walk_forward_window,
        trace
    ) VALUES (
        %s, %s, %s, %s::timestamptz,
        %s, %s, %s, %s,
        %s::jsonb
    )
    ON CONFLICT (trace_id) DO NOTHING
    RETURNING trace_id
"""


def _persist(conn: Any, shaped_rows: list[dict]) -> list[dict]:
    """INSERT the already-validated shaped rows append-only, atomically.

    One `conn.transaction()` covers the whole batch (a mid-batch DB error —
    e.g. an FK violation on an unresolvable `parent_trace_id` — rolls the
    entire batch back; no partial write). Per row: `ON CONFLICT (trace_id) DO
    NOTHING RETURNING trace_id` — a shaped row is collected ONLY when the
    INSERT actually wrote (RETURNING yields a row); a conflicting re-send
    yields no row and is silently a no-op (idempotency). The returned list is
    therefore exactly the rows actually written.
    """
    written: list[dict] = []
    with conn.transaction():
        with conn.cursor() as cur:
            for shaped in shaped_rows:
                cur.execute(
                    _INSERT_SQL,
                    (
                        shaped["trace_id"],
                        shaped["kind"],
                        shaped["parent_trace_id"],
                        shaped["event_ts"],
                        shaped["run_id"],
                        shaped["code_version"],
                        shaped["param_version"],
                        shaped["walk_forward_window"],
                        json.dumps(shaped["trace"], default=_trace_json_default),
                    ),
                )
                if cur.fetchone() is not None:
                    written.append(shaped)
    return written


def write_decision_trace(
    rows: list[DecisionTraceRow],
    conn: Any = None,
) -> list[dict]:
    """Append kind='decision' trace rows (requirements 1.1-1.3, 1.5, 1.6).

    Each row captures one daemon decision: the lexicographic gate link, the
    signal values + derived probability at fire, liquidation proximity, any
    stop-out, and the declined/missed flag — all inside the flexible JSONB
    `trace` payload (requirement 8.2). A declined/missed entry is just a
    decision row with no subsequent fill (requirement 1.6).

    Args:
        rows: decision rows to append. Each must carry a client-minted
            `trace_id` and complete `CorrelationKeys`.
        conn: a psycopg connection. None ⟹ dry-run: validate + shape only,
            NO write, NO connection opened (mirrors `emit_recommendation`).

    Returns:
        The shaped row-dicts. On dry-run: every shaped row (nothing written).
        On a live write: exactly the rows actually INSERTed — so a re-send of
        the same `trace_id` returns ``[]`` (ON CONFLICT DO NOTHING).

    Raises:
        ValueError: a row is not a DecisionTraceRow (wrong kind), or its
            correlation keys are incomplete. Raised before ANY INSERT, so a
            bad row never produces a partial write.
    """
    # Validate the WHOLE batch before touching any connection (fail-fast; a
    # bad row at any index prevents inserting any row).
    shaped_rows: list[dict] = []
    for i, row in enumerate(rows):
        if not isinstance(row, DecisionTraceRow):
            raise ValueError(
                f"write_decision_trace[{i}]: expected DecisionTraceRow "
                f"(kind='decision'), got {type(row).__name__}"
            )
        _validate_keys(row.keys, where=f"write_decision_trace[{i}]")
        shaped_rows.append(
            _shape_row(
                trace_id=row.trace_id,
                kind=_KIND_DECISION,
                parent_trace_id=None,  # a decision row has no parent
                event_ts=row.event_ts,
                keys=row.keys,
                trace=row.trace,
            )
        )

    if conn is None:
        return shaped_rows  # dry-run: shaped rows, nothing written

    return _persist(conn, shaped_rows)


def write_fill_outcome(
    rows: list[FillOutcomeRow],
    conn: Any = None,
) -> list[dict]:
    """Append kind='fill' rows resolving prior decisions (requirement 1.4).

    Each fill is a SEPARATE linked row, never a mutation of the decision row
    (R1.4 ↔ R2; design "System Flows"). The JSONB `trace` payload carries the
    expected-vs-actual fill: expected_price, actual_fill_price, slippage,
    fill_volume, counterparty_price. `keys.walk_forward_window` carries the
    DECISION's window (attribution follows the decision), while `event_ts` is
    the fill's own (possibly later) landing time — the late-fill firewall is a
    consumer predicate on `event_ts`, not enforced here (requirement 5).

    Args:
        rows: fill rows to append. Each must carry a client-minted `trace_id`,
            complete `CorrelationKeys`, and a non-empty `parent_trace_id`.
        conn: a psycopg connection. None ⟹ dry-run (validate + shape only).

    Returns:
        The shaped row-dicts; on a live write, exactly the rows actually
        INSERTed (a re-send of the same `trace_id` returns ``[]``).

    Raises:
        ValueError: a row is not a FillOutcomeRow, its correlation keys are
            incomplete, or its `parent_trace_id` is missing/empty. Raised
            before ANY INSERT. NOTE: structural parent check only — the FK
            (migration 048 `REFERENCES decision_process_trace(trace_id)`)
            enforces real resolvability at INSERT and rolls the batch back on
            violation; the writer issues no SELECT (P1: no reads).
    """
    shaped_rows: list[dict] = []
    for i, row in enumerate(rows):
        if not isinstance(row, FillOutcomeRow):
            raise ValueError(
                f"write_fill_outcome[{i}]: expected FillOutcomeRow "
                f"(kind='fill'), got {type(row).__name__}"
            )
        _validate_keys(row.keys, where=f"write_fill_outcome[{i}]")
        if row.parent_trace_id is None or (
            isinstance(row.parent_trace_id, str)
            and row.parent_trace_id.strip() == ""
        ):
            raise ValueError(
                f"write_fill_outcome[{i}]: a fill row requires a non-empty "
                "parent_trace_id (the decision row it resolves)"
            )
        shaped_rows.append(
            _shape_row(
                trace_id=row.trace_id,
                kind=_KIND_FILL,
                parent_trace_id=row.parent_trace_id,
                event_ts=row.event_ts,
                keys=row.keys,
                trace=row.trace,
            )
        )

    if conn is None:
        return shaped_rows  # dry-run: shaped rows, nothing written

    return _persist(conn, shaped_rows)


__all__ = [
    "write_decision_trace",
    "write_fill_outcome",
]
