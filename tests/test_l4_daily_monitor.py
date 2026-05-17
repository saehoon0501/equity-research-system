"""Smoke tests for the l4_daily_monitor package.

No DB I/O, no live LLM, no network. The orchestrator is exercised in
``dry_run=True`` mode with injected adapters and a fake LLM client.

Layered to mirror the package structure:

* event_ingestor          — adapter Protocol + Event normalizers
* materiality_classifier  — JSON validation, verbatim-quote rule, escalation
* router                  — M-1/M-2/M-3 paths, fallback table, judge confidence
* cut_evaluator           — Section 4.5 Q3 thresholds per mode
* refresh_emitter         — end-to-end pipeline (dry_run + stub db_writer)
* drift_detector          — Cohen's kappa + percentile + M-2 system event
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

# Mirror sys.path trick used by other test modules.
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from l4_daily_monitor import (
    ALL_AGENTS,
    DEFAULT_MODEL,
    ESCALATION_MODEL,
    EVENT_TYPE_AGENT_LOOKUP,
    JUDGE_CONFIDENCE_FLOOR,
    MATERIALITY_LABELS,
    MATERIALITY_M1,
    MATERIALITY_M2,
    MATERIALITY_M3,
    MIN_DRIFT_SAMPLE_SIZE,
    MODE_B,
    MODE_B_PRIME,
    MODE_C,
)
from l4_daily_monitor.cut_evaluator import (
    CutContext,
    build_cut_context_from_verdicts,
    evaluate_cut,
)
from l4_daily_monitor.drift_detector import (
    GoldStandardEvent,
    cohens_kappa,
    run_quarterly_drift_check,
)
from l4_daily_monitor.event_ingestor import (
    EVENT_TYPE_EARNINGS_CALL,
    EVENT_TYPE_FILING_8K,
    EVENT_TYPE_MACRO_PRINT,
    Event,
    ingest_events,
)
from l4_daily_monitor.materiality_classifier import (
    MaterialityVerdict,
    classify_materiality,
    _validate_payload,
)
from l4_daily_monitor.refresh_emitter import run_daily_refresh
from l4_daily_monitor.router import (
    RoutingDecision,
    fallback_agents_for_event,
    route_materiality,
)


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


def _evt(
    type_: str = EVENT_TYPE_EARNINGS_CALL,
    raw_text: str = "Revenue grew 30% YoY; guidance raised. CEO said 'execution remains strong'.",
    verbatim: str = "execution remains strong",
) -> Event:
    return Event(
        type=type_,
        source_id="test:1",
        timestamp=_dt.datetime(2026, 4, 30, 20, 30, 0, tzinfo=_dt.timezone.utc),
        raw_text=raw_text,
        verbatim_quote=verbatim,
    )


class _StubAdapter:
    def __init__(self, events: dict[str, list[Event]]) -> None:
        self._e = events

    def fetch_news(self, t, d):           return self._e.get("news", [])
    def fetch_filings(self, t, d):        return self._e.get("filings", [])
    def fetch_smart_money(self, t, d):    return self._e.get("smart_money", [])
    def fetch_macro(self, d):             return self._e.get("macro", [])
    def fetch_credit(self, d):            return self._e.get("credit", [])
    def fetch_sector_peers(self, t, d):   return self._e.get("sector", [])
    def fetch_earnings(self, t, d):       return self._e.get("earnings", [])


@dataclass
class _FakeBlock:
    text: str


@dataclass
class _FakeMessage:
    content: list[_FakeBlock]


class _FakeClient:
    """Records calls + replays scripted JSON responses keyed by model."""

    def __init__(self, scripts: dict[str, list[str]]) -> None:
        # scripts: {model: [response_text, ...]}; popped FIFO per model.
        self.scripts = {k: list(v) for k, v in scripts.items()}
        self.calls: list[dict[str, Any]] = []
        self.messages = self  # so `.messages.create` works

    def create(self, *, model, max_tokens, temperature, system, messages):
        self.calls.append(
            {"model": model, "system": system, "messages": messages,
             "temperature": temperature, "max_tokens": max_tokens}
        )
        # Per-model script; fall back to first non-empty queue.
        if model in self.scripts and self.scripts[model]:
            text = self.scripts[model].pop(0)
        else:
            # Fallback: any remaining script
            text = ""
            for k, q in self.scripts.items():
                if q:
                    text = q.pop(0)
                    break
        return _FakeMessage(content=[_FakeBlock(text=text)])


# --------------------------------------------------------------------------- #
# event_ingestor                                                              #
# --------------------------------------------------------------------------- #


def test_ingest_events_aggregates_all_sources_and_sorts():
    ev_macro = Event(
        type=EVENT_TYPE_MACRO_PRINT,
        source_id="fred:CPIAUCSL",
        timestamp=_dt.datetime(2026, 4, 30, 12, 30, tzinfo=_dt.timezone.utc),
        raw_text="CPI MoM 0.4%",
        verbatim_quote="0.4%",
    )
    ev_earn = _evt()
    ev_filing = Event(
        type=EVENT_TYPE_FILING_8K,
        source_id="edgar:abc",
        timestamp=_dt.datetime(2026, 4, 30, 8, 0, tzinfo=_dt.timezone.utc),
        raw_text="Item 5.02 — Resignation of Officer.",
        verbatim_quote="Resignation of Officer",
    )
    adapter = _StubAdapter({
        "macro": [ev_macro], "earnings": [ev_earn], "filings": [ev_filing],
    })
    out = ingest_events("NVDA", _dt.date(2026, 4, 30), adapter=adapter)
    assert len(out) == 3
    # Sorted by timestamp ascending.
    assert out[0].source_id == "edgar:abc"
    assert out[1].source_id == "fred:CPIAUCSL"
    assert out[2].source_id == "test:1"


def test_ingest_events_default_adapter_returns_empty():
    out = ingest_events("NVDA", _dt.date(2026, 4, 30))
    assert out == []


# --------------------------------------------------------------------------- #
# materiality_classifier                                                      #
# --------------------------------------------------------------------------- #


def test_validate_payload_accepts_well_formed_m2():
    payload = {
        "classification": "M-2",
        "confidence": 0.8,
        "rationale": "Guidance cut implies thesis erosion.",
        "verbatim_quote": "execution remains strong",
        "cited_kill_criterion_id": None,
    }
    ok, reason, norm = _validate_payload(payload, "execution remains strong is the quote")
    assert ok, reason
    assert norm["classification"] == 2
    assert norm["confidence"] == 0.8


def test_validate_payload_rejects_m2_without_verbatim_quote():
    payload = {
        "classification": "M-2",
        "confidence": 0.8,
        "rationale": "",
        "verbatim_quote": "",
        "cited_kill_criterion_id": None,
    }
    ok, reason, _norm = _validate_payload(payload, "anything")
    assert not ok
    assert "verbatim" in reason.lower()


def test_validate_payload_rejects_non_substring_quote():
    payload = {
        "classification": "M-3",
        "confidence": 0.9,
        "rationale": "",
        "verbatim_quote": "this string is not in raw_text",
        "cited_kill_criterion_id": "kill_3",
    }
    ok, reason, _norm = _validate_payload(payload, "hello world")
    assert not ok
    assert "substring" in reason.lower()


def test_validate_payload_allows_m1_without_quote():
    payload = {
        "classification": "M-1",
        "confidence": 0.5,
        "rationale": "noise",
        "verbatim_quote": "",
        "cited_kill_criterion_id": None,
    }
    ok, _r, norm = _validate_payload(payload, "anything")
    assert ok
    assert norm["classification"] == 1


def test_classify_materiality_m1_no_escalation():
    ev = _evt()
    resp = json.dumps({
        "classification": "M-1",
        "confidence": 0.5,
        "rationale": "informational only",
        "verbatim_quote": "",
        "cited_kill_criterion_id": None,
    })
    client = _FakeClient({DEFAULT_MODEL: [resp]})
    v = classify_materiality(ticker="NVDA", event=ev, client=client)
    assert v.classification == MATERIALITY_M1
    assert v.tier_escalated_to_opus is False
    assert v.model == DEFAULT_MODEL
    assert len(client.calls) == 1


def test_classify_materiality_m3_escalates_to_opus():
    ev = _evt(verbatim="execution remains strong")
    sonnet_resp = json.dumps({
        "classification": "M-3",
        "confidence": 0.85,
        "rationale": "thesis-defining",
        "verbatim_quote": "execution remains strong",
        "cited_kill_criterion_id": "kill_1",
    })
    opus_resp = json.dumps({
        "classification": "M-3",
        "confidence": 0.95,
        "rationale": "Opus confirmed",
        "verbatim_quote": "execution remains strong",
        "cited_kill_criterion_id": "kill_1",
    })
    client = _FakeClient({
        DEFAULT_MODEL: [sonnet_resp],
        ESCALATION_MODEL: [opus_resp],
    })
    v = classify_materiality(ticker="NVDA", event=ev, client=client)
    assert v.classification == MATERIALITY_M3
    assert v.tier_escalated_to_opus is True
    assert v.model == ESCALATION_MODEL
    assert len(client.calls) == 2
    assert client.calls[0]["model"] == DEFAULT_MODEL
    assert client.calls[1]["model"] == ESCALATION_MODEL


def test_classify_materiality_opus_cannot_downgrade_m3():
    """Per Section 4.5 Q2: M-3 cannot downgrade."""
    ev = _evt(verbatim="execution remains strong")
    sonnet_resp = json.dumps({
        "classification": "M-3", "confidence": 0.8,
        "rationale": "thesis-defining", "verbatim_quote": "execution remains strong",
        "cited_kill_criterion_id": "kill_1",
    })
    opus_resp = json.dumps({
        "classification": "M-2", "confidence": 0.7,
        "rationale": "Opus thinks it's only M-2", "verbatim_quote": "execution remains strong",
        "cited_kill_criterion_id": "kill_1",
    })
    client = _FakeClient({DEFAULT_MODEL: [sonnet_resp], ESCALATION_MODEL: [opus_resp]})
    v = classify_materiality(ticker="NVDA", event=ev, client=client)
    assert v.classification == MATERIALITY_M3
    assert any("floored_to_M-3" in f for f in v.flags)


def test_classify_materiality_malformed_json_defaults_to_m1():
    ev = _evt()
    client = _FakeClient({DEFAULT_MODEL: ["this is not JSON at all"]})
    v = classify_materiality(ticker="NVDA", event=ev, client=client)
    assert v.classification == MATERIALITY_M1
    assert v.confidence == 0.0
    assert any("malformed" in f for f in v.flags)


# --------------------------------------------------------------------------- #
# router                                                                      #
# --------------------------------------------------------------------------- #


def _verdict(cls: int, conf: float = 0.8, kill: str = None, quote: str = "") -> MaterialityVerdict:
    return MaterialityVerdict(
        classification=cls,
        confidence=conf,
        rationale="",
        verbatim_quote=quote or ("q" if cls > 1 else ""),
        cited_kill_criterion_id=kill,
        model=DEFAULT_MODEL,
        prompt_version="test",
        tier_escalated_to_opus=False,
    )


def test_route_m1_is_no_op():
    r = route_materiality("NVDA", _evt(), _verdict(MATERIALITY_M1))
    assert r.action == "no_op"
    assert r.agents == []
    assert r.operator_alert is False


def test_route_m3_dispatches_all_five_agents_no_llm_call():
    client = _FakeClient({})  # no scripts; should never be called
    r = route_materiality("NVDA", _evt(), _verdict(MATERIALITY_M3), client=client)
    assert r.action == "full_reunderwrite"
    assert set(r.agents) == set(ALL_AGENTS)
    assert r.operator_alert is True
    assert client.calls == []


def test_route_m2_low_confidence_uses_fallback_table():
    ev = _evt(type_=EVENT_TYPE_EARNINGS_CALL)
    v = _verdict(MATERIALITY_M2, conf=JUDGE_CONFIDENCE_FLOOR - 0.1)
    r = route_materiality("NVDA", ev, v)
    assert r.action == "partial_reunderwrite"
    assert r.used_fallback_table is True
    assert set(r.agents) == set(EVENT_TYPE_AGENT_LOOKUP[EVENT_TYPE_EARNINGS_CALL])


def test_route_m2_high_confidence_calls_llm_picker():
    ev = _evt(type_=EVENT_TYPE_EARNINGS_CALL)
    v = _verdict(MATERIALITY_M2, conf=0.85)
    picker_resp = json.dumps({
        "agents": ["Quality", "Macro-Regime", "Value"],
        "rationale": "macro overlay matters here.",
    })
    client = _FakeClient({DEFAULT_MODEL: [picker_resp]})
    r = route_materiality("NVDA", ev, v, client=client)
    assert r.action == "partial_reunderwrite"
    assert r.used_fallback_table is False
    assert r.agents == ["Quality", "Macro-Regime", "Value"]
    assert r.agent_selection_model == DEFAULT_MODEL


def test_route_m2_invalid_picker_falls_back():
    ev = _evt(type_=EVENT_TYPE_EARNINGS_CALL)
    v = _verdict(MATERIALITY_M2, conf=0.85)
    # Picker returns only 1 agent (must be 2-4) → fallback fires.
    bad_resp = json.dumps({"agents": ["Quality"], "rationale": ""})
    client = _FakeClient({DEFAULT_MODEL: [bad_resp]})
    r = route_materiality("NVDA", ev, v, client=client)
    assert r.used_fallback_table is True


def test_fallback_table_default_when_event_type_unknown():
    out = fallback_agents_for_event("nonsense_event_type")
    assert out == ["Quality", "Value"]


# --------------------------------------------------------------------------- #
# cut_evaluator                                                               #
# --------------------------------------------------------------------------- #


def test_cut_mode_b_kills_floor():
    ctx = CutContext(kills_fired_today=2)
    d = evaluate_cut(MODE_B, ctx)
    assert d.cut_recommended
    assert any("kills_fired_today=2" in c for c in d.triggered_conditions)


def test_cut_mode_b_below_kills_floor_no_cut():
    ctx = CutContext(kills_fired_today=1)
    d = evaluate_cut(MODE_B, ctx)
    assert not d.cut_recommended


def test_cut_mode_b_drawdown_requires_quarters():
    ctx = CutContext(drawdown_pp_vs_benchmark=11.0, drawdown_quarters_sustained=2)
    d = evaluate_cut(MODE_B, ctx)
    assert not d.cut_recommended  # 2 quarters < 3 required for B
    ctx = CutContext(drawdown_pp_vs_benchmark=11.0, drawdown_quarters_sustained=3)
    d = evaluate_cut(MODE_B, ctx)
    assert d.cut_recommended


def test_cut_mode_b_prime_thesis_defining_kill():
    ctx = CutContext(kills_fired_today=1, thesis_defining_kill_fired=True)
    d = evaluate_cut(MODE_B_PRIME, ctx)
    assert d.cut_recommended


def test_cut_mode_b_prime_growth_inflection():
    ctx = CutContext(growth_yoy_recent_quarters=[-60.0, -55.0])
    d = evaluate_cut(MODE_B_PRIME, ctx)
    assert d.cut_recommended


def test_cut_mode_c_any_kill_fires():
    ctx = CutContext(kills_fired_today=1)
    d = evaluate_cut(MODE_C, ctx)
    assert d.cut_recommended


def test_cut_mode_c_bocpd_threshold():
    """Mode-C BOCPD trigger consumes ``bocpd_short_run_mass`` per
    operator-locked dual-signal architecture (v3 §4.1; migration 020).
    The CutContext.bocpd_against_thesis_prob input is sourced from
    regime_state.bocpd_short_run_mass NOT from the canonical marginal —
    the canonical marginal is structurally pinned near hazard rate and
    would never cross 0.7 in steady state.
    """
    ctx = CutContext(bocpd_against_thesis_prob=0.75)
    d = evaluate_cut(MODE_C, ctx)
    assert d.cut_recommended
    # Triggered-condition string should reflect short-run-mass semantic.
    assert any(
        "bocpd_short_run_mass_against_thesis" in c
        for c in d.triggered_conditions
    ), (
        "Mode-C BOCPD trigger string should reference short-run mass "
        f"semantic, got: {d.triggered_conditions}"
    )
    ctx = CutContext(bocpd_against_thesis_prob=0.69)
    d = evaluate_cut(MODE_C, ctx)
    assert not d.cut_recommended


def test_cut_mode_c_smart_money_exit():
    ctx = CutContext(smart_money_exit_verified=True)
    d = evaluate_cut(MODE_C, ctx)
    assert d.cut_recommended


def test_build_cut_context_counts_kills_and_thesis_defining():
    v1 = _verdict(MATERIALITY_M2, kill="k1")
    v2 = _verdict(MATERIALITY_M3, kill="k2", quote="q")
    v3 = _verdict(MATERIALITY_M1)
    meta = {
        "k1": {"thesis_defining": False, "tag": "other"},
        "k2": {"thesis_defining": True, "tag": "moat_erosion"},
    }
    ctx = build_cut_context_from_verdicts([v1, v2, v3], kill_criteria_meta=meta)
    assert ctx.kills_fired_today == 2
    assert ctx.thesis_defining_kill_fired is True
    assert ctx.moat_erosion_verbatim_confirmed is True


# --------------------------------------------------------------------------- #
# refresh_emitter (end-to-end, dry_run)                                       #
# --------------------------------------------------------------------------- #


def test_run_daily_refresh_dry_run_m1_no_alerts():
    ev = _evt()
    resp = json.dumps({
        "classification": "M-1", "confidence": 0.4,
        "rationale": "noise", "verbatim_quote": "",
        "cited_kill_criterion_id": None,
    })
    client = _FakeClient({DEFAULT_MODEL: [resp]})
    adapter = _StubAdapter({"earnings": [ev]})
    outcome = run_daily_refresh(
        ticker="NVDA",
        date=_dt.date(2026, 4, 30),
        mode=MODE_B_PRIME,
        event_adapter=adapter,
        llm_client=client,
        dry_run=True,
    )
    assert outcome.materiality_rollup == MATERIALITY_M1
    assert outcome.materiality_label == "M-1"
    assert outcome.recommended_action == "no_action"
    assert outcome.triggered_alerts == []
    assert not outcome.cut_decision.cut_recommended


def test_run_daily_refresh_dry_run_m3_full_pipeline():
    ev = _evt(verbatim="execution remains strong")
    sonnet = json.dumps({
        "classification": "M-3", "confidence": 0.85,
        "rationale": "thesis-defining", "verbatim_quote": "execution remains strong",
        "cited_kill_criterion_id": "k1",
    })
    opus = json.dumps({
        "classification": "M-3", "confidence": 0.92,
        "rationale": "Opus confirmed", "verbatim_quote": "execution remains strong",
        "cited_kill_criterion_id": "k1",
    })
    client = _FakeClient({DEFAULT_MODEL: [sonnet], ESCALATION_MODEL: [opus]})
    adapter = _StubAdapter({"earnings": [ev]})
    outcome = run_daily_refresh(
        ticker="NVDA",
        date=_dt.date(2026, 4, 30),
        mode=MODE_C,
        event_adapter=adapter,
        llm_client=client,
        kill_criteria_meta={"k1": {"thesis_defining": True, "tag": "other"}},
        dry_run=True,
    )
    assert outcome.materiality_rollup == MATERIALITY_M3
    assert outcome.cut_decision.cut_recommended  # any kill on Mode C
    assert outcome.recommended_action == "exit"
    # Routing for M-3 dispatches all 5 agents.
    assert set(outcome.routings[0].agents) == set(ALL_AGENTS)


def test_run_daily_refresh_with_stub_db_writer_writes_three_tables():
    """Verify the persistence layer issues SQL for all three tables on M-2."""
    ev = _evt(verbatim="execution remains strong")
    resp = json.dumps({
        "classification": "M-2", "confidence": 0.85,
        "rationale": "watch", "verbatim_quote": "execution remains strong",
        "cited_kill_criterion_id": "k1",
    })
    picker_resp = json.dumps({
        "agents": ["Quality", "Growth"],
        "rationale": "earnings remark.",
    })
    client = _FakeClient({DEFAULT_MODEL: [resp, picker_resp]})
    adapter = _StubAdapter({"earnings": [ev]})

    writes: list[tuple[str, tuple]] = []

    def stub_writer(sql: str, params: tuple):
        writes.append((sql, params))
        # Return a non-None UUID-like sentinel when the SQL uses RETURNING
        # so the orchestrator's conflict-detection logic doesn't mistake
        # this stub for a header-row no-op (which would skip downstream
        # event + alert INSERTs). Mirrors the real psycopg writer's
        # contract: row[0] from RETURNING is the inserted row's id.
        if "RETURNING" in sql.upper():
            # First param is always the row id (log_id / event_id / alert_id).
            return params[0] if params else uuid.uuid4()
        return None

    outcome = run_daily_refresh(
        ticker="NVDA",
        date=_dt.date(2026, 4, 30),
        mode=MODE_B_PRIME,
        event_adapter=adapter,
        llm_client=client,
        db_writer=stub_writer,
        dry_run=False,
    )
    sqls = [w[0] for w in writes]
    assert any("daily_refresh_log" in s for s in sqls)
    assert any("materiality_events" in s for s in sqls)
    assert any("unread_alerts" in s for s in sqls)
    assert outcome.materiality_rollup == MATERIALITY_M2


def test_m2_without_kill_criterion_writes_materiality_m2_alert():
    """Section 4.5 PB#4: every M-2 MUST fire an alert. Previously, M-2
    events without a `cited_kill_criterion_id` were suppressed (no
    unread_alerts row). Migration 017 added `materiality_m2` to the
    enum and refresh_emitter no longer suppresses.
    """
    ev = _evt(
        raw_text="Margin trajectory unchanged; FCF stable.",
        verbatim="Margin trajectory unchanged",
    )
    resp = json.dumps({
        "classification": "M-2", "confidence": 0.7,
        "rationale": "watch", "verbatim_quote": "Margin trajectory unchanged",
        # NO kill criterion cited.
        "cited_kill_criterion_id": None,
    })
    picker_resp = json.dumps({
        "agents": ["Quality"],
        "rationale": "monitoring.",
    })
    client = _FakeClient({DEFAULT_MODEL: [resp, picker_resp]})
    adapter = _StubAdapter({"earnings": [ev]})

    writes: list[tuple[str, tuple]] = []

    def stub_writer(sql: str, params: tuple):
        writes.append((sql, params))
        # Return a non-None UUID-like sentinel when the SQL uses RETURNING
        # so the orchestrator's conflict-detection logic doesn't mistake
        # this stub for a header-row no-op (which would skip downstream
        # event + alert INSERTs). Mirrors the real psycopg writer's
        # contract: row[0] from RETURNING is the inserted row's id.
        if "RETURNING" in sql.upper():
            # First param is always the row id (log_id / event_id / alert_id).
            return params[0] if params else uuid.uuid4()
        return None

    run_daily_refresh(
        ticker="NVDA",
        date=_dt.date(2026, 4, 30),
        mode=MODE_B_PRIME,
        event_adapter=adapter,
        llm_client=client,
        db_writer=stub_writer,
        dry_run=False,
    )

    alert_writes = [w for w in writes if "unread_alerts" in w[0]]
    assert len(alert_writes) == 1, (
        "M-2 must fire an unread_alerts row even without a kill criterion"
    )
    # alert_type is the 3rd positional in the INSERT (after alert_id, severity).
    params = alert_writes[0][1]
    assert params[2] == "materiality_m2", (
        f"expected alert_type='materiality_m2', got {params[2]!r}"
    )


# --------------------------------------------------------------------------- #
# drift_detector                                                              #
# --------------------------------------------------------------------------- #


def test_cohens_kappa_perfect_agreement():
    a = [1, 2, 3, 1, 2, 3]
    assert cohens_kappa(a, list(a)) == pytest.approx(1.0)


def test_cohens_kappa_near_zero_for_random():
    a = [1, 1, 1, 2, 2, 2, 3, 3, 3] * 4
    b = [1, 2, 3, 1, 2, 3, 1, 2, 3] * 4
    k = cohens_kappa(a, b)
    assert -0.2 < k < 0.2


def test_drift_check_below_min_sample_raises():
    gold = [
        GoldStandardEvent(uuid.uuid4(), 1, 1, 0.5)
        for _ in range(5)
    ]
    with pytest.raises(ValueError, match="sample_size"):
        run_quarterly_drift_check(period="2026-Q4", gold_standard=gold, dry_run=True)


def test_drift_check_high_kappa_no_alert():
    # Perfect agreement on 30 events.
    gold = [
        GoldStandardEvent(uuid.uuid4(), (i % 3) + 1, (i % 3) + 1, 0.8)
        for i in range(MIN_DRIFT_SAMPLE_SIZE)
    ]
    r = run_quarterly_drift_check(period="2026-Q4", gold_standard=gold, dry_run=True)
    assert r.kappa == pytest.approx(1.0)
    assert r.fired_m2_system_event is False
    assert r.flags == []


def test_drift_check_2_consec_below_floor_fires_m2():
    # Disagree often enough to push kappa below 0.61.
    gold: list[GoldStandardEvent] = []
    for i in range(MIN_DRIFT_SAMPLE_SIZE):
        op = (i % 3) + 1
        sys_ = ((i + 1) % 3) + 1  # systematically off
        gold.append(GoldStandardEvent(uuid.uuid4(), op, sys_, 0.5))
    writes: list[tuple[str, tuple]] = []

    def stub_writer(sql, params):
        writes.append((sql, params))
        return None

    r = run_quarterly_drift_check(
        period="2026-Q4",
        gold_standard=gold,
        prior_kappa_below_floor=True,
        db_writer=stub_writer,
        dry_run=False,
    )
    assert r.kappa < 0.61
    assert r.fired_m2_system_event is True
    sqls = [w[0] for w in writes]
    assert any("materiality_classifier_drift" in s for s in sqls)
    assert any("unread_alerts" in s for s in sqls)


def test_drift_check_p50_p90_shift_flags():
    # All-1 vs all-1 → kappa=1; but confidence shift > 0.1.
    gold = [
        GoldStandardEvent(uuid.uuid4(), 1, 1, 0.9)
        for _ in range(MIN_DRIFT_SAMPLE_SIZE)
    ]
    prior = type("P", (), {})()
    prior.rolling_gold_standard_event_ids = []
    prior.kappa = 1.0
    prior.confidence_p50 = 0.7
    prior.confidence_p90 = 0.7
    r = run_quarterly_drift_check(
        period="2026-Q4",
        gold_standard=gold,
        prior_quarter=prior,  # type: ignore[arg-type]
        dry_run=True,
    )
    assert r.confidence_p50 > 0.85
    assert any("p50_shift" in f for f in r.flags)


# --------------------------------------------------------------------------- #
# Transaction-boundary regression tests (multi-row write atomicity audit).    #
# --------------------------------------------------------------------------- #
#
# refresh_emitter writes 1 daily_refresh_log row + N materiality_events
# rows + 0/1 unread_alerts row. drift_detector writes 1 drift row + 0/1
# alert. Per Section 4.5 Q1 + Phase 4 Q8: all rows in a single
# run_daily_refresh / run_quarterly_drift_check call MUST commit together
# or roll back together. The original ``_default_db_writer`` opened a fresh
# psycopg2 connection per call → each row was its own transaction; the new
# ``_TransactionalDbWriter`` shares one connection across the whole batch.


def test_transactional_db_writer_rollback_on_mid_batch_failure():
    """Mid-batch exception → rollback the WHOLE batch; no partial commit.

    Simulates a CHECK violation on the 2nd materiality_events INSERT.
    The daily_refresh_log header row + first materiality event already
    issued ``cur.execute`` calls — those must NOT survive in the DB.
    """
    from src.l4_daily_monitor.refresh_emitter import _TransactionalDbWriter

    class _FakeCursor:
        def __init__(self, conn):
            self._conn = conn
            self.description = None

        def execute(self, sql, params):
            # Counter lives on the CONN (not the cursor) — cursor() returns
            # a fresh cursor per call so a per-cursor counter never advances.
            self._conn.calls += 1
            self._conn.executed.append((sql, params))
            if self._conn.calls > self._conn.fail_after:
                raise RuntimeError("simulated CHECK violation")

        def fetchone(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _FakeConn:
        def __init__(self, fail_after):
            self.executed: list = []
            self.committed = False
            self.rolled_back = False
            self.autocommit = True
            self.fail_after = fail_after
            self.calls = 0

        def cursor(self):
            return _FakeCursor(self)

        def commit(self):
            self.committed = True

        def rollback(self):
            self.rolled_back = True

        def close(self):
            pass

    fake = _FakeConn(fail_after=2)

    # Instantiate writer with a stubbed psycopg2.connect that returns our fake.
    writer = _TransactionalDbWriter(dsn="postgresql://stub")

    import sys
    import types

    fake_psycopg2 = types.ModuleType("psycopg2")
    fake_psycopg2.connect = lambda dsn: fake  # type: ignore[attr-defined]
    sys.modules["psycopg2"] = fake_psycopg2
    try:
        with pytest.raises(RuntimeError, match="simulated CHECK"):
            with writer as w:
                w("INSERT INTO daily_refresh_log ...", ())
                w("INSERT INTO materiality_events ...", ())
                w("INSERT INTO materiality_events ...", ())  # raises here
                w("INSERT INTO unread_alerts ...", ())  # never reached
    finally:
        sys.modules.pop("psycopg2", None)

    # 3 calls (the raising one is recorded before raise).
    assert len(fake.executed) == 3
    # Rollback MUST have been issued; commit MUST NOT.
    assert fake.rolled_back is True, "writer must rollback on mid-batch failure"
    assert fake.committed is False, "writer must NOT commit a partial batch"


def test_transactional_db_writer_commits_clean_batch():
    """Clean path: writer issues exactly ONE commit at exit."""
    from src.l4_daily_monitor.refresh_emitter import _TransactionalDbWriter

    class _FakeCursor:
        def __init__(self, conn):
            self._conn = conn
            self.description = None

        def execute(self, sql, params):
            self._conn.executed.append((sql, params))

        def fetchone(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _FakeConn:
        def __init__(self):
            self.executed: list = []
            self.committed = False
            self.rolled_back = False
            self.autocommit = True

        def cursor(self):
            return _FakeCursor(self)

        def commit(self):
            self.committed = True

        def rollback(self):
            self.rolled_back = True

        def close(self):
            pass

    fake = _FakeConn()
    writer = _TransactionalDbWriter(dsn="postgresql://stub")

    import sys
    import types

    fake_psycopg2 = types.ModuleType("psycopg2")
    fake_psycopg2.connect = lambda dsn: fake  # type: ignore[attr-defined]
    sys.modules["psycopg2"] = fake_psycopg2
    try:
        with writer as w:
            w("INSERT INTO daily_refresh_log ...", ())
            w("INSERT INTO materiality_events ...", ())
            w("INSERT INTO unread_alerts ...", ())
    finally:
        sys.modules.pop("psycopg2", None)

    assert len(fake.executed) == 3
    assert fake.committed is True
    assert fake.rolled_back is False
    # Autocommit was disabled inside the transaction window.
    assert fake.autocommit is False


def test_drift_detector_transactional_writer_rollback():
    """drift_detector._TransactionalDbWriter mirrors the refresh_emitter
    contract — drift row + M-2 alert commit together or roll back together.
    """
    from src.l4_daily_monitor.drift_detector import _TransactionalDbWriter as _DDW

    class _FakeCursor:
        def __init__(self, conn):
            self._conn = conn
            self.description = None

        def execute(self, sql, params):
            self._conn.calls += 1
            self._conn.executed.append((sql, params))
            if self._conn.calls > self._conn.fail_after:
                raise RuntimeError("simulated drift CHECK violation")

        def fetchone(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _FakeConn:
        def __init__(self, fail_after):
            self.executed: list = []
            self.committed = False
            self.rolled_back = False
            self.autocommit = True
            self.fail_after = fail_after
            self.calls = 0

        def cursor(self):
            return _FakeCursor(self)

        def commit(self):
            self.committed = True

        def rollback(self):
            self.rolled_back = True

        def close(self):
            pass

    fake = _FakeConn(fail_after=1)
    writer = _DDW(dsn="postgresql://stub")

    import sys
    import types

    fake_psycopg2 = types.ModuleType("psycopg2")
    fake_psycopg2.connect = lambda dsn: fake  # type: ignore[attr-defined]
    sys.modules["psycopg2"] = fake_psycopg2
    try:
        with pytest.raises(RuntimeError, match="simulated drift CHECK"):
            with writer as w:
                w("INSERT INTO materiality_classifier_drift ...", ())
                w("INSERT INTO unread_alerts ...", ())  # raises here
    finally:
        sys.modules.pop("psycopg2", None)

    assert fake.rolled_back is True
    assert fake.committed is False


# --------------------------------------------------------------------------- #
# Idempotency regression tests (idempotency audit, migration 022)             #
# --------------------------------------------------------------------------- #


def test_daily_refresh_idempotent_on_header_conflict_skips_downstream():
    """Re-running run_daily_refresh on the same (ticker, date) must NOT
    duplicate materiality_events + unread_alerts rows.

    Migration 009 declares UNIQUE(ticker, date) on daily_refresh_log; the
    INSERT now uses ON CONFLICT (ticker, date) DO NOTHING with RETURNING.
    A returning value of None signals "prior row already committed" — the
    orchestrator MUST skip the per-event + alert writes in that case.

    Bug class: a stub writer that returns None unconditionally was making
    the orchestrator think every run hit a conflict. Real psycopg returns
    row[0] from RETURNING on success; None on conflict. The stub here
    mimics the real contract (returns id-like value on first call,
    None on subsequent retries).
    """
    ev = _evt(verbatim="execution remains strong")
    resp = json.dumps({
        "classification": "M-2", "confidence": 0.85,
        "rationale": "watch", "verbatim_quote": "execution remains strong",
        "cited_kill_criterion_id": "k1",
    })
    picker_resp = json.dumps({
        "agents": ["Quality"], "rationale": "earnings remark.",
    })

    # Simulate "first invocation succeeds, retry hits ON CONFLICT no-op"
    # by tracking call count and returning None on the second header INSERT.
    state = {"daily_refresh_log_calls": 0}
    writes_first: list[tuple[str, tuple]] = []
    writes_retry: list[tuple[str, tuple]] = []

    def writer_first(sql: str, params: tuple):
        writes_first.append((sql, params))
        if "RETURNING" in sql.upper():
            return params[0] if params else uuid.uuid4()
        return None

    def writer_retry(sql: str, params: tuple):
        writes_retry.append((sql, params))
        # On retry: header INSERT hits ON CONFLICT and RETURNING yields no row.
        if "daily_refresh_log" in sql:
            return None  # simulate conflict no-op
        if "RETURNING" in sql.upper():
            return params[0] if params else uuid.uuid4()
        return None

    common_kwargs = dict(
        ticker="NVDA",
        date=_dt.date(2026, 4, 30),
        mode=MODE_B_PRIME,
        event_adapter=_StubAdapter({"earnings": [ev]}),
        llm_client=_FakeClient({DEFAULT_MODEL: [resp, picker_resp,
                                                 resp, picker_resp]}),
        dry_run=False,
    )

    run_daily_refresh(db_writer=writer_first, **common_kwargs)
    run_daily_refresh(db_writer=writer_retry, **common_kwargs)

    # First run: header + 1 event + 1 alert.
    first_event_writes = [w for w in writes_first if "materiality_events" in w[0]]
    first_alert_writes = [w for w in writes_first if "unread_alerts" in w[0]]
    assert len(first_event_writes) == 1
    assert len(first_alert_writes) == 1

    # Retry: header attempted, but conflict no-op → NO event, NO alert writes.
    retry_event_writes = [w for w in writes_retry if "materiality_events" in w[0]]
    retry_alert_writes = [w for w in writes_retry if "unread_alerts" in w[0]]
    assert len(retry_event_writes) == 0, (
        "retry on same (ticker, date) MUST NOT duplicate materiality_events"
    )
    assert len(retry_alert_writes) == 0, (
        "retry on same (ticker, date) MUST NOT duplicate unread_alerts"
    )


def test_daily_refresh_log_insert_uses_on_conflict_clause():
    """Sanity: the SQL emitted for daily_refresh_log carries the ON CONFLICT
    clause. Catches regression if someone removes the idempotency guard.
    """
    ev = _evt(verbatim="execution remains strong")
    resp = json.dumps({
        "classification": "M-1", "confidence": 0.8,
        "rationale": "noise", "verbatim_quote": "execution remains strong",
    })
    writes: list[tuple[str, tuple]] = []

    def stub_writer(sql: str, params: tuple):
        writes.append((sql, params))
        if "RETURNING" in sql.upper():
            return params[0] if params else uuid.uuid4()
        return None

    run_daily_refresh(
        ticker="NVDA",
        date=_dt.date(2026, 4, 30),
        mode=MODE_B_PRIME,
        event_adapter=_StubAdapter({"earnings": [ev]}),
        llm_client=_FakeClient({DEFAULT_MODEL: [resp]}),
        db_writer=stub_writer,
        dry_run=False,
    )
    log_writes = [w for w in writes if "daily_refresh_log" in w[0]]
    assert log_writes, "no daily_refresh_log INSERT was issued"
    sql = log_writes[0][0]
    assert "ON CONFLICT (ticker, date)" in sql, (
        f"daily_refresh_log INSERT missing ON CONFLICT clause: {sql!r}"
    )
    assert "DO NOTHING" in sql.upper()


def test_materiality_events_insert_uses_on_conflict_clause():
    """Sanity: the SQL emitted for materiality_events carries the
    natural-key ON CONFLICT clause (migration 022).
    """
    ev = _evt(verbatim="execution remains strong")
    resp = json.dumps({
        "classification": "M-2", "confidence": 0.85,
        "rationale": "watch", "verbatim_quote": "execution remains strong",
        "cited_kill_criterion_id": "k1",
    })
    picker_resp = json.dumps({
        "agents": ["Quality"], "rationale": "earnings remark.",
    })
    writes: list[tuple[str, tuple]] = []

    def stub_writer(sql: str, params: tuple):
        writes.append((sql, params))
        if "RETURNING" in sql.upper():
            return params[0] if params else uuid.uuid4()
        return None

    run_daily_refresh(
        ticker="NVDA",
        date=_dt.date(2026, 4, 30),
        mode=MODE_B_PRIME,
        event_adapter=_StubAdapter({"earnings": [ev]}),
        llm_client=_FakeClient({DEFAULT_MODEL: [resp, picker_resp]}),
        db_writer=stub_writer,
        dry_run=False,
    )
    ev_writes = [w for w in writes if "materiality_events" in w[0]]
    assert ev_writes
    sql = ev_writes[0][0]
    assert "ON CONFLICT" in sql
    assert "md5(verbatim_quote)" in sql or "md5( verbatim_quote )" in sql


def test_drift_check_insert_uses_on_conflict_period():
    """Sanity: the SQL emitted for materiality_classifier_drift carries the
    UNIQUE(period) ON CONFLICT clause (migration 010 + idempotency audit).
    """
    gold = [
        GoldStandardEvent(uuid.uuid4(), (i % 3) + 1, (i % 3) + 1, 0.8)
        for i in range(MIN_DRIFT_SAMPLE_SIZE)
    ]
    writes: list[tuple[str, tuple]] = []

    def stub_writer(sql: str, params: tuple):
        writes.append((sql, params))
        return None

    run_quarterly_drift_check(
        period="2026-Q4",
        gold_standard=gold,
        db_writer=stub_writer,
    )
    drift_writes = [w for w in writes if "materiality_classifier_drift" in w[0]]
    assert drift_writes
    sql = drift_writes[0][0]
    assert "ON CONFLICT (period)" in sql, (
        f"materiality_classifier_drift INSERT missing ON CONFLICT clause: {sql!r}"
    )
