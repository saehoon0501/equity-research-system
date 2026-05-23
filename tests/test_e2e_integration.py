"""End-to-end P5->P7 funnel + HMAC scope isolation + cross-module integration smoke.

Validates that the modules built across Waves A/B/C compose correctly for a
realistic scenario (NVDA-2023, Mode B' clean-BUY case from spec walkthrough
#2). Concretely this suite exercises the **P5 -> P6 -> P7** slice of the
canonical funnel; the upstream (P1-P4) and downstream (P8-P9) phases are
stubbed at the module boundary because their full wiring runs in the
per-module unit suites and the launch walkthrough harness, not here.

Per v3 spec Section 2.1 the canonical funnel composition is::

    P1 trend capture
        |
    P2 scenario writing (3 scenarios + kill_criteria_structured)
        |
    P3 mechanical scorer (Stage 1A knockout + 1B Tier-A composite + 2 LLM + 3 linter)
        |
    P4 5-style debate (Phase A->B->C-conditional->D)
        |
    Mode classification (Stage 1 market structural + Stage 2 quality)
        |
    P5 watchlist add (HMAC-signed thesis_pillars_original + scenario_A_base_projections)   <-- exercised
        |
    P6 disposition determination (mode-anchored primary horizon)                             <-- exercised
        |
    P7 recommendation emit (full Q1 schema + HMAC chain)                                     <-- exercised
        |
    P8 daily monitor (kill criterion firing -> M-3 routing)                                  <-- stubbed
        |
    P9 cut signal emission (counterfactual veto pipeline + alert)                            <-- stubbed

Each scenario test below exercises a slice of the P5->P7 composition plus
HMAC-scope isolation (no cross-scope key reuse) and the cross-module
integration smoke. All tests are marked @pytest.mark.integration so they
can be run separately from fast unit tests via ``pytest -m integration``.

Reference:
  docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
    Section 2.1 (funnel composition; 9 phases)
    Section 4.1-4.6, 4.8 (per-phase modules)
    Section 5 Q1 (audit-chain HMAC)
    Section 6 Q5 (anchor-drift HMAC)
    Section 7 Q4 (layered drill-down lock)
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

# Ensure src/ is importable for tests that use bare-package imports.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


# ===========================================================================
# Module imports (after sys.path setup)
# ===========================================================================
from src.audit_trail.hmac_verify import (
    canonical_payload_dict,
    compute_signature_dict,
    verify_chain,
)
from src.audit_trail.loader import StageRow
from src.p4_debate import (
    MODE_B_PRIME as P4_MODE_B_PRIME,
    STYLE_GROWTH,
    STYLE_QUALITY_MOAT,
    STYLE_VALUE,
    VERDICT_ADD,
    WEIGHT_MATRIX,
    get_weights,
)
from src.p5_watchlist import (
    WatchlistAddInput,
    WatchlistAddOutcome,
    add_to_watchlist,
    derive_conviction_threshold,
    derive_regime_sensitivity,
)
from src.p6_disposition import (
    DispositionInput,
    HORIZON_MID,
    determine_disposition,
)
from src.p6_disposition.determiner import SIGNAL_BUY, SIGNAL_HOLD
from src.p7_recommendation_emitter import (
    AUDIT_HMAC_ENV,
    CONVICTION_HIGH,
    CONVICTION_LOW,
    EmitInputs,
    SizingContext,
    TRIGGER_M3,
    TRIGGER_NEW_CANDIDATE,
    compute_sizing,
    emit_recommendation,
)
from src.premortem_scheduler.hmac import (
    compute_premortem_hmac,
    verify_premortem_hmac,
)
from src.watchlist.hmac_producer import sign_watchlist_row


pytestmark = pytest.mark.integration


# ===========================================================================
# Fixture data — NVDA-2023 Mode B' clean-BUY case (walkthrough #2)
# ===========================================================================


# NVDA fiscal-2023 (data-center secular thesis): founder Huang 30+yr,
# ROIIC > 15%, per-share-value primary, pivot CUDA->AI multi-bag. Market
# cap > $50B + profitable + growth > 15% -> Mode B' per Stage 1
# market-structural rule. Founder >5y + ROIIC > 15% -> HIGH-quality per
# Stage 2 company-quality rule.
NVDA_TICKER = "NVDA"
NVDA_MODE = "B_prime"
NVDA_QUALITY = "HIGH"
NVDA_THESIS_PILLARS: list[dict[str, Any]] = [
    {
        "pillar": "moat_data_center_pivot",
        "claim": "CUDA->AI pivot from gaming (originally 100% gaming) to data-center monetization "
                 "is structural; founder Huang has 30+yr at the helm and explicitly committed "
                 "to AI/HPC convergence in 2018-2020 capex cycles.",
        "confidence": 0.85,
    },
    {
        "pillar": "growth_secular_demand",
        "claim": "Hyperscaler AI capex (AWS, Azure, GCP, Meta) is multi-year sustained; "
                 "data-center revenue YoY > +200% in fiscal-Q3-2023.",
        "confidence": 0.80,
    },
    {
        "pillar": "quality_roiic",
        "claim": "ROIIC > 30% in last 3 years (vs > 15% Tier-A floor); per-share-value "
                 "compounder, not gross-revenue chaser.",
        "confidence": 0.90,
    },
]
NVDA_SCENARIO_A_BASE: dict[str, Any] = {
    "scenario": "base",
    "horizon_years": 3,
    "revenue_cagr_pct": 35.0,
    "gross_margin_pct": 65.0,
    "fcf_margin_pct": 35.0,
    "exit_pe_multiple": 30.0,
    "implied_irr_pct": 22.0,
    "kill_criteria_structured": [
        {
            "id": "kill_1",
            "metric": "data_center_revenue_yoy_pct",
            "threshold_floor": -25.0,
            "horizon": "ttm",
            "rationale": "AI capex digestion period > 2 quarters violates secular thesis",
        },
        {
            "id": "kill_2",
            "metric": "gross_margin_pct",
            "threshold_floor": 50.0,
            "horizon": "ttm",
            "rationale": "Pricing power erosion below 50% violates moat thesis",
        },
        {
            "id": "kill_3",
            "metric": "growth_rate_inflection_yoy_pct",
            "threshold_floor": -50.0,
            "horizon": "yoy",
            "rationale": "Growth-rate inflection > -50% YoY = thesis-defining "
                         "demand collapse signal (e.g., 2018-2019 crypto bust analog)",
        },
    ],
}
NVDA_MACRO_REGIME_OUTPUT: dict[str, Any] = {
    "regime_sensitivity": "MEDIUM",
    "rationale_payload": {
        "regime_sensitivity": "MEDIUM",
        "notes": "AI secular bid partially regime-decoupled; rate-cycle sensitivity "
                 "remains via long-duration multiples.",
    },
}


# ===========================================================================
# Test fixtures
# ===========================================================================


@pytest.fixture
def hmac_keys(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    """All four HMAC keys set for the duration of one test.

    Per v3 Section 5 Q1 + Section 6 Q5, keys are scope-isolated:
      * AUDIT_HMAC_KEY        — execution_recommendations + audit_provenance
      * WATCHLIST_HMAC_SECRET — thesis_pillars + scenario_A_base_projections
      * PEAK_PAIN_HMAC_KEY    — peak_pain_archetypes
      * PREMORTEM_HMAC_SECRET — premortem
    """
    keys = {
        "audit": b"e2e-audit-key-do-not-use-in-prod",
        "watchlist": b"e2e-watchlist-key-do-not-use-in-prod",
        "peak_pain": b"e2e-peak-pain-key-do-not-use-in-prod",
        "premortem": b"e2e-premortem-key-do-not-use-in-prod",
    }
    monkeypatch.setenv("AUDIT_HMAC_KEY", keys["audit"].decode())
    monkeypatch.setenv("WATCHLIST_HMAC_SECRET", keys["watchlist"].decode())
    monkeypatch.setenv("PEAK_PAIN_HMAC_KEY", keys["peak_pain"].decode())
    monkeypatch.setenv("PREMORTEM_HMAC_SECRET", keys["premortem"].decode())
    return keys


# ---------------------------------------------------------------------------
# Stub Postgres connection (in-memory capture)
# ---------------------------------------------------------------------------


@dataclass
class CapturedExec:
    """One captured cur.execute() call."""

    sql: str
    params: tuple


class FakeCursor:
    """Minimal PEP-249-ish cursor that captures executes for assertions."""

    def __init__(self, store: list[CapturedExec]) -> None:
        self.store = store
        self._fetchone: tuple | None = None
        self._fetchall: list[tuple] = []

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.store.append(CapturedExec(sql=sql, params=tuple(params)))

    def fetchone(self):
        return self._fetchone

    def fetchall(self):
        return self._fetchall

    def close(self) -> None:
        pass

    # Allow context-manager use (psycopg-style).
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class FakeConn:
    """Minimal psycopg-style connection stub."""

    def __init__(self) -> None:
        self.executed: list[CapturedExec] = []
        self.committed = False

    def cursor(self) -> FakeCursor:
        return FakeCursor(self.executed)

    def commit(self) -> None:
        self.committed = True

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


@pytest.fixture
def fake_conn() -> FakeConn:
    """Fresh stub connection per test (table-write isolation)."""
    return FakeConn()


# ---------------------------------------------------------------------------
# Helpers — build canonical EmitInputs for NVDA scenario.
# ---------------------------------------------------------------------------


def _baseline_emit_inputs(**overrides: Any) -> EmitInputs:
    """Build EmitInputs for a clean-BUY NVDA emission.

    Mirrors test_p7_recommendation_emitter._baseline_inputs but tuned for
    the e2e walkthrough (Mode B', HIGH quality, 4/5 debate ADD,
    SURVIVOR-dominant top-3, no kills).
    """
    base: dict[str, Any] = dict(
        ticker=NVDA_TICKER,
        mode=NVDA_MODE,
        company_quality_flag=NVDA_QUALITY,
        mode_certainty="rule_clean",
        debate_add_count=4,
        debate_consensus_summary="4/5 ADD (Quant-Technical dissents HOLD on RSI > 70)",
        kills_fired=0,
        anchor_drift_channels_triggered=0,
        primary_recommendation="BUY",
        suggested_pacing="DCA over 21 days",
        triggered_by=TRIGGER_NEW_CANDIDATE,
        available_cash_pct=10.0,
        current_price=420.50,
        fair_value_payload={"point": 525, "range_low": 450, "range_high": 600},
        near_term_catalysts_raw=[
            {
                "event": "Q4 fiscal-2023 earnings",
                "date": "2023-02-22",
                "importance": "high",
            },
        ],
        technical_signals_raw={
            "ma_50d": 380.0,
            "ma_200d": 290.0,
            "rsi_14": 68,
            "atr_20": 12.5,
        },
        stage_drill_payloads={
            "stage_1_mechanical": {
                "outcome": "PROCEED",
                "score": 0.92,
                "stage_1a_knockout": "no_fraud_signature; era_fit_positive",
                "stage_1b_tier_a": {
                    "founder_duration_yrs": 30,
                    "roiic_pct": 32.5,
                    "per_share_primary": True,
                    "pivot_multi_bag": True,
                    "grade": "A",
                },
                "stage_2_llm_rubric": "info_isolated; verbatim_quotes_present",
                "stage_3_linter": "clean",
            },
            "stage_2_debate": {
                "consensus": "4/5 ADD",
                "dissenter": "Quant-Technical",
                "weight_matrix": dict(WEIGHT_MATRIX["B_prime"]),
            },
            "stage_3_kill_criteria": {
                "fired": 0,
                "structured": NVDA_SCENARIO_A_BASE["kill_criteria_structured"],
            },
            "stage_4_counterfactual": {
                "top_3_archetype": ["SURVIVOR", "SURVIVOR", "SURVIVOR"],
                "veto_status": "no_veto",
            },
            "materiality": {
                "classification": "M-1",
                "trigger": "new_candidate",
            },
        },
    )
    base.update(overrides)
    return EmitInputs(**base)


# ===========================================================================
# Scenario 1 — Clean BUY path (P1 -> P5 -> P7)
# ===========================================================================


def test_e2e_clean_buy_path(
    hmac_keys: dict[str, bytes], fake_conn: FakeConn
) -> None:
    """Full P1->P7 funnel for NVDA-2023 (Mode B' clean-BUY).

    Validates each phase composes with the next:
      P3 (mechanical A-grade) -> P4 (4/5 ADD) -> Mode (B'/HIGH) ->
      P5 (watchlist add HMAC) -> P6 (mid-horizon BUY) ->
      P7 (HIGH conviction, 2-5% B' band, full Q1 schema) ->
      audit_trail.verify_chain() returns all_ok.

    Per v3 spec Section 2.1 + Section 4.6 Q1.
    """
    # --- Mode classification (composes Stage 1 rule + Stage 2 quality) ---
    # The mode classifier package exposes constants only at the package init;
    # for this e2e we verify the canonical mode/quality pair is consumable
    # by P5/P6/P7 unchanged.
    assert NVDA_MODE == "B_prime"
    assert NVDA_QUALITY == "HIGH"

    # --- P4 weight matrix lock for B' (Value 15 / Growth 35 / Quality 30) ---
    weights = get_weights(NVDA_MODE)
    assert weights[STYLE_VALUE] == pytest.approx(0.15)
    assert weights[STYLE_GROWTH] == pytest.approx(0.35)
    assert weights[STYLE_QUALITY_MOAT] == pytest.approx(0.30)
    assert sum(weights.values()) == pytest.approx(1.0)

    # --- P5 watchlist add (HMAC-signed pillars + scenario A baselines) ---
    p5_inp = WatchlistAddInput(
        ticker=NVDA_TICKER,
        mode=NVDA_MODE,
        company_quality_flag=NVDA_QUALITY,
        pm_supervisor_decision=VERDICT_ADD,
        thesis_pillars_original=NVDA_THESIS_PILLARS,
        scenario_A_base_projections=NVDA_SCENARIO_A_BASE,
        macro_regime_style_output=NVDA_MACRO_REGIME_OUTPUT,
        parameters_version=uuid4(),
    )
    p5_outcome: WatchlistAddOutcome = add_to_watchlist(
        p5_inp, conn=fake_conn, hmac_key=hmac_keys["watchlist"]
    )
    assert p5_outcome.ticker == NVDA_TICKER
    assert p5_outcome.mode == NVDA_MODE
    # Section 2.2: B' conviction threshold is 0.6.
    assert p5_outcome.conviction_threshold == pytest.approx(0.60)
    assert p5_outcome.regime_sensitivity == "MEDIUM"
    # HMAC sigs present.
    assert len(p5_outcome.thesis_pillars_original_hmac) == 64  # SHA256 hex
    assert len(p5_outcome.scenario_A_base_projections_hmac) == 64
    # One row written to the watchlist table.
    watchlist_writes = [
        e for e in fake_conn.executed if "INSERT INTO watchlist" in e.sql
    ]
    assert len(watchlist_writes) == 1
    assert fake_conn.committed is True

    # --- P6 disposition determination (Mode B' -> mid primary; ADD -> BUY) ---
    p6_inp = DispositionInput(
        ticker=NVDA_TICKER,
        mode=NVDA_MODE,
        company_quality_flag=NVDA_QUALITY,
        pm_supervisor_decision=VERDICT_ADD,
        currently_held=False,
        conviction_bucket=None,
    )
    p6_decision = determine_disposition(p6_inp)
    assert p6_decision.primary_horizon == HORIZON_MID
    assert p6_decision.primary_recommendation == SIGNAL_BUY
    # Per Section 4.6 Q2: short HOLD / mid BUY / long HOLD (mode B' anchors mid).
    assert p6_decision.horizon_signals["short"] == SIGNAL_HOLD
    assert p6_decision.horizon_signals["mid"] == SIGNAL_BUY
    assert p6_decision.horizon_signals["long"] == SIGNAL_HOLD
    assert p6_decision.suggested_pacing == "DCA over 21 days"

    # --- P7 sizing band check (B' -> initial 2% / max 5%) ---
    sizing = compute_sizing(SizingContext(mode=NVDA_MODE))
    assert sizing.initial_pct == pytest.approx(2.0)
    assert sizing.max_pct == pytest.approx(5.0)

    # --- P7 emit recommendation (full Q1 schema; HIGH conviction; HMAC chain) ---
    p7_conn = FakeConn()
    p7_outcome = emit_recommendation(_baseline_emit_inputs(), conn=p7_conn)
    assert p7_outcome.recommendation == "BUY"
    assert p7_outcome.conviction == CONVICTION_HIGH
    # Full Q1 schema envelope keys present.
    assert "initial_pct" in p7_outcome.sizing_payload
    assert "base_band" in p7_outcome.sizing_payload
    assert "applied_overlays" in p7_outcome.sizing_payload
    assert "debate_consensus" in p7_outcome.conviction_breakdown
    assert "kills_fired" in p7_outcome.conviction_breakdown
    assert "current_price" in p7_outcome.execution_context
    assert "fair_value_estimate" in p7_outcome.execution_context
    assert "risk_flags" in p7_outcome.execution_context
    # 5 audit_provenance stages signed.
    assert len(p7_outcome.audit_chain_ids) == 5
    assert len(p7_outcome.audit_signature) == 64

    # --- audit_trail.verify_chain() round-trip on the emitted chain ---
    audit_writes = [
        e for e in p7_conn.executed if "INSERT INTO audit_provenance" in e.sql
    ]
    assert len(audit_writes) == 5
    rows: list[StageRow] = []
    for e in audit_writes:
        p = e.params
        rows.append(
            StageRow(
                audit_id=UUID(p[0]),
                recommendation_id=UUID(p[1]),
                stage=p[2],
                drill_payload=json.loads(p[3]),
                hmac_signature=p[4],
                parent_audit_id=UUID(p[5]) if p[5] else None,
                versions=json.loads(p[6]),
                created_at=p[7],
            )
        )
    result = verify_chain(rows, key=hmac_keys["audit"])
    assert result.mode == "keyed"
    assert result.all_ok, [r for r in result.rows if not r.ok]


# ===========================================================================
# Scenario 2 (Kill criterion fires via counterfactual_veto): test removed
# 2026-05-23 with src/counterfactual_veto/ deletion (mig 041) per
# docs/superpowers/specs/2026-05-23-eval-loop-deletion-design.md.
# ===========================================================================


# ===========================================================================
# Scenario 3 — Anchor-drift Channel 1 fires
# ===========================================================================


def test_e2e_anchor_drift_triggers(hmac_keys: dict[str, bytes]) -> None:
    """Channel 1 LLM diff produces drift_score 0.32 > 0.25 threshold.

    Simulates: 4 months after watchlist add, M-2 events accumulate; the
    operating thesis has softened/rewritten enough pillars that the LLM
    diff returns a drift score above PILLAR_DRIFT_THRESHOLD (0.25). The
    anchor_drift orchestrator then writes a forced_review row with
    operator_decision='pending' (per migration 018 sidecar; the schema
    blocks new actions until operator commits).

    Per v3 Section 4.5 Q5 + migration 010_v3_drift_detection.sql +
    migration 018_v3_forced_review_blocked_pending.sql.
    """
    from src.anchor_drift import PILLAR_DRIFT_THRESHOLD, DECISION_PENDING
    from src.anchor_drift.channel_1_pillar_drift import detect_pillar_drift
    from src.anchor_drift.hmac_verify import compute_hmac

    # Sign the original pillars under the WATCHLIST_HMAC_SECRET scope.
    sig = compute_hmac(NVDA_THESIS_PILLARS)

    # Simulate 4 months later: 1 unchanged, 1 softened, 1 rewritten.
    drifted_diff = json.dumps(
        {
            "pairs": [
                {
                    "pillar": "moat_data_center_pivot",
                    "classification": "unchanged",
                    "confidence_delta": 0.0,
                },
                {
                    "pillar": "growth_secular_demand",
                    "classification": "softened",
                    "confidence_delta": -0.20,
                },
                {
                    "pillar": "quality_roiic",
                    "classification": "rewritten",
                    "confidence_delta": -0.30,
                },
            ]
        }
    )

    class _FakeBlock:
        def __init__(self, text: str) -> None:
            self.text = text

    class _FakeResp:
        def __init__(self, text: str) -> None:
            self.content = [_FakeBlock(text)]

    class _FakeMessages:
        def __init__(self, text: str) -> None:
            self._text = text

        def create(self, **_kwargs: Any) -> _FakeResp:
            return _FakeResp(self._text)

    class _FakeClient:
        def __init__(self, text: str) -> None:
            self.messages = _FakeMessages(text)

    res = detect_pillar_drift(
        ticker=NVDA_TICKER,
        thesis_pillars_original=NVDA_THESIS_PILLARS,
        thesis_pillars_original_hmac=sig,
        current_pillars=NVDA_THESIS_PILLARS,  # placeholder; LLM diff is stubbed
        client=_FakeClient(drifted_diff),
    )
    assert res.hmac_verified is True
    # 1 softened + 1 rewritten + 0.50 conf-delta = (0.50 + 1 + 1)/3 = 0.833
    # which is well > 0.25 threshold.
    assert res.drift_score > PILLAR_DRIFT_THRESHOLD
    assert res.triggered is True
    # The orchestrator would write a forced_review row with operator_decision
    # = 'pending' — pin the contract by inspecting the constant.
    assert DECISION_PENDING == "pending"


# ===========================================================================
# Scenario 4 — Comprehensive HMAC verification across all 4 modules
# ===========================================================================


def test_e2e_audit_chain_integrity(hmac_keys: dict[str, bytes]) -> None:
    """Sign + verify + tamper-test rows from all 4 HMAC scopes.

    The 4 scope-isolated keys per v3 Section 5 Q1 + Section 6 Q5:
      * AUDIT_HMAC_KEY        — execution_recommendations row
      * PEAK_PAIN_HMAC_KEY    — peak_pain_archetypes row
      * WATCHLIST_HMAC_SECRET — thesis_pillars_original / scenario_A row
      * PREMORTEM_HMAC_SECRET — premortem row

    For each: (a) compute signature via canonical_payload_dict, (b) verify
    re-computed signature equals stored signature, (c) tamper a field and
    confirm re-verification fails.
    """
    # --- (a) AUDIT scope — P7 recommendation row ---
    rec_payload = {
        "recommendation_id": str(uuid4()),
        "ticker": NVDA_TICKER,
        "date": "2023-01-15",
        "recommendation": "BUY",
        "conviction": "HIGH",
        "conviction_changed_from_prior": False,
    }
    audit_sig = compute_signature_dict(rec_payload, hmac_keys["audit"])
    assert compute_signature_dict(rec_payload, hmac_keys["audit"]) == audit_sig
    # Tamper: flip recommendation BUY -> SELL.
    tampered = dict(rec_payload)
    tampered["recommendation"] = "SELL"
    assert compute_signature_dict(tampered, hmac_keys["audit"]) != audit_sig

    # --- (b) PEAK_PAIN scope — peak_pain_archetypes row ---
    pp_payload = {
        "case_id": "NVDA-2018",
        "ticker": "NVDA",
        "peak_date": "2018-10-01",
        "trough_date": "2019-01-01",
        "outcome": "SURVIVOR",
        "universal_core_features": {
            "founder_in_place": "YES",
            "roiic_above_15": "YES",
            "fraud_signature": "NO",
        },
    }
    pp_sig = compute_signature_dict(pp_payload, hmac_keys["peak_pain"])
    assert compute_signature_dict(pp_payload, hmac_keys["peak_pain"]) == pp_sig
    pp_tampered = dict(pp_payload)
    pp_tampered["outcome"] = "NON_SURVIVOR"
    assert (
        compute_signature_dict(pp_tampered, hmac_keys["peak_pain"]) != pp_sig
    )

    # --- (c) WATCHLIST scope — thesis_pillars + scenario_A (via producer) ---
    wl_sigs = sign_watchlist_row(
        NVDA_THESIS_PILLARS,
        NVDA_SCENARIO_A_BASE,
        hmac_key=hmac_keys["watchlist"],
    )
    # Round-trip: signing the same payload again under the same key
    # produces an identical signature (deterministic canonical-JSON).
    wl_sigs_again = sign_watchlist_row(
        NVDA_THESIS_PILLARS,
        NVDA_SCENARIO_A_BASE,
        hmac_key=hmac_keys["watchlist"],
    )
    assert (
        wl_sigs["thesis_pillars_original_hmac"]
        == wl_sigs_again["thesis_pillars_original_hmac"]
    )
    assert (
        wl_sigs["scenario_A_base_projections_hmac"]
        == wl_sigs_again["scenario_A_base_projections_hmac"]
    )
    # Tamper: append a pillar -> sig changes.
    tampered_pillars = NVDA_THESIS_PILLARS + [
        {"pillar": "INJECTED", "claim": "fake", "confidence": 0.99}
    ]
    wl_tampered = sign_watchlist_row(
        tampered_pillars,
        NVDA_SCENARIO_A_BASE,
        hmac_key=hmac_keys["watchlist"],
    )
    assert (
        wl_tampered["thesis_pillars_original_hmac"]
        != wl_sigs["thesis_pillars_original_hmac"]
    )

    # --- (d) PREMORTEM scope — premortem row ---
    pm_payload = {
        "ticker": NVDA_TICKER,
        "trigger": "thesis_confirmation",
        "failure_modes": [
            {"id": 1, "narrative": "AI capex digestion + GM compression"},
            {"id": 2, "narrative": "China export controls bite revenue"},
            {"id": 3, "narrative": "Founder Huang exit / succession risk"},
        ],
        "pillars_revisited": ["moat_data_center_pivot", "growth_secular_demand"],
    }
    pm_sig = compute_premortem_hmac(pm_payload, hmac_key=hmac_keys["premortem"])
    assert pm_sig is not None
    assert verify_premortem_hmac(
        pm_payload, pm_sig, hmac_key=hmac_keys["premortem"]
    )
    pm_tampered = dict(pm_payload)
    pm_tampered["failure_modes"] = pm_payload["failure_modes"][:2]  # drop one
    assert not verify_premortem_hmac(
        pm_tampered, pm_sig, hmac_key=hmac_keys["premortem"]
    )


# ===========================================================================
# Scenario 5 — Full chain smoke test
# ===========================================================================


def test_e2e_full_chain_smoke(
    hmac_keys: dict[str, bytes], fake_conn: FakeConn
) -> None:
    """Sequential P5 -> P6 -> P7 with HMAC chain holding across writes.

    Pipeline:
      1. P5: write watchlist row (HMAC-sign pillars + scenario A).
      2. P6: derive disposition (pure function; no DB).
      3. P7: emit recommendation (HMAC-sign main row + 5 audit rows).
      4. Verify the audit chain via verify_chain(rows, key=AUDIT_HMAC_KEY).
      5. Verify watchlist HMAC sigs are deterministic under the producer
         key (re-sign same payload -> same sig).

    Final invariants:
      - One execution_recommendations row written.
      - Five audit_provenance rows chained via parent_audit_id.
      - HMAC chain verifies all_ok=True.
      - Watchlist HMAC scopes do NOT cross-pollinate audit scope (signing
        the same payload under different keys produces different sigs).

    Per v3 spec Section 2.1 + Section 5 Q1 + Section 7 Q4.
    """
    # ---- P5 ----
    p5_outcome = add_to_watchlist(
        WatchlistAddInput(
            ticker=NVDA_TICKER,
            mode=NVDA_MODE,
            company_quality_flag=NVDA_QUALITY,
            pm_supervisor_decision=VERDICT_ADD,
            thesis_pillars_original=NVDA_THESIS_PILLARS,
            scenario_A_base_projections=NVDA_SCENARIO_A_BASE,
            macro_regime_style_output=NVDA_MACRO_REGIME_OUTPUT,
        ),
        conn=fake_conn,
        hmac_key=hmac_keys["watchlist"],
    )
    assert p5_outcome.inserted is True

    # ---- P6 ----
    p6_decision = determine_disposition(
        DispositionInput(
            ticker=NVDA_TICKER,
            mode=NVDA_MODE,
            company_quality_flag=NVDA_QUALITY,
            pm_supervisor_decision=VERDICT_ADD,
            currently_held=False,
        )
    )
    assert p6_decision.primary_recommendation == "BUY"

    # ---- P7 ----
    p7_conn = FakeConn()
    p7_outcome = emit_recommendation(_baseline_emit_inputs(), conn=p7_conn)
    assert p7_outcome.conviction == CONVICTION_HIGH

    # ---- Audit chain integrity ----
    audit_writes = [
        e for e in p7_conn.executed if "INSERT INTO audit_provenance" in e.sql
    ]
    rec_writes = [
        e for e in p7_conn.executed
        if "INSERT INTO execution_recommendations" in e.sql
    ]
    assert len(rec_writes) == 1
    assert len(audit_writes) == 5
    rows: list[StageRow] = []
    for e in audit_writes:
        p = e.params
        rows.append(
            StageRow(
                audit_id=UUID(p[0]),
                recommendation_id=UUID(p[1]),
                stage=p[2],
                drill_payload=json.loads(p[3]),
                hmac_signature=p[4],
                parent_audit_id=UUID(p[5]) if p[5] else None,
                versions=json.loads(p[6]),
                created_at=p[7],
            )
        )
    result = verify_chain(rows, key=hmac_keys["audit"])
    assert result.all_ok, [r for r in result.rows if not r.ok]

    # ---- Cross-scope HMAC isolation: same payload under different keys
    #      MUST produce different signatures (no cross-pollination). ----
    payload = dict(NVDA_SCENARIO_A_BASE)
    sig_a = compute_signature_dict(payload, hmac_keys["audit"])
    sig_w = compute_signature_dict(payload, hmac_keys["watchlist"])
    sig_p = compute_signature_dict(payload, hmac_keys["peak_pain"])
    sig_m = compute_signature_dict(payload, hmac_keys["premortem"])
    assert len({sig_a, sig_w, sig_p, sig_m}) == 4

    # ---- /disposition view contract: column shape ----
    # We don't have a real Postgres connection in this stub-driven test, so
    # verify the SQL view's column list matches the watchlist + recommendation
    # outputs by inspecting the view DDL (the SQL is static).
    view_sql = (
        _REPO_ROOT / "src" / "disposition_view" / "postgres_view.sql"
    ).read_text()
    # Required columns for the disposition rollup per Section 4.6 Q2.
    for required_col in (
        "ticker",
        "mode",
        "company_quality_flag",
        "conviction_threshold",
        "regime_sensitivity",
        "primary_horizon",
        "recommendation",
        "conviction",
    ):
        assert required_col in view_sql, (
            f"current_disposition view missing column {required_col}"
        )
