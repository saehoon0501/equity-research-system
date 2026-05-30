"""Command intake + gated apply — the daemon's only supervisory-command seam (task 3.5).

Boundary: commands (Requirements 5, 7, 9). Source of truth:
``.kiro/specs/execution-daemon/design.md`` §"Control — ``commands``"
(lines 298-315) + the command-intake transport flow (lines 218-235) + the
Requirements-Traceability rows 5.4 / 7.2 / 7.4 / 9.2-9.4 (lines 258-269); the
physical transport table is ``db/migrations/052_execution_daemon_state.sql``
(``execution_daemon_command_intake``).

What this module is
-------------------
The **only path** a supervisory command enters the daemon. The out-of-process
commander (``in-session-monitor`` / Operator) INSERTs a gated command row into
``execution_daemon_command_intake``; the daemon is the **sole reader/applier**.
Each cycle :func:`poll_and_apply` drains the un-applied rows, and for each row:

  1. **Validate it targets a gated seam** — one of ``engage_kill_switch`` /
     ``set_safe_mode_grade`` / ``select_validated_config`` (Req 9.2). **Reject
     any other command type** — a row that would directly mutate a position or a
     survival/edge value is never applied (Req 9.3).
  2. **Enforce the toward-safer guard** (Req 7.4 / P7): a ``set_safe_mode_grade``
     may only *tighten* (the requested grade rank ≥ the current grade rank — a
     lower rank is a loosen and is rejected); a ``select_validated_config`` must
     name a version present in the validated registry (and so cannot loosen
     survival — the registry only holds validated configs). A buggy/compromised
     commander therefore cannot loosen — downstream-conservative.
  3. **Apply a valid command** through the injected op-state seam — kill-switch /
     safe-mode as an op-state write (the gate path the loop reads fresh, Req
     5.2/5.3), ``select_validated_config`` by recording the selected version for
     the next atomic hot-swap (handed to ``lifecycle``, Req 9.4).
  4. **Mark the row** ``applied`` (or ``rejected`` + reason) via the set-once
     ``applied_at``/``status``/``reject_reason`` whitelist (migration 052).
  5. **Emit a ``command`` event** (applied or rejected) so the outcome is on the
     append-only record (design.md:231/304).

The deterministic reflex (kill-switch / safe-mode) applies **before and
independently of** any intake (Req 7.3) — that ordering lives in the loop (task
4.4); intake never *gates* the reflex, it only *feeds* op-state.

Phase-1 isolation (BL-3 — no ``src.survival`` import)
-----------------------------------------------------
The real op-state write integrates with ``survival_gate_state`` in **task 4.1**;
the validated-config registry shape is deferred to ``walkforward-tuning-loop``.
Here both are **injected seams**: ``op_state`` (a protocol exposing
``engage_kill_switch`` / ``set_safe_mode_grade`` / ``select_validated_config`` /
``grade_rank``) and ``registry`` (the set of validated version ids). That keeps
this boundary inner-ring testable now against a SYNTHETIC op-state with **no
survival import** (the daemon never imports an unbuilt ``src.survival`` type),
exactly as tasks.md 3.5 mandates. ``conn=None`` is the dry-run seam (the command
event is shaped, not written — the landed ``event_queue.emit_event`` idiom).

Pure-leaf control (P1): stdlib + the daemon-owned types + the landed
``event_queue`` only — no numpy, no MCP, no ``src.survival``, no decision logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Protocol, Sequence

from src.reactive.daemon.event_queue import emit_event
from src.reactive.daemon.types import (
    CommandRow,
    EpochContext,
)

__all__ = [
    "GATED_COMMAND_TYPES",
    "CommandResult",
    "OpStateSeam",
    "IntakeTransport",
    "poll_and_apply",
]

# The ONLY command types the daemon applies (Req 9.2). Mirrors the
# ``CommandType`` Literal (types.py) + the migration-052 ``command_type`` CHECK.
# A row naming anything else is a direct-mutation attempt → rejected (Req 9.3).
GATED_COMMAND_TYPES: frozenset[str] = frozenset(
    {"engage_kill_switch", "set_safe_mode_grade", "select_validated_config"}
)


# --------------------------------------------------------------------------- #
# Injected seams (Phase-1 isolation — the real survival/registry wire in 4.1) #
# --------------------------------------------------------------------------- #


class OpStateSeam(Protocol):
    """The op-state write seam the gated apply goes through.

    The real implementation writes ``survival_gate_state`` through the gate path
    (wired in task 4.1); in Phase-1 inner-ring tests a synthetic mutable state
    satisfies it. The daemon applies through these methods only — it never
    imports ``src.survival`` here (BL-3).
    """

    safe_mode_grade: str

    def grade_rank(self, grade: str) -> int:
        """Integer severity rank of a safe-mode grade (the single ordering
        source — NONE < TIGHTEN < HALT_NEW < FLATTEN). An unknown grade must
        rank toward the most-severe so a degraded value never reads looser."""
        ...

    def engage_kill_switch(self) -> None: ...

    def set_safe_mode_grade(self, grade: str) -> None: ...

    def select_validated_config(self, version_id: str) -> None: ...


class IntakeTransport(Protocol):
    """The command-intake transport seam (``execution_daemon_command_intake``).

    The daemon is the sole reader/applier: it ``poll_pending`` un-applied rows
    and ``mark`` each terminal (the set-once ``applied_at``/``status``/
    ``reject_reason`` whitelist). The real implementation runs SQL against the
    migration-052 table; an inner-ring fake records the marks.
    """

    def poll_pending(self, conn: Any) -> Sequence[CommandRow]: ...

    def mark(
        self,
        conn: Any,
        *,
        command_id: str,
        status: str,
        reject_reason: Optional[str],
    ) -> None: ...


# --------------------------------------------------------------------------- #
# Result record.                                                              #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CommandResult:
    """The outcome of validating + applying a single intake row.

    ``status`` is the terminal the row was marked (``applied`` | ``rejected``);
    ``reject_reason`` is the audit reason on a rejection (``None`` on apply).
    ``event`` is the shaped ``command`` event (the ``event_queue.emit_event``
    dry-run shape under ``conn=None``; the live INSERT row otherwise) the
    orchestrator persists — every processed row emits exactly one.
    """

    command_id: str
    command_type: str
    status: str
    reject_reason: Optional[str]
    event: Optional[dict[str, Any]]


# --------------------------------------------------------------------------- #
# Validation (pure — gated-seam + toward-safer; no I/O, no mutation).          #
# --------------------------------------------------------------------------- #


def _validate(
    row: CommandRow,
    *,
    op_state: OpStateSeam,
    registry: frozenset[str],
) -> Optional[str]:
    """Return a rejection reason, or ``None`` if the command is valid to apply.

    Pure — it mutates nothing; it only decides *whether* the gated apply may run.
    Two gates, in order:

      * **gated-seam** (Req 9.3): the command type must be one of the three
        gated seams; anything else is a direct-mutation attempt → rejected.
      * **toward-safer** (Req 7.4 / P7): ``set_safe_mode_grade`` must not loosen
        (the requested rank must be ≥ the current grade rank — equal is a no-op
        tighten, allowed); ``select_validated_config`` must name a registry
        member (the registry only holds validated configs, so a member cannot
        loosen survival). ``engage_kill_switch`` is unconditionally toward-safer
        (it can only halt new exposure, never loosen).
    """
    command_type = row.command_type
    if command_type not in GATED_COMMAND_TYPES:
        return (
            f"direct-mutation rejected: command_type {command_type!r} is not a "
            f"gated seam (one of {sorted(GATED_COMMAND_TYPES)}); the daemon never "
            f"applies a command that would directly mutate a position/survival/"
            f"edge value (Req 9.3)"
        )

    if command_type == "engage_kill_switch":
        return None  # toward-safer by construction (halts new exposure)

    if command_type == "set_safe_mode_grade":
        grade = row.target.get("grade")
        if grade is None:
            return "set_safe_mode_grade rejected: no 'grade' in target"
        # Toward-safer: a requested grade BELOW the current grade is a loosen.
        # Equal rank is a no-op tighten (allowed). Unknown grade ranks toward the
        # most-severe (grade_rank), so it cannot read as a loosen of a real grade.
        if op_state.grade_rank(grade) < op_state.grade_rank(op_state.safe_mode_grade):
            return (
                f"safe-mode loosen rejected: requested grade {grade!r} (rank "
                f"{op_state.grade_rank(grade)}) is below the current grade "
                f"{op_state.safe_mode_grade!r} (rank "
                f"{op_state.grade_rank(op_state.safe_mode_grade)}); safe-mode may "
                f"only tighten via intake (Req 7.4 / P7)"
            )
        return None

    # command_type == "select_validated_config"
    version_id = row.target.get("version_id")
    if version_id is None:
        return "select_validated_config rejected: no 'version_id' in target"
    if version_id not in registry:
        return (
            f"select_validated_config rejected: version {version_id!r} is not a "
            f"validated-registry member ({sorted(registry)}); a selected config "
            f"must be a registry member and so cannot loosen survival (Req 7.4/9.4)"
        )
    return None


def _apply(
    row: CommandRow,
    *,
    op_state: OpStateSeam,
) -> None:
    """Apply an ALREADY-VALIDATED command through the op-state seam.

    Only ever reached for a command that passed :func:`_validate` — so a rejected
    or un-gated row NEVER reaches the apply seam (Observable 4). Kill-switch /
    safe-mode write op-state (the gate path the loop reads fresh); a validated
    config-select records the version for the next atomic hot-swap (Req 9.4).
    """
    if row.command_type == "engage_kill_switch":
        op_state.engage_kill_switch()
    elif row.command_type == "set_safe_mode_grade":
        op_state.set_safe_mode_grade(row.target["grade"])
    elif row.command_type == "select_validated_config":
        op_state.select_validated_config(row.target["version_id"])


def _emit_command_event(
    *,
    run_id: str,
    row: CommandRow,
    status: str,
    reject_reason: Optional[str],
    conn: Any,
) -> dict[str, Any]:
    """Emit ONE ``command`` event for the processed row (applied or rejected).

    design.md:231/304 — every processed command is emitted to the append-only
    event queue. Returns the shaped event (``conn=None`` dry-run shape, or the
    live INSERT shape) so the caller can carry it on the :class:`CommandResult`.
    """
    shaped = emit_event(
        run_id=run_id,
        event_type="command",
        payload={
            "command_id": row.command_id,
            "command_type": row.command_type,
            "issued_by": row.issued_by,
            "status": status,
            "reject_reason": reject_reason,
            "target": row.target,
        },
        conn=conn,
    )
    return shaped[0]


# --------------------------------------------------------------------------- #
# The batch entry point.                                                       #
# --------------------------------------------------------------------------- #


def poll_and_apply(
    ctx: EpochContext,
    conn: Any,
    *,
    op_state: OpStateSeam,
    intake: IntakeTransport,
    registry: frozenset[str],
) -> list[CommandResult]:
    """Drain the un-applied intake rows; validate + apply + mark + emit each.

    The batch command surface (design.md:308 — "drain un-applied intake rows,
    validate+apply, mark"). For each polled row:

      1. validate (gated seam + toward-safer) — pure, no mutation;
      2. on PASS: apply through ``op_state``, mark ``applied``;
         on FAIL: do **not** apply (op-state untouched — Observable 4), mark
         ``rejected`` + reason;
      3. emit a ``command`` event for the outcome;
      4. collect a :class:`CommandResult`.

    A rejection of one row never blocks another's apply (independent per-row).
    Every polled row ends terminal — none is left pending.

    Args:
        ctx: the pinned epoch — supplies ``run_id`` for the command event (P3).
        conn: the daemon's caller-passed connection (house idiom). ``None`` is
            the dry-run seam (the command event is shaped, not written).
        op_state: the op-state write seam (the real ``survival_gate_state`` path
            wires in task 4.1; an injected synthetic state in Phase-1 tests).
        intake: the command-intake transport (poll un-applied; mark terminal).
        registry: the validated-config version ids a ``select_validated_config``
            may name (the real P2 registry is deferred to walkforward-tuning-loop;
            an injected allow-set here).

    Returns:
        One :class:`CommandResult` per polled row, in poll order.
    """
    results: list[CommandResult] = []

    for row in intake.poll_pending(conn):
        reject_reason = _validate(row, op_state=op_state, registry=registry)

        if reject_reason is None:
            _apply(row, op_state=op_state)
            status = "applied"
        else:
            # NOT applied — op-state stays untouched (Req 9.3 / Observable 4).
            status = "rejected"

        intake.mark(
            conn,
            command_id=row.command_id,
            status=status,
            reject_reason=reject_reason,
        )

        event = _emit_command_event(
            run_id=ctx.run_id,
            row=row,
            status=status,
            reject_reason=reject_reason,
            conn=conn,
        )

        results.append(
            CommandResult(
                command_id=row.command_id,
                command_type=row.command_type,
                status=status,
                reject_reason=reject_reason,
                event=event,
            )
        )

    return results
