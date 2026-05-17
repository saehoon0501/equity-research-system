"""Quarterly per-name re-classification (Phase 4 Q5).

Per spec ``docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md``
Section 2.2 line 127::

    Per-name quarterly re-classification: runs Stage 1 against current
    data; mismatch with stored mode -> operator review + pre-mortem
    before reclassification

This module implements only the *Stage 1 mismatch detection* half of
the rule. The pre-mortem trigger is dispatched separately by another
subagent (out of scope per task description).

Behaviour:

* For each ticker we look up the latest ``mode_classifications`` row.
* If absent -> we run a fresh classification (the name is new on the
  watchlist).
* If present -> we run Stage 1 only against current data.
  - ``stage1.provisional_bin == stored.final_mode`` -> no-op (the
    state was already 'confirmed'); we DO NOT INSERT a duplicate row.
  - ``provisional_bin != stored.final_mode`` -> INSERT a *new* row
    with ``recheck_status='pending_review'`` and
    ``prior_classification_id`` chained back. The orchestrator and
    the operator workflow then decide whether to escalate to a full
    Stage 2 + 3 reclassification.
  - Stage 1 overlap detected -> insert a pending_review row with
    rule_outcomes captured for downstream tie-breaker.

We deliberately do NOT run Stage 2 or Stage 3 in the re-check path —
the mismatch alone is the trigger; full reclassification (which may
include the LLM tie-breaker) happens after operator sign-off.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Optional

from . import (
    METHOD_RULE,
    QUALITY_STANDARD,
    RECHECK_CONFIRMED,
    RECHECK_PENDING,
)
from .adapters import DataAdapter, DefaultDataAdapter
from .orchestrator import _dsn, classify_ticker
from .stage1_market_structural import classify as stage1_classify

_LOG = logging.getLogger(__name__)


@dataclass
class RecheckOutcome:
    """One ticker's recheck result."""

    ticker: str
    status: str  # 'no_prior' | 'confirmed' | 'mismatch_pending_review' | 'overlap_pending_review'
    stored_mode: Optional[str]
    current_provisional_bin: Optional[str]
    new_classification_id: Optional[uuid.UUID]
    detail: str


def recheck_ticker(
    ticker: str,
    *,
    as_of: Optional[str] = None,
    data_adapter: Optional[DataAdapter] = None,
    persist: bool = True,
) -> RecheckOutcome:
    """Run the Phase 4 Q5 quarterly recheck for one ticker.

    Args:
        ticker: Equity ticker.
        as_of: ISO date for the snapshot; defaults to today.
        data_adapter: Stage 1 facts adapter; defaults to
            :class:`DefaultDataAdapter`.
        persist: When True, write a ``pending_review`` row on mismatch.

    Returns:
        :class:`RecheckOutcome`.
    """
    ticker = ticker.upper().strip()
    # UTC date — ``date.today()`` reads server local tz; this value is fed
    # downstream as the snapshot day key.
    as_of = as_of or _dt.datetime.now(_dt.timezone.utc).date().isoformat()
    data_adapter = data_adapter or DefaultDataAdapter()

    prior = _fetch_latest_row(ticker)
    if prior is None:
        _LOG.info("Recheck: %s has no prior classification; classifying fresh.", ticker)
        outcome = classify_ticker(
            ticker, as_of=as_of, data_adapter=data_adapter, persist=persist
        )
        return RecheckOutcome(
            ticker=ticker,
            status="no_prior",
            stored_mode=None,
            current_provisional_bin=outcome.final_mode,
            new_classification_id=outcome.classification_id,
            detail="no prior row; ran full classify_ticker pipeline",
        )

    stored_mode = prior["final_mode"]
    facts = data_adapter.get_structural_facts(ticker, as_of)
    s1 = stage1_classify(facts)

    # Overlap path — ambiguous current data, flag for review.
    if s1.overlap_detected:
        cid: Optional[uuid.UUID] = None
        if persist:
            cid = _insert_pending(
                ticker=ticker,
                final_mode=stored_mode,  # carry forward stored mode
                quality_flag=prior["company_quality_flag"],
                rule_outcomes=s1.to_rule_outcomes(),
                prior_classification_id=prior["classification_id"],
            )
        return RecheckOutcome(
            ticker=ticker,
            status="overlap_pending_review",
            stored_mode=stored_mode,
            current_provisional_bin=None,
            new_classification_id=cid,
            detail="Stage 1 overlap; tie-breaker required at full reclassification",
        )

    # Clean Stage 1 result — compare to stored.
    provisional = s1.provisional_bin
    assert provisional is not None
    if provisional == stored_mode:
        return RecheckOutcome(
            ticker=ticker,
            status="confirmed",
            stored_mode=stored_mode,
            current_provisional_bin=provisional,
            new_classification_id=None,
            detail="Stage 1 matches stored mode",
        )

    # Mismatch — insert pending_review row.
    cid = None
    if persist:
        cid = _insert_pending(
            ticker=ticker,
            final_mode=stored_mode,
            quality_flag=prior["company_quality_flag"],
            rule_outcomes={
                **s1.to_rule_outcomes(),
                "stored_mode": stored_mode,
                "provisional_mode_now": provisional,
                "mismatch": True,
            },
            prior_classification_id=prior["classification_id"],
        )
    return RecheckOutcome(
        ticker=ticker,
        status="mismatch_pending_review",
        stored_mode=stored_mode,
        current_provisional_bin=provisional,
        new_classification_id=cid,
        detail=(
            f"Stage 1 says {provisional!r}; stored is {stored_mode!r}; "
            "operator review + pre-mortem required before reclassification"
        ),
    )


def recheck_all(
    *,
    as_of: Optional[str] = None,
    data_adapter: Optional[DataAdapter] = None,
    persist: bool = True,
) -> list[RecheckOutcome]:
    """Bulk-recheck every ticker present in ``mode_classifications``.

    Returns one :class:`RecheckOutcome` per distinct ticker.
    """
    tickers = _fetch_distinct_tickers()
    return [
        recheck_ticker(
            t, as_of=as_of, data_adapter=data_adapter, persist=persist
        )
        for t in tickers
    ]


# --------------------------------------------------------------------------- #
# DB helpers                                                                  #
# --------------------------------------------------------------------------- #


def _fetch_latest_row(ticker: str) -> Optional[dict]:
    import psycopg  # deferred

    with psycopg.connect(_dsn()) as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT classification_id, final_mode, company_quality_flag
                  FROM mode_classifications
                 WHERE ticker = %s
              ORDER BY classified_at DESC
                 LIMIT 1
                """,
                (ticker,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return {
                "classification_id": row[0],
                "final_mode": row[1],
                "company_quality_flag": row[2],
            }


def _fetch_distinct_tickers() -> list[str]:
    import psycopg  # deferred

    with psycopg.connect(_dsn()) as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT ticker FROM mode_classifications ORDER BY ticker"
            )
            return [r[0] for r in cur.fetchall()]


def _insert_pending(
    *,
    ticker: str,
    final_mode: str,
    quality_flag: str,
    rule_outcomes: dict,
    prior_classification_id: uuid.UUID,
) -> uuid.UUID:
    """Append a ``pending_review`` row chained to the prior classification.

    Note: ``final_mode`` is the **stored** mode — we are flagging a
    mismatch, not yet committing to a reclassification. Full re-class
    happens in a follow-up call to :func:`classify_ticker` once the
    operator and pre-mortem subagent have signed off.
    """
    import psycopg  # deferred

    cid = uuid.uuid4()
    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO mode_classifications (
                    classification_id, ticker, final_mode,
                    company_quality_flag, classification_method,
                    rule_outcomes, recheck_status, prior_classification_id,
                    classified_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    cid,
                    ticker,
                    final_mode,
                    quality_flag or QUALITY_STANDARD,
                    METHOD_RULE,
                    json.dumps(rule_outcomes, default=str),
                    RECHECK_PENDING,
                    prior_classification_id,
                    _dt.datetime.now(_dt.timezone.utc),
                ),
            )
        conn.commit()
    return cid


# Re-export for clarity.
__all__ = [
    "RecheckOutcome",
    "recheck_ticker",
    "recheck_all",
    "RECHECK_CONFIRMED",
    "RECHECK_PENDING",
]
