"""Extended live-Postgres smoke for modules previously only FakeConn-tested.

Companion to ``tests/test_live_db_smoke.py``. Covers:

  1. regime_classification_history dual-signal (migration 020) +
     dimension_name post-021 rename CHECK enforcement + regime_state view.
  2. Counterfactual-veto orchestrator pipeline writes
     (counterfactual_retrievals + veto_lifecycle + system_errors HMAC-skip).
  3. l4_daily_monitor refresh emitter end-to-end
     (daily_refresh_log + materiality_events + unread_alerts) +
     materiality_label STORED column derivation +
     unread_alerts.alert_type='materiality_m2' (post-017).
  4. mode_classifier orchestrator persisted rows
     (rule + llm_tiebreaker paths) + mode_class_tiebreaker_payload CHECK.
  5. anchor_drift orchestrator + anchor_drift_review_decisions sidecar
     (migration 018) FK from sidecar to checks.
  6. Calibration capture: operator_overrides + recommendation_outcomes
     UPDATE state-machine (migration 013).
  7. alert_channels.email_sender failure path → system_errors row
     (escalated_to_alert=true).
  8. Full P5 → P7 → audit-chain meta-test.

Default behaviour: SKIPPED. Run with::

    pytest tests/test_live_db_smoke.py tests/test_live_db_smoke_extended.py \
        -m integration_live

Pre-conditions: same as ``test_live_db_smoke.py`` — Postgres at
127.0.0.1:5432 with all 21 migrations applied.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import secrets
import sys
import uuid
from pathlib import Path
from typing import Any, Optional
from uuid import UUID, uuid4

import pytest

# Ensure both repo root (for `from src.X`) and src/ (for bare-package
# imports like `from p5_watchlist import ...`) are on sys.path. Mirrors
# the path-manipulation discipline of test_live_db_smoke.py — the latter
# uses `from src.X` because it relies on the rootdir being on sys.path.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src"
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


pytestmark = pytest.mark.integration_live


LIVE_DSN = (
    "postgresql://equity_research_admin:"
    "cKgxj2TVEhjuLYiXXsm9cftYAhCAnBq@127.0.0.1:5432/equity_research"
)


_RUN_TAG = f"LIVESMOKE2-{secrets.token_hex(4)}"
_TEST_TICKER = f"YYTST{secrets.token_hex(2).upper()}"


# ---------------------------------------------------------------------------
# Common fixtures
# ---------------------------------------------------------------------------


def _require_psycopg():
    try:
        import psycopg  # noqa: F401
    except ImportError:
        pytest.skip("psycopg not installed in this environment")


def _require_db():
    _require_psycopg()
    import psycopg

    try:
        c = psycopg.connect(LIVE_DSN, connect_timeout=3)
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"live Postgres unreachable: {e!r}")
    c.close()


@pytest.fixture(scope="class")
def hmac_keys_class():
    """Random per-class HMAC keys (test-only)."""
    keys = {
        "audit": secrets.token_urlsafe(32).encode("utf-8"),
        "watchlist": secrets.token_urlsafe(32).encode("utf-8"),
        "peak_pain": secrets.token_urlsafe(32).encode("utf-8"),
        "premortem": secrets.token_urlsafe(32).encode("utf-8"),
    }
    saved = {
        "AUDIT_HMAC_KEY": os.environ.get("AUDIT_HMAC_KEY"),
        "WATCHLIST_HMAC_SECRET": os.environ.get("WATCHLIST_HMAC_SECRET"),
        "PEAK_PAIN_HMAC_KEY": os.environ.get("PEAK_PAIN_HMAC_KEY"),
        "PREMORTEM_HMAC_SECRET": os.environ.get("PREMORTEM_HMAC_SECRET"),
    }
    os.environ["AUDIT_HMAC_KEY"] = keys["audit"].decode("utf-8")
    os.environ["WATCHLIST_HMAC_SECRET"] = keys["watchlist"].decode("utf-8")
    os.environ["PEAK_PAIN_HMAC_KEY"] = keys["peak_pain"].decode("utf-8")
    os.environ["PREMORTEM_HMAC_SECRET"] = keys["premortem"].decode("utf-8")
    yield keys
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


class _NoCommitConn:
    """Same wrapper as test_live_db_smoke.py — swallows ``commit()``."""

    def __init__(self, real):
        self._real = real

    def cursor(self, *args, **kwargs):
        return self._real.cursor(*args, **kwargs)

    def commit(self):
        return None

    def rollback(self):
        return self._real.rollback()

    @property
    def autocommit(self):
        return self._real.autocommit

    def __getattr__(self, name):
        return getattr(self._real, name)


# ---------------------------------------------------------------------------
# Builders shared with test_live_db_smoke.py (kept local to avoid coupling).
# ---------------------------------------------------------------------------


_THESIS_PILLARS: list[dict[str, Any]] = [
    {"pillar": "moat_data_center_pivot",
     "claim": "CUDA->AI pivot is structural; founder Huang 30+yr.",
     "confidence": 0.85},
    {"pillar": "growth_secular_demand",
     "claim": "Hyperscaler AI capex multi-year sustained.",
     "confidence": 0.80},
    {"pillar": "quality_roiic",
     "claim": "ROIIC > 30% in last 3 years; per-share-value compounder.",
     "confidence": 0.90},
]

_SCENARIO_A_BASE: dict[str, Any] = {
    "scenario": "base", "horizon_years": 3, "revenue_cagr_pct": 35.0,
    "gross_margin_pct": 65.0, "fcf_margin_pct": 35.0,
    "exit_pe_multiple": 30.0, "implied_irr_pct": 22.0,
    "kill_criteria_structured": [
        {"id": "kill_1", "metric": "data_center_revenue_yoy_pct",
         "threshold_floor": -25.0, "horizon": "ttm",
         "rationale": "AI capex digestion > 2 quarters violates thesis"},
    ],
}


def _build_watchlist_input(ticker: str = _TEST_TICKER):
    from src.p5_watchlist import WatchlistAddInput

    return WatchlistAddInput(
        ticker=ticker,
        mode="B_prime",
        company_quality_flag="HIGH",
        pm_supervisor_decision="ADD",
        thesis_pillars_original=_THESIS_PILLARS,
        scenario_A_base_projections=_SCENARIO_A_BASE,
        macro_regime_style_output={"regime_sensitivity": "MEDIUM"},
        parameters_version=None,
    )


def _build_emit_inputs(ticker: str = _TEST_TICKER):
    from src.p7_recommendation_emitter import EmitInputs, TRIGGER_NEW_CANDIDATE
    from src.p4_debate import WEIGHT_MATRIX

    return EmitInputs(
        ticker=ticker, mode="B_prime", company_quality_flag="HIGH",
        mode_certainty="rule_clean",
        debate_add_count=4,
        debate_consensus_summary="4/5 ADD (Quant-Technical dissents HOLD)",
        kills_fired=0,
        counterfactual_top_3=["SURVIVOR", "SURVIVOR", "SURVIVOR"],
        anchor_drift_channels_triggered=0,
        primary_recommendation="BUY",
        suggested_pacing="DCA over 21 days",
        triggered_by=TRIGGER_NEW_CANDIDATE,
        available_cash_pct=10.0, current_price=420.50,
        fair_value_payload={"point": 525, "range_low": 450, "range_high": 600},
        near_term_catalysts_raw=[
            {"event": "Q4 earnings", "date": "2023-02-22", "importance": "high"}
        ],
        technical_signals_raw={"ma_50d": 380.0, "ma_200d": 290.0,
                               "rsi_14": 68, "atr_20": 12.5},
        stage_drill_payloads={
            "stage_1_mechanical": {"outcome": "PROCEED", "score": 0.92,
                                   "stage_1a_knockout": "no_fraud_signature"},
            "stage_2_debate": {"consensus": "4/5 ADD",
                               "dissenter": "Quant-Technical",
                               "weight_matrix": dict(WEIGHT_MATRIX["B_prime"])},
            "stage_3_kill_criteria": {
                "fired": 0,
                "structured": _SCENARIO_A_BASE["kill_criteria_structured"]},
            "stage_4_counterfactual": {
                "top_3_archetype": ["SURVIVOR", "SURVIVOR", "SURVIVOR"],
                "veto_status": "no_veto"},
            "materiality": {"classification": "M-1",
                            "trigger": "new_candidate"},
        },
    )


# ---------------------------------------------------------------------------
# Sign + insert helpers for peak_pain rows (so HMAC verification passes).
# ---------------------------------------------------------------------------


def _sign_peak_pain_row(payload: dict[str, Any], key: bytes) -> str:
    from src.audit_trail.hmac_verify import compute_signature_dict

    return compute_signature_dict(payload, key)


def _insert_peak_pain_row(
    conn,
    *,
    case_id: str,
    ticker: str,
    sector: str,
    outcome: str,
    universal_core: dict[str, str],
    sector_extensions: dict[str, str],
    hmac_key: bytes,
    tamper: bool = False,
) -> str:
    """Insert a peak_pain row with a write-time HMAC signature.

    Computes the signature over the canonical payload using the same
    ``Decimal(str(...))``-normalized peak_dd_pct that
    ``src.peak_pain_catalog.persistence`` writes — so the signature is
    byte-identical to what the loader recomputes after SELECT-readback
    (psycopg returns NUMERIC as ``Decimal``).
    """
    from decimal import Decimal as _Decimal

    payload_no_hmac = {
        "case_id": case_id,
        "ticker": ticker,
        "peak_date": "2018-10-01",
        "trough_date": "2019-01-01",
        # NUMERIC column — must canonicalize as Decimal so write-time and
        # SELECT-readback signatures match.
        "peak_dd_pct": _Decimal("-56.0"),
        "outcome": outcome,
        "sector": sector,
        "era_category": "modern_internet",
        "universal_core_features": universal_core,
        "sector_extensions": sector_extensions,
        "universal_core_consensus": {},
        "validation_status": "validated",
        "consensus_method": "v0.1",
        "notes": f"test {_RUN_TAG}",
        "source_urls": [],
    }
    sig = _sign_peak_pain_row(payload_no_hmac, hmac_key)

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO peak_pain_archetypes (
                case_id, ticker, peak_date, trough_date, peak_dd_pct,
                outcome, sector, era_category,
                universal_core_features, sector_extensions,
                universal_core_consensus, validation_status,
                consensus_method, notes, source_urls,
                hmac_signature
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s,
                %s::jsonb, %s::jsonb, %s::jsonb, %s,
                %s, %s, %s, %s
            )
            """,
            (
                case_id, ticker,
                payload_no_hmac["peak_date"], payload_no_hmac["trough_date"],
                payload_no_hmac["peak_dd_pct"],
                outcome, sector, payload_no_hmac["era_category"],
                json.dumps(universal_core), json.dumps(sector_extensions),
                json.dumps({}), payload_no_hmac["validation_status"],
                payload_no_hmac["consensus_method"], payload_no_hmac["notes"],
                json.dumps(payload_no_hmac["source_urls"]),
                sig,
            ),
        )

    if tamper:
        # Tamper the JSONB column AFTER signing so the stored signature no
        # longer matches the canonical payload — loader recompute fails.
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE peak_pain_archetypes "
                "SET universal_core_features = "
                "    jsonb_set(universal_core_features, "
                "              '{founder_in_place}', '\"NO\"'::jsonb) "
                "WHERE case_id = %s",
                (case_id,),
            )
    return sig


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestLiveDbSmokeExtended:

    @pytest.fixture(scope="class")
    def live_conn_raw(self):
        _require_db()
        import psycopg

        conn = psycopg.connect(LIVE_DSN)
        conn.autocommit = False
        try:
            yield conn
        finally:
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass
            conn.close()

    @pytest.fixture(scope="class")
    def live_conn(self, live_conn_raw):
        return _NoCommitConn(live_conn_raw)

    @pytest.fixture
    def savepoint(self, live_conn_raw):
        sp_name = f"sp_{secrets.token_hex(4)}"
        with live_conn_raw.cursor() as cur:
            cur.execute(f"SAVEPOINT {sp_name}")
        yield sp_name
        try:
            with live_conn_raw.cursor() as cur:
                cur.execute(f"ROLLBACK TO SAVEPOINT {sp_name}")
                cur.execute(f"RELEASE SAVEPOINT {sp_name}")
        except Exception:  # noqa: BLE001
            try:
                live_conn_raw.rollback()
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    # 1. regime_classification_history dual-signal + 021 rename
    # ------------------------------------------------------------------

    def test_live_regime_classification_history_dual_signal(
        self, live_conn_raw, savepoint
    ):
        """Insert a regime_classification_history row with both BOCPD signals
        and dimension_name='cycle_2y3m_slope' (post-021).

        Verifies:
          * Row insert with both bocpd_change_probability + bocpd_short_run_mass.
          * regime_state view returns the latest row.
          * Legacy 'cycle_ntfs' name is rejected by the new CHECK (post-021).
        """
        import psycopg

        # Insert a fresh row for dim 2 with the canonical name.
        with live_conn_raw.cursor() as cur:
            cur.execute(
                """
                INSERT INTO regime_classification_history (
                    classification_date, dimension_id, dimension_name,
                    state_probabilities, headline_state,
                    bocpd_change_probability,
                    raw_inputs, history_length_days,
                    rule_engine_version, bocpd_short_run_mass
                ) VALUES (
                    '2026-04-29', 2, 'cycle_2y3m_slope',
                    '{"hot": 0.6, "cool": 0.4}'::jsonb, 'hot',
                    0.004,
                    '{"DGS2": 4.2, "DGS3MO": 4.8}'::jsonb, 90,
                    'regime_sidecar.v0.1', 0.85
                ) RETURNING classification_id
                """,
            )
            (cls_id,) = cur.fetchone()

        # regime_state view exposes the latest row for that dimension.
        with live_conn_raw.cursor() as cur:
            cur.execute(
                """
                SELECT classification_id, dimension_name,
                       bocpd_change_probability, bocpd_short_run_mass,
                       headline_state
                FROM regime_state
                WHERE dimension_id = 2
                """,
            )
            row = cur.fetchone()
        assert row is not None
        assert row[0] == cls_id
        assert row[1] == "cycle_2y3m_slope"
        assert float(row[2]) == pytest.approx(0.004)
        assert float(row[3]) == pytest.approx(0.85)
        assert row[4] == "hot"

        # Legacy name rejected by the post-021 CHECK.
        with pytest.raises(psycopg.errors.CheckViolation):
            with live_conn_raw.transaction():
                with live_conn_raw.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO regime_classification_history (
                            classification_date, dimension_id, dimension_name,
                            state_probabilities, headline_state,
                            bocpd_change_probability,
                            raw_inputs, history_length_days,
                            rule_engine_version, bocpd_short_run_mass
                        ) VALUES (
                            '2026-04-29', 2, 'cycle_ntfs',
                            '{}'::jsonb, 'hot',
                            0.004, '{}'::jsonb, 90,
                            'v0.1', 0.5
                        )
                        """,
                    )

        # bocpd_short_run_mass > 1 must reject (migration 020 CHECK).
        with pytest.raises(psycopg.errors.CheckViolation):
            with live_conn_raw.transaction():
                with live_conn_raw.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO regime_classification_history (
                            classification_date, dimension_id, dimension_name,
                            state_probabilities, headline_state,
                            bocpd_change_probability,
                            raw_inputs, history_length_days,
                            rule_engine_version, bocpd_short_run_mass
                        ) VALUES (
                            '2026-04-29', 2, 'cycle_2y3m_slope',
                            '{}'::jsonb, 'hot',
                            0.004, '{}'::jsonb, 90,
                            'v0.1', 1.5
                        )
                        """,
                    )

    # ------------------------------------------------------------------
    # 2. counterfactual veto orchestrator writes (test removed 2026-05-23
    # with src/counterfactual_veto/ + counterfactual_retrievals / veto_lifecycle
    # tables dropped per mig 041 / docs/superpowers/specs/
    # 2026-05-23-eval-loop-deletion-design.md)
    # ------------------------------------------------------------------


    # ------------------------------------------------------------------
    # 3. l4_daily_monitor refresh emitter
    # ------------------------------------------------------------------

    def test_live_daily_refresh_log_with_routing(
        self, live_conn_raw, savepoint
    ):
        """Run refresh_emitter.run_daily_refresh end-to-end with stub adapter.

        Verifies:
          * daily_refresh_log row inserted (and materiality_label STORED
            column is correctly derived).
          * materiality_events row inserted per event.
          * unread_alerts row inserted with alert_type='materiality_m2' for
            an M-2 verdict (post-017 CHECK accepts this enum value).
        """
        import datetime as dt
        from l4_daily_monitor import MATERIALITY_M2
        from l4_daily_monitor.event_ingestor import (
            EVENT_TYPE_FILING_8K,
            Event,
        )
        from l4_daily_monitor.materiality_classifier import MaterialityVerdict
        from l4_daily_monitor.refresh_emitter import run_daily_refresh
        from l4_daily_monitor.router import RoutingDecision

        # Stub adapter — returns one filing event the LLM will see.
        ev = Event(
            type=EVENT_TYPE_FILING_8K,
            source_id=f"edgar:{_RUN_TAG}",
            timestamp=dt.datetime(2026, 4, 29, 8, 0, tzinfo=dt.timezone.utc),
            raw_text=(
                "Item 5.02 — CFO resignation announced. Replacement "
                "search underway; CEO Huang remains."
            ),
            verbatim_quote="CFO resignation announced",
        )

        class _StubAdapter:
            def __init__(self, ev: Event) -> None:
                self._ev = ev

            def fetch_news(self, t, d):           return []
            def fetch_filings(self, t, d):        return [self._ev]
            def fetch_smart_money(self, t, d):    return []
            def fetch_macro(self, d):             return []
            def fetch_credit(self, d):            return []
            def fetch_sector_peers(self, t, d):   return []
            def fetch_earnings(self, t, d):       return []

        # Monkey-patch classify_materiality + route_materiality to skip the
        # LLM dependency entirely (deterministic stubs only).
        import l4_daily_monitor.refresh_emitter as refresh_mod

        orig_classify = refresh_mod.classify_materiality
        orig_route = refresh_mod.route_materiality

        def _stub_classify(*, ticker, event, regime_context,
                           scenario_kill_criteria, client):
            return MaterialityVerdict(
                classification=MATERIALITY_M2, confidence=0.85,
                rationale="CFO departure is partial thesis erosion.",
                verbatim_quote="CFO resignation announced",
                cited_kill_criterion_id=None,
                model="stub-sonnet", prompt_version="stub.v0.1",
                tier_escalated_to_opus=False,
            )

        def _stub_route(*, ticker, event, verdict, client):
            return RoutingDecision(
                action="partial_reunderwrite",
                agents=["Quality", "Macro-Regime"],
                operator_alert=False,
                rationale="M-2 partial re-underwrite.",
                used_fallback_table=False,
            )

        refresh_mod.classify_materiality = _stub_classify  # type: ignore[assignment]
        refresh_mod.route_materiality = _stub_route  # type: ignore[assignment]

        # DB writer that goes through our raw connection.
        def _db_writer(sql: str, params: tuple) -> Optional[uuid.UUID]:
            with live_conn_raw.cursor() as cur:
                cur.execute(sql, params)
                if "RETURNING" in sql.upper():
                    row = cur.fetchone()
                    return row[0] if row else None
            return None

        try:
            outcome = run_daily_refresh(
                ticker=_TEST_TICKER,
                date=dt.date(2026, 4, 29),
                mode="B_prime",
                regime_context={"S0_classification": "neutral"},
                scenario_kill_criteria=[],
                event_adapter=_StubAdapter(ev),
                llm_client=None,
                db_writer=_db_writer,
            )
        finally:
            refresh_mod.classify_materiality = orig_classify  # type: ignore[assignment]
            refresh_mod.route_materiality = orig_route  # type: ignore[assignment]

        assert outcome.materiality_rollup == MATERIALITY_M2
        assert outcome.materiality_label == "M-2"
        assert len(outcome.triggered_alerts) == 1

        # Verify DB rows.
        with live_conn_raw.cursor() as cur:
            cur.execute(
                "SELECT materiality, materiality_label, recommended_action "
                "FROM daily_refresh_log WHERE ticker = %s AND date = %s",
                (_TEST_TICKER, "2026-04-29"),
            )
            r = cur.fetchone()
        assert r is not None
        assert r[0] == 2
        assert r[1] == "M-2"  # STORED column derived correctly
        assert r[2] in ("reunderwrite", "exit")

        # materiality_events row.
        with live_conn_raw.cursor() as cur:
            cur.execute(
                "SELECT classification, verbatim_quote FROM materiality_events "
                "WHERE ticker = %s AND source_id = %s",
                (_TEST_TICKER, f"edgar:{_RUN_TAG}"),
            )
            me = cur.fetchone()
        assert me is not None
        assert me[0] == 2
        assert "CFO resignation" in me[1]

        # unread_alerts row with alert_type='materiality_m2' (post-017 CHECK).
        with live_conn_raw.cursor() as cur:
            cur.execute(
                "SELECT alert_type, severity FROM unread_alerts "
                "WHERE ticker = %s AND alert_type = 'materiality_m2'",
                (_TEST_TICKER,),
            )
            ar = cur.fetchone()
        assert ar is not None
        assert ar[0] == "materiality_m2"
        assert ar[1] == 2

    # ------------------------------------------------------------------
    # 4. mode_classifier orchestrator writes
    # ------------------------------------------------------------------

    def test_live_mode_classification_writes(self, live_conn_raw, savepoint):
        """Persist mode_classifications rows for both rule + llm_tiebreaker
        paths and verify mode_class_tiebreaker_payload CHECK enforcement.

        The orchestrator's _persist opens its own connection, so we can't
        share our class transaction. We replicate its INSERT via the raw
        conn — the SQL string is the same INSERT contract.
        """
        import psycopg
        from mode_classifier.adapters import StructuralFacts, QualityFacts
        from mode_classifier.orchestrator import classify_ticker

        # Stubs from test_mode_classifier.py pattern.
        class _StubData:
            def __init__(self, f): self._f = f
            def get_structural_facts(self, t, d): return self._f

        class _StubQual:
            def __init__(self, q): self._q = q
            def get_quality_facts(self, t, d): return self._q

        # Rule-clean inputs (Mode B). Run with persist=False, then
        # replicate the INSERT through our connection.
        sf = StructuralFacts(
            market_cap_usd=300e9, realized_vol_252d=0.18,
            profitable_consecutive_years=30, revenue_growth_yoy=0.05,
            narrative_driven=False, as_of_date="2024-12-31",
        )
        qf = QualityFacts(
            founder_tenure_years=12.0, roiic_5yr_avg=0.20,
            profitability_path_clear=True, as_of_date="2024-12-31",
        )
        outcome = classify_ticker(
            "ZRULE", as_of="2024-12-31",
            data_adapter=_StubData(sf), quality_adapter=_StubQual(qf),
            persist=False, llm_client=None,
        )
        assert outcome.classification_method == "rule"
        assert outcome.llm_tiebreaker is None

        with live_conn_raw.cursor() as cur:
            cur.execute(
                """
                INSERT INTO mode_classifications (
                    classification_id, ticker, final_mode,
                    company_quality_flag, classification_method,
                    rule_outcomes, llm_tiebreaker, recheck_status,
                    prior_classification_id, parameters_version,
                    classified_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s::jsonb, NULL, %s,
                    NULL, NULL, %s
                )
                """,
                (
                    str(outcome.classification_id), outcome.ticker,
                    outcome.final_mode, outcome.company_quality_flag,
                    outcome.classification_method,
                    json.dumps(outcome.rule_outcomes, default=str),
                    outcome.recheck_status, outcome.classified_at,
                ),
            )

        # CHECK violation: method='llm_tiebreaker' but llm_tiebreaker IS NULL
        # OR method='rule' but llm_tiebreaker NOT NULL.
        with pytest.raises(psycopg.errors.CheckViolation):
            with live_conn_raw.transaction():
                with live_conn_raw.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO mode_classifications (
                            classification_id, ticker, final_mode,
                            company_quality_flag, classification_method,
                            rule_outcomes, llm_tiebreaker, recheck_status,
                            classified_at
                        ) VALUES (
                            gen_random_uuid(), 'XBAD1', 'B', 'STANDARD',
                            'llm_tiebreaker',
                            '{}'::jsonb, NULL, 'confirmed',
                            NOW()
                        )
                        """,
                    )

        with pytest.raises(psycopg.errors.CheckViolation):
            with live_conn_raw.transaction():
                with live_conn_raw.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO mode_classifications (
                            classification_id, ticker, final_mode,
                            company_quality_flag, classification_method,
                            rule_outcomes, llm_tiebreaker, recheck_status,
                            classified_at
                        ) VALUES (
                            gen_random_uuid(), 'XBAD2', 'B', 'STANDARD',
                            'rule',
                            '{}'::jsonb, '{"rating": "B"}'::jsonb, 'confirmed',
                            NOW()
                        )
                        """,
                    )

        # llm_tiebreaker path with a valid payload.
        tb_payload = {
            "rating": "B_prime",
            "self_consistency": {"agreement": 5, "samples": 5},
            "verbatim_evidence": ["market_cap=60B", "vol=0.22"],
        }
        with live_conn_raw.cursor() as cur:
            cur.execute(
                """
                INSERT INTO mode_classifications (
                    classification_id, ticker, final_mode,
                    company_quality_flag, classification_method,
                    rule_outcomes, llm_tiebreaker, recheck_status,
                    classified_at
                ) VALUES (
                    gen_random_uuid(), 'XLLM', 'B_prime', 'STANDARD',
                    'llm_tiebreaker',
                    '{}'::jsonb, %s::jsonb, 'confirmed',
                    NOW()
                ) RETURNING classification_id
                """,
                (json.dumps(tb_payload),),
            )
            (cls_id,) = cur.fetchone()
        assert cls_id is not None

    # ------------------------------------------------------------------
    # 5. anchor_drift orchestrator + sidecar
    # ------------------------------------------------------------------

    def test_live_anchor_drift_check_with_review_sidecar(
        self, live_conn_raw, live_conn, hmac_keys_class, savepoint
    ):
        """Insert watchlist + drift-check row directly, then test sidecar FK.

        The orchestrator's _persist creates a fresh connection (uses _dsn()),
        so for live-DB savepoint isolation we replicate its INSERT here;
        what we're testing is the migration-018 sidecar FK + CHECK.
        """
        import psycopg
        from src.p5_watchlist import add_to_watchlist

        # Insert watchlist via P5 path (needed for FK on subsequent writes).
        wl = _build_watchlist_input(ticker=f"{_TEST_TICKER}AD")
        add_to_watchlist(
            wl, conn=live_conn, hmac_key=hmac_keys_class["watchlist"]
        )

        # Insert anchor_drift_checks row with operator_decision=NULL
        # (per migration 018 — pending = row absent in sidecar).
        check_id = uuid4()
        forced_review = {
            "type": "pillar_drift",
            "surfaced_to": "operator",
            "operator_acknowledged_at": None,
            "operator_decision": None,
            "all_triggered": ["pillar_drift"],
        }
        c1_payload = {"drift_score": 0.42, "triggered": True,
                      "pillars_softened": [], "pillars_rewritten": ["moat"],
                      "diff_llm_model": "stub", "hmac_verified": True,
                      "error": None}
        c2_payload = {"triggered": False, "outcome_divergence_pp": 5.0}
        c3_payload = {"triggered": False, "days_since_reread": 30}
        with live_conn_raw.cursor() as cur:
            cur.execute(
                """
                INSERT INTO anchor_drift_checks (
                    check_id, ticker, check_date,
                    channel_1_pillar_drift,
                    channel_2_outcome_divergence,
                    channel_3_periodic_reread,
                    any_triggered, forced_review
                ) VALUES (
                    %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb,
                    true, %s::jsonb
                )
                """,
                (
                    str(check_id), wl.ticker, "2026-04-29",
                    json.dumps(c1_payload),
                    json.dumps(c2_payload),
                    json.dumps(c3_payload),
                    json.dumps(forced_review),
                ),
            )

        # Sidecar insert holds.
        with live_conn_raw.cursor() as cur:
            cur.execute(
                """
                INSERT INTO anchor_drift_review_decisions (
                    check_id, operator_decision, rationale, operator_id
                ) VALUES (
                    %s, 'revise_with_rationale',
                    'Pillar moat softened — refining claim language.',
                    'operator'
                )
                """,
                (str(check_id),),
            )

        # FK to a non-existent check_id must reject.
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            with live_conn_raw.transaction():
                with live_conn_raw.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO anchor_drift_review_decisions (
                            check_id, operator_decision, rationale
                        ) VALUES (
                            gen_random_uuid(),
                            'reaffirm', 'no rationale required'
                        )
                        """,
                    )

        # Sidecar CHECK: revise_with_rationale requires non-empty rationale.
        with pytest.raises(psycopg.errors.CheckViolation):
            with live_conn_raw.transaction():
                # Need a fresh check_id to avoid PK conflict.
                check_id_2 = uuid4()
                with live_conn_raw.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO anchor_drift_checks (
                            check_id, ticker, check_date,
                            channel_1_pillar_drift,
                            channel_2_outcome_divergence,
                            channel_3_periodic_reread,
                            any_triggered, forced_review
                        ) VALUES (
                            %s, %s, %s,
                            %s::jsonb, %s::jsonb, %s::jsonb,
                            true, %s::jsonb
                        )
                        """,
                        (
                            str(check_id_2), wl.ticker, "2026-04-30",
                            json.dumps(c1_payload),
                            json.dumps(c2_payload),
                            json.dumps(c3_payload),
                            json.dumps(forced_review),
                        ),
                    )
                    cur.execute(
                        """
                        INSERT INTO anchor_drift_review_decisions (
                            check_id, operator_decision, rationale
                        ) VALUES (
                            %s, 'revise_with_rationale', NULL
                        )
                        """,
                        (str(check_id_2),),
                    )

    # ------------------------------------------------------------------
    # 6. calibration capture (operator_overrides + recommendation_outcomes):
    # test removed 2026-05-23 with those tables dropped per mig 041 /
    # docs/superpowers/specs/2026-05-23-eval-loop-deletion-design.md.
    # ------------------------------------------------------------------


    # ------------------------------------------------------------------
    # 7. alert_channels.email_sender failure → system_errors
    # ------------------------------------------------------------------

    def test_live_system_errors_logging(
        self, live_conn, live_conn_raw, savepoint
    ):
        """Drive email_sender to its final-failure path with a stub SMTP
        client that always raises; verify the system_errors row is written
        with source='alert_channels.email_sender', error_type='smtp_send_failed',
        escalated_to_alert=true.

        Uses the ``_NoCommitConn`` wrapper so the email_sender's internal
        ``conn.commit()`` calls (used to release FOR UPDATE row locks)
        don't escape the savepoint and persist test rows.
        """
        from alert_channels import (
            EMAIL_ERROR_SOURCE,
            MAX_EMAIL_ATTEMPTS,
            SEVERITY_M3,
        )
        from alert_channels.email_sender import (
            AlertRow,
            SmtpConfig,
            send_email_for_alert,
        )

        # Insert a severity-3 unread_alerts row.
        alert_id = uuid4()
        with live_conn_raw.cursor() as cur:
            cur.execute(
                """
                INSERT INTO unread_alerts (
                    alert_id, severity, alert_type, ticker, summary,
                    payload, email_send_attempts
                ) VALUES (
                    %s, 3, 'materiality_m3', %s,
                    'M-3 stub for system_errors test',
                    '{}'::jsonb, %s
                )
                """,
                (str(alert_id), _TEST_TICKER, MAX_EMAIL_ATTEMPTS - 1),
            )

        cfg = SmtpConfig(
            host="smtp.example.invalid", port=587,
            username="u", password="p",
            sender="alerts@example.invalid",
            recipient="op@example.invalid",
            use_tls=False,
        )

        class _BoomSMTP:
            def starttls(self, *a, **kw): pass
            def login(self, *a, **kw):
                raise RuntimeError("smtp_login_unreachable")
            def sendmail(self, *a, **kw): pass
            def quit(self): pass

        result = send_email_for_alert(
            live_conn,  # NoCommitConn wrapper to keep savepoint isolation
            AlertRow(
                alert_id=alert_id, severity=SEVERITY_M3,
                alert_type="materiality_m3", ticker=_TEST_TICKER,
                summary="stub", payload={},
                drill_link_recommendation_id=None,
                email_send_attempts=MAX_EMAIL_ATTEMPTS - 1,
            ),
            cfg,
            smtp_client_factory=lambda: _BoomSMTP(),
            now=_dt.datetime(2026, 4, 29, tzinfo=_dt.timezone.utc),
        )

        assert result.sent is False
        assert result.attempt_number == MAX_EMAIL_ATTEMPTS
        assert result.queued_for_session_push is True

        # system_errors row written with the documented source/type.
        with live_conn_raw.cursor() as cur:
            cur.execute(
                """
                SELECT source, error_type, escalated_to_alert, blocked_decision
                FROM system_errors
                WHERE source = %s
                  AND error_type = 'smtp_send_failed'
                  AND blocked_decision = %s
                """,
                (EMAIL_ERROR_SOURCE, f"email_alert_{alert_id}"),
            )
            row = cur.fetchone()
        assert row is not None
        assert row[0] == "alert_channels.email_sender"
        assert row[1] == "smtp_send_failed"
        assert row[2] is True

    # ------------------------------------------------------------------
    # 8. Full P5 → P7 → audit-chain meta-test
    # ------------------------------------------------------------------

    def test_live_full_funnel_p5_to_p7_to_audit_chain(
        self, live_conn, live_conn_raw, hmac_keys_class, savepoint
    ):
        """Meta-test: P5 add → P7 emit → 5 audit_provenance rows, chain
        verifies under the documented HMAC keys."""
        from src.audit_trail.hmac_verify import verify_chain
        from src.audit_trail.loader import get_chain_for_recommendation
        from src.p5_watchlist import add_to_watchlist
        from src.p7_recommendation_emitter import emit_recommendation

        wl_inp = _build_watchlist_input(ticker=f"{_TEST_TICKER}FF")
        wl_outcome = add_to_watchlist(
            wl_inp, conn=live_conn, hmac_key=hmac_keys_class["watchlist"]
        )
        assert wl_outcome.inserted is True

        emit_inp = _build_emit_inputs(ticker=wl_inp.ticker)
        rec_outcome = emit_recommendation(
            emit_inp, conn=live_conn, hmac_key=hmac_keys_class["audit"]
        )
        assert rec_outcome.recommendation == "BUY"
        assert len(rec_outcome.audit_chain_ids) == 5

        # 5 audit_provenance rows.
        with live_conn_raw.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM audit_provenance "
                "WHERE recommendation_id = %s",
                (str(rec_outcome.recommendation_id),),
            )
            (n,) = cur.fetchone()
        assert n == 5

        # Chain verifies fully under the audit HMAC key.
        rows = get_chain_for_recommendation(live_conn, rec_outcome.recommendation_id)
        assert len(rows) == 5
        result = verify_chain(rows, key=hmac_keys_class["audit"])
        assert result.mode == "keyed"
        assert result.all_ok, [
            (r.audit_id, r.signature_ok, r.parent_link_ok)
            for r in result.rows
            if not r.ok
        ]

        # 1 execution_recommendations row.
        with live_conn_raw.cursor() as cur:
            cur.execute(
                "SELECT recommendation, conviction FROM execution_recommendations "
                "WHERE recommendation_id = %s",
                (str(rec_outcome.recommendation_id),),
            )
            r = cur.fetchone()
        assert r is not None
        assert r[0] == "BUY"

    # ------------------------------------------------------------------
    # 9. Transaction-boundary regression: P7 emitter atomic 6-row write.
    # ------------------------------------------------------------------

    def test_live_p7_emit_partial_failure_rolls_back_no_orphan_rows(
        self, live_conn_raw, hmac_keys_class, savepoint
    ):
        """A mid-batch failure during emit_recommendation must leave NO rows
        in execution_recommendations OR audit_provenance for that
        recommendation_id. Per Section 5 Q1 audit-chain lock.

        Setup: monkey-patch ``_do_persist`` to fail after the 3rd
        audit_provenance INSERT; verify the recommendation row + earlier
        audit rows are not visible after the with-block raises.
        """
        from src.p7_recommendation_emitter import emit_recommendation
        from src.p7_recommendation_emitter import emitter as emitter_mod

        original = emitter_mod._do_persist
        # Live raw conn is psycopg3 → has .transaction(). Use it.
        wrapped = _NoCommitConn(live_conn_raw)

        def failing_do_persist(conn, row, audit_rows):
            cur = conn.cursor()
            try:
                cur.execute(
                    """
                    INSERT INTO execution_recommendations (
                        recommendation_id, ticker, date, recommendation,
                        conviction, conviction_breakdown,
                        conviction_pending_transition, conviction_pending_target,
                        conviction_changed_from_prior, conviction_flip_count_30d,
                        conviction_frozen_pending_review,
                        mode, company_quality_flag, mode_certainty,
                        sizing_suggestion, execution_context, trigger_metadata,
                        audit_available, rule_engine_version, debate_prompt_version,
                        model_id, model_version, parameters_version,
                        audit_signature, created_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s::jsonb,
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        %s::jsonb, %s::jsonb, %s::jsonb,
                        %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        str(row["recommendation_id"]), row["ticker"], row["date"],
                        row["recommendation"], row["conviction"],
                        json.dumps(row["conviction_breakdown"], default=str),
                        row["conviction_pending_transition"],
                        row["conviction_pending_target"],
                        row["conviction_changed_from_prior"],
                        row["conviction_flip_count_30d"],
                        row["conviction_frozen_pending_review"],
                        row["mode"], row["company_quality_flag"],
                        row["mode_certainty"],
                        json.dumps(row["sizing_suggestion"], default=str),
                        json.dumps(row["execution_context"], default=str),
                        json.dumps(row["trigger_metadata"], default=str),
                        row["audit_available"], row["rule_engine_version"],
                        row["debate_prompt_version"], row["model_id"],
                        row["model_version"], row["parameters_version"],
                        row["audit_signature"], row["created_at"],
                    ),
                )
                # Insert only 2 of 5 audit rows, then raise.
                for i, ar in enumerate(audit_rows):
                    if i >= 2:
                        raise RuntimeError(
                            "simulated CHECK violation on audit_provenance"
                        )
                    cur.execute(
                        """
                        INSERT INTO audit_provenance (
                            audit_id, recommendation_id, stage,
                            drill_payload, hmac_signature, parent_audit_id,
                            versions, created_at
                        ) VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s::jsonb, %s)
                        """,
                        (
                            str(ar["audit_id"]),
                            str(ar["recommendation_id"]),
                            ar["stage"],
                            json.dumps(ar["drill_payload"], default=str),
                            ar["hmac_signature"],
                            str(ar["parent_audit_id"]) if ar["parent_audit_id"] else None,
                            json.dumps(ar["versions"], default=str),
                            ar["created_at"],
                        ),
                    )
            finally:
                cur.close()

        wl_inp = _build_watchlist_input(ticker=f"{_TEST_TICKER}TX")
        from src.p5_watchlist import add_to_watchlist
        add_to_watchlist(
            wl_inp, conn=wrapped, hmac_key=hmac_keys_class["watchlist"]
        )

        emit_inp = _build_emit_inputs(ticker=wl_inp.ticker)
        # Pre-build an EmitOutcome to grab the rec_id, but emit_recommendation
        # also generates one inside; we'll capture from the raised state by
        # selecting on ticker.
        emitter_mod._do_persist = failing_do_persist
        try:
            with pytest.raises(RuntimeError, match="simulated CHECK"):
                emit_recommendation(
                    emit_inp,
                    conn=wrapped,
                    hmac_key=hmac_keys_class["audit"],
                )
        finally:
            emitter_mod._do_persist = original

        # NO execution_recommendations OR audit_provenance rows must exist
        # for this ticker (the entire batch should have been rolled back).
        with live_conn_raw.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM execution_recommendations "
                "WHERE ticker = %s",
                (wl_inp.ticker,),
            )
            (n_recs,) = cur.fetchone()
            cur.execute(
                "SELECT count(*) FROM audit_provenance ap "
                "JOIN execution_recommendations er "
                "  ON er.recommendation_id = ap.recommendation_id "
                "WHERE er.ticker = %s",
                (wl_inp.ticker,),
            )
            (n_audit,) = cur.fetchone()
        assert n_recs == 0, (
            f"Expected 0 execution_recommendations rows on rolled-back batch "
            f"(no orphan recommendation), got {n_recs}"
        )
        assert n_audit == 0, (
            f"Expected 0 audit_provenance rows on rolled-back batch "
            f"(no broken audit chain), got {n_audit}"
        )


# ---------------------------------------------------------------------------
# Idempotency live-DB regression tests (idempotency audit, migration 022)
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("hmac_keys_class")
class TestLiveIdempotencyContracts:
    """Live-DB regression for the 4 write paths fixed in the idempotency audit:
      1. daily_refresh_log     ON CONFLICT (ticker, date) DO NOTHING
      2. materiality_events    ON CONFLICT (ticker, event_date, ...) DO NOTHING
      3. anchor_drift_checks   ON CONFLICT (ticker, check_date) DO NOTHING
      4. materiality_classifier_drift  ON CONFLICT (period) DO NOTHING

    Each test calls the underlying writer twice with identical inputs and
    asserts exactly 1 row exists post-write — i.e., the second call is a
    silent no-op rather than a UniqueViolation crash or a duplicate row.

    Skipped by default; run with ``pytest -m integration_live``.
    """

    def test_anchor_drift_double_write_is_idempotent(
        self, live_conn_raw, savepoint
    ):
        """Calling _persist twice with same (ticker, check_date) → 1 row."""
        from anchor_drift.orchestrator import _persist
        from anchor_drift.channel_1_pillar_drift import PillarDriftResult
        from anchor_drift.channel_2_outcome_divergence import (
            OutcomeDivergenceResult,
        )
        from anchor_drift.channel_3_periodic_reread import (
            PeriodicRereadResult,
        )

        ticker = f"ZZID{secrets.token_hex(2).upper()}"
        check_date = "2026-04-29"

        # Build minimal-shape channel results (no triggers; clean state).
        c1 = PillarDriftResult(
            drift_score=0.0, pillars_softened=[], pillars_rewritten=[],
            diff_llm_model="stub", triggered=False, hmac_verified=True,
        )
        c2 = OutcomeDivergenceResult(
            last_earnings_date="2026-01-31",
            revenue_actual=None, revenue_projected=None,
            margin_actual=None, margin_projected=None,
            fcf_actual=None, fcf_projected=None,
            triggered=False, hmac_verified=True,
        )
        c3 = PeriodicRereadResult(
            last_reread_date=None, days_elapsed=0,
            cadence_threshold_days=180, triggered=False,
        )

        # Patch _dsn so _persist uses the test connection's DSN. We can't
        # easily inject the connection — _persist opens its own. Skip if
        # we can't redirect.
        import anchor_drift.orchestrator as mod
        original_dsn = mod._dsn
        mod._dsn = lambda: LIVE_DSN
        try:
            cid_1 = _persist(
                ticker=ticker, check_date=check_date,
                c1=c1, c2=c2, c3=c3,
                any_triggered=False, forced_review=None,
                parameters_version=None,
            )
            cid_2 = _persist(
                ticker=ticker, check_date=check_date,
                c1=c1, c2=c2, c3=c3,
                any_triggered=False, forced_review=None,
                parameters_version=None,
            )
        finally:
            mod._dsn = original_dsn

        # Both calls must return the SAME check_id (the conflict path
        # re-fetches the prior row's id).
        assert cid_1 == cid_2, (
            f"Idempotency contract: second _persist call must return "
            f"the prior row's check_id; got {cid_1} vs {cid_2}"
        )

        # And exactly ONE row must exist for this (ticker, check_date).
        with live_conn_raw.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM anchor_drift_checks "
                "WHERE ticker = %s AND check_date = %s",
                (ticker, check_date),
            )
            (n,) = cur.fetchone()
        assert n == 1, (
            f"Expected exactly 1 anchor_drift_checks row after 2 _persist "
            f"calls with same (ticker, check_date); got {n}"
        )

        # Clean up the committed test row (anchor_drift_checks is
        # append-only; disable trigger to clean).
        with live_conn_raw.cursor() as cur:
            cur.execute(
                "ALTER TABLE anchor_drift_checks "
                "DISABLE TRIGGER anchor_drift_no_modify"
            )
            cur.execute(
                "DELETE FROM anchor_drift_checks WHERE ticker = %s",
                (ticker,),
            )
            cur.execute(
                "ALTER TABLE anchor_drift_checks "
                "ENABLE TRIGGER anchor_drift_no_modify"
            )
        live_conn_raw.commit()
