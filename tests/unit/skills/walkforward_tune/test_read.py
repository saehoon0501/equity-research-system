"""Pure-unit tests for the walkforward-tuning-loop ``read`` leaf (task 2.5).

``src/skills/walkforward_tune/read.py`` is the firewall-bounded model-trace
read + event-queue drain. It owns NO P&L read (the survival-net metric sources
reactive P&L from the harness's ``OutcomeRecord``s, NEVER the
``counterfactual_ledger`` — design §Allowed Dependencies). These are the
load-bearing observables (design §Testing Strategy → ``read.py``;
requirements 2.1, 10.1, 10.2, 10.5):

  * ``read_firewalled`` threads the IS boundary into ``query_trace`` as the
    ``until`` filter, so the firewall predicate excludes ``event_ts >
    is_boundary`` — no OOS observation leaks into the read (R2.1);
  * ``read_firewalled`` returns a ``ReadSet`` carrying the boundary + the
    firewall-bounded trace slice + the drained anomaly events (R10.5), and
    NEVER reads ``counterfactual_ledger`` (R10.1, the read-only boundary);
  * ``drain_events`` SELECTs only undrained rows, builds ``Event``s, then marks
    ``drained_at`` for exactly those rows — and is idempotent (a re-drain
    returns nothing because the rows are now drained, R10.2);
  * ``conn=None`` is the dry-run path — it touches NO DB (opens no connection,
    issues no SQL): the trace_writer idiom, not the persistence/reader
    open-my-own-connection idiom, because the task pins "conn=None dry-run,
    touches no DB".

No LLM, MCP, or live DB — a fake connection / fake cursor captures the SQL +
params, and the firewall is proven against a recorded ``query_trace`` call.

Requirements: 2.1 (read only up to the IS boundary), 10.1 (reader-only
consumption, no ledger), 10.2 (drain, not own emit; idempotent watermark),
10.5 (surface drained anomaly events to the fit).
"""

from __future__ import annotations

import importlib.util

from src.skills.walkforward_tune.read import drain_events, read_firewalled
from src.skills.walkforward_tune.types import Event, ReadSet


# --------------------------------------------------------------------------
# Fakes — capture the SQL/params a live path would issue, without a DB.
# --------------------------------------------------------------------------


class _FakeCursor:
    """A psycopg-cursor stand-in: records every (sql, params); replays a
    scripted ``fetchall`` per execute (FIFO). Supports the context-manager
    protocol (``with conn.cursor() as cur``).
    """

    def __init__(self, fetch_script):
        self._fetch_script = list(fetch_script)
        self.executed: list[tuple[str, object]] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        return self

    def fetchall(self):
        if self._fetch_script:
            return self._fetch_script.pop(0)
        return []


class _FakeTxn:
    """``conn.transaction()`` stand-in. Models psycopg3 semantics: a clean exit
    of ``with conn.transaction()`` COMMITS the block — so we flip the owning
    conn's ``committed`` flag on a clean __exit__, letting tests assert the drain
    watermark actually commits (a bare UPDATE outside a transaction would not)."""

    def __init__(self, conn=None):
        self._conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if self._conn is not None and exc[0] is None:
            self._conn.committed = True
        return False


class _FakeConn:
    """A psycopg-connection stand-in. ``cursor()`` hands back the one
    ``_FakeCursor``; ``transaction()`` is a no-op context manager; ``commit``
    is recorded. Never opens a socket.
    """

    def __init__(self, fetch_script=()):
        self.cur = _FakeCursor(fetch_script)
        self.committed = False
        self.closed = False

    def cursor(self):
        return self.cur

    def transaction(self):
        return _FakeTxn(self)

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


# Event-queue row tuple order the drain SELECT projects (event_id, run_id,
# event_type, payload, created_at) — mirrors mig 051's column set.
def _queue_row(event_id, event_type, created_at, *, run_id="run-1", payload=None):
    return (event_id, run_id, event_type, payload or {}, created_at)


# --------------------------------------------------------------------------
# read_firewalled — the temporal firewall (R2.1, R10.1)
# --------------------------------------------------------------------------


def test_read_firewalled_threads_is_boundary_as_until_filter(monkeypatch):
    """The firewall predicate is ``until = is_boundary`` — the read excludes
    ``event_ts > is_boundary`` (R2.1). Capture the filters handed to
    ``query_trace`` and assert ``until`` carries exactly the boundary.
    """
    import src.skills.walkforward_tune.read as read_mod

    captured = {}

    def _fake_query_trace(filters=None, conn=None):
        captured["filters"] = filters
        captured["conn"] = conn
        return []

    monkeypatch.setattr(read_mod, "query_trace", _fake_query_trace)
    # drain has its own DB path; isolate the firewall assertion from it.
    monkeypatch.setattr(read_mod, "drain_events", lambda conn=None: [])

    conn = _FakeConn()
    read_firewalled(
        {"run_id": "run-1", "code_version": "cv-1"},
        is_boundary="2026-05-30T20:00:00Z",
        conn=conn,
    )

    assert captured["filters"]["until"] == "2026-05-30T20:00:00Z"
    # The correlation-key filters pass through unchanged.
    assert captured["filters"]["run_id"] == "run-1"
    assert captured["filters"]["code_version"] == "cv-1"
    # The live read reuses the SAME connection (no leak to a fresh one).
    assert captured["conn"] is conn


def test_read_firewalled_boundary_overrides_caller_supplied_until(monkeypatch):
    """The firewall edge is ``is_boundary`` — it must win even if a caller
    smuggles an ``until`` into ``keys`` (a wider/future bound that would leak
    OOS rows). ``read_firewalled`` always sets ``until = is_boundary``, never
    the caller's value (R2.1, the firewall invariant).
    """
    import src.skills.walkforward_tune.read as read_mod

    captured = {}

    def _fake_query_trace(filters=None, conn=None):
        captured["filters"] = filters
        return []

    monkeypatch.setattr(read_mod, "query_trace", _fake_query_trace)
    monkeypatch.setattr(read_mod, "drain_events", lambda conn=None: [])

    read_firewalled(
        {"run_id": "run-1", "until": "9999-01-01T00:00:00Z"},  # malicious wide bound
        is_boundary="2026-05-30T20:00:00Z",
        conn=_FakeConn(),
    )

    # The boundary wins; the smuggled wide `until` is discarded.
    assert captured["filters"]["until"] == "2026-05-30T20:00:00Z"


def test_read_firewalled_returns_only_rows_at_or_before_boundary(monkeypatch):
    """End-to-end firewall property: the ``query_trace`` the leaf delegates to
    is bounded by ``until``, so a row with ``event_ts > is_boundary`` cannot
    appear in the returned ``ReadSet.trace_rows``. We model ``query_trace``
    honoring its own ``until`` contract (it filters server-side) and assert no
    OOS row leaks through.
    """
    import src.skills.walkforward_tune.read as read_mod

    boundary = "2026-05-30T20:00:00Z"
    all_rows = [
        {"trace_id": "t1", "event_ts": "2026-05-29T15:00:00Z"},  # in-sample
        {"trace_id": "t2", "event_ts": "2026-05-30T20:00:00Z"},  # at boundary
        {"trace_id": "t3", "event_ts": "2026-05-31T10:00:00Z"},  # OOS — must not leak
    ]

    def _fake_query_trace(filters=None, conn=None):
        until = filters.get("until")
        return [r for r in all_rows if until is None or r["event_ts"] <= until]

    monkeypatch.setattr(read_mod, "query_trace", _fake_query_trace)
    monkeypatch.setattr(read_mod, "drain_events", lambda conn=None: [])

    rs = read_firewalled({"run_id": "run-1"}, is_boundary=boundary, conn=_FakeConn())

    assert isinstance(rs, ReadSet)
    ids = {r["trace_id"] for r in rs.trace_rows}
    assert ids == {"t1", "t2"}
    assert "t3" not in ids  # the OOS row was firewalled out
    assert rs.is_boundary == boundary


def test_read_firewalled_surfaces_drained_events(monkeypatch):
    """The ReadSet carries the drained anomaly events for the fit's behavioral
    analysis (R10.5). ``read_firewalled`` delegates the drain to
    ``drain_events`` and threads the result onto ``ReadSet.drained_events``.
    """
    import src.skills.walkforward_tune.read as read_mod

    ev = Event(
        event_id="e1",
        event_type="safe_mode",
        event_ts="2026-05-30T18:00:00Z",
        payload={"reason": "tripwire"},
    )
    monkeypatch.setattr(read_mod, "query_trace", lambda filters=None, conn=None: [])
    monkeypatch.setattr(read_mod, "drain_events", lambda conn=None: [ev])

    rs = read_firewalled({"run_id": "run-1"}, is_boundary="2026-05-30T20:00:00Z", conn=_FakeConn())

    assert rs.drained_events == [ev]
    assert rs.drained_events[0].event_type == "safe_mode"


def test_read_firewalled_dry_run_touches_no_db(monkeypatch):
    """``conn=None`` is the dry-run path — it opens no connection and issues no
    query (task: "dry-run path touches no DB"). It must NOT call
    ``query_trace`` (whose own ``conn=None`` would open a live connection).
    """
    import src.skills.walkforward_tune.read as read_mod

    def _boom_query_trace(filters=None, conn=None):
        raise AssertionError("dry-run must not call query_trace")

    def _boom_drain(conn=None):
        raise AssertionError("dry-run must not drain")

    monkeypatch.setattr(read_mod, "query_trace", _boom_query_trace)
    monkeypatch.setattr(read_mod, "drain_events", _boom_drain)

    rs = read_firewalled({"run_id": "run-1"}, is_boundary="2026-05-30T20:00:00Z", conn=None)

    assert isinstance(rs, ReadSet)
    assert rs.trace_rows == []
    assert rs.drained_events == []
    assert rs.is_boundary == "2026-05-30T20:00:00Z"


def test_read_firewalled_never_reads_counterfactual_ledger():
    """The read-only boundary: this leaf never reads ``counterfactual_ledger``
    (R10.1 / design §Allowed Dependencies — reactive P&L comes from the
    harness's OutcomeRecords). Guard against a regression that wires the ledger
    into a query: the ledger table must never appear in a SQL ``FROM`` / ``JOIN``
    / ``INTO`` clause. (The docstring may NAME the ledger to document the
    boundary — so we check SQL usage, not any textual mention.)
    """
    import re

    src = importlib.util.find_spec("src.skills.walkforward_tune.read").origin
    with open(src, encoding="utf-8") as fh:
        text = fh.read()
    # No SQL clause may target counterfactual_ledger.
    assert not re.search(
        r"(?is)\b(from|join|into|update)\b\s+counterfactual_ledger", text
    ), "read.py must not query counterfactual_ledger (R10.1)"


# --------------------------------------------------------------------------
# drain_events — SELECT undrained -> process -> mark drained_at (R10.2)
# --------------------------------------------------------------------------


def test_drain_events_selects_only_undrained_and_marks_drained_at():
    """drain SELECTs ``WHERE drained_at IS NULL``, builds Events, then UPDATEs
    ``SET drained_at = NOW()`` for exactly those event_ids (R10.2). Assert the
    SELECT predicate, the returned Events, and that the UPDATE binds the drained
    ids.
    """
    rows = [
        _queue_row("e1", "safe_mode", "2026-05-30T18:00:00Z", payload={"x": 1}),
        _queue_row("e2", "kill_switch", "2026-05-30T19:00:00Z"),
    ]
    conn = _FakeConn(fetch_script=[rows])

    events = drain_events(conn=conn)

    # The SELECT only pulls undrained rows.
    select_sql = conn.cur.executed[0][0]
    assert "drained_at IS NULL" in select_sql

    # Returned Events carry the queue rows (R10.5 — surfaced to the fit).
    assert [e.event_id for e in events] == ["e1", "e2"]
    assert all(isinstance(e, Event) for e in events)
    assert events[0].event_type == "safe_mode"
    assert events[1].event_type == "kill_switch"

    # An UPDATE marking drained_at fired, scoped to the drained ids.
    update_calls = [c for c in conn.cur.executed if "UPDATE" in c[0].upper()]
    assert update_calls, "expected an UPDATE setting drained_at"
    update_sql = update_calls[0][0]
    assert "drained_at" in update_sql
    assert "NOW()" in update_sql.upper() or "now()" in update_sql
    # The set-once watermark must only move NULL -> value (mig 051 guard).
    assert "drained_at IS NULL" in update_sql
    # the drained ids are bound as params (not interpolated) — the ids are
    # passed as a single ANY(%s) array bind, so flatten one level past the
    # per-call params tuple to reach the id list.
    bound_ids: list = []
    for _sql, params in update_calls:
        for p in params or ():
            bound_ids.extend(p if isinstance(p, (list, tuple)) else [p])
    assert "e1" in bound_ids and "e2" in bound_ids


def test_drain_events_is_idempotent_re_drain_returns_nothing():
    """A second drain returns nothing because the rows are now drained (the
    SELECT ``WHERE drained_at IS NULL`` no longer matches them) — the set-once
    watermark makes the drain idempotent (R10.2).
    """
    rows = [_queue_row("e1", "lifecycle", "2026-05-30T18:00:00Z")]
    # First drain sees one row; the (now-drained) second drain SELECT returns
    # the empty set the DB would yield post-watermark.
    conn = _FakeConn(fetch_script=[rows, []])

    first = drain_events(conn=conn)
    second = drain_events(conn=conn)

    assert [e.event_id for e in first] == ["e1"]
    assert second == []


def test_drain_events_commits_the_watermark_in_a_transaction():
    """R10.2 RUNTIME idempotency: the drain ``UPDATE … SET drained_at=NOW()``
    must run inside ``conn.transaction()`` so the watermark COMMITS. On a
    non-autocommit connection (the project's ``_dsn()`` convention) a bare UPDATE
    rolls back at connection close, and the next cycle re-drains the same rows —
    SQL-text idempotency that is defeated at runtime. Mirrors publish.py/audit.py.
    Guards against the transaction boundary being dropped again.
    """
    rows = [_queue_row("e1", "safe_mode", "2026-05-30T18:00:00Z")]
    conn = _FakeConn(fetch_script=[rows])

    events = drain_events(conn=conn)

    assert [e.event_id for e in events] == ["e1"]  # something was drained
    # The watermark UPDATE committed — `conn.transaction()` was entered and exited
    # cleanly. A bare UPDATE (no transaction) would leave this False (RED guard).
    assert conn.committed is True


def test_drain_events_dry_run_touches_no_db():
    """``conn=None`` dry-run: drain opens no connection, issues no SQL, returns
    an empty list (task: "dry-run path touches no DB").
    """
    events = drain_events(conn=None)
    assert events == []


def test_drain_events_empty_queue_returns_empty_no_update():
    """No undrained rows -> no Events and no spurious UPDATE (don't mark a
    watermark when nothing was drained).
    """
    conn = _FakeConn(fetch_script=[[]])
    events = drain_events(conn=conn)
    assert events == []
    update_calls = [c for c in conn.cur.executed if "UPDATE" in c[0].upper()]
    assert not update_calls
