"""Layer 2 — Multi-source confirmation (v3 spec Section 4.5 Q6).

Mode-tuned multi-source confirmation that fires even on Mode C at 2× cut
threshold. Cut is blocked unless ALL three of:

    1. ≥2 INDEPENDENT kill-criteria fired. BOCPD-correlated triggers
       collapse to 1 (Section 4.5 Q6 lock — same regime-shift signal can
       fire multiple kills but counts as one).
    2. Verbatim primary-source confirmation in last evidence (10-K, earnings
       call transcript, regulatory filing, etc.) — not analyst commentary.
    3. Operator pre-mortem within last 30 days (queries `premortem` table
       per migration 012).

If any of the three is missing, cut is blocked; the operator must escalate
manually or wait for the missing condition to materialize.

Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
           Section 4.5 Q6 Layer 2,
           db/migrations/012_v3_premortem.sql (premortem table).
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional, Sequence


PREMORTEM_LOOKBACK_DAYS: int = 30


@dataclass(frozen=True)
class KillCriterionFire:
    """One kill-criterion fire event.

    Attributes:
        kill_id:                 Catalog id of the fired kill criterion.
        fired_at:                Timestamp of fire.
        bocpd_correlation_group: Optional group key shared by triggers that
                                 collapsed under the same BOCPD regime-shift
                                 detection. Triggers with the same group key
                                 count as ONE independent kill.
        verbatim_primary_quote:  Optional verbatim quote from a primary source
                                 (10-K, earnings call, regulatory). Counted
                                 toward the verbatim-primary-source check.
        primary_source_type:     Optional source-type tag — must be in
                                 PRIMARY_SOURCE_TYPES to count.
    """

    kill_id: str
    fired_at: _dt.datetime
    bocpd_correlation_group: str | None = None
    verbatim_primary_quote: str | None = None
    primary_source_type: str | None = None


PRIMARY_SOURCE_TYPES: frozenset[str] = frozenset({
    "10-K", "10-Q", "8-K", "S-1", "S-3", "DEF 14A",
    "earnings_call", "earnings_call_transcript",
    "regulatory_filing", "court_filing", "fda_filing",
})


@dataclass(frozen=True)
class MultiSourceStatus:
    """Outcome of the Layer 2 multi-source confirmation check.

    Attributes:
        independent_kill_count:  Number of independent kills (BOCPD-collapsed).
        verbatim_primary_source: True iff at least one fired kill carries a
                                 verbatim quote from a primary-source type.
        premortem_within_30d:    True iff a premortem row exists for this
                                 ticker with premortem_date within 30 days.
        all_satisfied:           True iff (kills>=2) AND verbatim AND premortem.
        cut_blocked_reason:      Human-readable reason string when not
                                 all_satisfied; empty string otherwise.
    """

    independent_kill_count: int
    verbatim_primary_source: bool
    premortem_within_30d: bool
    all_satisfied: bool
    cut_blocked_reason: str = ""


PremortemLookupFn = Callable[[str, _dt.datetime, int], bool]
"""Signature: (ticker, evaluated_at, lookback_days) -> True iff a premortem
row exists for `ticker` with premortem_date within the lookback window."""


def collapse_bocpd_correlated(
    fires: Sequence[KillCriterionFire],
) -> int:
    """Collapse BOCPD-correlated triggers to count INDEPENDENT kills only.

    Per Section 4.5 Q6: "BOCPD-correlated triggers collapse to 1". Two kills
    sharing a non-empty bocpd_correlation_group key count as one independent
    fire. Kills without a group key are independent on their own.
    """
    independent = 0
    seen_groups: set[str] = set()
    for f in fires:
        if f.bocpd_correlation_group:
            if f.bocpd_correlation_group not in seen_groups:
                seen_groups.add(f.bocpd_correlation_group)
                independent += 1
        else:
            independent += 1
    return independent


def has_verbatim_primary(fires: Iterable[KillCriterionFire]) -> bool:
    """True iff any fired kill carries a verbatim primary-source quote."""
    for f in fires:
        if (
            f.verbatim_primary_quote
            and f.primary_source_type
            and f.primary_source_type in PRIMARY_SOURCE_TYPES
        ):
            return True
    return False


def evaluate_multi_source(
    *,
    ticker: str,
    fires: Sequence[KillCriterionFire],
    premortem_lookup: PremortemLookupFn,
    evaluated_at: _dt.datetime | None = None,
    lookback_days: int = PREMORTEM_LOOKBACK_DAYS,
) -> MultiSourceStatus:
    """Run Layer 2 multi-source confirmation.

    Args:
        ticker:           Candidate ticker (used to query premortem table).
        fires:            Kill-criterion fire events for this peak-pain event.
        premortem_lookup: Callable returning True if a premortem row exists
                          within the lookback. Production wires this to
                          ``SELECT 1 FROM premortem WHERE ticker=$1 AND
                          premortem_date >= $2`` via mcp__postgres; tests pass
                          a stub.
        evaluated_at:     Evaluation timestamp (defaults to UTC now).
        lookback_days:    Pre-mortem lookback window (default 30 per Section 4.5).

    Returns:
        MultiSourceStatus.
    """
    now = evaluated_at or _dt.datetime.now(_dt.timezone.utc)
    independent = collapse_bocpd_correlated(fires)
    verbatim = has_verbatim_primary(fires)
    premortem_ok = bool(premortem_lookup(ticker, now, lookback_days))

    reasons: list[str] = []
    if independent < 2:
        reasons.append(
            f"only {independent} independent kill-criterion fire(s); need ≥2 (BOCPD-collapsed)"
        )
    if not verbatim:
        reasons.append("no verbatim primary-source quote among fired kills")
    if not premortem_ok:
        reasons.append(f"no operator pre-mortem within last {lookback_days} days")

    all_satisfied = (independent >= 2) and verbatim and premortem_ok
    return MultiSourceStatus(
        independent_kill_count=independent,
        verbatim_primary_source=verbatim,
        premortem_within_30d=premortem_ok,
        all_satisfied=all_satisfied,
        cut_blocked_reason="; ".join(reasons),
    )
