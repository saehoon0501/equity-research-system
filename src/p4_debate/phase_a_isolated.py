"""Phase A — isolated parallel research per style.

Per v3 spec Section 2.3 row "A Isolated research" (line 166): each style
independently builds its case with NO cross-style visibility. This is
the *manufactured independence* requirement — preventing persona
contamination per L8 finding 11 (ChatEval: persona diversity matters
more than agent count) and L8 finding 13 (Peacemaker/Troublemaker:
persistent identities prevent sycophancy).

Inputs per style:

* candidate facts (verbatim block; same for all styles)
* L1/L3 references (if available; mode-classifier passes through
  L3-successful-companies)
* scenario set (from P2 — same for all styles)
* S0 regime context — DELIVERED ONLY TO ``macro_regime`` per Section 2.6
  Sidecar wiring (Macro-Regime is the only style that pulls S0)

Output schema per style (preliminary case)::

    {
      style: <style_id>,
      preliminary_verdict: "ADD" | "WATCH" | "PASS",
      preliminary_rationale: <text>,
      key_observations: [<text>, ...],
      regime_sensitivity: "HIGH" | "MEDIUM" | "LOW"  # macro_regime only
    }

The output is "preliminary" — Phase B will then ask the same style to
emit the IMMUTABLE load-bearing claims + non-negotiables.

Concurrency model: ``run_phase_a`` invokes the 5 styles via
``concurrent.futures.ThreadPoolExecutor`` so they run in parallel
without sharing intermediate state. (Each thread instantiates its own
LLM round-trip; no shared mutable across threads.)
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Optional

from . import (
    ALL_STYLES,
    MODEL_SONNET,
    PROMPT_VERSION_PHASE_A,
    STYLE_MACRO_REGIME,
    VERDICT_PASS,
)
from ._llm import build_default_client, call_messages, extract_json
from .styles import PERSONAS

_LOG = logging.getLogger(__name__)


@dataclass
class PhaseAStyleOutput:
    """Per-style Phase A output — preliminary case before Phase B locking."""

    style_id: str
    preliminary_verdict: str
    preliminary_rationale: str
    key_observations: list[str]
    # Populated only for macro_regime; None for the other 4 styles.
    regime_sensitivity: Optional[str] = None
    raw_text: str = ""
    valid: bool = True
    invalid_reason: Optional[str] = None
    prompt_version: str = PROMPT_VERSION_PHASE_A
    model: str = MODEL_SONNET


@dataclass
class PhaseAResult:
    """Full Phase A output — the 5-style cache before Phase B."""

    ticker: str
    per_style: dict[str, PhaseAStyleOutput] = field(default_factory=dict)

    def to_payload(self) -> dict:
        """Serialize for downstream cache / debate_consensus_history."""
        return {
            "ticker": self.ticker,
            "per_style": {
                sid: {
                    "preliminary_verdict": s.preliminary_verdict,
                    "preliminary_rationale": s.preliminary_rationale,
                    "key_observations": s.key_observations,
                    "regime_sensitivity": s.regime_sensitivity,
                    "valid": s.valid,
                    "invalid_reason": s.invalid_reason,
                    "prompt_version": s.prompt_version,
                    "model": s.model,
                }
                for sid, s in self.per_style.items()
            },
        }


# --------------------------------------------------------------------------- #
# Prompt construction                                                         #
# --------------------------------------------------------------------------- #


_USER_TEMPLATE = """\
TICKER: {ticker}

CANDIDATE FACTS (verbatim block — quote from this only):
{candidate_facts}

L1 / L3 REFERENCES (lane references; optional context):
{lane_refs}

SCENARIO SET (from P2):
{scenarios}

{regime_block}

TASK — PHASE A (isolated):
Produce your style's PRELIMINARY case. You DO NOT see the other styles'
work; this is manufactured independence.

Output ONLY this JSON object — no markdown, no commentary:

{{
  "preliminary_verdict": "ADD" | "WATCH" | "PASS",
  "preliminary_rationale": "<= 4 sentences",
  "key_observations": ["<obs 1>", "<obs 2>", ...]{macro_extra}
}}
"""

_MACRO_EXTRA_FIELD = (
    ',\n  "regime_sensitivity": "HIGH" | "MEDIUM" | "LOW"'
)


def _build_user_prompt(
    ticker: str,
    style_id: str,
    candidate_facts: str,
    lane_refs: str,
    scenarios: str,
    s0_regime_context: Optional[str],
) -> str:
    if style_id == STYLE_MACRO_REGIME:
        regime_block = (
            "S0 REGIME CONTEXT (you are the Macro-Regime agent — only YOU "
            "see this):\n"
            + (s0_regime_context or "<no S0 context provided>")
        )
        macro_extra = _MACRO_EXTRA_FIELD
    else:
        regime_block = (
            "S0 REGIME CONTEXT: <withheld — only Macro-Regime style sees S0>"
        )
        macro_extra = ""
    return _USER_TEMPLATE.format(
        ticker=ticker,
        candidate_facts=candidate_facts.strip(),
        lane_refs=(lane_refs or "<none>").strip(),
        scenarios=(scenarios or "<none>").strip(),
        regime_block=regime_block,
        macro_extra=macro_extra,
    )


# --------------------------------------------------------------------------- #
# Per-style runner                                                            #
# --------------------------------------------------------------------------- #


def _run_one_style(
    *,
    style_id: str,
    ticker: str,
    candidate_facts: str,
    lane_refs: str,
    scenarios: str,
    s0_regime_context: Optional[str],
    client: Any,
    model: str,
    temperature: float,
) -> PhaseAStyleOutput:
    persona = PERSONAS[style_id]
    user_prompt = _build_user_prompt(
        ticker=ticker,
        style_id=style_id,
        candidate_facts=candidate_facts,
        lane_refs=lane_refs,
        scenarios=scenarios,
        s0_regime_context=s0_regime_context,
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
        return PhaseAStyleOutput(
            style_id=style_id,
            preliminary_verdict=VERDICT_PASS,
            preliminary_rationale="malformed JSON; defaulted to PASS",
            key_observations=[],
            raw_text=raw,
            valid=False,
            invalid_reason="json parse failure",
            model=model,
        )
    verdict = str(parsed.get("preliminary_verdict", "")).upper()
    if verdict not in {"ADD", "WATCH", "PASS"}:
        return PhaseAStyleOutput(
            style_id=style_id,
            preliminary_verdict=VERDICT_PASS,
            preliminary_rationale="invalid verdict; defaulted to PASS",
            key_observations=[],
            raw_text=raw,
            valid=False,
            invalid_reason=f"invalid verdict: {verdict!r}",
            model=model,
        )
    obs_raw = parsed.get("key_observations", [])
    obs = [str(o) for o in obs_raw] if isinstance(obs_raw, list) else []
    rs = None
    if style_id == STYLE_MACRO_REGIME:
        rs_raw = str(parsed.get("regime_sensitivity", "")).upper()
        rs = rs_raw if rs_raw in {"HIGH", "MEDIUM", "LOW"} else "MEDIUM"
    return PhaseAStyleOutput(
        style_id=style_id,
        preliminary_verdict=verdict,
        preliminary_rationale=str(parsed.get("preliminary_rationale", "")),
        key_observations=obs,
        regime_sensitivity=rs,
        raw_text=raw,
        valid=True,
        model=model,
    )


def run_phase_a(
    *,
    ticker: str,
    candidate_facts: str,
    lane_refs: str = "",
    scenarios: str = "",
    s0_regime_context: Optional[str] = None,
    client: Any = None,
    model: str = MODEL_SONNET,
    temperature: float = 0.4,
    parallel: bool = True,
) -> PhaseAResult:
    """Run all 5 styles in (preferably) parallel, returning combined output.

    Args:
        ticker: The candidate name.
        candidate_facts: Verbatim facts block; the same string is supplied
            to every style (manufactured independence).
        lane_refs: L1 / L3 lane reference text (may be empty).
        scenarios: P2 scenario set serialized to text.
        s0_regime_context: S0 regime classification + BOCPD shift
            probability serialized to text. ONLY shown to ``macro_regime``.
        client: Optional pre-built ``anthropic.Anthropic`` client; if
            ``None`` we construct one from the environment.
        model: Anthropic model id; default Sonnet per Section 6 Q1.
        temperature: Sampling temperature; Phase A defaults to 0.4 to
            preserve genuine style divergence (per L8 finding 14).
        parallel: If True (default), the 5 styles run in a thread pool;
            if False, sequentially (useful for tests + deterministic
            replay).

    Returns:
        :class:`PhaseAResult` with one entry per style.
    """
    if client is None:
        client = build_default_client()

    result = PhaseAResult(ticker=ticker)

    def _runner(style_id: str) -> PhaseAStyleOutput:
        return _run_one_style(
            style_id=style_id,
            ticker=ticker,
            candidate_facts=candidate_facts,
            lane_refs=lane_refs,
            scenarios=scenarios,
            s0_regime_context=s0_regime_context,
            client=client,
            model=model,
            temperature=temperature,
        )

    if parallel:
        with ThreadPoolExecutor(max_workers=len(ALL_STYLES)) as ex:
            futures = {
                ex.submit(_runner, sid): sid for sid in ALL_STYLES
            }
            for fut in as_completed(futures):
                sid = futures[fut]
                try:
                    result.per_style[sid] = fut.result()
                except Exception as exc:  # noqa: BLE001 - catch-all by design
                    _LOG.exception(
                        "Phase A style %s failed: %s", sid, exc,
                    )
                    result.per_style[sid] = PhaseAStyleOutput(
                        style_id=sid,
                        preliminary_verdict=VERDICT_PASS,
                        preliminary_rationale=(
                            f"Phase A runner exception: {exc!r}; "
                            "defaulted to PASS"
                        ),
                        key_observations=[],
                        valid=False,
                        invalid_reason=f"runner exception: {exc!r}",
                        model=model,
                    )
    else:
        for sid in ALL_STYLES:
            result.per_style[sid] = _runner(sid)

    return result
