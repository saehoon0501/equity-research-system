"""Smoke tests for the premortem_scheduler package (v3 Section 4.5 Q4).

Covers cadence, each event trigger, the scheduler OR-logic, the
recorder validation, and the devil's-advocate JSON parser. All tests
hermetic — no DB; recorder runs with persist=False.
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


# --------------------------------------------------------------------------- #
# cadence                                                                     #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "mode,days_since,expected_due",
    [
        ("B", 100, False),
        ("B", 180, True),
        ("B_prime", 119, False),
        ("B_prime", 120, True),
        ("C", 59, False),
        ("C", 60, True),
    ],
)
def test_cadence_threshold_per_mode(mode, days_since, expected_due):
    from premortem_scheduler.cadence import cadence_status

    today = _dt.date(2026, 4, 29)
    last = today - _dt.timedelta(days=days_since)
    s = cadence_status(
        "NVDA",
        mode,
        as_of=today.isoformat(),
        last_premortem_date=last,
    )
    assert s.due is expected_due
    assert s.days_since == days_since


def test_cadence_no_prior_due_immediately():
    from premortem_scheduler.cadence import cadence_status

    s = cadence_status(
        "NEW",
        "B",
        as_of="2026-04-29",
        last_premortem_date=None,
    )
    # When last is None and DB fetch returns nothing (offline test) it's due.
    # We can't guarantee no DB connection in CI, but the helper accepts a
    # None override so we patch by passing a sentinel via env-less DSN; on a
    # missing DB the fetch raises and falls through to None -> due=True.
    assert s.due is True


# --------------------------------------------------------------------------- #
# event_triggers                                                              #
# --------------------------------------------------------------------------- #


def test_thesis_confirmation_triggers_with_event():
    from premortem_scheduler.event_triggers import check_thesis_confirmation

    chk = check_thesis_confirmation(
        "NVDA",
        as_of="2026-04-29",
        events=[{
            "event_type": "thesis_confirmation",
            "event_date": _dt.date(2026, 4, 28),
        }],
    )
    assert chk.triggered is True
    assert chk.deadline_date == "2026-05-06"


def test_thesis_confirmation_no_event_no_trigger():
    from premortem_scheduler.event_triggers import check_thesis_confirmation

    chk = check_thesis_confirmation(
        "NVDA",
        as_of="2026-04-29",
        events=[{"event_type": "earnings_beat", "event_date": _dt.date.today()}],
    )
    assert chk.triggered is False


def test_consecutive_m2_within_window():
    from premortem_scheduler.event_triggers import check_consecutive_m2

    today = _dt.date(2026, 4, 29)
    chk = check_consecutive_m2(
        "NVDA",
        as_of=today.isoformat(),
        m2_events=[
            {"event_date": today - _dt.timedelta(days=5)},
            {"event_date": today - _dt.timedelta(days=20)},
        ],
    )
    assert chk.triggered is True
    assert chk.detail["m2_count_in_window"] == 2


def test_consecutive_m2_outside_window():
    from premortem_scheduler.event_triggers import check_consecutive_m2

    today = _dt.date(2026, 4, 29)
    chk = check_consecutive_m2(
        "NVDA",
        as_of=today.isoformat(),
        m2_events=[
            {"event_date": today - _dt.timedelta(days=5)},
            {"event_date": today - _dt.timedelta(days=60)},
        ],
    )
    assert chk.triggered is False


@pytest.mark.parametrize(
    "mode,drawdown_pp,expected",
    [
        ("B", 4.5, False),
        ("B", 5.0, True),
        ("B_prime", 6.5, False),
        ("B_prime", 7.5, True),
        ("C", 9.0, False),
        ("C", 10.0, True),
    ],
)
def test_auto_tighten_thresholds(mode, drawdown_pp, expected):
    from premortem_scheduler.event_triggers import check_auto_tighten

    chk = check_auto_tighten(
        "NVDA", mode, drawdown_vs_benchmark_pp=drawdown_pp
    )
    assert chk.triggered is expected


def test_mode_reclass_triggers_when_proposal_present():
    from premortem_scheduler.event_triggers import check_mode_reclass_proposed

    chk = check_mode_reclass_proposed(
        "NVDA",
        pending_proposal={
            "classification_id": "abc", "stored_mode": "B",
            "rule_outcomes": {}, "classified_at": "2026-04-29",
        },
    )
    assert chk.triggered is True


def test_mode_reclass_no_proposal_no_trigger():
    from premortem_scheduler.event_triggers import check_mode_reclass_proposed

    chk = check_mode_reclass_proposed("NVDA", pending_proposal=None)
    # When pending_proposal explicitly None and DB fetch yields nothing,
    # the helper falls through to fetcher; in test env psycopg may not
    # connect — _fetch returns None -> not triggered.
    assert chk.triggered is False


# --------------------------------------------------------------------------- #
# scheduler                                                                   #
# --------------------------------------------------------------------------- #


def _stub_check(triggered, code):
    from premortem_scheduler.event_triggers import TriggerCheck
    return TriggerCheck(triggered=triggered, trigger_code=code)


def test_scheduler_due_when_calendar_floor_only():
    from premortem_scheduler.cadence import CadenceStatus
    from premortem_scheduler.scheduler import schedule_check_one

    s = schedule_check_one(
        "NVDA", "B", as_of="2026-04-29",
        cadence_override=CadenceStatus(
            ticker="NVDA", mode="B",
            last_premortem_date="2025-10-01",
            days_since=210, threshold_days=180, due=True,
        ),
        event_overrides={
            "thesis_confirmation": _stub_check(False, "thesis_confirmation"),
            "consecutive_m2": _stub_check(False, "consecutive_m2"),
            "auto_tighten": _stub_check(False, "auto_tighten"),
            "mode_reclass": _stub_check(False, "mode_reclass"),
        },
    )
    assert s.due is True
    assert s.blocking is False
    assert s.primary_trigger == "calendar_floor"


def test_scheduler_blocking_on_mode_reclass():
    from premortem_scheduler.cadence import CadenceStatus
    from premortem_scheduler.scheduler import schedule_check_one

    s = schedule_check_one(
        "NVDA", "B", as_of="2026-04-29",
        cadence_override=CadenceStatus(
            ticker="NVDA", mode="B",
            last_premortem_date="2026-03-01",
            days_since=59, threshold_days=180, due=False,
        ),
        event_overrides={
            "thesis_confirmation": _stub_check(False, "thesis_confirmation"),
            "consecutive_m2": _stub_check(False, "consecutive_m2"),
            "auto_tighten": _stub_check(False, "auto_tighten"),
            "mode_reclass": _stub_check(True, "mode_reclass"),
        },
    )
    assert s.due is True
    assert s.blocking is True
    assert s.primary_trigger == "mode_reclass"


def test_scheduler_no_triggers_not_due():
    from premortem_scheduler.cadence import CadenceStatus
    from premortem_scheduler.scheduler import schedule_check_one

    s = schedule_check_one(
        "NVDA", "B_prime", as_of="2026-04-29",
        cadence_override=CadenceStatus(
            ticker="NVDA", mode="B_prime",
            last_premortem_date="2026-02-01",
            days_since=87, threshold_days=120, due=False,
        ),
        event_overrides={
            "thesis_confirmation": _stub_check(False, "thesis_confirmation"),
            "consecutive_m2": _stub_check(False, "consecutive_m2"),
            "auto_tighten": _stub_check(False, "auto_tighten"),
            "mode_reclass": _stub_check(False, "mode_reclass"),
        },
    )
    assert s.due is False
    assert s.triggers == []


# --------------------------------------------------------------------------- #
# devils_advocate                                                             #
# --------------------------------------------------------------------------- #


class _Block:
    def __init__(self, t):
        self.text = t


class _Resp:
    def __init__(self, t):
        self.content = [_Block(t)]


class _Msgs:
    def __init__(self, t):
        self._t = t

    def create(self, **kwargs):
        return _Resp(self._t)


class _Client:
    def __init__(self, t):
        self.messages = _Msgs(t)


def test_devils_advocate_parses_json_output():
    from premortem_scheduler.devils_advocate import generate_failure_modes

    text = json.dumps({"failure_modes": [
        {"mode": "demand_reversal", "mechanism": "...", "leading_indicator": "...",
         "probability_estimate": 0.2, "kill_criterion_proposal": "..."},
        {"mode": "competitive_intensity", "mechanism": "...", "leading_indicator": "...",
         "probability_estimate": 0.15, "kill_criterion_proposal": None},
        {"mode": "regulatory", "mechanism": "...", "leading_indicator": "...",
         "probability_estimate": 0.1, "kill_criterion_proposal": "..."},
    ]})
    out = generate_failure_modes(
        ticker="NVDA",
        mode="B_prime",
        thesis_pillars=[{"pillar": "moat", "confidence": 0.8}],
        client=_Client(text),
    )
    assert out.error is None
    assert len(out.failure_modes) == 3
    assert out.model.startswith("claude-opus")


def test_devils_advocate_handles_bad_json():
    from premortem_scheduler.devils_advocate import generate_failure_modes

    out = generate_failure_modes(
        ticker="NVDA",
        mode="B",
        thesis_pillars=[],
        client=_Client("not-json"),
    )
    assert out.failure_modes == []
    assert out.error is not None


# --------------------------------------------------------------------------- #
# recorder                                                                    #
# --------------------------------------------------------------------------- #


def test_recorder_validates_trigger_enum():
    from premortem_scheduler.recorder import PremortemRecord, record_premortem

    rec = PremortemRecord(
        ticker="NVDA",
        premortem_date="2026-04-29",
        trigger="not_a_real_trigger",
        mode="B",
    )
    with pytest.raises(ValueError):
        record_premortem(rec, persist=False)


def test_recorder_no_persist_returns_uuid(monkeypatch):
    from premortem_scheduler.devils_advocate import DevilsAdvocateOutput
    from premortem_scheduler.recorder import PremortemRecord, record_premortem

    monkeypatch.setenv("WATCHLIST_HMAC_SECRET", "test-secret-do-not-use")
    rec = PremortemRecord(
        ticker="NVDA",
        premortem_date="2026-04-29",
        trigger="calendar_floor",
        mode="B_prime",
        operator_imagined_failure_modes=[
            {"mode": "demand_reversal", "probability_estimate": 0.2,
             "kill_criterion_added": False, "rationale_for_skip": "covered"},
        ],
        thesis_pillars_revisited=[
            {"pillar": "moat", "still_holds": True,
             "confidence_delta": 0.0, "verbatim_evidence": "..."},
        ],
        net_thesis_strength=0.62,
        operator_accepted_count=2,
        operator_rejected_count=1,
        days_since_last_premortem=128,
        llm_assist=DevilsAdvocateOutput(
            model="claude-opus-4-7", failure_modes=[]
        ),
    )
    pid = record_premortem(rec, persist=False)
    assert pid is not None
    # uuid stringified is 36 chars
    assert len(str(pid)) == 36


# --------------------------------------------------------------------------- #
# Idempotency regression tests (idempotency audit, migration 022)             #
# --------------------------------------------------------------------------- #


def test_premortem_recorder_uses_on_conflict_clause():
    """Migration 022 adds UNIQUE (ticker, premortem_date, trigger) on
    premortem. The recorder must use ON CONFLICT DO NOTHING so an operator
    double-click submission becomes a silent no-op instead of duplicating
    the row.

    Bug class: the v0.1 INSERT had no idempotency. Operator submits a
    pre-mortem, network glitches, operator clicks again — two rows with
    the same payload but different premortem_id and signed_at. Audit chain
    becomes ambiguous (which row is canonical?) and the cadence-floor
    detector double-counts the session.
    """
    import inspect
    from premortem_scheduler.recorder import record_premortem

    src = inspect.getsource(record_premortem)
    assert "ON CONFLICT (ticker, premortem_date, trigger)" in src, (
        "record_premortem must use ON CONFLICT (ticker, premortem_date, "
        "trigger) DO NOTHING per migration 022"
    )
    assert "DO NOTHING" in src
    # Conflict path must re-fetch the prior premortem_id so /audit-trail
    # still has a stable handle.
    assert "SELECT premortem_id FROM premortem" in src
