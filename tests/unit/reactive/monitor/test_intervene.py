"""Pure-unit tests for the In-Session Monitor intervention decision (leaf).

Task 2.3 (in-session-monitor). Asserts the design's "Leaf — intervene" contract
(`decide(verdict, active, menu, params) -> InterventionIntent`) — the pure map
from an envelope verdict to the bounded §15 reading-#2 intervention vocabulary,
conservative-only, select-safer-from-the-validated-menu, never-fit.

The verdict→intent mapping (design §Leaf — intervene; severity-banded, cutoffs
P2-pinned upstream in the judge):
  * IN_ENVELOPE / INSUFFICIENT             -> NONE
  * `mild` DRIFTED                          -> SELECT_SAFER_CONFIG if a safer
                                               menu candidate exists, else
                                               TIGHTEN_SAFE_MODE (least-disruptive
                                               that restores the envelope)
  * `severe` DRIFTED (calibration collapse) -> HALT_NEW_ENTRIES

Three structural invariants asserted here:
  * Conservative-only (R5.1) — a DRIFTED verdict whose banded `severity` is NOT
    strictly more conservative than the live `active.severity` is rejected to
    NONE. The guard is the SHARED `Severity` ordering on `EnvelopeVerdict.severity`
    vs `ActiveState.severity` (design: "`result.severity <= active.severity` is
    the conservative-only guard") — one comparison, never a parallel intent→grade
    table. Redundant with the daemon's toward-safer guard (defense in depth, P6).
  * Menu-only / toward-safer (R9.3, R3.3) — `SELECT_SAFER_CONFIG` is chosen ONLY
    when the validated-version menu offers a candidate distinct from the active
    version; an empty / active-only menu falls back to TIGHTEN_SAFE_MODE.
  * Never-fit (R1.4, R3.3) — `decide` NEVER ranks/parses version strings to invent
    a "safer" version: the menu predicate is purely structural (is there a
    validated member other than the active one?). The concrete never-fit assertion
    is `mild DRIFTED + empty menu -> TIGHTEN_SAFE_MODE`, never SELECT.

`decide` owns R5.1 ONLY. It does NOT consult `active.kill_switch_engaged` /
`safe_mode_grade` (R5.2 "don't relax an engaged reflex" is command_writer / Phase 2)
and it does NOT emit the wedged-component `operator_action_required` flag (that is
an InterventionAudit field set by the audit leaf / orchestrator — none of `decide`'s
inputs carry a wedged signal). Its slice is strictly verdict-severity -> intent.

Pure leaf (P1): stdlib + own-layer `types` only — no DB, no MCP, no LLM. The
returned `InterventionIntent` is one of EXACTLY four members (the cardinality is
the operator-granted authority bound).

Requirements: 3.1 (operational authority — halt/tighten), 3.2 (select-pre-validated
-config), 3.3 (never fit / never select-unvalidated), 5.1 (conservative-only),
9.3 (select only from the published registry/menu).
"""

from __future__ import annotations

import pytest

from src.reactive.monitor import (
    ActiveState,
    EnvelopeState,
    EnvelopeVerdict,
    InterventionIntent,
    MonitorParams,
    Severity,
    VersionRef,
)
from src.reactive.monitor.intervene import decide

# Two distinct validated-version menu entries (structural identity only — the
# three telemetry version keys; no safety field exists on VersionRef by design).
_ACTIVE_VERSION = VersionRef(code_version="c2", param_version="p2", walk_forward_window="2026Q1")
_OTHER_VERSION = VersionRef(code_version="c1", param_version="p1", walk_forward_window="2025Q4")


def _params() -> MonitorParams:
    """A P2-shaped `MonitorParams`. `decide` is a pure severity->intent map and
    does not bind any numeric knob (severity is already banded by the judge), so
    the values here are placeholders kept only to satisfy the design signature."""
    return MonitorParams(
        min_observations=5,
        window_W=50,
        margin_M=0.02,
        severity_cutoffs={"mild": 0.05, "severe": 0.15},
        in_sample_baseline={},
        cadence_seconds=300,
    )


def _verdict(state: EnvelopeState, severity: Severity, binding_metric: str | None = None) -> EnvelopeVerdict:
    return EnvelopeVerdict(state=state, severity=severity, binding_metric=binding_metric)


def _active(severity: Severity = Severity.NONE) -> ActiveState:
    """The live state intervene must not loosen. `safe_mode_grade` /
    `kill_switch_engaged` are deliberately set to benign values — `decide` owns
    R5.1 (the severity guard) only and must NOT branch on them (R5.2 is Phase 2)."""
    return ActiveState(
        version=_ACTIVE_VERSION,
        safe_mode_grade=0,
        kill_switch_engaged=False,
        severity=severity,
    )


# --- IN_ENVELOPE / INSUFFICIENT -> NONE ------------------------------------


def test_in_envelope_yields_none() -> None:
    out = decide(_verdict(EnvelopeState.IN_ENVELOPE, Severity.NONE), _active(), [], _params())
    assert out is InterventionIntent.NONE


def test_insufficient_yields_none() -> None:
    out = decide(_verdict(EnvelopeState.INSUFFICIENT, Severity.NONE), _active(), [], _params())
    assert out is InterventionIntent.NONE


def test_in_envelope_with_menu_still_yields_none() -> None:
    # A populated menu must not coax a non-DRIFTED verdict into selecting.
    out = decide(
        _verdict(EnvelopeState.IN_ENVELOPE, Severity.NONE),
        _active(),
        [_OTHER_VERSION],
        _params(),
    )
    assert out is InterventionIntent.NONE


# --- severe DRIFTED -> HALT_NEW_ENTRIES (calibration collapse) ---------------


def test_severe_drifted_yields_halt() -> None:
    out = decide(
        _verdict(EnvelopeState.DRIFTED, Severity.SEVERE, "brier"),
        _active(Severity.NONE),
        [_OTHER_VERSION],  # a candidate exists, but severe overrides to HALT
        _params(),
    )
    assert out is InterventionIntent.HALT_NEW_ENTRIES


def test_severe_drifted_halts_even_with_empty_menu() -> None:
    out = decide(
        _verdict(EnvelopeState.DRIFTED, Severity.SEVERE, "brier"),
        _active(Severity.NONE),
        [],
        _params(),
    )
    assert out is InterventionIntent.HALT_NEW_ENTRIES


# --- mild DRIFTED -> SELECT_SAFER_CONFIG if a candidate exists ---------------


def test_mild_drifted_with_safer_candidate_selects_config() -> None:
    out = decide(
        _verdict(EnvelopeState.DRIFTED, Severity.MILD, "brier"),
        _active(Severity.NONE),
        [_OTHER_VERSION],  # a validated member distinct from the active version
        _params(),
    )
    assert out is InterventionIntent.SELECT_SAFER_CONFIG


def test_mild_drifted_with_only_active_in_menu_tightens() -> None:
    # The menu contains ONLY the active version -> no distinct candidate ->
    # fall back to TIGHTEN_SAFE_MODE (cannot "select a safer one" when there is
    # no other validated member).
    out = decide(
        _verdict(EnvelopeState.DRIFTED, Severity.MILD, "brier"),
        _active(Severity.NONE),
        [_ACTIVE_VERSION],
        _params(),
    )
    assert out is InterventionIntent.TIGHTEN_SAFE_MODE


def test_mild_drifted_with_only_value_equal_active_in_menu_tightens() -> None:
    # The menu's "active" entry arrives as a DISTINCT object that is VALUE-equal to
    # the active version (the normal case — the active version is itself a
    # published menu member, read separately from the DB). The candidate predicate
    # must compare by VALUE (frozen-dataclass equality), not identity: a
    # distinct-but-equal copy is NOT a safer candidate, so decide TIGHTENs rather
    # than churning by selecting the version it is already on. (Guards against an
    # `!=`->`is not` regression that the _ACTIVE_VERSION singleton tests cannot.)
    same_value = VersionRef(code_version="c2", param_version="p2", walk_forward_window="2026Q1")
    assert same_value is not _ACTIVE_VERSION and same_value == _ACTIVE_VERSION
    out = decide(
        _verdict(EnvelopeState.DRIFTED, Severity.MILD, "brier"),
        _active(Severity.NONE),
        [same_value],
        _params(),
    )
    assert out is InterventionIntent.TIGHTEN_SAFE_MODE
    assert out is not InterventionIntent.SELECT_SAFER_CONFIG


# --- never-fit: mild DRIFTED + empty menu -> TIGHTEN, never SELECT -----------


def test_mild_drifted_with_empty_menu_tightens_never_selects() -> None:
    # The concrete never-fit assertion: with NO validated candidate, decide must
    # NOT fabricate / rank a "safer" version — it falls back to TIGHTEN_SAFE_MODE.
    out = decide(
        _verdict(EnvelopeState.DRIFTED, Severity.MILD, "brier"),
        _active(Severity.NONE),
        [],
        _params(),
    )
    assert out is InterventionIntent.TIGHTEN_SAFE_MODE
    assert out is not InterventionIntent.SELECT_SAFER_CONFIG


# --- conservative-only (R5.1): never decrease conservatism -------------------


def test_mild_drift_when_active_already_mild_is_rejected_to_none() -> None:
    # verdict.severity (MILD) is NOT strictly more conservative than the live
    # active.severity (MILD) -> the move would not increase conservatism -> NONE.
    out = decide(
        _verdict(EnvelopeState.DRIFTED, Severity.MILD, "brier"),
        _active(Severity.MILD),
        [_OTHER_VERSION],
        _params(),
    )
    assert out is InterventionIntent.NONE


def test_mild_drift_when_active_already_severe_is_rejected_to_none() -> None:
    # The live state is SEVERE; a MILD verdict would LOOSEN -> rejected to NONE.
    out = decide(
        _verdict(EnvelopeState.DRIFTED, Severity.MILD, "brier"),
        _active(Severity.SEVERE),
        [_OTHER_VERSION],
        _params(),
    )
    assert out is InterventionIntent.NONE


def test_severe_drift_when_active_already_severe_is_rejected_to_none() -> None:
    # SEVERE verdict against an already-SEVERE active state is not MORE
    # conservative (equal) -> rejected to NONE (the guard is strict: <= rejects).
    out = decide(
        _verdict(EnvelopeState.DRIFTED, Severity.SEVERE, "brier"),
        _active(Severity.SEVERE),
        [],
        _params(),
    )
    assert out is InterventionIntent.NONE


def test_severe_drift_when_active_mild_escalates_to_halt() -> None:
    # SEVERE verdict is strictly more conservative than a MILD active state ->
    # the escalation is allowed -> HALT.
    out = decide(
        _verdict(EnvelopeState.DRIFTED, Severity.SEVERE, "brier"),
        _active(Severity.MILD),
        [],
        _params(),
    )
    assert out is InterventionIntent.HALT_NEW_ENTRIES


# --- decide owns R5.1 ONLY: does not branch on kill_switch / safe_mode_grade --


def test_decide_ignores_kill_switch_engaged_flag() -> None:
    # R5.2 (don't relax an engaged reflex) is command_writer / Phase 2 — decide
    # must NOT branch on active.kill_switch_engaged. A severe DRIFT strictly above
    # a NONE active still HALTs regardless of the (Phase-2-only) flag.
    active = ActiveState(
        version=_ACTIVE_VERSION,
        safe_mode_grade=9,
        kill_switch_engaged=True,
        severity=Severity.NONE,
    )
    out = decide(_verdict(EnvelopeState.DRIFTED, Severity.SEVERE, "brier"), active, [], _params())
    assert out is InterventionIntent.HALT_NEW_ENTRIES


# --- authority is bounded to EXACTLY the four intents ------------------------


@pytest.mark.parametrize(
    "verdict",
    [
        _verdict(EnvelopeState.IN_ENVELOPE, Severity.NONE),
        _verdict(EnvelopeState.INSUFFICIENT, Severity.NONE),
        _verdict(EnvelopeState.DRIFTED, Severity.MILD, "brier"),
        _verdict(EnvelopeState.DRIFTED, Severity.SEVERE, "brier"),
    ],
)
def test_result_is_always_one_of_the_four_intents(verdict: EnvelopeVerdict) -> None:
    for menu in ([], [_OTHER_VERSION], [_ACTIVE_VERSION, _OTHER_VERSION]):
        for active_sev in (Severity.NONE, Severity.MILD, Severity.SEVERE):
            out = decide(verdict, _active(active_sev), menu, _params())
            assert isinstance(out, InterventionIntent)
            assert out in {
                InterventionIntent.NONE,
                InterventionIntent.HALT_NEW_ENTRIES,
                InterventionIntent.TIGHTEN_SAFE_MODE,
                InterventionIntent.SELECT_SAFER_CONFIG,
            }


def test_drifted_with_severity_none_is_treated_as_no_actionable_intent() -> None:
    # Defensive: a DRIFTED verdict should never carry NONE (the judge guarantees
    # MILD/SEVERE), but if one arrives, decide must not invent an intent — the
    # conservative guard (NONE <= active NONE) rejects it to NONE.
    out = decide(_verdict(EnvelopeState.DRIFTED, Severity.NONE), _active(Severity.NONE), [], _params())
    assert out is InterventionIntent.NONE


# --- purity ----------------------------------------------------------------


def test_decide_does_not_mutate_menu() -> None:
    menu = [_OTHER_VERSION]
    before = list(menu)
    decide(_verdict(EnvelopeState.DRIFTED, Severity.MILD, "brier"), _active(), menu, _params())
    assert menu == before
