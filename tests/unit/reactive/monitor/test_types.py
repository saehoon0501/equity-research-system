"""Pure-unit shape/contract tests for the In-Session Monitor domain types.

Task 1.2 (in-session-monitor). Asserts the named observables the parent's
import/shape check can't on its own: every dataclass's exact field set, the
frozen guarantee, and the two fixed-cardinality enums the design pins by count
(`InterventionIntent` is EXACTLY four members; `EnvelopeState` is three). No DB,
no MCP, no I/O — these are pure leaf types (P1). The leaf modules' runtime
behavior (diagnostic / judge / intervene / audit / command_writer) is tested in
later tasks.

The field sets are taken verbatim from design.md "Data Models" (InterventionAudit,
InterventionCommand, MonitorParams) and the "Leaf —" contract signatures
(EnvelopeVerdict{state, severity, binding_metric}; DriftDiagnostic per-metric
observed+ci+baseline, window_n, in_survival_band, sufficient, analyzed keys;
intervene's ActiveState/VersionRef; command_writer's CommandResult).

Requirements: 2.2 (classify sub-survival drift → verdict types), 3.1 (operational
authority vocabulary → the four intents + the command-type seams), 7.3 (4-key
correlation tag on the audit → keys: CorrelationKeys).
"""

from __future__ import annotations

import dataclasses as d

import pytest

from src.reactive.monitor import (
    ActiveState,
    CommandResult,
    CommandResultStatus,
    CommandType,
    DriftDiagnostic,
    EnvelopeState,
    EnvelopeVerdict,
    InterventionAudit,
    InterventionCommand,
    InterventionIntent,
    MetricObservation,
    MonitorParams,
    Severity,
    VersionRef,
)
from src.reactive.telemetry import CorrelationKeys


def _keys() -> CorrelationKeys:
    return CorrelationKeys(
        run_id="00000000-0000-0000-0000-000000000000",
        code_version="c1",
        param_version="p1",
        walk_forward_window="2026Q1",
    )


# --- Enums: fixed cardinality is load-bearing -----------------------------


def test_intervention_intent_has_exactly_four_members() -> None:
    # design.md: "InterventionIntent enum with EXACTLY four members" — the three
    # daemon-actionable intents plus NONE. A fifth would mint authority §15
    # reading #2 does not grant.
    assert len(InterventionIntent) == 4
    assert {m.name for m in InterventionIntent} == {
        "NONE",
        "HALT_NEW_ENTRIES",
        "TIGHTEN_SAFE_MODE",
        "SELECT_SAFER_CONFIG",
    }


def test_envelope_state_has_exactly_three_members() -> None:
    assert len(EnvelopeState) == 3
    assert {m.name for m in EnvelopeState} == {
        "IN_ENVELOPE",
        "DRIFTED",
        "INSUFFICIENT",
    }


def test_command_type_is_the_three_daemon_seams() -> None:
    # design.md "Owned (writer-side only) — InterventionCommand": command_type is
    # the daemon's THREE intake seam names — distinct vocabulary from the FOUR
    # InterventionIntent members (the advisor-flagged trap).
    assert len(CommandType) == 3
    assert {m.value for m in CommandType} == {
        "engage-kill-switch",
        "set-safe-mode-grade",
        "select-validated-config",
    }


def test_severity_is_ordered_and_banded() -> None:
    # Severity is shared by EnvelopeVerdict.severity and ActiveState.severity so
    # intervene's `result.severity <= active.severity` (ordered) AND the
    # mild/severe band branch both type-check. IntEnum gives the ordering.
    assert Severity.NONE < Severity.MILD < Severity.SEVERE
    assert {m.name for m in Severity} == {"NONE", "MILD", "SEVERE"}


def test_command_result_status_members() -> None:
    # Phase 1 returns ADVISORY (design command_writer leaf); Phase 2 adds the
    # live outcomes the confirm/fail-safe path needs.
    assert {m.name for m in CommandResultStatus} == {
        "ADVISORY",
        "APPLIED",
        "REJECTED",
        "ESCALATED",
    }


# --- Dataclass field sets (verbatim from design) --------------------------


def test_metric_observation_fields() -> None:
    assert [f.name for f in d.fields(MetricObservation)] == [
        "observed",
        "ci_low",
        "ci_high",
        "baseline",
    ]


def test_envelope_verdict_fields() -> None:
    # design "Leaf — judge": EnvelopeVerdict {state, severity, binding_metric}.
    assert [f.name for f in d.fields(EnvelopeVerdict)] == [
        "state",
        "severity",
        "binding_metric",
    ]


def test_drift_diagnostic_fields() -> None:
    # design "Leaf — diagnostic": per-metric (observed, ci_low, ci_high) +
    # baseline, window_n, in_survival_band, sufficient, analyzed version keys.
    assert [f.name for f in d.fields(DriftDiagnostic)] == [
        "metrics",
        "window_n",
        "in_survival_band",
        "sufficient",
        "keys",
    ]


def test_intervention_command_fields() -> None:
    # design "Owned (writer-side only) — InterventionCommand".
    assert [f.name for f in d.fields(InterventionCommand)] == [
        "command_id",
        "command_type",
        "args",
        "run_id",
        "issued_by",
        "requested_at",
    ]


def test_intervention_audit_fields() -> None:
    # design "Owned — InterventionAudit" (envelope-on-disk; the HG validator and
    # emit_audit serialize THIS field set — keep them byte-aligned).
    assert [f.name for f in d.fields(InterventionAudit)] == [
        "keys",
        "trigger_diagnostic",
        "verdict",
        "intervention_intent",
        "operator_action_required",
        "rationale",
        "applied",
        "command_ref",
        "event_ts",
    ]


def test_monitor_params_fields() -> None:
    # design "Owned — MonitorParams".
    assert [f.name for f in d.fields(MonitorParams)] == [
        "min_observations",
        "window_W",
        "margin_M",
        "severity_cutoffs",
        "in_sample_baseline",
        "cadence_seconds",
    ]


def test_version_ref_fields() -> None:
    assert [f.name for f in d.fields(VersionRef)] == [
        "code_version",
        "param_version",
        "walk_forward_window",
    ]


def test_active_state_fields() -> None:
    assert [f.name for f in d.fields(ActiveState)] == [
        "version",
        "safe_mode_grade",
        "kill_switch_engaged",
        "severity",
    ]


def test_command_result_fields() -> None:
    assert [f.name for f in d.fields(CommandResult)] == [
        "status",
        "command_ref",
        "reason",
    ]


# --- Frozen-ness: every record type is immutable --------------------------


def test_all_dataclasses_are_frozen() -> None:
    metric = MetricObservation(observed=0.2, ci_low=0.1, ci_high=0.3, baseline=0.15)
    verdict = EnvelopeVerdict(
        state=EnvelopeState.DRIFTED,
        severity=Severity.MILD,
        binding_metric="brier",
    )
    diag = DriftDiagnostic(
        metrics={"brier": metric},
        window_n=42,
        in_survival_band=False,
        sufficient=True,
        keys=_keys(),
    )
    command = InterventionCommand(
        command_id="cmd-1",
        command_type=CommandType.ENGAGE_KILL_SWITCH,
        args={},
        run_id="run-1",
        issued_by="in-session-monitor",
        requested_at="2026-05-30T00:00:00Z",
    )
    audit = InterventionAudit(
        keys=_keys(),
        trigger_diagnostic={"metric": "brier", "observed": 0.2},
        verdict="DRIFTED",
        intervention_intent="HALT_NEW_ENTRIES",
        operator_action_required=None,
        rationale={"hypothesis": "calibration collapse", "falsifiers": ["brier recovers"]},
        applied=False,
        command_ref=None,
        event_ts="2026-05-30T00:00:00Z",
    )
    params = MonitorParams(
        min_observations=30,
        window_W=100,
        margin_M=0.05,
        severity_cutoffs={"mild": 0.05, "severe": 0.15},
        in_sample_baseline={"brier": 0.18},
        cadence_seconds=300,
    )
    version = VersionRef(code_version="c1", param_version="p1", walk_forward_window="2026Q1")
    active = ActiveState(
        version=version,
        safe_mode_grade=0,
        kill_switch_engaged=False,
        severity=Severity.NONE,
    )
    result = CommandResult(
        status=CommandResultStatus.ADVISORY, command_ref=None, reason="phase-1 no-op"
    )

    for obj, field_name, new_value in [
        (metric, "observed", 0.0),
        (verdict, "binding_metric", "ece"),
        (diag, "window_n", 0),
        (command, "command_id", "x"),
        (audit, "applied", True),
        (params, "cadence_seconds", 1),
        (version, "code_version", "c2"),
        (active, "kill_switch_engaged", True),
        (result, "status", CommandResultStatus.APPLIED),
    ]:
        with pytest.raises(d.FrozenInstanceError):
            setattr(obj, field_name, new_value)


# --- The 4-key correlation tag rides typed, not in a blob (R7.3) ----------


def test_audit_and_diagnostic_carry_typed_correlation_keys() -> None:
    # Requirement 7.3: the audit joins to the model trace + ledger via the four
    # correlation keys — carried as a typed CorrelationKeys, not a loose dict.
    diag = DriftDiagnostic(
        metrics={},
        window_n=0,
        in_survival_band=True,
        sufficient=False,
        keys=_keys(),
    )
    audit = InterventionAudit(
        keys=_keys(),
        trigger_diagnostic={},
        verdict="INSUFFICIENT",
        intervention_intent="NONE",
        operator_action_required=None,
        rationale={"hypothesis": "n/a", "falsifiers": []},
        applied=False,
        command_ref=None,
        event_ts="2026-05-30T00:00:00Z",
    )
    assert isinstance(diag.keys, CorrelationKeys)
    assert isinstance(audit.keys, CorrelationKeys)
    assert audit.keys.param_version == "p1"
