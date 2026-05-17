"""Phase C — bounded negotiation rounds (only when judge says needed).

Per v3 spec Section 2.3 row "C Conditional negotiation" (line 168):
"Refine conflicts only when needed; bounded to 3 rounds." Each round:

* The conflicting styles' claims are surfaced (the judge's
  :class:`JudgedConflict` set from ``phase_c_judge``).
* Each conflicting style is asked to REFINE its position WITHIN its
  Phase B locks — meaning: it can clarify, narrow, or qualify, but it
  cannot rewrite a locked claim or non-negotiable.
* The output is a refined position + new disagreement state. If the
  styles converge (no new conflicts after a round) the loop terminates
  early.

CRITICAL: Phase C runs the SAME locked persona system prompt as Phase
A and B. We DO NOT inject "be more agreeable" or "synthesize toward
consensus" instructions. Per L8 finding 13 (Peacemaker/Troublemaker),
that is exactly the failure mode that destroys debate value.

Output schema (per round + final aggregate)::

    {
      rounds: [
        {round: int,
         conflicts_addressed: [conflict_id, ...],
         per_style_refinements: {
           style_id: {
             refined_position: <text>,
             still_disagrees_with: [style_id, ...],
             willing_to_concede: [conflict_id, ...]   # may be empty
           }
         }}
      ],
      final_disagreement_state: {
        unresolved_conflicts: [conflict_id, ...],
        resolved_conflicts: [conflict_id, ...]
      }
    }
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Optional

from . import (
    MODEL_SONNET,
    PHASE_C_MAX_ROUNDS,
    PROMPT_VERSION_PHASE_C_NEGOTIATION,
)
from ._llm import build_default_client, call_messages, extract_json
from .phase_b_locked import PhaseBLockedSet, PhaseBStyleLock
from .phase_c_judge import JudgedConflict, PhaseCJudgeResult
from .styles import PERSONAS

_LOG = logging.getLogger(__name__)


@dataclass
class StyleRefinement:
    """One style's response in one Phase C round."""

    style_id: str
    refined_position: str
    still_disagrees_with: list[str]
    willing_to_concede: list[str]
    raw_text: str = ""
    valid: bool = True
    invalid_reason: Optional[str] = None

    def to_payload(self) -> dict:
        return {
            "refined_position": self.refined_position,
            "still_disagrees_with": list(self.still_disagrees_with),
            "willing_to_concede": list(self.willing_to_concede),
            "valid": self.valid,
            "invalid_reason": self.invalid_reason,
        }


@dataclass
class PhaseCRoundResult:
    """One round's combined output across the conflicting styles."""

    round_number: int
    conflicts_addressed: list[str]  # conflict_id list
    per_style: dict[str, StyleRefinement] = field(default_factory=dict)

    def to_payload(self) -> dict:
        return {
            "round": self.round_number,
            "conflicts_addressed": list(self.conflicts_addressed),
            "per_style_refinements": {
                sid: r.to_payload() for sid, r in self.per_style.items()
            },
        }


@dataclass
class PhaseCNegotiationResult:
    """Full Phase C negotiation output."""

    ticker: str
    rounds: list[PhaseCRoundResult] = field(default_factory=list)
    unresolved_conflicts: list[str] = field(default_factory=list)
    resolved_conflicts: list[str] = field(default_factory=list)
    prompt_version: str = PROMPT_VERSION_PHASE_C_NEGOTIATION

    def to_payload(self) -> dict:
        return {
            "ticker": self.ticker,
            "rounds": [r.to_payload() for r in self.rounds],
            "final_disagreement_state": {
                "unresolved_conflicts": list(self.unresolved_conflicts),
                "resolved_conflicts": list(self.resolved_conflicts),
            },
            "prompt_version": self.prompt_version,
        }


# --------------------------------------------------------------------------- #
# Prompt construction                                                         #
# --------------------------------------------------------------------------- #


_USER_TEMPLATE = """\
TICKER: {ticker}

PHASE C NEGOTIATION — ROUND {round_number} of {max_rounds}

YOUR PHASE B LOCKED CLAIMS (IMMUTABLE — you may NOT rewrite these):

VERDICT: {your_verdict}
LOAD_BEARING_CLAIMS:
{your_claims_block}
NON_NEGOTIABLES:
{your_nons_block}

CONFLICTS THE JUDGE FLAGGED INVOLVING YOU:
{conflicts_block}

OPPOSING STYLES' RELEVANT LOCKED CLAIMS:
{opposing_block}

PRIOR ROUND REFINEMENTS (if any):
{prior_rounds_block}

TASK — refine your position WITHIN your locks. You may:
  - Clarify a load-bearing claim's scope (e.g., "applies only when X").
  - Acknowledge that the opposing style's claim, IF true, would weaken
    yours — without conceding it.
  - Concede a SPECIFIC conflict (by conflict_id) ONLY when the
    opposing claim is genuinely persuasive AND your locks still hold.

You MAY NOT:
  - Rewrite or weaken a locked claim or non-negotiable.
  - Adopt the opposing style's verdict because of debate pressure
    (sycophancy is the failure mode we are designed to prevent).
  - Soften your verdict without explicit evidence change.

Output ONLY this JSON object — no markdown, no commentary:

{{
  "refined_position": "<= 4 sentences refining your stance",
  "still_disagrees_with": ["<style_id>", ...],
  "willing_to_concede": ["<conflict_id>", ...]
}}
"""


def _format_claims(lock: PhaseBStyleLock) -> str:
    if not lock.load_bearing_claims:
        return "  <none>"
    return "\n".join(
        f"  [{c.claim_id}] (-> {c.supports_recommendation}) {c.text}"
        for c in lock.load_bearing_claims
    )


def _format_nons(lock: PhaseBStyleLock) -> str:
    if not lock.non_negotiables:
        return "  <none>"
    return "\n".join(
        f"  [{n.constraint_id}] {n.text}" for n in lock.non_negotiables
    )


def _format_conflicts_for_style(
    style_id: str, conflicts: list[JudgedConflict]
) -> tuple[str, list[str]]:
    """Render conflicts that involve ``style_id`` and return (text, ids)."""
    relevant = [
        c for c in conflicts if c.style_a == style_id or c.style_b == style_id
    ]
    if not relevant:
        return "  <no conflicts involving you>", []
    lines: list[str] = []
    ids: list[str] = []
    for c in relevant:
        ids.append(c.conflict_id)
        opposing = c.style_b if c.style_a == style_id else c.style_a
        oc_id = c.style_b_claim_id if c.style_a == style_id else c.style_a_claim_id
        lines.append(
            f"  [{c.conflict_id}] type={c.conflict_type} "
            f"vs {opposing} (claim {oc_id}): {c.rationale}"
        )
    return "\n".join(lines), ids


def _format_opposing(
    style_id: str,
    conflicts: list[JudgedConflict],
    locked: PhaseBLockedSet,
) -> str:
    """Show the opposing styles' specific claims that we conflict with."""
    seen: set[tuple[str, str]] = set()
    lines: list[str] = []
    for c in conflicts:
        if c.style_a == style_id:
            other_sid, other_cid = c.style_b, c.style_b_claim_id
        elif c.style_b == style_id:
            other_sid, other_cid = c.style_a, c.style_a_claim_id
        else:
            continue
        key = (other_sid, other_cid)
        if key in seen:
            continue
        seen.add(key)
        other_lock = locked.locks.get(other_sid)
        if not other_lock:
            continue
        for cl in other_lock.load_bearing_claims:
            if cl.claim_id == other_cid:
                lines.append(
                    f"  {other_sid}.[{cl.claim_id}] "
                    f"(-> {cl.supports_recommendation}) {cl.text}"
                )
                break
    if not lines:
        return "  <none>"
    return "\n".join(lines)


def _format_prior_rounds(
    style_id: str, prior: list[PhaseCRoundResult]
) -> str:
    if not prior:
        return "  <this is round 1>"
    lines: list[str] = []
    for r in prior:
        ref = r.per_style.get(style_id)
        if not ref:
            continue
        lines.append(
            f"  Round {r.round_number}: refined='{ref.refined_position}', "
            f"conceded={ref.willing_to_concede}, "
            f"still_disagrees={ref.still_disagrees_with}"
        )
    if not lines:
        return "  <no prior refinements from you>"
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Per-style runner                                                            #
# --------------------------------------------------------------------------- #


def _run_one_style_round(
    *,
    style_id: str,
    ticker: str,
    round_number: int,
    locked: PhaseBLockedSet,
    judge_conflicts: list[JudgedConflict],
    prior_rounds: list[PhaseCRoundResult],
    client: Any,
    model: str,
    temperature: float,
) -> tuple[StyleRefinement, list[str]]:
    """Run one style's response for one round; returns (refinement, conflict_ids)."""
    persona = PERSONAS[style_id]
    lock = locked.locks[style_id]
    conflicts_text, conflict_ids = _format_conflicts_for_style(
        style_id, judge_conflicts
    )
    user_prompt = _USER_TEMPLATE.format(
        ticker=ticker,
        round_number=round_number,
        max_rounds=PHASE_C_MAX_ROUNDS,
        your_verdict=lock.verdict,
        your_claims_block=_format_claims(lock),
        your_nons_block=_format_nons(lock),
        conflicts_block=conflicts_text,
        opposing_block=_format_opposing(style_id, judge_conflicts, locked),
        prior_rounds_block=_format_prior_rounds(style_id, prior_rounds),
    )
    raw = call_messages(
        client,
        model,
        persona.system_prompt,
        user_prompt,
        max_tokens=1536,
        temperature=temperature,
    )
    parsed = extract_json(raw)
    if parsed is None:
        return (
            StyleRefinement(
                style_id=style_id,
                refined_position="malformed JSON",
                still_disagrees_with=[],
                willing_to_concede=[],
                raw_text=raw,
                valid=False,
                invalid_reason="json parse failure",
            ),
            conflict_ids,
        )
    refined = str(parsed.get("refined_position", ""))
    sd_raw = parsed.get("still_disagrees_with", [])
    wc_raw = parsed.get("willing_to_concede", [])
    sd = [str(x) for x in sd_raw] if isinstance(sd_raw, list) else []
    wc = [str(x) for x in wc_raw] if isinstance(wc_raw, list) else []
    return (
        StyleRefinement(
            style_id=style_id,
            refined_position=refined,
            still_disagrees_with=sd,
            willing_to_concede=wc,
            raw_text=raw,
            valid=True,
        ),
        conflict_ids,
    )


# --------------------------------------------------------------------------- #
# Negotiation driver                                                          #
# --------------------------------------------------------------------------- #


def _styles_in_conflicts(conflicts: list[JudgedConflict]) -> list[str]:
    """Return the unique set of style ids involved in any conflict."""
    s: set[str] = set()
    for c in conflicts:
        s.add(c.style_a)
        s.add(c.style_b)
    return sorted(s)


def run_phase_c_negotiation(
    *,
    locked: PhaseBLockedSet,
    judge_result: PhaseCJudgeResult,
    client: Any = None,
    model: str = MODEL_SONNET,
    temperature: float = 0.3,
    max_rounds: int = PHASE_C_MAX_ROUNDS,
    parallel: bool = True,
) -> PhaseCNegotiationResult:
    """Run up to ``max_rounds`` (default 3) of bounded negotiation.

    Args:
        locked: The Phase B locked set (immutable; passed by reference).
        judge_result: The judge's conflict set; must have
            ``phase_c_needed=True`` and a non-empty conflict list.
            (Caller guards this; we no-op if either condition is false.)
        client: Optional pre-built Anthropic client.
        model: Sonnet (Section 6 Q1; lower-stakes than the judge call).
        temperature: 0.3 — moderate variance for refinement language.
        max_rounds: Spec-locked ceiling at 3.
        parallel: Run the conflicting styles' refinements in a thread
            pool within each round (default True).

    Returns:
        :class:`PhaseCNegotiationResult` with the per-round transcript
        and the final unresolved/resolved conflict split.
    """
    result = PhaseCNegotiationResult(ticker=locked.ticker)
    if not judge_result.phase_c_needed or not judge_result.conflicts:
        result.unresolved_conflicts = []
        result.resolved_conflicts = []
        return result
    if client is None:
        client = build_default_client()

    conflicting_styles = _styles_in_conflicts(judge_result.conflicts)
    open_conflict_ids = {c.conflict_id for c in judge_result.conflicts}
    resolved: set[str] = set()

    for round_number in range(1, max_rounds + 1):
        round_result = PhaseCRoundResult(
            round_number=round_number,
            conflicts_addressed=sorted(open_conflict_ids - resolved),
        )

        def _runner(sid: str) -> tuple[StyleRefinement, list[str]]:
            return _run_one_style_round(
                style_id=sid,
                ticker=locked.ticker,
                round_number=round_number,
                locked=locked,
                judge_conflicts=judge_result.conflicts,
                prior_rounds=result.rounds,
                client=client,
                model=model,
                temperature=temperature,
            )

        if parallel:
            with ThreadPoolExecutor(max_workers=len(conflicting_styles)) as ex:
                futures = {
                    ex.submit(_runner, sid): sid for sid in conflicting_styles
                }
                for fut in as_completed(futures):
                    sid = futures[fut]
                    try:
                        refinement, _ = fut.result()
                    except Exception as exc:  # noqa: BLE001
                        _LOG.exception(
                            "Phase C round %d style %s failed: %s",
                            round_number, sid, exc,
                        )
                        refinement = StyleRefinement(
                            style_id=sid,
                            refined_position=f"runner exception: {exc!r}",
                            still_disagrees_with=[],
                            willing_to_concede=[],
                            valid=False,
                            invalid_reason=f"runner exception: {exc!r}",
                        )
                    round_result.per_style[sid] = refinement
        else:
            for sid in conflicting_styles:
                refinement, _ = _runner(sid)
                round_result.per_style[sid] = refinement

        result.rounds.append(round_result)

        # Conflicts resolved if BOTH sides of a conflict are willing to
        # concede it — otherwise it remains open.
        for conflict in judge_result.conflicts:
            cid = conflict.conflict_id
            if cid in resolved:
                continue
            ra = round_result.per_style.get(conflict.style_a)
            rb = round_result.per_style.get(conflict.style_b)
            a_concedes = bool(ra and cid in ra.willing_to_concede)
            b_concedes = bool(rb and cid in rb.willing_to_concede)
            # Conservative: require BOTH sides to concede for resolution.
            # This prevents one-sided sycophantic capitulation from
            # collapsing a real disagreement (per Section 2.4 #1 +
            # L8 finding 13).
            if a_concedes and b_concedes:
                resolved.add(cid)

        # Early termination if all conflicts resolved.
        if resolved == open_conflict_ids:
            break

    result.resolved_conflicts = sorted(resolved)
    result.unresolved_conflicts = sorted(open_conflict_ids - resolved)
    return result


__all__ = [
    "StyleRefinement",
    "PhaseCRoundResult",
    "PhaseCNegotiationResult",
    "run_phase_c_negotiation",
]
