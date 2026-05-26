"""Cross-module HMAC integration test.

Validates the canonical HMAC scheme is shared by every signer in the system:

  1. p3_mechanical_scorer signs an audit row → audit_trail.verify_chain validates.
  2. peak_pain_catalog signs a row → verify_hmac matches the same canonical bytes.
  3. watchlist HMAC producer signs pillars → anchor_drift verifier validates.
  4. Non-ASCII (Greek + em-dash) round-trips identically (catches ensure_ascii=True).
  5. Decimal columns (psycopg NUMERIC → Decimal) round-trip identically.

Per remediation requirement: "every audit/HMAC row written by any module
verifies cleanly under the canonical scheme."
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import replace
from datetime import timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from src.audit_trail import (
    canonical_payload_dict,
    compute_signature_dict,
    verify_chain,
)
from src.audit_trail.hmac_verify import compute_signature
from src.audit_trail.loader import StageRow


# ---------------------------------------------------------------------------
# 1. p3 emitter -> audit_trail verifier
# ---------------------------------------------------------------------------


def test_p3_audit_row_verifies_under_audit_trail(monkeypatch: pytest.MonkeyPatch) -> None:
    """A row signed by p3 (after stitching) must verify under verify_chain."""
    monkeypatch.setenv("AUDIT_HMAC_KEY", "shared-audit-secret")
    from src.p3_mechanical_scorer.orchestrator import _build_audit_row, _sign_row_payload

    rec_id = uuid4()
    now = _dt.datetime(2026, 4, 29, 12, 0, tzinfo=timezone.utc)
    row_dict = _build_audit_row(
        recommendation_id=rec_id,
        stage="stage_1_mechanical",
        substage="stage_1a",
        payload={"outcome": "PROCEED", "score": 0.85},
        parent_audit_id=None,
        versions={"rule_engine_version": "v0.1.0"},
        created_at=now,
    )
    # Recreate as StageRow so verify_chain can ingest it
    stage_row = StageRow(
        audit_id=UUID(row_dict["audit_id"]),
        recommendation_id=rec_id,
        stage=row_dict["stage"],
        drill_payload=row_dict["drill_payload"],
        hmac_signature=row_dict["hmac_signature"],
        parent_audit_id=None,
        versions=row_dict["versions"],
        created_at=now,
    )
    result = verify_chain([stage_row], key=b"shared-audit-secret")
    assert result.mode == "keyed"
    assert result.all_ok, [r for r in result.rows if not r.ok]


def test_p3_unicode_drill_payload_round_trips(monkeypatch: pytest.MonkeyPatch) -> None:
    """Greek letter + em-dash in drill_payload must verify (ensure_ascii=False)."""
    monkeypatch.setenv("AUDIT_HMAC_KEY", "shared-audit-secret")
    from src.p3_mechanical_scorer.orchestrator import _build_audit_row

    rec_id = uuid4()
    now = _dt.datetime(2026, 4, 29, 12, 0, tzinfo=timezone.utc)
    row_dict = _build_audit_row(
        recommendation_id=rec_id,
        stage="stage_1_mechanical",
        substage="stage_2_llm_rubric",
        payload={"verbatim": "α-measured per-share — em-dash; δ-Δ"},
        parent_audit_id=None,
        versions={"rule_engine_version": "v0.1.0"},
        created_at=now,
    )
    stage_row = StageRow(
        audit_id=UUID(row_dict["audit_id"]),
        recommendation_id=rec_id,
        stage=row_dict["stage"],
        drill_payload=row_dict["drill_payload"],
        hmac_signature=row_dict["hmac_signature"],
        parent_audit_id=None,
        versions=row_dict["versions"],
        created_at=now,
    )
    result = verify_chain([stage_row], key=b"shared-audit-secret")
    assert result.all_ok


# ---------------------------------------------------------------------------
# Section 2 (peak_pain_catalog round-trip): tests removed 2026-05-23 with
# src/peak_pain_catalog/ deletion (mig 041) per docs/superpowers/specs/
# 2026-05-23-eval-loop-deletion-design.md.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 3. watchlist producer -> anchor_drift verifier
# ---------------------------------------------------------------------------


def test_watchlist_producer_to_anchor_drift_verifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WATCHLIST_HMAC_SECRET", "shared-watchlist-secret")
    from src.anchor_drift.hmac_verify import (
        verify_pillars_hmac,
        verify_scenario_hmac,
    )
    from src.watchlist.hmac_producer import sign_watchlist_row

    pillars = [
        {"pillar": "moat", "evidence": "10K disclosure"},
        {"pillar": "founder", "evidence": "since 1976"},
    ]
    scenario = {"revenue_5y_cagr": 0.12, "wacc": 0.085}
    sigs = sign_watchlist_row(pillars, scenario)
    assert verify_pillars_hmac(pillars, sigs["thesis_pillars_original_hmac"])
    assert verify_scenario_hmac(
        scenario, sigs["scenario_A_base_projections_hmac"]
    )


# ---------------------------------------------------------------------------
# 4. Non-ASCII char (Greek + em-dash) round-trip across all canonicalizers
# ---------------------------------------------------------------------------


def test_canonical_payload_dict_unicode_byte_stable() -> None:
    """ensure_ascii=False must be byte-identical across emitter and verifier."""
    payload = {
        "greek": "α-Δ",
        "em_dash": "—",
        "mix": "alpha α — measured per-share",
    }
    b1 = canonical_payload_dict(payload)
    b2 = canonical_payload_dict(payload)
    assert b1 == b2
    # Non-ASCII bytes are emitted directly (not \uXXXX escaped):
    assert "α".encode("utf-8") in b1
    assert "—".encode("utf-8") in b1


# ---------------------------------------------------------------------------
# 5. Decimal columns round-trip
# ---------------------------------------------------------------------------


def test_canonical_payload_dict_decimal_byte_stable() -> None:
    """Decimal must serialize via str() preserving full precision."""
    payload = {
        "wacc": Decimal("0.0850"),
        "cagr": Decimal("0.123456789"),
        "neg": Decimal("-0.5000"),
    }
    b1 = canonical_payload_dict(payload)
    b2 = canonical_payload_dict(payload)
    assert b1 == b2
    # Trailing zeros preserved (Decimal('0.0850') -> "0.0850" not "0.085"):
    assert b'"0.0850"' in b1
    # Full precision:
    assert b'"0.123456789"' in b1


def test_signature_with_decimal_round_trips() -> None:
    payload = {
        "wacc": Decimal("0.0850"),
        "ticker": "AAPL",
    }
    sig1 = compute_signature_dict(payload, b"k")
    sig2 = compute_signature_dict(payload, b"k")
    assert sig1 == sig2
    # Different precision Decimal -> different bytes -> different signature:
    payload2 = {"wacc": Decimal("0.085"), "ticker": "AAPL"}
    sig3 = compute_signature_dict(payload2, b"k")
    assert sig1 != sig3, (
        "Decimal('0.0850') and Decimal('0.085') should sign differently — "
        "str() preserves trailing zeros"
    )


# ---------------------------------------------------------------------------
# 6. Premortem signer round-trip via dedicated module wrapper
# ---------------------------------------------------------------------------


def test_premortem_hmac_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PREMORTEM_HMAC_SECRET", "premortem-secret")
    from src.premortem_scheduler.hmac import (
        compute_premortem_hmac,
        verify_premortem_hmac,
    )

    payload = {
        "failure_modes": [
            {"mode": "demand_reversal", "probability_estimate": 0.2},
        ],
        "pillars_revisited": [
            {"pillar": "moat", "still_holds": True},
        ],
    }
    sig = compute_premortem_hmac(payload)
    assert sig is not None
    assert verify_premortem_hmac(payload, sig)
    # Tamper -> fail
    tampered = {**payload, "failure_modes": []}
    assert not verify_premortem_hmac(tampered, sig)


# ---------------------------------------------------------------------------
# 7. JSONB round-trip type-coercion regression tests
#
# These tests cover the audit-time vs verify-time canonical-bytes parity for
# JSONB-stored fields. Bug pattern: signing serializes via `_json_default`
# (datetime -> ISO8601, UUID -> str, Decimal -> str), but the JSONB write
# previously used `json.dumps(..., default=str)` which yields Python's
# `str(datetime)` form ("2026-04-29 12:00:00", space, no Z) — which then
# round-trips through Postgres JSONB and produces a different canonical-byte
# form at verify time.
#
# Fix: persist callsites use the same `_json_default` as signing so the
# Postgres JSONB string representation is byte-identical to the signed
# canonical bytes for every supported type.
# ---------------------------------------------------------------------------


def test_p7_audit_chain_drill_payload_with_datetime_round_trips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """p7 audit_chain row with datetime in drill_payload: sign-time and
    persist-time JSONB encoding must produce byte-identical canonical bytes
    so verify_chain validates after DB round-trip.

    Regression: pre-fix, _persist used json.dumps(default=str) which converts
    datetime via str() -> "2026-04-29 12:00:00" (no T separator, no Z), but
    canonical_payload_dict uses _json_default -> "2026-04-29T12:00:00Z".
    """
    from src.audit_trail.hmac_verify import _json_default

    naive = _dt.datetime(2026, 4, 29, 12, 0, 0)
    drill_payload = {"event_at": naive, "score": Decimal("0.85")}

    # SIGN-time (canonical):
    sign_bytes = canonical_payload_dict({"drill_payload": drill_payload})

    # PERSIST-time using fixed default=_json_default:
    persist_str = json.dumps(drill_payload, default=_json_default)

    # Postgres JSONB returns dict via psycopg2 (or json.loads of TEXT-cast).
    roundtrip_payload = json.loads(persist_str)

    verify_bytes = canonical_payload_dict({"drill_payload": roundtrip_payload})

    assert sign_bytes == verify_bytes, (
        f"sign vs verify byte mismatch:\n  sign:   {sign_bytes!r}\n  verify: {verify_bytes!r}"
    )


def test_p7_audit_chain_drill_payload_with_uuid_round_trips() -> None:
    """UUID inside JSONB drill_payload must round-trip identically."""
    from src.audit_trail.hmac_verify import _json_default

    inner_uuid = uuid4()
    drill_payload = {"materiality_event_ref": inner_uuid}

    sign_bytes = canonical_payload_dict({"drill_payload": drill_payload})
    persist_str = json.dumps(drill_payload, default=_json_default)
    roundtrip = json.loads(persist_str)
    verify_bytes = canonical_payload_dict({"drill_payload": roundtrip})

    assert sign_bytes == verify_bytes


def test_p7_audit_chain_drill_payload_with_decimal_round_trips() -> None:
    """Decimal inside JSONB drill_payload must round-trip identically.

    Sign-time _json_default -> JSON string '"0.085"'. Persist-time same.
    DB JSONB stores quoted string, returns str on readback. Re-sign as JSON
    string (no Decimal in roundtrip dict) -> same bytes.
    """
    from src.audit_trail.hmac_verify import _json_default

    drill_payload = {"wacc": Decimal("0.0850"), "cagr": Decimal("0.123456789")}

    sign_bytes = canonical_payload_dict({"drill_payload": drill_payload})
    persist_str = json.dumps(drill_payload, default=_json_default)
    roundtrip = json.loads(persist_str)
    verify_bytes = canonical_payload_dict({"drill_payload": roundtrip})

    assert sign_bytes == verify_bytes


def test_premortem_failure_modes_with_datetime_round_trips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Premortem JSONB persist must use _json_default so datetime-bearing
    operator entries round-trip cleanly through Postgres JSONB.

    Regression: pre-fix, recorder.py used json.dumps(default=str) for
    operator_imagined_failure_modes / thesis_pillars_revisited / metadata,
    which produced Python str(datetime) — incompatible with the canonical
    sign-time _json_default ISO8601 form.
    """
    from src.audit_trail.hmac_verify import _json_default

    naive = _dt.datetime(2026, 4, 29, 12, 0, 0)
    failure_modes = [
        {
            "mode": "demand_reversal",
            "probability_estimate": 0.2,
            "added_at": naive,
        },
    ]
    pillars = [
        {"pillar": "moat", "last_reviewed": _dt.date(2026, 4, 29)},
    ]

    # Sign-time:
    sign_bytes = canonical_payload_dict(
        {"failure_modes": failure_modes, "pillars_revisited": pillars}
    )

    # Persist-time using the fixed default=_json_default:
    persist_fm = json.dumps(failure_modes, default=_json_default)
    persist_pillars = json.dumps(pillars, default=_json_default)

    # DB round-trip:
    roundtrip_fm = json.loads(persist_fm)
    roundtrip_pillars = json.loads(persist_pillars)

    verify_bytes = canonical_payload_dict(
        {"failure_modes": roundtrip_fm, "pillars_revisited": roundtrip_pillars}
    )

    assert sign_bytes == verify_bytes


def test_p7_emitter_persist_uses_json_default_not_str() -> None:
    """Direct check on the fixed persist callsite: no `default=str` remains.

    Sentinel test that catches regression if a future change re-introduces
    `default=str` in the JSONB serialization path.
    """
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "src" / "p7_recommendation_emitter" / "emitter.py"
    text = src.read_text()
    # The fix: every json.dumps for JSONB-bound fields uses _json_default.
    assert "default=_json_default" in text
    # And no leftover default=str:
    assert "default=str" not in text, (
        "p7 emitter still has a json.dumps(default=str) call — datetime/UUID/Decimal "
        "in JSONB payloads will sign differently than the persisted form, breaking "
        "HMAC verification after DB round-trip."
    )


def test_premortem_recorder_persist_uses_json_default_not_str() -> None:
    """Direct check on the fixed persist callsite: no `default=str` remains."""
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "src" / "premortem_scheduler" / "recorder.py"
    text = src.read_text()
    assert "default=_json_default" in text
    assert "default=str" not in text, (
        "premortem recorder still has a json.dumps(default=str) call — JSONB "
        "round-trip will not match canonical sign-time bytes."
    )
