"""Smoke tests for src/audit_trail/.

No live Postgres required — tests use a hand-rolled FakeConnection that
implements just enough of the loader's _Connection / _Cursor protocol to
drive get_audit_summary, get_stage_drill, get_chain_for_recommendation,
and get_latest_for_ticker.

Verifies:
  - Top-level summary renders all 5 stages with drill_link commands.
  - Per-stage drill renders verbatim quotes / iteration logs / etc.
  - HMAC verification: OK case + tampered case + unkeyed mode.
  - Latest-by-ticker lookup.
  - CLI argparse smoke.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

import pytest

from src.audit_trail import (
    canonical_payload,
    compute_signature,
    get_audit_summary,
    get_chain_for_recommendation,
    get_latest_for_ticker,
    get_stage_drill,
    render_audit_summary,
    render_chain_verification,
    render_stage_drill,
    verify_chain,
)
from src.audit_trail.loader import StageRow


# -----------------------------------------------------------------------------
# Fake Postgres connection
# -----------------------------------------------------------------------------


class FakeCursor:
    def __init__(self, store: "FakeStore") -> None:
        self._store = store
        self._result: list[tuple[Any, ...]] = []

    def execute(self, sql: str, params: Optional[tuple[Any, ...]] = None) -> None:
        params = params or ()
        sql_norm = " ".join(sql.split())
        if "FROM execution_recommendations" in sql_norm and "ORDER BY date DESC" in sql_norm:
            ticker = params[0]
            rows = [r for r in self._store.recommendations if r["ticker"] == ticker]
            rows.sort(key=lambda r: (r["date"], r["created_at"]), reverse=True)
            self._result = [(str(r["recommendation_id"]),) for r in rows[:1]]
            return
        if "FROM execution_recommendations" in sql_norm and "WHERE recommendation_id" in sql_norm:
            rec_id = params[0]
            for r in self._store.recommendations:
                if str(r["recommendation_id"]) == str(rec_id):
                    self._result = [
                        (
                            str(r["recommendation_id"]),
                            r["ticker"],
                            r["recommendation"],
                            r["conviction"],
                            r["date"],
                            r["audit_available"],
                            r["rule_engine_version"],
                            r["debate_prompt_version"],
                            r["model_id"],
                            r["model_version"],
                            r["parameters_version"],
                        )
                    ]
                    return
            self._result = []
            return
        if (
            "FROM audit_provenance" in sql_norm
            and "stage = %s" in sql_norm
        ):
            rec_id, stage = params
            rows = [
                r
                for r in self._store.provenance
                if str(r["recommendation_id"]) == str(rec_id) and r["stage"] == stage
            ]
            rows.sort(key=lambda r: r["created_at"])
            self._result = [
                (
                    str(r["audit_id"]),
                    str(r["recommendation_id"]),
                    r["stage"],
                    r["drill_payload"],
                    r["hmac_signature"],
                    str(r["parent_audit_id"]) if r["parent_audit_id"] else None,
                    r["versions"],
                    r["created_at"],
                )
                for r in rows[:1]
            ]
            return
        if (
            "FROM audit_provenance" in sql_norm
            and "SELECT stage, audit_id, drill_payload" in sql_norm
        ):
            # Top-level summary projection — only 3 columns.
            rec_id = params[0]
            rows = [
                r
                for r in self._store.provenance
                if str(r["recommendation_id"]) == str(rec_id)
            ]
            rows.sort(key=lambda r: r["created_at"])
            self._result = [
                (r["stage"], str(r["audit_id"]), r["drill_payload"])
                for r in rows
            ]
            return
        if "FROM audit_provenance" in sql_norm:
            rec_id = params[0]
            rows = [
                r
                for r in self._store.provenance
                if str(r["recommendation_id"]) == str(rec_id)
            ]
            rows.sort(key=lambda r: r["created_at"])
            self._result = [
                (
                    str(r["audit_id"]),
                    str(r["recommendation_id"]),
                    r["stage"],
                    r["drill_payload"],
                    r["hmac_signature"],
                    str(r["parent_audit_id"]) if r["parent_audit_id"] else None,
                    r["versions"],
                    r["created_at"],
                )
                for r in rows
            ]
            return
        self._result = []

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return list(self._result)

    def close(self) -> None:
        pass


class FakeStore:
    def __init__(self) -> None:
        self.recommendations: list[dict[str, Any]] = []
        self.provenance: list[dict[str, Any]] = []


class FakeConnection:
    def __init__(self, store: FakeStore) -> None:
        self._store = store

    def cursor(self) -> FakeCursor:
        return FakeCursor(self._store)

    def close(self) -> None:
        pass


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


REC_ID = UUID("8f2e1234-aaaa-bbbb-cccc-dddddddddddd")
PARAMS_ID = UUID("11111111-2222-3333-4444-555555555555")


def _make_versions() -> dict[str, Any]:
    return {
        "rule_engine_version": "v0.1.0",
        "debate_prompt_version": "v0.3.2",
        "model_id": "claude-opus-4-7",
        "model_version": "20260101",
        "parameters_version": str(PARAMS_ID),
    }


def _populate(store: FakeStore, *, hmac_key: bytes | None = None) -> list[StageRow]:
    """Seed the store with one recommendation + 5 stage rows; return chain rows."""
    store.recommendations.append(
        {
            "recommendation_id": REC_ID,
            "ticker": "AAPL",
            "recommendation": "BUY",
            "conviction": "HIGH",
            "date": date(2026, 4, 28),
            "audit_available": True,
            "rule_engine_version": "v0.1.0",
            "debate_prompt_version": "v0.3.2",
            "model_id": "claude-opus-4-7",
            "model_version": "20260101",
            "parameters_version": PARAMS_ID,
            "created_at": datetime(2026, 4, 28, 16, 30, tzinfo=timezone.utc),
        }
    )

    payloads = {
        "stage_1_mechanical": {
            "outcome": "B_MATCH",
            "score": 0.83,
            "rule_engine_version": "v0.1.0",
            "rules_applied": [
                {"id": "r_quality_high", "matched": True, "note": "ROIC > 15%"},
                {"id": "r_growth_consistent", "matched": True, "note": "5y rev CAGR"},
            ],
        },
        "stage_2_debate": {
            "consensus": "LONG",
            "dissenter": "BearAgent",
            "iterations": 3,
            "iteration_log": [
                {"agent": "Bull", "verdict": "LONG", "confidence": 0.78},
                {"agent": "Bear", "verdict": "HOLD", "confidence": 0.55},
                {"agent": "Judge", "verdict": "LONG", "confidence": 0.71},
            ],
            "verbatim_quotes": [
                "Net cash position of $51B grew QoQ.",
                "Services revenue mix +5pts YoY.",
            ],
        },
        "stage_3_kill_criteria": {
            "fired": [],
            "evaluation_chain": [
                {
                    "criterion": "FCF_margin < 10%",
                    "threshold": "10%",
                    "observed": "26%",
                    "fired": False,
                },
                {
                    "criterion": "covenant breach",
                    "threshold": "any",
                    "observed": "none",
                    "fired": False,
                },
            ],
        },
        "stage_4_counterfactual": {
            "top_3_archetype": [
                {"archetype": "MSFT-2017", "distance": 0.21, "outcome": "SURVIVOR"},
                {"archetype": "GOOG-2018", "distance": 0.27, "outcome": "SURVIVOR"},
                {"archetype": "IBM-2014", "distance": 0.34, "outcome": "NON-SURVIVOR"},
            ],
            "veto_status": "no_veto",
            "veto_rationale": "2/3 SURVIVOR matches; archetype distribution clears threshold.",
        },
        "materiality": {
            "classification": "M-1",
            "trigger": "scheduled_quarterly",
            "event_ref": None,
            "verbatim_quotes": [
                "Quarterly cadence trigger; no materiality-event.",
            ],
        },
    }

    parent: Optional[UUID] = None
    chain: list[StageRow] = []
    base_ts = datetime(2026, 4, 28, 16, 0, tzinfo=timezone.utc)
    for i, stage in enumerate(
        [
            "stage_1_mechanical",
            "stage_2_debate",
            "stage_3_kill_criteria",
            "stage_4_counterfactual",
            "materiality",
        ]
    ):
        audit_id = uuid4()
        created_at = datetime(2026, 4, 28, 16, i, tzinfo=timezone.utc)
        row = StageRow(
            audit_id=audit_id,
            recommendation_id=REC_ID,
            stage=stage,
            drill_payload=payloads[stage],
            hmac_signature="",  # filled in below if key provided
            parent_audit_id=parent,
            versions=_make_versions(),
            created_at=created_at,
        )
        if hmac_key is not None:
            sig = compute_signature(row, hmac_key)
        else:
            sig = "unsigned-placeholder"
        # rebuild with signature
        row = StageRow(
            audit_id=row.audit_id,
            recommendation_id=row.recommendation_id,
            stage=row.stage,
            drill_payload=row.drill_payload,
            hmac_signature=sig,
            parent_audit_id=row.parent_audit_id,
            versions=row.versions,
            created_at=row.created_at,
        )
        chain.append(row)
        store.provenance.append(
            {
                "audit_id": row.audit_id,
                "recommendation_id": row.recommendation_id,
                "stage": row.stage,
                "drill_payload": row.drill_payload,
                "hmac_signature": row.hmac_signature,
                "parent_audit_id": row.parent_audit_id,
                "versions": dict(row.versions),
                "created_at": row.created_at,
            }
        )
        parent = audit_id

    return chain


# -----------------------------------------------------------------------------
# Tests — loader + renderer
# -----------------------------------------------------------------------------


def test_top_level_summary_renders_all_stages():
    store = FakeStore()
    _populate(store)
    conn = FakeConnection(store)

    summary = get_audit_summary(conn, REC_ID)
    assert summary.ticker == "AAPL"
    assert summary.recommendation == "BUY"
    assert summary.conviction == "HIGH"
    assert summary.audit_available is True

    expected_stages = {
        "stage_1_mechanical",
        "stage_2_debate",
        "stage_3_kill_criteria",
        "stage_4_counterfactual",
        "materiality",
    }
    assert set(summary.decision_path.keys()) == expected_stages

    md = render_audit_summary(summary)
    assert "# Audit Trail — AAPL" in md
    assert "BUY" in md
    assert "/audit-trail" in md and "--stage stage_2_debate" in md
    # All five stages appear in the table.
    for stage in expected_stages:
        assert stage in md
    # Versions table.
    assert "rule_engine_version" in md and "v0.1.0" in md


def test_stage_drill_debate_renders_iterations_and_quotes():
    store = FakeStore()
    _populate(store)
    conn = FakeConnection(store)

    row = get_stage_drill(conn, REC_ID, "stage_2_debate")
    md = render_stage_drill("stage_2_debate", row)
    assert "Debate Consensus" in md
    assert "Bull" in md and "Bear" in md and "Judge" in md
    assert "Net cash position of $51B grew QoQ." in md


def test_stage_drill_counterfactual_renders_top3():
    store = FakeStore()
    _populate(store)
    conn = FakeConnection(store)

    row = get_stage_drill(conn, REC_ID, "stage_4_counterfactual")
    md = render_stage_drill("stage_4_counterfactual", row)
    assert "MSFT-2017" in md and "SURVIVOR" in md
    assert "no_veto" in md


def test_stage_drill_kill_criteria_renders_chain():
    store = FakeStore()
    _populate(store)
    conn = FakeConnection(store)

    row = get_stage_drill(conn, REC_ID, "stage_3_kill_criteria")
    md = render_stage_drill("stage_3_kill_criteria", row)
    assert "FCF_margin" in md
    assert "covenant breach" in md


def test_stage_drill_unknown_stage_raises():
    store = FakeStore()
    _populate(store)
    conn = FakeConnection(store)
    with pytest.raises(ValueError):
        get_stage_drill(conn, REC_ID, "stage_99_bogus")


def test_get_latest_for_ticker():
    store = FakeStore()
    _populate(store)
    conn = FakeConnection(store)
    rec_id = get_latest_for_ticker(conn, "AAPL")
    assert rec_id == REC_ID


def test_get_latest_for_ticker_missing():
    store = FakeStore()
    _populate(store)
    conn = FakeConnection(store)
    with pytest.raises(LookupError):
        get_latest_for_ticker(conn, "ZZZZ")


# -----------------------------------------------------------------------------
# Tests — HMAC verification
# -----------------------------------------------------------------------------


def test_hmac_chain_verifies_clean():
    key = b"test-key-not-for-prod"
    store = FakeStore()
    _populate(store, hmac_key=key)
    conn = FakeConnection(store)

    rows = get_chain_for_recommendation(conn, REC_ID)
    result = verify_chain(rows, key=key)
    assert result.mode == "keyed"
    assert result.all_ok, [r for r in result.rows if not r.ok]
    md = render_chain_verification(result)
    assert "OK" in md and "TAMPER-EVIDENT" not in md


def test_hmac_chain_detects_tamper():
    key = b"test-key-not-for-prod"
    store = FakeStore()
    _populate(store, hmac_key=key)

    # Tamper: rewrite drill_payload of stage 2 in place.
    for row in store.provenance:
        if row["stage"] == "stage_2_debate":
            row["drill_payload"] = {**row["drill_payload"], "consensus": "SHORT"}

    conn = FakeConnection(store)
    rows = get_chain_for_recommendation(conn, REC_ID)
    result = verify_chain(rows, key=key)
    assert not result.all_ok
    tampered_stages = {r.stage for r in result.tampered_rows}
    assert "stage_2_debate" in tampered_stages
    md = render_chain_verification(result)
    assert "TAMPER-EVIDENT" in md
    assert "M-2 system event" in md


def test_hmac_unkeyed_mode_marks_unverified(monkeypatch):
    # Isolate AUDIT_HMAC_KEY from the loaded .env so the test pins behaviour
    # under a genuinely-unkeyed environment regardless of operator config.
    monkeypatch.delenv("AUDIT_HMAC_KEY", raising=False)
    store = FakeStore()
    _populate(store)  # no key
    conn = FakeConnection(store)

    rows = get_chain_for_recommendation(conn, REC_ID)
    result = verify_chain(rows, key=None)  # explicit no-key, no env var either
    assert result.mode == "unkeyed"
    md = render_chain_verification(result)
    assert "UNVERIFIED" in md or "unkeyed" in md


def test_unkeyed_mode_surfaces_forged_parent_link_via_exit_code(monkeypatch):
    """Forged parent_audit_id (e.g., pointing to a LATER row in the chain) must
    surface as exit code 3 even in unkeyed mode. Previously the CLI short-
    circuited to exit 0 when mode=='unkeyed', masking parent-link tampering.
    """
    import io
    import sys
    from src.audit_trail import cli as audit_cli

    store = FakeStore()
    chain = _populate(store)  # no key → unkeyed mode

    # Tamper: rewrite stage_2_debate's parent to point to a LATER row's
    # audit_id (stage_4_counterfactual). This is detectable by parent-link
    # ordering check (parent.created_at > current.created_at → not OK).
    later_id = next(
        r["audit_id"]
        for r in store.provenance
        if r["stage"] == "stage_4_counterfactual"
    )
    for row in store.provenance:
        if row["stage"] == "stage_2_debate":
            row["parent_audit_id"] = later_id

    conn = FakeConnection(store)

    # Patch _open_connection to return our fake connection.
    monkeypatch.setattr(audit_cli, "_open_connection", lambda: conn)
    monkeypatch.delenv("AUDIT_HMAC_KEY", raising=False)

    # Capture stdout (the renderer prints there).
    captured = io.StringIO()
    monkeypatch.setattr(sys, "stdout", captured)

    exit_code = audit_cli.main([str(REC_ID), "--verify"])
    assert exit_code == 3, (
        "forged parent_audit_id pointing to a later row in unkeyed mode "
        "must surface as exit 3 (tamper-evident)"
    )


def test_strict_without_audit_hmac_key_returns_exit_5(monkeypatch):
    """`--verify --strict` with no AUDIT_HMAC_KEY must return exit 5
    (env/driver missing) instead of crashing with uncaught RuntimeError.
    """
    import io
    import sys
    from src.audit_trail import cli as audit_cli

    store = FakeStore()
    _populate(store)
    conn = FakeConnection(store)
    monkeypatch.setattr(audit_cli, "_open_connection", lambda: conn)
    monkeypatch.delenv("AUDIT_HMAC_KEY", raising=False)

    captured_err = io.StringIO()
    monkeypatch.setattr(sys, "stderr", captured_err)
    captured_out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", captured_out)

    exit_code = audit_cli.main([str(REC_ID), "--verify", "--strict"])
    assert exit_code == 5
    assert "AUDIT_HMAC_KEY" in captured_err.getvalue()


def test_canonical_payload_is_byte_stable():
    key = b"k"
    store = FakeStore()
    chain = _populate(store, hmac_key=key)
    # Re-canonicalize twice; bytes must match.
    p1 = canonical_payload(chain[0])
    p2 = canonical_payload(chain[0])
    assert p1 == p2
    # And signature is reproducible.
    assert compute_signature(chain[0], key) == chain[0].hmac_signature


# -----------------------------------------------------------------------------
# Tests — CLI argparse smoke
# -----------------------------------------------------------------------------


def test_cli_argparse_rec_id_only():
    from src.audit_trail.cli import _build_parser

    args = _build_parser().parse_args(
        ["8f2e1234-aaaa-bbbb-cccc-dddddddddddd"]
    )
    assert args.rec_id == "8f2e1234-aaaa-bbbb-cccc-dddddddddddd"
    assert args.stage is None
    assert args.latest is None
    assert args.verify is False


def test_cli_argparse_with_stage_and_verify():
    from src.audit_trail.cli import _build_parser

    args = _build_parser().parse_args(
        [
            "8f2e1234-aaaa-bbbb-cccc-dddddddddddd",
            "--stage",
            "stage_2_debate",
            "--verify",
            "--strict",
        ]
    )
    assert args.stage == "stage_2_debate"
    assert args.verify is True
    assert args.strict is True


def test_cli_argparse_latest_ticker():
    from src.audit_trail.cli import _build_parser

    args = _build_parser().parse_args(["--latest", "AAPL"])
    assert args.latest == "AAPL"
    assert args.rec_id is None


def test_cli_rejects_invalid_stage():
    from src.audit_trail.cli import _build_parser

    with pytest.raises(SystemExit):
        _build_parser().parse_args(["x", "--stage", "stage_99_invalid"])
