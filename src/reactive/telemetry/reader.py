"""Decision-Trace Telemetry: the read/replay surface (leaf, direct-psycopg).

The consumer-agnostic SELECT-only surface over `decision_process_trace`
(migration 048), following the repo's direct-psycopg convention
(`_dsn()` + `conn=None` opens-its-own; mirrors
`src/shared/regime_sidecar/persistence.py`). Per the design's
"Components and Interfaces -> Telemetry leaf -> reader":

  * `query_trace(filters, conn=None) -> list[dict]` retrieves trace rows
    filtered by any subset of the correlation keys plus a since/until time
    bound and `kind`.

Boundary (P1 / requirements 7.1-7.3): a leaf — direct psycopg, NO MCP, NO
account/survival reads, NO aggregates (R7.3 — analysis is downstream). This is
a SELECT-only surface: it reads rows and never mutates them.

R5.2 — PROVIDE, never enforce. Every returned row carries the full column set,
including `event_ts` and `walk_forward_window`, so a consumer (the
walk-forward tuner, the in-session monitor) can enforce its OWN temporal
firewall. This surface does not itself enforce a firewall; a `since`/`until`
bound is offered as a convenience predicate the consumer chooses to pass.

R6.1 / R6.2 — replay/read filterable by the correlation keys. Consumer-agnostic:
the reader knows only the correlation keys + the two convenience bounds; it
holds no consumer-specific logic.

SQL-injection safety: every allowed filter key maps to a FIXED
`(column, operator)` pair via the `_FILTER_SPEC` whitelist. The clause is built
only from whitelisted keys; every VALUE is bound with a psycopg `%s`
placeholder. No filter key and no filter value is ever interpolated into the
SQL string. An unknown filter key fails fast with `ValueError` (mirrors the
writer's boundary discipline).
"""

from __future__ import annotations

import os
from typing import Any

import psycopg

# decision_process_trace columns in migration-048 DDL order. The SELECT projects
# exactly these, and each result tuple is zipped back to this order — so a
# returned dict always carries ALL columns (notably `event_ts` +
# `walk_forward_window` for the consumer-enforced firewall, R5.2).
_COLUMNS: tuple[str, ...] = (
    "trace_id",
    "kind",
    "parent_trace_id",
    "event_ts",
    "run_id",
    "code_version",
    "param_version",
    "walk_forward_window",
    "trace",
    "created_at",
)

_SELECT_PREFIX = f"SELECT {', '.join(_COLUMNS)} FROM decision_process_trace"

# Whitelist: filter key -> (column, SQL operator fragment). The value is ALWAYS
# bound with %s; the key/operator come only from this fixed map, never from
# caller input. `since`/`until` are range predicates on event_ts (cast to
# timestamptz, mirroring the writer's own cast so a text/ISO bound compares
# correctly against the TIMESTAMPTZ column). All others are equality on a
# correlation key (or the kind discriminator).
_FILTER_SPEC: dict[str, tuple[str, str]] = {
    "run_id": ("run_id", "="),
    "code_version": ("code_version", "="),
    "param_version": ("param_version", "="),
    "walk_forward_window": ("walk_forward_window", "="),
    "kind": ("kind", "="),
    "since": ("event_ts", ">="),
    "until": ("event_ts", "<="),
}

# Filters whose value must be cast to timestamptz in the placeholder.
_TS_FILTERS = frozenset({"since", "until"})


def _dsn() -> str:
    """Build the Postgres DSN from env — mirrors
    `src/shared/regime_sidecar/persistence.py::_dsn()` and the writer's
    `_dsn()` exactly (a live read needs a real connection).
    """
    return (
        f"postgresql://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}"
        f"@{os.environ.get('POSTGRES_HOST', '127.0.0.1')}:{os.environ.get('POSTGRES_PORT', '5432')}"
        f"/{os.environ['POSTGRES_DB']}"
    )


def _build_query(filters: dict[str, Any]) -> tuple[str, list[Any]]:
    """Compose the parameterized SELECT + ordered bind params from `filters`.

    Returns `(sql, params)`. Only whitelisted keys contribute a clause; an
    unknown key raises `ValueError` (fail-fast). Every value is a `%s` bind in
    clause order — no key or value is interpolated into the SQL string.
    Empty filters → the bare SELECT (return all). Always `ORDER BY event_ts`
    for a stable, replay-friendly ordering.
    """
    clauses: list[str] = []
    params: list[Any] = []
    for key, value in filters.items():
        spec = _FILTER_SPEC.get(key)
        if spec is None:
            raise ValueError(
                f"query_trace: unknown filter key {key!r}; "
                f"allowed: {sorted(_FILTER_SPEC)}"
            )
        column, operator = spec
        placeholder = "%s::timestamptz" if key in _TS_FILTERS else "%s"
        clauses.append(f"{column} {operator} {placeholder}")
        params.append(value)

    sql = _SELECT_PREFIX
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY event_ts"
    return sql, params


def query_trace(
    filters: dict[str, Any] | None = None,
    conn: Any = None,
) -> list[dict]:
    """Read trace rows from `decision_process_trace`, filtered by `filters`.

    Consumer-agnostic SELECT-only surface (R6.1, R6.2). Each matching row is
    returned as a dict carrying ALL columns (`trace_id, kind, parent_trace_id,
    event_ts, run_id, code_version, param_version, walk_forward_window, trace,
    created_at`) so a consumer has `event_ts` + `walk_forward_window` to enforce
    its own temporal firewall (R5.2 — this surface PROVIDES, never enforces).

    A decision row and its linked fill row are joinable by the fill's
    `parent_trace_id` (= the decision's `trace_id`); a `(code_version,
    param_version, walk_forward_window)` filter returns both because the fill
    carries the decision's window for attribution.

    Args:
        filters: any subset of the allowed keys. Equality keys: `run_id`,
            `code_version`, `param_version`, `walk_forward_window`, `kind`.
            Range keys on `event_ts`: `since` (`event_ts >= since`), `until`
            (`event_ts <= until`). An empty/None mapping returns all rows.
            An unknown key raises `ValueError`.
        conn: a psycopg connection. None ⟹ open one via `_dsn()` and close it
            after the read (read-only; no commit needed) — mirrors
            `persistence.py`'s `own_conn` convention. A live read requires a
            real connection.

    Returns:
        A list of row dicts ordered by `event_ts`, one per matching row.

    Raises:
        ValueError: a filter key is not in the allowed whitelist (fail-fast).
    """
    sql, params = _build_query(filters or {})

    own_conn = conn is None
    if own_conn:
        conn = psycopg.connect(_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [dict(zip(_COLUMNS, row)) for row in rows]
    finally:
        if own_conn:
            conn.close()


__all__ = [
    "query_trace",
]
