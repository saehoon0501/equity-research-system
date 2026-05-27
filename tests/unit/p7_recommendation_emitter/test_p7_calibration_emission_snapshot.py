"""Tests for the write-once calibration_emission_snapshot wiring in P7.

Phase-2 (P0-2 / migration 045): ``emit_recommendation`` now ALSO produces a
``calibration_emission_snapshot`` payload carrying the five reproducibility
fields {rec_id, as_of_ts, continuous_score, p_beat_benchmark, model_version}.

These tests run fully OFFLINE (no live DB) using a fake conn that records the
SQL it is handed, so the atomicity / write-once semantics can be asserted
without Postgres.

Coverage:
  * dry-run (conn=None) exposes the snapshot payload with all 5 fields
  * persist path issues the snapshot INSERT in the SAME transaction as the
    rec (and the audit chain), committing exactly once
  * backdating: inp.now (a past timestamp) flows into snapshot.as_of_ts —
    the seam the WS-4 resolver relies on to pick up a backdated rec
  * p_beat_benchmark threading + documented continuous_score proxy fallback

Per db/migrations/045_calibration_resolver.sql + v3 §6.4.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

import pytest

from src.p7_recommendation_emitter import (
    EmitInputs,
    TRIGGER_NEW_CANDIDATE,
    emit_recommendation,
)
from src.p7_recommendation_emitter.continuous_conviction import (
    score_conviction,
)
from src.p7_recommendation_emitter.conviction_rollup import ConvictionInputs


# ---------------------------------------------------------------------------
# Fakes — a recording conn/cursor with an explicit transaction() so we can
# observe that everything lands inside ONE atomic block.
# ---------------------------------------------------------------------------


class _RecordingCursor:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple]] = []

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.executed.append((sql, params))

    def close(self) -> None:
        pass


class _TxnRecordingConn:
    """psycopg3-style conn: advertises ``transaction()`` so the emitter takes
    the atomic path. Records every execute + whether the txn block was used.
    """

    def __init__(self) -> None:
        self.cur = _RecordingCursor()
        self.commits = 0
        self.transaction_entered = False
        # Index into cur.executed at the moment the txn block opened — lets us
        # prove every INSERT happened INSIDE the block.
        self.exec_count_at_txn_enter: int | None = None
        self.exec_count_at_txn_exit: int | None = None

    def cursor(self) -> _RecordingCursor:
        return self.cur

    def commit(self) -> None:
        self.commits += 1

    def transaction(self):
        outer = self

        class _Ctx:
            def __enter__(self_inner):
                outer.transaction_entered = True
                outer.exec_count_at_txn_enter = len(outer.cur.executed)
                return self_inner

            def __exit__(self_inner, exc_type, exc, tb):
                outer.exec_count_at_txn_exit = len(outer.cur.executed)
                return False

        return _Ctx()


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
        model_version="claude-opus-4-7-20260101",
    )
    base.update(overrides)
    return EmitInputs(**base)


def _expected_continuous_score(
    *, debate_add_count: int, kills_fired: int, anchor_drift: int
) -> float:
    return score_conviction(
        ConvictionInputs(
            debate_add_count=debate_add_count,
            kills_fired=kills_fired,
            anchor_drift_channels_triggered=anchor_drift,
        )
    ).score


# ---------------------------------------------------------------------------
# Dry-run: snapshot payload exposed with all 5 fields.
# ---------------------------------------------------------------------------


def test_dry_run_exposes_calibration_snapshot_with_five_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUDIT_HMAC_KEY", "test-audit-key")
    now = _dt.datetime(2026, 5, 23, 0, 0, tzinfo=_dt.timezone.utc)
    inp = _baseline_inputs(now=now, p_beat_benchmark=0.62)

    out = emit_recommendation(inp, conn=None)
    snap = out.calibration_emission_snapshot

    # All five reproducibility fields present.
    assert set(snap) == {
        "rec_id",
        "as_of_ts",
        "continuous_score",
        "p_beat_benchmark",
        "model_version",
    }
    # rec_id matches the emitted recommendation_id.
    assert snap["rec_id"] == str(out.recommendation_id)
    # as_of_ts == inp.now.
    assert snap["as_of_ts"] == now
    # continuous_score matches score_conviction on the same inputs.
    assert snap["continuous_score"] == pytest.approx(
        _expected_continuous_score(
            debate_add_count=4, kills_fired=0, anchor_drift=0
        )
    )
    # p_beat_benchmark threaded from the envelope score block.
    assert snap["p_beat_benchmark"] == pytest.approx(0.62)
    # model_version mirrors the pinned envelope model id (P0-5).
    assert snap["model_version"] == "claude-opus-4-7-20260101"


def test_dry_run_continuous_score_mirrored_into_conviction_breakdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """continuous_score is the SAME value in the snapshot and in the
    conviction_breakdown JSONB (single source of truth per §6.4)."""
    monkeypatch.setenv("AUDIT_HMAC_KEY", "test-audit-key")
    out = emit_recommendation(_baseline_inputs(p_beat_benchmark=0.5), conn=None)

    assert "continuous_score" in out.conviction_breakdown
    assert out.conviction_breakdown["continuous_score"] == pytest.approx(
        out.calibration_emission_snapshot["continuous_score"], abs=1e-4
    )


def test_dry_run_does_not_write_db(monkeypatch: pytest.MonkeyPatch) -> None:
    """conn=None must NOT touch any cursor — snapshot is computed offline."""
    monkeypatch.setenv("AUDIT_HMAC_KEY", "test-audit-key")
    conn = _TxnRecordingConn()
    # Sanity: passing conn=None means conn is unused; we just assert the
    # payload is still produced.
    out = emit_recommendation(_baseline_inputs(p_beat_benchmark=0.6), conn=None)
    assert out.calibration_emission_snapshot["p_beat_benchmark"] == pytest.approx(0.6)
    assert conn.cur.executed == []  # untouched


# ---------------------------------------------------------------------------
# p_beat_benchmark proxy fallback (documented).
# ---------------------------------------------------------------------------


def test_p_beat_benchmark_falls_back_to_continuous_score_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the caller does not thread p_beat_benchmark (upstream WS not yet
    wired), the snapshot uses continuous_score as a DOCUMENTED proxy — the
    DB column is NOT NULL, so a value must be present, never fabricated."""
    monkeypatch.setenv("AUDIT_HMAC_KEY", "test-audit-key")
    inp = _baseline_inputs()  # no p_beat_benchmark
    out = emit_recommendation(inp, conn=None)
    snap = out.calibration_emission_snapshot
    assert snap["p_beat_benchmark"] == pytest.approx(snap["continuous_score"])


# ---------------------------------------------------------------------------
# Persist path: snapshot INSERT in the SAME transaction as the rec.
# ---------------------------------------------------------------------------


def test_persist_snapshot_insert_in_same_transaction_as_rec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUDIT_HMAC_KEY", "test-audit-key")
    now = _dt.datetime(2026, 5, 23, 0, 0, tzinfo=_dt.timezone.utc)
    inp = _baseline_inputs(now=now, p_beat_benchmark=0.71)

    conn = _TxnRecordingConn()
    out = emit_recommendation(inp, conn=conn)

    sqls = [sql for sql, _ in conn.cur.executed]
    rec_inserts = [s for s in sqls if "INSERT INTO execution_recommendations" in s]
    snap_inserts = [
        s for s in sqls if "INSERT INTO calibration_emission_snapshot" in s
    ]
    audit_inserts = [s for s in sqls if "INSERT INTO audit_provenance" in s]

    # Both the rec and the snapshot are issued (exactly once each), alongside
    # the 5-stage audit chain.
    assert len(rec_inserts) == 1
    assert len(snap_inserts) == 1
    assert len(audit_inserts) == 5

    # The atomic transaction block was used, and BOTH the rec INSERT and the
    # snapshot INSERT happened INSIDE it (between enter and exit) — i.e. they
    # share the same transaction so they commit atomically.
    assert conn.transaction_entered is True
    assert conn.exec_count_at_txn_enter == 0
    assert conn.exec_count_at_txn_exit == len(conn.cur.executed)  # all 7 inside
    assert len(conn.cur.executed) == 7  # 1 rec + 1 snapshot + 5 audit

    # psycopg3 atomic block owns the commit — emitter issues no explicit one.
    assert conn.commits == 0

    # The snapshot row carries the rec's id + the emitted fields.
    snap_sql, snap_params = next(
        (sql, p)
        for sql, p in conn.cur.executed
        if "INSERT INTO calibration_emission_snapshot" in sql
    )
    # Column order: rec_id, as_of_ts, continuous_score, p_beat_benchmark, model_version
    assert snap_params[0] == str(out.recommendation_id)
    assert snap_params[1] == now
    assert snap_params[3] == pytest.approx(0.71)
    assert snap_params[4] == "claude-opus-4-7-20260101"

    # Write-once: the INSERT must NOT use ON CONFLICT (a second emit for the
    # same rec_id must be rejected by the DB PK, not silently overwritten).
    assert "ON CONFLICT" not in snap_sql.upper()


def test_persist_snapshot_continuous_score_matches_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The continuous_score INSERTed equals the snapshot payload value."""
    monkeypatch.setenv("AUDIT_HMAC_KEY", "test-audit-key")
    inp = _baseline_inputs(p_beat_benchmark=0.55)
    conn = _TxnRecordingConn()
    out = emit_recommendation(inp, conn=conn)

    _, snap_params = next(
        (sql, p)
        for sql, p in conn.cur.executed
        if "INSERT INTO calibration_emission_snapshot" in sql
    )
    assert snap_params[2] == pytest.approx(
        out.calibration_emission_snapshot["continuous_score"]
    )


# ---------------------------------------------------------------------------
# Backdating: inp.now flows into snapshot.as_of_ts (WS-4 resolver seam).
# ---------------------------------------------------------------------------


def test_backdated_now_flows_into_snapshot_as_of_ts_dry_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUDIT_HMAC_KEY", "test-audit-key")
    backdated = _dt.datetime(2024, 1, 2, 9, 30, tzinfo=_dt.timezone.utc)
    inp = _baseline_inputs(now=backdated, p_beat_benchmark=0.6)

    out = emit_recommendation(inp, conn=None)
    assert out.calibration_emission_snapshot["as_of_ts"] == backdated


def test_backdated_now_flows_into_snapshot_insert_persist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A backdated inp.now must be the as_of_ts written to the DB row — this
    is the exact seam the WS-4 resolver uses to pick up a backdated rec."""
    monkeypatch.setenv("AUDIT_HMAC_KEY", "test-audit-key")
    backdated = _dt.datetime(2024, 1, 2, 9, 30, tzinfo=_dt.timezone.utc)
    inp = _baseline_inputs(now=backdated, p_beat_benchmark=0.6)

    conn = _TxnRecordingConn()
    emit_recommendation(inp, conn=conn)

    _, snap_params = next(
        (sql, p)
        for sql, p in conn.cur.executed
        if "INSERT INTO calibration_emission_snapshot" in sql
    )
    # as_of_ts is the 2nd positional param and equals the backdated now.
    assert snap_params[1] == backdated
