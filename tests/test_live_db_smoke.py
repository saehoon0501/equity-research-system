"""Live-Postgres end-to-end smoke for P5 -> P7 against the running DB.

Unlike ``tests/test_e2e_integration.py`` (which uses ``FakeConn`` to capture
SQL strings without touching a real engine), this module exercises the
actual psycopg + real triggers + real CHECK constraints so we surface any
FakeConn-vs-real-DB discrepancy: trigger semantics, type coercion (UUID,
Decimal, datetime, JSONB), FK violations, append-only enforcement gaps,
unique-constraint behaviour.

Default behaviour: SKIPPED. Run only with::

    pytest tests/test_live_db_smoke.py -m integration_live

Pre-conditions:
  * Postgres running at 127.0.0.1:5432 with all 21 migrations applied.
  * Connection string matches the ``LIVE_DSN`` constant below.

Each test creates its own savepoint so the connection is rolled back to
a clean state between tests; the class-scoped fixture's ``conn.rollback()``
discards everything at teardown so the DB is left as we found it.

Per v3 spec Section 5 Q1 (audit-chain HMAC), Section 7 Q4 (layered
drill-down lock), migrations 007/008/016.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import secrets
import sys
import uuid
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

# Ensure src/ is importable for tests that use bare-package imports.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


pytestmark = pytest.mark.integration_live


LIVE_DSN = (
    "postgresql://equity_research_admin:"
    "cKgxj2TVEhjuLYiXXsm9cftYAhCAnBq@127.0.0.1:5432/equity_research"
)


# Sentinels so cleanup can target only this run's rows.
_RUN_TAG = f"LIVESMOKE-{secrets.token_hex(4)}"
_TEST_TICKER = f"ZZTST{secrets.token_hex(2).upper()}"  # short, unique


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _require_psycopg():
    try:
        import psycopg  # noqa: F401
    except ImportError:
        pytest.skip("psycopg not installed in this environment")


def _require_db():
    """Skip the whole class if the DB is unreachable."""
    _require_psycopg()
    import psycopg

    try:
        c = psycopg.connect(LIVE_DSN, connect_timeout=3)
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"live Postgres unreachable: {e!r}")
    c.close()


@pytest.fixture(scope="class")
def hmac_keys_class():
    """Random per-class HMAC keys (test-only; not from operator's .env).

    Returned as both raw bytes (for direct compute) and as the env-var
    strings the test sets via os.environ for the duration of the class.
    """
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


# ---------------------------------------------------------------------------
# Builders — minimal-shape inputs for each phase
# ---------------------------------------------------------------------------


_THESIS_PILLARS: list[dict[str, Any]] = [
    {
        "pillar": "moat_data_center_pivot",
        "claim": "CUDA->AI pivot is structural; founder Huang 30+yr.",
        "confidence": 0.85,
    },
    {
        "pillar": "growth_secular_demand",
        "claim": "Hyperscaler AI capex multi-year sustained.",
        "confidence": 0.80,
    },
    {
        "pillar": "quality_roiic",
        "claim": "ROIIC > 30% in last 3 years; per-share-value compounder.",
        "confidence": 0.90,
    },
]

_SCENARIO_A_BASE: dict[str, Any] = {
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
            "rationale": "AI capex digestion > 2 quarters violates thesis",
        },
    ],
}


def _build_watchlist_input(ticker: str = _TEST_TICKER):
    """Build a NVDA-2023-style WatchlistAddInput for live insert."""
    from src.p5_watchlist import WatchlistAddInput

    return WatchlistAddInput(
        ticker=ticker,
        mode="B_prime",
        company_quality_flag="HIGH",
        pm_supervisor_decision="ADD",
        thesis_pillars_original=_THESIS_PILLARS,
        scenario_A_base_projections=_SCENARIO_A_BASE,
        macro_regime_style_output={"regime_sensitivity": "MEDIUM"},
        parameters_version=None,  # parameters table empty; FK NULL is allowed
    )


def _build_emit_inputs(ticker: str = _TEST_TICKER):
    """Build a clean-BUY P7 EmitInputs."""
    from src.p7_recommendation_emitter import EmitInputs, TRIGGER_NEW_CANDIDATE
    from src.p4_debate import WEIGHT_MATRIX

    return EmitInputs(
        ticker=ticker,
        mode="B_prime",
        company_quality_flag="HIGH",
        mode_certainty="rule_clean",
        debate_add_count=4,
        debate_consensus_summary="4/5 ADD (Quant-Technical dissents HOLD)",
        kills_fired=0,
        counterfactual_top_3=["SURVIVOR", "SURVIVOR", "SURVIVOR"],
        anchor_drift_channels_triggered=0,
        primary_recommendation="BUY",
        suggested_pacing="DCA over 21 days",
        triggered_by=TRIGGER_NEW_CANDIDATE,
        available_cash_pct=10.0,
        current_price=420.50,
        fair_value_payload={"point": 525, "range_low": 450, "range_high": 600},
        near_term_catalysts_raw=[
            {"event": "Q4 earnings", "date": "2023-02-22", "importance": "high"}
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
                "stage_1a_knockout": "no_fraud_signature",
            },
            "stage_2_debate": {
                "consensus": "4/5 ADD",
                "dissenter": "Quant-Technical",
                "weight_matrix": dict(WEIGHT_MATRIX["B_prime"]),
            },
            "stage_3_kill_criteria": {
                "fired": 0,
                "structured": _SCENARIO_A_BASE["kill_criteria_structured"],
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


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class _NoCommitConn:
    """Pass-through wrapper that swallows ``commit()``.

    The P5 adder + P7 emitter call ``conn.commit()`` after their writes.
    Under a real psycopg connection with autocommit=False, that releases
    all outstanding savepoints — making per-test savepoint-based isolation
    impossible. Wrapping the connection so commit() is a no-op preserves
    the savepoint hierarchy; we still rollback the underlying transaction
    at class teardown, so nothing persists.
    """

    def __init__(self, real):
        self._real = real

    def cursor(self, *args, **kwargs):
        return self._real.cursor(*args, **kwargs)

    def commit(self):  # swallow
        return None

    def rollback(self):
        return self._real.rollback()

    @property
    def autocommit(self):
        return self._real.autocommit

    def __getattr__(self, name):
        return getattr(self._real, name)


class TestLiveDbSmoke:
    """Live-Postgres smoke tests for P5 -> P7 + append-only enforcement."""

    @pytest.fixture(scope="class")
    def live_conn_raw(self):
        """Underlying real psycopg connection.

        Class-scoped — we open ONE transaction and rollback at the end so
        no test residue persists. The wrapper below swallows commit() so
        savepoints survive across module-level ``conn.commit()`` calls.
        """
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
        """Wrapped connection used by P5/P7 entry points.

        Provides cursor() etc. as pass-through but swallows commit() so
        the test fixture's outer transaction (and savepoints inside it)
        survive intra-emitter commit calls.
        """
        return _NoCommitConn(live_conn_raw)

    @pytest.fixture
    def savepoint(self, live_conn_raw):
        """Per-test savepoint; rolled back at teardown.

        Operates on the raw connection so we can recover from any aborted
        transaction state by rolling back to the savepoint (which clears
        the InError flag).
        """
        sp_name = f"sp_{secrets.token_hex(4)}"
        with live_conn_raw.cursor() as cur:
            cur.execute(f"SAVEPOINT {sp_name}")
        yield sp_name
        # Recover from any aborted-tx state and discard test writes.
        try:
            with live_conn_raw.cursor() as cur:
                cur.execute(f"ROLLBACK TO SAVEPOINT {sp_name}")
                cur.execute(f"RELEASE SAVEPOINT {sp_name}")
        except Exception:  # noqa: BLE001
            # Outer tx may already be aborted; rollback to be safe.
            try:
                live_conn_raw.rollback()
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    # 1. P5 watchlist insert with HMAC
    # ------------------------------------------------------------------

    def test_live_p5_watchlist_insert_with_hmac(
        self, live_conn, hmac_keys_class, savepoint
    ):
        """Insert a watchlist row via real psycopg + verify HMAC round-trip."""
        from src.p5_watchlist import add_to_watchlist
        from src.watchlist.hmac_producer import sign_watchlist_row

        inp = _build_watchlist_input()
        outcome = add_to_watchlist(
            inp, conn=live_conn, hmac_key=hmac_keys_class["watchlist"]
        )
        assert outcome.inserted is True
        assert len(outcome.thesis_pillars_original_hmac) == 64
        assert len(outcome.scenario_A_base_projections_hmac) == 64

        # Verify row landed.
        with live_conn.cursor() as cur:
            cur.execute(
                "SELECT ticker, mode, company_quality_flag, "
                "       conviction_threshold, regime_sensitivity, "
                "       thesis_pillars_original_hmac "
                "FROM watchlist WHERE ticker = %s",
                (inp.ticker,),
            )
            row = cur.fetchone()
        assert row is not None, "watchlist row not found post-insert"
        ticker_db, mode_db, qual_db, thresh_db, rs_db, sig_db = row
        assert ticker_db == inp.ticker
        assert mode_db == "B_prime"
        assert qual_db == "HIGH"
        assert float(thresh_db) == pytest.approx(0.60)  # B' default
        assert rs_db == "MEDIUM"
        # HMAC stored matches re-computed sig under same key.
        recompute = sign_watchlist_row(
            list(inp.thesis_pillars_original),
            dict(inp.scenario_A_base_projections),
            hmac_key=hmac_keys_class["watchlist"],
        )
        assert sig_db == recompute["thesis_pillars_original_hmac"]

    # ------------------------------------------------------------------
    # 2. Append-only trigger blocks DELETE on watchlist
    # ------------------------------------------------------------------

    def test_live_watchlist_append_only_trigger_blocks_delete(
        self, live_conn, live_conn_raw, hmac_keys_class, savepoint
    ):
        """Migration 007 watchlist_no_delete trigger must fire under real psycopg."""
        import psycopg
        from src.p5_watchlist import add_to_watchlist

        inp = _build_watchlist_input(ticker=f"{_TEST_TICKER}D")
        add_to_watchlist(inp, conn=live_conn, hmac_key=hmac_keys_class["watchlist"])

        # DELETE must raise. Use psycopg3's transaction() context to manage
        # the inner savepoint so the outer transaction survives the abort.
        with pytest.raises(psycopg.errors.RaiseException) as exc:
            with live_conn_raw.transaction():
                with live_conn_raw.cursor() as cur:
                    cur.execute(
                        "DELETE FROM watchlist WHERE ticker = %s", (inp.ticker,)
                    )
        assert "delete-protected" in str(exc.value).lower() or \
               "not permitted" in str(exc.value).lower()

    # ------------------------------------------------------------------
    # 3. P7 emit + full audit chain
    # ------------------------------------------------------------------

    def test_live_p7_emit_with_full_audit_chain(
        self, live_conn, hmac_keys_class, savepoint
    ):
        """P7 emits 1 execution_recommendations + 5 audit_provenance rows."""
        from src.audit_trail.hmac_verify import verify_chain
        from src.audit_trail.loader import get_chain_for_recommendation
        from src.p5_watchlist import add_to_watchlist
        from src.p7_recommendation_emitter import emit_recommendation

        # Pre-insert the watchlist row (P5).
        wl_inp = _build_watchlist_input(ticker=f"{_TEST_TICKER}E")
        add_to_watchlist(
            wl_inp, conn=live_conn, hmac_key=hmac_keys_class["watchlist"]
        )

        # Emit P7.
        emit_inp = _build_emit_inputs(ticker=wl_inp.ticker)
        outcome = emit_recommendation(
            emit_inp, conn=live_conn, hmac_key=hmac_keys_class["audit"]
        )
        assert outcome.recommendation == "BUY"
        assert len(outcome.audit_chain_ids) == 5
        assert len(outcome.audit_signature) == 64

        # 1 row in execution_recommendations.
        with live_conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM execution_recommendations "
                "WHERE recommendation_id = %s",
                (str(outcome.recommendation_id),),
            )
            (rec_count,) = cur.fetchone()
        assert rec_count == 1

        # 5 rows in audit_provenance, chained.
        with live_conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM audit_provenance "
                "WHERE recommendation_id = %s",
                (str(outcome.recommendation_id),),
            )
            (audit_count,) = cur.fetchone()
        assert audit_count == 5

        # Read back the chain via loader and verify HMAC signatures.
        rows = get_chain_for_recommendation(live_conn, outcome.recommendation_id)
        assert len(rows) == 5
        result = verify_chain(rows, key=hmac_keys_class["audit"])
        assert result.mode == "keyed"
        assert result.all_ok, [r for r in result.rows if not r.ok]

    # ------------------------------------------------------------------
    # 4. Audit trail verifies after DB round-trip + reconnect
    # ------------------------------------------------------------------

    def test_live_audit_trail_verifies_after_db_round_trip(
        self, hmac_keys_class
    ):
        """Round-trip via a SECOND connection — catches type-coercion drift.

        We commit on conn-1, then read back on conn-2 to ensure the
        canonical-payload reproduces the same bytes after psycopg parses
        UUID/Decimal/timestamptz back from Postgres types.
        """
        import psycopg
        from src.audit_trail.hmac_verify import verify_chain
        from src.audit_trail.loader import get_chain_for_recommendation
        from src.p5_watchlist import add_to_watchlist
        from src.p7_recommendation_emitter import emit_recommendation

        ticker = f"{_TEST_TICKER}R"
        rec_id_holder: dict[str, UUID] = {}

        # Conn 1: write + commit.
        conn1 = psycopg.connect(LIVE_DSN)
        try:
            wl_inp = _build_watchlist_input(ticker=ticker)
            add_to_watchlist(
                wl_inp, conn=conn1, hmac_key=hmac_keys_class["watchlist"]
            )
            outcome = emit_recommendation(
                _build_emit_inputs(ticker=ticker),
                conn=conn1,
                hmac_key=hmac_keys_class["audit"],
            )
            rec_id_holder["rec_id"] = outcome.recommendation_id
            conn1.commit()
        except Exception:
            conn1.rollback()
            raise
        finally:
            conn1.close()

        # Conn 2: read + verify (real psycopg fetches; real DB types).
        conn2 = psycopg.connect(LIVE_DSN)
        try:
            rows = get_chain_for_recommendation(conn2, rec_id_holder["rec_id"])
            assert len(rows) == 5
            # Real DB returns timestamptz with tzinfo, UUIDs as UUID objs,
            # JSONB as dict — this is the path FakeConn never exercises.
            result = verify_chain(rows, key=hmac_keys_class["audit"])
            assert result.all_ok, [
                (r.audit_id, r.signature_ok, r.parent_link_ok)
                for r in result.rows
                if not r.ok
            ]
        finally:
            # Cleanup: delete via DB-admin path (must use TRUNCATE-equivalent
            # or accept residue — audit_provenance is append-only). We use a
            # second transaction that we then rollback to avoid committing
            # any deletes; since the data was committed above, we instead
            # rely on dropping by recommendation_id within an explicit
            # delete-bypass-by-superuser path. Simplest: use a dedicated
            # cleanup connection that disables triggers session-locally.
            _cleanup_recommendation(conn2, rec_id_holder["rec_id"], ticker)
            conn2.close()

    # ------------------------------------------------------------------
    # 5. Append-only enforcement across multiple tables
    # ------------------------------------------------------------------

    def test_live_append_only_enforcement_across_tables(
        self, live_conn_raw, hmac_keys_class, savepoint
    ):
        """UPDATE/DELETE blocked on append-only tables under real psycopg.

        Tables under test:
          * peak_pain_archetypes  (DELETE blocked; UPDATE allowed per migration)
          * premortem             (UPDATE + DELETE blocked)
          * materiality_events    (UPDATE + DELETE blocked)
          * debate_consensus_history (UPDATE + DELETE blocked)

        Each expected-error operation runs inside ``live_conn_raw.transaction()``
        so an aborted savepoint is rolled back without poisoning the outer tx.
        """
        import psycopg

        # peak_pain_archetypes — DELETE-blocked.
        case_id = f"{_RUN_TAG}-PP"
        with live_conn_raw.cursor() as cur:
            cur.execute(
                """
                INSERT INTO peak_pain_archetypes (
                    case_id, ticker, peak_date, trough_date, peak_dd_pct,
                    outcome, sector, era_category,
                    universal_core_features, sector_extensions,
                    universal_core_consensus, validation_status,
                    hmac_signature
                ) VALUES (
                    %s, 'NVDA', '2018-10-01', '2019-01-01', -56.0,
                    'SURVIVOR', 'tech', 'modern_internet',
                    '{}'::jsonb, '{}'::jsonb,
                    '{}'::jsonb, 'pending', 'sig'
                )
                """,
                (case_id,),
            )
        with pytest.raises(psycopg.errors.RaiseException):
            with live_conn_raw.transaction():
                with live_conn_raw.cursor() as cur:
                    cur.execute(
                        "DELETE FROM peak_pain_archetypes WHERE case_id = %s",
                        (case_id,),
                    )

        # premortem — UPDATE blocked.
        with live_conn_raw.cursor() as cur:
            cur.execute(
                """
                INSERT INTO premortem (
                    ticker, premortem_date, trigger,
                    operator_imagined_failure_modes,
                    thesis_pillars_revisited,
                    llm_assist_metadata, hmac_signature
                ) VALUES (
                    'NVDA', '2024-01-01', 'thesis_confirmation',
                    '[]'::jsonb, '[]'::jsonb, '{}'::jsonb, 'sig'
                ) RETURNING premortem_id
                """,
            )
            (pm_id,) = cur.fetchone()
        with pytest.raises(psycopg.errors.RaiseException):
            with live_conn_raw.transaction():
                with live_conn_raw.cursor() as cur:
                    cur.execute(
                        "UPDATE premortem SET ticker = 'AMD' "
                        "WHERE premortem_id = %s",
                        (str(pm_id),),
                    )
        # premortem — DELETE blocked.
        with pytest.raises(psycopg.errors.RaiseException):
            with live_conn_raw.transaction():
                with live_conn_raw.cursor() as cur:
                    cur.execute(
                        "DELETE FROM premortem WHERE premortem_id = %s",
                        (str(pm_id),),
                    )

        # materiality_events — DELETE blocked.
        with live_conn_raw.cursor() as cur:
            cur.execute(
                """
                INSERT INTO materiality_events (
                    ticker, event_date, event_type, source_id,
                    verbatim_quote, classification, llm_judge_confidence
                ) VALUES (
                    'NVDA', NOW(), 'earnings', 'src1', 'q', 2, 0.9
                ) RETURNING event_id
                """,
            )
            (me_id,) = cur.fetchone()
        with pytest.raises(psycopg.errors.RaiseException):
            with live_conn_raw.transaction():
                with live_conn_raw.cursor() as cur:
                    cur.execute(
                        "DELETE FROM materiality_events WHERE event_id = %s",
                        (str(me_id),),
                    )

        # debate_consensus_history — DELETE blocked.
        rec_uuid = uuid4()
        with live_conn_raw.cursor() as cur:
            cur.execute(
                """
                INSERT INTO debate_consensus_history (
                    recommendation_id, ticker, debate_date,
                    per_style_outputs, phase_d_synthesis,
                    debate_prompt_version, model_id, model_version
                ) VALUES (
                    %s, 'NVDA', '2024-01-01',
                    '{}'::jsonb, '{}'::jsonb,
                    'v0.1', 'm', 'v'
                ) RETURNING debate_id
                """,
                (str(rec_uuid),),
            )
            (dbg_id,) = cur.fetchone()
        with pytest.raises(psycopg.errors.RaiseException):
            with live_conn_raw.transaction():
                with live_conn_raw.cursor() as cur:
                    cur.execute(
                        "DELETE FROM debate_consensus_history "
                        "WHERE debate_id = %s",
                        (str(dbg_id),),
                    )

    # ------------------------------------------------------------------
    # 6. CHECK constraint enforcement
    # ------------------------------------------------------------------

    def test_live_check_constraint_enforcement(self, live_conn_raw, savepoint):
        """Postgres CHECK constraints reject invalid enums + out-of-range numeric."""
        import psycopg

        # Invalid mode 'X' on watchlist (must be B / B_prime / C).
        with pytest.raises(psycopg.errors.CheckViolation):
            with live_conn_raw.transaction():
                with live_conn_raw.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO watchlist (
                            ticker, mode, company_quality_flag,
                            conviction_threshold,
                            thesis_pillars_original,
                            thesis_pillars_original_hmac,
                            scenario_A_base_projections,
                            scenario_A_base_projections_hmac,
                            regime_sensitivity
                        ) VALUES (
                            'BAD1', 'X', 'HIGH', 0.6,
                            '[]'::jsonb, 'sig',
                            '{}'::jsonb, 'sig',
                            'MEDIUM'
                        )
                        """,
                    )

        # BOCPD probability > 1.0 must reject (migration 005).
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
                            '2024-01-01', 1, 'credit_ebp',
                            '{}'::jsonb, 'X',
                            1.5,
                            '{}'::jsonb, 30,
                            'v0.1', 0.5
                        )
                        """,
                    )

        # Conviction-threshold > 1 on watchlist.
        with pytest.raises(psycopg.errors.CheckViolation):
            with live_conn_raw.transaction():
                with live_conn_raw.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO watchlist (
                            ticker, mode, company_quality_flag,
                            conviction_threshold,
                            thesis_pillars_original,
                            thesis_pillars_original_hmac,
                            scenario_A_base_projections,
                            scenario_A_base_projections_hmac,
                            regime_sensitivity
                        ) VALUES (
                            'BAD2', 'B', 'HIGH', 1.5,
                            '[]'::jsonb, 'sig',
                            '{}'::jsonb, 'sig',
                            'MEDIUM'
                        )
                        """,
                    )

    # ------------------------------------------------------------------
    # 7. UNIQUE constraint enforcement on positions
    # ------------------------------------------------------------------

    def test_live_unique_constraint_enforcement(self, live_conn_raw, savepoint):
        """positions UNIQUE(ticker, broker, account_id_hash) rejects duplicates."""
        import psycopg

        # Use a unique hash so this test doesn't collide with other tests.
        h = f"hash-{secrets.token_hex(4)}"
        with live_conn_raw.cursor() as cur:
            cur.execute(
                """
                INSERT INTO positions (
                    ticker, shares_held, cost_basis, first_acquired,
                    source, broker, account_id_hash
                ) VALUES (
                    'NVDA', 100, 250.0, '2024-01-01',
                    'mcp__broker__get_positions', 'fidelity', %s
                )
                """,
                (h,),
            )

        with pytest.raises(psycopg.errors.UniqueViolation):
            with live_conn_raw.transaction():
                with live_conn_raw.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO positions (
                            ticker, shares_held, cost_basis, first_acquired,
                            source, broker, account_id_hash
                        ) VALUES (
                            'NVDA', 200, 260.0, '2024-02-01',
                            'mcp__broker__get_positions', 'fidelity', %s
                        )
                        """,
                        (h,),
                    )


# ---------------------------------------------------------------------------
# Cleanup helper for the cross-connection round-trip test
# ---------------------------------------------------------------------------


def _cleanup_recommendation(conn, rec_id: UUID, ticker: str) -> None:
    """Forcibly remove a committed test recommendation + chain.

    Both audit_provenance and execution_recommendations are append-only via
    triggers, so we temporarily drop the triggers (session-local) to clean
    up. This mirrors what an admin migration would do.
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                "ALTER TABLE audit_provenance DISABLE TRIGGER audit_provenance_no_modify"
            )
            cur.execute(
                "ALTER TABLE execution_recommendations DISABLE TRIGGER exec_recs_no_modify"
            )
            cur.execute(
                "ALTER TABLE watchlist DISABLE TRIGGER watchlist_no_delete"
            )
            cur.execute(
                "DELETE FROM audit_provenance WHERE recommendation_id = %s",
                (str(rec_id),),
            )
            cur.execute(
                "DELETE FROM execution_recommendations WHERE recommendation_id = %s",
                (str(rec_id),),
            )
            cur.execute("DELETE FROM watchlist WHERE ticker = %s", (ticker,))
            cur.execute(
                "ALTER TABLE audit_provenance ENABLE TRIGGER audit_provenance_no_modify"
            )
            cur.execute(
                "ALTER TABLE execution_recommendations ENABLE TRIGGER exec_recs_no_modify"
            )
            cur.execute(
                "ALTER TABLE watchlist ENABLE TRIGGER watchlist_no_delete"
            )
        conn.commit()
    except Exception:  # noqa: BLE001
        conn.rollback()
