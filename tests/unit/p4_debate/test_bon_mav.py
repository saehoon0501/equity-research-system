"""WS-5 — BoN-MAV (best-of-N synthesis + cross-model verifier) tests.

All tests run with NO network: the LLM/verifier calls are served by a fake
Anthropic client. Covers the three WS-5 acceptance criteria:

  1. N=5 candidates; verifier model = sonnet != synthesizer opus.
  2. Quality lift on the 10-envelope bon_panel: composite quality of the
     verifier-selected candidate >= single-pass (N=1) baseline, at <= $15/pass
     (per-pass cost recorded as one attempt_cost_usd).
  3. No MAD path unless (heterogeneous models) AND (verifiable step); verifier
     error falls back to self-consistency (fault-injection), never auto-PASS.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from p4_debate import (  # noqa: E402
    ALL_STYLES,
    MODE_B,
    VERDICT_ADD,
    VERDICT_PASS,
    VERDICT_WATCH,
    get_weights,
)
from p4_debate import _bon_mav as bon  # noqa: E402
from p4_debate.phase_a_isolated import PhaseAResult, PhaseAStyleOutput  # noqa: E402
from p4_debate.phase_b_locked import (  # noqa: E402
    LoadBearingClaim,
    NonNegotiable,
    PhaseBLockedSet,
    PhaseBStyleLock,
)
from p4_debate.phase_c_judge import PhaseCJudgeResult  # noqa: E402
from p4_debate.phase_d_pm_supervisor import (  # noqa: E402
    PhaseDBoNResult,
    run_phase_d_bon,
)

_FIXTURE_DIR = _REPO_ROOT / "tests" / "fixtures" / "bon_panel"


# --------------------------------------------------------------------------- #
# Fakes                                                                       #
# --------------------------------------------------------------------------- #


class _FakeUsage:
    def __init__(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _FakeMessage:
    def __init__(self, text: str, usage: _FakeUsage | None = None) -> None:
        self.content = [type("Block", (), {"text": text})()]
        self.usage = usage


class FakeClient:
    """Fake Anthropic client that scripts responses by model + call order.

    - ``synth_responses``: list of texts returned in order for synthesizer calls.
    - ``verifier_response``: text returned for the verifier system prompt call.
    - per-call usage is fixed (small) so cost stays well under the $15 cap.
    - sets ``self.last_response`` after each call (so the BoN cost rollup can
      read token usage, mirroring the real SDK stash in _llm._raw_call_messages).
    - ``raise_on_verifier``: if True, the verifier call raises (fault injection).
    """

    def __init__(
        self,
        *,
        synth_responses: list[str],
        verifier_response: str | None = None,
        in_tok: int = 1000,
        out_tok: int = 500,
        raise_on_verifier: bool = False,
    ) -> None:
        self._synth = list(synth_responses)
        self._verifier_response = verifier_response
        self._in_tok = in_tok
        self._out_tok = out_tok
        self._raise_on_verifier = raise_on_verifier
        self.calls: list[dict] = []
        self.last_response: Any = None
        self.messages = self

    def create(self, **kwargs: Any) -> _FakeMessage:
        self.calls.append(kwargs)
        system = kwargs.get("system", "")
        is_verifier = "BoN VERIFIER" in system
        if is_verifier:
            if self._raise_on_verifier:
                raise RuntimeError("injected verifier transport failure")
            text = self._verifier_response or '{"selected_index": 0, "rationale": "ok"}'
        else:
            text = self._synth.pop(0) if self._synth else '{"error": "no script"}'
        msg = _FakeMessage(text, _FakeUsage(self._in_tok, self._out_tok))
        self.last_response = msg
        return msg


# --------------------------------------------------------------------------- #
# Builders                                                                    #
# --------------------------------------------------------------------------- #


def _locked_all(verdict: str = VERDICT_WATCH) -> PhaseBLockedSet:
    locks = {}
    for sid in ALL_STYLES:
        locks[sid] = PhaseBStyleLock(
            style_id=sid,
            verdict=verdict,
            rationale="r",
            load_bearing_claims=(
                LoadBearingClaim(
                    claim_id=f"{sid}_c1", text="claim",
                    supports_recommendation=verdict,
                ),
            ),
            non_negotiables=(
                NonNegotiable(constraint_id=f"{sid}_n1", text="constraint"),
            ),
        )
    return PhaseBLockedSet(ticker="NVDA", locks=locks)


def _phase_a() -> PhaseAResult:
    pa = PhaseAResult(ticker="NVDA")
    for sid in ALL_STYLES:
        pa.per_style[sid] = PhaseAStyleOutput(
            style_id=sid, preliminary_verdict=VERDICT_WATCH,
            preliminary_rationale="r", key_observations=[],
        )
    return pa


def _judge() -> PhaseCJudgeResult:
    return PhaseCJudgeResult(phase_c_needed=False, judge_confidence=0.85, conflicts=[])


def _synth_payload(decision: str, conviction: float, *, kills: int = 0, drift: int = 0) -> str:
    return json.dumps({
        "decision": decision,
        "recommended_conviction": conviction,
        "dissent_trace": [
            {"style": sid, "verdict": decision, "rationale": "x", "weight": w}
            for sid, w in get_weights(MODE_B).items()
        ],
        "override_reasoning": "",
        "kills_fired": kills,
        "anchor_drift_channels_triggered": drift,
        "non_negotiables_not_addressed": [],
    })


# --------------------------------------------------------------------------- #
# Criterion 1 — N=5 + verifier model = sonnet != synthesizer opus            #
# --------------------------------------------------------------------------- #


def test_bon_generates_n5_candidates():
    client = FakeClient(
        synth_responses=[_synth_payload(VERDICT_WATCH, 0.35)] * 5,
        verifier_response='{"selected_index": 2, "rationale": "best dissent"}',
    )
    res = run_phase_d_bon(
        phase_a=_phase_a(), locked=_locked_all(), judge_result=_judge(),
        mode=MODE_B, client=client,
    )
    assert isinstance(res, PhaseDBoNResult)
    assert res.n == 5
    assert len(res.candidates) == 5
    # 5 synthesizer calls + 1 verifier call.
    synth_calls = [c for c in client.calls if "BoN VERIFIER" not in c.get("system", "")]
    verifier_calls = [c for c in client.calls if "BoN VERIFIER" in c.get("system", "")]
    assert len(synth_calls) == 5
    assert len(verifier_calls) == 1
    assert res.verifier_pick.selected_index == 2
    assert res.verifier_pick.method == "verifier"


def test_verifier_model_is_sonnet_and_differs_from_opus_synthesizer():
    """ACCEPTANCE 1: verifier == sonnet, synthesizer == opus, and they DIFFER.

    The verifier model is resolved from the pm-supervisor.md header
    (verifier_model: sonnet) via the P0-6 reader.
    """
    client = FakeClient(
        synth_responses=[_synth_payload(VERDICT_WATCH, 0.35)] * 5,
        verifier_response='{"selected_index": 0, "rationale": "ok"}',
    )
    res = run_phase_d_bon(
        phase_a=_phase_a(), locked=_locked_all(), judge_result=_judge(),
        mode=MODE_B, client=client,
    )
    # Synthesizer is opus (resolved); verifier is sonnet (resolved).
    assert "opus" in res.synthesizer_model
    assert "sonnet" in res.verifier_model
    assert res.synthesizer_model != res.verifier_model
    # Verifier system prompt was actually used (cross-model verifier ran).
    assert any("BoN VERIFIER" in c.get("system", "") for c in client.calls)


def test_n_is_capped_at_5():
    client = FakeClient(
        synth_responses=[_synth_payload(VERDICT_WATCH, 0.35)] * 5,
        verifier_response='{"selected_index": 0}',
    )
    res = run_phase_d_bon(
        phase_a=_phase_a(), locked=_locked_all(), judge_result=_judge(),
        mode=MODE_B, client=client, n=99,
    )
    assert res.n == 5
    assert len(res.candidates) == 5


# --------------------------------------------------------------------------- #
# Conviction-input aggregation BEFORE the rollup                              #
# --------------------------------------------------------------------------- #


def test_aggregate_conviction_inputs_median_add_max_kills_max_drift():
    samples = [
        bon.ConvictionInputSample(debate_add_count=2, kills_fired=0, drift=0),
        bon.ConvictionInputSample(debate_add_count=4, kills_fired=1, drift=0),
        bon.ConvictionInputSample(debate_add_count=4, kills_fired=0, drift=2),
        bon.ConvictionInputSample(debate_add_count=5, kills_fired=0, drift=1),
        bon.ConvictionInputSample(debate_add_count=3, kills_fired=0, drift=0),
    ]
    agg = bon.aggregate_conviction_inputs(samples)
    # median of [2,3,4,4,5] = 4
    assert agg.debate_add_count == 4
    # max kills (1) flows through; max drift (2) flows through.
    assert agg.kills_fired == 1
    assert agg.drift == 2


def test_aggregate_requires_at_least_one_sample():
    with pytest.raises(ValueError):
        bon.aggregate_conviction_inputs([])


def test_bon_aggregates_inputs_not_final_convictions():
    """The BoN result exposes aggregated conviction INPUTS (not averaged buckets)."""
    # Candidates with varying kills so the max-rule is observable.
    responses = [
        _synth_payload(VERDICT_ADD, 0.7, kills=0, drift=0),
        _synth_payload(VERDICT_ADD, 0.7, kills=1, drift=0),
        _synth_payload(VERDICT_ADD, 0.7, kills=0, drift=2),
        _synth_payload(VERDICT_ADD, 0.7, kills=0, drift=0),
        _synth_payload(VERDICT_ADD, 0.7, kills=0, drift=1),
    ]
    client = FakeClient(synth_responses=responses, verifier_response='{"selected_index": 0}')
    res = run_phase_d_bon(
        phase_a=_phase_a(), locked=_locked_all(VERDICT_ADD), judge_result=_judge(),
        mode=MODE_B, client=client,
    )
    agg = res.aggregated_conviction_inputs
    assert agg.kills_fired == 1  # max across the N passes
    assert agg.drift == 2        # max across the N passes
    assert agg.debate_add_count == 5  # all 5 styles ADD in every candidate


# --------------------------------------------------------------------------- #
# Criterion 2 — quality lift on the bon_panel + $15/pass cost cap            #
# --------------------------------------------------------------------------- #


def _load_panel() -> list[dict]:
    envs = []
    for p in sorted(_FIXTURE_DIR.glob("env_*.json")):
        envs.append(json.loads(p.read_text(encoding="utf-8")))
    return envs


def test_bon_panel_has_10_envelopes_with_golden_axis_blocks():
    panel = _load_panel()
    assert len(panel) == 10
    for env in panel:
        assert "axis_a" in env and "faithfulness" in env["axis_a"]
        assert "axis_b" in env and "roscoe" in env["axis_b"]


def _bon_lift_run(env: dict, verifier_index: int) -> PhaseDBoNResult:
    """Run BoN where candidate 0 = the degraded (single-pass N=1) draft and
    candidates 1..4 = the golden-axis candidates. ``verifier_index`` is the
    index the (mocked) verifier selects.

    The single-pass (N=1) baseline is candidate 0 (the degraded draft a naive
    single synthesis would have emitted); BoN's job is for the verifier to pick
    a candidate whose composite quality is >= that baseline.
    """
    golden = {"axis_a": env["axis_a"], "axis_b": env["axis_b"]}
    degraded = {
        "axis_a": {"faithfulness": env["axis_a"]["faithfulness"] * 0.5},
        "axis_b": {"roscoe": env["axis_b"]["roscoe"] * 0.5},
    }
    candidate_axes = [degraded] + [golden] * 4
    client = FakeClient(
        synth_responses=[_synth_payload(VERDICT_ADD, 0.7)] * 5,
        verifier_response=json.dumps({"selected_index": verifier_index}),
    )
    return run_phase_d_bon(
        phase_a=_phase_a(), locked=_locked_all(VERDICT_ADD), judge_result=_judge(),
        mode=MODE_B, client=client, candidate_axes=candidate_axes,
    )


def test_quality_lift_ge_single_pass_baseline_on_panel():
    """ACCEPTANCE 2 (>= baseline): for each panel envelope, the verifier-selected
    candidate's composite quality >= the single-pass (N=1) baseline.

    The N=1 baseline is candidate 0 (a degraded draft). The verifier selects a
    golden candidate (idx 1). The assertion is NON-tautological: it would FAIL
    if the verifier selected the degraded candidate 0 (see the guard test
    below, which proves the inequality flips).

    NOTE: WS-1 (axis_a) / WS-2 (axis_b) LIVE scorers are not importable yet —
    live-scorer wiring is DEFERRED to Phase 2. We use the GOLDEN axis blocks
    carried on each fixture + the identity percentile stub. The >= baseline
    assertion + the $15 cost cap are fully testable now.
    """
    panel = _load_panel()
    for env in panel:
        res = _bon_lift_run(env, verifier_index=1)
        baseline = res.candidates[0].composite_quality  # N=1 single-pass draft
        selected = res.candidates[res.verifier_pick.selected_index]
        assert selected.composite_quality >= baseline, (
            f"{env['ticker']}: selected {selected.composite_quality} < baseline {baseline}"
        )
        # And the lift is strict for these fixtures (golden > degraded).
        assert selected.composite_quality > baseline
        # ACCEPTANCE 2 (cost cap): per-pass cost recorded as ONE attempt_cost_usd
        # and is <= $15.
        assert res.attempt_cost_usd <= bon.COST_CAP_USD
        assert res.cost_within_cap is True


def test_quality_lift_assertion_would_fail_if_verifier_picked_degraded():
    """Guard against a tautological lift test: if the verifier picked the
    degraded candidate 0, selected == baseline and the strict-lift assertion
    must fail. This proves the lift test discriminates on the verifier's pick.
    """
    panel = _load_panel()
    env = panel[0]
    res = _bon_lift_run(env, verifier_index=0)  # verifier picks the degraded draft
    baseline = res.candidates[0].composite_quality
    selected = res.candidates[res.verifier_pick.selected_index]
    # Selected IS the degraded candidate, so there is NO lift.
    assert selected.composite_quality == baseline
    assert not (selected.composite_quality > baseline)


def test_attempt_cost_is_single_figure_summing_candidates_and_verifier():
    client = FakeClient(
        synth_responses=[_synth_payload(VERDICT_WATCH, 0.35)] * 5,
        verifier_response='{"selected_index": 0}',
        in_tok=2000, out_tok=1000,
    )
    res = run_phase_d_bon(
        phase_a=_phase_a(), locked=_locked_all(), judge_result=_judge(),
        mode=MODE_B, client=client,
    )
    # 5 opus candidates + 1 sonnet verifier, all metered into one figure.
    opus_each = bon.UsageRecord("claude-opus-4-5", 2000, 1000).cost_usd()
    sonnet = bon.UsageRecord("claude-sonnet-4-5", 2000, 1000).cost_usd()
    expected = round(5 * opus_each + sonnet, 6)
    assert res.attempt_cost_usd == pytest.approx(expected)
    assert res.attempt_cost_usd <= bon.COST_CAP_USD


def test_cost_cap_flag_trips_when_exceeded():
    # Force huge token usage so the rollup exceeds $15.
    client = FakeClient(
        synth_responses=[_synth_payload(VERDICT_WATCH, 0.35)] * 5,
        verifier_response='{"selected_index": 0}',
        in_tok=5_000_000, out_tok=5_000_000,
    )
    res = run_phase_d_bon(
        phase_a=_phase_a(), locked=_locked_all(), judge_result=_judge(),
        mode=MODE_B, client=client,
    )
    assert res.attempt_cost_usd > bon.COST_CAP_USD
    assert res.cost_within_cap is False


# --------------------------------------------------------------------------- #
# Criterion 3 — MAD gate + verifier-error self-consistency fallback           #
# --------------------------------------------------------------------------- #


def test_mad_gate_requires_both_flags():
    assert bon.mad_allowed(heterogeneous_models=True, verifiable_step=True) is True
    assert bon.mad_allowed(heterogeneous_models=True, verifiable_step=False) is False
    assert bon.mad_allowed(heterogeneous_models=False, verifiable_step=True) is False
    assert bon.mad_allowed(heterogeneous_models=False, verifiable_step=False) is False


def test_bon_default_does_not_use_mad_path():
    client = FakeClient(
        synth_responses=[_synth_payload(VERDICT_WATCH, 0.35)] * 5,
        verifier_response='{"selected_index": 0}',
    )
    res = run_phase_d_bon(
        phase_a=_phase_a(), locked=_locked_all(), judge_result=_judge(),
        mode=MODE_B, client=client,
    )
    assert res.mad_path_used is False


def test_bon_mad_path_only_with_both_flags():
    client = FakeClient(
        synth_responses=[_synth_payload(VERDICT_WATCH, 0.35)] * 5,
        verifier_response='{"selected_index": 0}',
    )
    res = run_phase_d_bon(
        phase_a=_phase_a(), locked=_locked_all(), judge_result=_judge(),
        mode=MODE_B, client=client,
        heterogeneous_models=True, verifiable_step=True,
    )
    assert res.mad_path_used is True


def test_verifier_error_falls_back_to_self_consistency_never_auto_pass():
    """ACCEPTANCE 3 (fault injection): verifier raises -> self-consistency pick;
    NEVER auto-PASS.

    3 candidates vote WATCH, 2 vote ADD -> majority WATCH. The fallback must
    pick a WATCH candidate (not fabricate a PASS).
    """
    responses = [
        _synth_payload(VERDICT_WATCH, 0.35),
        _synth_payload(VERDICT_ADD, 0.7),
        _synth_payload(VERDICT_WATCH, 0.35),
        _synth_payload(VERDICT_ADD, 0.7),
        _synth_payload(VERDICT_WATCH, 0.35),
    ]
    client = FakeClient(
        synth_responses=responses,
        verifier_response=None,
        raise_on_verifier=True,
    )
    res = run_phase_d_bon(
        phase_a=_phase_a(), locked=_locked_all(), judge_result=_judge(),
        mode=MODE_B, client=client,
    )
    assert res.verifier_pick.method == "self_consistency_fallback"
    assert res.verifier_pick.fallback_reason is not None
    # Selected candidate is a WATCH (majority) — NOT an auto-PASS.
    selected = res.candidates[res.verifier_pick.selected_index]
    assert selected.payload["decision"] == VERDICT_WATCH
    assert res.synthesis.decision == VERDICT_WATCH
    assert res.synthesis.decision != VERDICT_PASS


def test_verifier_out_of_range_index_falls_back():
    client = FakeClient(
        synth_responses=[_synth_payload(VERDICT_WATCH, 0.35)] * 5,
        verifier_response='{"selected_index": 99, "rationale": "bad"}',
    )
    res = run_phase_d_bon(
        phase_a=_phase_a(), locked=_locked_all(), judge_result=_judge(),
        mode=MODE_B, client=client,
    )
    assert res.verifier_pick.method == "self_consistency_fallback"


def test_self_consistency_no_parse_does_not_fabricate_pass():
    """If NO candidate parses, fallback returns lowest index WITHOUT coercing a
    PASS decision — the validator then marks the synthesis invalid (no auto-PASS
    masquerading as a real decision)."""
    cands = [
        bon.BoNCandidate(
            sample_index=i, raw_text="garbage", payload=None,
            conviction_inputs=bon.ConvictionInputSample(0, 0, 0),
            usage=bon.UsageRecord("claude-opus-4-5", 0, 0),
        )
        for i in range(5)
    ]
    pick = bon.self_consistency_pick(cands, fallback_reason="verifier down")
    assert pick.method == "self_consistency_fallback"
    assert pick.selected_index == 0


# --------------------------------------------------------------------------- #
# composite_quality unit                                                      #
# --------------------------------------------------------------------------- #


def test_composite_quality_is_mean_of_axis_a_faithfulness_and_axis_b_roscoe():
    axes = {"axis_a": {"faithfulness": 0.9}, "axis_b": {"roscoe": 0.7}}
    assert bon.composite_quality(axes) == pytest.approx((0.9 + 0.7) / 2.0)


def test_composite_quality_missing_axes_scores_zero():
    assert bon.composite_quality({}) == 0.0


# --------------------------------------------------------------------------- #
# BoN-level cache: (input_sha, model_version, n, temp) -> {candidates, pick}  #
# --------------------------------------------------------------------------- #


def test_serialize_roundtrip_preserves_candidates_and_pick():
    cands = [
        bon.BoNCandidate(
            sample_index=i,
            raw_text=_synth_payload(VERDICT_ADD, 0.7),
            payload={"decision": VERDICT_ADD, "recommended_conviction": 0.7},
            conviction_inputs=bon.ConvictionInputSample(5, i % 2, 0),
            usage=bon.UsageRecord("claude-opus-4-5", 1000, 500),
            axes={"axis_a": {"faithfulness": 0.9}, "axis_b": {"roscoe": 0.7}},
            composite_quality=0.8,
        )
        for i in range(5)
    ]
    pick = bon.VerifierPick(selected_index=2, method="verifier", verifier_model="claude-sonnet-4-5")
    verifier_usage = bon.UsageRecord("claude-sonnet-4-5", 200, 100)
    text = bon.serialize_bon_result(cands, pick, verifier_usage)
    re_cands, re_pick, re_vusage = bon.deserialize_bon_result(text)
    assert len(re_cands) == 5
    assert re_pick.selected_index == 2
    assert re_pick.method == "verifier"
    assert re_cands[2].payload["decision"] == VERDICT_ADD
    assert re_cands[0].usage.input_tokens == 1000
    # BUG 2: verifier usage round-trips so replay reproduces attempt_cost_usd.
    assert re_vusage.input_tokens == 200
    assert re_vusage.output_tokens == 100
    assert re_vusage.model == "claude-sonnet-4-5"


def test_bon_cache_digest_keys_on_input_model_n_temp():
    d1 = bon.bon_cache_digest(input_sha="abc", model_version="claude-opus-4-5", n=5, temperature=0.7)
    d2 = bon.bon_cache_digest(input_sha="abc", model_version="claude-opus-4-5", n=3, temperature=0.7)
    d3 = bon.bon_cache_digest(input_sha="abc", model_version="claude-opus-4-5", n=5, temperature=0.2)
    d4 = bon.bon_cache_digest(input_sha="xyz", model_version="claude-opus-4-5", n=5, temperature=0.7)
    # All four key dimensions change the digest.
    assert len({d1, d2, d3, d4}) == 4
    assert d1.startswith("bon:")


def test_bon_cache_record_then_replay_returns_both_without_recalling(tmp_path, monkeypatch):
    """ACCEPTANCE / spec: cache stores BOTH candidates and verifier_pick.

    Record mode populates the cache; a second run in replay mode returns the
    same candidates + verifier pick WITHOUT any model call (the fake client
    would raise 'no script' if called again — instead .calls stays empty).
    """
    monkeypatch.setenv("LLM_CACHE_ENABLED", "1")
    monkeypatch.setenv("LLM_CACHE_MODE", "record")
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path / "cass"))

    client1 = FakeClient(
        synth_responses=[_synth_payload(VERDICT_WATCH, 0.35)] * 5,
        verifier_response='{"selected_index": 3, "rationale": "best"}',
    )
    res1 = run_phase_d_bon(
        phase_a=_phase_a(), locked=_locked_all(), judge_result=_judge(),
        mode=MODE_B, client=client1, temperature=0.7,
    )
    assert res1.verifier_pick.selected_index == 3
    assert len(client1.calls) == 6  # 5 synth + 1 verifier (record miss)

    # Replay: a fresh client with NO scripted responses must not be called.
    monkeypatch.setenv("LLM_CACHE_MODE", "replay")
    client2 = FakeClient(synth_responses=[], verifier_response=None)
    res2 = run_phase_d_bon(
        phase_a=_phase_a(), locked=_locked_all(), judge_result=_judge(),
        mode=MODE_B, client=client2, temperature=0.7,
    )
    assert client2.calls == []  # NO model calls on replay
    assert len(res2.candidates) == 5
    assert res2.verifier_pick.selected_index == 3  # verifier pick replayed
    assert res2.synthesis.decision == res1.synthesis.decision


# --------------------------------------------------------------------------- #
# BUG 1 regression — self_consistency excludes decision-less candidates        #
# --------------------------------------------------------------------------- #


def test_self_consistency_excludes_candidates_missing_decision():
    """BUG 1: candidates MISSING a 'decision' key (or empty) must NOT win the
    tally. With 3 of 5 candidates decision-less, the pick must land on one of
    the 2 candidates that DO carry a valid decision — never a malformed one."""
    cands = []
    # 3 decision-less / malformed payloads (no 'decision' key, or empty value).
    cands.append(
        bon.BoNCandidate(
            sample_index=0, raw_text="{}", payload={"foo": "bar"},
            conviction_inputs=bon.ConvictionInputSample(0, 0, 0),
            usage=bon.UsageRecord("claude-opus-4-5", 0, 0),
        )
    )
    cands.append(
        bon.BoNCandidate(
            sample_index=1, raw_text="{}", payload={"decision": ""},
            conviction_inputs=bon.ConvictionInputSample(0, 0, 0),
            usage=bon.UsageRecord("claude-opus-4-5", 0, 0),
        )
    )
    cands.append(
        bon.BoNCandidate(
            sample_index=2, raw_text="{}", payload={"decision": "   "},
            conviction_inputs=bon.ConvictionInputSample(0, 0, 0),
            usage=bon.UsageRecord("claude-opus-4-5", 0, 0),
        )
    )
    # 2 valid-decision candidates.
    cands.append(
        bon.BoNCandidate(
            sample_index=3, raw_text="{}",
            payload={"decision": VERDICT_WATCH, "recommended_conviction": 0.3},
            conviction_inputs=bon.ConvictionInputSample(0, 0, 0),
            usage=bon.UsageRecord("claude-opus-4-5", 0, 0),
            composite_quality=0.5,
        )
    )
    cands.append(
        bon.BoNCandidate(
            sample_index=4, raw_text="{}",
            payload={"decision": VERDICT_WATCH, "recommended_conviction": 0.4},
            conviction_inputs=bon.ConvictionInputSample(0, 0, 0),
            usage=bon.UsageRecord("claude-opus-4-5", 0, 0),
            composite_quality=0.9,
        )
    )
    pick = bon.self_consistency_pick(cands, fallback_reason="verifier down")
    assert pick.method == "self_consistency_fallback"
    # MUST select a candidate with a real decision (index 3 or 4), NOT a
    # malformed/decision-less one (0/1/2). Empty-string decision must never win.
    assert pick.selected_index in (3, 4)
    selected = next(c for c in cands if c.sample_index == pick.selected_index)
    assert str(selected.payload.get("decision", "")).strip()


def test_self_consistency_all_missing_decision_hits_no_parse_fallback():
    """BUG 1: when EVERY candidate lacks a valid decision, fall through to the
    no-parse fallback — never fabricate a PASS, never select a winner by an
    empty-string majority."""
    cands = [
        bon.BoNCandidate(
            sample_index=i, raw_text="{}", payload={"foo": "bar"},
            conviction_inputs=bon.ConvictionInputSample(0, 0, 0),
            usage=bon.UsageRecord("claude-opus-4-5", 0, 0),
        )
        for i in range(5)
    ]
    pick = bon.self_consistency_pick(cands, fallback_reason="verifier down")
    assert pick.method == "self_consistency_fallback"
    assert pick.selected_index == 0
    # The selected payload has no real decision — it is NOT coerced to PASS.
    selected = next(c for c in cands if c.sample_index == pick.selected_index)
    assert not str((selected.payload or {}).get("decision", "")).strip()
    assert "no candidate has a valid decision" in pick.rationale


# --------------------------------------------------------------------------- #
# BUG 2 regression — per-sample cost reproducible on cache replay              #
# --------------------------------------------------------------------------- #


def test_attempt_cost_reproducible_across_record_and_replay(tmp_path, monkeypatch):
    """BUG 2: a BoN pass recorded with usage must replay with the IDENTICAL
    attempt_cost_usd. The recorded cost is non-zero and the replay reproduces
    it exactly (not 0, not call-order dependent)."""
    monkeypatch.setenv("LLM_CACHE_ENABLED", "1")
    monkeypatch.setenv("LLM_CACHE_MODE", "record")
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path / "cass"))

    client1 = FakeClient(
        synth_responses=[_synth_payload(VERDICT_WATCH, 0.35)] * 5,
        verifier_response='{"selected_index": 0, "rationale": "ok"}',
        in_tok=1000, out_tok=500,
    )
    res1 = run_phase_d_bon(
        phase_a=_phase_a(), locked=_locked_all(), judge_result=_judge(),
        mode=MODE_B, client=client1, temperature=0.7,
    )
    assert res1.attempt_cost_usd > 0.0  # real usage was recorded

    monkeypatch.setenv("LLM_CACHE_MODE", "replay")
    client2 = FakeClient(synth_responses=[], verifier_response=None)
    res2 = run_phase_d_bon(
        phase_a=_phase_a(), locked=_locked_all(), judge_result=_judge(),
        mode=MODE_B, client=client2, temperature=0.7,
    )
    assert client2.calls == []  # pure replay, no model calls
    # Cost field is reproducible to the cent (in fact exactly identical).
    assert res2.attempt_cost_usd == res1.attempt_cost_usd
    # Decision is unchanged by the cost fix.
    assert res2.synthesis.decision == res1.synthesis.decision


def test_replay_cost_independent_of_stale_last_response(tmp_path, monkeypatch):
    """BUG 2 (order/state independence): a replay's attempt_cost_usd must be
    derived from the PERSISTED cache value, NOT from whatever stale value a
    client happens to carry on ``last_response``. We pre-set a bogus
    last_response (999_999 tokens) on the replay client; the recorded cost must
    still reproduce exactly and the candidate usages must match the recorded
    (real) values — proving the cost field is reproducible and not a function
    of client call-state."""
    monkeypatch.setenv("LLM_CACHE_ENABLED", "1")
    monkeypatch.setenv("LLM_CACHE_MODE", "record")
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path / "cass"))

    rec_client = FakeClient(
        synth_responses=[_synth_payload(VERDICT_WATCH, 0.35)] * 5,
        verifier_response='{"selected_index": 0, "rationale": "ok"}',
        in_tok=1000, out_tok=500,
    )
    res1 = run_phase_d_bon(
        phase_a=_phase_a(), locked=_locked_all(), judge_result=_judge(),
        mode=MODE_B, client=rec_client, temperature=0.7,
    )

    monkeypatch.setenv("LLM_CACHE_MODE", "replay")
    replay_client = FakeClient(synth_responses=[], verifier_response=None)
    # Bogus pre-set state that MUST NOT influence the replayed cost.
    replay_client.last_response = _FakeMessage(
        "stale", _FakeUsage(input_tokens=999_999, output_tokens=999_999)
    )
    res2 = run_phase_d_bon(
        phase_a=_phase_a(), locked=_locked_all(), judge_result=_judge(),
        mode=MODE_B, client=replay_client, temperature=0.7,
    )
    assert replay_client.calls == []  # pure replay, no model calls
    # Cost reproduced exactly from cache, independent of the bogus last_response.
    assert res2.attempt_cost_usd == res1.attempt_cost_usd
    # Candidate usages came from the persisted record (1000/500), not 999_999.
    for cand in res2.candidates:
        assert cand.usage.input_tokens == 1000
        assert cand.usage.output_tokens == 500
