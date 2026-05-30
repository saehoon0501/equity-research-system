"""In-Session Monitor: the intervention-audit emitter (leaf).

The audit leaf — `emit_audit(audit, conn=None) -> dict` — serializes a built
`InterventionAudit` into its envelope dict and PERSISTS it as the envelope-on-disk
at `memos/envelopes/in-session-monitor__<run_id>.json` via an atomic
tmp-file + `os.replace` write. It owns the **why** only (the triggering diagnostic
+ the falsifiable rationale + the four correlation keys + the advisory-vs-live
`applied` signal); it NEVER writes the model trace or the daemon's command-event
`what` — those join to this audit via the four keys (design §Leaf — audit, R7.4).
Satisfies requirements 7.1 (emit the audit on intervene / declined-on-anomaly),
7.2 (falsifiable + derived figures, P15), 7.3 (tag the four correlation keys),
7.4 (own the audit surface, separate from the model trace).

Two design contracts are load-bearing here:

  * **The four correlation keys (R7.3)** are the daemon `execution_daemon_epoch`
    keys of the single analyzed `(code_version, param_version)` (Issue 1 — one
    version per audit), read off the analyzed trace and carried typed on
    `audit.keys` (`CorrelationKeys`, the landed telemetry contract). They ride
    INSIDE the envelope so the audit joins the model trace + ledger — distinct from
    the monitor's own orchestration run_id, which only NAMES the envelope file
    (Rev 2.1). The signature's `run_id` keyword carries that orchestration run_id;
    it defaults to `audit.keys.run_id` when the orchestrator does not supply a
    separate one (the design surfaces the distinction in prose but pins only the
    `emit_audit(audit, conn=None)` positional shape — the naming run_id is a
    keyword extension, never a new positional).

  * **`conn=None` is a DRY-RUN that writes NOTHING** (design §Leaf — audit:
    "`conn=None` dry-run"; task brief: "conn=None dry-run writes NOTHING"). It
    returns the serialized would-be envelope (so the orchestrator/validator can
    inspect it) but persists no file. A live persist happens ONLY when a connection
    is supplied — the envelope-on-disk pattern needs no DB transaction itself (it
    is a local file), so the presence of `conn` is the deliberate advisory-vs-live
    switch, NOT a connection the file write consumes. This INVERTS the
    `regime_sidecar` "`conn is None` ⟹ open-my-own" convention on purpose: this
    leaf's persistence target is the filesystem, and Phase-1 advisory ticks (the
    dominant v0.1 case) must leave no artifact behind.

`applied` is the unmistakable advisory-vs-live signal (Issue 2): Phase 1 always
`applied=false` + `command_ref=null` ("NO ACTION TAKEN"); Phase 2 sets
`applied=true` + `command_ref` only after the intake row confirms `status=applied`.
This leaf serializes whatever the caller built — it does not flip `applied`; the
Phase split lives in the orchestrator / command_writer.

Pure leaf (P1): stdlib + own-layer `types` only — no LLM, no MCP, no live DB, no
calibration/metrics recompute. Dependency direction (design §Allowed Dependencies,
strict left→right) `types → diagnostic → judge → intervene → {audit,
command_writer}`: imports only `types` (own layer) + stdlib — nothing downward,
nothing from `execution-daemon` / `walkforward-tuning-loop`. Append-only by
convention (one envelope per tick; the orchestration run_id names it).
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from src.reactive.monitor.types import InterventionAudit

# Walk: audit.py → monitor/ → reactive/ → src/ → repo root. The audit envelope
# lands under `<repo>/memos/envelopes/`. Module-level so the inner-ring tests can
# redirect persistence to a tmp dir (monkeypatch `_REPO_ROOT`) and never touch the
# shared repo envelope directory.
_REPO_ROOT = Path(__file__).resolve().parents[3]

# The agent-envelope namespace for this monitor (mirrors the agent-envelope path
# convention `memos/envelopes/<agent>__<run_id>.json`). The `<run_id>` is the
# monitor's orchestration run_id (the file name), NOT the audit's daemon-epoch
# correlation run_id (which rides inside the envelope's keys).
_ENVELOPE_AGENT = "in-session-monitor"


def _serialize(audit: InterventionAudit) -> dict:
    """Serialize an `InterventionAudit` to its JSON envelope dict.

    `dataclasses.asdict` recurses the frozen `CorrelationKeys` into a nested dict
    (`keys -> {run_id, code_version, param_version, walk_forward_window}`) and the
    `trigger_diagnostic` / `rationale` dicts pass through by value. The field set
    is byte-aligned with the design's "Owned — InterventionAudit" table and the
    `intervention_audit_shape` HG validator (the gate is presence-only, P13;
    type-correctness is the `InterventionAudit` dataclass + the golden-envelope
    test, P14). No field is renamed, dropped, or added here.
    """
    return asdict(audit)


def _envelope_path(run_id: str) -> Path:
    """The envelope-on-disk path `memos/envelopes/in-session-monitor__<run_id>.json`.

    `run_id` is the envelope-NAMING run_id (the monitor's orchestration run_id);
    the directory is resolved off the module-level `_REPO_ROOT` seam so tests can
    redirect it.
    """
    return _REPO_ROOT / "memos" / "envelopes" / f"{_ENVELOPE_AGENT}__{run_id}.json"


def _atomic_write_json(path: Path, obj: dict) -> None:
    """Atomically serialize ``obj`` as JSON onto ``path`` (tmp + os.replace).

    Writes to a uniquely-named temp file in the SAME directory, fsyncs it, then
    `os.replace`s it over the target. `os.replace` is atomic on POSIX, so a crash
    mid-write leaves either no file or the complete new file — never a truncated
    one (mirrors `src/shared/agent_harness/orchestrator_step.py::_atomic_write_json`
    + `src/conformal/buffer.py`). The parent dir is created if missing (a fresh
    `memos/envelopes/` on first persist). On any failure the stray *.tmp sibling
    is best-effort unlinked so a failed write never leaves debris.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(obj, indent=2, default=str)
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


def emit_audit(
    audit: InterventionAudit,
    conn: Any = None,
    run_id: str | None = None,
) -> dict:
    """Serialize + (live only) persist the intervention audit envelope (design §Leaf).

    Builds the envelope dict from `audit` (the four correlation keys + the derived
    triggering diagnostic + the falsifiable rationale + the advisory-vs-live
    `applied`/`command_ref` signal) and, when `conn` is supplied, persists it
    atomically at `memos/envelopes/in-session-monitor__<run_id>.json`. The audit
    owns the WHY only — no model-trace write happens here (R7.4).

    Args:
        audit: the already-built `InterventionAudit` (the audit leaf serializes +
            persists; it does NOT decide `applied` — the Phase split is the
            orchestrator's / command_writer's). Its `keys` are the daemon-epoch
            correlation keys (R7.3), carried typed.
        conn: the advisory-vs-live switch (design §Leaf — audit: "`conn=None`
            dry-run"). `None` ⟹ DRY-RUN: serialize + return the would-be envelope,
            write NOTHING. Any non-None value ⟹ live persist the envelope. The
            value is NOT consumed by the file write (the envelope is a local file,
            not a DB row) — its presence is solely the advisory/live signal so the
            dominant Phase-1 advisory ticks leave no artifact.
        run_id: the envelope-NAMING run_id (the monitor's own orchestration
            run_id). Defaults to `audit.keys.run_id` when the orchestrator does not
            supply a separate one. Distinct from the daemon-epoch correlation
            run_id that rides inside `audit.keys` (Rev 2.1) — only the file name
            uses this; the in-envelope keys are unchanged.

    Returns:
        The serialized envelope dict (the persisted-or-would-be envelope), so the
        orchestrator can run the P10 `validate_envelope.sh` seam against it and
        patch-on-RETRY regardless of dry-run vs live.
    """
    envelope = _serialize(audit)

    # DRY-RUN (conn=None): write nothing. The Phase-1 advisory tick — and any
    # pre-persist inspection — leaves no artifact on disk.
    if conn is None:
        return envelope

    naming_run_id = run_id if run_id is not None else audit.keys.run_id
    _atomic_write_json(_envelope_path(naming_run_id), envelope)
    return envelope


__all__ = ["emit_audit"]
