"""Orchestrator — runs Stage 1 -> Stage 2 -> (Stage 3) and persists.

Per spec ``docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md``
Section 2.2 lines 95-130 and migration ``008_v3_recommendations.sql``
table ``mode_classifications``.

Pipeline::

    facts (DataAdapter)
        -> Stage 1 mechanical rule
            -> if no overlap: bin = stage1.provisional_bin, method = "rule"
            -> if overlap:    bin = stage3.tiebreaker(...), method = "llm_tiebreaker"
        -> Stage 2 quality refinement on the chosen bin
        -> persist row to mode_classifications

The orchestrator's responsibilities:

* Compose the data adapters and run the three stages in order.
* Format the rule_outcomes / llm_tiebreaker JSONB payloads to match
  the migration's documented shape.
* Honour the table's append-only contract:
  - Always INSERT a new row (never UPDATE).
  - When this is a re-classification (i.e. a prior row exists),
    set ``prior_classification_id`` to chain the audit.
* Tolerate the absence of an Anthropic key during Stage 3: when
  :class:`stage3.LLMUnavailableError` fires we record a *rule-only*
  result with ``recheck_status='pending_review'`` and a structured
  invalid_reason payload — the operator/Claude Code subagent can
  re-run the tie-breaker with a real client later.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import uuid
from dataclasses import dataclass
from typing import Optional

from . import (
    METHOD_LLM,
    METHOD_RULE,
    MODE_C,
    QUALITY_STANDARD,
    RECHECK_CONFIRMED,
    RECHECK_PENDING,
)
from .adapters import (
    DataAdapter,
    DefaultDataAdapter,
    DefaultQualityAdapter,
    QualityAdapter,
    StructuralFacts,
)
from .stage1_market_structural import Stage1Result, classify as stage1_classify
from .stage2_company_quality import Stage2Result, classify as stage2_classify
from .stage3_overlap_tiebreaker import (
    LLMUnavailableError,
    TiebreakerResult,
    tiebreaker as stage3_tiebreaker,
)

_LOG = logging.getLogger(__name__)


@dataclass
class ClassificationOutcome:
    """End-to-end classifier output, ready for persistence."""

    classification_id: uuid.UUID
    ticker: str
    final_mode: str
    company_quality_flag: str
    classification_method: str
    rule_outcomes: dict
    llm_tiebreaker: Optional[dict]
    recheck_status: str
    prior_classification_id: Optional[uuid.UUID]
    parameters_version: Optional[uuid.UUID]
    classified_at: _dt.datetime
    stage1: Stage1Result
    stage2: Stage2Result
    stage3: Optional[TiebreakerResult]


# --------------------------------------------------------------------------- #
# DSN helper (mirrors src/mcp/postgres/server.py)                             #
# --------------------------------------------------------------------------- #


def _dsn() -> str:
    return (
        f"postgresql://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}"
        f"@{os.environ.get('POSTGRES_HOST', '127.0.0.1')}:"
        f"{os.environ.get('POSTGRES_PORT', '5432')}"
        f"/{os.environ['POSTGRES_DB']}"
    )


# --------------------------------------------------------------------------- #
# Construct evidence block for Stage 3                                        #
# --------------------------------------------------------------------------- #


def _build_evidence_block(facts: StructuralFacts) -> str:
    """Plain-text evidence the LLM is allowed to quote from."""
    lines = [
        f"ticker_as_of_date: {facts.as_of_date}",
        f"market_cap_usd: {facts.market_cap_usd}",
        f"realized_vol_252d: {facts.realized_vol_252d}",
        f"profitable_consecutive_years: {facts.profitable_consecutive_years}",
        f"revenue_growth_yoy: {facts.revenue_growth_yoy}",
        f"narrative_driven: {facts.narrative_driven}",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Public API                                                                  #
# --------------------------------------------------------------------------- #


def classify_ticker(
    ticker: str,
    as_of: Optional[str] = None,
    *,
    data_adapter: Optional[DataAdapter] = None,
    quality_adapter: Optional[QualityAdapter] = None,
    high_stakes: bool = False,
    parameters_version: Optional[uuid.UUID] = None,
    prior_classification_id: Optional[uuid.UUID] = None,
    persist: bool = True,
    llm_client: object = None,
) -> ClassificationOutcome:
    """End-to-end classify a single ticker and (optionally) persist.

    Args:
        ticker: Equity ticker.
        as_of: ISO date for the snapshot. Defaults to today (UTC).
        data_adapter: Stage 1 facts adapter; defaults to
            :class:`DefaultDataAdapter`.
        quality_adapter: Stage 2 facts adapter; defaults to
            :class:`DefaultQualityAdapter`.
        high_stakes: Route Stage 3 to Opus instead of Sonnet.
        parameters_version: Optional FK to ``parameters.version_id``.
        prior_classification_id: Set when this call is a
            re-classification of a name already in the table; the
            ``prior_classification_id`` column will be populated.
        persist: When True, INSERT into ``mode_classifications``;
            when False, return the outcome without DB I/O (test mode).
        llm_client: Optional pre-built Anthropic client (for tests).

    Returns:
        :class:`ClassificationOutcome` with the row identifier and
        all stage outputs.
    """
    ticker = ticker.upper().strip()
    # UTC date — ``date.today()`` reads server local tz; the resulting
    # ``as_of`` is fed to data adapters and stage1/stage2 lookups, all of
    # which assume a UTC day key.
    as_of = as_of or _dt.datetime.now(_dt.timezone.utc).date().isoformat()
    data_adapter = data_adapter or DefaultDataAdapter()
    quality_adapter = quality_adapter or DefaultQualityAdapter()

    # --- Stage 1 -------------------------------------------------------- #
    facts = data_adapter.get_structural_facts(ticker, as_of)
    s1 = stage1_classify(facts)
    rule_outcomes = s1.to_rule_outcomes()

    # --- Stage 3 (only if overlap) -------------------------------------- #
    s3: Optional[TiebreakerResult] = None
    method = METHOD_RULE
    recheck_status = RECHECK_CONFIRMED

    if s1.overlap_detected:
        evidence = _build_evidence_block(facts)
        try:
            s3 = stage3_tiebreaker(
                ticker=ticker,
                evidence_block=evidence,
                rule_outcomes=rule_outcomes,
                high_stakes=high_stakes,
                client=llm_client,
            )
            method = METHOD_LLM
            chosen_bin = s3.bin
        except LLMUnavailableError as exc:
            _LOG.warning(
                "Stage 3 unavailable for %s (%s); flagging pending_review",
                ticker,
                exc,
            )
            method = METHOD_RULE
            chosen_bin = (
                s1.provisional_bin
                or MODE_C  # most-conservative default per spec line 119
            )
            recheck_status = RECHECK_PENDING
            rule_outcomes = {**rule_outcomes, "stage3_unavailable": str(exc)}
    else:
        assert s1.provisional_bin is not None
        chosen_bin = s1.provisional_bin

    # --- Stage 2 -------------------------------------------------------- #
    quality_facts = quality_adapter.get_quality_facts(ticker, as_of)
    s2 = stage2_classify(chosen_bin, quality_facts)
    rule_outcomes["stage2"] = s2.to_audit_payload()

    # --- Compose outcome ------------------------------------------------ #
    classification_id = uuid.uuid4()
    classified_at = _dt.datetime.now(_dt.timezone.utc)
    outcome = ClassificationOutcome(
        classification_id=classification_id,
        ticker=ticker,
        final_mode=chosen_bin,
        company_quality_flag=s2.flag if s2 else QUALITY_STANDARD,
        classification_method=method,
        rule_outcomes=rule_outcomes,
        llm_tiebreaker=(s3.to_payload() if s3 is not None else None),
        recheck_status=recheck_status,
        prior_classification_id=prior_classification_id,
        parameters_version=parameters_version,
        classified_at=classified_at,
        stage1=s1,
        stage2=s2,
        stage3=s3,
    )

    if persist:
        _persist(outcome)
    return outcome


# --------------------------------------------------------------------------- #
# Persistence                                                                 #
# --------------------------------------------------------------------------- #


_INSERT_SQL = """
INSERT INTO mode_classifications (
    classification_id, ticker, final_mode, company_quality_flag,
    classification_method, rule_outcomes, llm_tiebreaker,
    recheck_status, prior_classification_id, parameters_version,
    classified_at
) VALUES (
    %(classification_id)s, %(ticker)s, %(final_mode)s, %(company_quality_flag)s,
    %(classification_method)s, %(rule_outcomes)s, %(llm_tiebreaker)s,
    %(recheck_status)s, %(prior_classification_id)s, %(parameters_version)s,
    %(classified_at)s
)
"""


def _persist(outcome: ClassificationOutcome) -> None:
    """INSERT into ``mode_classifications``; respects append-only trigger."""
    import psycopg  # deferred — persist=False paths don't need the DB driver.

    params = {
        "classification_id": outcome.classification_id,
        "ticker": outcome.ticker,
        "final_mode": outcome.final_mode,
        "company_quality_flag": outcome.company_quality_flag,
        "classification_method": outcome.classification_method,
        "rule_outcomes": json.dumps(outcome.rule_outcomes, default=str),
        "llm_tiebreaker": (
            json.dumps(outcome.llm_tiebreaker, default=str)
            if outcome.llm_tiebreaker is not None
            else None
        ),
        "recheck_status": outcome.recheck_status,
        "prior_classification_id": outcome.prior_classification_id,
        "parameters_version": outcome.parameters_version,
        "classified_at": outcome.classified_at,
    }
    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(_INSERT_SQL, params)
        conn.commit()


def fetch_latest(ticker: str) -> Optional[dict]:
    """Return the most-recent row from ``mode_classifications`` for ticker."""
    import psycopg  # deferred

    with psycopg.connect(_dsn()) as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT classification_id, ticker, final_mode,
                       company_quality_flag, classification_method,
                       rule_outcomes, llm_tiebreaker, recheck_status,
                       prior_classification_id, parameters_version,
                       classified_at
                  FROM mode_classifications
                 WHERE ticker = %s
              ORDER BY classified_at DESC
                 LIMIT 1
                """,
                (ticker.upper(),),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = [d.name for d in cur.description]
            return dict(zip(cols, row))
