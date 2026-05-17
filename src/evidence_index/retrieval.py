"""Deterministic evidence selection for /research-company runs (drift-fix Phase 2 Step 6 — 2026-05-17).

Addresses the CRWD v1→v2 same-day rerun drift class: pre-fix, the LLM picked
which evidence refs to cite per-run (6 refs in v1, 14 refs in v2 — including
a $1.24B FCF claim that v1 missed entirely). This module replaces LLM-elective
inclusion with a deterministic SQL retrieval that returns the canonical
evidence refs for a given (run_id, tier).

The HLM-elective-inclusion failure mode lives in two places:
  1. WHICH evidence rows get cited (drift class addressed here)
  2. WHAT order they appear in (already deterministic via PK ordering)

This module returns a stable ordered list; pm-supervisor + cdd-lead consume
it verbatim into `evidence_index_refs` instead of choosing the citation set.

Evaluator HG-32 verifies that the emitted `evidence_index_refs` array equals
the function's return for the run's (run_id, tier) tuple.

Tier minimum-count rules (per drift-fix Phase 2 Step 6 spec):
  - core_fundamental: ≥ 30 refs required
  - thematic_growth:  ≥ 25 refs required
  - speculative_optionality: ≥ 15 refs required

Materiality verification: substituted as `source_quality_tier IN (1, 2)`
(primary regulatory + company IR) because the evidence_index schema (migration
001) does not carry a separate `materiality_verified` boolean — the source-
quality tier is the canonical primary-source signal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence


# Minimum evidence-ref counts per tier. Below these floors, the run is
# under-cited and HG-32 will reject. Authored per Phase 2 Step 6 plan.
TIER_MIN_EVIDENCE_COUNT: dict[str, int] = {
    "core_fundamental": 30,
    "thematic_growth": 25,
    "speculative_optionality": 15,
}

# Materiality thresholds for source-verification gate (USD).
# Numeric claims exceeding these thresholds in their materiality_usd field
# (when present) require source_quality_tier = 1 (primary regulatory).
MATERIALITY_THRESHOLD_USD: dict[str, float] = {
    "core_fundamental": 100_000_000.0,   # $100M
    "thematic_growth": 100_000_000.0,
    "speculative_optionality": 50_000_000.0,
}

# Schema version stamp for evaluator HG-32 grandfathering.
EVIDENCE_RETRIEVAL_SCHEMA_VERSION = "v1-2026-05-17"


@dataclass
class EvidenceRef:
    """A canonical evidence_index row materialised for retrieval.

    The fields mirror evidence_index columns (migration 001) plus a
    derived ``materiality_verified`` boolean = `source_quality_tier IN (1,2)`.
    """

    evidence_id: str
    agent_id: str
    agent_run_id: str
    claim_text: str
    claim_type: str
    source_uri: str
    source_date: str
    source_quality_tier: int
    surfaced_date: str
    created_at: str

    @property
    def materiality_verified(self) -> bool:
        """Primary-source-verified = source_quality_tier ≤ 2 (regulatory / IR)."""
        return self.source_quality_tier in (1, 2)


QueryFn = Callable[[str, tuple[Any, ...]], Sequence[dict[str, Any]]]
"""Signature for the DB-execute hook. Production wires this to mcp__postgres__query."""


def retrieve_tier_evidence(
    run_id: str,
    tier: str,
    query_fn: QueryFn,
) -> list[EvidenceRef]:
    """Deterministic evidence selection for a /research-company run.

    Returns ALL primary-source-verified evidence rows from `evidence_index`
    associated with the given `agent_run_id`, ordered deterministically:

        ORDER BY source_quality_tier ASC,    -- tier 1 (primary) before tier 2 (IR)
                 source_date DESC,            -- newer first within tier
                 evidence_id ASC              -- terminal tiebreaker (PK uniqueness)

    The triple-key ordering is total — no two rows can tie on all three —
    so the returned list is reproducible across re-runs on the same DB state.

    Args:
        run_id: the /research-company agent_run_id (UUID string).
        tier: cdd-lead.tier — affects min-count enforcement downstream.
        query_fn: DB-execute hook.

    Returns:
        Ordered list of EvidenceRef. May be empty (caller checks against
        TIER_MIN_EVIDENCE_COUNT[tier]).

    Raises:
        ValueError on unknown tier.
    """
    if tier not in TIER_MIN_EVIDENCE_COUNT:
        raise ValueError(
            f"unknown tier '{tier}'; must be one of {list(TIER_MIN_EVIDENCE_COUNT)}"
        )

    sql = (
        "SELECT evidence_id, agent_id, agent_run_id, claim_text, "
        "claim_type, source_uri, source_date, source_quality_tier, "
        "surfaced_date, created_at "
        "FROM evidence_index "
        "WHERE agent_run_id = %s "
        # Primary-source-verified = quality_tier ≤ 2 (regulatory + company IR).
        # source_quality_tier = 3 (sell-side) and 4 (retail/blog) are excluded
        # from the canonical citation set even when present in the index;
        # those rows can still be referenced inline in memo prose but do not
        # count toward the canonical evidence_index_refs[] array.
        "AND source_quality_tier IN (1, 2) "
        # Deterministic ordering — see module docstring for rationale.
        "ORDER BY source_quality_tier ASC, source_date DESC, evidence_id ASC"
    )

    rows = query_fn(sql, (run_id,))

    return [
        EvidenceRef(
            evidence_id=str(r["evidence_id"]),
            agent_id=r["agent_id"],
            agent_run_id=str(r["agent_run_id"]),
            claim_text=r["claim_text"],
            claim_type=r["claim_type"],
            source_uri=r["source_uri"],
            source_date=str(r["source_date"]),
            source_quality_tier=int(r["source_quality_tier"]),
            surfaced_date=str(r["surfaced_date"]),
            created_at=str(r["created_at"]),
        )
        for r in rows
    ]


def check_min_count(refs: Sequence[EvidenceRef], tier: str) -> tuple[bool, str]:
    """Verify the retrieved evidence count meets the tier minimum.

    Returns (passes, audit_line). audit_line carries the count + threshold
    for the evaluator HG-32 audit chain.
    """
    if tier not in TIER_MIN_EVIDENCE_COUNT:
        raise ValueError(
            f"unknown tier '{tier}'; must be one of {list(TIER_MIN_EVIDENCE_COUNT)}"
        )
    threshold = TIER_MIN_EVIDENCE_COUNT[tier]
    n = len(refs)
    if n < threshold:
        return False, (
            f"evidence under-cited: tier={tier} required ≥{threshold} "
            f"primary-source-verified refs; found {n}"
        )
    return True, f"evidence count ok: {n} ≥ {threshold} for tier={tier}"


def check_materiality_verification(
    materiality_claims: Sequence[dict],
    refs: Sequence[EvidenceRef],
    tier: str,
) -> tuple[bool, str]:
    """Verify numeric claims above materiality threshold have tier-1 sources.

    Addresses the CRWD v1→v2 failure mode where a $1.24B FCF claim was cited
    without primary-source verification. Numeric claims with magnitude above
    MATERIALITY_THRESHOLD_USD[tier] MUST cite at least one evidence_ref with
    source_quality_tier == 1.

    Args:
        materiality_claims: list of {"claim_text", "magnitude_usd",
            "cited_evidence_ids"} from the memo's load-bearing-claims section.
        refs: the canonical evidence_index_refs returned by retrieve_tier_evidence.
        tier: cdd-lead.tier.

    Returns:
        (passes, audit_line).
    """
    if tier not in MATERIALITY_THRESHOLD_USD:
        raise ValueError(f"unknown tier '{tier}'")
    threshold = MATERIALITY_THRESHOLD_USD[tier]

    refs_by_id = {r.evidence_id: r for r in refs}

    failures: list[str] = []
    for claim in materiality_claims:
        try:
            mag = float(claim.get("magnitude_usd", 0.0))
        except (TypeError, ValueError):
            continue
        if mag < threshold:
            continue
        cited = claim.get("cited_evidence_ids", []) or []
        has_tier_1 = any(
            (refs_by_id.get(eid) is not None
             and refs_by_id[eid].source_quality_tier == 1)
            for eid in cited
        )
        if not has_tier_1:
            failures.append(
                f"claim '{claim.get('claim_text', '<unnamed>')[:60]}' "
                f"(magnitude=${mag:,.0f}) cited evidence {cited} but none "
                f"has source_quality_tier=1 (primary regulatory)"
            )

    if failures:
        return False, "materiality verification failed: " + "; ".join(failures)
    return True, f"materiality verification ok: all claims above ${threshold:,.0f} have tier-1 source"


__all__ = [
    "TIER_MIN_EVIDENCE_COUNT",
    "MATERIALITY_THRESHOLD_USD",
    "EVIDENCE_RETRIEVAL_SCHEMA_VERSION",
    "EvidenceRef",
    "retrieve_tier_evidence",
    "check_min_count",
    "check_materiality_verification",
]
