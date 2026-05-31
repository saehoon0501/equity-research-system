"""The ``audit`` leaf — tuner-action-audit assembly + append-only write (task 3.2).

Emitted on **both** promote and decline (R8.1): every tuning cycle records WHY
the loop promoted (or declined to promote) a candidate. ``write_audit`` does two
things, in this order:

  1. **Persist the envelope-on-disk** at
     ``memos/envelopes/walkforward-tune__<run_id>.json`` (P4) — UNCONDITIONALLY,
     even in the dry-run. This INVERTS the publish/monitor convention (where
     ``conn=None`` writes nothing): here the local-file envelope is the P4
     cross-stage artifact the orchestrator + the HG validator (task 3.3) read,
     so it must exist regardless of whether the DB row was written.
  2. **Append the DB row** to ``walkforward_tuner_audit`` (mig 053) — ONLY when a
     live ``conn`` is supplied. ``conn=None`` is the dry-run seam: the envelope
     file is written, but NO DB row (task 3.2 observable: "dry-run writes the
     envelope but no DB row").

THE ENVELOPE SHAPE (the contract task 3.3's ``validate_tuner_action_audit``
enforces). The envelope is the ``TunerActionAudit`` field set (which itself
mirrors the mig-053 columns minus the DB-default ``created_at``), flattened to a
flat JSON dict:

    {
      "audit_id":            str (uuid5),       # client-minted idempotency key
      "run_id":              str,               # correlation key 1 (P3)
      "code_version":        str,               # correlation key 2
      "param_version":       str,               # correlation key 3
      "walk_forward_window": str | null,        # correlation key 4 (null on decline)
      "promoted":            bool,              # the verdict
      "track":               "param"|"code"|"both",
      "gate_metrics": {                          # DERIVED, not asserted (P15, R8.2)
        "dsr": float, "psr": float, "min_trl_met": bool,
        "pbo": float, "effective_n": int, "lexicographic_ok": bool
      },
      "hypothesis": {                            # FALSIFIABLE (P15, R8.2)
        "statement":  str,                       # the falsifiable promotion rationale
        "falsifiers": [str, ...]                 # >=1 observable falsifier
      }
    }

The four correlation keys are flattened so the envelope joins
``decision_process_trace`` (mig 048) + ``counterfactual_ledger`` (R8.3). The
``hypothesis`` sub-shape is STRUCTURED (statement + falsifiers list, not a bare
string) precisely so task 3.3 can validate the hypothesis and the falsifiers
SEPARATELY (its observable rejects "the hypothesis / the falsifiers"
independently). ``gate_metrics`` is DERIVED by ``gate_metrics_from_verdict`` — a
pure projection of the ``GateVerdict`` (P15: derived, never an asserted
probability).

Idempotency on the cycle (R9.1): ``audit_id`` is minted deterministically as
``uuid5(<stable ns>, run_id)`` — one row per cycle — so a crash/resume that
re-fires the SAME ``run_id`` mints the SAME ``audit_id`` and the live INSERT's
``ON CONFLICT (audit_id) DO NOTHING`` swallows the re-write (the migration
assigns this idempotency contract to this writer: "the writer supplies the UUID
so its ON CONFLICT (audit_id) DO NOTHING is an idempotency key on crash/resume").

Boundary (P1): a pure-assembly + bounded-INSERT + local-file leaf. No MCP, no
LLM, no leaf imports another leaf, no consumer-spec import — it imports only the
owned ``types`` (``TunerActionAudit`` / ``GateVerdict``) + stdlib. It RECORDS the
verdict; it never acts on it (no deploy / apply / hot-swap — that is the daemon's,
and the publish leaf's, seam).

Requirements: 8.1 (emit on both promote and decline), 8.2 (falsifiable hypothesis
+ derived metrics, P15), 8.3 (tag the four correlation keys for joinability).
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from src.skills.walkforward_tune.types import GateVerdict, TunerActionAudit

# Walk: audit.py -> walkforward_tune/ -> skills/ -> src/ -> repo root. The audit
# envelope lands under ``<repo>/memos/envelopes/``. Module-level so the inner-ring
# tests can redirect persistence to a tmp dir (monkeypatch ``_REPO_ROOT``) and
# never touch the shared repo envelope directory (the file write is UNCONDITIONAL
# here — even dry-run — so the redirect is mandatory in tests).
_REPO_ROOT = Path(__file__).resolve().parents[3]

# The agent-envelope namespace for this loop (the P4 convention
# ``memos/envelopes/<agent>__<run_id>.json``). The ``<run_id>`` names the file
# AND is one of the four in-envelope correlation keys.
_ENVELOPE_AGENT = "walkforward-tune"

# Stable application-scoped uuid5 namespace for audit-id minting — a FIXED,
# code-pinned constant (mirrors ``publish._VERSION_ID_NAMESPACE`` /
# ``command_writer._COMMAND_ID_NAMESPACE``). Re-deriving off ``run_id`` by name
# mints the same id across processes, so a crash/resume re-fire of the same cycle
# collides on the live ``ON CONFLICT (audit_id) DO NOTHING`` (exactly-once per
# cycle / per ``run_id``).
_AUDIT_ID_NAMESPACE = uuid.uuid5(
    uuid.NAMESPACE_DNS, "walkforward-tuning-loop.tuner-action-audit"
)

# The six DERIVED gate figures the audit records (P15 — derived, not asserted).
# Pinned here as the single source of truth for the ``gate_metrics`` sub-shape
# (mig-053's ``gate_metrics`` JSONB column + task 3.3's HG check both key on
# exactly these).
_GATE_METRIC_KEYS = (
    "dsr",
    "psr",
    "min_trl_met",
    "pbo",
    "effective_n",
    "lexicographic_ok",
)

# The append-only INSERT. audit_id is client-minted (deterministic, the
# idempotency key); created_at takes its DB default (NOW()). ON CONFLICT
# (audit_id) DO NOTHING + RETURNING makes a crash/resume re-write a silent no-op
# (mirrors trace_writer / publish).
_INSERT_SQL = """
    INSERT INTO walkforward_tuner_audit
        (audit_id, run_id, code_version, param_version, walk_forward_window,
         promoted, track, gate_metrics, hypothesis)
    VALUES
        (%s, %s, %s, %s, %s,
         %s, %s, %s::jsonb, %s::jsonb)
    ON CONFLICT (audit_id) DO NOTHING
    RETURNING audit_id
"""


def mint_audit_id(*, run_id: str) -> str:
    """Mint the deterministic, idempotent ``audit_id`` for one cycle's audit row.

    ``uuid5(_AUDIT_ID_NAMESPACE, run_id)`` — keyed ONLY on the cycle's ``run_id``
    (P3): one audit row per cycle. A crash/resume re-fire of the SAME ``run_id``
    mints the SAME id, so the live ``ON CONFLICT (audit_id) DO NOTHING`` dedups
    the re-write (exactly-once per cycle, R9.1); a different ``run_id`` (a later
    cycle) mints a distinct id and lands as a new row.

    Returns the uuid5 string (version == 5).
    """
    return str(uuid.uuid5(_AUDIT_ID_NAMESPACE, run_id))


def gate_metrics_from_verdict(verdict: GateVerdict) -> dict[str, Any]:
    """Project a ``GateVerdict`` into the DERIVED ``gate_metrics`` dict (P15).

    The metrics are DERIVED — a pure projection of the gate's output, never
    asserted figures (R8.2 / P15). Returns exactly the six pinned keys
    (``dsr, psr, min_trl_met, pbo, effective_n, lexicographic_ok``) so the
    audit's ``gate_metrics`` is provably the gate's own numbers. The orchestrator
    uses this to build the ``TunerActionAudit.gate_metrics`` so there is one
    source of truth for the sub-shape mig 053 + task 3.3 both key on
    (``_GATE_METRIC_KEYS``): every key projects the verdict field of the same
    name, so the metrics are provably the gate's own numbers and the six-key set
    cannot silently drift from the verdict.
    """
    return {key: getattr(verdict, key) for key in _GATE_METRIC_KEYS}


def _json_default(o: Any) -> Any:
    """JSONB / envelope-file serializer for derived metrics that may be numpy
    scalars (the gate can compute with numpy).

    Duck-typed ``.item()`` coercion to a NATIVE python scalar (mirrors
    ``trace_writer._trace_json_default``), deliberately NOT ``default=str`` — a
    derived metric must stay numeric, never be stringified (that would corrupt
    the number a downstream consumer / the HG validator reads). This leaf takes
    NO hard numpy import (the pure-unit suite runs without numpy); anything else
    falls through to ``str`` only as a last resort for an exotic type.
    """
    item = getattr(o, "item", None)
    if callable(item):
        return item()  # numpy scalar -> native python scalar
    return str(o)


def _serialize(audit: TunerActionAudit) -> dict[str, Any]:
    """Serialize a ``TunerActionAudit`` to its flat envelope dict (THE SHAPE).

    ``dataclasses.asdict`` flattens the frozen dataclass to the field set, which
    is byte-aligned with the mig-053 columns (minus the DB-default ``created_at``)
    AND with the task-3.3 HG validator's contract: the four correlation keys at
    the top level (R8.3), the DERIVED ``gate_metrics`` dict (P15), and the
    STRUCTURED ``hypothesis`` (statement + falsifiers). No field is renamed,
    dropped, or added here — the type IS the contract.
    """
    return asdict(audit)


def _envelope_path(run_id: str) -> Path:
    """The envelope-on-disk path ``memos/envelopes/walkforward-tune__<run_id>.json``
    (P4). Resolved off the module-level ``_REPO_ROOT`` seam so tests can redirect
    it to a tmp dir."""
    return _REPO_ROOT / "memos" / "envelopes" / f"{_ENVELOPE_AGENT}__{run_id}.json"


def _atomic_write_json(path: Path, obj: dict[str, Any]) -> None:
    """Atomically serialize ``obj`` as JSON onto ``path`` (tmp + os.replace).

    Writes to a uniquely-named temp file in the SAME directory, fsyncs it, then
    ``os.replace``s it over the target — atomic on POSIX, so a crash mid-write
    leaves either no file or the complete new file, never a truncated one
    (mirrors ``reactive/monitor/audit.py`` +
    ``shared/agent_harness/orchestrator_step.py``). The parent dir is created if
    missing (a fresh ``memos/envelopes/`` on first persist). On any failure the
    stray *.tmp sibling is best-effort unlinked.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(obj, indent=2, default=_json_default)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def _persist(conn: Any, audit: TunerActionAudit) -> int:
    """INSERT the audit row append-only, atomically — return the count written.

    One ``conn.transaction()`` covers the single-row write. ``ON CONFLICT
    (audit_id) DO NOTHING RETURNING audit_id`` — the row counts as written ONLY
    when the INSERT actually wrote (RETURNING yields a row); a crash/resume
    re-fire of the same ``run_id`` conflicts on the deterministic ``audit_id``
    and yields no row (idempotent, R9.1). ``gate_metrics`` / ``hypothesis`` are
    serialized to JSONB with the numeric-preserving default. Mirrors
    ``trace_writer._persist`` / ``publish._persist``.
    """
    written = 0
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                _INSERT_SQL,
                (
                    audit.audit_id,
                    audit.run_id,
                    audit.code_version,
                    audit.param_version,
                    audit.walk_forward_window,
                    audit.promoted,
                    audit.track,
                    json.dumps(audit.gate_metrics, default=_json_default),
                    json.dumps(audit.hypothesis, default=_json_default),
                ),
            )
            if cur.fetchone() is not None:
                written = 1
    return written


def write_audit(audit: TunerActionAudit, conn: Any = None) -> dict[str, Any]:
    """Assemble + persist the tuner-action audit (task 3.2). Emitted on BOTH
    promote and decline (R8.1).

    Always persists the envelope-on-disk at
    ``memos/envelopes/walkforward-tune__<run_id>.json`` (P4 — UNCONDITIONAL, even
    dry-run). Appends the ``walkforward_tuner_audit`` (mig 053) row ONLY when a
    live ``conn`` is supplied (``conn=None`` ⟹ dry-run: envelope written, NO DB
    row — task 3.2 observable). Append-only + idempotent on the cycle's ``run_id``
    via the deterministic ``audit_id`` (R9.1).

    Args:
        audit: the already-built ``TunerActionAudit`` frozen dataclass. Carries
            the four correlation keys (R8.3), the DERIVED ``gate_metrics`` (build
            it with :func:`gate_metrics_from_verdict`, P15), and the FALSIFIABLE
            ``hypothesis`` (a structured ``{statement, falsifiers}``, P15). Its
            ``audit_id`` should be minted with :func:`mint_audit_id` so the
            idempotency key holds on resume. The same shape is emitted whether
            ``promoted`` is True or False (R8.1).
        conn: a psycopg connection. ``None`` ⟹ dry-run: write the envelope file,
            but NO DB row (``written == 0``). A live ``conn`` triggers the atomic,
            idempotent INSERT (``written == 1``, or ``0`` on a resume re-fire).

    Returns:
        The serialized envelope dict, augmented with an OPERATIONAL ``"written":
        int`` (0 on dry-run / resume no-op, 1 on a fresh live write). NOTE: the
        artifact task 3.3's ``validate_tuner_action_audit`` validates is the
        ON-DISK envelope file (the 9-field shape hooks find by ``run_id``);
        ``written`` is NOT part of that validated contract — it is here only for
        the orchestrator's post-write inspection (write-confirmation /
        idempotency signal). The on-disk file and this return share the 9 audit
        fields exactly; they differ only by this operational ``written``.
    """
    envelope = _serialize(audit)

    # P4: the envelope-on-disk is written UNCONDITIONALLY (even in the dry-run) —
    # it is the cross-stage artifact the orchestrator + the HG validator read.
    _atomic_write_json(_envelope_path(audit.run_id), envelope)

    # The DB row is gated on a live conn: conn=None is the dry-run (no DB row).
    written = 0 if conn is None else _persist(conn, audit)

    return {**envelope, "written": written}


__all__ = [
    "write_audit",
    "mint_audit_id",
    "gate_metrics_from_verdict",
]
