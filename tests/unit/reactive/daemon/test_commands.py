"""Inner-ring test for command intake + gated apply (task 3.5).

Boundary: commands (Requirements 5, 7, 9). Asserts the Observable from tasks.md
3.5 + the §"Control — ``commands``" contract (design.md:298-315) + the
command-intake transport flow (design.md:218-235), tested against a **SYNTHETIC
op-state seam** (the real ``survival_gate_state`` write is wired in task 4.1; the
commands boundary must not import ``src.survival`` here — no LLM, no MCP, no live
DB):

  * a **gated** ``engage_kill_switch`` row is applied + marked ``applied`` and the
    synthetic op-state reflects kill-switch engaged (Req 9.2 / 7.1);
  * a **direct-mutation** row (anything outside the three gated seams) is rejected
    with a reason and never mutates op-state (Req 9.3);
  * a **safe-mode-loosen** row (a grade below the current grade) is rejected by the
    toward-safer guard and never mutates op-state (Req 7.4 / P7);
  * an **un-gated / rejected** row never mutates state — the apply seam is not
    called for it (Req 9.3);
  * ``select_validated_config`` for a **non-registry / looser** version is rejected
    (toward-safer registry-member guard); a registry-member selection is recorded
    for the next hot-swap (Req 9.4).

Pure + deterministic against synthetic intake rows + a fake op-state seam + a fake
intake transport (a list of un-applied rows + a recorder of marks); the emit is
the landed ``event_queue.emit_event`` dry-run (``conn=None``).
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Optional

import pytest

import src.reactive.daemon.commands as commands_module
from src.reactive.daemon.commands import poll_and_apply
from src.reactive.daemon.types import CommandRow, EpochContext, PinnedParams
from src.reactive.params import DEFAULTS as _REACTIVE_DEFAULTS


# --------------------------------------------------------------------------- #
# Synthetic op-state seam (the real survival_gate_state write is wired in 4.1) #
# --------------------------------------------------------------------------- #


@dataclass
class _SyntheticOpState:
    """A mutable synthetic operational state the commands apply against.

    Stands in for the survival op-state the real path (task 4.1) writes to
    ``survival_gate_state``. The commands boundary applies through the seam's
    methods only — it never imports ``src.survival`` (Phase-1 isolation, BL-3).
    Grade ordering mirrors survival's ``_GRADE_RANK`` (NONE < TIGHTEN < HALT_NEW
    < FLATTEN) but is restated here so the test takes no survival import either.
    """

    kill_switch_engaged: bool = False
    safe_mode_grade: str = "NONE"
    # selected validated-config version recorded for the next hot-swap (Req 9.4).
    selected_config_version: Optional[str] = None
    # call recorder — proves a rejected/un-gated row never reaches the apply seam.
    apply_calls: list[tuple[str, Any]] = field(default_factory=list)

    _GRADE_RANK = {"NONE": 0, "TIGHTEN": 1, "HALT_NEW": 2, "FLATTEN": 3}

    def grade_rank(self, grade: str) -> int:
        # Unknown grade fails toward the most-severe rank (never reads looser).
        return self._GRADE_RANK.get(grade, self._GRADE_RANK["FLATTEN"])

    # --- the gated apply methods the daemon writes through ------------------ #

    def engage_kill_switch(self) -> None:
        self.apply_calls.append(("engage_kill_switch", True))
        self.kill_switch_engaged = True

    def set_safe_mode_grade(self, grade: str) -> None:
        self.apply_calls.append(("set_safe_mode_grade", grade))
        self.safe_mode_grade = grade

    def select_validated_config(self, version_id: str) -> None:
        self.apply_calls.append(("select_validated_config", version_id))
        self.selected_config_version = version_id


@dataclass
class _FakeIntake:
    """A fake command-intake transport (stands in for the DB table).

    ``rows`` is the pending (un-applied) set the daemon polls; ``marks`` records
    each ``(command_id, status, reject_reason)`` the daemon writes (the set-once
    ``applied_at``/``status``/``reject_reason`` whitelist of migration 052). The
    daemon is the sole applier — it never inserts, only polls + marks.
    """

    rows: list[CommandRow] = field(default_factory=list)
    marks: list[tuple[str, str, Optional[str]]] = field(default_factory=list)

    def poll_pending(self, conn: Any) -> list[CommandRow]:
        return list(self.rows)

    def mark(
        self, conn: Any, *, command_id: str, status: str, reject_reason: Optional[str]
    ) -> None:
        self.marks.append((command_id, status, reject_reason))

    def status_of(self, command_id: str) -> Optional[str]:
        for cid, status, _reason in self.marks:
            if cid == command_id:
                return status
        return None

    def reason_of(self, command_id: str) -> Optional[str]:
        for cid, _status, reason in self.marks:
            if cid == command_id:
                return reason
        return None


def _ctx() -> EpochContext:
    """A minimal synthetic epoch context (only ``run_id`` is load-bearing here —
    the command event carries it)."""
    pinned = PinnedParams(
        reactive_snapshot=_REACTIVE_DEFAULTS,
        survival_snapshot={},
    )
    return EpochContext(
        run_id="33333333-3333-3333-3333-333333333333",
        code_version="code-v0",
        param_version="param-v0",
        walk_forward_window="bootstrap-test",
        pinned_params=pinned,
    )


# The v0.1 validated-config registry seam — the "menu" of versions a
# select_validated_config may name (the real P2 registry is deferred to
# walkforward-tuning-loop; here it is an injected allow-set).
_REGISTRY = frozenset({"cfg-validated-A", "cfg-validated-B"})


def _run(
    rows: list[CommandRow],
    op_state: _SyntheticOpState,
    *,
    intake: Optional[_FakeIntake] = None,
    registry: frozenset[str] = _REGISTRY,
):
    """Drive ``poll_and_apply`` over synthetic rows + the fake seams."""
    intake = intake or _FakeIntake(rows=list(rows))
    results = poll_and_apply(
        _ctx(),
        conn=None,
        op_state=op_state,
        intake=intake,
        registry=registry,
    )
    return results, intake


# --------------------------------------------------------------------------- #
# 1. A gated kill-switch row is applied + marked (Observable 1, Req 9.2/7.1)   #
# --------------------------------------------------------------------------- #


def test_gated_kill_switch_applied_and_marked() -> None:
    """A gated ``engage_kill_switch`` row is applied + marked ``applied``.

    Observable: "a gated kill-switch row is applied and marked". The synthetic
    op-state reflects the kill-switch engaged (the real path writes
    ``survival_gate_state``, wired in 4.1); the intake row is marked ``applied``.
    """
    op = _SyntheticOpState()
    row = CommandRow(
        command_id="cmd-ks-1",
        issued_by="operator",
        command_type="engage_kill_switch",
        target={},
    )
    results, intake = _run([row], op)

    assert op.kill_switch_engaged is True
    assert ("engage_kill_switch", True) in op.apply_calls
    assert intake.status_of("cmd-ks-1") == "applied"
    # exactly one result, applied.
    assert len(results) == 1
    assert results[0].status == "applied"


# --------------------------------------------------------------------------- #
# 2. A direct-mutation row is rejected with a reason (Observable 2, Req 9.3)   #
# --------------------------------------------------------------------------- #


def test_direct_mutation_row_rejected_with_reason() -> None:
    """A row outside the three gated seams is rejected with a reason; no mutation.

    Observable: "a direct-mutation row is rejected with a reason". A command type
    that would directly mutate a position / survival / edge value is never
    applied (Req 9.3) — op-state is untouched and the apply seam is never called.
    """
    op = _SyntheticOpState()
    # Bypass the CommandRow Literal by constructing a row whose command_type is a
    # direct-mutation verb (the kind a buggy/compromised commander might insert).
    row = CommandRow(
        command_id="cmd-mutate-1",
        issued_by="monitor",
        command_type="set_position_volume",  # type: ignore[arg-type]
        target={"position_id": "p1", "volume": 999},
    )
    results, intake = _run([row], op)

    assert intake.status_of("cmd-mutate-1") == "rejected"
    assert intake.reason_of("cmd-mutate-1")  # a non-empty reason
    # no op-state mutation, apply seam never reached.
    assert op.kill_switch_engaged is False
    assert op.safe_mode_grade == "NONE"
    assert op.apply_calls == []
    assert results[0].status == "rejected"


# --------------------------------------------------------------------------- #
# 3. A safe-mode-loosen row is rejected (Observable 3, Req 7.4 / P7)           #
# --------------------------------------------------------------------------- #


def test_safe_mode_loosen_rejected() -> None:
    """A ``set_safe_mode_grade`` that LOOSENS is rejected (toward-safer guard).

    Observable: "a safe-mode-loosen row is rejected". With op-state at HALT_NEW,
    a command to set TIGHTEN (a lower rank) must be rejected and op-state stays
    HALT_NEW — the daemon never loosens via intake (Req 7.4 / P7).
    """
    op = _SyntheticOpState(safe_mode_grade="HALT_NEW")
    row = CommandRow(
        command_id="cmd-loosen-1",
        issued_by="monitor",
        command_type="set_safe_mode_grade",
        target={"grade": "TIGHTEN"},  # rank 1 < current HALT_NEW rank 2
    )
    results, intake = _run([row], op)

    assert intake.status_of("cmd-loosen-1") == "rejected"
    assert intake.reason_of("cmd-loosen-1")
    assert op.safe_mode_grade == "HALT_NEW"  # unchanged — never loosened
    assert op.apply_calls == []
    assert results[0].status == "rejected"


def test_safe_mode_tighten_applied() -> None:
    """A ``set_safe_mode_grade`` that TIGHTENS is applied (toward-safer allows it).

    The complement of the loosen-reject: from NONE to HALT_NEW (a higher rank)
    is a tighten and is applied + marked.
    """
    op = _SyntheticOpState(safe_mode_grade="NONE")
    row = CommandRow(
        command_id="cmd-tighten-1",
        issued_by="operator",
        command_type="set_safe_mode_grade",
        target={"grade": "HALT_NEW"},
    )
    results, intake = _run([row], op)

    assert op.safe_mode_grade == "HALT_NEW"
    assert ("set_safe_mode_grade", "HALT_NEW") in op.apply_calls
    assert intake.status_of("cmd-tighten-1") == "applied"
    assert results[0].status == "applied"


def test_safe_mode_same_grade_is_not_a_loosen() -> None:
    """Re-asserting the SAME grade is not a loosen — it is applied (idempotent).

    Equal rank is not below the current grade, so the toward-safer guard permits
    it (a no-op tighten); op-state stays at the grade.
    """
    op = _SyntheticOpState(safe_mode_grade="TIGHTEN")
    row = CommandRow(
        command_id="cmd-same-1",
        issued_by="operator",
        command_type="set_safe_mode_grade",
        target={"grade": "TIGHTEN"},
    )
    results, intake = _run([row], op)

    assert op.safe_mode_grade == "TIGHTEN"
    assert intake.status_of("cmd-same-1") == "applied"
    assert results[0].status == "applied"


# --------------------------------------------------------------------------- #
# 4. An un-gated / rejected row never mutates state (Observable 4, Req 9.3)    #
# --------------------------------------------------------------------------- #


def test_ungated_row_never_mutates_state() -> None:
    """An un-gated row never mutates state — the apply seam is not reached.

    Observable: "an un-gated row never mutates state". A rejected command leaves
    every op-state field untouched and never calls the apply seam, even when
    other valid rows in the same batch DO mutate.
    """
    op = _SyntheticOpState()
    bad = CommandRow(
        command_id="cmd-bad-1",
        issued_by="monitor",
        command_type="delete_all_positions",  # type: ignore[arg-type]
        target={},
    )
    results, intake = _run([bad], op)

    assert intake.status_of("cmd-bad-1") == "rejected"
    assert op.apply_calls == []  # apply seam never reached
    assert op.kill_switch_engaged is False
    assert op.safe_mode_grade == "NONE"
    assert op.selected_config_version is None


# --------------------------------------------------------------------------- #
# 5. select_validated_config registry-member + toward-safer (Req 9.4 / 7.4)   #
# --------------------------------------------------------------------------- #


def test_select_validated_config_registry_member_applied() -> None:
    """A ``select_validated_config`` naming a registry member is recorded.

    A version present in the validated registry is recorded for the next atomic
    hot-swap (handed to lifecycle, Req 9.4) and the row is marked applied.
    """
    op = _SyntheticOpState()
    row = CommandRow(
        command_id="cmd-cfg-1",
        issued_by="operator",
        command_type="select_validated_config",
        target={"version_id": "cfg-validated-A"},
    )
    results, intake = _run([row], op)

    assert op.selected_config_version == "cfg-validated-A"
    assert ("select_validated_config", "cfg-validated-A") in op.apply_calls
    assert intake.status_of("cmd-cfg-1") == "applied"
    assert results[0].status == "applied"


def test_select_validated_config_non_registry_rejected() -> None:
    """A ``select_validated_config`` naming a NON-registry version is rejected.

    The toward-safer guard requires the selected version be a registry member; an
    unknown version is rejected and never recorded.
    """
    op = _SyntheticOpState()
    row = CommandRow(
        command_id="cmd-cfg-bad-1",
        issued_by="operator",
        command_type="select_validated_config",
        target={"version_id": "cfg-not-validated"},
    )
    results, intake = _run([row], op)

    assert intake.status_of("cmd-cfg-bad-1") == "rejected"
    assert intake.reason_of("cmd-cfg-bad-1")
    assert op.selected_config_version is None
    assert op.apply_calls == []
    assert results[0].status == "rejected"


def test_select_validated_config_missing_version_rejected() -> None:
    """A ``select_validated_config`` with no version_id in the target is rejected.

    A malformed config-select (no version named) cannot resolve to a registry
    member, so it is rejected — never a fail-open mutation.
    """
    op = _SyntheticOpState()
    row = CommandRow(
        command_id="cmd-cfg-empty-1",
        issued_by="operator",
        command_type="select_validated_config",
        target={},
    )
    results, intake = _run([row], op)

    assert intake.status_of("cmd-cfg-empty-1") == "rejected"
    assert op.selected_config_version is None
    assert op.apply_calls == []


# --------------------------------------------------------------------------- #
# 6. Batch semantics + emit + boundary                                        #
# --------------------------------------------------------------------------- #


def test_batch_applies_valid_and_rejects_invalid_independently() -> None:
    """A mixed batch applies the gated rows and rejects the direct-mutation row.

    Drains the whole un-applied set in one poll (batch contract); a rejection of
    one row does not block another's apply, and the valid mutations land.
    """
    op = _SyntheticOpState(safe_mode_grade="NONE")
    rows = [
        CommandRow(
            command_id="b-ks",
            issued_by="operator",
            command_type="engage_kill_switch",
            target={},
        ),
        CommandRow(
            command_id="b-mutate",
            issued_by="monitor",
            command_type="set_position_volume",  # type: ignore[arg-type]
            target={"position_id": "p1"},
        ),
        CommandRow(
            command_id="b-tighten",
            issued_by="operator",
            command_type="set_safe_mode_grade",
            target={"grade": "HALT_NEW"},
        ),
    ]
    results, intake = _run(rows, op)

    assert op.kill_switch_engaged is True
    assert op.safe_mode_grade == "HALT_NEW"
    assert intake.status_of("b-ks") == "applied"
    assert intake.status_of("b-mutate") == "rejected"
    assert intake.status_of("b-tighten") == "applied"
    # every polled row ends terminal — none left pending.
    assert len(intake.marks) == 3
    assert len(results) == 3


def test_emits_a_command_event_per_row() -> None:
    """Each processed row emits a ``command`` event (applied or rejected).

    design.md:304 — "Persist every gate transition + command to append-only
    records"; design.md:231 — "emit command event". The result carries the
    emitted event so the orchestrator persists it; here (``conn=None`` dry-run)
    the event is shaped, not written.
    """
    op = _SyntheticOpState()
    rows = [
        CommandRow(
            command_id="ev-ks",
            issued_by="operator",
            command_type="engage_kill_switch",
            target={},
        ),
        CommandRow(
            command_id="ev-bad",
            issued_by="monitor",
            command_type="bad_verb",  # type: ignore[arg-type]
            target={},
        ),
    ]
    results, _intake = _run(rows, op)

    # Each result carries a command event whose payload names the command + outcome.
    for res in results:
        assert res.event is not None
        assert res.event["event_type"] == "command"
        assert res.event["run_id"] == _ctx().run_id
        assert res.event["payload"]["command_id"] in ("ev-ks", "ev-bad")
        assert res.event["payload"]["status"] in ("applied", "rejected")


def test_poll_and_apply_signature_takes_caller_passed_conn() -> None:
    """``poll_and_apply`` takes the daemon's caller-passed ``conn`` (house idiom).

    The daemon owns its connection (§14.10) and passes it explicitly; the seams
    (op_state / intake / registry) are injected so the boundary is inner-ring
    testable with no survival import + no live DB (Phase-1 isolation).
    """
    sig = inspect.signature(poll_and_apply)
    assert "conn" in sig.parameters


def test_module_takes_no_survival_import() -> None:
    """The commands module imports nothing from ``src.survival`` (Phase-1 BL-3).

    The real op-state write integrates with ``survival_gate_state`` in task 4.1;
    here the boundary stays survival-free so it is inner-ring testable now.
    Asserted against the module's actual import graph (not prose) — the docstring
    legitimately *mentions* ``src.survival`` to explain the isolation.
    """
    import ast

    tree = ast.parse(inspect.getsource(commands_module))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    survival_imports = [m for m in imported if m.startswith("src.survival")]
    assert survival_imports == [], (
        f"commands must take no survival import (Phase-1 BL-3); found "
        f"{survival_imports}"
    )
