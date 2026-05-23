"""Smoke tests for the anchor_drift package (v3 Section 4.5 Q5).

Covers each channel + the orchestrator wiring. No DB writes; the
orchestrator is exercised with persist=False and a synthetic
``watchlist_row`` injected to keep tests hermetic.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import sys
from pathlib import Path

import pytest

# Ensure src/ is importable.
_SRC = Path(__file__).resolve().parents[3] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


@pytest.fixture(autouse=True)
def _hmac_secret(monkeypatch):
    monkeypatch.setenv("WATCHLIST_HMAC_SECRET", "test-secret-do-not-use")


# --------------------------------------------------------------------------- #
# hmac_verify                                                                 #
# --------------------------------------------------------------------------- #


def test_hmac_compute_and_verify_round_trip():
    from anchor_drift.hmac_verify import compute_hmac, verify_hmac

    payload = [{"pillar": "moat", "claim": "data flywheel", "confidence": 0.8}]
    sig = compute_hmac(payload)
    assert verify_hmac(payload, sig)
    assert not verify_hmac(payload + [{"pillar": "X", "claim": "y", "confidence": 0.5}], sig)
    assert not verify_hmac(payload, "deadbeef")


def test_hmac_canonical_json_is_stable():
    from anchor_drift.hmac_verify import canonical_json

    a = {"b": 1, "a": [3, 1, 2]}
    b = {"a": [3, 1, 2], "b": 1}
    assert canonical_json(a) == canonical_json(b)


def test_hmac_missing_secret(monkeypatch):
    from anchor_drift.hmac_verify import compute_hmac, HmacVerificationError

    monkeypatch.delenv("WATCHLIST_HMAC_SECRET", raising=False)
    with pytest.raises(HmacVerificationError):
        compute_hmac([{"x": 1}])


# --------------------------------------------------------------------------- #
# Channel 1 — pillar drift                                                    #
# --------------------------------------------------------------------------- #


class _FakeBlock:
    def __init__(self, text):
        self.text = text


class _FakeResp:
    def __init__(self, text):
        self.content = [_FakeBlock(text)]


class _FakeMessages:
    def __init__(self, text):
        self._text = text

    def create(self, **kwargs):
        return _FakeResp(self._text)


class _FakeClient:
    def __init__(self, text):
        self.messages = _FakeMessages(text)


def test_channel_1_no_drift_below_threshold():
    from anchor_drift.channel_1_pillar_drift import detect_pillar_drift
    from anchor_drift.hmac_verify import compute_hmac

    original = [
        {"pillar": "moat", "claim": "A", "confidence": 0.8},
        {"pillar": "growth", "claim": "B", "confidence": 0.7},
    ]
    sig = compute_hmac(original)
    diff_text = json.dumps({
        "pairs": [
            {"pillar": "moat", "classification": "unchanged", "confidence_delta": 0.0},
            {"pillar": "growth", "classification": "unchanged", "confidence_delta": 0.0},
        ]
    })
    res = detect_pillar_drift(
        ticker="NVDA",
        thesis_pillars_original=original,
        thesis_pillars_original_hmac=sig,
        current_pillars=original,
        client=_FakeClient(diff_text),
    )
    assert res.hmac_verified is True
    assert res.drift_score == 0.0
    assert res.triggered is False


def test_channel_1_triggers_when_score_exceeds_threshold():
    from anchor_drift.channel_1_pillar_drift import detect_pillar_drift
    from anchor_drift.hmac_verify import compute_hmac

    original = [
        {"pillar": "moat", "claim": "A", "confidence": 0.9},
        {"pillar": "growth", "claim": "B", "confidence": 0.7},
    ]
    sig = compute_hmac(original)
    # 1 softened (0.4 delta) + 1 rewritten => (0.4 + 1 + 1) / 2 = 1.2 > 0.25
    diff_text = json.dumps({
        "pairs": [
            {"pillar": "moat", "classification": "softened", "confidence_delta": -0.4},
            {"pillar": "growth", "classification": "rewritten", "confidence_delta": -0.1},
        ]
    })
    res = detect_pillar_drift(
        ticker="NVDA",
        thesis_pillars_original=original,
        thesis_pillars_original_hmac=sig,
        current_pillars=original,
        client=_FakeClient(diff_text),
    )
    assert res.triggered is True
    assert res.drift_score > 0.25
    assert "moat" in res.pillars_softened
    assert "growth" in res.pillars_rewritten


def test_channel_1_hmac_tamper_triggers():
    from anchor_drift.channel_1_pillar_drift import detect_pillar_drift

    original = [{"pillar": "moat", "claim": "A", "confidence": 0.9}]
    res = detect_pillar_drift(
        ticker="NVDA",
        thesis_pillars_original=original,
        thesis_pillars_original_hmac="0" * 64,  # bogus
        current_pillars=original,
        client=_FakeClient("{}"),
    )
    assert res.hmac_verified is False
    assert res.triggered is True
    assert res.error == "hmac_mismatch_or_tamper"


# --------------------------------------------------------------------------- #
# Channel 2 — outcome divergence                                              #
# --------------------------------------------------------------------------- #


def test_channel_2_within_threshold_no_trigger():
    from anchor_drift.channel_2_outcome_divergence import detect_outcome_divergence
    from anchor_drift.hmac_verify import compute_hmac

    proj = {"revenue": 100.0, "gross_margin": 0.40, "fcf": 25.0}
    sig = compute_hmac(proj)
    # actuals all within 10%
    actuals = {
        "revenue": 105.0,
        "gross_margin": 0.42,
        "fcf": 24.0,
        "last_earnings_date": "2026-01-31",
    }
    res = detect_outcome_divergence(
        ticker="NVDA",
        scenario_A_base_projections=proj,
        scenario_A_base_projections_hmac=sig,
        fundamentals_fn=lambda ticker: actuals,
    )
    assert res.triggered is False
    assert res.breached_metrics == []


def test_channel_2_revenue_breach_triggers():
    from anchor_drift.channel_2_outcome_divergence import detect_outcome_divergence
    from anchor_drift.hmac_verify import compute_hmac

    proj = {"revenue": 100.0, "gross_margin": 0.40, "fcf": 25.0}
    sig = compute_hmac(proj)
    actuals = {
        "revenue": 70.0,  # 30% deviation
        "gross_margin": 0.40,
        "fcf": 25.0,
        "last_earnings_date": "2026-01-31",
    }
    res = detect_outcome_divergence(
        ticker="NVDA",
        scenario_A_base_projections=proj,
        scenario_A_base_projections_hmac=sig,
        fundamentals_fn=lambda ticker: actuals,
    )
    assert res.triggered is True
    assert "revenue" in res.breached_metrics
    assert res.deviations["revenue"] == pytest.approx(0.30)


def test_channel_2_no_actuals_no_trigger():
    from anchor_drift.channel_2_outcome_divergence import detect_outcome_divergence
    from anchor_drift.hmac_verify import compute_hmac

    proj = {"revenue": 100.0, "gross_margin": 0.40, "fcf": 25.0}
    sig = compute_hmac(proj)
    res = detect_outcome_divergence(
        ticker="NVDA",
        scenario_A_base_projections=proj,
        scenario_A_base_projections_hmac=sig,
        fundamentals_fn=lambda ticker: {},
    )
    assert res.triggered is False
    assert res.error == "no_actuals"


# --------------------------------------------------------------------------- #
# Channel 3 — periodic re-read                                                #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "mode,days_old,expected",
    [
        ("B", 90, False),
        ("B", 180, True),
        ("B_prime", 119, False),
        ("B_prime", 121, True),
        ("C", 59, False),
        ("C", 60, True),
    ],
)
def test_channel_3_threshold_per_mode(mode, days_old, expected):
    from anchor_drift.channel_3_periodic_reread import detect_periodic_reread

    today = _dt.date(2026, 4, 29)
    last = today - _dt.timedelta(days=days_old)
    res = detect_periodic_reread(
        ticker="NVDA",
        mode=mode,
        last_reread_date=last,
        as_of=today.isoformat(),
    )
    assert res.triggered is expected


# --------------------------------------------------------------------------- #
# Orchestrator                                                                #
# --------------------------------------------------------------------------- #


def test_orchestrator_or_logic_no_persist():
    from anchor_drift.hmac_verify import compute_hmac
    from anchor_drift.orchestrator import run_anchor_drift_check

    pillars = [{"pillar": "moat", "claim": "A", "confidence": 0.9}]
    proj = {"revenue": 100.0, "gross_margin": 0.40, "fcf": 25.0}
    pillar_sig = compute_hmac(pillars)
    proj_sig = compute_hmac(proj)
    today = _dt.date(2026, 4, 29)
    # Mode C, last reread 90 days ago -> Channel 3 triggers (60d threshold).
    last_reread = today - _dt.timedelta(days=90)

    diff_text = json.dumps({"pairs": [
        {"pillar": "moat", "classification": "unchanged", "confidence_delta": 0.0}
    ]})
    actuals = {
        "revenue": 102.0, "gross_margin": 0.40, "fcf": 25.0,
        "last_earnings_date": "2026-01-31",
    }

    outcome = run_anchor_drift_check(
        ticker="NVDA",
        current_pillars=pillars,
        as_of=today.isoformat(),
        persist=False,
        llm_client=_FakeClient(diff_text),
        fundamentals_fn=lambda t: actuals,
        watchlist_row={
            "mode": "C",
            "thesis_pillars_original": pillars,
            "thesis_pillars_original_hmac": pillar_sig,
            "scenario_A_base_projections": proj,
            "scenario_A_base_projections_hmac": proj_sig,
            "added_at": last_reread,
            "last_reunderwritten_at": last_reread,
            "last_acknowledged_reread": last_reread,
            "parameters_version": None,
        },
    )
    assert outcome.any_triggered is True
    assert "periodic_reread" in outcome.triggered_channels
    assert outcome.forced_review is not None
    assert outcome.forced_review["operator_decision"] == "pending"


def test_orchestrator_clean_no_trigger():
    from anchor_drift.hmac_verify import compute_hmac
    from anchor_drift.orchestrator import run_anchor_drift_check

    pillars = [{"pillar": "moat", "claim": "A", "confidence": 0.9}]
    proj = {"revenue": 100.0, "gross_margin": 0.40, "fcf": 25.0}
    pillar_sig = compute_hmac(pillars)
    proj_sig = compute_hmac(proj)
    today = _dt.date(2026, 4, 29)
    last_reread = today - _dt.timedelta(days=10)

    diff_text = json.dumps({"pairs": [
        {"pillar": "moat", "classification": "unchanged", "confidence_delta": 0.0}
    ]})
    actuals = {
        "revenue": 100.0, "gross_margin": 0.40, "fcf": 25.0,
        "last_earnings_date": "2026-01-31",
    }
    outcome = run_anchor_drift_check(
        ticker="NVDA",
        current_pillars=pillars,
        as_of=today.isoformat(),
        persist=False,
        llm_client=_FakeClient(diff_text),
        fundamentals_fn=lambda t: actuals,
        watchlist_row={
            "mode": "B",
            "thesis_pillars_original": pillars,
            "thesis_pillars_original_hmac": pillar_sig,
            "scenario_A_base_projections": proj,
            "scenario_A_base_projections_hmac": proj_sig,
            "added_at": last_reread,
            "last_reunderwritten_at": last_reread,
            "last_acknowledged_reread": last_reread,
            "parameters_version": None,
        },
    )
    assert outcome.any_triggered is False
    assert outcome.forced_review is None


# --------------------------------------------------------------------------- #
# Idempotency regression tests (idempotency audit, migration 010 UNIQUE)      #
# --------------------------------------------------------------------------- #


def test_anchor_drift_persist_uses_on_conflict_clause():
    """Migration 010 declares UNIQUE(ticker, check_date) on
    anchor_drift_checks. The orchestrator's _persist must use ON CONFLICT
    (ticker, check_date) DO NOTHING so a Channel-1 retry on the same M-2
    event (e.g., crash + cron retry the same day) becomes a silent no-op
    instead of raising UniqueViolation.

    Bug class found by the idempotency audit: prior to this fix, a retry
    on the same day would crash the orchestrator and leave the operator
    with an opaque system_error.
    """
    import inspect
    from anchor_drift.orchestrator import _persist

    src = inspect.getsource(_persist)
    assert "ON CONFLICT (ticker, check_date)" in src, (
        "anchor_drift._persist must use ON CONFLICT (ticker, check_date) "
        "DO NOTHING per migration 010 UNIQUE constraint"
    )
    assert "DO NOTHING" in src
    # On conflict, the function MUST re-fetch the prior row's check_id so
    # the caller has a stable handle (the audit chain references the
    # check_id; returning a fresh-but-uninserted UUID would break it).
    assert "SELECT check_id FROM anchor_drift_checks" in src, (
        "anchor_drift._persist must re-fetch the prior check_id on conflict"
    )
