"""Pure-unit tests for the ``publish`` leaf (task 3.1).

Covers the design's "Observable" for 3.1 (tasks.md line 67) without touching a
live DB or any deploy/hot-swap path:

  * a PROMOTE verdict produces resolvable ``parameters_active`` rows (the
    reactive + survival namespaces) + a boundary-label stamp of the advanced
    ``walk_forward_window`` (Req 7.1, 7.3, 1.4),
  * re-running the SAME ``run_id`` is idempotent (the version_id is minted
    deterministically off ``run_id|parameter_key``, so a re-publish collides
    by design — mirrors the trace_writer / command_writer idempotency pattern),
  * there is NO deploy/hot-swap path (Req 7.2 — the leaf only writes P2 rows),
  * a DECLINE verdict writes NOTHING,
  * ``conn=None`` is the dry-run seam (mirrors ``trace_writer``): build + return
    the shaped rows, open no connection, touch no DB.

The verdict is the real ``GateVerdict`` and the candidate is the real consumed
``Candidate`` / ``ParamSnapshot`` / ``SurvivalParameters`` frozen dataclasses —
never a loose dict (the unit-green/integration-broken trap class, design notes).
A FakeConn records every INSERT so the live-path shape + idempotency can be
asserted without a real Postgres.
"""

from __future__ import annotations

import uuid

import pytest

from src.reactive.params import ParamSnapshot
from src.reactive.types import CalibrationEvidence, Weights
from src.reactive.replay.types import Candidate
from src.survival.params import SurvivalParameters
from src.skills.walkforward_tune import publish as P
from src.skills.walkforward_tune.types import GateVerdict


# --------------------------------------------------------------------------- #
# Fixtures — real frozen-dataclass candidate + verdicts.                       #
# --------------------------------------------------------------------------- #

RUN_ID = "11111111-1111-1111-1111-111111111111"
ADVANCED_WINDOW = "2026-05-31..2026-06-30"


def _candidate() -> Candidate:
    """A real consumed ``Candidate`` carrying tuned reactive + survival values."""
    snap = ParamSnapshot(
        weights=Weights(w_trend=0.5, w_flow=0.3, w_meanrev=0.2),
        temperature=1.25,
        threshold=0.62,
        calibration=CalibrationEvidence(brier=0.18, reliability=0.81),
        code_version="cv-2026.05",
        param_version="pv-cand-A",
    )
    surv = SurvivalParameters(
        stop_out_level_pct=55.0,
        safe_mode_buffer_pct=110.0,
        per_order_size_max=0.8,
        speculative_sleeve_cap_pct=8.0,
        flatten_lead_seconds=300.0,
        assess_max_latency_seconds=5.0,
        exclusion_enabled=True,
        code_version="cv-2026.05",
        param_version="pv-cand-A",
    )
    return Candidate(param_snapshot=snap, survival_parameters=surv, code_version=None)


def _promote_verdict() -> GateVerdict:
    return GateVerdict(
        promote=True,
        selected_config="pv-cand-A",
        reasons=["dsr>=threshold", "psr>=threshold", "lexicographic_ok"],
        dsr=2.1,
        psr=0.97,
        min_trl_met=True,
        pbo=0.05,
        effective_n=4,
        lexicographic_ok=True,
    )


def _decline_verdict() -> GateVerdict:
    return GateVerdict(
        promote=False,
        selected_config=None,
        reasons=["insufficient_oos"],
        dsr=0.0,
        psr=0.0,
        min_trl_met=False,
        pbo=1.0,
        effective_n=1,
        lexicographic_ok=True,
    )


class FakeCursor:
    def __init__(self, store: list[tuple]):
        self._store = store
        self._last_conflict = False

    def execute(self, sql, params):
        assert "INSERT INTO parameters" in sql, sql
        assert "ON CONFLICT" in sql, "live publish must dedup via ON CONFLICT"
        version_id = params[0]
        # Emulate ON CONFLICT (version_id) DO NOTHING: a repeated version_id is a no-op.
        existing = {row[0] for row in self._store}
        self._last_conflict = version_id in existing
        if not self._last_conflict:
            self._store.append(tuple(params))

    def fetchone(self):
        # RETURNING version_id yields a row only when an INSERT actually wrote.
        return None if self._last_conflict else ("written",)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeTxn:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeConn:
    """Records INSERTs; emulates ON CONFLICT DO NOTHING + RETURNING."""

    def __init__(self):
        self.rows: list[tuple] = []

    def transaction(self):
        return FakeTxn()

    def cursor(self):
        return FakeCursor(self.rows)


# --------------------------------------------------------------------------- #
# Dry-run path (conn=None) — the seam this task tests.                          #
# --------------------------------------------------------------------------- #


def test_promote_dry_run_returns_resolvable_param_rows_and_boundary_stamp():
    out = P.publish(
        _promote_verdict(),
        _candidate(),
        run_id=RUN_ID,
        advanced_window=ADVANCED_WINDOW,
        conn=None,
    )
    assert out["promoted"] is True
    assert out["written"] == 0  # dry-run writes nothing

    rows = out["param_rows"]
    keys = {r["parameter_key"] for r in rows}

    # Reactive namespace: the exact keys the daemon overlays
    # (src/reactive/daemon/params.py::_reactive_snapshot_from_map).
    for k in (
        "reactive.w_trend",
        "reactive.w_flow",
        "reactive.w_meanrev",
        "reactive.temperature",
        "reactive.threshold",
        "reactive.calibration_brier",
        "reactive.calibration_reliability",
    ):
        assert k in keys, f"missing reactive key {k}"

    # Survival namespace: every survival.* threshold the daemon pins.
    for k in (
        "survival.stop_out_level_pct",
        "survival.safe_mode_buffer_pct",
        "survival.per_order_size_max",
        "survival.speculative_sleeve_cap_pct",
        "survival.flatten_lead_seconds",
        "survival.assess_max_latency_seconds",
        "survival.exclusion_enabled",
    ):
        assert k in keys, f"missing survival key {k}"

    # Every row satisfies the mig-004 namespace-prefix CHECK and carries the
    # full append-only column set the parameters table requires.
    for r in rows:
        assert r["parameter_key"].startswith(r["parameter_namespace"] + ".")
        for col in (
            "version_id",
            "parameter_key",
            "parameter_namespace",
            "value",
            "description",
            "change_rationale",
            "approved_by",
        ):
            assert col in r, f"row missing column {col}: {r}"
        # run_id provenance must be discoverable in the change_rationale.
        assert RUN_ID in r["change_rationale"]


def test_promote_writes_correct_tuned_values():
    out = P.publish(
        _promote_verdict(), _candidate(), run_id=RUN_ID,
        advanced_window=ADVANCED_WINDOW, conn=None,
    )
    by_key = {r["parameter_key"]: r["value"] for r in out["param_rows"]}
    assert by_key["reactive.w_trend"] == 0.5
    assert by_key["reactive.temperature"] == 1.25
    assert by_key["reactive.threshold"] == 0.62
    assert by_key["reactive.calibration_brier"] == 0.18
    assert by_key["survival.stop_out_level_pct"] == 55.0
    assert by_key["survival.exclusion_enabled"] is True


def test_promote_stamps_advanced_boundary_label():
    out = P.publish(
        _promote_verdict(), _candidate(), run_id=RUN_ID,
        advanced_window=ADVANCED_WINDOW, conn=None,
    )
    stamp = out["boundary_row"]
    assert stamp is not None
    # The advanced walk_forward_window label is discoverable in P2 so the daemon
    # re-sources it at hot-swap (Req 7.3 / 1.4).
    assert stamp["value"] == ADVANCED_WINDOW
    assert stamp["parameter_key"].startswith(stamp["parameter_namespace"] + ".")
    assert "walk_forward_window" in stamp["parameter_key"]
    # It is part of the returned param rows too (a single resolvable set).
    assert stamp in out["param_rows"]


def test_decline_writes_nothing():
    out = P.publish(
        _decline_verdict(), _candidate(), run_id=RUN_ID,
        advanced_window=ADVANCED_WINDOW, conn=None,
    )
    assert out["promoted"] is False
    assert out["param_rows"] == []
    assert out["boundary_row"] is None
    assert out["written"] == 0


def test_decline_writes_nothing_even_with_live_conn():
    """A decline NEVER touches the DB, even when a live conn is supplied (P7)."""
    conn = FakeConn()
    out = P.publish(
        _decline_verdict(), _candidate(), run_id=RUN_ID,
        advanced_window=ADVANCED_WINDOW, conn=conn,
    )
    assert out["promoted"] is False
    assert conn.rows == []
    assert out["written"] == 0


def test_no_deploy_hotswap_surface():
    """The leaf exposes only publish (Req 7.2 — no deploy/hot-swap/apply)."""
    forbidden = ("deploy", "hot_swap", "hotswap", "apply", "activate", "swap")
    public = [n for n in dir(P) if not n.startswith("_")]
    for name in public:
        for bad in forbidden:
            assert bad not in name.lower(), f"publish leaf exposes a deploy-ish name: {name}"


# --------------------------------------------------------------------------- #
# Live path (FakeConn) — idempotency on run_id.                                 #
# --------------------------------------------------------------------------- #


def test_promote_live_writes_rows():
    conn = FakeConn()
    out = P.publish(
        _promote_verdict(), _candidate(), run_id=RUN_ID,
        advanced_window=ADVANCED_WINDOW, conn=conn,
    )
    assert out["promoted"] is True
    # reactive(7) + survival(7) + boundary(1) = 15 rows.
    assert len(conn.rows) == len(out["param_rows"]) == 15
    assert out["written"] == 15


def test_idempotent_on_run_id():
    """Re-running the SAME run_id is a no-op: the deterministic version_id
    collides and ON CONFLICT DO NOTHING swallows the re-write."""
    conn = FakeConn()
    first = P.publish(
        _promote_verdict(), _candidate(), run_id=RUN_ID,
        advanced_window=ADVANCED_WINDOW, conn=conn,
    )
    n_after_first = len(conn.rows)
    second = P.publish(
        _promote_verdict(), _candidate(), run_id=RUN_ID,
        advanced_window=ADVANCED_WINDOW, conn=conn,
    )
    assert len(conn.rows) == n_after_first  # no new rows on re-run
    assert second["written"] == 0  # nothing newly written the second time
    # The first run did write everything.
    assert first["written"] == n_after_first


def test_version_id_is_deterministic_uuid5_on_run_id_and_key():
    """The minted version_id is uuid5(run_id|parameter_key) — same inputs,
    same id across processes (the idempotency key)."""
    out = P.publish(
        _promote_verdict(), _candidate(), run_id=RUN_ID,
        advanced_window=ADVANCED_WINDOW, conn=None,
    )
    for r in out["param_rows"]:
        vid = r["version_id"]
        parsed = uuid.UUID(vid)
        assert parsed.version == 5
        # Re-deriving from the same (run_id, parameter_key) yields the same id.
        assert vid == P.mint_version_id(run_id=RUN_ID, parameter_key=r["parameter_key"])


def test_different_run_id_mints_distinct_version_ids():
    a = P.mint_version_id(run_id=RUN_ID, parameter_key="reactive.threshold")
    b = P.mint_version_id(
        run_id="22222222-2222-2222-2222-222222222222",
        parameter_key="reactive.threshold",
    )
    assert a != b


def test_promote_requires_param_candidate():
    """A promote with no param_snapshot AND no survival_parameters has nothing
    to publish — the leaf rejects it rather than writing an empty set (P7)."""
    empty = Candidate(param_snapshot=None, survival_parameters=None, code_version="cv-x")
    with pytest.raises(ValueError):
        P.publish(
            _promote_verdict(), empty, run_id=RUN_ID,
            advanced_window=ADVANCED_WINDOW, conn=None,
        )
