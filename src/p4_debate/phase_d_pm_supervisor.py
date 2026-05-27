"""Phase D — PMSupervisor synthesis with explicit dissent preservation.

Per v3 spec Section 2.3 row "D PMSupervisor synthesis" (line 169) and
Section 2.4 finding 1:

    PMSupervisor MUST NOT force consensus — sycophancy is dominant MAD
    failure mode (ICML 2025). Phase D output explicitly preserves
    dissenting views per agent.

This is the SINGLE most-important architectural invariant in the entire
debate package. The PMSupervisor:

1. Reads ALL phases (A preliminary + B locked + C negotiation if any).
2. Applies the mode-style weighting matrix (Section 2.3) — including
   sector overrides for Biotech-C and Banks/insurers-B.
3. Produces a SINGLE decision (ADD / WATCH / PASS) with an EXPLICIT
   dissent trace listing every style's locked verdict + rationale.
4. EMITS override-reasoning when the synthesized decision overrides
   any dissenter (so the audit-trail can surface "why was Value's PASS
   overridden in favor of ADD?").
5. PRESERVES non-negotiables that the synthesis decision did not
   address (so subsequent kill-criteria evaluation has the inputs).

Output schema (matches Section 2.3 line 169 example)::

    {
      decision: "ADD" | "WATCH" | "PASS",
      recommended_conviction: float ∈ [0, 1],
      dissent_trace: [
        {style: <id>, verdict: <verdict>, rationale: <text>, weight: float},
        ...
      ],
      override_reasoning: <text>,
      non_negotiables_not_addressed: [
        {style: <id>, constraint_id: <id>, text: <text>}
      ]
    }
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from . import (
    ALL_VERDICTS,
    MODEL_OPUS,
    MODEL_SONNET,
    PROMPT_VERSION_PHASE_D,
    VERDICT_ADD,
    VERDICT_PASS,
    VERDICT_WATCH,
    get_weights,
)
from ._bon_mav import (
    BON_N,
    BON_N_CAP,
    COST_CAP_USD,
    SELF_CONSISTENCY_TEMPERATURE,
    AggregatedConvictionInputs,
    BoNCandidate,
    ConvictionInputSample,
    UsageRecord,
    VerifierPick,
    aggregate_conviction_inputs,
    attempt_cost_usd,
    bon_cache_digest,
    bon_input_sha,
    composite_quality,
    deserialize_bon_result,
    extract_usage,
    mad_allowed,
    self_consistency_pick,
    serialize_bon_result,
)
from ._llm import build_default_client, call_messages, extract_json
from .phase_a_isolated import PhaseAResult
from .phase_b_locked import PhaseBLockedSet
from .phase_c_judge import PhaseCJudgeResult
from .phase_c_negotiation import PhaseCNegotiationResult

_LOG = logging.getLogger(__name__)


@dataclass
class DissentEntry:
    """One style's preserved verdict + rationale + weight in the decision."""

    style_id: str
    verdict: str
    rationale: str
    weight: float

    def to_payload(self) -> dict:
        return {
            "style": self.style_id,
            "verdict": self.verdict,
            "rationale": self.rationale,
            "weight": self.weight,
        }


@dataclass
class UnaddressedNonNegotiable:
    """A non-negotiable from a dissenting style that the synthesis did
    not satisfy.

    This is NOT necessarily a veto — but it MUST be surfaced to the
    operator + the kill-criteria stage. Per Section 2.4 #1, the
    PMSupervisor cannot "wash out" these constraints.
    """

    style_id: str
    constraint_id: str
    text: str

    def to_payload(self) -> dict:
        return {
            "style": self.style_id,
            "constraint_id": self.constraint_id,
            "text": self.text,
        }


@dataclass
class PhaseDSynthesis:
    """Full Phase D output."""

    ticker: str
    decision: str  # ADD / WATCH / PASS
    recommended_conviction: float
    dissent_trace: list[DissentEntry] = field(default_factory=list)
    override_reasoning: str = ""
    non_negotiables_not_addressed: list[UnaddressedNonNegotiable] = field(
        default_factory=list
    )
    mode: str = ""
    sector: Optional[str] = None
    weights_used: dict[str, float] = field(default_factory=dict)
    raw_text: str = ""
    valid: bool = True
    invalid_reason: Optional[str] = None
    prompt_version: str = PROMPT_VERSION_PHASE_D
    model: str = MODEL_OPUS

    def to_payload(self) -> dict:
        return {
            "decision": self.decision,
            "recommended_conviction": self.recommended_conviction,
            "dissent_trace": [d.to_payload() for d in self.dissent_trace],
            "override_reasoning": self.override_reasoning,
            "non_negotiables_not_addressed": [
                n.to_payload() for n in self.non_negotiables_not_addressed
            ],
            "mode": self.mode,
            "sector": self.sector,
            "weights_used": dict(self.weights_used),
            "valid": self.valid,
            "invalid_reason": self.invalid_reason,
            "prompt_version": self.prompt_version,
            "model": self.model,
        }


# --------------------------------------------------------------------------- #
# PMSupervisor system prompt                                                  #
# --------------------------------------------------------------------------- #


_SYSTEM_PROMPT = """\
You are the PMSupervisor — the synthesizer for a 5-style equity-research
debate (Value, Growth, Quality/Moat, Macro/Regime, Quant/Technical).

CRITICAL — READ TWICE BEFORE OUTPUT:

  YOU MUST NOT FORCE CONSENSUS.

  Inter-agent sycophancy is the dominant failure mode of multi-agent
  debate (ICML 2025 — Talk Isn't Always Cheap; Peacemaker or
  Troublemaker). A correct minority view CAN BE LOST when a synthesizer
  rounds off dissent in the name of "alignment". You are forbidden
  from doing this.

YOUR JOB:

  1. Read all 5 styles' Phase B locked verdicts + claims. Read Phase C
     negotiation outputs if present. THESE LOCKED VERDICTS ARE INPUTS;
     you do not rewrite them.
  2. Produce a SINGLE decision (ADD / WATCH / PASS) using the supplied
     mode-weighted vote (already computed for you below).
  3. EXPLICITLY preserve every style's verdict + rationale in the
     dissent_trace — even (especially) when a style disagrees with your
     decision.
  4. When your decision overrides any dissenter, write override_reasoning
     explaining WHY the weighting + evidence justified the override.
     "It's the weighted vote" is NOT sufficient — you must address the
     dissenter's load-bearing claim.
  5. Surface every UNADDRESSED non-negotiable from dissenting styles.
     These are not blockers, but they MUST flow downstream to the
     kill-criteria stage.

SIZING / CONVICTION:

  recommended_conviction ∈ [0, 1]:
    - 5/5 styles agree on ADD: 0.85-1.00 (rare; usually too good to be true)
    - 4/5 agree on ADD: 0.65-0.85 (typical strong-conviction ADD)
    - 3/5 agree on ADD with strong weighted majority: 0.50-0.65
    - Mixed / weighted-decision-overriding-dissent: 0.30-0.50
    - WATCH: 0.20-0.40
    - PASS: 0.0-0.20

OUTPUT DISCIPLINE:

  Return ONLY this JSON object — no markdown, no commentary:

  {
    "decision": "ADD" | "WATCH" | "PASS",
    "recommended_conviction": 0.0-1.0,
    "dissent_trace": [
      {"style": "<id>", "verdict": "ADD|WATCH|PASS",
       "rationale": "<= 2 sentences", "weight": 0.0-1.0},
      ... ALL 5 STYLES MUST APPEAR — no omissions ...
    ],
    "override_reasoning": "<= 4 sentences; required when any style's "
                         "verdict differs from your decision; otherwise "
                         "may be empty string>",
    "non_negotiables_not_addressed": [
      {"style": "<id>", "constraint_id": "<id>", "text": "<text>"},
      ...
    ]
  }
"""


_USER_TEMPLATE = """\
TICKER: {ticker}
MODE: {mode}
SECTOR: {sector}

MODE-STYLE WEIGHTS (Section 2.3 matrix; sector override if applicable):
{weights_block}

WEIGHTED VOTE (computed mechanically from Phase B verdicts):
{weighted_vote_block}

PHASE B LOCKED CLAIMS PER STYLE (IMMUTABLE):

{phase_b_block}

PHASE C JUDGE OUTCOME:
  phase_c_needed: {phase_c_needed}
  judge_confidence: {judge_confidence}
  conflict_count: {conflict_count}
{phase_c_negotiation_block}

NON-NEGOTIABLES SUMMARY (from all 5 styles' Phase B):
{nons_block}

PRODUCE YOUR JSON OUTPUT NOW.
"""


# --------------------------------------------------------------------------- #
# Mechanical weighted-vote helper                                             #
# --------------------------------------------------------------------------- #


def compute_weighted_vote(
    locks: PhaseBLockedSet,
    weights: dict[str, float],
) -> dict[str, float]:
    """Aggregate verdict-weights from the 5 locks.

    Returns a mapping ``verdict -> total_weight`` summed over styles. The
    weighted vote does NOT itself decide the synthesis — it's a mechanical
    input PMSupervisor uses (per Section 2.4 #1: synthesis is judgment,
    not arithmetic).
    """
    tally = {v: 0.0 for v in ALL_VERDICTS}
    for sid, lk in locks.locks.items():
        w = weights.get(sid, 0.0)
        if lk.verdict in tally:
            tally[lk.verdict] += w
    return tally


def _format_weights(weights: dict[str, float]) -> str:
    return "\n".join(
        f"  {sid}: {w:.2f}" for sid, w in sorted(weights.items())
    )


def _format_weighted_vote(tally: dict[str, float]) -> str:
    return "\n".join(
        f"  {v}: {tally.get(v, 0.0):.3f}" for v in (VERDICT_ADD, VERDICT_WATCH, VERDICT_PASS)
    )


def _format_phase_b(locks: PhaseBLockedSet) -> str:
    parts: list[str] = []
    for sid, lk in locks.locks.items():
        parts.append(f"--- {sid} VERDICT={lk.verdict} ---")
        parts.append(f"  rationale: {lk.rationale}")
        parts.append("  load_bearing_claims:")
        for c in lk.load_bearing_claims:
            parts.append(
                f"    [{c.claim_id}] (-> {c.supports_recommendation}) {c.text}"
            )
        parts.append("")
    return "\n".join(parts)


def _format_nons(locks: PhaseBLockedSet) -> str:
    parts: list[str] = []
    for sid, lk in locks.locks.items():
        for n in lk.non_negotiables:
            parts.append(f"  {sid}.[{n.constraint_id}] {n.text}")
    if not parts:
        return "  <none>"
    return "\n".join(parts)


def _format_phase_c_negotiation(
    negotiation: Optional[PhaseCNegotiationResult],
) -> str:
    if negotiation is None or not negotiation.rounds:
        return "  (Phase C did not run — no negotiation transcript.)"
    parts: list[str] = ["  Phase C negotiation transcript:"]
    for r in negotiation.rounds:
        parts.append(f"  Round {r.round_number}:")
        for sid, ref in r.per_style.items():
            parts.append(
                f"    {sid}: refined='{ref.refined_position}'; "
                f"concedes={ref.willing_to_concede}; "
                f"still_disagrees={ref.still_disagrees_with}"
            )
    parts.append(f"  Resolved: {negotiation.resolved_conflicts}")
    parts.append(f"  Unresolved: {negotiation.unresolved_conflicts}")
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# Synthesis runner                                                            #
# --------------------------------------------------------------------------- #


def run_phase_d(
    *,
    phase_a: PhaseAResult,
    locked: PhaseBLockedSet,
    judge_result: PhaseCJudgeResult,
    negotiation: Optional[PhaseCNegotiationResult] = None,
    mode: str,
    sector: Optional[str] = None,
    client: Any = None,
    model: str = MODEL_OPUS,
    temperature: float = 0.2,
) -> PhaseDSynthesis:
    """Run the PMSupervisor synthesis with explicit dissent preservation.

    Args:
        phase_a: Phase A result (preliminary cases; not used directly by
            the LLM but included for downstream audit completeness).
        locked: Phase B locked set; the canonical source of verdicts.
        judge_result: Phase C trigger judge output.
        negotiation: Phase C negotiation result if it ran; ``None`` if
            ``judge_result.phase_c_needed`` was False.
        mode: B / B_prime / C — drives the weighting matrix lookup.
        sector: Optional sector tag for sector overrides.
        client: Optional pre-built Anthropic client.
        model: Default Opus (high-stakes synthesis).
        temperature: 0.2 — low variance for the final decision call.
    """
    if client is None:
        client = build_default_client()

    weights = get_weights(mode=mode, sector=sector)
    tally = compute_weighted_vote(locked, weights)

    user_prompt = _USER_TEMPLATE.format(
        ticker=locked.ticker,
        mode=mode,
        sector=sector or "<none>",
        weights_block=_format_weights(weights),
        weighted_vote_block=_format_weighted_vote(tally),
        phase_b_block=_format_phase_b(locked),
        phase_c_needed=judge_result.phase_c_needed,
        judge_confidence=judge_result.judge_confidence,
        conflict_count=len(judge_result.conflicts),
        phase_c_negotiation_block=_format_phase_c_negotiation(negotiation),
        nons_block=_format_nons(locked),
    )

    raw = call_messages(
        client,
        model,
        _SYSTEM_PROMPT,
        user_prompt,
        max_tokens=3072,
        temperature=temperature,
    )
    parsed = extract_json(raw)
    if parsed is None:
        return PhaseDSynthesis(
            ticker=locked.ticker,
            decision=VERDICT_PASS,
            recommended_conviction=0.0,
            mode=mode,
            sector=sector,
            weights_used=weights,
            raw_text=raw,
            valid=False,
            invalid_reason="json parse failure",
        )

    return _validate_phase_d_payload(
        parsed=parsed,
        ticker=locked.ticker,
        locked=locked,
        mode=mode,
        sector=sector,
        weights=weights,
        raw_text=raw,
    )


def _validate_phase_d_payload(
    *,
    parsed: dict,
    ticker: str,
    locked: PhaseBLockedSet,
    mode: str,
    sector: Optional[str],
    weights: dict[str, float],
    raw_text: str,
) -> PhaseDSynthesis:
    """Validate Phase D LLM output + ENFORCE the dissent-preservation invariant."""
    decision = str(parsed.get("decision", "")).upper()
    if decision not in ALL_VERDICTS:
        return PhaseDSynthesis(
            ticker=ticker,
            decision=VERDICT_PASS,
            recommended_conviction=0.0,
            mode=mode,
            sector=sector,
            weights_used=weights,
            raw_text=raw_text,
            valid=False,
            invalid_reason=f"invalid decision: {decision!r}",
        )
    try:
        conviction = float(parsed.get("recommended_conviction", 0.0))
    except (TypeError, ValueError):
        conviction = 0.0
    conviction = max(0.0, min(1.0, conviction))

    raw_dissent = parsed.get("dissent_trace", [])
    dissent: list[DissentEntry] = []
    if isinstance(raw_dissent, list):
        for raw in raw_dissent:
            if not isinstance(raw, dict):
                continue
            sid = str(raw.get("style", "")).strip()
            v = str(raw.get("verdict", "")).upper()
            if not sid or v not in ALL_VERDICTS:
                continue
            try:
                w = float(raw.get("weight", weights.get(sid, 0.0)))
            except (TypeError, ValueError):
                w = weights.get(sid, 0.0)
            dissent.append(
                DissentEntry(
                    style_id=sid,
                    verdict=v,
                    rationale=str(raw.get("rationale", "")),
                    weight=w,
                )
            )

    # CRITICAL ENFORCEMENT: every locked style MUST appear in the
    # dissent trace, even if the model omitted it. We don't trust the
    # LLM to obey "no omissions" — we backfill from Phase B locks.
    seen = {d.style_id for d in dissent}
    for sid, lk in locked.locks.items():
        if sid not in seen:
            dissent.append(
                DissentEntry(
                    style_id=sid,
                    verdict=lk.verdict,
                    rationale=lk.rationale or "(rationale not surfaced by PMSupervisor; backfilled from Phase B)",
                    weight=weights.get(sid, 0.0),
                )
            )

    override_reasoning = str(parsed.get("override_reasoning", "")).strip()
    # ENFORCE: if any style's verdict != decision, override_reasoning must be non-empty.
    requires_override = any(d.verdict != decision for d in dissent)
    if requires_override and not override_reasoning:
        override_reasoning = (
            "(override_reasoning was empty in PMSupervisor output despite "
            "dissenting style verdicts — flagged for operator review)"
        )

    raw_nons = parsed.get("non_negotiables_not_addressed", [])
    nons: list[UnaddressedNonNegotiable] = []
    if isinstance(raw_nons, list):
        for raw in raw_nons:
            if not isinstance(raw, dict):
                continue
            sid = str(raw.get("style", "")).strip()
            cid = str(raw.get("constraint_id", "")).strip()
            text = str(raw.get("text", "")).strip()
            if not (sid and cid and text):
                continue
            nons.append(
                UnaddressedNonNegotiable(
                    style_id=sid,
                    constraint_id=cid,
                    text=text,
                )
            )

    return PhaseDSynthesis(
        ticker=ticker,
        decision=decision,
        recommended_conviction=conviction,
        dissent_trace=dissent,
        override_reasoning=override_reasoning,
        non_negotiables_not_addressed=nons,
        mode=mode,
        sector=sector,
        weights_used=weights,
        raw_text=raw_text,
        valid=True,
    )


# --------------------------------------------------------------------------- #
# WS-5 — Best-of-N synthesis with cross-model verifier (BoN-MAV)              #
# --------------------------------------------------------------------------- #


_VERIFIER_SYSTEM_PROMPT = """\
You are the BoN VERIFIER for the PMSupervisor synthesis. You are a DIFFERENT,
cheaper model than the synthesizer on purpose — to cut self-preference bias.

You are given N candidate syntheses (each an ADD/WATCH/PASS decision with a
dissent trace + conviction + override reasoning). RANK them and SELECT the
single best one on these criteria, in order:

  1. Faithfully preserves dissent (does NOT force consensus).
  2. Override reasoning addresses the load-bearing dissenting claim (not just
     "it's the weighted vote").
  3. Conviction is consistent with the dissent spread.
  4. Surfaces unaddressed non-negotiables.

You do NOT rewrite any candidate. You only pick the best index.

Return ONLY this JSON — no markdown:
  {"selected_index": <int 0-based>, "rationale": "<= 2 sentences"}
"""


def _verifier_user_prompt(candidates: list[BoNCandidate]) -> str:
    parts: list[str] = ["CANDIDATES (pick the best by index):", ""]
    for c in candidates:
        p = c.payload or {}
        parts.append(f"--- INDEX {c.sample_index} ---")
        parts.append(f"  decision: {p.get('decision')}")
        parts.append(f"  recommended_conviction: {p.get('recommended_conviction')}")
        parts.append(f"  override_reasoning: {p.get('override_reasoning', '')!r}")
        dt = p.get("dissent_trace", []) or []
        parts.append(f"  dissent_trace ({len(dt)} styles):")
        for d in dt:
            if isinstance(d, dict):
                parts.append(
                    f"    {d.get('style')}: {d.get('verdict')} "
                    f"(w={d.get('weight')}) — {d.get('rationale', '')}"
                )
        parts.append("")
    parts.append("SELECT THE BEST INDEX NOW.")
    return "\n".join(parts)


def _resolve_verifier_model(agent_name: str = "pm-supervisor") -> str:
    """Resolve the verifier model from the agent header (P0-6).

    Reads ``verifier_model`` from ``.claude/agents/<agent>.md`` via the P0-6
    reader and pins it to a resolved id. Falls back to the ``sonnet`` resolved
    id if the header (or reader) is unavailable so the verifier is ALWAYS a
    different model than the opus synthesizer.
    """
    try:
        from src.llm_cache.agent_model import VERIFIER, effective_model

        resolved = effective_model(agent_name, VERIFIER)
        if resolved:
            return resolved
    except Exception:  # pragma: no cover - header reader must never break runtime
        _LOG.warning("verifier-model header read failed; defaulting to sonnet")
    from src.llm_cache.model_pin import pin_resolved_model

    return pin_resolved_model(MODEL_SONNET)


def _conviction_inputs_from_candidate(
    payload: Optional[dict],
    locked: PhaseBLockedSet,
) -> ConvictionInputSample:
    """Derive the conviction INPUTS one candidate implies.

    * ``debate_add_count`` — count of styles whose dissent-trace verdict is ADD
      (falls back to the Phase-B locks if the candidate omitted the trace).
    * ``kills_fired``       — candidate's ``kills_fired`` field if present.
    * ``drift``             — candidate's ``anchor_drift_channels_triggered``
      (a.k.a. ``drift``) field if present, clamped to 0..3.
    """
    add_count = 0
    if payload and isinstance(payload.get("dissent_trace"), list):
        for d in payload["dissent_trace"]:
            if isinstance(d, dict) and str(d.get("verdict", "")).upper() == VERDICT_ADD:
                add_count += 1
    else:
        add_count = sum(1 for lk in locked.locks.values() if lk.verdict == VERDICT_ADD)

    def _int(v: Any, default: int = 0) -> int:
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    kills = _int((payload or {}).get("kills_fired"), 0)
    drift = _int(
        (payload or {}).get("anchor_drift_channels_triggered",
                            (payload or {}).get("drift")),
        0,
    )
    drift = max(0, min(3, drift))
    return ConvictionInputSample(
        debate_add_count=max(0, min(5, add_count)),
        kills_fired=max(0, kills),
        drift=drift,
    )


@dataclass
class PhaseDBoNResult:
    """Full WS-5 BoN-MAV output: the selected synthesis + provenance."""

    synthesis: PhaseDSynthesis
    candidates: list[BoNCandidate]
    verifier_pick: VerifierPick
    aggregated_conviction_inputs: AggregatedConvictionInputs
    attempt_cost_usd: float
    n: int
    synthesizer_model: str
    verifier_model: str
    cost_cap_usd: float = COST_CAP_USD
    cost_within_cap: bool = True
    mad_path_used: bool = False

    def to_payload(self) -> dict:
        return {
            "synthesis": self.synthesis.to_payload(),
            "candidates": [c.to_payload() for c in self.candidates],
            "verifier_pick": self.verifier_pick.to_payload(),
            "aggregated_conviction_inputs": {
                "debate_add_count": self.aggregated_conviction_inputs.debate_add_count,
                "kills_fired": self.aggregated_conviction_inputs.kills_fired,
                "drift": self.aggregated_conviction_inputs.drift,
            },
            "attempt_cost_usd": self.attempt_cost_usd,
            "n": self.n,
            "synthesizer_model": self.synthesizer_model,
            "verifier_model": self.verifier_model,
            "cost_cap_usd": self.cost_cap_usd,
            "cost_within_cap": self.cost_within_cap,
            "mad_path_used": self.mad_path_used,
        }


def run_phase_d_bon(
    *,
    phase_a: PhaseAResult,
    locked: PhaseBLockedSet,
    judge_result: PhaseCJudgeResult,
    negotiation: Optional[PhaseCNegotiationResult] = None,
    mode: str,
    sector: Optional[str] = None,
    client: Any = None,
    verifier_client: Any = None,
    synthesizer_model: str = MODEL_OPUS,
    verifier_model: Optional[str] = None,
    agent_name: str = "pm-supervisor",
    n: int = BON_N,
    temperature: float = SELF_CONSISTENCY_TEMPERATURE,
    candidate_axes: Optional[list[dict]] = None,
    heterogeneous_models: bool = False,
    verifiable_step: bool = False,
) -> PhaseDBoNResult:
    """WS-5 BoN-MAV synthesis: N=5 opus candidates + sonnet verifier select.

    Flow:
      1. Generate ``n`` (cap 5) synthesizer candidates from a SINGLE opus
         synthesizer (self-consistency, first-pass only) at ``temperature``.
      2. Resolve the verifier model from the agent header (P0-6) — sonnet,
         a DIFFERENT model than the opus synthesizer.
      3. Verifier ranks/selects the best candidate. On verifier ERROR, fall
         back to self-consistency (majority decision); NEVER auto-PASS.
      4. Aggregate the conviction INPUTS across the N passes BEFORE the
         deterministic rollup (do NOT average final convictions).
      5. Roll candidate + verifier usage into ONE ``attempt_cost_usd`` and
         enforce the ``$15/pass`` cap.

    The MAD path is gated: it runs only when BOTH ``heterogeneous_models`` AND
    ``verifiable_step`` are set; otherwise this is pure self-consistency BoN.
    """
    if client is None:
        client = build_default_client()
    n = max(1, min(int(n), BON_N_CAP))

    weights = get_weights(mode=mode, sector=sector)
    tally = compute_weighted_vote(locked, weights)
    user_prompt = _USER_TEMPLATE.format(
        ticker=locked.ticker,
        mode=mode,
        sector=sector or "<none>",
        weights_block=_format_weights(weights),
        weighted_vote_block=_format_weighted_vote(tally),
        phase_b_block=_format_phase_b(locked),
        phase_c_needed=judge_result.phase_c_needed,
        judge_confidence=judge_result.judge_confidence,
        conflict_count=len(judge_result.conflicts),
        phase_c_negotiation_block=_format_phase_c_negotiation(negotiation),
        nons_block=_format_nons(locked),
    )

    input_sha = bon_input_sha(system=_SYSTEM_PROMPT, user=user_prompt)
    resolved_verifier = (
        verifier_model if verifier_model else _resolve_verifier_model(agent_name)
    )

    mad_path = mad_allowed(
        heterogeneous_models=heterogeneous_models, verifiable_step=verifiable_step
    )

    # --- BoN-level cache (opt-in): (input_sha, model_version, n, temp) ----- #
    #     -> {candidates, verifier_pick}. Stores BOTH the N candidates and the
    # verifier pick as ONE value (distinct from the per-sample llm_cache key,
    # which also carries sample_index). Default OFF; enabled via LLM_CACHE_*.
    bon_cache = None
    bon_key = None
    try:
        from src.llm_cache import cache_from_env  # noqa: WPS433
        from src.llm_cache.cache import CacheKey

        bon_cache = cache_from_env()
        if bon_cache is not None:
            digest = bon_cache_digest(
                input_sha=input_sha,
                model_version=synthesizer_model,
                n=n,
                temperature=temperature,
            )
            # Reuse the llm_cache store keyed by the BoN digest (the CacheKey's
            # prompt_sha slot carries the full BoN digest; sample_index=-1 marks
            # the BoN-level aggregate entry so it never collides with per-sample
            # entries that use sample_index >= 0).
            bon_key = CacheKey(
                model_version=synthesizer_model,
                prompt_sha=digest,
                temperature=temperature,
                max_tokens=0,
                sample_index=-1,
            )
    except Exception:  # pragma: no cover - cache import must never break runtime
        bon_cache = None
        bon_key = None

    cached_text = None
    if bon_cache is not None and bon_key is not None:
        cached_text = bon_cache.get(bon_key)

    if cached_text is not None:
        # Replay: rebuild candidates, the verifier pick AND the verifier usage;
        # no model is called. BUG 2 fix: verifier usage is now PERSISTED in the
        # BoN cache and replayed here, instead of being hardcoded to zero. This
        # makes attempt_cost_usd on a replay identical to the recorded run
        # (candidate usages already replayed their recorded token counts).
        candidates, pick, verifier_usage = deserialize_bon_result(cached_text)
    else:
        # --- 1. generate N synthesizer candidates (self-consistency) ------- #
        candidates = []
        for i in range(n):
            # BUG 2 fix (cost reproducibility): clear last_response BEFORE the
            # call so usage extraction is strictly per-call. On a per-sample
            # CACHE HIT, call_messages returns text WITHOUT invoking
            # _raw_call_messages, so last_response is never refreshed; without
            # this reset, a STALE last_response from a prior loop iteration (or
            # a prior run) would leak into this candidate's usage, making
            # attempt_cost_usd call-order dependent and non-reproducible on
            # replay. Cleared -> a cache-hit candidate deterministically
            # records ZERO usage, which the BoN-level cache then serializes and
            # faithfully replays.
            try:
                client.last_response = None
            except Exception:  # pragma: no cover - read-only client object
                pass
            raw = call_messages(
                client,
                synthesizer_model,
                _SYSTEM_PROMPT,
                user_prompt,
                max_tokens=3072,
                temperature=temperature,
                sample_index=i,
            )
            # extract_usage reads the last raw response object when the fake/SDK
            # exposes it; call_messages only returns text, so we read usage off
            # the client's recorded call when available (test doubles attach
            # .last_response, _llm._raw_call_messages stashes it in prod). On a
            # per-sample cache hit last_response stays None (cleared above) ->
            # deterministic zero usage rather than a stale carry-over.
            last_resp = getattr(client, "last_response", None)
            usage = extract_usage(synthesizer_model, last_resp)
            payload = extract_json(raw)
            axes = (
                candidate_axes[i] if candidate_axes and i < len(candidate_axes) else {}
            ) or {}
            cand = BoNCandidate(
                sample_index=i,
                raw_text=raw,
                payload=payload,
                conviction_inputs=_conviction_inputs_from_candidate(payload, locked),
                usage=usage,
                axes=axes,
                composite_quality=composite_quality(axes) if axes else 0.0,
            )
            candidates.append(cand)

        # --- 2 + 3. verifier select (sonnet) w/ self-consistency fallback -- #
        vclient = verifier_client if verifier_client is not None else client
        # BUG 2 fix (cost reproducibility): clear last_response BEFORE the
        # verifier call for the same reason as the candidate loop — a verifier
        # cache hit (or a fallback that issues no call) must not inherit a
        # stale last_response. Cleared -> deterministic zero verifier usage on
        # a cache hit / fallback, serialized + replayed via the BoN cache.
        try:
            vclient.last_response = None
        except Exception:  # pragma: no cover - read-only client object
            pass
        pick = _verify_select(
            candidates=candidates,
            verifier_client=vclient,
            verifier_model=resolved_verifier,
        )
        verifier_usage = UsageRecord(
            model=resolved_verifier, input_tokens=0, output_tokens=0
        )
        if pick.method == "verifier":
            verifier_usage = extract_usage(
                resolved_verifier, getattr(vclient, "last_response", None)
            )

        # Store candidates, the verifier pick AND the verifier usage under the
        # BoN key. Persisting verifier_usage (BUG 2) lets a replay reproduce the
        # exact attempt_cost_usd recorded here.
        if bon_cache is not None and bon_key is not None:
            bon_cache.put(
                bon_key, serialize_bon_result(candidates, pick, verifier_usage)
            )

    # --- 4. aggregate conviction INPUTS BEFORE the deterministic rollup --- #
    aggregated = aggregate_conviction_inputs([c.conviction_inputs for c in candidates])

    # --- 5. cost rollup + cap -------------------------------------------- #
    usages = [c.usage for c in candidates] + [verifier_usage]
    cost = attempt_cost_usd(usages)
    within_cap = cost <= COST_CAP_USD
    if not within_cap:
        _LOG.warning(
            "BoN attempt_cost_usd=%.4f exceeds cap $%.2f", cost, COST_CAP_USD
        )

    # Build the selected synthesis (re-validate through the existing validator,
    # which enforces the dissent-preservation invariant + backfill).
    selected = next(
        (c for c in candidates if c.sample_index == pick.selected_index), candidates[0]
    )
    if selected.payload is not None:
        synthesis = _validate_phase_d_payload(
            parsed=selected.payload,
            ticker=locked.ticker,
            locked=locked,
            mode=mode,
            sector=sector,
            weights=weights,
            raw_text=selected.raw_text,
        )
    else:
        # NEVER auto-PASS on a parse failure: mark invalid for operator review.
        synthesis = PhaseDSynthesis(
            ticker=locked.ticker,
            decision=VERDICT_PASS,
            recommended_conviction=0.0,
            mode=mode,
            sector=sector,
            weights_used=weights,
            raw_text=selected.raw_text,
            valid=False,
            invalid_reason="selected BoN candidate failed JSON parse",
        )
    synthesis.model = synthesizer_model

    return PhaseDBoNResult(
        synthesis=synthesis,
        candidates=candidates,
        verifier_pick=pick,
        aggregated_conviction_inputs=aggregated,
        attempt_cost_usd=cost,
        n=n,
        synthesizer_model=synthesizer_model,
        verifier_model=resolved_verifier,
        cost_within_cap=within_cap,
        mad_path_used=mad_path,
    )


def _verify_select(
    *,
    candidates: list[BoNCandidate],
    verifier_client: Any,
    verifier_model: str,
) -> VerifierPick:
    """Run the sonnet verifier; fall back to self-consistency on ANY error.

    The verifier picks the best candidate index. On verifier error (exception,
    unparseable output, out-of-range index) we degrade to
    ``self_consistency_pick`` — NEVER auto-PASS.
    """
    try:
        raw = call_messages(
            verifier_client,
            verifier_model,
            _VERIFIER_SYSTEM_PROMPT,
            _verifier_user_prompt(candidates),
            max_tokens=512,
            temperature=0.0,
        )
    except Exception as exc:  # verifier round-trip failed
        _LOG.warning("verifier call raised %r; falling back to self-consistency", exc)
        return self_consistency_pick(
            candidates,
            fallback_reason=f"verifier exception: {type(exc).__name__}",
            verifier_model=verifier_model,
        )

    parsed = extract_json(raw)
    if not isinstance(parsed, dict) or "selected_index" not in parsed:
        return self_consistency_pick(
            candidates,
            fallback_reason="verifier returned unparseable / missing selected_index",
            verifier_model=verifier_model,
        )
    try:
        idx = int(parsed["selected_index"])
    except (TypeError, ValueError):
        return self_consistency_pick(
            candidates,
            fallback_reason="verifier selected_index not an int",
            verifier_model=verifier_model,
        )
    valid_indices = {c.sample_index for c in candidates}
    if idx not in valid_indices:
        return self_consistency_pick(
            candidates,
            fallback_reason=f"verifier selected out-of-range index {idx}",
            verifier_model=verifier_model,
        )
    return VerifierPick(
        selected_index=idx,
        method="verifier",
        rationale=str(parsed.get("rationale", "")),
        verifier_model=verifier_model,
    )


__all__ = [
    "DissentEntry",
    "UnaddressedNonNegotiable",
    "PhaseDSynthesis",
    "PhaseDBoNResult",
    "compute_weighted_vote",
    "run_phase_d",
    "run_phase_d_bon",
]
