"""Pure-unit tests for the In-Session Monitor intervention-audit emitter (leaf).

Task 2.4 (in-session-monitor). Asserts the design's "Leaf — audit" contract
(`emit_audit(audit, conn=None) -> dict`) and the "Data Models — InterventionAudit"
shape: build the serialized envelope from an `InterventionAudit`, tag it with the
four correlation keys (R7.3), carry the falsifiable rationale (`hypothesis` +
`falsifiers: list[str]`, P15 / R7.2), the `applied` advisory-vs-live signal
(Phase 1 always `false`, R7.1), and PERSIST it as the envelope-on-disk at
`memos/envelopes/in-session-monitor__<run_id>.json` via an atomic tmp+os.replace
write (R7.1 / R7.4).

Two behaviors are load-bearing and asserted here:
  * The serialized dict carries ALL FOUR correlation keys (run_id / code_version /
    param_version / walk_forward_window), `applied=False`, `command_ref=None`, and
    the `rationale.falsifiers` list (R7.2 / R7.3 — joinable + falsifiable). The
    keys are the daemon-epoch keys read off the analyzed trace; the audit owns the
    WHY only — no model-trace write happens here (R7.4).
  * The `conn=None` DRY-RUN writes NOTHING to disk — it returns the serialized
    dict (the would-be envelope) but persists no file. A live persist happens only
    when a connection is supplied; the file then lands at the
    `in-session-monitor__<run_id>.json` path and round-trips to the same dict.

Pure leaf (P1): stdlib + own-layer `types` only — no LLM, no MCP, no live DB. The
persist path writes a local JSON file under a tmp `memos/envelopes/` root injected
via the module's repo-root seam, so the test touches no shared envelope directory.

Requirements: 7.1 (emit the audit on intervene / declined-on-anomaly), 7.2
(falsifiable + derived, P15), 7.3 (tag the four correlation keys), 7.4 (own the
audit surface — the WHY, separate from the model trace).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.reactive.monitor import InterventionAudit
from src.reactive.monitor.audit import emit_audit
from src.reactive.telemetry import CorrelationKeys


# --- Fixtures --------------------------------------------------------------


def _keys() -> CorrelationKeys:
    """The four daemon-epoch correlation keys of the single analyzed version
    (R7.3) — read off the analyzed trace by the diagnostic, carried typed."""
    return CorrelationKeys(
        run_id="run-abc-123",
        code_version="c7",
        param_version="p3",
        walk_forward_window="2026Q1",
    )


def _audit(
    keys: CorrelationKeys | None = None,
    intervention_intent: str = "HALT_NEW_ENTRIES",
    applied: bool = False,
    command_ref: str | None = None,
    operator_action_required: str | None = None,
) -> InterventionAudit:
    """A falsifiable `InterventionAudit` (P15): the rationale is a structured
    `{hypothesis, falsifiers: list[str]}`, the trigger is a derived diagnostic
    (metric / observed / threshold / window_n — never an asserted probability)."""
    return InterventionAudit(
        keys=keys if keys is not None else _keys(),
        trigger_diagnostic={
            "metric": "brier",
            "observed": 0.31,
            "threshold": 0.18,
            "window_n": 64,
        },
        verdict="DRIFTED",
        intervention_intent=intervention_intent,
        operator_action_required=operator_action_required,
        rationale={
            "hypothesis": "softmax calibration has broken down inside survival limits",
            "falsifiers": [
                "next-window Brier returns within the pinned baseline CI",
                "reliability slope recovers toward 1.0 over W closed decisions",
            ],
        },
        applied=applied,
        command_ref=command_ref,
        event_ts="2026-05-30T14:05:00Z",
    )


@pytest.fixture()
def envelope_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the audit emitter's repo-root seam to a tmp dir so persistence
    writes under `<tmp>/memos/envelopes/`, never the shared repo envelope dir."""
    from src.reactive.monitor import audit as audit_mod

    monkeypatch.setattr(audit_mod, "_REPO_ROOT", tmp_path)
    return tmp_path


# --- Serialized-dict shape (R7.3 / R7.2) -----------------------------------


def test_returns_serialized_dict_carrying_all_four_keys() -> None:
    out = emit_audit(_audit(), conn=None)
    assert isinstance(out, dict)
    keys = out["keys"]
    assert keys["run_id"] == "run-abc-123"
    assert keys["code_version"] == "c7"
    assert keys["param_version"] == "p3"
    assert keys["walk_forward_window"] == "2026Q1"


def test_serialized_dict_carries_falsifiers_list() -> None:
    out = emit_audit(_audit(), conn=None)
    falsifiers = out["rationale"]["falsifiers"]
    assert isinstance(falsifiers, list)
    assert len(falsifiers) == 2
    assert all(isinstance(f, str) for f in falsifiers)
    assert out["rationale"]["hypothesis"]


def test_serialized_dict_phase1_advisory_signal() -> None:
    # Issue 2: Phase 1 is always advisory — applied=false, command_ref=null.
    out = emit_audit(_audit(applied=False, command_ref=None), conn=None)
    assert out["applied"] is False
    assert out["command_ref"] is None


def test_serialized_dict_carries_trigger_and_verdict_and_intent() -> None:
    out = emit_audit(_audit(intervention_intent="TIGHTEN_SAFE_MODE"), conn=None)
    assert out["verdict"] == "DRIFTED"
    assert out["intervention_intent"] == "TIGHTEN_SAFE_MODE"
    assert out["trigger_diagnostic"]["metric"] == "brier"
    assert out["trigger_diagnostic"]["window_n"] == 64
    assert out["event_ts"] == "2026-05-30T14:05:00Z"


def test_serialized_dict_carries_operator_action_required() -> None:
    # Wedged-component response (R3.1): the out-of-band operator action surfaces
    # on the audit (the daemon has no restart/clear-state seam).
    out = emit_audit(
        _audit(operator_action_required="restart_wedged_component"),
        conn=None,
    )
    assert out["operator_action_required"] == "restart_wedged_component"


def test_no_action_taken_audit_records_none_intent() -> None:
    # R7.1: a declined-on-anomaly audit still emits — intent NONE, advisory.
    out = emit_audit(_audit(intervention_intent="NONE", applied=False), conn=None)
    assert out["intervention_intent"] == "NONE"
    assert out["applied"] is False


# --- Dry-run writes NOTHING (conn=None) ------------------------------------


def test_dry_run_writes_no_file(envelope_root: Path) -> None:
    out = emit_audit(_audit(), conn=None)
    assert isinstance(out, dict)  # still returns the would-be envelope
    envelopes_dir = envelope_root / "memos" / "envelopes"
    # Nothing persisted — no envelope file, no stray tmp sibling.
    if envelopes_dir.exists():
        assert list(envelopes_dir.iterdir()) == []


# --- Live persist (conn supplied) ------------------------------------------


def test_live_persist_writes_envelope_at_run_id_path(envelope_root: Path) -> None:
    sentinel_conn = object()  # any non-None triggers the live persist branch
    out = emit_audit(_audit(), conn=sentinel_conn)
    path = envelope_root / "memos" / "envelopes" / "in-session-monitor__run-abc-123.json"
    assert path.exists()
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk == out
    # No stray *.tmp sibling left behind by the atomic write.
    siblings = list((envelope_root / "memos" / "envelopes").iterdir())
    assert [p.name for p in siblings] == ["in-session-monitor__run-abc-123.json"]


def test_live_persist_round_trips_keys_and_falsifiers(envelope_root: Path) -> None:
    sentinel_conn = object()
    emit_audit(_audit(), conn=sentinel_conn)
    path = envelope_root / "memos" / "envelopes" / "in-session-monitor__run-abc-123.json"
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["keys"]["run_id"] == "run-abc-123"
    assert on_disk["keys"]["code_version"] == "c7"
    assert on_disk["keys"]["param_version"] == "p3"
    assert on_disk["keys"]["walk_forward_window"] == "2026Q1"
    assert on_disk["rationale"]["falsifiers"]


def test_orchestration_run_id_names_the_envelope(envelope_root: Path) -> None:
    # The envelope-naming run_id is the monitor's own orchestration run_id when
    # supplied — distinct from the audit's daemon-epoch correlation run_id, which
    # still rides INSIDE the envelope's keys (design §Leaf — audit / Rev 2.1).
    sentinel_conn = object()
    out = emit_audit(_audit(), conn=sentinel_conn, run_id="orch-run-999")
    path = envelope_root / "memos" / "envelopes" / "in-session-monitor__orch-run-999.json"
    assert path.exists()
    # The correlation run_id inside the envelope is unchanged (the daemon epoch).
    assert out["keys"]["run_id"] == "run-abc-123"


def test_null_walk_forward_window_round_trips(envelope_root: Path) -> None:
    keys = CorrelationKeys(
        run_id="run-xyz",
        code_version="c1",
        param_version="p1",
        walk_forward_window=None,
    )
    sentinel_conn = object()
    out = emit_audit(_audit(keys=keys), conn=sentinel_conn)
    assert out["keys"]["walk_forward_window"] is None
    path = envelope_root / "memos" / "envelopes" / "in-session-monitor__run-xyz.json"
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["keys"]["walk_forward_window"] is None
