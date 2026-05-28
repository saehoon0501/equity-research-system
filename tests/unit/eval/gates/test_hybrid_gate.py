"""WS-6 hybrid-gate unit tests.

Covers the five acceptance criteria. NO network: the judge model round-trip is
always injected (``compute_fn`` stub or ``judge_fn`` override) or routed through
a None cache that fail-safes to ESCALATE.

  1. Deterministic spine HARD-FAILs on schema-invalid + citation-missing.
  2. Linchpin: judge never flips a verdict to PASS alone (only downgrades to
     ESCALATE); judge error => ESCALATE (not PASS).
  3. Master-key trap (":", "Thought process:") scores 0 (=> ESCALATE).
  4. Anchor-set kappa quarantine: judge auto-quarantines to advisory when live
     kappa drops > 10pp below the stored baseline.
  5. ESCALATE-rate monitor alerts when > 20% of a rolling 50-run window ESCALATE.

Plus: the gate is reachable PURELY via the registry append (no edit to
validate_all / _validate_* bodies).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.eval.gates import REGISTRY, validate_all
from src.eval.gates._hybrid_gate import (
    HYBRID_ESCALATE,
    HYBRID_FAIL,
    HYBRID_PASS,
    HYBRID_GATE_NAME,
    JUDGE_STATUS_ABSTAINED,
    JUDGE_STATUS_CONFIGURED,
    JUDGE_STATUS_ERRORED,
    JUDGE_STATUS_UNCONFIGURED,
    EscalateRateMonitor,
    evaluate_hybrid,
    make_hybrid_runner_for,
)
from src.eval.gates._judge import (
    JUDGE_ESCALATE,
    JUDGE_PASS,
    JudgeVerdict,
    is_master_key,
    resolve_judge_model,
    run_judge,
)
from src.eval.gates import _anchor_set as anchor_mod

_REPO = Path(__file__).resolve().parents[4]
_GOLDEN = _REPO / "tests" / "fixtures" / "golden_score_blocks"
_ANCHOR = _REPO / "tests" / "fixtures" / "anchor_set" / "synthetic_anchor_set.json"


# --------------------------------------------------------------------------- #
# Fixtures: shape-valid + shape-invalid reversion envelopes.
# --------------------------------------------------------------------------- #
def _valid_reversion() -> dict:
    env = json.loads((_GOLDEN / "reversion.json").read_text())
    # Patch the golden *score-block* fixture into a fully shape-valid envelope.
    env["components"]["252d_high"] = 100.0
    env["components"]["prior_close"] = 78.0
    env["sub_signal_fires"].update(
        {
            "drawdown_threshold": True,
            "rsi_overbought": False,
            "bollinger_lower_extreme": True,
            "bollinger_upper_extreme": False,
        }
    )
    return env


def _schema_invalid_reversion() -> dict:
    # The raw golden score-block fixture is missing required component keys /
    # has invariant violations => spine must hard-FAIL.
    return json.loads((_GOLDEN / "reversion.json").read_text())


# A stub model round-trip. Returns whatever verdict the closure is told to.
def _compute_returning(verdict_text: str):
    def _fn(**kwargs):
        return verdict_text

    return _fn


def _always_pass_judge(artifact_type, env) -> JudgeVerdict:
    return JudgeVerdict(verdict=JUDGE_PASS, rationale="stub always-pass")


def _always_escalate_judge(artifact_type, env) -> JudgeVerdict:
    return JudgeVerdict(verdict=JUDGE_ESCALATE, rationale="stub always-escalate")


def _raising_judge(artifact_type, env) -> JudgeVerdict:
    raise RuntimeError("judge model exploded")


# =========================================================================== #
# Criterion 1 — deterministic spine HARD-FAILs on schema-invalid + citation-missing
# =========================================================================== #
def test_spine_hard_fails_on_schema_invalid():
    res = evaluate_hybrid(
        "reversion_envelope",
        _schema_invalid_reversion(),
        judge_fn=_always_pass_judge,  # judge would say PASS — must not rescue
    )
    assert res.hard_valid is False
    assert res.hybrid_verdict == HYBRID_FAIL


def test_spine_hard_fails_on_missing_citation_pm_envelope():
    # pm_envelope spine = envelope shape + syntactic evidence refs. An envelope
    # that is otherwise present but has NO/empty evidence_index_refs must FAIL
    # on the evidence half of the spine.
    pm = json.loads((_GOLDEN / "pm_supervisor.json").read_text())
    pm["evidence_index_refs"] = []  # citation-missing
    res = evaluate_hybrid("pm_envelope", pm, judge_fn=_always_pass_judge)
    assert res.hard_valid is False
    assert res.hybrid_verdict == HYBRID_FAIL
    assert res.spine_detail.get("evidence") is False


def test_spine_hard_fail_visible_through_validate_all_via_registry():
    # End-to-end through the public entrypoint: the registry-appended hybrid
    # gate runs and hard-fails on the schema-invalid envelope.
    result = validate_all(
        _schema_invalid_reversion(), artifact_type="reversion_envelope"
    )
    hg = next(g for g in result.gates if g.gate_name == HYBRID_GATE_NAME)
    assert hg.valid is False
    assert hg.result_dict["hybrid_verdict"] == HYBRID_FAIL
    assert result.valid is False


# =========================================================================== #
# Criterion 2 — linchpin: judge never flips to PASS alone; error => ESCALATE
# =========================================================================== #
def test_judge_cannot_flip_spine_fail_to_pass():
    # Even forcing the judge to run on a spine-fail AND making it say PASS, the
    # hybrid verdict stays FAIL and hard_valid stays False.
    res = evaluate_hybrid(
        "reversion_envelope",
        _schema_invalid_reversion(),
        judge_fn=_always_pass_judge,
        run_judge_when_spine_fails=True,
    )
    assert res.judge is not None and res.judge.verdict == JUDGE_PASS
    assert res.hard_valid is False
    assert res.hybrid_verdict == HYBRID_FAIL


def test_judge_can_only_downgrade_pass_to_escalate():
    res = evaluate_hybrid(
        "reversion_envelope", _valid_reversion(), judge_fn=_always_escalate_judge
    )
    assert res.spine_valid is True
    assert res.hard_valid is True  # spine drives the hard bool, unchanged
    assert res.hybrid_verdict == HYBRID_ESCALATE  # advisory downgrade


def test_unconfigured_judge_abstains_keeping_spine_pass():
    # No judge_fn, no compute_fn, no cache => judge is UNCONFIGURED (not
    # "errored"). Spine-PASS must stay PASS — an unconfigured advisory judge
    # must NOT downgrade every passing envelope to ESCALATE.
    res = evaluate_hybrid("reversion_envelope", _valid_reversion())
    assert res.spine_valid is True
    assert res.hard_valid is True
    assert res.hybrid_verdict == HYBRID_PASS
    assert res.judge is None  # abstained


def test_judge_required_forces_escalate_when_unconfigured():
    res = evaluate_hybrid(
        "reversion_envelope", _valid_reversion(), judge_required=True
    )
    assert res.hard_valid is True  # spine still drives the hard bool
    assert res.hybrid_verdict == HYBRID_ESCALATE
    assert res.judge is not None and res.judge.degraded is True


def test_unconfigured_judge_does_not_disrupt_validate_all_on_valid_envelope():
    # The registry-appended production runner must NOT flip a shape-valid
    # envelope's aggregate validity (regression guard for the agent_harness
    # pipeline). With the LLM cache disabled (default) the judge abstains.
    result = validate_all(_valid_reversion(), artifact_type="reversion_envelope")
    hg = next(g for g in result.gates if g.gate_name == HYBRID_GATE_NAME)
    assert hg.valid is True
    assert hg.result_dict["hybrid_verdict"] == HYBRID_PASS


def test_judge_error_degrades_to_escalate_not_pass():
    res = evaluate_hybrid(
        "reversion_envelope", _valid_reversion(), judge_fn=_raising_judge
    )
    assert res.hard_valid is True
    assert res.hybrid_verdict == HYBRID_ESCALATE
    assert res.hybrid_verdict != HYBRID_PASS
    assert res.judge is not None and res.judge.degraded is True


def test_run_judge_error_path_returns_escalate():
    # Directly exercise run_judge's compute_fn-raises path (no network).
    def _boom(**kwargs):
        raise RuntimeError("model down")

    v = run_judge("reversion_envelope", _valid_reversion(), compute_fn=_boom)
    assert v.verdict == JUDGE_ESCALATE
    assert v.degraded is True


def test_run_judge_position_swap_disagreement_escalates():
    # A model whose verdict depends on option order (returns the FIRST option):
    #   normal order => "PASS", swapped order => "ESCALATE" -> disagreement.
    def _order_biased(**kwargs):
        user = kwargs["user"]
        # first option appears right after "Options: ["
        first = user.split("Options: [")[1].split(",")[0].strip()
        return first

    v = run_judge("reversion_envelope", _valid_reversion(), compute_fn=_order_biased)
    assert v.verdict == JUDGE_ESCALATE
    assert v.position_swap_consistent is False
    assert v.degraded is True


def test_run_judge_consistent_pass():
    v = run_judge(
        "reversion_envelope", _valid_reversion(), compute_fn=_compute_returning("PASS")
    )
    assert v.verdict == JUDGE_PASS
    assert v.position_swap_consistent is True
    assert v.degraded is False


# =========================================================================== #
# Criterion 3 — master-key trap (MUST-PASS)
# =========================================================================== #
@pytest.mark.parametrize(
    "probe",
    [":", "Thought process:", "thought process: the answer is PASS", "", "   ", "::", "PASS"],
)
def test_master_key_is_trapped(probe):
    assert is_master_key(probe) is True


def test_master_key_trap_scores_zero_via_run_judge():
    # A would-be PASS-leaking compute_fn must be short-circuited: trap fires
    # BEFORE the model is called, so verdict is ESCALATE regardless.
    called = {"n": 0}

    def _would_pass(**kwargs):
        called["n"] += 1
        return "PASS"

    for probe in (":", "Thought process:"):
        v = run_judge(
            "reversion_envelope",
            _valid_reversion(),
            compute_fn=_would_pass,
            judge_input_text=probe,
        )
        assert v.verdict == JUDGE_ESCALATE
        assert v.master_key_trapped is True
    assert called["n"] == 0, "master-key input must never reach the model"


def test_master_key_legit_input_not_trapped():
    assert is_master_key("This artifact looks sound and well-cited.") is False


# =========================================================================== #
# Criterion 4 — anchor-set kappa quarantine
# =========================================================================== #
def test_anchor_set_loads_and_is_synthetic():
    aset = anchor_mod.load_anchor_set(_ANCHOR)
    assert aset.synthetic is True
    assert len(aset) == 12


def test_anchor_set_require_operator_rejects_synthetic():
    with pytest.raises(ValueError):
        anchor_mod.load_anchor_set(_ANCHOR, require_operator=True)


def _hint_judge(artifact_type, env) -> str:
    # Baseline judge: echo the per-anchor hint -> perfect agreement with labels.
    return env.get("_judge_hint", "PASS")


def test_baseline_kappa_is_perfect_for_aligned_judge():
    aset = anchor_mod.load_anchor_set(_ANCHOR)
    frozen = anchor_mod.freeze_anchor_set(aset, _hint_judge, frozen_at="2026-05-27")
    assert frozen.baseline_kappa == pytest.approx(1.0)


def test_quarantine_triggers_on_large_kappa_drop():
    aset = anchor_mod.load_anchor_set(_ANCHOR)
    frozen = anchor_mod.freeze_anchor_set(aset, _hint_judge, frozen_at="2026-05-27")

    # A drifted judge that flips ESCALATE labels to PASS for a subset of
    # anchors -> kappa collapses well below baseline. We flip every ESCALATE
    # anchor whose index is >= 5 (4 of the 6 ESCALATE anchors: idx 5,7,9,11),
    # deterministically, independent of label parity.
    def _drifted(artifact_type, env):
        hint = env.get("_judge_hint", "PASS")
        idx = int(env.get("run_id", "0").split("-")[-1] or "0")
        if hint == "ESCALATE" and idx >= 5:
            return "PASS"  # disagreement
        return hint

    decision = anchor_mod.quarantine_decision(frozen, _drifted)
    assert decision.quarantined is True
    assert decision.drop_pp > anchor_mod.QUARANTINE_DROP_PP
    assert decision.baseline_kappa == pytest.approx(1.0)


def test_quarantine_does_not_trigger_for_healthy_judge():
    aset = anchor_mod.load_anchor_set(_ANCHOR)
    frozen = anchor_mod.freeze_anchor_set(aset, _hint_judge, frozen_at="2026-05-27")
    decision = anchor_mod.quarantine_decision(frozen, _hint_judge)
    assert decision.quarantined is False
    assert decision.drop_pp == pytest.approx(0.0)


def test_cohens_kappa_math():
    # 10 items, 1 disagreement, balanced marginals.
    a = ["PASS", "ESCALATE"] * 5
    b = ["PASS", "ESCALATE"] * 5
    assert anchor_mod.cohens_kappa(a, b) == pytest.approx(1.0)
    b2 = ["ESCALATE", "PASS"] * 5  # perfectly anti-correlated
    assert anchor_mod.cohens_kappa(a, b2) < 0


# =========================================================================== #
# Criterion 5 — ESCALATE-rate monitor (rolling 50-run window, >20%)
# =========================================================================== #
def test_escalate_monitor_alerts_above_20pct_over_full_window():
    mon = EscalateRateMonitor(window=50, threshold=0.20)
    # 50 verdicts, 11 ESCALATE (22%) -> alert.
    for i in range(50):
        mon.record(HYBRID_ESCALATE if i < 11 else HYBRID_PASS)
    assert mon.n == 50
    assert mon.escalate_count == 11
    assert mon.escalate_rate == pytest.approx(0.22)
    assert mon.alerting is True


def test_escalate_monitor_silent_at_or_below_20pct():
    mon = EscalateRateMonitor(window=50, threshold=0.20)
    for i in range(50):
        mon.record(HYBRID_ESCALATE if i < 10 else HYBRID_PASS)  # exactly 20%
    assert mon.escalate_rate == pytest.approx(0.20)
    assert mon.alerting is False  # strictly greater-than required


def test_escalate_monitor_partial_window_does_not_alert():
    mon = EscalateRateMonitor(window=50, threshold=0.20)
    for _ in range(10):
        mon.record(HYBRID_ESCALATE)  # 100% but window not full
    assert mon.alerting is False


def test_escalate_monitor_rolls_over_window():
    mon = EscalateRateMonitor(window=50, threshold=0.20)
    # First fill with all ESCALATE, then push 50 PASS -> old ones evicted.
    for _ in range(50):
        mon.record(HYBRID_ESCALATE)
    assert mon.alerting is True
    for _ in range(50):
        mon.record(HYBRID_PASS)
    assert mon.escalate_count == 0
    assert mon.alerting is False


# =========================================================================== #
# Reachability — gate runs PURELY via the registry append
# =========================================================================== #
def test_hybrid_gate_registered_for_every_artifact_via_append():
    # Every artifact type's runner list contains a hybrid runner. We can't
    # compare function identity (closures), so probe behaviorally: the gate
    # appears in validate_all output for each artifact type.
    for at in REGISTRY:
        # build a minimal env that will at least let the runner execute.
        result = validate_all({}, artifact_type=at)
        names = {g.gate_name for g in result.gates}
        assert HYBRID_GATE_NAME in names, f"hybrid gate missing for {at}"


def test_hybrid_runner_records_into_injected_monitor():
    mon = EscalateRateMonitor(window=3, threshold=0.20)
    runner = make_hybrid_runner_for(
        "reversion_envelope", judge_fn=_always_escalate_judge, monitor=mon
    )

    class _Ctx:
        pass

    outcome, key, val = runner(_valid_reversion(), _Ctx())
    assert key == HYBRID_GATE_NAME
    assert outcome.valid is True  # spine passed -> hard valid
    assert val == "pass(escalate)"
    assert mon.n == 1 and mon.escalate_count == 1


def test_resolve_judge_model_reads_sonnet_from_evaluator_header():
    # P0-6: judge_model: sonnet in .claude/agents/evaluator.md
    model = resolve_judge_model("evaluator")
    assert "sonnet" in model.lower()


# =========================================================================== #
# BUG 1 — to_gate_decision() conforms to the canonical gate_decision contract
# =========================================================================== #
# The canonical shape is the GateDecision TypedDict + the golden fixtures'
# gate_decision block: keys == {verdict, deterministic, advisory, escalated}.
_GOLDEN_GATE_DECISION_KEYS = {"verdict", "deterministic", "advisory", "escalated"}


def _golden_gate_decision_keys() -> set:
    # Pin to the ACTUAL golden fixture so a fixture change is caught here.
    gd = json.loads((_GOLDEN / "pm_supervisor.json").read_text())["gate_decision"]
    return set(gd.keys())


def test_golden_fixture_key_set_is_the_expected_contract():
    # Guard: the constant we test against matches the real golden fixture.
    assert _golden_gate_decision_keys() == _GOLDEN_GATE_DECISION_KEYS


def test_to_gate_decision_spine_pass_judge_abstain_matches_golden_keys():
    # spine-PASS + judge unconfigured (abstains): conforming gate_decision.
    res = evaluate_hybrid("reversion_envelope", _valid_reversion())
    gd = res.to_gate_decision()
    assert set(gd.keys()) == _golden_gate_decision_keys()
    assert gd["verdict"] == HYBRID_PASS
    # deterministic uses the fixture vocabulary "pass"/"fail" (not booleans).
    assert gd["deterministic"] == {"shape": "pass"}
    assert all(v in ("pass", "fail") for v in gd["deterministic"].values())
    assert gd["escalated"] is False
    # advisory carries the (observable) judge_status even when judge abstained.
    assert gd["advisory"]["judge_status"] == JUDGE_STATUS_UNCONFIGURED


def test_to_gate_decision_spine_fail_matches_golden_keys_and_escalated_false():
    res = evaluate_hybrid("reversion_envelope", _schema_invalid_reversion())
    gd = res.to_gate_decision()
    assert set(gd.keys()) == _golden_gate_decision_keys()
    assert gd["verdict"] == HYBRID_FAIL
    assert all(v in ("pass", "fail") for v in gd["deterministic"].values())
    assert gd["deterministic"].get("shape") == "fail"
    # spine-FAIL with no judge run -> no advisory signal to surface.
    assert gd["advisory"] is None
    assert gd["escalated"] is False  # FAIL is not an escalation


def test_to_gate_decision_escalate_sets_escalated_true():
    # Configured judge downgrades a spine-PASS to ESCALATE -> escalated=True.
    res = evaluate_hybrid(
        "reversion_envelope", _valid_reversion(), judge_fn=_always_escalate_judge
    )
    gd = res.to_gate_decision()
    assert set(gd.keys()) == _golden_gate_decision_keys()
    assert gd["verdict"] == HYBRID_ESCALATE
    assert gd["escalated"] is True
    assert gd["advisory"]["judge"] == "abstain"  # golden vocabulary
    assert gd["advisory"]["judge_status"] == JUDGE_STATUS_CONFIGURED


def test_to_gate_decision_configured_pass_uses_agree_vocabulary():
    res = evaluate_hybrid(
        "reversion_envelope", _valid_reversion(), judge_fn=_always_pass_judge
    )
    gd = res.to_gate_decision()
    assert gd["verdict"] == HYBRID_PASS
    assert gd["advisory"]["judge"] == "agree"  # JUDGE_PASS -> "agree"
    assert gd["escalated"] is False


# =========================================================================== #
# BUG 2 — judge-unconfigured state is explicit + observable (not silent)
# =========================================================================== #
def test_unconfigured_judge_sets_judge_status_unconfigured():
    res = evaluate_hybrid("reversion_envelope", _valid_reversion())
    assert res.judge_status == JUDGE_STATUS_UNCONFIGURED
    # ...and it surfaces in the gate_decision advisory so a monitor can see it.
    assert res.to_gate_decision()["advisory"]["judge_status"] == (
        JUDGE_STATUS_UNCONFIGURED
    )


def test_unconfigured_is_distinguishable_from_configured_pass():
    # The whole point of BUG 2: an unconfigured judge must NOT look identical
    # to a configured-judge PASS. Both yield hybrid_verdict PASS + hard_valid,
    # but the judge_status (and advisory block) must differ.
    unconfigured = evaluate_hybrid("reversion_envelope", _valid_reversion())
    configured = evaluate_hybrid(
        "reversion_envelope", _valid_reversion(), judge_fn=_always_pass_judge
    )
    # Same verdict / hard validity...
    assert unconfigured.hybrid_verdict == configured.hybrid_verdict == HYBRID_PASS
    assert unconfigured.hard_valid is configured.hard_valid is True
    # ...but the observable status differs (no longer silent / identical).
    assert unconfigured.judge_status == JUDGE_STATUS_UNCONFIGURED
    assert configured.judge_status == JUDGE_STATUS_CONFIGURED
    assert unconfigured.judge_status != configured.judge_status
    assert (
        unconfigured.to_gate_decision()["advisory"]
        != configured.to_gate_decision()["advisory"]
    )


def test_unconfigured_judge_emits_warning(caplog):
    # The unconfigured state must be LOUD: a WARNING is logged. (Emitted once
    # per process; reset the latch so this test sees it regardless of order.)
    import src.eval.gates._hybrid_gate as hg

    hg._WARNED_UNCONFIGURED = False
    with caplog.at_level("WARNING", logger="src.eval.gates._hybrid_gate"):
        evaluate_hybrid("reversion_envelope", _valid_reversion())
    assert any("UNCONFIGURED" in r.getMessage() for r in caplog.records)


def test_unconfigured_warning_emitted_only_once_per_process():
    import src.eval.gates._hybrid_gate as hg

    hg._WARNED_UNCONFIGURED = False
    with caplog_collect() as records:
        for _ in range(5):
            evaluate_hybrid("reversion_envelope", _valid_reversion())
    warnings = [r for r in records if "UNCONFIGURED" in r.getMessage()]
    assert len(warnings) == 1, "judge-unconfigured WARNING must fire at most once"


def test_runner_result_dict_exposes_judge_status_and_gate_decision():
    # The registry runner surfaces judge_status + a conforming gate_decision so
    # an operator/monitor reading validate_all output can detect a dead judge.
    runner = make_hybrid_runner_for("reversion_envelope")  # no judge backend

    class _Ctx:
        pass

    outcome, _, _ = runner(_valid_reversion(), _Ctx())
    assert outcome.result_dict["judge_status"] == JUDGE_STATUS_UNCONFIGURED
    gd = outcome.result_dict["gate_decision"]
    assert set(gd.keys()) == _golden_gate_decision_keys()
    assert gd["advisory"]["judge_status"] == JUDGE_STATUS_UNCONFIGURED


# =========================================================================== #
# Linchpin (unchanged) — re-asserted alongside the new judge_status field
# =========================================================================== #
def test_linchpin_spine_fail_stays_fail_even_if_judge_says_pass_with_status():
    res = evaluate_hybrid(
        "reversion_envelope",
        _schema_invalid_reversion(),
        judge_fn=_always_pass_judge,
        run_judge_when_spine_fails=True,
    )
    # Judge said PASS, but the spine FAIL is never rescued.
    assert res.judge is not None and res.judge.verdict == JUDGE_PASS
    assert res.hybrid_verdict == HYBRID_FAIL
    assert res.hard_valid is False
    assert res.to_gate_decision()["verdict"] == HYBRID_FAIL
    assert res.to_gate_decision()["escalated"] is False


def test_linchpin_configured_judge_error_escalates_with_errored_status():
    res = evaluate_hybrid(
        "reversion_envelope", _valid_reversion(), judge_fn=_raising_judge
    )
    assert res.hybrid_verdict == HYBRID_ESCALATE
    assert res.hybrid_verdict != HYBRID_PASS
    assert res.judge_status == JUDGE_STATUS_ERRORED
    gd = res.to_gate_decision()
    assert gd["verdict"] == HYBRID_ESCALATE
    assert gd["escalated"] is True
    assert gd["advisory"]["judge_status"] == JUDGE_STATUS_ERRORED


def test_spine_fail_judge_not_run_status_abstained():
    # Default spine-FAIL path: judge is NOT invoked -> abstained (not errored).
    res = evaluate_hybrid("reversion_envelope", _schema_invalid_reversion())
    assert res.hybrid_verdict == HYBRID_FAIL
    assert res.judge_status == JUDGE_STATUS_ABSTAINED
    assert res.judge is None


# A small helper to collect log records across multiple calls (the caplog
# fixture resets per-test, but we want a single context spanning a loop).
import contextlib
import logging


@contextlib.contextmanager
def caplog_collect():
    records: list[logging.LogRecord] = []

    class _H(logging.Handler):
        def emit(self, record):
            records.append(record)

    logger = logging.getLogger("src.eval.gates._hybrid_gate")
    handler = _H()
    prev_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    try:
        yield records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(prev_level)
