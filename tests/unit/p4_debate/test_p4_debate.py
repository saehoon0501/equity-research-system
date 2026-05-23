"""Smoke tests for ``src/p4_debate/`` — 5-style debate orchestrator.

Tests cover each phase with a fake LLM client — no network, no DB I/O.
Layered to mirror the package structure:

* Style personas — locked identity + non-empty system prompts.
* Phase A — isolated parallel runs; macro_regime emits regime sensitivity.
* Phase B — locked claim parsing; immutability via dataclass(frozen=True).
* Phase C judge — Type 1/2/3 conflict parsing; phase_c_needed gate.
* Phase C negotiation — round-bounding + early termination on convergence.
* Phase D PMSupervisor — dissent backfill, override-reasoning enforcement.
* Mode-style weighting matrix — sums to 1.0 per mode; sector overrides.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

# Mirror the sys.path trick used by tests/test_mode_classifier.py.
_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from p4_debate import (  # noqa: E402
    ALL_STYLES,
    ALL_VERDICTS,
    CONFLICT_TYPE_1,
    CONFLICT_TYPE_2,
    CONFLICT_TYPE_3,
    MODE_B,
    MODE_B_PRIME,
    MODE_C,
    SECTOR_OVERRIDES,
    STYLE_GROWTH,
    STYLE_MACRO_REGIME,
    STYLE_QUALITY_MOAT,
    STYLE_QUANT_TECHNICAL,
    STYLE_VALUE,
    VERDICT_ADD,
    VERDICT_PASS,
    VERDICT_WATCH,
    WEIGHT_MATRIX,
    get_weights,
)
from p4_debate.phase_a_isolated import (  # noqa: E402
    PhaseAResult,
    PhaseAStyleOutput,
    run_phase_a,
)
from p4_debate.phase_b_locked import (  # noqa: E402
    LoadBearingClaim,
    NonNegotiable,
    PhaseBLockedSet,
    PhaseBStyleLock,
    _parse_payload_to_lock,
    run_phase_b,
)
from p4_debate.phase_c_judge import (  # noqa: E402
    JudgedConflict,
    PhaseCJudgeResult,
    _parse_judge_payload,
    run_phase_c_judge,
)
from p4_debate.phase_c_negotiation import (  # noqa: E402
    PhaseCNegotiationResult,
    StyleRefinement,
    run_phase_c_negotiation,
)
from p4_debate.phase_d_pm_supervisor import (  # noqa: E402
    DissentEntry,
    PhaseDSynthesis,
    _validate_phase_d_payload,
    compute_weighted_vote,
    run_phase_d,
)
from p4_debate.styles import PERSONAS  # noqa: E402


# --------------------------------------------------------------------------- #
# Fake LLM client — pluggable per-call response.                              #
# --------------------------------------------------------------------------- #


class _FakeMessage:
    def __init__(self, text: str) -> None:
        self.content = [type("B", (), {"text": text})()]


class FakeAnthropic:
    """Test double matching the surface of ``anthropic.Anthropic``."""

    def __init__(self, scripted: list[str] | dict[str, str] | None = None) -> None:
        self._queue: list[str] = list(scripted) if isinstance(scripted, list) else []
        self._by_keyword: dict[str, str] = (
            dict(scripted) if isinstance(scripted, dict) else {}
        )
        self.calls: list[dict] = []
        self.messages = self  # so `client.messages.create(...)` works

    def create(self, **kwargs: Any) -> _FakeMessage:
        self.calls.append(kwargs)
        # Keyword-match takes priority over queue.
        user_content = ""
        for m in kwargs.get("messages", []):
            if m.get("role") == "user":
                user_content = m.get("content", "")
                break
        for kw, resp in self._by_keyword.items():
            if kw in user_content:
                return _FakeMessage(resp)
        if self._queue:
            return _FakeMessage(self._queue.pop(0))
        return _FakeMessage('{"error": "no scripted response"}')


# --------------------------------------------------------------------------- #
# Style personas                                                              #
# --------------------------------------------------------------------------- #


def test_personas_registry_has_5_styles():
    assert set(PERSONAS.keys()) == set(ALL_STYLES)


def test_each_persona_has_locked_identity():
    for sid, persona in PERSONAS.items():
        assert persona.style_id == sid
        assert persona.archetypes  # non-empty
        assert persona.core_question
        assert persona.prioritizes
        assert persona.rejects
        # The system prompt must include locked-identity language to
        # implement the L8 finding-13 mitigation (persistent identity
        # prevents inter-agent sycophancy).
        assert "LOCKED IDENTITY" in persona.system_prompt
        assert "DO NOT BREAK CHARACTER" in persona.system_prompt


def test_macro_regime_consumes_s0():
    persona = PERSONAS[STYLE_MACRO_REGIME]
    assert "S0" in persona.system_prompt
    assert "BOCPD" in persona.system_prompt
    assert "regime-sensitivity" in persona.system_prompt or "regime sensitivity" in persona.system_prompt


def test_value_includes_distressed_variant():
    persona = PERSONAS[STYLE_VALUE]
    assert "cash-as-option" in persona.system_prompt.lower()
    assert "Klarman" in persona.archetypes or "Marks" in persona.archetypes


# --------------------------------------------------------------------------- #
# Mode-style weighting matrix                                                 #
# --------------------------------------------------------------------------- #


def test_weight_matrix_sums_to_one_per_mode():
    for mode, weights in WEIGHT_MATRIX.items():
        s = sum(weights.values())
        assert abs(s - 1.0) < 1e-9, f"mode {mode} sums to {s}"


def test_get_weights_basic_modes():
    for mode in (MODE_B, MODE_B_PRIME, MODE_C):
        w = get_weights(mode)
        assert set(w.keys()) == set(ALL_STYLES)
        assert abs(sum(w.values()) - 1.0) < 1e-9


def test_get_weights_sector_override_biotech_c():
    w = get_weights(MODE_C, sector="Biotech")
    assert w[STYLE_GROWTH] == 0.50
    assert w[STYLE_MACRO_REGIME] == 0.25
    assert abs(sum(w.values()) - 1.0) < 1e-9


def test_get_weights_sector_override_banks_b():
    w = get_weights(MODE_B, sector="Banks")
    assert w[STYLE_VALUE] == 0.35
    assert w[STYLE_MACRO_REGIME] == 0.30


def test_get_weights_unknown_sector_falls_back_to_default_matrix():
    w_default = get_weights(MODE_B_PRIME)
    w_unknown = get_weights(MODE_B_PRIME, sector="Cryptocurrency")
    assert w_default == w_unknown


def test_get_weights_invalid_mode_raises():
    with pytest.raises(ValueError):
        get_weights("X")


# --------------------------------------------------------------------------- #
# Phase A — isolated                                                          #
# --------------------------------------------------------------------------- #


def _phase_a_response(verdict: str, with_regime: bool = False) -> str:
    payload = {
        "preliminary_verdict": verdict,
        "preliminary_rationale": "test rationale",
        "key_observations": ["obs 1", "obs 2"],
    }
    if with_regime:
        payload["regime_sensitivity"] = "MEDIUM"
    return json.dumps(payload)


def test_phase_a_runs_all_5_styles_isolated_sequential():
    fake = FakeAnthropic(
        scripted=[_phase_a_response(VERDICT_WATCH) for _ in range(5)]
    )
    # Override the macro_regime scripted slot with a regime-tagged payload.
    fake._by_keyword["S0 REGIME CONTEXT (you are the Macro-Regime"] = (
        _phase_a_response(VERDICT_PASS, with_regime=True)
    )
    result = run_phase_a(
        ticker="NVDA",
        candidate_facts="NVDA fact block",
        s0_regime_context="regime block",
        client=fake,
        parallel=False,
    )
    assert isinstance(result, PhaseAResult)
    assert set(result.per_style.keys()) == set(ALL_STYLES)
    macro = result.per_style[STYLE_MACRO_REGIME]
    assert macro.regime_sensitivity in {"HIGH", "MEDIUM", "LOW"}
    for sid, out in result.per_style.items():
        if sid != STYLE_MACRO_REGIME:
            assert out.regime_sensitivity is None


def test_phase_a_handles_malformed_json_gracefully():
    fake = FakeAnthropic(scripted=["not json"] * 5)
    result = run_phase_a(
        ticker="X", candidate_facts="x", client=fake, parallel=False,
    )
    for out in result.per_style.values():
        assert out.preliminary_verdict == VERDICT_PASS
        assert not out.valid


# --------------------------------------------------------------------------- #
# Phase B — locked                                                            #
# --------------------------------------------------------------------------- #


def _good_phase_b_payload(verdict: str = VERDICT_ADD) -> dict:
    return {
        "verdict": verdict,
        "rationale": "test rationale",
        "load_bearing_claims": [
            {"id": "lbc1", "text": "claim 1", "supports_recommendation": verdict},
            {"id": "lbc2", "text": "claim 2", "supports_recommendation": verdict},
            {"id": "lbc3", "text": "claim 3", "supports_recommendation": verdict},
        ],
        "non_negotiables": [
            {"id": "nn1", "text": "constraint 1"},
            {"id": "nn2", "text": "constraint 2"},
        ],
    }


def test_phase_b_lock_is_frozen():
    lock = _parse_payload_to_lock(
        style_id="value", parsed=_good_phase_b_payload(), model="m",
    )
    assert lock.valid
    assert lock.verdict == VERDICT_ADD
    # frozen=True: assignment must fail.
    with pytest.raises(Exception):  # noqa: PT011
        lock.verdict = VERDICT_PASS  # type: ignore[misc]
    with pytest.raises(Exception):  # noqa: PT011
        lock.load_bearing_claims = ()  # type: ignore[misc]


def test_phase_b_rejects_too_few_claims():
    payload = _good_phase_b_payload()
    payload["load_bearing_claims"] = payload["load_bearing_claims"][:1]
    lock = _parse_payload_to_lock(style_id="value", parsed=payload, model="m")
    assert not lock.valid
    assert "claim count" in (lock.invalid_reason or "")


def test_phase_b_rejects_too_few_nons():
    payload = _good_phase_b_payload()
    payload["non_negotiables"] = []
    lock = _parse_payload_to_lock(style_id="value", parsed=payload, model="m")
    assert not lock.valid


def test_phase_b_runs_for_all_styles_sequential():
    phase_a = PhaseAResult(ticker="NVDA")
    for sid in ALL_STYLES:
        phase_a.per_style[sid] = PhaseAStyleOutput(
            style_id=sid,
            preliminary_verdict=VERDICT_WATCH,
            preliminary_rationale="r",
            key_observations=["o1"],
        )
    payload_text = json.dumps(_good_phase_b_payload())
    fake = FakeAnthropic(scripted=[payload_text] * 5)
    locked = run_phase_b(
        phase_a=phase_a,
        candidate_facts="facts",
        client=fake,
        parallel=False,
    )
    assert isinstance(locked, PhaseBLockedSet)
    assert set(locked.locks.keys()) == set(ALL_STYLES)
    for lk in locked.locks.values():
        assert lk.valid
        assert len(lk.load_bearing_claims) == 3
        assert len(lk.non_negotiables) == 2


# --------------------------------------------------------------------------- #
# Phase C judge                                                               #
# --------------------------------------------------------------------------- #


def _build_minimal_locked_set() -> PhaseBLockedSet:
    locks = {}
    for sid in ALL_STYLES:
        locks[sid] = PhaseBStyleLock(
            style_id=sid,
            verdict=VERDICT_WATCH,
            rationale="r",
            load_bearing_claims=(
                LoadBearingClaim(
                    claim_id=f"{sid}_c1",
                    text="claim",
                    supports_recommendation=VERDICT_WATCH,
                ),
            ) * 1,
            non_negotiables=(
                NonNegotiable(constraint_id=f"{sid}_n1", text="constraint"),
            ),
        )
    return PhaseBLockedSet(ticker="NVDA", locks=locks)


def test_phase_c_judge_parses_type_1():
    payload = {
        "phase_c_needed": True,
        "judge_confidence": 0.9,
        "conflicts": [
            {
                "conflict_id": "c1",
                "type": CONFLICT_TYPE_1,
                "style_a": STYLE_VALUE,
                "style_a_claim_id": "v_lbc_1",
                "style_b": STYLE_GROWTH,
                "style_b_claim_id": "g_lbc_1",
                "rationale": "directly contradicts",
            }
        ],
    }
    res = _parse_judge_payload(payload)
    assert res.valid
    assert res.phase_c_needed is True
    assert res.judge_confidence == 0.9
    assert len(res.conflicts) == 1
    assert res.conflicts[0].conflict_type == CONFLICT_TYPE_1


def test_phase_c_judge_rejects_unknown_conflict_type():
    payload = {
        "phase_c_needed": True,
        "judge_confidence": 0.5,
        "conflicts": [
            {
                "conflict_id": "c1",
                "type": "type_99_made_up",
                "style_a": STYLE_VALUE,
                "style_a_claim_id": "x",
                "style_b": STYLE_GROWTH,
                "style_b_claim_id": "y",
                "rationale": "x",
            }
        ],
    }
    res = _parse_judge_payload(payload)
    # Unknown types are dropped; with no surviving conflicts we must
    # collapse phase_c_needed to False (cannot escalate without a conflict).
    assert res.valid
    assert res.phase_c_needed is False
    assert res.conflicts == []


def test_phase_c_judge_validates_confidence_range():
    payload = {"phase_c_needed": False, "judge_confidence": 1.5, "conflicts": []}
    res = _parse_judge_payload(payload)
    assert not res.valid


def test_phase_c_judge_runs_with_fake_client():
    locked = _build_minimal_locked_set()
    judge_payload = {
        "phase_c_needed": False,
        "judge_confidence": 0.85,
        "conflicts": [],
    }
    fake = FakeAnthropic(scripted=[json.dumps(judge_payload)])
    res = run_phase_c_judge(locked=locked, client=fake)
    assert res.phase_c_needed is False
    assert res.judge_confidence == 0.85


# --------------------------------------------------------------------------- #
# Phase C negotiation                                                         #
# --------------------------------------------------------------------------- #


def test_phase_c_negotiation_skips_when_judge_says_not_needed():
    locked = _build_minimal_locked_set()
    judge_result = PhaseCJudgeResult(
        phase_c_needed=False, judge_confidence=0.9, conflicts=[],
    )
    fake = FakeAnthropic(scripted=[])  # should not be called
    res = run_phase_c_negotiation(
        locked=locked,
        judge_result=judge_result,
        client=fake,
        parallel=False,
    )
    assert res.rounds == []
    assert res.unresolved_conflicts == []
    assert res.resolved_conflicts == []
    # No LLM calls made.
    assert fake.calls == []


def test_phase_c_negotiation_terminates_when_both_sides_concede():
    locked = _build_minimal_locked_set()
    judge_result = PhaseCJudgeResult(
        phase_c_needed=True,
        judge_confidence=0.9,
        conflicts=[
            JudgedConflict(
                conflict_id="c1",
                conflict_type=CONFLICT_TYPE_1,
                style_a=STYLE_VALUE,
                style_a_claim_id="value_c1",
                style_b=STYLE_GROWTH,
                style_b_claim_id="growth_c1",
                rationale="direct contradiction",
            )
        ],
    )
    # Both sides concede the conflict in round 1 -> early termination.
    refine_text = json.dumps({
        "refined_position": "I refine my view",
        "still_disagrees_with": [],
        "willing_to_concede": ["c1"],
    })
    fake = FakeAnthropic(scripted=[refine_text, refine_text])
    res = run_phase_c_negotiation(
        locked=locked,
        judge_result=judge_result,
        client=fake,
        parallel=False,
    )
    assert len(res.rounds) == 1
    assert res.resolved_conflicts == ["c1"]
    assert res.unresolved_conflicts == []


def test_phase_c_negotiation_respects_3_round_bound():
    locked = _build_minimal_locked_set()
    judge_result = PhaseCJudgeResult(
        phase_c_needed=True,
        judge_confidence=0.7,
        conflicts=[
            JudgedConflict(
                conflict_id="c1",
                conflict_type=CONFLICT_TYPE_1,
                style_a=STYLE_VALUE,
                style_a_claim_id="value_c1",
                style_b=STYLE_GROWTH,
                style_b_claim_id="growth_c1",
                rationale="contradicts",
            )
        ],
    )
    # No one concedes -> runs 3 rounds.
    refine_text = json.dumps({
        "refined_position": "I hold my view",
        "still_disagrees_with": [STYLE_GROWTH, STYLE_VALUE],
        "willing_to_concede": [],
    })
    fake = FakeAnthropic(scripted=[refine_text] * 6)  # 3 rounds × 2 styles
    res = run_phase_c_negotiation(
        locked=locked,
        judge_result=judge_result,
        client=fake,
        parallel=False,
    )
    assert len(res.rounds) == 3
    assert res.unresolved_conflicts == ["c1"]


# --------------------------------------------------------------------------- #
# Phase D — PMSupervisor synthesis                                            #
# --------------------------------------------------------------------------- #


def test_compute_weighted_vote():
    locked = _build_minimal_locked_set()
    weights = get_weights(MODE_B)
    tally = compute_weighted_vote(locked, weights)
    # All 5 styles WATCH in the minimal set.
    assert abs(tally[VERDICT_WATCH] - 1.0) < 1e-9


def test_phase_d_validator_backfills_missing_dissent():
    """Critical invariant: if PMSupervisor omits a style, validator backfills."""
    locked = _build_minimal_locked_set()
    weights = get_weights(MODE_B_PRIME)
    parsed = {
        "decision": VERDICT_ADD,
        "recommended_conviction": 0.7,
        # ONLY 2 styles in the trace — validator must backfill the other 3.
        "dissent_trace": [
            {"style": STYLE_VALUE, "verdict": VERDICT_PASS,
             "rationale": "price too high", "weight": 0.15},
            {"style": STYLE_GROWTH, "verdict": VERDICT_ADD,
             "rationale": "TAM huge", "weight": 0.35},
        ],
        "override_reasoning": "Growth conviction outweighs Value's price concern",
        "non_negotiables_not_addressed": [],
    }
    synth = _validate_phase_d_payload(
        parsed=parsed,
        ticker="NVDA",
        locked=locked,
        mode=MODE_B_PRIME,
        sector=None,
        weights=weights,
        raw_text="<raw>",
    )
    assert synth.valid
    # All 5 styles must appear post-validation.
    assert {d.style_id for d in synth.dissent_trace} == set(ALL_STYLES)


def test_phase_d_enforces_override_reasoning_when_dissent_differs():
    """If decision != all dissenters' verdicts and override_reasoning empty,
    validator must insert a flag string."""
    locked = _build_minimal_locked_set()  # all WATCH
    weights = get_weights(MODE_B)
    parsed = {
        "decision": VERDICT_ADD,
        "recommended_conviction": 0.6,
        "dissent_trace": [],  # validator backfills 5 WATCH entries
        "override_reasoning": "",
        "non_negotiables_not_addressed": [],
    }
    synth = _validate_phase_d_payload(
        parsed=parsed,
        ticker="NVDA",
        locked=locked,
        mode=MODE_B,
        sector=None,
        weights=weights,
        raw_text="<raw>",
    )
    # All backfilled styles vote WATCH != ADD decision -> requires override_reasoning.
    assert synth.override_reasoning  # non-empty (validator inserted a flag)
    assert "flagged for operator review" in synth.override_reasoning.lower() or \
           "flagged for operator" in synth.override_reasoning.lower()


def test_phase_d_run_end_to_end_with_fake_client():
    locked = _build_minimal_locked_set()
    judge_result = PhaseCJudgeResult(
        phase_c_needed=False, judge_confidence=0.85, conflicts=[],
    )
    response = json.dumps({
        "decision": VERDICT_WATCH,
        "recommended_conviction": 0.35,
        "dissent_trace": [
            {"style": sid, "verdict": VERDICT_WATCH,
             "rationale": "consistent", "weight": w}
            for sid, w in get_weights(MODE_B).items()
        ],
        "override_reasoning": "",
        "non_negotiables_not_addressed": [],
    })
    fake = FakeAnthropic(scripted=[response])
    phase_a = PhaseAResult(ticker="NVDA")
    for sid in ALL_STYLES:
        phase_a.per_style[sid] = PhaseAStyleOutput(
            style_id=sid,
            preliminary_verdict=VERDICT_WATCH,
            preliminary_rationale="r",
            key_observations=[],
        )
    synth = run_phase_d(
        phase_a=phase_a,
        locked=locked,
        judge_result=judge_result,
        negotiation=None,
        mode=MODE_B,
        client=fake,
    )
    assert synth.decision == VERDICT_WATCH
    assert {d.style_id for d in synth.dissent_trace} == set(ALL_STYLES)


# --------------------------------------------------------------------------- #
# Constants sanity                                                            #
# --------------------------------------------------------------------------- #


def test_all_verdicts_canonical_set():
    assert set(ALL_VERDICTS) == {VERDICT_ADD, VERDICT_WATCH, VERDICT_PASS}


def test_sector_overrides_keys():
    # Spec Section 2.3 line 185: "Banks/insurers-B" is a SINGLE class.
    # Banks / Insurers / Financials all normalize to the same override.
    assert ("Biotech", MODE_C) in SECTOR_OVERRIDES
    assert ("Banks/insurers", MODE_B) in SECTOR_OVERRIDES
    assert ("Banks", MODE_B) not in SECTOR_OVERRIDES
    assert ("Insurers", MODE_B) not in SECTOR_OVERRIDES
    for (sector, mode), w in SECTOR_OVERRIDES.items():
        s = sum(w.values())
        assert abs(s - 1.0) < 1e-9, f"sector {sector}/{mode} sums to {s}"


def test_sector_normalizer_maps_banks_and_insurers_to_canonical():
    # "Banks", "Insurers", "Financials" → same override.
    from src.p4_debate import get_weights

    canonical = get_weights(MODE_B, sector="Banks/insurers")
    for alias in ("Banks", "Insurers", "Financials", "banks", "INSURERS"):
        assert get_weights(MODE_B, sector=alias) == canonical, (
            f"alias {alias!r} should resolve to Banks/insurers override"
        )

    # Biotech still routes correctly (no normalization needed).
    assert get_weights(MODE_C, sector="Biotech") == dict(
        SECTOR_OVERRIDES[("Biotech", MODE_C)]
    )

    # Unknown sector falls back to base mode weights.
    from src.p4_debate import WEIGHT_MATRIX

    assert get_weights(MODE_B, sector="Tech") == dict(WEIGHT_MATRIX[MODE_B])
