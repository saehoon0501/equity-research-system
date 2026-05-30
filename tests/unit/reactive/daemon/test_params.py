"""Inner-ring unit tests for the daemon's per-epoch parameter pin (task 2.1).

Boundary: ``params`` (Requirements 1, 4, 8). Asserts the Observable from
tasks.md 2.1:

  * against synthetic param rows, a fresh epoch mints a ``run_id``, pins a
    param hash + window, and exposes ``PinnedParams.reactive_snapshot``;
  * the pinned value is returned unchanged within a cycle (no mid-cycle
    re-resolution — P2).

The resolver REPEATABLE-READ-resolves ``parameters_active`` over the reactive +
survival namespaces into the daemon-owned ``execution_daemon_epoch`` row
(``epoch_id`` = ``run_id``, ``pinned_param_hash``, ``walk_forward_window``) and
re-sources ``walk_forward_window`` from the P2 registry at hot-swap (v0.1
bootstrap label until the tuner publishes). It writes the **epoch** table, NOT
``run_parameters_snapshot`` (Issue 1 / option b).

No LLM, no MCP, no live DB (P14 inner ring): the param rows are synthetic and
the DB connection is either ``None`` (dry-run) or an injected fake whose query
count we assert to prove there is no mid-cycle re-resolution.
"""

from __future__ import annotations

from typing import Any

import pytest
from psycopg.rows import dict_row

from src.reactive.daemon import params as P
from src.reactive.daemon.types import EpochContext, PinnedParams
from src.reactive.params import DEFAULTS as REACTIVE_DEFAULTS, ParamSnapshot


# --------------------------------------------------------------------------- #
# Synthetic ``parameters_active`` rows.                                        #
# --------------------------------------------------------------------------- #
# Shape mirrors the mig-004 ``parameters_active`` view columns the resolver
# reads: (parameter_key, parameter_namespace, value, version_id). ``value`` is
# the JSONB scalar already decoded to a Python object (psycopg decodes JSONB).
# The complete 7-row survival.* set (what survival.params.resolve consumes).
_SURVIVAL_ROWS: list[dict[str, Any]] = [
    {"parameter_key": "survival.stop_out_level_pct", "parameter_namespace": "survival", "value": 50.0, "version_id": "v-surv-1"},
    {"parameter_key": "survival.safe_mode_buffer_pct", "parameter_namespace": "survival", "value": 100.0, "version_id": "v-surv-2"},
    {"parameter_key": "survival.per_order_size_max", "parameter_namespace": "survival", "value": 1.0, "version_id": "v-surv-3"},
    {"parameter_key": "survival.speculative_sleeve_cap_pct", "parameter_namespace": "survival", "value": 8.0, "version_id": "v-surv-4"},
    {"parameter_key": "survival.flatten_lead_seconds", "parameter_namespace": "survival", "value": 300.0, "version_id": "v-surv-5"},
    {"parameter_key": "survival.assess_max_latency_seconds", "parameter_namespace": "survival", "value": 5.0, "version_id": "v-surv-6"},
    {"parameter_key": "survival.exclusion_enabled", "parameter_namespace": "survival", "value": True, "version_id": "v-surv-7"},
]

# A reactive.* override row (the reactive namespace is NOT seeded in migrations;
# the resolver overlays present rows onto the reactive DEFAULTS).
_REACTIVE_ROWS: list[dict[str, Any]] = [
    {"parameter_key": "reactive.threshold", "parameter_namespace": "reactive", "value": 0.62, "version_id": "v-react-1"},
    {"parameter_key": "reactive.temperature", "parameter_namespace": "reactive", "value": 1.5, "version_id": "v-react-2"},
]


class _FakeConn:
    """A minimal psycopg-shaped fake recording cursor/execute calls.

    Counts how many times ``execute`` is called so a test can prove the resolver
    reads ``parameters_active`` exactly once per epoch (no mid-cycle
    re-resolution, P2) and writes the epoch row.
    """

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.executed: list[str] = []
        # psycopg3 connection-level isolation knob the resolver sets before the
        # snapshot transaction. Starts unset; the resolver assigns REPEATABLE_READ.
        self.isolation_level: Any = None
        self.autocommit: bool = True

    # psycopg3 transaction() context manager seam.
    def transaction(self) -> "_FakeTxn":
        return _FakeTxn(self)

    def cursor(self, *a: Any, **k: Any) -> "_FakeCursor":
        return _FakeCursor(self)

    def execute(self, sql: str, params: Any = None) -> "_FakeCursor":
        cur = _FakeCursor(self)
        cur.execute(sql, params)
        return cur


class _FakeTxn:
    def __init__(self, conn: "_FakeConn") -> None:
        self._conn = conn

    def __enter__(self) -> "_FakeConn":
        return self._conn

    def __exit__(self, *exc: Any) -> bool:
        return False


class _FakeCursor:
    def __init__(self, conn: "_FakeConn") -> None:
        self._conn = conn
        self._last: str = ""

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    def execute(self, sql: str, params: Any = None) -> "_FakeCursor":
        self._conn.executed.append(sql)
        self._last = sql
        return self

    def fetchall(self) -> list[dict[str, Any]]:
        # Only the parameters_active SELECT returns rows.
        if "parameters_active" in self._last:
            return list(self._conn._rows)
        return []

    def fetchone(self) -> Any:
        return None


def _all_rows() -> list[dict[str, Any]]:
    return _SURVIVAL_ROWS + _REACTIVE_ROWS


# The column order of ``_SELECT_PARAMETERS_ACTIVE`` (params.py): the resolved
# tuple-row positional contract a *real* psycopg3 default cursor returns.
_SELECT_COLUMNS = ("parameter_key", "parameter_namespace", "value", "version_id")


def _as_tuple_row(row: dict[str, Any]) -> tuple[Any, ...]:
    """Project a synthetic dict row to the positional tuple a default (no
    ``row_factory``) psycopg3 cursor yields for the parameters_active SELECT."""
    return tuple(row[col] for col in _SELECT_COLUMNS)


class _RealisticConn:
    """A psycopg3-faithful fake: a default cursor yields **tuple** rows, and a
    cursor opened with ``row_factory=dict_row`` yields **dict** rows.

    Unlike ``_FakeConn`` (whose ``fetchall`` always returns dicts and ignores the
    row factory), this fake reproduces the real psycopg3 contract the production
    DB path hits: the daemon's owned connection (``daemon/db.py``) configures no
    connection-level ``dict_row``, so a plain ``conn.cursor()`` returns tuples.
    A resolver that does not request ``row_factory=dict_row`` for the
    parameters_active read therefore feeds tuple rows into ``_rows_to_param_map``
    and raises ``TypeError`` — this fake makes that defect observable.
    """

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.executed: list[str] = []
        self.isolation_level: Any = None
        self.autocommit: bool = True

    def transaction(self) -> "_FakeTxn":
        return _FakeTxn(self)  # type: ignore[arg-type]

    def cursor(self, *a: Any, row_factory: Any = None, **k: Any) -> "_RealisticCursor":
        return _RealisticCursor(self, row_factory=row_factory)


class _RealisticCursor:
    def __init__(self, conn: "_RealisticConn", *, row_factory: Any) -> None:
        self._conn = conn
        self._row_factory = row_factory
        self._last: str = ""

    def __enter__(self) -> "_RealisticCursor":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    def execute(self, sql: str, params: Any = None) -> "_RealisticCursor":
        self._conn.executed.append(sql)
        self._last = sql
        return self

    def fetchall(self) -> list[Any]:
        if "parameters_active" not in self._last:
            return []
        # Default psycopg3 cursor (no row_factory) yields positional tuples;
        # dict_row yields keyed mappings. Reproduce both faithfully.
        if self._row_factory is dict_row:
            return list(self._conn._rows)
        return [_as_tuple_row(r) for r in self._conn._rows]

    def fetchone(self) -> Any:
        return None


# --------------------------------------------------------------------------- #
# Pure helpers (build_pinned_params / hash_param_map).                         #
# --------------------------------------------------------------------------- #


def test_build_pinned_params_exposes_reactive_snapshot() -> None:
    """``build_pinned_params`` yields a ``PinnedParams`` whose
    ``reactive_snapshot`` is the reactive ``ParamSnapshot`` ``decide`` consumes."""
    param_map = {r["parameter_key"]: r["value"] for r in _all_rows()}

    pinned = P.build_pinned_params(
        param_map, code_version="cv@1", param_version="pv@1"
    )

    assert isinstance(pinned, PinnedParams)
    assert isinstance(pinned.reactive_snapshot, ParamSnapshot)
    # Reactive override rows overlay the DEFAULTS.
    assert pinned.reactive_snapshot.threshold == 0.62
    assert pinned.reactive_snapshot.temperature == 1.5
    # An unspecified reactive field falls back to the reactive DEFAULTS.
    assert pinned.reactive_snapshot.weights == REACTIVE_DEFAULTS.weights
    # Versions thread onto the reactive snapshot from the epoch identity.
    assert pinned.reactive_snapshot.code_version == "cv@1"
    assert pinned.reactive_snapshot.param_version == "pv@1"


def test_build_pinned_params_carries_survival_namespace_by_value() -> None:
    """``survival_snapshot`` is the raw ``survival.*`` key->value map survival's
    ``resolve`` consumes (kept a plain mapping; no unbuilt-type import)."""
    param_map = {r["parameter_key"]: r["value"] for r in _all_rows()}

    pinned = P.build_pinned_params(
        param_map, code_version="cv@1", param_version="pv@1"
    )

    # Every survival.* key present and only survival.* keys carried.
    assert pinned.survival_snapshot["survival.stop_out_level_pct"] == 50.0
    assert pinned.survival_snapshot["survival.exclusion_enabled"] is True
    assert all(k.startswith("survival.") or k in ("code_version", "param_version")
               for k in pinned.survival_snapshot)


def test_survival_snapshot_is_consumable_by_survival_resolve() -> None:
    """The carried survival namespace map is consumable by
    ``survival.params.resolve`` by value (the Phase-2 cross-spec contract).

    Imported + torn down inside the test so it does not leave ``src.survival``
    resident in ``sys.modules`` (the daemon ``types`` module deliberately never
    imports survival, BL-3 — a sibling test asserts that isolation, so this
    cross-spec smoke must not pollute the shared session)."""
    import sys

    survival_mods_before = {m for m in sys.modules if m.startswith("src.survival")}
    try:
        from src.survival.params import resolve as survival_resolve

        param_map = {r["parameter_key"]: r["value"] for r in _all_rows()}
        pinned = P.build_pinned_params(
            param_map, code_version="cv@1", param_version="pv@1"
        )
        sp = survival_resolve(pinned.survival_snapshot)
        assert sp.stop_out_level_pct == 50.0
        assert sp.exclusion_enabled is True
        assert sp.code_version == "cv@1"
    finally:
        for m in list(sys.modules):
            if m.startswith("src.survival") and m not in survival_mods_before:
                del sys.modules[m]


def test_hash_is_deterministic_and_order_independent() -> None:
    """``pinned_param_hash`` is a stable sha256 of the canonical param map —
    identical maps hash equal regardless of insertion order; a changed value
    changes the hash."""
    m1 = {r["parameter_key"]: r["value"] for r in _all_rows()}
    m2 = {r["parameter_key"]: r["value"] for r in reversed(_all_rows())}

    assert P.hash_param_map(m1) == P.hash_param_map(m2)

    m3 = dict(m1)
    m3["reactive.threshold"] = 0.99
    assert P.hash_param_map(m3) != P.hash_param_map(m1)


# --------------------------------------------------------------------------- #
# Epoch mint (run_id + hash + window) — dry-run (conn=None).                   #
# --------------------------------------------------------------------------- #


def test_resolve_epoch_dry_run_mints_run_id_pins_hash_and_window() -> None:
    """A fresh epoch (conn=None dry-run) mints a ``run_id``, pins a param hash +
    window, and exposes ``PinnedParams.reactive_snapshot`` (the Observable)."""
    rows = _all_rows()
    epoch = P.resolve_epoch(
        conn=None,
        rows=rows,
        code_version="reactive-signal-model@v0.1",
        param_version="defaults@v0.1",
    )

    assert isinstance(epoch, P.PinnedEpoch)
    assert isinstance(epoch.context, EpochContext)
    # run_id minted (a uuid string) and is the epoch_id carried on the trace.
    assert isinstance(epoch.run_id, str) and len(epoch.run_id) >= 32
    # the reactive snapshot is exposed by value.
    assert isinstance(epoch.pinned_params, PinnedParams)
    assert isinstance(epoch.pinned_params.reactive_snapshot, ParamSnapshot)
    assert epoch.pinned_params.reactive_snapshot.threshold == 0.62
    # a non-empty walk_forward_window (bootstrap label) is pinned.
    assert isinstance(epoch.walk_forward_window, str) and epoch.walk_forward_window


def test_resolve_epoch_mints_distinct_run_id_per_epoch() -> None:
    """Each epoch (daemon start + each hot-swap) mints a distinct ``run_id``."""
    rows = _all_rows()
    e1 = P.resolve_epoch(conn=None, rows=rows, code_version="cv", param_version="pv")
    e2 = P.resolve_epoch(conn=None, rows=rows, code_version="cv", param_version="pv")
    assert e1.run_id != e2.run_id


def test_resolve_epoch_bootstrap_window_when_registry_absent() -> None:
    """v0.1 bootstrap: with no published window, the resolver pins a bootstrap
    label tied to the epoch rather than leaving the window null (Req 4.2)."""
    rows = _all_rows()
    epoch = P.resolve_epoch(conn=None, rows=rows, code_version="cv", param_version="pv")
    # bootstrap label is present and references the epoch / a bootstrap marker.
    assert epoch.walk_forward_window
    assert "bootstrap" in epoch.walk_forward_window.lower()


def test_resolve_epoch_resources_window_at_hot_swap() -> None:
    """At hot-swap the window is re-sourced from the P2 registry: a published
    window overrides the bootstrap label (Req 8.1 atomic swap re-source)."""
    rows = _all_rows()
    epoch = P.resolve_epoch(
        conn=None,
        rows=rows,
        code_version="cv",
        param_version="pv",
        published_window="2026Q2-walkforward",
    )
    assert epoch.walk_forward_window == "2026Q2-walkforward"


# --------------------------------------------------------------------------- #
# Hash + version threading consistency.                                        #
# --------------------------------------------------------------------------- #


def test_epoch_hash_matches_pinned_map() -> None:
    """The epoch's ``pinned_param_hash`` equals the hash of the resolved param
    map (the same canonical hash used downstream for equality)."""
    rows = _all_rows()
    epoch = P.resolve_epoch(conn=None, rows=rows, code_version="cv", param_version="pv")
    expected = P.hash_param_map({r["parameter_key"]: r["value"] for r in rows})
    assert epoch.pinned_param_hash == expected


# --------------------------------------------------------------------------- #
# No mid-cycle re-resolution (P2) — injected fake conn.                        #
# --------------------------------------------------------------------------- #


def test_resolve_epoch_reads_parameters_active_exactly_once() -> None:
    """With an injected fake conn (no ``rows=`` override), the resolver reads
    ``parameters_active`` exactly once per epoch and never re-resolves: a second
    read of the pinned snapshot returns the same object, issuing no new query."""
    fake = _FakeConn(_all_rows())
    epoch = P.resolve_epoch(
        conn=fake, code_version="cv", param_version="pv"
    )

    # exactly one parameters_active SELECT was issued for the epoch resolve.
    active_reads = [s for s in fake.executed if "parameters_active" in s]
    assert len(active_reads) == 1

    # the epoch row was written to execution_daemon_epoch (NOT run_parameters_snapshot).
    epoch_writes = [s for s in fake.executed if "execution_daemon_epoch" in s]
    assert len(epoch_writes) == 1
    assert not any("run_parameters_snapshot" in s for s in fake.executed)

    # re-using the pinned snapshot issues NO further parameters_active read.
    pre = len([s for s in fake.executed if "parameters_active" in s])
    _ = epoch.pinned_params.reactive_snapshot
    _ = epoch.pinned_params.survival_snapshot
    post = len([s for s in fake.executed if "parameters_active" in s])
    assert pre == post  # no mid-cycle re-resolution


def test_resolve_epoch_live_read_handles_default_cursor_tuple_rows() -> None:
    """The live DB read path (``conn=<real cursor>``, no ``rows=`` override) must
    resolve the same param map / hash whether the cursor returns psycopg3 default
    **tuple** rows or ``dict_row`` mappings.

    The daemon's owned connection (``daemon/db.py``) configures no
    connection-level ``dict_row``, so a plain cursor yields tuples. This asserts
    the resolver requests ``row_factory=dict_row`` for the parameters_active read
    so ``_rows_to_param_map`` (which key-subscripts each row) does not crash with
    ``TypeError: tuple indices must be integers``. It FAILS against an impl that
    opens the read cursor without a row factory.
    """
    rows = _all_rows()
    # _RealisticConn yields TUPLE rows for a default cursor (the production shape)
    # and dict rows only when row_factory=dict_row is requested.
    realistic = _RealisticConn(rows)
    epoch = P.resolve_epoch(conn=realistic, code_version="cv", param_version="pv")

    # The map/hash resolved from the live tuple-row cursor must equal the one the
    # dict-row path (synthetic rows=) produces — i.e. the row shape is irrelevant
    # to the pinned result because the read normalizes to dict rows.
    expected_hash = P.hash_param_map(
        {r["parameter_key"]: r["value"] for r in rows}
    )
    assert epoch.pinned_param_hash == expected_hash
    # The pinned snapshot carried the live-read values through correctly.
    assert epoch.pinned_params.reactive_snapshot.threshold == 0.62
    assert epoch.pinned_params.survival_snapshot["survival.stop_out_level_pct"] == 50.0
    # The read cursor was opened with the dict_row factory (proves the fix path).
    assert epoch.pinned_param_hash  # non-empty hash means the read did not crash


def test_resolve_epoch_sets_repeatable_read_isolation() -> None:
    """The epoch resolve runs under REPEATABLE READ (P2 — the whole param map is
    pinned in one snapshot transaction)."""
    from psycopg import IsolationLevel

    fake = _FakeConn(_all_rows())
    P.resolve_epoch(conn=fake, code_version="cv", param_version="pv")
    # The resolver sets the psycopg3 connection-level isolation knob to
    # REPEATABLE READ before the snapshot read (the documented reliable path).
    assert fake.isolation_level == IsolationLevel.REPEATABLE_READ


def test_resolve_epoch_uses_injected_run_id() -> None:
    """A caller-supplied ``run_id`` is honored (so the daemon can thread a
    pre-minted epoch id); otherwise one is minted."""
    rows = _all_rows()
    epoch = P.resolve_epoch(
        conn=None, rows=rows, code_version="cv", param_version="pv",
        run_id="11111111-1111-1111-1111-111111111111",
    )
    assert epoch.run_id == "11111111-1111-1111-1111-111111111111"
