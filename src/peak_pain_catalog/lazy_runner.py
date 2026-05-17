"""Lazy validation for the tail (~115 non-priority cases).

Per Phase 4 Q3 lazy-validation strategy: tail cases stay in catalog with
single-subagent-pass annotations marked `validation_status='pending'`. The
**first time** a tail case appears in active retrieval (any watchlist name
retrieves it in top-N), we run the 3-LLM consensus pipeline on that case
before its retrieval result is committed to veto evaluation.

Mechanics:
    - If consensus passes (HIGH on all features) → case promotes to
      `validation_status='validated'`; retrieval proceeds.
    - If consensus surfaces material disagreement → case flagged for operator
      review; retrieval falls back to top-N excluding this case for the
      current event; case enters validation queue.

This module exposes `validate_on_first_retrieval(case_id, ...)`, intended to
be called by the counterfactual VETO retrieval subagent (separate Wave C work)
when a candidate case has `validation_status='pending'` at retrieval time.

Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
           Phase 4 Q3 (lazy validation for tail) + Section 5 Q4 (event-driven
           mechanics).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

from src.peak_pain_catalog.consensus import ConsensusResult, run_consensus
from src.peak_pain_catalog.extractor import (
    AnthropicClient,
    get_anthropic_client_from_env,
)
from src.peak_pain_catalog.parser import parse_catalog
from src.peak_pain_catalog.persistence import (
    PersistencePayload,
    write_validated_case,
)


_LOG = logging.getLogger(__name__)


LazyOutcome = Literal["promoted_to_validated", "promoted_to_pending", "disputed"]


@dataclass(frozen=True)
class LazyValidationResult:
    """Outcome of a lazy validation pass.

    Attributes:
        case_id:           The validated case.
        outcome:           promoted_to_validated / promoted_to_pending /
                           disputed (matches the validation_status the case is
                           now stamped with).
        consensus:         Full ConsensusResult for audit chain.
        payload:           PersistencePayload that was written / dry-run.
        retrieval_safe:    True iff the case is safe to include in the current
                           retrieval (validated). False → caller drops the
                           case from current top-N and queues it for review.
    """

    case_id: str
    outcome: LazyOutcome
    consensus: ConsensusResult
    payload: PersistencePayload
    retrieval_safe: bool


def validate_on_first_retrieval(
    case_id: str,
    *,
    catalog_md_path: str | Path,
    client: Optional[AnthropicClient] = None,
    dsn: Optional[str] = None,
) -> LazyValidationResult:
    """Validate a tail case on its first retrieval-time hit.

    Args:
        case_id:         The catalog case_id (e.g. 'TWLO-2022') being
                         retrieved.
        catalog_md_path: Path to catalog-v0.1.md.
        client:          Anthropic client (or test stub).
        dsn:             Postgres DSN, or None for dry-run.

    Returns:
        LazyValidationResult containing the new validation_status and a
        retrieval_safe flag.

    Raises:
        KeyError if case_id is not in the parsed catalog.
    """
    cases = parse_catalog(catalog_md_path)
    by_case_id = {c.case_id: c for c in cases}
    if case_id not in by_case_id:
        raise KeyError(f"case_id {case_id!r} not present in catalog")

    case = by_case_id[case_id]
    if client is None:
        # Subscription-auth (Claude Code OAuth) when no API key set;
        # API-key path when ANTHROPIC_API_KEY is explicitly present.
        # Per BUILD_LOG decision 1, the project does NOT carry an API key.
        import os
        if os.environ.get("ANTHROPIC_API_KEY"):
            client = get_anthropic_client_from_env()
        else:
            from src.peak_pain_catalog.claude_sdk_client import get_claude_sdk_client
            client = get_claude_sdk_client()

    _LOG.info(
        "Lazy validation triggered for tail case %s (sector=%s, era=%s)",
        case_id,
        case.sector,
        case.era_category,
    )
    consensus = run_consensus(case, client=client)
    payload = write_validated_case(case, consensus, dsn=dsn)

    if consensus.validation_status == "validated":
        return LazyValidationResult(
            case_id=case_id,
            outcome="promoted_to_validated",
            consensus=consensus,
            payload=payload,
            retrieval_safe=True,
        )
    if consensus.validation_status == "pending":
        # LOW on at least one universal-core feature — still in catalog but
        # operator-review-pending. Per Phase 4 Q3, fall back: drop from
        # current retrieval to avoid load-bearing on shaky data.
        return LazyValidationResult(
            case_id=case_id,
            outcome="promoted_to_pending",
            consensus=consensus,
            payload=payload,
            retrieval_safe=False,
        )
    # disputed
    return LazyValidationResult(
        case_id=case_id,
        outcome="disputed",
        consensus=consensus,
        payload=payload,
        retrieval_safe=False,
    )


__all__ = [
    "LazyOutcome",
    "LazyValidationResult",
    "validate_on_first_retrieval",
]
