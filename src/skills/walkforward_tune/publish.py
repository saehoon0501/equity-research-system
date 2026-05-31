"""The ``publish`` leaf — version handoff into the P2 parameter machinery
(task 3.1).

On a PROMOTE verdict this writes the candidate's validated reactive + survival
values into ``parameters`` rows (so ``parameters_active`` resolves to them) and
stamps the advanced ``walk_forward_window`` label, so the ``execution-daemon``
re-sources the promoted version + the new boundary at its NEXT hot-swap (design
§Leaf — publish; Req 7.1, 7.3, 1.4). It is the §14.1 two-clock meeting point:
the tuner writes the param table; the daemon adopts at hot-swap.

What this leaf is NOT (Req 7.2 / design §Out of Boundary):
  * it NEVER deploys, hot-swaps, or applies a version — that is the daemon's;
  * it writes nothing on a DECLINE verdict (P7 — conservative by default,
    incumbent retained, even if a live ``conn`` is passed);
  * a promoted CODE candidate's deploy mechanics (git-landed diff, code_version
    bump, clean-boundary load, rollback) are an Open Question / a daemon seam —
    this leaf handles the PARAM-config publish only.

Idempotency on ``run_id`` (the cycle's correlation key, P3): each row's
``version_id`` is minted deterministically as ``uuid5(<stable ns>, run_id |
parameter_key)``, so re-running the SAME ``run_id`` mints the SAME ids and the
live INSERT's ``ON CONFLICT (version_id) DO NOTHING`` swallows the re-write — a
publish is exactly-once per (run_id, parameter_key). This mirrors the landed
idempotency convention (``trace_writer`` client-minted ``trace_id`` +
``ON CONFLICT DO NOTHING``; ``command_writer`` ``mint_command_id`` uuid5).

``conn=None`` is the dry-run seam (mirrors ``trace_writer``, NOT the reader's
open-own convention): build + return the shaped rows, open no connection, write
nothing. A live write requires a caller-passed ``conn`` and runs inside one
``conn.transaction()`` so the whole publish is atomic.

Boundary (P1): a pure-shaping + bounded-INSERT leaf. No MCP, no LLM, no leaf
imports another leaf, no consumer-spec import. The reactive key NAMES mirror the
daemon's ``parameters_active`` overlay
(``src/reactive/daemon/params.py::_reactive_snapshot_from_map``) so the rows this
leaf writes are exactly the ones the daemon re-sources.

Requirements: 1.4 (advance the IS boundary, discoverable for the next cycle),
5.7 (paper/challenger track only while paper-phase — encoded in ``approved_by``),
7.1 (write the validated version to the P2 registry), 7.2 (NEVER deploy),
7.3 (the advanced window discoverable to the daemon at hot-swap).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from src.skills.walkforward_tune.types import Candidate, GateVerdict

# Stable application-scoped uuid5 namespace for version-id minting — a FIXED,
# code-pinned constant (mirrors command_writer._COMMAND_ID_NAMESPACE). Re-deriving
# off (run_id, parameter_key) by name mints the same id across processes, so the
# live ON CONFLICT (version_id) DO NOTHING dedups a re-publish of the same cycle.
_VERSION_ID_NAMESPACE = uuid.uuid5(
    uuid.NAMESPACE_DNS, "walkforward-tuning-loop.parameters-publish"
)

# ASCII unit separator — a non-printable delimiter that cannot occur inside a
# run_id (a UUID) or a parameter_key (a dotted identifier), so the (run_id,
# parameter_key) name boundary is unambiguous (mirrors command_writer).
_SEP = "\x1f"

REACTIVE_NAMESPACE = "reactive"
SURVIVAL_NAMESPACE = "survival"
# The IS-boundary label lives in its own namespace so the daemon (or the
# orchestrator that feeds resolve_epoch's published_window) can discover the
# advanced walk_forward_window without colliding with a reactive/survival
# threshold key (the daemon pins only reactive.*/survival.* as thresholds).
WALKFORWARD_NAMESPACE = "walkforward"
_BOUNDARY_KEY = f"{WALKFORWARD_NAMESPACE}.walk_forward_window"

# While the system is paper-only (Req 5.7) every published row is governed as the
# paper/challenger track — it does NOT enable live real-money routing. Encoded in
# the append-only `approved_by` governance column (mirrors the mig-050 seed's
# `launch_default_*` convention).
_PAPER_APPROVED_BY = "walkforward_tune_paper"

# The append-only INSERT. version_id is client-minted (deterministic, the
# idempotency key); effective_at / created_at take their DB defaults (NOW()), so
# the new row wins the parameters_active DISTINCT ON (latest effective_at) race.
# ON CONFLICT (version_id) DO NOTHING + RETURNING makes a re-publish of the same
# (run_id, parameter_key) a silent no-op (mirrors trace_writer).
_INSERT_SQL = """
    INSERT INTO parameters
        (version_id, parameter_key, parameter_namespace, value,
         description, change_rationale, approved_by)
    VALUES
        (%s, %s, %s, %s::jsonb, %s, %s, %s)
    ON CONFLICT (version_id) DO NOTHING
    RETURNING version_id
"""


def mint_version_id(*, run_id: str, parameter_key: str) -> str:
    """Mint the deterministic, idempotent ``version_id`` for one published row.

    ``uuid5(_VERSION_ID_NAMESPACE, run_id | parameter_key)`` — keyed ONLY on the
    cycle's ``run_id`` (P3) and the parameter being set, deliberately NOT on the
    value or any timestamp. So a re-publish of the SAME cycle mints the SAME id
    per key → the live ``ON CONFLICT (version_id) DO NOTHING`` dedups the
    re-write (exactly-once per (run_id, parameter_key)); a different ``run_id``
    (a later cycle) mints a distinct id and lands as a new active row.

    Returns the uuid5 string (version == 5).
    """
    name = _SEP.join((run_id, parameter_key))
    return str(uuid.uuid5(_VERSION_ID_NAMESPACE, name))


def _row(
    *,
    run_id: str,
    parameter_key: str,
    parameter_namespace: str,
    value: Any,
    description: str,
    change_rationale: str,
    approved_by: str,
) -> dict[str, Any]:
    """Shape one append-only ``parameters`` row dict (the mig-004 column set).

    ``version_id`` is the deterministic idempotency key; the namespace-prefix
    invariant (mig-004 ``parameters_namespace_prefix`` CHECK: ``parameter_key
    LIKE parameter_namespace || '.%'``) is asserted here so a mis-keyed row is
    caught at shape time (in the dry-run) rather than only at the live INSERT.
    """
    if not parameter_key.startswith(parameter_namespace + "."):
        raise ValueError(
            f"publish: parameter_key {parameter_key!r} must be prefixed by "
            f"its namespace {parameter_namespace!r} (mig-004 CHECK)"
        )
    return {
        "version_id": mint_version_id(run_id=run_id, parameter_key=parameter_key),
        "parameter_key": parameter_key,
        "parameter_namespace": parameter_namespace,
        "value": value,
        "description": description,
        "change_rationale": change_rationale,
        "approved_by": approved_by,
    }


def _reactive_rows(
    snap: Any, *, run_id: str, selected_config: str | None, approved_by: str
) -> list[dict[str, Any]]:
    """The ``reactive.*`` rows — the exact keys the daemon overlays.

    Mirrors ``src/reactive/daemon/params.py::_reactive_snapshot_from_map`` so the
    rows this leaf writes are byte-for-byte the keys the daemon re-sources at
    hot-swap. ``code_version`` / ``param_version`` are run-identity (threaded by
    the daemon per epoch), NOT tunable threshold rows, so they are not published.
    """
    rationale = (
        f"walkforward-tuning-loop promote (run_id={run_id}, "
        f"selected_config={selected_config}); reactive snapshot tuned after-market "
        "under CPCV out-of-sample discipline (R3.1/R7.1)."
    )
    spec: list[tuple[str, Any, str]] = [
        ("reactive.w_trend", snap.weights.w_trend, "Reactive trend feature weight."),
        ("reactive.w_flow", snap.weights.w_flow, "Reactive flow feature weight."),
        ("reactive.w_meanrev", snap.weights.w_meanrev, "Reactive mean-reversion feature weight."),
        ("reactive.temperature", snap.temperature, "Softmax temperature."),
        ("reactive.threshold", snap.threshold, "Decision (fire) threshold."),
        ("reactive.calibration_brier", snap.calibration.brier, "Exposed Brier (tuner-computed, R7.4)."),
        ("reactive.calibration_reliability", snap.calibration.reliability, "Exposed reliability (tuner-computed)."),
    ]
    return [
        _row(
            run_id=run_id,
            parameter_key=key,
            parameter_namespace=REACTIVE_NAMESPACE,
            value=value,
            description=desc,
            change_rationale=rationale,
            approved_by=approved_by,
        )
        for key, value, desc in spec
    ]


def _survival_rows(
    surv: Any, *, run_id: str, selected_config: str | None, approved_by: str
) -> list[dict[str, Any]]:
    """The ``survival.*`` rows — the 7 thresholds ``survival/params.resolve``
    consumes (mig-050's complete pinned set).

    Accepts the landed ``SurvivalParameters`` frozen dataclass (anchored-memory
    survival tunables) and projects its 7 domain fields. ``code_version`` /
    ``param_version`` are run-identity, not survival-domain thresholds, so they
    are not published (mirrors mig-050's deliberate omission).
    """
    rationale = (
        f"walkforward-tuning-loop promote (run_id={run_id}, "
        f"selected_config={selected_config}); survival snapshot tuned after-market "
        "on anchored all-history memory (R3.2/R7.1); not the runtime tighten-only "
        "guarantee (that is owned downstream, R6.4)."
    )
    spec: list[tuple[str, Any, str]] = [
        ("survival.stop_out_level_pct", surv.stop_out_level_pct, "Venue stop-out / liquidation threshold."),
        ("survival.safe_mode_buffer_pct", surv.safe_mode_buffer_pct, "Safe-mode escalation buffer (> stop-out)."),
        ("survival.per_order_size_max", surv.per_order_size_max, "Per-order volume / exposure cap."),
        ("survival.speculative_sleeve_cap_pct", surv.speculative_sleeve_cap_pct, "Speculative-sleeve funding cap."),
        ("survival.flatten_lead_seconds", surv.flatten_lead_seconds, "Flat-before-close lead time."),
        ("survival.assess_max_latency_seconds", surv.assess_max_latency_seconds, "Standing-monitor assess cadence bound."),
        ("survival.exclusion_enabled", surv.exclusion_enabled, "Ex-ante universe-exclusion toggle."),
    ]
    return [
        _row(
            run_id=run_id,
            parameter_key=key,
            parameter_namespace=SURVIVAL_NAMESPACE,
            value=value,
            description=desc,
            change_rationale=rationale,
            approved_by=approved_by,
        )
        for key, value, desc in spec
    ]


def _boundary_row(
    advanced_window: str, *, run_id: str, approved_by: str
) -> dict[str, Any]:
    """Stamp the advanced ``walk_forward_window`` label into P2 (Req 7.3 / 1.4).

    A single P2 row carrying the advanced boundary value so the daemon re-sources
    it at its next hot-swap (``execution-daemon`` feeds it as
    ``resolve_epoch(published_window=...)``; design §publish). It lives in its own
    ``walkforward.*`` namespace so it never collides with a reactive/survival
    threshold key the daemon pins.
    """
    return _row(
        run_id=run_id,
        parameter_key=_BOUNDARY_KEY,
        parameter_namespace=WALKFORWARD_NAMESPACE,
        value=advanced_window,
        description="Advanced in-sample / walk-forward boundary label; the daemon re-sources it at hot-swap.",
        change_rationale=(
            f"walkforward-tuning-loop advanced the IS boundary on promote "
            f"(run_id={run_id}); discoverable to the daemon at its next hot-swap "
            "(R7.3/R1.4). This loop NEVER deploys/hot-swaps (R7.2)."
        ),
        approved_by=approved_by,
    )


def _persist(conn: Any, rows: list[dict[str, Any]]) -> int:
    """INSERT the shaped rows append-only, atomically — return the count written.

    One ``conn.transaction()`` covers the whole publish (a mid-batch DB error
    rolls every row back; no partial publish). Per row: ``ON CONFLICT
    (version_id) DO NOTHING RETURNING version_id`` — a row counts as written ONLY
    when the INSERT actually wrote (RETURNING yields a row); a re-publish of the
    same ``run_id`` conflicts on the deterministic ``version_id`` and yields no
    row (idempotent). Mirrors ``trace_writer._persist``.
    """
    written = 0
    with conn.transaction():
        with conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    _INSERT_SQL,
                    (
                        r["version_id"],
                        r["parameter_key"],
                        r["parameter_namespace"],
                        json.dumps(r["value"]),
                        r["description"],
                        r["change_rationale"],
                        r["approved_by"],
                    ),
                )
                if cur.fetchone() is not None:
                    written += 1
    return written


def publish(
    verdict: GateVerdict,
    candidate: Candidate,
    *,
    run_id: str,
    advanced_window: str,
    approved_by: str = _PAPER_APPROVED_BY,
    conn: Any = None,
) -> dict[str, Any]:
    """Publish a promoted version into the P2 parameter machinery (task 3.1).

    On ``verdict.promote == True``: shape the ``reactive.*`` + ``survival.*``
    parameter rows from the candidate's validated values (so ``parameters_active``
    resolves to them, Req 7.1) plus a ``walkforward.walk_forward_window`` boundary
    stamp (the advanced IS boundary, discoverable to the daemon at hot-swap,
    Req 7.3 / 1.4). On a DECLINE: write nothing, retain the incumbent (P7) — even
    if a live ``conn`` is passed.

    This loop NEVER deploys, hot-swaps, or applies the version (Req 7.2) — it only
    writes P2 rows the daemon adopts later. Idempotent on ``run_id`` (deterministic
    ``version_id`` + ``ON CONFLICT DO NOTHING``).

    Args:
        verdict: the deterministic ``GateVerdict``. ``promote`` gates the write.
        candidate: the consumed ``Candidate`` whose validated values are published.
            On a promote it must carry a ``param_snapshot`` and/or
            ``survival_parameters`` (a code-only candidate has nothing to publish
            here — that is the daemon's deploy seam).
        run_id: the cycle's correlation key (P3) — the idempotency key.
        advanced_window: the advanced ``walk_forward_window`` label to stamp.
        approved_by: the P2 governance column. Defaults to the paper/challenger
            track (Req 5.7 — paper-only does not enable live routing).
        conn: a psycopg connection. ``None`` ⟹ dry-run: shape + return, NO write,
            NO connection opened (mirrors ``trace_writer``). A live ``conn``
            triggers the atomic, idempotent INSERT.

    Returns:
        ``{"promoted": bool, "param_rows": list[dict], "boundary_row": dict | None,
        "written": int}``. On decline: ``param_rows=[]``, ``boundary_row=None``,
        ``written=0``. On a dry-run promote: the shaped rows, ``written=0``. On a
        live promote: ``written`` = rows actually INSERTed (0 on a re-run of the
        same ``run_id``).

    Raises:
        ValueError: a promote verdict whose candidate carries neither a
            ``param_snapshot`` nor ``survival_parameters`` (nothing to publish).
    """
    if not verdict.promote:
        # P7: a decline retains the incumbent — write NOTHING, even with a live
        # conn (no published version, no boundary advance).
        return {
            "promoted": False,
            "param_rows": [],
            "boundary_row": None,
            "written": 0,
        }

    snap = candidate.param_snapshot
    surv = candidate.survival_parameters
    if snap is None and surv is None:
        raise ValueError(
            "publish: a promote verdict requires a candidate carrying a "
            "param_snapshot and/or survival_parameters; a code-only candidate "
            "has nothing to publish here (its deploy is the daemon's seam, R7.2)."
        )

    rows: list[dict[str, Any]] = []
    if snap is not None:
        rows.extend(
            _reactive_rows(
                snap,
                run_id=run_id,
                selected_config=verdict.selected_config,
                approved_by=approved_by,
            )
        )
    if surv is not None:
        rows.extend(
            _survival_rows(
                surv,
                run_id=run_id,
                selected_config=verdict.selected_config,
                approved_by=approved_by,
            )
        )

    boundary_row = _boundary_row(
        advanced_window, run_id=run_id, approved_by=approved_by
    )
    rows.append(boundary_row)

    written = 0 if conn is None else _persist(conn, rows)

    return {
        "promoted": True,
        "param_rows": rows,
        "boundary_row": boundary_row,
        "written": written,
    }


__all__ = [
    "publish",
    "mint_version_id",
    "REACTIVE_NAMESPACE",
    "SURVIVAL_NAMESPACE",
    "WALKFORWARD_NAMESPACE",
]
