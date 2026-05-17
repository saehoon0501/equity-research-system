"""Channel 1 — Pillar drift (LLM-diff of original vs current pillars).

Per spec ``docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md``
Section 4.5 Q5 line 532::

    1. Pillar drift (diff-based): P3 lock writes immutable
       thesis_pillars_original (HMAC-signed); on every M-2 / M-3 event,
       LLM diffs current vs original; trigger if drift score > 0.25

Drift score formula (per spec):

    drift_score =
        (sum(|confidence_delta|) + count(softened) + count(rewritten))
        / total_pillars

LLM role: structured diff (NOT contestable judgment) -> Sonnet, JSON output.
Trigger threshold: > 0.25 (strictly greater).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional

from . import CHANNEL_1_LLM_MODEL, PILLAR_DRIFT_THRESHOLD
from .hmac_verify import verify_pillars_hmac

_LOG = logging.getLogger(__name__)


@dataclass
class PillarDriftResult:
    """One name's Channel 1 result.

    ``payload`` matches the JSONB shape documented in
    ``010_v3_drift_detection.sql`` for ``channel_1_pillar_drift``.
    """

    triggered: bool
    drift_score: float
    pillars_softened: list[str] = field(default_factory=list)
    pillars_rewritten: list[str] = field(default_factory=list)
    diff_llm_model: str = CHANNEL_1_LLM_MODEL
    hmac_verified: bool = True
    error: Optional[str] = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "drift_score": float(self.drift_score),
            "pillars_softened": list(self.pillars_softened),
            "pillars_rewritten": list(self.pillars_rewritten),
            "diff_llm_model": self.diff_llm_model,
            "hmac_verified": bool(self.hmac_verified),
            "triggered": bool(self.triggered),
            "error": self.error,
        }


_DIFF_PROMPT = """You are a structured diff engine for an equity-research thesis. \
You must output ONLY valid JSON, no prose, no markdown fences.

Input:
ORIGINAL_PILLARS = {original}
CURRENT_PILLARS = {current}

Each pillar object has the shape:
{{
  "pillar": "<short label>",
  "claim": "<full text>",
  "confidence": <number in [0,1]>
}}

For each ORIGINAL pillar, locate the corresponding CURRENT pillar (match
on `pillar` label; substring fallback). Classify each pair as:
  - "unchanged"  : claim wording substantively identical, confidence delta < 0.05
  - "softened"   : same claim direction but weaker language OR confidence dropped >= 0.05
  - "rewritten"  : claim text materially altered (different mechanism, scope, or numbers)
  - "removed"    : no corresponding current pillar (treat as rewritten)

Output JSON shape:
{{
  "pairs": [
    {{
      "pillar": "<label>",
      "classification": "unchanged" | "softened" | "rewritten" | "removed",
      "confidence_delta": <signed number, current_confidence - original_confidence;
                          0 if removed>
    }},
    ...
  ]
}}
"""


def _call_llm_diff(
    original_pillars: Any,
    current_pillars: Any,
    *,
    client: Any | None = None,
) -> dict[str, Any]:
    """Call Claude Sonnet for the structured diff. Returns parsed JSON.

    A ``client`` may be injected for tests (any object with a
    ``messages.create`` returning the SDK's standard response shape).
    Returns ``{}`` on transport / parse failure (caller treats as no-drift).
    """
    if client is None:
        try:
            import anthropic  # deferred
        except ImportError:
            _LOG.warning("anthropic SDK not installed; skipping LLM diff")
            return {}
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            _LOG.warning("ANTHROPIC_API_KEY not set; skipping LLM diff")
            return {}
        client = anthropic.Anthropic(api_key=api_key)

    prompt = _DIFF_PROMPT.format(
        original=json.dumps(original_pillars, ensure_ascii=False),
        current=json.dumps(current_pillars, ensure_ascii=False),
    )
    try:
        resp = client.messages.create(
            model=CHANNEL_1_LLM_MODEL,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(
            getattr(b, "text", "") for b in getattr(resp, "content", [])
        ).strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
        return json.loads(text)
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.exception("LLM diff failure: %s", exc)
        return {}


def _drift_score(pairs: list[dict[str, Any]], total: int) -> tuple[
    float, list[str], list[str]
]:
    """Compute the spec drift score and bucket lists.

    drift_score = (sum |confidence_delta| + softened_count + rewritten_count)
                  / total
    """
    if total <= 0:
        return 0.0, [], []
    softened: list[str] = []
    rewritten: list[str] = []
    abs_delta_sum = 0.0
    for pair in pairs:
        cls = (pair.get("classification") or "").lower()
        label = pair.get("pillar") or ""
        try:
            cd = float(pair.get("confidence_delta") or 0.0)
        except (TypeError, ValueError):
            cd = 0.0
        abs_delta_sum += abs(cd)
        if cls == "softened":
            softened.append(label)
        elif cls in ("rewritten", "removed"):
            rewritten.append(label)
    score = (abs_delta_sum + len(softened) + len(rewritten)) / float(total)
    return score, softened, rewritten


def detect_pillar_drift(
    *,
    ticker: str,
    thesis_pillars_original: Any,
    thesis_pillars_original_hmac: str,
    current_pillars: Any,
    client: Any | None = None,
) -> PillarDriftResult:
    """Run Channel 1 pillar-drift detection for one ticker.

    Args:
        ticker: equity ticker (for logging).
        thesis_pillars_original: P5 lock pillars (JSONB list-of-dicts).
        thesis_pillars_original_hmac: HMAC accompanying the original.
        current_pillars: live operating thesis pillars.
        client: optional Anthropic SDK client (injected in tests).

    Returns:
        PillarDriftResult with ``triggered`` true when drift > 0.25 or
        when HMAC verification fails (tampering treated as drift).
    """
    ticker = ticker.upper().strip()

    hmac_ok = verify_pillars_hmac(
        thesis_pillars_original, thesis_pillars_original_hmac
    )
    if not hmac_ok:
        _LOG.error("HMAC mismatch on thesis_pillars_original for %s", ticker)
        return PillarDriftResult(
            triggered=True,
            drift_score=1.0,
            pillars_softened=[],
            pillars_rewritten=[],
            hmac_verified=False,
            error="hmac_mismatch_or_tamper",
        )

    if not isinstance(thesis_pillars_original, list) or not thesis_pillars_original:
        return PillarDriftResult(
            triggered=False,
            drift_score=0.0,
            error="no_original_pillars",
        )

    diff = _call_llm_diff(thesis_pillars_original, current_pillars, client=client)
    pairs = diff.get("pairs", []) if isinstance(diff, dict) else []
    score, softened, rewritten = _drift_score(pairs, len(thesis_pillars_original))
    triggered = score > PILLAR_DRIFT_THRESHOLD
    return PillarDriftResult(
        triggered=triggered,
        drift_score=score,
        pillars_softened=softened,
        pillars_rewritten=rewritten,
        hmac_verified=True,
    )


__all__ = ["PillarDriftResult", "detect_pillar_drift"]
