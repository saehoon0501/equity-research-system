"""Tests for src/p7_recommendation_emitter/.

Coverage:
  * sizing — mode bands + 3 hard overlay edge cases
  * conviction rollup — HIGH/MEDIUM/LOW + LOW-precedence
  * hysteresis — 2-cycle persistence + flip-frequency escalation
  * trigger_logic — cadence-floor per mode + M-2/M-3 interrupts
  * execution_context — risk_flags aggregation
  * emitter — full orchestration + HMAC round-trip via audit_trail.verify_chain

Per v3 spec Section 4.6 + Section 5 Q1 + Section 7 Q4.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any
from uuid import UUID, uuid4

import pytest

from src.audit_trail.hmac_verify import verify_chain
from src.audit_trail.loader import StageRow
from src.p7_recommendation_emitter import (
    AUDIT_HMAC_ENV,
    CONVICTION_HIGH,
    CONVICTION_LOW,
    CONVICTION_MEDIUM,
    ConvictionInputs,
    EmitInputs,
    HysteresisInputs,
    P7EmitError,
    SizingContext,
    TRIGGER_M2,
    TRIGGER_MODE_CADENCE_FLOOR,
    TRIGGER_NEW_CANDIDATE,
    TriggerInputs,
    aggregate_risk_flags,
    apply_hysteresis,
    cadence_floor_due_at,
    compute_sizing,
    compute_trigger_metadata,
    emit_recommendation,
    roll_up_conviction,
)


# ===========================================================================
# Sizing
# ===========================================================================


def test_sizing_mode_bands_unmodified() -> None:
    """All overlays None → no multipliers, returns base bands."""
    out = compute_sizing(SizingContext(mode="B"))
    assert out.initial_pct == pytest.approx(3.0)
    assert out.max_pct == pytest.approx(8.0)
    assert out.net_multiplier == pytest.approx(1.0)
    assert out.funding_required is False


def test_sizing_b_prime_band() -> None:
    out = compute_sizing(SizingContext(mode="B_prime"))
    assert out.initial_pct == pytest.approx(2.0)
    assert out.max_pct == pytest.approx(5.0)


def test_sizing_c_band() -> None:
    out = compute_sizing(SizingContext(mode="C"))
    assert out.initial_pct == pytest.approx(1.0)
    assert out.max_pct == pytest.approx(3.0)


def test_sizing_invalid_mode_raises() -> None:
    with pytest.raises(ValueError):
        compute_sizing(SizingContext(mode="X"))


def test_sizing_cash_overlay_binding() -> None:
    """Cash < target → multiplier scales initial down; funding_required."""
    out = compute_sizing(
        SizingContext(mode="B_prime", available_cash_pct=1.0)  # < 2.0 target
    )
    assert out.funding_required is True
    assert out.initial_pct == pytest.approx(1.0)
    # max_pct unaffected by cash overlay (post-funding ceiling).
    assert out.max_pct == pytest.approx(5.0)


def test_sizing_cash_overlay_not_binding() -> None:
    out = compute_sizing(
        SizingContext(mode="B_prime", available_cash_pct=10.0)  # ample
    )
    assert out.funding_required is False
    assert out.initial_pct == pytest.approx(2.0)


def test_sizing_drawdown_overlay_threshold_exclusive() -> None:
    """At exactly threshold (5pp for B), no tighten."""
    out = compute_sizing(
        SizingContext(mode="B", portfolio_underperformance_pp_vs_bench=5.0)
    )
    assert out.initial_pct == pytest.approx(3.0)


def test_sizing_drawdown_overlay_fires() -> None:
    """Above threshold → × 0.5."""
    out = compute_sizing(
        SizingContext(mode="B", portfolio_underperformance_pp_vs_bench=6.0)
    )
    assert out.initial_pct == pytest.approx(1.5)
    assert out.max_pct == pytest.approx(4.0)


def test_sizing_vol_overlay_threshold_exclusive() -> None:
    """At exactly +1σ, no tighten (strict ">")."""
    out = compute_sizing(SizingContext(mode="B_prime", s0_vol_z=1.0))
    assert out.initial_pct == pytest.approx(2.0)


def test_sizing_vol_overlay_fires() -> None:
    out = compute_sizing(SizingContext(mode="B_prime", s0_vol_z=1.5))
    assert out.initial_pct == pytest.approx(2.0 * 0.7)
    assert out.max_pct == pytest.approx(5.0 * 0.7)


def test_sizing_compound_overlays() -> None:
    """All 3 overlays fire — multipliers compound."""
    out = compute_sizing(
        SizingContext(
            mode="B_prime",
            available_cash_pct=0.5,  # binds to 0.5
            portfolio_underperformance_pp_vs_bench=10.0,  # > 7pp → 0.5
            s0_vol_z=2.0,  # > 1σ → 0.7
        )
    )
    # initial: 2.0 × 0.5 (drawdown) × 0.7 (vol) = 0.7; cash 0.5 < 0.7 → cash mult = 0.714
    # final initial = 0.5 (capped to cash)
    assert out.initial_pct == pytest.approx(0.5, rel=0.01)
    assert out.funding_required is True
    # max: 5.0 × 0.5 × 0.7 = 1.75 (no cash overlay)
    assert out.max_pct == pytest.approx(1.75)


def test_sizing_overlays_documented_with_reason() -> None:
    out = compute_sizing(SizingContext(mode="B"))
    overlay_names = {o.name for o in out.applied_overlays}
    assert overlay_names == {"cash_constraint", "drawdown_tighten", "vol_regime"}
    for o in out.applied_overlays:
        assert o.reason  # non-empty


# ===========================================================================
# Conviction rollup
# ===========================================================================


def test_conviction_high_gate_all_satisfied() -> None:
    out = roll_up_conviction(
        ConvictionInputs(
            debate_add_count=4,
            kills_fired=0,
            anchor_drift_channels_triggered=0,
        )
    )
    assert out.bucket == CONVICTION_HIGH


def test_conviction_high_blocked_by_kill() -> None:
    """4/5 debate + 1 kill → MEDIUM (not HIGH; kills_fired must be 0)."""
    out = roll_up_conviction(
        ConvictionInputs(
            debate_add_count=4,
            kills_fired=1,
            anchor_drift_channels_triggered=0,
        )
    )
    assert out.bucket == CONVICTION_MEDIUM


def test_conviction_low_2_kills() -> None:
    out = roll_up_conviction(
        ConvictionInputs(
            debate_add_count=5,
            kills_fired=2,
            anchor_drift_channels_triggered=0,
        )
    )
    assert out.bucket == CONVICTION_LOW


def test_conviction_low_under_3_debate() -> None:
    out = roll_up_conviction(
        ConvictionInputs(
            debate_add_count=2,
            kills_fired=0,
            anchor_drift_channels_triggered=0,
        )
    )
    assert out.bucket == CONVICTION_LOW


def test_conviction_low_takes_precedence_over_high() -> None:
    """Spec ambiguity resolution: LOW > HIGH when both could fire."""
    # 4 ADD + 0 kills + 0 drift would be HIGH...
    # ...but ≥2 kills_fired fires LOW.
    out = roll_up_conviction(
        ConvictionInputs(
            debate_add_count=4,
            kills_fired=2,
            anchor_drift_channels_triggered=0,
        )
    )
    assert out.bucket == CONVICTION_LOW


def test_conviction_medium_3_debate() -> None:
    out = roll_up_conviction(
        ConvictionInputs(
            debate_add_count=3,
            kills_fired=0,
            anchor_drift_channels_triggered=0,
        )
    )
    assert out.bucket == CONVICTION_MEDIUM


def test_conviction_medium_2_drift_channels() -> None:
    out = roll_up_conviction(
        ConvictionInputs(
            debate_add_count=4,
            kills_fired=0,
            anchor_drift_channels_triggered=2,
        )
    )
    assert out.bucket == CONVICTION_MEDIUM


# ===========================================================================
# Hysteresis
# ===========================================================================


def test_hysteresis_new_candidate_commits_immediately() -> None:
    out = apply_hysteresis(
        HysteresisInputs(proposed_bucket=CONVICTION_HIGH, prior_bucket=None)
    )
    assert out.effective_bucket == CONVICTION_HIGH
    assert out.pending_transition is False
    assert out.flip_count_30d == 0


def test_hysteresis_no_change_clears_pending() -> None:
    out = apply_hysteresis(
        HysteresisInputs(
            proposed_bucket=CONVICTION_MEDIUM,
            prior_bucket=CONVICTION_MEDIUM,
            prior_pending_target=CONVICTION_HIGH,
            prior_pending_transition=True,
        )
    )
    assert out.effective_bucket == CONVICTION_MEDIUM
    assert out.pending_transition is False
    assert out.pending_target is None


def test_hysteresis_cycle_one_queues() -> None:
    """First cycle of transition: prior remains, target queued."""
    out = apply_hysteresis(
        HysteresisInputs(
            proposed_bucket=CONVICTION_HIGH,
            prior_bucket=CONVICTION_MEDIUM,
            prior_pending_transition=False,
        )
    )
    assert out.effective_bucket == CONVICTION_MEDIUM
    assert out.pending_transition is True
    assert out.pending_target == CONVICTION_HIGH


def test_hysteresis_cycle_two_commits() -> None:
    out = apply_hysteresis(
        HysteresisInputs(
            proposed_bucket=CONVICTION_HIGH,
            prior_bucket=CONVICTION_MEDIUM,
            prior_pending_target=CONVICTION_HIGH,
            prior_pending_transition=True,
        )
    )
    assert out.effective_bucket == CONVICTION_HIGH
    assert out.pending_transition is False
    assert out.flip_count_30d == 1


def test_hysteresis_target_change_resets() -> None:
    """Pending was HIGH, now LOW proposed → restart 2-cycle clock."""
    out = apply_hysteresis(
        HysteresisInputs(
            proposed_bucket=CONVICTION_LOW,
            prior_bucket=CONVICTION_MEDIUM,
            prior_pending_target=CONVICTION_HIGH,
            prior_pending_transition=True,
        )
    )
    assert out.effective_bucket == CONVICTION_MEDIUM
    assert out.pending_transition is True
    assert out.pending_target == CONVICTION_LOW


def test_hysteresis_flip_frequency_escalates() -> None:
    """4 flips in 30 days → auto-demote MEDIUM + freeze + M-2 escalate."""
    today = _dt.date(2026, 4, 29)
    flip_history = [
        today - _dt.timedelta(days=20),
        today - _dt.timedelta(days=15),
        today - _dt.timedelta(days=10),
    ]
    out = apply_hysteresis(
        HysteresisInputs(
            proposed_bucket=CONVICTION_HIGH,
            prior_bucket=CONVICTION_MEDIUM,
            prior_pending_target=CONVICTION_HIGH,
            prior_pending_transition=True,
            flip_history_30d=flip_history,
            now_date=today,
        )
    )
    assert out.frozen_pending_review is True
    assert out.escalate_m2 is True
    assert out.effective_bucket == CONVICTION_MEDIUM
    assert out.flip_count_30d == 4


def test_hysteresis_window_trims_old_flips() -> None:
    """Flips older than 30 days are not counted."""
    today = _dt.date(2026, 4, 29)
    flip_history = [
        today - _dt.timedelta(days=45),  # outside window
        today - _dt.timedelta(days=10),
    ]
    out = apply_hysteresis(
        HysteresisInputs(
            proposed_bucket=CONVICTION_HIGH,
            prior_bucket=CONVICTION_MEDIUM,
            prior_pending_target=CONVICTION_HIGH,
            prior_pending_transition=True,
            flip_history_30d=flip_history,
            now_date=today,
        )
    )
    # Only 1 prior flip in window + this commit = 2 total → not escalated
    assert out.flip_count_30d == 2
    assert out.escalate_m2 is False


# ===========================================================================
# Trigger logic
# ===========================================================================


def test_cadence_floor_b_next_monday() -> None:
    # Wed 2026-04-29 → next Mon 2026-05-04.
    now = _dt.datetime(2026, 4, 29, 12, 0, tzinfo=_dt.timezone.utc)
    floor = cadence_floor_due_at("B", now)
    assert floor.date() == _dt.date(2026, 5, 4)


def test_cadence_floor_b_prime_3_days() -> None:
    now = _dt.datetime(2026, 4, 29, 12, 0, tzinfo=_dt.timezone.utc)
    floor = cadence_floor_due_at("B_prime", now)
    assert floor.date() == _dt.date(2026, 5, 2)


def test_cadence_floor_c_daily() -> None:
    now = _dt.datetime(2026, 4, 29, 12, 0, tzinfo=_dt.timezone.utc)
    floor = cadence_floor_due_at("C", now)
    assert floor.date() == _dt.date(2026, 4, 30)


def test_trigger_metadata_m2_requires_event_ref() -> None:
    with pytest.raises(ValueError, match="materiality_event_ref"):
        compute_trigger_metadata(
            TriggerInputs(mode="B", triggered_by=TRIGGER_M2)
        )


def test_trigger_metadata_changed_from_prior() -> None:
    out = compute_trigger_metadata(
        TriggerInputs(
            mode="B_prime",
            triggered_by=TRIGGER_MODE_CADENCE_FLOOR,
            prior_recommendation="HOLD",
            new_recommendation="BUY",
        )
    )
    assert out.changed_from_prior is True


def test_trigger_metadata_new_candidate() -> None:
    out = compute_trigger_metadata(
        TriggerInputs(
            mode="C",
            triggered_by=TRIGGER_NEW_CANDIDATE,
        )
    )
    assert out.changed_from_prior is False
    assert out.cadence_floor_due_at is not None


# ===========================================================================
# Risk flags aggregation
# ===========================================================================


def test_risk_flags_empty_inputs() -> None:
    assert aggregate_risk_flags() == []


def test_risk_flags_s0_regime_shift() -> None:
    flags = aggregate_risk_flags(
        s0_regime_state={
            "dimensions": [
                {"dimension_name": "vol_vrp", "bocpd_short_run_mass": 0.85}
            ]
        }
    )
    assert any("vol_vrp" in f for f in flags)


def test_risk_flags_s4_catastrophic() -> None:
    flags = aggregate_risk_flags(s4_smart_money={"category": "catastrophic"})
    assert any("catastrophic" in f for f in flags)


def test_risk_flags_dedup() -> None:
    flags = aggregate_risk_flags(extra=["dup", "dup", "other"])
    assert flags == ["dup", "other"]


# ===========================================================================
# Emitter — full orchestration + HMAC round-trip
# ===========================================================================


class _FakeCursor:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple]] = []

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.executed.append((sql, params))

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def close(self) -> None:
        pass


class _FakeConn:
    def __init__(self) -> None:
        self.cur = _FakeCursor()
        self.committed = False

    def cursor(self) -> _FakeCursor:
        return self.cur

    def commit(self) -> None:
        self.committed = True


def _baseline_inputs(**overrides: Any) -> EmitInputs:
    base = dict(
        ticker="NVDA",
        mode="B_prime",
        company_quality_flag="HIGH",
        mode_certainty="rule_clean",
        debate_add_count=4,
        debate_consensus_summary="4/5 (Quant-Technical dissents HOLD)",
        kills_fired=0,
        anchor_drift_channels_triggered=0,
        primary_recommendation="BUY",
        suggested_pacing="DCA over 21 days",
        triggered_by=TRIGGER_NEW_CANDIDATE,
        available_cash_pct=10.0,
        current_price=158.32,
        fair_value_payload={"point": 175, "range_low": 155, "range_high": 195},
        near_term_catalysts_raw=[
            {"event": "Q2 earnings", "date": "2026-05-22", "importance": "high"}
        ],
        technical_signals_raw={
            "ma_50d": 150,
            "ma_200d": 130,
            "rsi_14": 62,
            "atr_20": 5.0,
        },
        stage_drill_payloads={
            "stage_1_mechanical": {"outcome": "PROCEED", "score": 0.85},
            "stage_2_debate": {
                "consensus": "4/5 ADD",
                "dissenter": "Quant-Technical",
            },
            "stage_3_kill_criteria": {"fired": 0},
            "stage_4_counterfactual": {
                "note": "deprecated stage, retained for chain shape",
            },
            "materiality": {
                "classification": "M-1",
                "trigger": "new_candidate",
            },
        },
    )
    base.update(overrides)
    return EmitInputs(**base)


def test_emit_requires_audit_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(AUDIT_HMAC_ENV, raising=False)
    with pytest.raises(P7EmitError):
        emit_recommendation(_baseline_inputs(), conn=None)


def test_emit_dry_run_returns_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(AUDIT_HMAC_ENV, "test-audit-key")
    out = emit_recommendation(_baseline_inputs(), conn=None)
    assert out.recommendation == "BUY"
    assert out.conviction == CONVICTION_HIGH
    assert len(out.audit_signature) == 64  # SHA256 hex
    assert len(out.audit_chain_ids) == 5  # 5 stages


def test_emit_full_q1_schema_populated(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every Section 4.6 Q1 envelope key is populated."""
    monkeypatch.setenv(AUDIT_HMAC_ENV, "test-audit-key")
    out = emit_recommendation(_baseline_inputs(), conn=None)
    siz = out.sizing_payload
    assert "initial_pct" in siz
    assert "max_pct" in siz
    assert "base_band" in siz
    assert "applied_overlays" in siz
    assert "net_multiplier" in siz
    assert "funding_required" in siz

    cb = out.conviction_breakdown
    assert "debate_consensus" in cb
    assert "kills_fired" in cb
    assert "mode_certainty" in cb
    assert "drift_channels" in cb

    tm = out.trigger_metadata
    assert "triggered_by" in tm
    assert "cadence_floor_due_at" in tm
    assert "changed_from_prior" in tm

    ec = out.execution_context
    assert "current_price" in ec
    assert "fair_value_estimate" in ec
    assert "near_term_catalysts" in ec
    assert "suggested_pacing" in ec
    assert "technical_signals" in ec
    assert "risk_flags" in ec


def test_emit_audit_chain_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    """Audit chain emitted by P7 must verify under audit_trail.verify_chain."""
    monkeypatch.setenv(AUDIT_HMAC_ENV, "shared-audit-secret")

    inp = _baseline_inputs()
    # Capture the audit rows by intercepting the persistence step.
    captured_audit: list[dict] = []
    captured_main: list[dict] = []

    class _Cursor:
        def execute(self, sql: str, params: tuple) -> None:
            if "INSERT INTO execution_recommendations" in sql:
                captured_main.append({"sql": sql, "params": params})
            elif "INSERT INTO audit_provenance" in sql:
                captured_audit.append({"sql": sql, "params": params})

        def close(self) -> None:
            pass

    class _Conn:
        def cursor(self) -> _Cursor:
            return _Cursor()

        def commit(self) -> None:
            pass

    conn = _Conn()
    out = emit_recommendation(inp, conn=conn)

    # 5 stage rows emitted.
    assert len(captured_audit) == 5

    # Reconstruct StageRows to feed verify_chain.
    rows: list[StageRow] = []
    import json as _json

    for entry in captured_audit:
        params = entry["params"]
        # SQL parameter order matches emitter._persist:
        # (audit_id, recommendation_id, stage, drill_payload, hmac_signature,
        #  parent_audit_id, versions, created_at)
        audit_id = UUID(params[0])
        rec_id = UUID(params[1])
        stage = params[2]
        drill_payload = _json.loads(params[3])
        hmac_signature = params[4]
        parent_audit_id = UUID(params[5]) if params[5] else None
        versions = _json.loads(params[6])
        created_at = params[7]
        rows.append(
            StageRow(
                audit_id=audit_id,
                recommendation_id=rec_id,
                stage=stage,
                drill_payload=drill_payload,
                hmac_signature=hmac_signature,
                parent_audit_id=parent_audit_id,
                versions=versions,
                created_at=created_at,
            )
        )

    result = verify_chain(rows, key=b"shared-audit-secret")
    assert result.mode == "keyed"
    assert result.all_ok, [r for r in result.rows if not r.ok]


def test_emit_low_conviction_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """2 kills → LOW conviction; sizing still computed."""
    monkeypatch.setenv(AUDIT_HMAC_ENV, "test-audit-key")
    inp = _baseline_inputs(kills_fired=2)
    out = emit_recommendation(inp, conn=None)
    assert out.conviction == CONVICTION_LOW


def test_emit_with_overlays_active(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drawdown + vol overlays both fire; sizing reduced; risk_flags include vol."""
    monkeypatch.setenv(AUDIT_HMAC_ENV, "test-audit-key")
    inp = _baseline_inputs(
        portfolio_underperformance_pp_vs_bench=10.0,
        s0_vol_z=2.0,
        s0_regime_state={
            "dimensions": [
                {"dimension_name": "vol_vrp", "bocpd_short_run_mass": 0.9}
            ],
            "vol_elevated": True,
        },
    )
    out = emit_recommendation(inp, conn=None)
    siz = out.sizing_payload
    assert siz["net_multiplier"] < 1.0
    assert any("vol" in f.lower() for f in out.execution_context["risk_flags"])


def test_emit_persists_via_fake_conn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(AUDIT_HMAC_ENV, "test-audit-key")
    conn = _FakeConn()
    out = emit_recommendation(_baseline_inputs(), conn=conn)
    # 1 main row + 5 audit rows = 6 SQL executes.
    assert len(conn.cur.executed) == 6
    # First INSERT is execution_recommendations.
    sql0, params0 = conn.cur.executed[0]
    assert "INSERT INTO execution_recommendations" in sql0
    assert params0[1] == "NVDA"  # ticker
    # Audit rows follow.
    for sql, _ in conn.cur.executed[1:]:
        assert "INSERT INTO audit_provenance" in sql
    assert conn.committed is True


def test_audit_signature_includes_conviction_changed_from_prior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression test for canonical-projection ↔ migration-008-trigger lock.

    Per migration 008 ``exec_recs_guard`` (db/migrations/008_v3_recommendations.sql
    line 189), ``conviction_changed_from_prior`` is in the trigger's
    rejection clause — i.e., immutable post-insert. Therefore P7 MUST
    sign over it; otherwise tampering with that column in Postgres
    would not invalidate the HMAC.

    This test mutates the column and confirms the signature flips.
    """
    from src.audit_trail.hmac_verify import compute_signature_dict
    from src.p7_recommendation_emitter.emitter import _row_canonical_payload

    monkeypatch.setenv(AUDIT_HMAC_ENV, "test-audit-key")
    out = emit_recommendation(_baseline_inputs(), conn=None)

    # Reconstruct a minimal canonical row matching emit_recommendation's
    # payload. We don't have the raw `row` dict, so we synthesize one
    # with both values for conviction_changed_from_prior and check that
    # the signatures DIFFER. This implicitly proves the field is in the
    # signed projection.
    base_row = {
        "recommendation_id": str(out.recommendation_id),
        "ticker": "NVDA",
        "date": _dt.date(2026, 4, 29),
        "recommendation": "BUY",
        "conviction": "HIGH",
        "conviction_changed_from_prior": False,
        # state-machine columns (must be excluded):
        "conviction_pending_transition": False,
        "conviction_pending_target": None,
        "conviction_flip_count_30d": 0,
        "conviction_frozen_pending_review": False,
        "audit_signature": "ignored",
    }
    sig_a = compute_signature_dict(
        _row_canonical_payload(base_row), b"k"
    )
    flipped = dict(base_row)
    flipped["conviction_changed_from_prior"] = True
    sig_b = compute_signature_dict(
        _row_canonical_payload(flipped), b"k"
    )
    assert sig_a != sig_b, (
        "conviction_changed_from_prior must be part of the signed canonical "
        "projection (migration 008 exec_recs_guard treats it as immutable)"
    )

    # Also confirm the four narrow-UPDATE-allowed columns are NOT signed.
    for state_col in (
        "conviction_pending_transition",
        "conviction_pending_target",
        "conviction_flip_count_30d",
        "conviction_frozen_pending_review",
    ):
        mutated = dict(base_row)
        # Toggle to a different value of the right type.
        if state_col == "conviction_pending_target":
            mutated[state_col] = "HIGH"
        elif state_col == "conviction_flip_count_30d":
            mutated[state_col] = 5
        else:
            mutated[state_col] = True
        sig_mut = compute_signature_dict(
            _row_canonical_payload(mutated), b"k"
        )
        assert sig_mut == sig_a, (
            f"state-machine column {state_col!r} must be excluded from "
            "signed payload (migration 008 trigger allows narrow UPDATE)"
        )


def test_hysteresis_pending_target_change_starts_fresh_cycle_count() -> None:
    """DECISION LOCK: mid-stream pending_target change → restart 2-cycle clock.

    When the pending_target changes (cycle 1 was MEDIUM→HIGH; cycle 2
    proposes MEDIUM→LOW), the new proposal must NOT commit immediately;
    it counts as cycle 1/2 of the NEW transition.

    Reference: ``src/p7_recommendation_emitter/hysteresis.py`` Case 4
    + module docstring; v3 spec Section 4.6 Phase 4 Q7.

    Rationale: alternative interpretation (commit-on-cycle-2 regardless of
    target match) defeats the persistence guarantee — the transition is
    no longer "the same condition for 2 consecutive cycles".
    """
    out = apply_hysteresis(
        HysteresisInputs(
            proposed_bucket=CONVICTION_LOW,
            prior_bucket=CONVICTION_MEDIUM,
            prior_pending_target=CONVICTION_HIGH,
            prior_pending_transition=True,
        )
    )
    # NEW transition queued — effective stays at prior; pending_target is the new proposal.
    assert out.effective_bucket == CONVICTION_MEDIUM
    assert out.pending_transition is True
    assert out.pending_target == CONVICTION_LOW
    # No flip recorded yet — that requires cycle 2 confirmation of the new target.
    assert out.flip_count_30d == 0
    assert "restart" in out.rationale.lower()


# ===========================================================================
# Transaction-boundary regression tests (multi-row write atomicity audit).
# ===========================================================================
#
# The emitter writes 1 execution_recommendations row + 5 audit_provenance
# rows. Per the audit-chain HMAC contract (Section 5 Q1), all 6 rows MUST
# commit together. A mid-batch failure that left only the recommendation
# row would surface to /audit-trail as "broken chain" — these tests pin
# the rollback behaviour so a regression would fail loudly.
# ===========================================================================


class _FailingAuditCursor(_FakeCursor):
    """Fake cursor that raises on the Nth INSERT (simulates CHECK violation)."""

    def __init__(self, fail_after_n_audit_inserts: int) -> None:
        super().__init__()
        self._audit_seen = 0
        self._limit = fail_after_n_audit_inserts

    def execute(self, sql: str, params: tuple = ()) -> None:
        super().execute(sql, params)
        if "audit_provenance" in sql.lower():
            self._audit_seen += 1
            if self._audit_seen > self._limit:
                raise RuntimeError(
                    "simulated CHECK violation on audit_provenance insert"
                )


class _FailingAuditConn:
    """Fake connection that:
      * advertises ``transaction()`` (psycopg3-style) so the emitter
        takes the atomic path,
      * raises mid-loop via the cursor,
      * tracks rollback / commit counts so the test can assert.
    """

    def __init__(self, fail_after_n_audit_inserts: int) -> None:
        self._cur = _FailingAuditCursor(fail_after_n_audit_inserts)
        self.rollbacks = 0
        self.commits = 0
        self.transaction_entered = False
        self.transaction_exited_clean = False

    def cursor(self) -> _FakeCursor:
        return self._cur

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def transaction(self):
        outer = self

        class _Ctx:
            def __enter__(self_inner):
                outer.transaction_entered = True
                return self_inner

            def __exit__(self_inner, exc_type, exc, tb):
                outer.transaction_exited_clean = exc_type is None
                # psycopg3 contract: re-raise exception so caller sees it.
                return False

        return _Ctx()


def test_emit_partial_failure_rolls_back_via_psycopg3_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mid-batch failure must propagate WITHOUT committing partial rows.

    Per Section 5 Q1 audit-chain lock: a CHECK violation on the 3rd
    audit_provenance INSERT must NOT leave the recommendation row +
    first 2 audit rows committed (orphan / broken chain). The psycopg3
    ``with conn.transaction():`` block is the atomicity primitive.
    """
    monkeypatch.setenv(AUDIT_HMAC_ENV, "test-audit-key")
    conn = _FailingAuditConn(fail_after_n_audit_inserts=2)

    with pytest.raises(RuntimeError, match="simulated CHECK violation"):
        emit_recommendation(_baseline_inputs(), conn=conn)

    # The transaction block was entered (atomic boundary engaged).
    assert conn.transaction_entered is True
    # The transaction block was exited with an exception (NOT clean) —
    # psycopg3 will then ROLLBACK the whole batch on the real connection.
    assert conn.transaction_exited_clean is False
    # Emitter did NOT issue an explicit commit (atomic block owns commit).
    assert conn.commits == 0


class _Psycopg2StyleConn:
    """Fake psycopg2-style conn (no ``transaction()`` method).

    Has ``autocommit`` toggle + ``commit``/``rollback`` so the emitter
    falls into the legacy fallback path which manages the transaction
    via autocommit toggling.
    """

    def __init__(self, fail_after_n_audit_inserts: int) -> None:
        self._cur = _FailingAuditCursor(fail_after_n_audit_inserts)
        self.rollbacks = 0
        self.commits = 0
        self.autocommit = True  # start in autocommit; emitter must disable it

    def cursor(self) -> _FakeCursor:
        return self._cur

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def test_emit_partial_failure_rolls_back_via_psycopg2_autocommit_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """psycopg2-style fallback: rollback on mid-batch failure.

    Caller is in autocommit=True; emitter must (a) flip to autocommit=False
    for the multi-row write, (b) rollback on exception, (c) NEVER issue
    a partial commit before re-raising.
    """
    monkeypatch.setenv(AUDIT_HMAC_ENV, "test-audit-key")
    conn = _Psycopg2StyleConn(fail_after_n_audit_inserts=2)

    with pytest.raises(RuntimeError, match="simulated CHECK violation"):
        emit_recommendation(_baseline_inputs(), conn=conn)

    # Rollback was issued.
    assert conn.rollbacks == 1
    # No commit before the rollback.
    assert conn.commits == 0


def test_emit_clean_psycopg2_path_commits_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful path: psycopg2 fallback issues exactly ONE commit."""
    monkeypatch.setenv(AUDIT_HMAC_ENV, "test-audit-key")
    # fail_after = large → no failures.
    conn = _Psycopg2StyleConn(fail_after_n_audit_inserts=99)
    out = emit_recommendation(_baseline_inputs(), conn=conn)
    assert out is not None
    assert conn.rollbacks == 0
    assert conn.commits == 1
