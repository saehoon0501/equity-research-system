"""Catalyst-scout sentiment-degradation re-computation (Bug 14 fix — 2026-05-16).

The catalyst-scout §4 sentiment-indicator sweep fetches 4 cross-section
indicators via WebFetch (BofA FMS, AAII, Investors Intelligence, NAAIM).
When a WebFetch fails (rate-limit, CAPTCHA, source down, UA-block),
the indicator is unavailable for that run. Historical case: MSFT
2026-05-15 had 3 of 4 sentiment indicators unavailable (AAII + II +
BofA FMS WebFetch timeouts), but ``tier_insufficient`` stayed False
because polygon data was healthy. The ±25% catalyst-modifier bound
applied at full width over half-blind sentiment data.

The fix surface: a separate ``sentiment_data_degraded`` boolean,
computed deterministically as ``count(unavailable indicators) >= 2``,
that triggers the same ±10% bound shrinkage as ``tier_insufficient``
(OR-ed, not AND-ed) in pm-supervisor §6.

This module re-computes the boolean from a catalyst-scout sentiment
block so the evaluator can validate the agent's emitted value matches
the deterministic ground truth.

DETERMINISM: pure Python; no I/O beyond CLI stdin/stdout.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Sequence

# Catalyst-scout §4 declares 4 named sentiment indicators. The boolean
# threshold is "≥2 of 4 unavailable → degraded=true."
EXPECTED_INDICATOR_COUNT = 4
DEGRADATION_THRESHOLD = 2

# Canonical names per catalyst-scout.md §4 output schema. Case-insensitive
# substring match for fuzzy tolerance (the agent may emit slight
# variations like "BofA FMS cash level" vs "BofA Global Fund Manager Survey").
EXPECTED_INDICATOR_NAMES: tuple[str, ...] = (
    "BofA FMS",
    "AAII",
    "Investors Intelligence",
    "NAAIM",
)


@dataclass
class SentimentDegradationResult:
    """Result envelope for sentiment-availability counting."""

    degraded: bool
    n_unavailable: int
    n_total_expected: int
    threshold: int
    unavailable_names: list[str] = field(default_factory=list)
    available_names: list[str] = field(default_factory=list)
    indicators_missing_from_emission: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _is_indicator_available(indicator_block: dict) -> bool:
    """Per-indicator availability check.

    An indicator block counts as AVAILABLE iff it has a non-null
    ``reading`` AND a non-null ``reading_date``. Any of the following
    flags the indicator as UNAVAILABLE:

    - missing or None ``reading``
    - missing or None ``reading_date``
    - explicit marker fields: ``error_class``, ``data_unavailable=true``,
      ``unavailable=true``, or ``fetch_failed=true``
    - ``implication == "data-unavailable"`` (string sentinel some agents emit)
    """
    if not isinstance(indicator_block, dict):
        return False

    if indicator_block.get("data_unavailable") is True:
        return False
    if indicator_block.get("unavailable") is True:
        return False
    if indicator_block.get("fetch_failed") is True:
        return False
    if indicator_block.get("error_class"):
        return False

    implication = indicator_block.get("implication")
    if isinstance(implication, str) and implication.lower() in {
        "data-unavailable",
        "data_unavailable",
        "unavailable",
    }:
        return False

    if indicator_block.get("reading") is None:
        return False
    if indicator_block.get("reading_date") is None:
        return False

    return True


def _canonical_indicator_name(name: str | None) -> str | None:
    """Return the canonical expected-name that ``name`` matches by
    case-insensitive substring, or None if no match.

    Tolerates variations like ``"BofA FMS cash level"`` matching
    ``"BofA FMS"`` and ``"AAII bull-bear spread"`` matching ``"AAII"``.
    """
    if not isinstance(name, str):
        return None
    n = name.lower()
    for expected in EXPECTED_INDICATOR_NAMES:
        if expected.lower() in n:
            return expected
    return None


def compute_sentiment_data_degraded(
    indicators: Sequence[dict],
) -> SentimentDegradationResult:
    """Re-compute ``sentiment_data_degraded`` from a catalyst-scout §4
    sentiment-indicator list.

    Rule: ``degraded = (n_unavailable >= 2)`` where n_unavailable counts
    BOTH (a) indicators present in the list but with unavailable data,
    AND (b) expected indicators entirely absent from the emission.

    Args:
        indicators: list of indicator block dicts per the catalyst-scout
            §4 output schema.

    Returns:
        SentimentDegradationResult with the boolean + counts + per-name
        breakdown for audit.
    """
    if not isinstance(indicators, (list, tuple)):
        return SentimentDegradationResult(
            degraded=True,
            n_unavailable=EXPECTED_INDICATOR_COUNT,
            n_total_expected=EXPECTED_INDICATOR_COUNT,
            threshold=DEGRADATION_THRESHOLD,
            indicators_missing_from_emission=list(EXPECTED_INDICATOR_NAMES),
            notes=[
                f"indicators must be a list; got {type(indicators).__name__}"
            ],
        )

    seen_canonical: set[str] = set()
    unavailable: list[str] = []
    available: list[str] = []

    for block in indicators:
        canon = _canonical_indicator_name(
            block.get("indicator") if isinstance(block, dict) else None
        )
        if canon is None:
            continue  # unknown indicator name — does not contribute either way
        seen_canonical.add(canon)
        if _is_indicator_available(block):
            available.append(canon)
        else:
            unavailable.append(canon)

    missing_from_emission = [
        n for n in EXPECTED_INDICATOR_NAMES if n not in seen_canonical
    ]
    # Indicators entirely missing from emission count as unavailable.
    n_unavailable = len(unavailable) + len(missing_from_emission)
    degraded = n_unavailable >= DEGRADATION_THRESHOLD

    return SentimentDegradationResult(
        degraded=degraded,
        n_unavailable=n_unavailable,
        n_total_expected=EXPECTED_INDICATOR_COUNT,
        threshold=DEGRADATION_THRESHOLD,
        unavailable_names=sorted(unavailable),
        available_names=sorted(available),
        indicators_missing_from_emission=missing_from_emission,
    )


def _result_to_dict(r: SentimentDegradationResult) -> dict:
    return {
        "degraded": r.degraded,
        "n_unavailable": r.n_unavailable,
        "n_total_expected": r.n_total_expected,
        "threshold": r.threshold,
        "unavailable_names": r.unavailable_names,
        "available_names": r.available_names,
        "indicators_missing_from_emission": r.indicators_missing_from_emission,
        "notes": r.notes,
    }


def _cli(argv: list[str] | None = None) -> int:
    """CLI wrapper. Accepts JSON via ``--indicators-json <path>`` or
    stdin (``--indicators-json -``); prints the deterministic result.

    Input format: either (a) a JSON array of indicator blocks, or
    (b) a JSON object with an ``indicators`` field whose value is the
    array. Both are accepted for caller convenience.

    Exit codes:
      0  computed successfully (regardless of degraded T/F)
      2  input unparseable or arguments invalid
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="sentiment_degradation",
        description=(
            "Re-compute catalyst-scout sentiment_data_degraded boolean "
            "from a §4 indicator list. Prints JSON result. Exit 0 on "
            "success, 2 on unparseable input."
        ),
    )
    parser.add_argument(
        "--indicators-json",
        required=True,
        help='path to indicators JSON, or "-" to read from stdin',
    )
    args = parser.parse_args(argv)

    try:
        if args.indicators_json == "-":
            raw = sys.stdin.read()
        else:
            with open(args.indicators_json, "r", encoding="utf-8") as f:
                raw = f.read()
        parsed = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"unable to read/parse indicators: {exc}\n")
        return 2

    # Accept both a bare list and a {"indicators": [...]} wrapper.
    if isinstance(parsed, list):
        indicators = parsed
    elif isinstance(parsed, dict) and isinstance(parsed.get("indicators"), list):
        indicators = parsed["indicators"]
    else:
        sys.stderr.write(
            "input must be a JSON array of indicator blocks OR an object "
            'with an "indicators" field of the same shape\n'
        )
        return 2

    result = compute_sentiment_data_degraded(indicators)
    sys.stdout.write(json.dumps(_result_to_dict(result), indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())


__all__ = [
    "SentimentDegradationResult",
    "compute_sentiment_data_degraded",
    "EXPECTED_INDICATOR_NAMES",
    "EXPECTED_INDICATOR_COUNT",
    "DEGRADATION_THRESHOLD",
]
