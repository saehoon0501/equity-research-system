"""Tests for the counterfactual VETO pipeline (v3 spec Section 4.5 Q6 d').

Coverage:

    * Layer 1 cooling-off — mode-tuned floors (B/72h, B'/48h, C/24h).
    * Layer 2 multi-source — BOCPD collapse, verbatim primary, premortem.
    * Layer 3 veto — archetype-distribution rules.
    * Retrieval — Bayesian-shrunk Hamming, sector-extension on sector match,
      cross-sector zero-extension, active-pool filter.
    * Lifecycle — single-fire + M-3-driven re-fire (PB#5).
    * Orchestrator — end-to-end with stub DB writes.
    * Walkthrough #1 — PLTR-2022 SURVIVOR-dominant veto fires (Section 7.3a).
"""

from __future__ import annotations

import datetime as _dt
import json
from typing import Any

import pytest

from src.counterfactual_veto import (
    CUT_STATUS_NOT_ACTIVATED_BELOW_2X,
    MODE_2X_THRESHOLDS,
    MODE_COOLING_OFF_HOURS,
)
from src.counterfactual_veto.feature_extractor import (
    CandidateFeatures,
    candidate_from_dict,
)
from src.counterfactual_veto.layer1_cooling_off import evaluate_cooling_off
from src.counterfactual_veto.layer2_multi_source import (
    KillCriterionFire,
    collapse_bocpd_correlated,
    evaluate_multi_source,
    has_verbatim_primary,
)
from src.counterfactual_veto.layer3_veto import evaluate_veto, is_survivor_dominant
from src.counterfactual_veto.lifecycle import (
    VetoLifecycleRecord,
    operator_override,
    refresh_on_m3,
    release_by_recovery,
)
from src.counterfactual_veto.orchestrator import (
    CUT_STATUS_BLOCKED_VETO,
    CUT_STATUS_BLOCKED_MULTI_SOURCE,
    CUT_STATUS_PROCEED,
    CUT_STATUS_WAIT_COOLING_OFF,
    PipelineInputs,
    run_pipeline,
)
from src.counterfactual_veto.retrieval import (
    CatalogCase,
    archetype_distribution,
    load_catalog_from_pg,
    retrieve_top_3,
    score_case,
)
from tests.fixtures.realistic_catalog import (
    build_realistic_catalog,
    realistic_catalog_as_db_rows,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def pltr_2022_candidate() -> CandidateFeatures:
    """PLTR at 2022 trough — SURVIVOR-shaped structural features.

    Per Walkthrough #1 in Section 7.3a:
      - founder_insider_stake_direction: increasing (Karp + Thiel adding)
      - cash_runway: >24mo (net cash positive)
      - founder_in_place: yes (Karp + Thiel both active)
      - margin_trajectory: improving (GM expansion through 2022)
      - revenue_trajectory: growing (+24% YoY 2022)
      - industry_tailwind: intact (government / AI)
    """
    return CandidateFeatures(
        ticker="PLTR",
        sector="tech_saas",
        extraction_date="2022-12-15",
        universal_core={
            "founder_insider_stake_direction": "increasing",
            "cash_runway": ">24mo",
            "founder_in_place": "yes",
            "margin_trajectory": "improving",
            "revenue_trajectory": "growing",
            "industry_tailwind": "intact",
        },
        sector_extensions={
            "customer_engagement": "holding",
            "engagement_decoupling_from_price": "yes",
            "NDR_trend": "expanding",
        },
        consensus={f: "HIGH" for f in [
            "founder_insider_stake_direction",
            "cash_runway",
            "founder_in_place",
            "margin_trajectory",
            "revenue_trajectory",
            "industry_tailwind",
            "customer_engagement",
            "engagement_decoupling_from_price",
            "NDR_trend",
        ]},
    )


def _survivor_case(case_id: str, ticker: str, sector: str = "tech_saas") -> CatalogCase:
    """A canonical SURVIVOR catalog case with SURVIVOR-shaped features."""
    return CatalogCase(
        case_id=case_id,
        ticker=ticker,
        sector=sector,
        outcome="SURVIVOR",
        universal_core_features={
            "founder_insider_stake_direction": "increasing",
            "cash_runway": ">24mo",
            "founder_in_place": "yes",
            "margin_trajectory": "improving",
            "revenue_trajectory": "growing",
            "industry_tailwind": "intact",
        },
        sector_extensions={
            "customer_engagement": "holding",
            "engagement_decoupling_from_price": "yes",
            "NDR_trend": "expanding",
        },
        validation_status="validated",
        peak_dd_pct=-65.0,
    )


def _non_survivor_case(case_id: str, ticker: str, sector: str = "tech_saas") -> CatalogCase:
    """Canonical NON-SURVIVOR catalog case with terminal-decline features."""
    return CatalogCase(
        case_id=case_id,
        ticker=ticker,
        sector=sector,
        outcome="NON-SURVIVOR",
        universal_core_features={
            "founder_insider_stake_direction": "departed",
            "cash_runway": "distressed",
            "founder_in_place": "departed",
            "margin_trajectory": "deteriorating",
            "revenue_trajectory": "declining",
            "industry_tailwind": "structural-decline",
        },
        sector_extensions={
            "customer_engagement": "collapsed",
            "engagement_decoupling_from_price": "no",
            "NDR_trend": "contracting",
        },
        validation_status="validated",
        peak_dd_pct=-95.0,
    )


@pytest.fixture
def pltr_catalog_top_survivor() -> list[CatalogCase]:
    """SURVIVOR-leaning catalog — top-3 should all be SURVIVOR/DILUTED-SURVIVOR.

    NVDA-2008, AAPL-2003, AMZN-2001 are the canonical Walkthrough #1 matches.
    """
    return [
        _survivor_case("NVDA-2008", "NVDA"),
        _survivor_case("AAPL-2003", "AAPL"),
        _survivor_case("AMZN-2001", "AMZN"),
        # Plus one NON-SURVIVOR distractor with deeply different features.
        _non_survivor_case("WEWORK-2019", "WE"),
    ]


@pytest.fixture
def stub_premortem_yes() -> Any:
    def _lookup(ticker: str, when: _dt.datetime, lookback: int) -> bool:
        return True
    return _lookup


@pytest.fixture
def stub_premortem_no() -> Any:
    def _lookup(ticker: str, when: _dt.datetime, lookback: int) -> bool:
        return False
    return _lookup


@pytest.fixture
def db_recorder() -> dict[str, list[tuple[str, tuple[Any, ...]]]]:
    """Record DB calls for assertion. Returns {'calls': [(sql, params), ...]}."""
    state: dict[str, list[tuple[str, tuple[Any, ...]]]] = {"calls": []}

    def _execute(sql: str, params: tuple[Any, ...]) -> None:
        state["calls"].append((sql, params))

    state["execute"] = _execute  # type: ignore[assignment]
    return state


# ---------------------------------------------------------------------------
# Layer 1 — cooling-off
# ---------------------------------------------------------------------------


class TestLayer1CoolingOff:
    def test_constants_match_spec(self) -> None:
        assert MODE_COOLING_OFF_HOURS == {"B": 72, "B_prime": 48, "C": 24}
        assert MODE_2X_THRESHOLDS == {"B": 20.0, "B_prime": 24.0, "C": 30.0}

    def test_mode_c_24h_blocking_at_trigger(self) -> None:
        trigger = _dt.datetime(2026, 4, 29, 12, 0, tzinfo=_dt.timezone.utc)
        result = evaluate_cooling_off(mode="C", trigger_event_at=trigger, now=trigger)
        assert result.duration_h == 24
        assert result.blocking
        assert result.remaining_seconds == 24 * 3600

    def test_mode_c_24h_expired(self) -> None:
        trigger = _dt.datetime(2026, 4, 29, 12, 0, tzinfo=_dt.timezone.utc)
        later = trigger + _dt.timedelta(hours=25)
        result = evaluate_cooling_off(mode="C", trigger_event_at=trigger, now=later)
        assert not result.blocking
        assert result.remaining_seconds == 0

    def test_mode_b_prime_48h(self) -> None:
        trigger = _dt.datetime(2026, 4, 29, 12, 0, tzinfo=_dt.timezone.utc)
        result = evaluate_cooling_off(
            mode="B_prime",
            trigger_event_at=trigger,
            now=trigger + _dt.timedelta(hours=47),
        )
        assert result.duration_h == 48
        assert result.blocking

    def test_mode_b_72h(self) -> None:
        trigger = _dt.datetime(2026, 4, 29, 12, 0, tzinfo=_dt.timezone.utc)
        result = evaluate_cooling_off(
            mode="B",
            trigger_event_at=trigger,
            now=trigger + _dt.timedelta(hours=72, seconds=1),
        )
        assert result.duration_h == 72
        assert not result.blocking

    def test_unknown_mode_raises(self) -> None:
        with pytest.raises(ValueError):
            evaluate_cooling_off(
                mode="X",
                trigger_event_at=_dt.datetime.now(_dt.timezone.utc),
            )


# ---------------------------------------------------------------------------
# Layer 2 — multi-source
# ---------------------------------------------------------------------------


class TestLayer2MultiSource:
    def test_bocpd_collapse_two_correlated_count_as_one(self) -> None:
        now = _dt.datetime.now(_dt.timezone.utc)
        fires = [
            KillCriterionFire(
                kill_id="kill_1",
                fired_at=now,
                bocpd_correlation_group="regime_shift_2026_q1",
            ),
            KillCriterionFire(
                kill_id="kill_2",
                fired_at=now,
                bocpd_correlation_group="regime_shift_2026_q1",
            ),
        ]
        assert collapse_bocpd_correlated(fires) == 1

    def test_bocpd_uncorrelated_count_independently(self) -> None:
        now = _dt.datetime.now(_dt.timezone.utc)
        fires = [
            KillCriterionFire(kill_id="kill_1", fired_at=now),
            KillCriterionFire(kill_id="kill_2", fired_at=now),
            KillCriterionFire(
                kill_id="kill_3",
                fired_at=now,
                bocpd_correlation_group="grp_a",
            ),
            KillCriterionFire(
                kill_id="kill_4",
                fired_at=now,
                bocpd_correlation_group="grp_a",
            ),
        ]
        assert collapse_bocpd_correlated(fires) == 3

    def test_verbatim_primary_only_counts_with_recognized_source(self) -> None:
        now = _dt.datetime.now(_dt.timezone.utc)
        non_primary = [
            KillCriterionFire(
                kill_id="k1",
                fired_at=now,
                verbatim_primary_quote="analyst commentary",
                primary_source_type="analyst_note",
            )
        ]
        assert not has_verbatim_primary(non_primary)

        primary = [
            KillCriterionFire(
                kill_id="k1",
                fired_at=now,
                verbatim_primary_quote="...as disclosed in Item 7...",
                primary_source_type="10-K",
            )
        ]
        assert has_verbatim_primary(primary)

    def test_blocked_when_premortem_missing(
        self, stub_premortem_no: Any
    ) -> None:
        now = _dt.datetime.now(_dt.timezone.utc)
        fires = [
            KillCriterionFire(
                kill_id="k1",
                fired_at=now,
                verbatim_primary_quote="from 10-K",
                primary_source_type="10-K",
            ),
            KillCriterionFire(kill_id="k2", fired_at=now),
        ]
        result = evaluate_multi_source(
            ticker="ABC",
            fires=fires,
            premortem_lookup=stub_premortem_no,
        )
        assert not result.all_satisfied
        assert "pre-mortem" in result.cut_blocked_reason

    def test_satisfied_when_all_three(self, stub_premortem_yes: Any) -> None:
        now = _dt.datetime.now(_dt.timezone.utc)
        fires = [
            KillCriterionFire(
                kill_id="k1",
                fired_at=now,
                verbatim_primary_quote="from 10-K",
                primary_source_type="10-K",
            ),
            KillCriterionFire(kill_id="k2", fired_at=now),
        ]
        result = evaluate_multi_source(
            ticker="ABC",
            fires=fires,
            premortem_lookup=stub_premortem_yes,
        )
        assert result.all_satisfied
        assert result.independent_kill_count == 2


# ---------------------------------------------------------------------------
# Retrieval — Bayesian-shrunk Hamming + sector logic
# ---------------------------------------------------------------------------


class TestRetrieval:
    def test_universal_core_full_match_high_similarity(
        self, pltr_2022_candidate: CandidateFeatures
    ) -> None:
        case = _survivor_case("NVDA-2008", "NVDA")
        match = score_case(
            candidate_sector=pltr_2022_candidate.sector,
            candidate_universal_core=pltr_2022_candidate.universal_core,
            candidate_sector_extensions=pltr_2022_candidate.sector_extensions,
            case=case,
        )
        # 6/6 universal-core agreement → shrunk to (6 + 0.5*6) / (6+6) = 0.75
        # 3/3 sector extensions agreement → shrunk to (3 + 0.5*3) / (3+3) = 0.75
        # combined: 0.7*0.75 + 0.3*0.75 = 0.75
        assert match.universal_core_similarity == pytest.approx(0.75, rel=1e-9)
        assert match.sector_extension_similarity == pytest.approx(0.75, rel=1e-9)
        assert match.similarity == pytest.approx(0.75, rel=1e-9)

    def test_cross_sector_drops_extension_term(
        self, pltr_2022_candidate: CandidateFeatures
    ) -> None:
        # SURVIVOR feature shape but DIFFERENT sector → 0.3 weight should
        # drop entirely (the candidate is tech_saas, the case is energy).
        case = CatalogCase(
            case_id="XOM-2020",
            ticker="XOM",
            sector="energy",
            outcome="SURVIVOR",
            universal_core_features=dict(pltr_2022_candidate.universal_core),
            sector_extensions={
                "net_debt_at_trough": "healthy",
                "hedge_book": "strong",
            },
            validation_status="validated",
        )
        match = score_case(
            candidate_sector=pltr_2022_candidate.sector,
            candidate_universal_core=pltr_2022_candidate.universal_core,
            candidate_sector_extensions=pltr_2022_candidate.sector_extensions,
            case=case,
        )
        assert match.sector_extension_similarity is None
        # Only the universal-core term contributes: 0.7 * 0.75 = 0.525
        assert match.similarity == pytest.approx(0.7 * 0.75, rel=1e-9)

    def test_active_pool_excludes_tbd_and_disputed(
        self, pltr_2022_candidate: CandidateFeatures
    ) -> None:
        catalog = [
            _survivor_case("S1", "S1"),
            CatalogCase(
                case_id="TBD-1",
                ticker="TBD",
                sector="tech_saas",
                outcome="TBD",
                universal_core_features=dict(pltr_2022_candidate.universal_core),
                sector_extensions={},
                validation_status="validated",
            ),
            CatalogCase(
                case_id="DISP-1",
                ticker="DISP",
                sector="tech_saas",
                outcome="SURVIVOR",
                universal_core_features=dict(pltr_2022_candidate.universal_core),
                sector_extensions={},
                validation_status="disputed",
            ),
        ]
        top = retrieve_top_3(
            candidate_sector=pltr_2022_candidate.sector,
            candidate_universal_core=pltr_2022_candidate.universal_core,
            candidate_sector_extensions=pltr_2022_candidate.sector_extensions,
            catalog=catalog,
        )
        assert len(top) == 1
        assert top[0].case.case_id == "S1"

    def test_archetype_distribution_counts_correctly(
        self, pltr_2022_candidate: CandidateFeatures, pltr_catalog_top_survivor: list[CatalogCase]
    ) -> None:
        top = retrieve_top_3(
            candidate_sector=pltr_2022_candidate.sector,
            candidate_universal_core=pltr_2022_candidate.universal_core,
            candidate_sector_extensions=pltr_2022_candidate.sector_extensions,
            catalog=pltr_catalog_top_survivor,
        )
        dist = archetype_distribution(top)
        assert dist["SURVIVOR"] == 3
        assert dist["NON-SURVIVOR"] == 0


# ---------------------------------------------------------------------------
# Layer 3 — VETO
# ---------------------------------------------------------------------------


class TestLayer3Veto:
    def test_survivor_dominant_blocks_with_operator_override(
        self,
        pltr_2022_candidate: CandidateFeatures,
        pltr_catalog_top_survivor: list[CatalogCase],
    ) -> None:
        result = evaluate_veto(
            candidate=pltr_2022_candidate,
            catalog=pltr_catalog_top_survivor,
        )
        assert result.veto_invoked
        assert result.status == "operator_override_required"
        assert result.archetype_distribution["SURVIVOR"] == 3

    def test_non_survivor_dominant_does_not_block(
        self, pltr_2022_candidate: CandidateFeatures
    ) -> None:
        catalog = [
            _non_survivor_case(f"NS-{i}", f"NS{i}") for i in range(3)
        ]
        result = evaluate_veto(candidate=pltr_2022_candidate, catalog=catalog)
        assert not result.veto_invoked
        assert result.status == "not_triggered"

    def test_mixed_review_required(
        self, pltr_2022_candidate: CandidateFeatures
    ) -> None:
        catalog = [
            _survivor_case("S-1", "S1"),
            _non_survivor_case("NS-1", "NS1"),
            CatalogCase(
                case_id="DS-1",
                ticker="DS1",
                sector="tech_saas",
                outcome="DILUTED-SURVIVOR",
                universal_core_features={
                    "founder_insider_stake_direction": "flat",
                    "cash_runway": "12-24mo",
                    "founder_in_place": "replaced-by-competent",
                    "margin_trajectory": "stable",
                    "revenue_trajectory": "flat",
                    "industry_tailwind": "weakening",
                },
                sector_extensions={},
                validation_status="validated",
            ),
        ]
        result = evaluate_veto(candidate=pltr_2022_candidate, catalog=catalog)
        # SURVIVOR + DILUTED-SURVIVOR ≥ 2 → operator_override_required
        # (DILUTED-SURVIVOR counts as SURVIVOR-leaning per Layer 3 rule).
        assert result.status == "operator_override_required"

    def test_is_survivor_dominant_helper(self) -> None:
        assert is_survivor_dominant({"SURVIVOR": 2, "NON-SURVIVOR": 1})
        assert is_survivor_dominant({"SURVIVOR": 1, "DILUTED-SURVIVOR": 1, "NON-SURVIVOR": 1})
        assert not is_survivor_dominant({"SURVIVOR": 1, "NON-SURVIVOR": 2})


# ---------------------------------------------------------------------------
# Lifecycle — single-fire + M-3 refresh
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_m3_refresh_unchanged_keeps_active(
        self,
        pltr_2022_candidate: CandidateFeatures,
        pltr_catalog_top_survivor: list[CatalogCase],
    ) -> None:
        record = VetoLifecycleRecord(
            veto_id="veto-1",
            retrieval_id="ret-1",
            ticker="PLTR",
            initial_fire_date=_dt.date(2022, 12, 15),
            status="active",
            last_archetype_distribution={"SURVIVOR": 3, "NON-SURVIVOR": 0, "DILUTED-SURVIVOR": 0},
        )
        outcome = refresh_on_m3(
            record=record,
            candidate=pltr_2022_candidate,
            catalog=pltr_catalog_top_survivor,
            drawdown_vs_benchmark_pp=-66.0,
        )
        assert outcome.action_taken == "unchanged"
        assert outcome.new_status == "active"
        assert len(record.m3_refreshes) == 1

    def test_m3_refresh_feature_shift_releases(
        self,
        pltr_2022_candidate: CandidateFeatures,
    ) -> None:
        record = VetoLifecycleRecord(
            veto_id="veto-1",
            retrieval_id="ret-1",
            ticker="PLTR",
            initial_fire_date=_dt.date(2022, 12, 15),
            status="active",
            last_archetype_distribution={"SURVIVOR": 3, "NON-SURVIVOR": 0, "DILUTED-SURVIVOR": 0},
        )
        # Now imagine founder departure flips features → new top-3 is NON-SURVIVOR
        new_catalog = [_non_survivor_case(f"NS-{i}", f"NS{i}") for i in range(3)]
        # Re-extracted candidate now has founder_in_place=departed, cash_runway distressed, etc
        shifted_candidate = CandidateFeatures(
            ticker="PLTR",
            sector="tech_saas",
            extraction_date="2023-03-15",
            universal_core={
                "founder_insider_stake_direction": "departed",
                "cash_runway": "distressed",
                "founder_in_place": "departed",
                "margin_trajectory": "deteriorating",
                "revenue_trajectory": "declining",
                "industry_tailwind": "structural-decline",
            },
            sector_extensions={},
            consensus={},
        )
        outcome = refresh_on_m3(
            record=record,
            candidate=shifted_candidate,
            catalog=new_catalog,
            drawdown_vs_benchmark_pp=-70.0,
        )
        assert outcome.action_taken == "released"
        assert outcome.new_status == "released-by-feature-shift"
        assert record.status == "released-by-feature-shift"

    def test_release_by_recovery_appends_event(self) -> None:
        record = VetoLifecycleRecord(
            veto_id="veto-1",
            retrieval_id="ret-1",
            ticker="PLTR",
            initial_fire_date=_dt.date(2022, 12, 15),
            status="active",
            last_archetype_distribution={"SURVIVOR": 3},
        )
        release_by_recovery(record, drawdown_vs_benchmark_pp=-5.0)
        assert record.status == "released-by-recovery"
        assert record.m3_refreshes[-1]["action_taken"] == "released-by-recovery"

    def test_operator_override_captures_rationale(self) -> None:
        record = VetoLifecycleRecord(
            veto_id="veto-1",
            retrieval_id="ret-1",
            ticker="PLTR",
            initial_fire_date=_dt.date(2022, 12, 15),
            status="active",
            last_archetype_distribution={"SURVIVOR": 3},
        )
        operator_override(record, rationale="Operator: thesis broken on data lock-in")
        assert record.status == "overridden-by-operator"
        assert record.operator_override_occurred
        assert record.operator_override_rationale.startswith("Operator:")


# ---------------------------------------------------------------------------
# Orchestrator — full pipeline
# ---------------------------------------------------------------------------


class TestOrchestrator:
    def test_cooling_off_blocks_before_layer_2(
        self,
        pltr_2022_candidate: CandidateFeatures,
        pltr_catalog_top_survivor: list[CatalogCase],
        stub_premortem_yes: Any,
        db_recorder: dict[str, Any],
    ) -> None:
        trigger = _dt.datetime(2022, 12, 15, 20, 30, tzinfo=_dt.timezone.utc)
        eval_now = trigger + _dt.timedelta(hours=1)  # only 1h after trigger
        decision = run_pipeline(
            PipelineInputs(
                ticker="PLTR",
                mode="C",  # 24h cooling-off
                candidate=pltr_2022_candidate,
                catalog=pltr_catalog_top_survivor,
                fires=[],
                trigger_event_at=trigger,
                drawdown_vs_benchmark_pp=-65.0,
                catalog_version_hash="test-hash",
            ),
            premortem_lookup=stub_premortem_yes,
            execute=db_recorder["execute"],
            now=eval_now,
        )
        assert decision.cut_status == CUT_STATUS_WAIT_COOLING_OFF
        assert decision.cooling_off.blocking
        assert db_recorder["calls"] == []  # no DB writes when blocked at L1

    def test_layer2_block_when_no_premortem(
        self,
        pltr_2022_candidate: CandidateFeatures,
        pltr_catalog_top_survivor: list[CatalogCase],
        stub_premortem_no: Any,
        db_recorder: dict[str, Any],
    ) -> None:
        trigger = _dt.datetime(2022, 12, 15, 20, 30, tzinfo=_dt.timezone.utc)
        eval_now = trigger + _dt.timedelta(hours=25)  # past 24h
        fires = [
            KillCriterionFire(
                kill_id="k1",
                fired_at=trigger,
                verbatim_primary_quote="from 10-K",
                primary_source_type="10-K",
            )
        ]
        decision = run_pipeline(
            PipelineInputs(
                ticker="PLTR",
                mode="C",
                candidate=pltr_2022_candidate,
                catalog=pltr_catalog_top_survivor,
                fires=fires,
                trigger_event_at=trigger,
                drawdown_vs_benchmark_pp=-65.0,
            ),
            premortem_lookup=stub_premortem_no,
            execute=db_recorder["execute"],
            now=eval_now,
        )
        assert decision.cut_status == CUT_STATUS_BLOCKED_MULTI_SOURCE
        assert "pre-mortem" in decision.multi_source.cut_blocked_reason

    def test_pltr_2022_walkthrough_veto_fires(
        self,
        pltr_2022_candidate: CandidateFeatures,
        pltr_catalog_top_survivor: list[CatalogCase],
        stub_premortem_yes: Any,
        db_recorder: dict[str, Any],
    ) -> None:
        """Section 7.3a Walkthrough #1 — PLTR-2022 veto fires; cut blocked.

        Expected pipeline behavior at the trough:
            * Mode C, drawdown -65pp (vs 30pp 2× threshold).
            * Cooling-off 24h elapsed.
            * Layer 2: 1 BOCPD-collapsed kill fire + verbatim primary →
              fails ≥2 independent kills check (per task brief)
            * If we DO have ≥2 independent kills + premortem → Layer 3 gate
        """
        trigger = _dt.datetime(2022, 12, 15, 20, 30, tzinfo=_dt.timezone.utc)
        eval_now = trigger + _dt.timedelta(hours=25)  # past 24h
        # Set up 2 truly independent (non-BOCPD-correlated) kills + verbatim
        fires = [
            KillCriterionFire(
                kill_id="k1",
                fired_at=trigger,
                verbatim_primary_quote="...government revenue declined...",
                primary_source_type="10-K",
            ),
            KillCriterionFire(kill_id="k2", fired_at=trigger),
        ]
        decision = run_pipeline(
            PipelineInputs(
                ticker="PLTR",
                mode="C",
                candidate=pltr_2022_candidate,
                catalog=pltr_catalog_top_survivor,
                fires=fires,
                trigger_event_at=trigger,
                drawdown_vs_benchmark_pp=-65.0,
                catalog_version_hash="walkthrough-1",
            ),
            premortem_lookup=stub_premortem_yes,
            execute=db_recorder["execute"],
            now=eval_now,
        )
        # Layer 1 elapsed → not WAIT
        assert decision.cooling_off.blocking is False
        # Layer 2 satisfied → didn't block at multi-source
        assert decision.multi_source.all_satisfied
        # Layer 3 fired → cut blocked, operator override required
        assert decision.cut_status == CUT_STATUS_BLOCKED_VETO
        assert decision.veto.status == "operator_override_required"
        assert decision.veto.archetype_distribution["SURVIVOR"] == 3
        # M-3 alert SHOULD have been fired (SURVIVOR-dominant)
        assert decision.m3_alert_fired

        # DB writes: counterfactual_retrievals + veto_lifecycle + unread_alerts
        sql_starts = [c[0].split()[1] for c in db_recorder["calls"] if "INTO" in c[0]]
        assert "counterfactual_retrievals" in sql_starts or any(
            "counterfactual_retrievals" in c[0] for c in db_recorder["calls"]
        )

    def test_pltr_2022_walkthrough_only_one_kill_blocks_at_layer2(
        self,
        pltr_2022_candidate: CandidateFeatures,
        pltr_catalog_top_survivor: list[CatalogCase],
        stub_premortem_yes: Any,
        db_recorder: dict[str, Any],
    ) -> None:
        """Per task brief: 'Layer 2 likely blocks cut (1 independent kill from
        BOCPD-collapse)'. Two BOCPD-correlated kills → counts as 1, blocked."""
        trigger = _dt.datetime(2022, 12, 15, 20, 30, tzinfo=_dt.timezone.utc)
        eval_now = trigger + _dt.timedelta(hours=25)
        fires = [
            KillCriterionFire(
                kill_id="k1",
                fired_at=trigger,
                bocpd_correlation_group="2022_macro_growth_shock",
                verbatim_primary_quote="from earnings call",
                primary_source_type="earnings_call",
            ),
            KillCriterionFire(
                kill_id="k2",
                fired_at=trigger,
                bocpd_correlation_group="2022_macro_growth_shock",
            ),
        ]
        decision = run_pipeline(
            PipelineInputs(
                ticker="PLTR",
                mode="C",
                candidate=pltr_2022_candidate,
                catalog=pltr_catalog_top_survivor,
                fires=fires,
                trigger_event_at=trigger,
                drawdown_vs_benchmark_pp=-65.0,
            ),
            premortem_lookup=stub_premortem_yes,
            execute=db_recorder["execute"],
            now=eval_now,
        )
        assert decision.cut_status == CUT_STATUS_BLOCKED_MULTI_SOURCE
        assert decision.multi_source.independent_kill_count == 1
        assert "≥2" in decision.multi_source.cut_blocked_reason

    def test_non_survivor_dominant_proceeds(
        self,
        pltr_2022_candidate: CandidateFeatures,
        stub_premortem_yes: Any,
        db_recorder: dict[str, Any],
    ) -> None:
        # Catalog all NON-SURVIVOR — even with PLTR-shaped candidate features,
        # NON-SURVIVOR catalog has terminal-decline features so these will
        # match poorly; but the top-3 will still be those (only options).
        catalog = [_non_survivor_case(f"NS-{i}", f"NS{i}") for i in range(3)]
        trigger = _dt.datetime(2022, 12, 15, 20, 30, tzinfo=_dt.timezone.utc)
        eval_now = trigger + _dt.timedelta(hours=25)
        fires = [
            KillCriterionFire(
                kill_id="k1",
                fired_at=trigger,
                verbatim_primary_quote="from 10-K",
                primary_source_type="10-K",
            ),
            KillCriterionFire(kill_id="k2", fired_at=trigger),
        ]
        decision = run_pipeline(
            PipelineInputs(
                ticker="ABC",
                mode="C",
                candidate=pltr_2022_candidate,
                catalog=catalog,
                fires=fires,
                trigger_event_at=trigger,
                drawdown_vs_benchmark_pp=-65.0,
            ),
            premortem_lookup=stub_premortem_yes,
            execute=db_recorder["execute"],
            now=eval_now,
        )
        assert decision.cut_status == CUT_STATUS_PROCEED
        assert decision.veto.status == "not_triggered"
        assert not decision.m3_alert_fired


# ---------------------------------------------------------------------------
# Round-trip helper
# ---------------------------------------------------------------------------


class TestCandidateRoundTrip:
    def test_to_dict_from_dict_roundtrip(
        self, pltr_2022_candidate: CandidateFeatures
    ) -> None:
        payload = pltr_2022_candidate.to_dict()
        roundtrip = candidate_from_dict(payload)
        assert roundtrip.ticker == pltr_2022_candidate.ticker
        assert roundtrip.sector == pltr_2022_candidate.sector
        assert roundtrip.universal_core == pltr_2022_candidate.universal_core
        assert roundtrip.sector_extensions == pltr_2022_candidate.sector_extensions


# ---------------------------------------------------------------------------
# 2× cut threshold gate (Section 4.5 Q6 — C.3 H2 remediation)
# ---------------------------------------------------------------------------


class TestActivationGate:
    """Pipeline must short-circuit below the mode-tuned 2× cut threshold.

    Per v3 spec Section 4.5 Q6: drawdown_vs_benchmark_pp must be ≥ the mode's
    2× threshold (B/20pp, B'/24pp, C/30pp) before any layer runs. Otherwise
    tiny drawdowns leak through to Layer 3 and may emit alerts / DB writes.
    """

    def test_below_2x_threshold_short_circuits(
        self,
        pltr_2022_candidate: CandidateFeatures,
        pltr_catalog_top_survivor: list[CatalogCase],
        stub_premortem_yes: Any,
        db_recorder: dict[str, Any],
    ) -> None:
        # Mode C threshold = 30pp; supply -2pp (well below).
        trigger = _dt.datetime(2026, 4, 29, 12, 0, tzinfo=_dt.timezone.utc)
        decision = run_pipeline(
            PipelineInputs(
                ticker="PLTR",
                mode="C",
                candidate=pltr_2022_candidate,
                catalog=pltr_catalog_top_survivor,
                fires=[],
                trigger_event_at=trigger,
                drawdown_vs_benchmark_pp=-2.0,
            ),
            premortem_lookup=stub_premortem_yes,
            execute=db_recorder["execute"],
            now=trigger + _dt.timedelta(hours=25),
        )
        assert decision.cut_status == CUT_STATUS_NOT_ACTIVATED_BELOW_2X
        assert decision.cooling_off is None
        assert decision.multi_source is None
        assert decision.veto is None
        assert decision.m3_alert_fired is False
        assert "below" in decision.rationale.lower()
        # No DB writes emitted while below threshold.
        assert db_recorder["calls"] == []

    def test_at_2x_threshold_runs_pipeline(
        self,
        pltr_2022_candidate: CandidateFeatures,
        pltr_catalog_top_survivor: list[CatalogCase],
        stub_premortem_yes: Any,
        db_recorder: dict[str, Any],
    ) -> None:
        trigger = _dt.datetime(2026, 4, 29, 12, 0, tzinfo=_dt.timezone.utc)
        eval_now = trigger + _dt.timedelta(hours=25)
        fires = [
            KillCriterionFire(
                kill_id="k1",
                fired_at=trigger,
                verbatim_primary_quote="from 10-K",
                primary_source_type="10-K",
            ),
            KillCriterionFire(kill_id="k2", fired_at=trigger),
        ]
        decision = run_pipeline(
            PipelineInputs(
                ticker="PLTR",
                mode="C",
                candidate=pltr_2022_candidate,
                catalog=pltr_catalog_top_survivor,
                fires=fires,
                trigger_event_at=trigger,
                drawdown_vs_benchmark_pp=-30.0,  # exactly at C threshold
            ),
            premortem_lookup=stub_premortem_yes,
            execute=db_recorder["execute"],
            now=eval_now,
        )
        assert decision.cut_status != CUT_STATUS_NOT_ACTIVATED_BELOW_2X
        assert decision.cooling_off is not None  # pipeline ran past gate
        assert len(db_recorder["calls"]) >= 1  # retrieval row at minimum

    def test_just_above_2x_threshold_runs_pipeline(
        self,
        pltr_2022_candidate: CandidateFeatures,
        pltr_catalog_top_survivor: list[CatalogCase],
        stub_premortem_yes: Any,
        db_recorder: dict[str, Any],
    ) -> None:
        trigger = _dt.datetime(2026, 4, 29, 12, 0, tzinfo=_dt.timezone.utc)
        eval_now = trigger + _dt.timedelta(hours=25)
        fires = [
            KillCriterionFire(
                kill_id="k1",
                fired_at=trigger,
                verbatim_primary_quote="from 10-K",
                primary_source_type="10-K",
            ),
            KillCriterionFire(kill_id="k2", fired_at=trigger),
        ]
        decision = run_pipeline(
            PipelineInputs(
                ticker="PLTR",
                mode="C",
                candidate=pltr_2022_candidate,
                catalog=pltr_catalog_top_survivor,
                fires=fires,
                trigger_event_at=trigger,
                drawdown_vs_benchmark_pp=-30.01,  # just past C threshold
            ),
            premortem_lookup=stub_premortem_yes,
            execute=db_recorder["execute"],
            now=eval_now,
        )
        assert decision.cut_status != CUT_STATUS_NOT_ACTIVATED_BELOW_2X
        assert decision.cooling_off is not None


# ---------------------------------------------------------------------------
# HMAC tamper-evidence at retrieval load time (Section 7.2 — C.3 H4 remediation)
# ---------------------------------------------------------------------------


class TestRetrievalHmacIntegration:
    """``load_catalog_from_pg`` MUST verify each row's HMAC.

    Per v3 spec Section 7.2 + 7.3a launch-gate, tampering with peak-pain
    catalog rows must be detected: the bad row is dropped from the active
    pool and a system_errors row is emitted (M-2 path).
    """

    def test_retrieval_processes_valid_hmac_rows(self) -> None:
        key = b"unit-test-peak-pain-hmac-key"
        rows = realistic_catalog_as_db_rows(sign_with_key=key)

        execute_calls: list[tuple[str, tuple[Any, ...]]] = []

        def query_fn(_sql: str) -> list[dict[str, Any]]:
            return rows

        def execute(sql: str, params: tuple[Any, ...]) -> None:
            execute_calls.append((sql, params))

        out = load_catalog_from_pg(
            query_fn,
            peak_pain_hmac_secret=key,
            execute=execute,
        )
        # All valid rows survive the gate.
        assert len(out) == len(rows)
        # No system_errors rows emitted on the happy path.
        assert all("system_errors" not in c[0] for c in execute_calls)

    def test_retrieval_skips_tampered_hmac_row(self) -> None:
        key = b"unit-test-peak-pain-hmac-key"
        rows = realistic_catalog_as_db_rows(sign_with_key=key)
        # Tamper with one row's universal_core_features (flip
        # founder_in_place from 'departed' to 'yes' — survivor-flipping
        # tamper). Signature should no longer match.
        target = next(r for r in rows if r["case_id"] == "BBBY-2023")
        target["universal_core_features"] = dict(target["universal_core_features"])
        target["universal_core_features"]["founder_in_place"] = "yes"

        execute_calls: list[tuple[str, tuple[Any, ...]]] = []

        def query_fn(_sql: str) -> list[dict[str, Any]]:
            return rows

        def execute(sql: str, params: tuple[Any, ...]) -> None:
            execute_calls.append((sql, params))

        out = load_catalog_from_pg(
            query_fn,
            peak_pain_hmac_secret=key,
            execute=execute,
        )
        # Tampered row dropped; rest survive.
        assert all(c.case_id != "BBBY-2023" for c in out)
        assert len(out) == len(rows) - 1
        # system_errors row emitted with the right source/error_type.
        sys_err_calls = [
            c for c in execute_calls if "system_errors" in c[0]
        ]
        assert len(sys_err_calls) == 1
        params = sys_err_calls[0][1]
        # Param order: source, error_type, error_detail, blocked_decision
        assert params[0] == "counterfactual_veto.retrieval"
        assert params[1] == "peak_pain_hmac_invalid"
        assert "BBBY-2023" in params[2]


# ---------------------------------------------------------------------------
# Lifecycle M-3 re-fire + re-evaluate paths (PB#5 — C.3 H3 remediation)
# ---------------------------------------------------------------------------


class TestLifecycleM3RefireAndReEvaluate:
    """Cover the re-fired and re-evaluate branches of refresh_on_m3.

    Existing tests cover ``unchanged`` and ``released`` (feature-shift). PB#5
    also defines:
        - re-fired:    new mix flips INTO SURVIVOR-dominant from non-blocking;
                       veto stays 'active' with refreshed snapshot.
        - re-evaluate: mix changed but neither prior nor new is SURVIVOR-
                       dominant; veto status unchanged.
    """

    def test_m3_refresh_re_fires_when_new_archetype_mix_changes_to_blocking(
        self,
        pltr_2022_candidate: CandidateFeatures,
        pltr_catalog_top_survivor: list[CatalogCase],
    ) -> None:
        # Prior was non-blocking (mixed) — only one SURVIVOR-leaning bucket.
        record = VetoLifecycleRecord(
            veto_id="veto-1",
            retrieval_id="ret-1",
            ticker="PLTR",
            initial_fire_date=_dt.date(2022, 12, 15),
            status="active",
            last_archetype_distribution={
                "SURVIVOR": 1,
                "DILUTED-SURVIVOR": 0,
                "NON-SURVIVOR": 2,
            },
        )
        outcome = refresh_on_m3(
            record=record,
            candidate=pltr_2022_candidate,
            catalog=pltr_catalog_top_survivor,
            drawdown_vs_benchmark_pp=-66.0,
        )
        # New top-3 is SURVIVOR-dominant per pltr_catalog_top_survivor fixture.
        assert outcome.action_taken == "re-fired"
        assert outcome.new_status == "active"
        assert outcome.archetype_mix_changed
        assert is_survivor_dominant(outcome.new_archetype_distribution)
        assert record.status == "active"
        # Refresh event captured in the m3_refreshes append-only array.
        assert record.m3_refreshes[-1]["action_taken"] == "re-fired"

    def test_m3_refresh_re_evaluate_branch(
        self, pltr_2022_candidate: CandidateFeatures
    ) -> None:
        # Prior had no SURVIVOR-dominance (1 SURVIVOR / 2 NON-SURVIVOR);
        # new mix shifts to a DIFFERENT non-SURVIVOR-dominant shape
        # (3 NON-SURVIVOR) — features changed but veto neither blocks nor
        # releases.
        record = VetoLifecycleRecord(
            veto_id="veto-1",
            retrieval_id="ret-1",
            ticker="PLTR",
            initial_fire_date=_dt.date(2022, 12, 15),
            status="active",
            last_archetype_distribution={
                "SURVIVOR": 1,
                "DILUTED-SURVIVOR": 0,
                "NON-SURVIVOR": 2,
            },
        )
        new_catalog = [
            CatalogCase(
                case_id=f"NS-{i}",
                ticker=f"NS{i}",
                sector="tech_saas",
                outcome="NON-SURVIVOR",
                universal_core_features={
                    "founder_insider_stake_direction": "departed",
                    "cash_runway": "distressed",
                    "founder_in_place": "departed",
                    "margin_trajectory": "deteriorating",
                    "revenue_trajectory": "declining",
                    "industry_tailwind": "structural-decline",
                },
                sector_extensions={
                    "customer_engagement": "collapsed",
                    "engagement_decoupling_from_price": "no",
                    "NDR_trend": "contracting",
                },
                validation_status="validated",
            )
            for i in range(3)
        ]
        outcome = refresh_on_m3(
            record=record,
            candidate=pltr_2022_candidate,
            catalog=new_catalog,
            drawdown_vs_benchmark_pp=-65.0,
        )
        # New mix: 0 SURVIVOR / 3 NON-SURVIVOR — diff from prior 1/2/0,
        # mix changed, neither old nor new is SURVIVOR-dominant.
        assert outcome.archetype_mix_changed
        assert outcome.action_taken == "re-evaluate"
        assert not is_survivor_dominant(outcome.new_archetype_distribution)
        # Veto status preserved (per spec: re-evaluate keeps record.status).
        assert outcome.new_status == "active"
        assert record.status == "active"


# ---------------------------------------------------------------------------
# PLTR-2022 walkthrough — Section 7.3a launch-gate evidence (C.3 H1 remediation)
# ---------------------------------------------------------------------------


class TestPltr2022WalkthroughDiscrimination:
    """Realistic 14-case catalog with mixed feature alignment levels.

    The earlier walkthrough used 3 hand-picked SURVIVOR cases identical to the
    candidate; that's a smoke test, not launch-gate evidence. This suite uses
    ``build_realistic_catalog()`` with real SURVIVOR/NON-SURVIVOR/DILUTED-
    SURVIVOR shapes and checks that the retrieval scorer surfaces the right
    top-3 by feature alignment, not by fixture hand-pick.
    """

    @pytest.fixture
    def realistic_catalog(self) -> list[CatalogCase]:
        return build_realistic_catalog()

    def test_walkthrough_2x_threshold_fires_at_minus_30pp(
        self,
        pltr_2022_candidate: CandidateFeatures,
        realistic_catalog: list[CatalogCase],
        stub_premortem_yes: Any,
        db_recorder: dict[str, Any],
    ) -> None:
        """Mode C 2× gate fires at exactly -30pp (boundary case)."""
        trigger = _dt.datetime(2022, 12, 15, 20, 30, tzinfo=_dt.timezone.utc)
        eval_now = trigger + _dt.timedelta(hours=25)
        fires = [
            KillCriterionFire(
                kill_id="k1",
                fired_at=trigger,
                verbatim_primary_quote="...government revenue declined...",
                primary_source_type="10-K",
            ),
            KillCriterionFire(kill_id="k2", fired_at=trigger),
        ]
        decision = run_pipeline(
            PipelineInputs(
                ticker="PLTR",
                mode="C",
                candidate=pltr_2022_candidate,
                catalog=realistic_catalog,
                fires=fires,
                trigger_event_at=trigger,
                drawdown_vs_benchmark_pp=-30.0,
                catalog_version_hash="walkthrough-realistic",
            ),
            premortem_lookup=stub_premortem_yes,
            execute=db_recorder["execute"],
            now=eval_now,
        )
        assert decision.cut_status != CUT_STATUS_NOT_ACTIVATED_BELOW_2X
        assert decision.cooling_off is not None
        assert decision.cooling_off.blocking is False

    def test_walkthrough_top_3_reflects_feature_alignment(
        self,
        pltr_2022_candidate: CandidateFeatures,
        realistic_catalog: list[CatalogCase],
    ) -> None:
        """Top-3 SURVIVOR-dominant is earned by feature alignment, not hand-pick.

        PLTR's universal_core matches all 6 SURVIVOR features; PLTR is in
        tech_saas sector so AAPL-2003 (same sector) gets the +0.3 bonus,
        but cross-sector SURVIVOR cases (NVDA-2008 semis_hardware, NFLX-2011
        comms_media, MELI-2022 international_em) still beat NON-SURVIVOR
        cases on the universal-core 0.7-weighted term.
        """
        top = retrieve_top_3(
            candidate_sector=pltr_2022_candidate.sector,
            candidate_universal_core=pltr_2022_candidate.universal_core,
            candidate_sector_extensions=pltr_2022_candidate.sector_extensions,
            catalog=realistic_catalog,
            k=3,
        )
        case_ids = [m.case.case_id for m in top]
        # Top-3 must include at least 2 SURVIVOR-leaning cases.
        survivor_lean = sum(
            1 for m in top if m.case.outcome in ("SURVIVOR", "DILUTED-SURVIVOR")
        )
        assert survivor_lean >= 2, f"Expected SURVIVOR-leaning top-3, got {case_ids}"
        # Similarities should NOT all be 1.0 — discrimination happens.
        sims = [m.similarity for m in top]
        # AAPL-2003 (same sector + identical features) should have HIGHER
        # similarity than NVDA-2008 (cross-sector, identical universal core).
        ids_to_sim = {m.case.case_id: m.similarity for m in top}
        if "AAPL-2003" in ids_to_sim and "NVDA-2008" in ids_to_sim:
            assert ids_to_sim["AAPL-2003"] > ids_to_sim["NVDA-2008"]
        # No similarity should be exactly 1.0 (Bayesian shrinkage caps at 0.75).
        assert all(s < 1.0 for s in sims)

    def test_walkthrough_layer2_with_two_independent_kills(
        self,
        pltr_2022_candidate: CandidateFeatures,
        realistic_catalog: list[CatalogCase],
        stub_premortem_yes: Any,
        db_recorder: dict[str, Any],
    ) -> None:
        trigger = _dt.datetime(2022, 12, 15, 20, 30, tzinfo=_dt.timezone.utc)
        eval_now = trigger + _dt.timedelta(hours=25)
        fires = [
            KillCriterionFire(
                kill_id="k1",
                fired_at=trigger,
                verbatim_primary_quote="...government revenue declined...",
                primary_source_type="10-K",
            ),
            KillCriterionFire(kill_id="k2", fired_at=trigger),
        ]
        decision = run_pipeline(
            PipelineInputs(
                ticker="PLTR",
                mode="C",
                candidate=pltr_2022_candidate,
                catalog=realistic_catalog,
                fires=fires,
                trigger_event_at=trigger,
                drawdown_vs_benchmark_pp=-65.0,
                catalog_version_hash="walkthrough-realistic",
            ),
            premortem_lookup=stub_premortem_yes,
            execute=db_recorder["execute"],
            now=eval_now,
        )
        # Two independent kills + verbatim primary + premortem → multi-source ok
        assert decision.multi_source.all_satisfied
        assert decision.multi_source.independent_kill_count == 2
        # Layer 3 fires SURVIVOR-dominant
        assert decision.cut_status == CUT_STATUS_BLOCKED_VETO
        assert decision.veto.status == "operator_override_required"
        # Top-3 case_ids drawn from realistic catalog, not hand-pick fixture.
        retrieved_ids = [m.case.case_id for m in decision.veto.top_3_matches]
        assert all(cid in {c.case_id for c in realistic_catalog} for cid in retrieved_ids)
        # SURVIVOR-leaning ≥2 of 3 in top-3.
        outcomes = [m.case.outcome for m in decision.veto.top_3_matches]
        assert (
            sum(1 for o in outcomes if o in ("SURVIVOR", "DILUTED-SURVIVOR")) >= 2
        )

    def test_walkthrough_layer2_one_kill_blocks_at_layer2(
        self,
        pltr_2022_candidate: CandidateFeatures,
        realistic_catalog: list[CatalogCase],
        stub_premortem_yes: Any,
        db_recorder: dict[str, Any],
    ) -> None:
        """When only one independent kill fires, Layer 2 blocks before Layer 3."""
        trigger = _dt.datetime(2022, 12, 15, 20, 30, tzinfo=_dt.timezone.utc)
        eval_now = trigger + _dt.timedelta(hours=25)
        fires = [
            KillCriterionFire(
                kill_id="k1",
                fired_at=trigger,
                bocpd_correlation_group="2022_macro_growth_shock",
                verbatim_primary_quote="from 10-K",
                primary_source_type="10-K",
            ),
            KillCriterionFire(
                kill_id="k2",
                fired_at=trigger,
                bocpd_correlation_group="2022_macro_growth_shock",
            ),
        ]
        decision = run_pipeline(
            PipelineInputs(
                ticker="PLTR",
                mode="C",
                candidate=pltr_2022_candidate,
                catalog=realistic_catalog,
                fires=fires,
                trigger_event_at=trigger,
                drawdown_vs_benchmark_pp=-65.0,
            ),
            premortem_lookup=stub_premortem_yes,
            execute=db_recorder["execute"],
            now=eval_now,
        )
        assert decision.cut_status == CUT_STATUS_BLOCKED_MULTI_SOURCE
        assert decision.multi_source.independent_kill_count == 1
        assert decision.veto is None  # never reached Layer 3
