"""Per-epoch parameter pin + ``walk_forward_window`` re-source (task 2.1).

Boundary: ``params`` (Requirements 1, 4, 8).

The daemon's parameter ground-truth resolver. At startup and at each atomic
hot-swap it resolves ``parameters_active`` (the reactive + survival namespaces)
under a single **REPEATABLE READ** snapshot transaction (P2 — pin the whole
versioned param object once; never re-resolve from live state mid-cycle), hashes
the resolved key→value map (sha256 of its canonical JSON, mirroring
``run_parameters_snapshot.effective_parameters_hash``), mints a ``run_id``, and
writes a daemon-owned ``execution_daemon_epoch`` row (``epoch_id`` = ``run_id``,
``pinned_param_hash``, ``walk_forward_window``). It then exposes the pinned
snapshots **by value** as a :class:`~src.reactive.daemon.types.PinnedParams`
carrying ``.reactive_snapshot`` (the reactive ``ParamSnapshot`` ``decide``
consumes, BL-2) alongside the raw survival namespace map (consumable by
``survival.params.resolve`` by value, BL-3 — no unbuilt ``src.survival`` type is
imported here).

It writes the **epoch** table, deliberately **NOT** ``run_parameters_snapshot``
(Issue 1 / option b): the LLM ``/research-company`` run lifecycle
(``run_status`` in_progress/failed) and the P6 orphan reconciler stay
uncontaminated by the daemon's fast-clock epochs.

``walk_forward_window`` is the correlation key the signal model does *not*
provide. It is re-sourced from the P2 param-version registry at each hot-swap —
published there by ``walkforward-tuning-loop`` alongside the promoted version
(its Req 7.3). For v0.1 the tuner has not published yet, so the resolver pins a
**bootstrap label tied to the epoch** until it does (research.md
``walk_forward_window`` provenance).

Test seams (P14 inner ring — no LLM, no MCP, no live DB required):
  * ``conn=None`` is the **dry-run** path (mirrors the telemetry writer): the
    epoch is resolved + hashed + minted but no row is written. Callers may pass
    ``rows=`` synthetic ``parameters_active`` rows to drive a pure resolve.
  * a real (or injected-fake) ``conn`` runs the REPEATABLE READ read of
    ``parameters_active`` **exactly once** per epoch and writes the epoch row;
    the resolved snapshot is then served by value with no further query.

Imports: stdlib + the daemon-owned types + the reactive snapshot shapes only —
no numpy, no MCP, no survival type. ``psycopg`` is used only for the isolation
constant when a live ``conn`` is passed (the resolve/hash logic is pure).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from psycopg import IsolationLevel
from psycopg.rows import dict_row

from src.reactive.daemon.types import EpochContext, PinnedParams
from src.reactive.params import DEFAULTS as _REACTIVE_DEFAULTS, ParamSnapshot
from src.reactive.types import CalibrationEvidence, Weights

__all__ = [
    "PinnedEpoch",
    "build_pinned_params",
    "hash_param_map",
    "resolve_epoch",
    "REACTIVE_NAMESPACE",
    "SURVIVAL_NAMESPACE",
]


@dataclass(frozen=True)
class PinnedEpoch:
    """The ``params``-owned result of an epoch resolve (task 2.1 boundary).

    Bundles the 1.3-owned :class:`EpochContext` (the trace-correlation envelope:
    ``run_id`` / versions / ``walk_forward_window`` / ``pinned_params``) with the
    epoch's ``pinned_param_hash`` — the sha256 written to
    ``execution_daemon_epoch.pinned_param_hash`` and the fast param-equality key
    a hot-swap compares against. The hash lives here (not on the 1.3
    ``EpochContext``) so this task stays inside the ``params`` boundary and does
    not mutate the types module. ``EpochContext`` proxy attributes
    (``run_id`` / ``walk_forward_window`` / ``pinned_params``) are surfaced for
    callers that thread the epoch directly. Frozen — a pinned epoch is immutable;
    a hot-swap mints a new one (whole-object swap, Req 8.1).
    """

    context: EpochContext
    pinned_param_hash: str

    @property
    def run_id(self) -> str:
        return self.context.run_id

    @property
    def code_version(self) -> str:
        return self.context.code_version

    @property
    def param_version(self) -> str:
        return self.context.param_version

    @property
    def walk_forward_window(self) -> str:
        return self.context.walk_forward_window

    @property
    def pinned_params(self) -> PinnedParams:
        return self.context.pinned_params

REACTIVE_NAMESPACE = "reactive"
SURVIVAL_NAMESPACE = "survival"

# The namespaces the daemon pins jointly (P2). reactive feeds ``decide``;
# survival feeds the gate. Both resolve from the same ``parameters`` machinery
# via distinct namespaces (research.md — no separate reactive param table).
_PINNED_NAMESPACES: tuple[str, ...] = (REACTIVE_NAMESPACE, SURVIVAL_NAMESPACE)

# REPEATABLE READ snapshot read of parameters_active over the pinned namespaces.
# DISTINCT ON in the view already collapses to the active row per key; we filter
# to the two pinned namespaces so the daemon never pins unrelated parameters.
_SELECT_PARAMETERS_ACTIVE = """
SELECT parameter_key, parameter_namespace, value, version_id
FROM parameters_active
WHERE parameter_namespace = ANY(%s)
"""

_INSERT_EPOCH = """
INSERT INTO execution_daemon_epoch
    (epoch_id, pinned_param_hash, code_version, param_version,
     walk_forward_window, status)
VALUES (%s, %s, %s, %s, %s, 'open')
"""


# --------------------------------------------------------------------------- #
# Pure helpers (no I/O) — hash + snapshot build.                              #
# --------------------------------------------------------------------------- #


def hash_param_map(param_map: dict[str, Any]) -> str:
    """sha256 of the canonical JSON of the resolved param map (order-independent).

    Mirrors ``run_parameters_snapshot.effective_parameters_hash`` (canonical
    JSON, sorted keys) so two identical pinned maps hash equal regardless of row
    order, and any value change changes the hash. Used as the epoch's
    ``pinned_param_hash`` (the fast equality key downstream).
    """
    canonical = json.dumps(param_map, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _reactive_snapshot_from_map(
    param_map: dict[str, Any], *, code_version: str, param_version: str
) -> ParamSnapshot:
    """Build the reactive ``ParamSnapshot`` from the pinned ``reactive.*`` rows.

    The reactive namespace is **not seeded in migrations** (research.md — no
    separate reactive param table), so present ``reactive.*`` keys overlay the
    reactive ``DEFAULTS`` and absent ones fall back to the default value. The
    epoch's identity (``code_version`` / ``param_version``) threads onto the
    snapshot — these are the two correlation keys the model emits, pinned per
    epoch (P3). ``calibration`` is exposed from the defaults, never computed
    here (R7.4 — the tuner owns it).
    """
    weights = Weights(
        w_trend=float(param_map.get("reactive.w_trend", _REACTIVE_DEFAULTS.weights.w_trend)),
        w_flow=float(param_map.get("reactive.w_flow", _REACTIVE_DEFAULTS.weights.w_flow)),
        w_meanrev=float(param_map.get("reactive.w_meanrev", _REACTIVE_DEFAULTS.weights.w_meanrev)),
    )
    return ParamSnapshot(
        weights=weights,
        temperature=float(param_map.get("reactive.temperature", _REACTIVE_DEFAULTS.temperature)),
        threshold=float(param_map.get("reactive.threshold", _REACTIVE_DEFAULTS.threshold)),
        calibration=CalibrationEvidence(
            brier=param_map.get("reactive.calibration_brier", _REACTIVE_DEFAULTS.calibration.brier),
            reliability=param_map.get(
                "reactive.calibration_reliability", _REACTIVE_DEFAULTS.calibration.reliability
            ),
        ),
        code_version=code_version,
        param_version=param_version,
    )


def _survival_snapshot_from_map(
    param_map: dict[str, Any], *, code_version: str, param_version: str
) -> dict[str, Any]:
    """Carve the raw ``survival.*`` namespace map ``survival.params.resolve``
    consumes — kept a plain mapping (no unbuilt ``src.survival`` type, BL-3).

    Every ``survival.*`` key is carried by value; ``code_version`` /
    ``param_version`` are added as snapshot-level keys (survival reads them
    un-prefixed as run identity, ``survival/params.py:_STR_KEYS``).
    """
    out: dict[str, Any] = {
        k: v for k, v in param_map.items() if k.startswith(SURVIVAL_NAMESPACE + ".")
    }
    out["code_version"] = code_version
    out["param_version"] = param_version
    return out


def build_pinned_params(
    param_map: dict[str, Any], *, code_version: str, param_version: str
) -> PinnedParams:
    """Assemble the by-value :class:`PinnedParams` from the resolved param map.

    Pure: builds the reactive ``ParamSnapshot`` (the 3rd arg ``decide`` consumes)
    + the raw survival namespace map from the pinned key→value map. The whole
    object is later swapped atomically (Req 8.1) — never field-by-field.
    """
    return PinnedParams(
        reactive_snapshot=_reactive_snapshot_from_map(
            param_map, code_version=code_version, param_version=param_version
        ),
        survival_snapshot=_survival_snapshot_from_map(
            param_map, code_version=code_version, param_version=param_version
        ),
    )


# --------------------------------------------------------------------------- #
# walk_forward_window re-source (P2 registry; v0.1 bootstrap).                 #
# --------------------------------------------------------------------------- #


def _resolve_window(
    *, published_window: Optional[str], param_hash: str
) -> str:
    """Re-source ``walk_forward_window`` (Req 4.2 / 8.1).

    At hot-swap the daemon re-sources the window from the P2 param-version
    registry — published there by ``walkforward-tuning-loop`` alongside the
    promoted version (its Req 7.3). For v0.1 the tuner has not published, so a
    bootstrap label tied to the epoch's pinned hash is pinned until it does
    (never a null window — the trace four-key contract requires a value).
    """
    if published_window:
        return published_window
    return f"bootstrap-{param_hash[:12]}"


# --------------------------------------------------------------------------- #
# parameters_active read (REPEATABLE READ) — one snapshot per epoch (P2).      #
# --------------------------------------------------------------------------- #


def _set_repeatable_read(conn: Any) -> None:
    """Set the connection to REPEATABLE READ before the snapshot transaction.

    psycopg3's documented, reliable mechanism is the connection-level
    ``isolation_level`` knob applied **before** a transaction begins (not a
    ``SET TRANSACTION`` statement issued after an implicit ``BEGIN`` — that is
    fragile). The knob takes effect for the next transaction the connection
    opens, which is the ``parameters_active`` read below. A connection that does
    not expose the knob (a minimal injected fake) is left untouched.
    """
    try:
        conn.isolation_level = IsolationLevel.REPEATABLE_READ
    except AttributeError:  # pragma: no cover - minimal fakes without the knob
        pass


def _read_parameters_active(conn: Any) -> list[dict[str, Any]]:
    """REPEATABLE-READ read of ``parameters_active`` over the pinned namespaces.

    One snapshot transaction per epoch (P2): the whole resolved param map is
    pinned in a single REPEATABLE READ read, never re-resolved mid-cycle. The
    isolation level is set on the connection first (``_set_repeatable_read``),
    then the read runs inside a single ``conn.transaction()`` block so the
    snapshot is atomic; returns the resolved rows as **dict rows** (each a
    ``{parameter_key, parameter_namespace, value, version_id}`` mapping).

    The cursor is opened with psycopg3's ``row_factory=dict_row`` so the rows are
    keyed mappings — the daemon's owned connection (``daemon/db.py``) configures
    no connection-level ``dict_row``, so a default cursor would yield tuples that
    ``_rows_to_param_map`` (which subscripts ``row["parameter_key"]`` /
    ``row["value"]``) cannot index. Requesting it per-cursor keeps the shape
    contract local to ``params`` (no dependency on ``db.py``'s connection knobs).
    """
    _set_repeatable_read(conn)
    with conn.transaction():
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(_SELECT_PARAMETERS_ACTIVE, (list(_PINNED_NAMESPACES),))
            return list(cur.fetchall())


def _write_epoch_row(
    conn: Any,
    *,
    run_id: str,
    param_hash: str,
    code_version: str,
    param_version: str,
    walk_forward_window: str,
) -> None:
    """Write the daemon-owned ``execution_daemon_epoch`` row (NOT
    ``run_parameters_snapshot`` — Issue 1 / option b).

    ``epoch_id`` IS the ``run_id`` carried on every trace + event in the epoch
    (P3). One row per pinned-param epoch (daemon start + each hot-swap).
    """
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                _INSERT_EPOCH,
                (
                    run_id,
                    param_hash,
                    code_version,
                    param_version,
                    walk_forward_window,
                ),
            )


def _rows_to_param_map(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Collapse ``parameters_active`` rows to a key→value map (by value)."""
    return {row["parameter_key"]: row["value"] for row in rows}


def resolve_epoch(
    conn: Any,
    *,
    code_version: str,
    param_version: str,
    rows: Optional[Sequence[dict[str, Any]]] = None,
    run_id: Optional[str] = None,
    published_window: Optional[str] = None,
) -> PinnedEpoch:
    """Mint a pinned-param epoch and return its :class:`PinnedEpoch` (P2/P3).

    The single entry point ``params`` exposes. At daemon start and at each atomic
    hot-swap:

      1. Resolve the reactive + survival ``parameters_active`` rows under a
         single REPEATABLE READ snapshot (P2). When ``rows=`` is supplied
         (inner-ring tests / a pre-read snapshot), that pinned set is used
         verbatim and no DB read is issued; otherwise the rows are read from
         ``conn`` exactly once.
      2. Hash the resolved map (``pinned_param_hash``) and build the by-value
         ``PinnedParams`` (``reactive_snapshot`` + the survival namespace map).
      3. Re-source ``walk_forward_window`` from the P2 registry (``published_window``)
         or pin the v0.1 bootstrap label (Req 4.2).
      4. Mint the ``run_id`` (``epoch_id``) — or honor a caller-supplied one —
         and, when ``conn`` is a live connection (not ``None`` dry-run), write
         the ``execution_daemon_epoch`` row.

    Returns the ``EpochContext`` the trace assembler correlates against. The
    pinned snapshot is served **by value** thereafter — no mid-cycle
    re-resolution against live state (P2).

    ``conn=None`` is the dry-run seam (mirrors the telemetry writer): resolve +
    hash + mint, but write no row. Requires ``rows=`` (there is no connection to
    read from).
    """
    if rows is None:
        if conn is None:
            raise ValueError(
                "resolve_epoch(conn=None) is the dry-run seam and requires "
                "rows=<synthetic parameters_active rows>; pass a live conn to "
                "read parameters_active."
            )
        rows = _read_parameters_active(conn)

    param_map = _rows_to_param_map(rows)
    param_hash = hash_param_map(param_map)
    pinned = build_pinned_params(
        param_map, code_version=code_version, param_version=param_version
    )
    walk_forward_window = _resolve_window(
        published_window=published_window, param_hash=param_hash
    )
    epoch_id = run_id if run_id is not None else str(uuid.uuid4())

    if conn is not None:
        _write_epoch_row(
            conn,
            run_id=epoch_id,
            param_hash=param_hash,
            code_version=code_version,
            param_version=param_version,
            walk_forward_window=walk_forward_window,
        )

    context = EpochContext(
        run_id=epoch_id,
        code_version=code_version,
        param_version=param_version,
        walk_forward_window=walk_forward_window,
        pinned_params=pinned,
    )
    return PinnedEpoch(context=context, pinned_param_hash=param_hash)
