"""Resolve the slow-layer directional prior for /micro.

The prior is one of the canonical 4-bin codes (BUY/HOLD/TRIM/SELL) that the
signal model maps to a small intraday tilt. /micro looks for it in priority
order (most authoritative first):

  1. **PM Recommendation** — the structured pm-supervisor decision in
     ``execution_recommendations.recommendation`` (canonical), or its logged
     twin ``counterfactual_ledger.summary_code``.
  2. **PM report** (fallback) — when no structured row exists but a narrative
     pm-supervisor synthesis / CDD memo does (a JSON envelope or markdown
     report), parse the recommendation out of it deterministically.
  3. None → /micro runs prior-free.

Parsing the report here (not in LLM prose) keeps the BUY/HOLD/TRIM/SELL choice
deterministic and unit-testable; the command only supplies the raw text.
"""

from __future__ import annotations

import json
import re
from typing import Any

CANONICAL = ("BUY", "HOLD", "TRIM", "SELL")

# "recommendation: HOLD", "summary_code = SELL", "PM call — BUY", "## Recommendation: TRIM"
# Anchored to the start of a line (after optional markdown markers) with a
# MANDATORY separator, so a "...see recommendation - BUY below" mention buried
# mid-prose does NOT match — only a genuine labelled line like "## Recommendation: BUY".
_LABELLED = re.compile(
    r"^[ \t]*[#>*\-]*[ \t]*"
    r"(?:recommendation|summary[_\s]?code|pm[\s_]*(?:call|decision|rec)|decision)"
    r"\s*[:=—\-]\s*\*{0,2}\b(BUY|HOLD|TRIM|SELL)\b",
    re.IGNORECASE | re.MULTILINE,
)


def from_code(value: Any) -> str | None:
    """Normalize a structured recommendation/summary_code to a canonical bin."""
    if not value:
        return None
    code = str(value).strip().upper()
    return code if code in CANONICAL else None


def from_report(text: Any) -> str | None:
    """Extract a canonical recommendation from a PM report / envelope.

    Handles both a JSON envelope (looks for recommendation/summary_code/decision
    keys) and free markdown (a labelled "Recommendation: X" line is preferred
    over a bare token to avoid matching a BUY/SELL mention buried in prose).
    """
    if not text:
        return None
    if not isinstance(text, str):
        text = json.dumps(text)

    # JSON envelope path.
    stripped = text.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            obj = json.loads(stripped)
        except ValueError:
            obj = None
        if isinstance(obj, dict):
            for key in ("recommendation", "summary_code", "decision", "pm_recommendation"):
                hit = from_code(obj.get(key))
                if hit:
                    return hit
            # Parsed JSON object with no recognized key: trust the keys only —
            # do NOT regex-scan the raw JSON blob (a BUY/SELL mention inside some
            # narrative string field would be a false positive).
            return None

    # Non-JSON narrative text: labelled-line search (anchored, see _LABELLED).
    m = _LABELLED.search(text)
    if m:
        return m.group(1).upper()
    return None


def resolve(
    recommendation: Any = None,
    summary_code: Any = None,
    report_text: Any = None,
) -> dict[str, Any]:
    """Apply the PM-Recommendation → PM-report fallback chain.

    Returns {"summary_code": <code|None>, "source": <where it came from>}.
    ``source`` is one of: pm_recommendation, counterfactual_ledger, pm_report,
    none.
    """
    code = from_code(recommendation)
    if code:
        return {"summary_code": code, "source": "pm_recommendation"}
    code = from_code(summary_code)
    if code:
        return {"summary_code": code, "source": "counterfactual_ledger"}
    code = from_report(report_text)
    if code:
        return {"summary_code": code, "source": "pm_report"}
    return {"summary_code": None, "source": "none"}
