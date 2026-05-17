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
    PROMPT_VERSION_PHASE_D,
    VERDICT_ADD,
    VERDICT_PASS,
    VERDICT_WATCH,
    get_weights,
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


__all__ = [
    "DissentEntry",
    "UnaddressedNonNegotiable",
    "PhaseDSynthesis",
    "compute_weighted_vote",
    "run_phase_d",
]
