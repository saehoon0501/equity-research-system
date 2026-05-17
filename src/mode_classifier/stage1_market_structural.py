"""Stage 1 — Market-structural mode classifier.

Implements the original Section 1 Item 1 mechanical rule (verbatim from
``docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md``
Section 2.2 lines 106-109)::

    IF market_cap > $50B AND vol < 25% AND profitable >5y AND growth < 12% -> bin: B
    IF market_cap > $50B AND profitable AND (vol > 25% OR growth > 15%)    -> bin: B'
    IF market_cap < $50B OR not_yet_profitable OR narrative-driven          -> bin: C

The function is *pure*: it takes :class:`StructuralFacts` (no MCP I/O) and
returns a :class:`Stage1Result` capturing each rule's match boolean plus
the overlap detector. The orchestrator hands control to Stage 3
(LLM tie-breaker) when ``overlap_detected`` is True or no rule matches.

Edge cases handled deterministically:

* Any required input is ``None`` → that rule cannot evaluate and is
  treated as ``False`` for that rule's match. If *no* rule matches,
  ``overlap_detected`` is True (forces tie-breaker).
* The B and B' rules are not mutually exclusive on cap/profit/vol —
  e.g., a $60B firm with 10% growth and 26% vol matches B' (vol>25%)
  and partially matches B until you hit the vol clause; the rule text
  uses strict inequalities, so the predicate is well-defined. We
  flag overlap when more than one rule's predicate evaluates True.
* Narrative-driven flag is an unconditional C-bin trigger.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from . import MODE_B, MODE_B_PRIME, MODE_C
from .adapters import StructuralFacts


# Spec-fixed thresholds — Section 1 Item 1 / Section 2.2.
MARKET_CAP_THRESHOLD_USD: float = 50_000_000_000.0  # $50B
VOL_B_CEILING: float = 0.25                          # < 25%
VOL_BPRIME_FLOOR: float = 0.25                       # > 25%
PROFITABLE_YEARS_B_MIN: int = 5                      # > 5y
GROWTH_B_CEILING: float = 0.12                       # < 12%
GROWTH_BPRIME_FLOOR: float = 0.15                    # > 15%


@dataclass(frozen=True)
class Stage1Result:
    """Output of the mechanical classifier.

    Attributes:
        b_match: Stage 1 B rule predicate evaluated True.
        b_prime_match: Stage 1 B' rule predicate evaluated True.
        c_match: Stage 1 C rule predicate evaluated True.
        overlap_detected: ``True`` iff more than one rule matched OR
            no rule matched. When True, the orchestrator hands off to
            Stage 3 (LLM tie-breaker per Section 2.2 line 116).
        provisional_bin: The single-rule winner (B / B_prime / C) when
            overlap is False; ``None`` when overlap is True. The DB
            ``mode_classifications.final_mode`` is filled from this
            (or from Stage 3 output) by the orchestrator.
        facts_snapshot: The :class:`StructuralFacts` we evaluated against
            (recorded into ``rule_outcomes`` for audit).
    """

    b_match: bool
    b_prime_match: bool
    c_match: bool
    overlap_detected: bool
    provisional_bin: str | None
    facts_snapshot: StructuralFacts

    def to_rule_outcomes(self) -> dict:
        """Serialize for ``mode_classifications.rule_outcomes`` JSONB.

        Schema matches the migration's documented payload comment:
            { B_match, B_prime_match, C_match, overlap_detected, ... }
        """
        return {
            "B_match": self.b_match,
            "B_prime_match": self.b_prime_match,
            "C_match": self.c_match,
            "overlap_detected": self.overlap_detected,
            "provisional_bin": self.provisional_bin,
            "facts": asdict(self.facts_snapshot),
            "thresholds": {
                "market_cap_usd": MARKET_CAP_THRESHOLD_USD,
                "vol_b_ceiling": VOL_B_CEILING,
                "vol_bprime_floor": VOL_BPRIME_FLOOR,
                "profitable_years_b_min": PROFITABLE_YEARS_B_MIN,
                "growth_b_ceiling": GROWTH_B_CEILING,
                "growth_bprime_floor": GROWTH_BPRIME_FLOOR,
            },
        }


def _eval_b(f: StructuralFacts) -> bool:
    """B rule: cap>$50B AND vol<25% AND profitable>5y AND growth<12%."""
    if (
        f.market_cap_usd is None
        or f.realized_vol_252d is None
        or f.profitable_consecutive_years is None
        or f.revenue_growth_yoy is None
    ):
        return False
    return (
        f.market_cap_usd > MARKET_CAP_THRESHOLD_USD
        and f.realized_vol_252d < VOL_B_CEILING
        and f.profitable_consecutive_years > PROFITABLE_YEARS_B_MIN
        and f.revenue_growth_yoy < GROWTH_B_CEILING
    )


def _eval_b_prime(f: StructuralFacts) -> bool:
    """B' rule: cap>$50B AND profitable AND (vol>25% OR growth>15%)."""
    if (
        f.market_cap_usd is None
        or f.profitable_consecutive_years is None
    ):
        return False
    if f.market_cap_usd <= MARKET_CAP_THRESHOLD_USD:
        return False
    if f.profitable_consecutive_years <= 0:
        return False
    vol_high = (
        f.realized_vol_252d is not None
        and f.realized_vol_252d > VOL_BPRIME_FLOOR
    )
    growth_high = (
        f.revenue_growth_yoy is not None
        and f.revenue_growth_yoy > GROWTH_BPRIME_FLOOR
    )
    return vol_high or growth_high


def _eval_c(f: StructuralFacts) -> bool:
    """C rule: cap<$50B OR not-yet-profitable OR narrative-driven."""
    if f.narrative_driven:
        return True
    if (
        f.profitable_consecutive_years is not None
        and f.profitable_consecutive_years <= 0
    ):
        return True
    if (
        f.market_cap_usd is not None
        and f.market_cap_usd < MARKET_CAP_THRESHOLD_USD
    ):
        return True
    return False


def classify(facts: StructuralFacts) -> Stage1Result:
    """Run the Section 1 Item 1 rule and return a :class:`Stage1Result`.

    Per spec Section 2.2 line 106-109. Overlap is detected when more
    than one rule fires (e.g. a name on the boundary of B and B') or
    when no rule fires (data missing). The orchestrator routes
    overlapping cases to Stage 3.
    """
    b = _eval_b(facts)
    bp = _eval_b_prime(facts)
    c = _eval_c(facts)
    fired = [m for m, f in ((MODE_B, b), (MODE_B_PRIME, bp), (MODE_C, c)) if f]
    if len(fired) == 1:
        return Stage1Result(b, bp, c, False, fired[0], facts)
    # 0 or 2+ fired → overlap path; provisional_bin is None.
    return Stage1Result(b, bp, c, True, None, facts)
