"""Pure-unit tests for the ``audit`` leaf (task 3.2).

Covers the design's "Observable" for 3.2 (tasks.md line 74) without touching a
live DB:

  * a row payload is assembled on PROMOTE **and** on DECLINE (R8.1 — emitted on
    both; this is where audit DIVERGES from publish, which writes nothing on a
    decline),
  * the envelope carries the DERIVED gate metrics (P15 — derived, not asserted)
    + the FALSIFIABLE promotion hypothesis (a structured statement + observable
    falsifiers, so task 3.3's HG validator can check the hypothesis and the
    falsifiers SEPARATELY) + the four correlation keys (R8.2, R8.3),
  * ``conn=None`` is the dry-run seam: it writes the envelope file but NO DB row
    (the audit leaf's persistence INVERTS publish/monitor — the envelope-on-disk
    is UNCONDITIONAL per P4; only the append-only DB INSERT is gated on ``conn``),
  * the live path writes ONE append-only ``walkforward_tuner_audit`` row, and is
    idempotent on the cycle (``audit_id`` minted deterministically off ``run_id``
    so a crash/resume re-fire collides via ``ON CONFLICT (audit_id) DO NOTHING``,
    R9.1).

The audit is the real ``TunerActionAudit`` frozen dataclass (never a loose dict
— the unit-green/integration-broken trap class). A FakeConn records every INSERT
so the live-path shape + idempotency can be asserted without a real Postgres. The
module-level ``_REPO_ROOT`` seam is monkeypatched to ``tmp_path`` so NO test ever
writes into the shared repo ``memos/envelopes/`` (the dry-run write is
unconditional here, so this redirect is mandatory — unlike test_publish.py).
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from src.skills.walkforward_tune import audit as A
from src.skills.walkforward_tune.types import GateVerdict, TunerActionAudit


# --------------------------------------------------------------------------- #
# Fixtures — real frozen-dataclass TunerActionAudit on both verdicts.          #
# --------------------------------------------------------------------------- #

RUN_ID = "11111111-1111-1111-1111-111111111111"
CODE_VERSION = "cv-2026.05"
PARAM_VERSION = "pv-cand-A"
ADVANCED_WINDOW = "2026-05-31..2026-06-30"


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


def _hypothesis(statement: str, falsifiers: list[str]) -> dict:
    """The falsifiable promotion rationale (P15): a structured statement + the
    observable falsifiers task 3.3 checks SEPARATELY (so neither is a bare str)."""
    return {"statement": statement, "falsifiers": falsifiers}


def _promote_audit() -> TunerActionAudit:
    v = _promote_verdict()
    return TunerActionAudit(
        audit_id=A.mint_audit_id(run_id=RUN_ID),
        run_id=RUN_ID,
        code_version=CODE_VERSION,
        param_version=PARAM_VERSION,
        walk_forward_window=ADVANCED_WINDOW,  # advanced on promote
        promoted=True,
        track="param",
        gate_metrics=A.gate_metrics_from_verdict(v),
        hypothesis=_hypothesis(
            "Candidate pv-cand-A's survival-net OOS edge over the incumbent "
            "persists out-of-sample across the CPCV partitions.",
            [
                "next cycle's OOS survival-net return falls below the incumbent's",
                "a survival breach / stop-out appears the incumbent did not incur",
                "OOS calibration reliability degrades below the incumbent's",
            ],
        ),
    )


def _decline_audit() -> TunerActionAudit:
    """A DECLINE still carries a full gate_metrics + falsifiable hypothesis — the
    mig-053 columns are NOT NULL on decline too (R8.1/R8.2)."""
    v = _decline_verdict()
    return TunerActionAudit(
        audit_id=A.mint_audit_id(run_id=RUN_ID),
        run_id=RUN_ID,
        code_version=CODE_VERSION,
        param_version=PARAM_VERSION,
        walk_forward_window=None,  # decline advances no boundary (mig-053: null until promoted)
        promoted=False,
        track="param",
        gate_metrics=A.gate_metrics_from_verdict(v),
        hypothesis=_hypothesis(
            "No candidate cleared the gate this cycle; the incumbent is retained "
            "because the OOS evidence was statistically insufficient (MinTRL not met).",
            [
                "next cycle's OOS observation count clears MinTRL for a candidate",
                "a candidate's deflated Sharpe clears the threshold next cycle",
            ],
        ),
    )


# --------------------------------------------------------------------------- #
# FakeConn — records INSERTs; emulates ON CONFLICT DO NOTHING + RETURNING.      #
# --------------------------------------------------------------------------- #


class FakeCursor:
    def __init__(self, store: list[tuple]):
        self._store = store
        self._last_conflict = False

    def execute(self, sql, params):
        assert "INSERT INTO walkforward_tuner_audit" in sql, sql
        assert "ON CONFLICT" in sql, "live audit write must dedup via ON CONFLICT"
        audit_id = params[0]
        existing = {row[0] for row in self._store}
        self._last_conflict = audit_id in existing
        if not self._last_conflict:
            self._store.append(tuple(params))

    def fetchone(self):
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
    """Records INSERTs; emulates ON CONFLICT (audit_id) DO NOTHING + RETURNING."""

    def __init__(self):
        self.rows: list[tuple] = []

    def transaction(self):
        return FakeTxn()

    def cursor(self):
        return FakeCursor(self.rows)


@pytest.fixture(autouse=True)
def _redirect_envelope_dir(tmp_path, monkeypatch):
    """The envelope write is UNCONDITIONAL (even in dry-run), so redirect the
    module-level repo-root seam to a tmp dir — no test touches the real
    memos/envelopes/."""
    monkeypatch.setattr(A, "_REPO_ROOT", tmp_path)
    return tmp_path


def _envelope_file(tmp_path: Path, run_id: str = RUN_ID) -> Path:
    return tmp_path / "memos" / "envelopes" / f"walkforward-tune__{run_id}.json"


# --------------------------------------------------------------------------- #
# Envelope shape — derived metrics + falsifiable hypothesis + 4 keys.          #
# --------------------------------------------------------------------------- #


def test_promote_envelope_carries_four_keys_metrics_and_hypothesis():
    out = A.write_audit(_promote_audit(), conn=None)

    # The four correlation keys (R8.3) — flattened on the envelope so it joins
    # decision_process_trace / counterfactual_ledger.
    assert out["run_id"] == RUN_ID
    assert out["code_version"] == CODE_VERSION
    assert out["param_version"] == PARAM_VERSION
    assert out["walk_forward_window"] == ADVANCED_WINDOW

    # Derived gate metrics (P15) — the six gate figures, derived not asserted.
    gm = out["gate_metrics"]
    for k in ("dsr", "psr", "min_trl_met", "pbo", "effective_n", "lexicographic_ok"):
        assert k in gm, f"gate_metrics missing derived key {k}"
    assert gm["dsr"] == 2.1
    assert gm["effective_n"] == 4

    # The falsifiable hypothesis: a STRUCTURED statement + observable falsifiers
    # (so task 3.3 checks the hypothesis and the falsifiers separately).
    hyp = out["hypothesis"]
    assert isinstance(hyp["statement"], str) and hyp["statement"].strip()
    assert isinstance(hyp["falsifiers"], list) and len(hyp["falsifiers"]) >= 1
    assert all(isinstance(f, str) and f.strip() for f in hyp["falsifiers"])

    # The verdict + track + audit_id ride too (mirrors the mig-053 columns).
    assert out["promoted"] is True
    assert out["track"] == "param"
    assert uuid.UUID(out["audit_id"]).version == 5


def test_decline_envelope_carries_metrics_and_hypothesis_too():
    """R8.1: the audit is emitted on DECLINE too — full gate_metrics +
    falsifiable hypothesis present, with a null advanced window."""
    out = A.write_audit(_decline_audit(), conn=None)
    assert out["promoted"] is False
    assert out["walk_forward_window"] is None  # decline advances no boundary
    gm = out["gate_metrics"]
    for k in ("dsr", "psr", "min_trl_met", "pbo", "effective_n", "lexicographic_ok"):
        assert k in gm
    assert gm["min_trl_met"] is False
    hyp = out["hypothesis"]
    assert isinstance(hyp["statement"], str) and hyp["statement"].strip()
    assert isinstance(hyp["falsifiers"], list) and len(hyp["falsifiers"]) >= 1


def test_envelope_is_json_serializable():
    """The returned envelope round-trips through json (the file write does the
    same) — a numeric derived metric must stay numeric, never stringified."""
    out = A.write_audit(_promote_audit(), conn=None)
    reloaded = json.loads(json.dumps(out))
    assert reloaded["gate_metrics"]["dsr"] == 2.1
    assert isinstance(reloaded["gate_metrics"]["dsr"], float)


# --------------------------------------------------------------------------- #
# Dry-run (conn=None) — writes the envelope FILE but NO DB row.                 #
# --------------------------------------------------------------------------- #


def test_dry_run_writes_envelope_file_but_no_db_row(_redirect_envelope_dir):
    tmp = _redirect_envelope_dir
    out = A.write_audit(_promote_audit(), conn=None)

    # No DB row (dry-run).
    assert out["written"] == 0

    # The envelope file IS written (P4 persistence is unconditional).
    path = _envelope_file(tmp)
    assert path.exists(), "dry-run must still persist the envelope-on-disk (P4)"
    on_disk = json.loads(path.read_text())
    assert on_disk["run_id"] == RUN_ID
    assert on_disk["gate_metrics"]["dsr"] == 2.1
    assert on_disk["hypothesis"]["statement"]


def test_dry_run_decline_also_writes_envelope_file(_redirect_envelope_dir):
    tmp = _redirect_envelope_dir
    out = A.write_audit(_decline_audit(), conn=None)
    assert out["written"] == 0
    path = _envelope_file(tmp)
    assert path.exists()
    on_disk = json.loads(path.read_text())
    assert on_disk["promoted"] is False


# --------------------------------------------------------------------------- #
# Live path (FakeConn) — a row on promote AND on decline; idempotent on run_id. #
# --------------------------------------------------------------------------- #


def test_live_promote_writes_one_db_row():
    conn = FakeConn()
    out = A.write_audit(_promote_audit(), conn=conn)
    assert out["written"] == 1
    assert len(conn.rows) == 1


def test_live_decline_writes_one_db_row():
    """The point where audit DIVERGES from publish: a decline STILL writes a row
    (R8.1 — emitted on both)."""
    conn = FakeConn()
    out = A.write_audit(_decline_audit(), conn=conn)
    assert out["written"] == 1
    assert len(conn.rows) == 1


def test_live_write_persists_envelope_file_too(_redirect_envelope_dir):
    tmp = _redirect_envelope_dir
    conn = FakeConn()
    A.write_audit(_promote_audit(), conn=conn)
    # The envelope is persisted on the live path as well (P4).
    assert _envelope_file(tmp).exists()


def test_idempotent_on_run_id_resume():
    """Crash/resume re-fires the SAME run_id (R9.1). Two INDEPENDENTLY-built
    audits for the same run_id mint the SAME audit_id (uuid5 off run_id), so the
    second write collides via ON CONFLICT (audit_id) DO NOTHING — one row total.
    Building two distinct objects (not reusing one) is what actually exercises
    the deterministic-id contract; a random id would pass a same-object test."""
    conn = FakeConn()
    first = A.write_audit(_promote_audit(), conn=conn)
    n_after_first = len(conn.rows)
    second = A.write_audit(_promote_audit(), conn=conn)  # a fresh object, same run_id
    assert len(conn.rows) == n_after_first  # no new row on resume
    assert first["written"] == 1
    assert second["written"] == 0  # the resume re-fire is a no-op


def test_audit_id_is_deterministic_uuid5_on_run_id():
    a = A.mint_audit_id(run_id=RUN_ID)
    b = A.mint_audit_id(run_id=RUN_ID)
    assert a == b
    assert uuid.UUID(a).version == 5


def test_different_run_id_mints_distinct_audit_ids():
    a = A.mint_audit_id(run_id=RUN_ID)
    b = A.mint_audit_id(run_id="22222222-2222-2222-2222-222222222222")
    assert a != b


# --------------------------------------------------------------------------- #
# gate_metrics_from_verdict — the DERIVED-metrics projection (P15).            #
# --------------------------------------------------------------------------- #


def test_gate_metrics_are_a_pure_projection_of_the_verdict():
    """P15: the gate metrics are DERIVED (a projection of the gate's output),
    not asserted magic numbers — provably equal to the verdict's fields."""
    v = _promote_verdict()
    gm = A.gate_metrics_from_verdict(v)
    assert gm == {
        "dsr": v.dsr,
        "psr": v.psr,
        "min_trl_met": v.min_trl_met,
        "pbo": v.pbo,
        "effective_n": v.effective_n,
        "lexicographic_ok": v.lexicographic_ok,
    }


def test_no_deploy_or_apply_surface():
    """The audit leaf exposes only the writer + the deterministic helpers — no
    deploy/apply/promote-action surface (it records, it does not act)."""
    forbidden = ("deploy", "hot_swap", "hotswap", "apply", "activate")
    public = [n for n in dir(A) if not n.startswith("_")]
    for name in public:
        for bad in forbidden:
            assert bad not in name.lower(), f"audit leaf exposes an action-ish name: {name}"
