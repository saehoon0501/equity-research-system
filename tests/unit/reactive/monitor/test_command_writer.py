"""Pure-unit tests for the In-Session Monitor command writer (leaf) — Phase 1.

Task 3.2 (in-session-monitor). Asserts the design's "Leaf — command_writer"
contract (`submit_command(cmd, conn=None) -> CommandResult`) and the "Owned
(writer-side only) — InterventionCommand" data model, for PHASE 1 ONLY:

  (a) `command_id` minting — a stable `uuid5` over the version-epoch keys
      (`code_version`, `param_version`, `walk_forward_window`) PLUS the
      `intent_type`, deliberately NOT the rolling-window edge / `run_id` /
      `requested_at` (which move every tick). So the SAME logical command mints
      the SAME id across ticks (idempotent re-issue → `ON CONFLICT (command_id)
      DO NOTHING` dedups, Phase 2), while a DIFFERENT intent mints a DIFFERENT id.
  (b) `InterventionCommand` serialization incl. `issued_by` (the commander
      identity the daemon validates against its allowlist, Rev 2.1) and the
      string `command_type` (the daemon seam name) for a clean would-be intake row.
  (c) the Phase-1 advisory path — `submit_command` returns an `ADVISORY`
      `CommandResult` and writes NOTHING live (mig 052 / the daemon-owned
      `execution_daemon_command_intake` table does not exist yet), EVEN WHEN a
      `conn` is supplied. This deliberately differs from a live-INSERT path; the
      live intake INSERT / confirm-poll / single-flight is task 5.1 (blocked).

Two behaviors are load-bearing and asserted here (per the advisor + the design):
  * STABILITY (a): vary `run_id` AND `requested_at` (the per-tick movers) while
    holding `(code_version, param_version, walk_forward_window, intent)` constant
    → the SAME `command_id`. A test holding everything constant would not prove
    the EXCLUSION of `run_id` — varying it does. Different intent → different id.
  * NO LIVE WRITE (c): `submit_command(cmd, conn=<poison-spy>)` returns ADVISORY
    AND never touches the connection. `status == ADVISORY` alone does NOT prove
    no write — the poison spy (raises on ANY attribute access) does.

Pure leaf (P1): stdlib + own-layer `types` only — no LLM, no MCP, no live DB. The
advisory path is a complete Phase-1 behavior: no INSERT, no confirm/poll, no
single-flight, no reject branch (all task 5.1, blocked).

Requirements: 4.1 (command via existing mechanisms only — the writer-side row),
6.2 (fail-safe is Phase 2; Phase 1 is advisory-only, no fire-and-forget because
nothing is fired), 9.4 (defined channel; until it lands the monitor is advisory
and the operator's manual kill switch is the interim backstop).
"""

from __future__ import annotations

import uuid

from src.reactive.monitor.command_writer import (
    mint_command_id,
    serialize_command,
    submit_command,
)
from src.reactive.monitor.types import (
    CommandResult,
    CommandResultStatus,
    CommandType,
    InterventionCommand,
    InterventionIntent,
)


# --- Fixtures --------------------------------------------------------------


def _command(
    *,
    code_version: str = "c7",
    param_version: str = "p3",
    walk_forward_window: str | None = "2026Q1",
    intent: InterventionIntent = InterventionIntent.HALT_NEW_ENTRIES,
    command_type: CommandType = CommandType.ENGAGE_KILL_SWITCH,
    args: dict | None = None,
    run_id: str = "orch-run-1",
    issued_by: str = "in-session-monitor",
    requested_at: str = "2026-05-30T14:05:00Z",
) -> InterventionCommand:
    """A built `InterventionCommand` (writer-side intake row). `command_id` is
    minted from the version-epoch keys + the intent so the fixture's id is
    consistent with the minting contract under test."""
    return InterventionCommand(
        command_id=mint_command_id(
            code_version=code_version,
            param_version=param_version,
            walk_forward_window=walk_forward_window,
            intent=intent,
        ),
        command_type=command_type,
        args=args if args is not None else {},
        run_id=run_id,
        issued_by=issued_by,
        requested_at=requested_at,
    )


class _PoisonConn:
    """A spy connection that raises on ANY attribute access.

    Phase 1 must write NOTHING live even when a `conn` is supplied (mig 052 does
    not exist) — so `submit_command` must never call `.cursor()` / `.execute()` /
    `.commit()` / anything on it. Touching it at all blows up the test, proving
    no live write (a positive guarantee `status == ADVISORY` cannot give)."""

    def __getattr__(self, name: str) -> object:  # pragma: no cover - defensive
        raise AssertionError(
            f"Phase 1 advisory path touched the connection (.{name}) — it must "
            f"write NOTHING live (mig 052 not implemented)."
        )


# --- (a) command_id minting: stable identity, not the rolling edge ----------


def test_command_id_stable_across_ticks_for_same_version_keys_and_intent() -> None:
    # The two "ticks" vary run_id AND requested_at (the per-tick movers) while the
    # version-epoch keys + intent are held — the id MUST be identical. This proves
    # the EXCLUSION of run_id/requested_at from the hash (the design's pin).
    tick1 = mint_command_id(
        code_version="c7",
        param_version="p3",
        walk_forward_window="2026Q1",
        intent=InterventionIntent.HALT_NEW_ENTRIES,
    )
    tick2 = mint_command_id(
        code_version="c7",
        param_version="p3",
        walk_forward_window="2026Q1",
        intent=InterventionIntent.HALT_NEW_ENTRIES,
    )
    assert tick1 == tick2


def test_command_id_excludes_run_id_and_requested_at_via_built_command() -> None:
    # End-to-end through the built command: two commands with DIFFERENT run_id and
    # DIFFERENT requested_at but the SAME version-epoch + intent share command_id.
    cmd_a = _command(run_id="orch-run-1", requested_at="2026-05-30T14:05:00Z")
    cmd_b = _command(run_id="orch-run-9", requested_at="2026-05-30T15:59:00Z")
    assert cmd_a.run_id != cmd_b.run_id
    assert cmd_a.requested_at != cmd_b.requested_at
    assert cmd_a.command_id == cmd_b.command_id


def test_command_id_differs_across_intents() -> None:
    # Same version-epoch, DIFFERENT intent → DIFFERENT id (the three actionable
    # intents do not collide).
    halt = mint_command_id(
        code_version="c7",
        param_version="p3",
        walk_forward_window="2026Q1",
        intent=InterventionIntent.HALT_NEW_ENTRIES,
    )
    tighten = mint_command_id(
        code_version="c7",
        param_version="p3",
        walk_forward_window="2026Q1",
        intent=InterventionIntent.TIGHTEN_SAFE_MODE,
    )
    select = mint_command_id(
        code_version="c7",
        param_version="p3",
        walk_forward_window="2026Q1",
        intent=InterventionIntent.SELECT_SAFER_CONFIG,
    )
    assert len({halt, tighten, select}) == 3


def test_command_id_differs_across_version_epochs() -> None:
    # A hot-swap (different version-epoch) under the SAME intent mints a DISTINCT
    # id — the id is the per-version logical-command identity.
    v1 = mint_command_id(
        code_version="c7",
        param_version="p3",
        walk_forward_window="2026Q1",
        intent=InterventionIntent.HALT_NEW_ENTRIES,
    )
    v2 = mint_command_id(
        code_version="c8",
        param_version="p3",
        walk_forward_window="2026Q1",
        intent=InterventionIntent.HALT_NEW_ENTRIES,
    )
    assert v1 != v2


def test_command_id_distinguishes_null_vs_string_walk_forward_window() -> None:
    # walk_forward_window is part of the epoch identity; None and a string are
    # distinct epochs and must not collide.
    with_window = mint_command_id(
        code_version="c7",
        param_version="p3",
        walk_forward_window="2026Q1",
        intent=InterventionIntent.HALT_NEW_ENTRIES,
    )
    no_window = mint_command_id(
        code_version="c7",
        param_version="p3",
        walk_forward_window=None,
        intent=InterventionIntent.HALT_NEW_ENTRIES,
    )
    assert with_window != no_window


def test_command_id_is_a_valid_uuid5_string() -> None:
    cid = mint_command_id(
        code_version="c7",
        param_version="p3",
        walk_forward_window="2026Q1",
        intent=InterventionIntent.HALT_NEW_ENTRIES,
    )
    assert isinstance(cid, str)
    parsed = uuid.UUID(cid)
    assert parsed.version == 5  # deterministic name-based UUID (not random v4)


# --- (b) InterventionCommand serialization (incl. issued_by) -----------------


def test_serialize_command_carries_issued_by_and_string_command_type() -> None:
    cmd = _command(
        command_type=CommandType.SET_SAFE_MODE_GRADE,
        args={"safe_mode_grade": 3},
        issued_by="in-session-monitor",
    )
    row = serialize_command(cmd)
    assert isinstance(row, dict)
    assert row["issued_by"] == "in-session-monitor"
    # command_type serializes to the daemon SEAM NAME string, not an enum repr.
    assert row["command_type"] == "set-safe-mode-grade"
    assert isinstance(row["command_type"], str)


def test_serialize_command_carries_all_writer_side_fields() -> None:
    cmd = _command(
        command_type=CommandType.SELECT_VALIDATED_CONFIG,
        args={"version_ref": {"code_version": "c8", "param_version": "p3"}},
        run_id="orch-run-1",
        requested_at="2026-05-30T14:05:00Z",
    )
    row = serialize_command(cmd)
    assert row["command_id"] == cmd.command_id
    assert row["command_type"] == "select-validated-config"
    assert row["args"] == {"version_ref": {"code_version": "c8", "param_version": "p3"}}
    assert row["run_id"] == "orch-run-1"
    assert row["requested_at"] == "2026-05-30T14:05:00Z"
    # Exactly the writer-side InterventionCommand field set — no daemon-owned
    # markers (applied_at / status / reject_reason are the daemon's, not written).
    assert set(row) == {
        "command_id",
        "command_type",
        "args",
        "run_id",
        "issued_by",
        "requested_at",
    }


def test_serialize_is_json_clean() -> None:
    import json

    cmd = _command(command_type=CommandType.ENGAGE_KILL_SWITCH)
    # Must round-trip through JSON with no custom encoder (clean would-be intake row).
    text = json.dumps(serialize_command(cmd))
    back = json.loads(text)
    assert back["command_type"] == "engage-kill-switch"


# --- (c) Phase-1 advisory path: returns ADVISORY, writes NOTHING live --------


def test_submit_command_returns_advisory_result() -> None:
    result = submit_command(_command(), conn=None)
    assert isinstance(result, CommandResult)
    assert result.status is CommandResultStatus.ADVISORY


def test_submit_command_advisory_has_no_command_ref() -> None:
    # Phase 1: NOTHING is confirmed-applied, so command_ref is null (mirrors the
    # audit's advisory-vs-live signal). The reason states the advisory cause.
    result = submit_command(_command(), conn=None)
    assert result.command_ref is None
    assert result.reason  # a human-readable advisory note (channel not landed)


def test_submit_command_writes_nothing_live_even_with_conn() -> None:
    # The load-bearing Phase-1 guarantee (advisor #1): mig 052 does not exist, so
    # the advisory path must IGNORE the connection entirely — a poison-spy conn
    # raises on ANY attribute access; if submit_command touched it the test blows
    # up. status == ADVISORY ALONE would not prove this.
    result = submit_command(_command(), conn=_PoisonConn())
    assert result.status is CommandResultStatus.ADVISORY
    assert result.command_ref is None


def test_submit_command_does_not_mutate_the_command() -> None:
    cmd = _command()
    before = serialize_command(cmd)
    submit_command(cmd, conn=None)
    assert serialize_command(cmd) == before


def test_submit_command_is_advisory_for_every_actionable_command_type() -> None:
    # No command_type triggers a live path in Phase 1 — all three are advisory.
    for ct, intent in (
        (CommandType.ENGAGE_KILL_SWITCH, InterventionIntent.HALT_NEW_ENTRIES),
        (CommandType.SET_SAFE_MODE_GRADE, InterventionIntent.TIGHTEN_SAFE_MODE),
        (CommandType.SELECT_VALIDATED_CONFIG, InterventionIntent.SELECT_SAFER_CONFIG),
    ):
        result = submit_command(_command(command_type=ct, intent=intent), conn=None)
        assert result.status is CommandResultStatus.ADVISORY
