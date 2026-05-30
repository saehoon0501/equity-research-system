"""In-Session Monitor: the writer-side command emitter (leaf) — Phase 1.

The `command_writer` leaf — `submit_command(cmd, conn=None) -> CommandResult` —
plus the two writer-side helpers it composes: `mint_command_id(...)` (the stable
idempotent identity) and `serialize_command(cmd)` (the would-be intake row). It
owns the **writer-side `InterventionCommand` contract** ONLY — the row the monitor
produces — NOT the channel that carries it (design §This Spec Owns; §Out of
Boundary). The daemon-owned inbound channel (`execution_daemon_command_intake`,
mig 052) and the poll-validate-apply-mark wiring are out of boundary.

PHASE 1 ONLY (this task, 3.2). The live intake INSERT, the `applied_at`/`status`/
`reject_reason` confirm-poll, single-flight skip-if-outstanding, and the
reject→escalate-to-halt branch are **task 5.1, BLOCKED** until the daemon
implements mig 052 + the intake poll (design §Migration/Rollout — Phase 2 gates
on the daemon IMPLEMENTING mig 052, a build-order dependency). Until then:

  * `mint_command_id` (design §Owned — InterventionCommand): `command_id =
    uuid5(<stable namespace>, code_version + param_version + walk_forward_window
    + intent_type)`. Hashed over the **stable version-epoch identity + the
    intent** — deliberately NOT the rolling-window edge, NOT the monitor's
    orchestration `run_id`, NOT `requested_at` (all move every tick). So a re-run
    of the SAME logical command mints the SAME id → `ON CONFLICT (command_id) DO
    NOTHING` dedups in Phase 2 (mirrors `decision_process_trace.trace_id`). A
    different intent — or a different version-epoch (a hot-swap) — mints a
    distinct id. The two SELECT-config targets collide by design (the design pins
    the hash to version-epoch+intent and accepts it: the daemon serializes intake
    + applies toward-safer, so a later HALT supersedes an earlier TIGHTEN — the
    worst case is bounded, never a double-mutation). `args` is therefore NOT in
    the hash.

  * `serialize_command` (design §Leaf — command_writer): the writer-side intake
    row the monitor produces — `{command_id, command_type (the daemon SEAM-NAME
    string), args, run_id, issued_by, requested_at}`. `issued_by` is the commander
    identity the daemon validates against its allowlist (Rev 2.1 write-auth).
    `command_type` serializes to its `.value` seam-name string for a clean JSON
    intake row (the daemon-owned `applied_at`/`status`/`reject_reason` markers are
    NOT written by the monitor — they are the daemon's apply-side state).

  * `submit_command` (design §Leaf — command_writer: "Phase 1: returns ADVISORY,
    writes nothing live"): the advisory path. Returns an `ADVISORY`
    `CommandResult` recording the would-be intent and writes NOTHING live. This
    deliberately INVERTS the `audit` leaf's `conn`-present⟹persist switch: here
    mig 052 does not exist, so the advisory path IGNORES `conn` entirely — even a
    supplied connection is never touched (a future-Phase-2 INSERT must not be
    able to fire from Phase 1). The live intake INSERT / confirm-poll /
    single-flight entry API is task 5.1's to design — Phase 1 owns ONLY the
    advisory return; no Phase-2 entry point is pre-committed here.

Pure leaf (P1): stdlib + own-layer `types` only — no LLM, no MCP, no live DB, no
metrics recompute. Dependency direction (design §Allowed Dependencies, strict
left→right) `types → diagnostic → judge → intervene → {audit, command_writer}`:
imports only `types` (own layer) + stdlib — nothing downward, nothing from
`execution-daemon` / `walkforward-tuning-loop`. Phase-1 advisory is a COMPLETE
behavior: no INSERT, no confirm/poll, no single-flight, no reject branch (all
task 5.1).
"""

from __future__ import annotations

import uuid

from src.reactive.monitor.types import (
    CommandResult,
    CommandResultStatus,
    InterventionCommand,
    InterventionIntent,
)

# Stable application-scoped uuid5 namespace for the command-id minting. A FIXED,
# deterministic namespace (NOT a per-process random one) is load-bearing: the id
# must be reproducible across ticks/processes so the SAME logical command dedups
# via `ON CONFLICT (command_id) DO NOTHING` (Phase 2). Derived once, by name, off
# the well-known DNS namespace so it is itself deterministic and documented; it
# never changes (changing it would break idempotent re-issue across a deploy).
_COMMAND_ID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "in-session-monitor.command-intake")

# The advisory note returned in Phase 1 — the channel (mig 052) is not yet landed,
# so the monitor is advisory-only and the operator's manual kill switch is the
# interim backstop (R9.4 / design §Out-of-boundary dependency).
_ADVISORY_REASON = (
    "Phase 1 advisory: the daemon-owned command-intake channel "
    "(execution_daemon_command_intake, mig 052) is not yet implemented; "
    "no command was written live. Operator manual kill switch is the interim "
    "backstop (R9.4)."
)


def mint_command_id(
    *,
    code_version: str,
    param_version: str,
    walk_forward_window: str | None,
    intent: InterventionIntent,
) -> str:
    """Mint the stable, idempotent `command_id` (design §Owned — InterventionCommand).

    `uuid5(_COMMAND_ID_NAMESPACE, code_version|param_version|walk_forward_window|
    intent)` — hashed over the STABLE version-epoch identity PLUS the intent,
    deliberately NOT the rolling-window edge, the orchestration `run_id`, or
    `requested_at` (all move every tick). So the SAME logical command (same
    version-epoch + intent) mints the SAME id across ticks/processes → Phase-2
    `ON CONFLICT (command_id) DO NOTHING` dedups a re-issue; a different intent or
    a different version-epoch (a hot-swap) mints a distinct id.

    The name string joins the four components with a delimiter that cannot appear
    inside a component's identity and disambiguates the None window from an empty
    string, so distinct epochs never alias to the same name. `args` is NOT part of
    the identity (the design pins the hash to version-epoch+intent; the two
    SELECT-config targets collide by design — the daemon applies toward-safer).

    Args:
        code_version, param_version, walk_forward_window: the daemon-epoch
            version keys of the analyzed `(code_version, param_version)` window
            (`walk_forward_window` may be None — a distinct epoch from any string).
        intent: the `InterventionIntent` (its stable `.value` discriminates the
            three actionable intents; NONE never reaches the writer).

    Returns:
        The deterministic uuid5 string (version == 5).
    """
    # `\x1f` (ASCII unit separator) is a non-printable delimiter that cannot occur
    # in a version key or an enum value, so component boundaries are unambiguous.
    # `None` window is rendered distinctly from the empty string so the two epochs
    # never collide.
    window_token = "\x00" if walk_forward_window is None else walk_forward_window
    name = "\x1f".join(
        (code_version, param_version, window_token, intent.value)
    )
    return str(uuid.uuid5(_COMMAND_ID_NAMESPACE, name))


def serialize_command(cmd: InterventionCommand) -> dict:
    """Serialize an `InterventionCommand` to its writer-side intake row dict.

    The row the monitor would INSERT into `execution_daemon_command_intake`:
    `{command_id, command_type (the daemon SEAM-NAME string), args, run_id,
    issued_by, requested_at}` (design §Owned — InterventionCommand / §Leaf —
    command_writer). `command_type` is emitted as its `.value` seam-name string so
    the row is clean JSON (no enum repr). Only the writer-side fields are written;
    the daemon-owned `applied_at`/`status`/`reject_reason` markers are the
    daemon's apply-side state, never set by the monitor.

    Args:
        cmd: the built `InterventionCommand` (its `command_id` was minted by
            `mint_command_id`; `issued_by` is the commander identity the daemon
            validates against its allowlist, Rev 2.1).

    Returns:
        The would-be intake row dict (JSON-clean; values are str/dict only).
    """
    return {
        "command_id": cmd.command_id,
        "command_type": cmd.command_type.value,
        "args": cmd.args,
        "run_id": cmd.run_id,
        "issued_by": cmd.issued_by,
        "requested_at": cmd.requested_at,
    }


def submit_command(cmd: InterventionCommand, conn: object = None) -> CommandResult:
    """Phase-1 advisory submit — records the would-be intent, writes NOTHING live.

    Returns an `ADVISORY` `CommandResult` (design §Leaf — command_writer: "Phase
    1: returns ADVISORY, writes nothing live"). The daemon-owned command-intake
    channel (mig 052) does not exist yet, so this path writes NOTHING — and
    deliberately IGNORES `conn` (it is never touched), inverting the `audit`
    leaf's conn-present⟹persist switch so no future Phase-2 INSERT can fire from
    a Phase-1 caller that happens to pass a connection. The live intake INSERT /
    confirm-poll / single-flight is task 5.1 (BLOCKED on the daemon implementing
    mig 052) — its entry API is that task's to design; Phase 1 adds no Phase-2
    hook here.

    Args:
        cmd: the built `InterventionCommand` to advise on (left unmutated).
        conn: accepted for the pinned signature `submit_command(cmd, conn=None)`
            but UNUSED in Phase 1 — the advisory path never touches it (mig 052
            not landed). Present so the Phase-2 wiring adds no signature break.

    Returns:
        An advisory `CommandResult(status=ADVISORY, command_ref=None, reason=...)`.
    """
    # Phase-1 advisory: NOTHING is written live, `conn` is intentionally not
    # touched (cmd is read-only here), and the result is the unmistakable advisory
    # signal (command_ref None, mirroring the audit's advisory-vs-live signal —
    # design §Leaf — audit).
    del conn  # explicitly unused in Phase 1 (no live write possible yet).
    del cmd  # advisory path reads no field of the command in Phase 1.
    return CommandResult(
        status=CommandResultStatus.ADVISORY,
        command_ref=None,
        reason=_ADVISORY_REASON,
    )


__all__ = [
    "mint_command_id",
    "serialize_command",
    "submit_command",
]
