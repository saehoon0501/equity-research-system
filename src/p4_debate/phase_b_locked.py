"""Phase B — locked load-bearing claims + non-negotiables per style.

Per v3 spec Section 2.3 row "B Locked claims" (line 167) and Section 2.4
finding 2 ("Persona drift is real — Phase B locks load-bearing claims
and non-negotiables in writing; Phase C cannot modify Phase B locks").

Schema per style::

    {
      style: "Value" | "Growth" | "Quality / Moat" | "Macro / Regime" | "Quant / Technical",
      load_bearing_claims: [
        {id, text, supports_recommendation: ADD|WATCH|PASS}
      ],
      non_negotiables: [
        {id, text}
      ]
    }

The :class:`PhaseBStyleLock` dataclass is ``frozen=True``: once a
``PhaseBLockedSet`` is constructed, the engine MAY NOT mutate any
locked field. Phase C's :func:`refine_within_locks` API takes the
locked set as input and produces NEW positions — it cannot reach
back into the lock. This is the structural mitigation for L8 finding
13 (sycophantic collapse) + Section 2.4 finding 2 (persona drift).
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Optional

from . import (
    ALL_STYLES,
    ALL_VERDICTS,
    MODEL_SONNET,
    PROMPT_VERSION_PHASE_B,
    VERDICT_PASS,
)
from ._llm import build_default_client, call_messages, extract_json
from .phase_a_isolated import PhaseAResult, PhaseAStyleOutput
from .styles import PERSONAS

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoadBearingClaim:
    """One falsifiable claim that, if untrue, flips the style's verdict.

    Frozen to enforce Phase B immutability.
    """

    claim_id: str
    text: str
    supports_recommendation: str  # one of ADD / WATCH / PASS


@dataclass(frozen=True)
class NonNegotiable:
    """A condition that MUST hold or the style refuses to move from PASS.

    Frozen to enforce Phase B immutability.
    """

    constraint_id: str
    text: str


@dataclass(frozen=True)
class PhaseBStyleLock:
    """One style's locked claim + non-negotiable set.

    Frozen — once constructed, cannot be modified. The orchestrator's
    Phase C uses these as INPUTS to negotiation prompts but writes new
    state to a separate ``PhaseCRoundResult`` rather than mutating these.
    """

    style_id: str
    verdict: str
    rationale: str
    load_bearing_claims: tuple[LoadBearingClaim, ...]
    non_negotiables: tuple[NonNegotiable, ...]
    valid: bool = True
    invalid_reason: Optional[str] = None
    prompt_version: str = PROMPT_VERSION_PHASE_B
    model: str = MODEL_SONNET

    def to_payload(self) -> dict:
        """Serialize to dict (the spec's Phase B schema)."""
        return {
            "style": self.style_id,
            "verdict": self.verdict,
            "rationale": self.rationale,
            "load_bearing_claims": [
                {
                    "id": c.claim_id,
                    "text": c.text,
                    "supports_recommendation": c.supports_recommendation,
                }
                for c in self.load_bearing_claims
            ],
            "non_negotiables": [
                {"id": n.constraint_id, "text": n.text}
                for n in self.non_negotiables
            ],
            "valid": self.valid,
            "invalid_reason": self.invalid_reason,
            "prompt_version": self.prompt_version,
            "model": self.model,
        }


@dataclass(frozen=True)
class PhaseBLockedSet:
    """The five-style locked claim set after Phase B.

    Frozen at construction. Pass-through-by-value to Phase C; Phase D
    reads the same instance.
    """

    ticker: str
    locks: dict[str, PhaseBStyleLock] = field(default_factory=dict)

    def to_payload(self) -> dict:
        return {
            "ticker": self.ticker,
            "locks": {sid: lk.to_payload() for sid, lk in self.locks.items()},
        }


# --------------------------------------------------------------------------- #
# Prompt construction                                                         #
# --------------------------------------------------------------------------- #


_USER_TEMPLATE = """\
TICKER: {ticker}

YOUR PHASE A PRELIMINARY OUTPUT (already produced by you in isolation):
  preliminary_verdict: {prelim_verdict}
  preliminary_rationale: {prelim_rationale}
  key_observations:
{key_obs_block}

CANDIDATE FACTS (verbatim block — quote from this only):
{candidate_facts}

TASK — PHASE B (lock-in):
Refine your preliminary case into IMMUTABLE form. Once you submit this,
neither you nor any other style nor the PMSupervisor may modify these
fields. Phase C negotiation rounds will surface conflicts but they
cannot rewrite your locked claims — they can only ask whether new
information should warrant a SEPARATE refined position.

Output ONLY this JSON object — no markdown, no commentary:

{{
  "verdict": "ADD" | "WATCH" | "PASS",
  "rationale": "<= 4 sentences anchoring the verdict",
  "load_bearing_claims": [
    {{"id": "<short id>", "text": "<falsifiable claim>",
      "supports_recommendation": "ADD" | "WATCH" | "PASS"}},
    ...
  ],
  "non_negotiables": [
    {{"id": "<short id>", "text": "<condition that MUST hold>"}},
    ...
  ]
}}

REQUIREMENTS:
  - 3-7 load_bearing_claims; each must be FALSIFIABLE (a statement that
    new evidence could prove false).
  - 2-5 non_negotiables; each must be a HARD floor below which you
    will not move from PASS regardless of debate pressure.
  - Verdict must be consistent with at least one supporting claim.
  - Use stable string ids (e.g., "v_lbc_1", "v_nn_1") so Phase C can
    reference them across rounds.
"""


def _format_obs(observations: list[str]) -> str:
    if not observations:
        return "    <none>"
    return "\n".join(f"    - {o}" for o in observations)


# --------------------------------------------------------------------------- #
# Per-style runner                                                            #
# --------------------------------------------------------------------------- #


def _run_one_style(
    *,
    style_id: str,
    ticker: str,
    phase_a_output: PhaseAStyleOutput,
    candidate_facts: str,
    client: Any,
    model: str,
    temperature: float,
) -> PhaseBStyleLock:
    persona = PERSONAS[style_id]
    user_prompt = _USER_TEMPLATE.format(
        ticker=ticker,
        prelim_verdict=phase_a_output.preliminary_verdict,
        prelim_rationale=phase_a_output.preliminary_rationale,
        key_obs_block=_format_obs(phase_a_output.key_observations),
        candidate_facts=candidate_facts.strip(),
    )
    raw = call_messages(
        client,
        model,
        persona.system_prompt,
        user_prompt,
        max_tokens=2048,
        temperature=temperature,
    )
    parsed = extract_json(raw)
    if parsed is None:
        return PhaseBStyleLock(
            style_id=style_id,
            verdict=VERDICT_PASS,
            rationale="malformed JSON; defaulted to PASS",
            load_bearing_claims=(),
            non_negotiables=(),
            valid=False,
            invalid_reason="json parse failure",
            model=model,
        )
    return _parse_payload_to_lock(
        style_id=style_id,
        parsed=parsed,
        model=model,
    )


def _parse_payload_to_lock(
    *,
    style_id: str,
    parsed: dict,
    model: str,
) -> PhaseBStyleLock:
    """Parse a Phase B JSON payload into a frozen :class:`PhaseBStyleLock`.

    On any validation failure we return a valid=False lock with verdict
    PASS — the orchestrator surfaces this to the operator (per the
    Evaluator hard-gate convention: do not silently down-grade).
    """
    verdict = str(parsed.get("verdict", "")).upper()
    if verdict not in ALL_VERDICTS:
        return PhaseBStyleLock(
            style_id=style_id,
            verdict=VERDICT_PASS,
            rationale="invalid verdict",
            load_bearing_claims=(),
            non_negotiables=(),
            valid=False,
            invalid_reason=f"invalid verdict: {verdict!r}",
            model=model,
        )

    raw_claims = parsed.get("load_bearing_claims", [])
    raw_nons = parsed.get("non_negotiables", [])
    if not isinstance(raw_claims, list) or not isinstance(raw_nons, list):
        return PhaseBStyleLock(
            style_id=style_id,
            verdict=VERDICT_PASS,
            rationale="malformed claim/non-negotiable lists",
            load_bearing_claims=(),
            non_negotiables=(),
            valid=False,
            invalid_reason="claims or non_negotiables not a list",
            model=model,
        )

    claims: list[LoadBearingClaim] = []
    for i, raw in enumerate(raw_claims):
        if not isinstance(raw, dict):
            continue
        cid = str(raw.get("id") or f"{style_id}_lbc_{i+1}")
        ctext = str(raw.get("text", "")).strip()
        cverdict = str(raw.get("supports_recommendation", "")).upper()
        if not ctext or cverdict not in ALL_VERDICTS:
            continue
        claims.append(
            LoadBearingClaim(
                claim_id=cid,
                text=ctext,
                supports_recommendation=cverdict,
            )
        )

    nons: list[NonNegotiable] = []
    for i, raw in enumerate(raw_nons):
        if not isinstance(raw, dict):
            continue
        nid = str(raw.get("id") or f"{style_id}_nn_{i+1}")
        ntext = str(raw.get("text", "")).strip()
        if not ntext:
            continue
        nons.append(NonNegotiable(constraint_id=nid, text=ntext))

    if len(claims) < 3 or len(claims) > 7:
        return PhaseBStyleLock(
            style_id=style_id,
            verdict=verdict,
            rationale=str(parsed.get("rationale", "")),
            load_bearing_claims=tuple(claims),
            non_negotiables=tuple(nons),
            valid=False,
            invalid_reason=(
                f"claim count {len(claims)} outside [3, 7]"
            ),
            model=model,
        )
    if len(nons) < 2 or len(nons) > 5:
        return PhaseBStyleLock(
            style_id=style_id,
            verdict=verdict,
            rationale=str(parsed.get("rationale", "")),
            load_bearing_claims=tuple(claims),
            non_negotiables=tuple(nons),
            valid=False,
            invalid_reason=(
                f"non-negotiable count {len(nons)} outside [2, 5]"
            ),
            model=model,
        )

    return PhaseBStyleLock(
        style_id=style_id,
        verdict=verdict,
        rationale=str(parsed.get("rationale", "")),
        load_bearing_claims=tuple(claims),
        non_negotiables=tuple(nons),
        valid=True,
        model=model,
    )


def run_phase_b(
    *,
    phase_a: PhaseAResult,
    candidate_facts: str,
    client: Any = None,
    model: str = MODEL_SONNET,
    temperature: float = 0.2,
    parallel: bool = True,
) -> PhaseBLockedSet:
    """Lock every style's claim + non-negotiable set.

    Args:
        phase_a: The Phase A result; this is the only source of truth
            for each style's preliminary verdict.
        candidate_facts: Same verbatim block fed to Phase A.
        client: Optional pre-built Anthropic client.
        model: Default Sonnet per spec.
        temperature: Phase B defaults to 0.2 — we want low variance
            because the output is IMMUTABLE.
        parallel: 5-style threadpool (default).
    """
    if client is None:
        client = build_default_client()

    locks: dict[str, PhaseBStyleLock] = {}

    def _runner(sid: str) -> PhaseBStyleLock:
        return _run_one_style(
            style_id=sid,
            ticker=phase_a.ticker,
            phase_a_output=phase_a.per_style[sid],
            candidate_facts=candidate_facts,
            client=client,
            model=model,
            temperature=temperature,
        )

    if parallel:
        with ThreadPoolExecutor(max_workers=len(ALL_STYLES)) as ex:
            futures = {ex.submit(_runner, sid): sid for sid in ALL_STYLES}
            for fut in as_completed(futures):
                sid = futures[fut]
                try:
                    locks[sid] = fut.result()
                except Exception as exc:  # noqa: BLE001
                    _LOG.exception("Phase B style %s failed: %s", sid, exc)
                    locks[sid] = PhaseBStyleLock(
                        style_id=sid,
                        verdict=VERDICT_PASS,
                        rationale=f"runner exception: {exc!r}",
                        load_bearing_claims=(),
                        non_negotiables=(),
                        valid=False,
                        invalid_reason=f"runner exception: {exc!r}",
                        model=model,
                    )
    else:
        for sid in ALL_STYLES:
            locks[sid] = _runner(sid)

    return PhaseBLockedSet(ticker=phase_a.ticker, locks=locks)
