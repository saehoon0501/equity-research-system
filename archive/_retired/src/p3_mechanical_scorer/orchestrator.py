"""Orchestrator — runs Stage 1A -> Stage 1B -> Stage 2 (info-isolated) -> Stage 3.

Per spec ``docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md``
Section 4.3 (3-stage hybrid scorer) and Section 5.2 (audit-mode UX).

Pipeline::

    inputs (data adapter)
        -> Stage 1A multiplicative knockout
            if REJECT -> short-circuit, audit, return PASS
        -> Stage 1B Tier-A composite
            if REJECT -> short-circuit, audit, return PASS
        -> Stage 2 LLM rubric  (INFO-ISOLATED — sees only source corpus)
        -> Stage 3 deterministic linter (cross-checks Stage 2 vs Stage 1)
        -> Final decision: PROCEED / WATCH / PASS

Information-isolation enforcement (Section 4.3 + Section 5 Q1 lock):

1. Stage 2 inputs are constructed from the source corpus (DataAdapter
   ``fetch_evidence_corpus``), NEVER from Stage 1 outputs.
2. The orchestrator passes only the EvidenceCorpus to Stage 2 — there
   is no API surface where Stage 1 outputs could leak.
3. Stage 2 result carries ``saw_rule_output: false`` which is checked
   by Stage 3 linter; if false-flag is missing/true, the run is
   quarantined and operator review forced.

Audit trail (Section 5.2):
* One ``audit_provenance`` row per stage, all with stage='stage_1_mechanical'
  per the migration's allowed enum (the stage-2 LLM rubric and stage-3
  linter are sub-stages of P3's mechanical scorer; the migration's
  'stage_2_debate' value is reserved for the downstream P4 5-style debate).
  Each row's ``drill_payload`` contains a ``substage`` key disambiguating
  ``stage_1a``/``stage_1b``/``stage_2_llm_rubric``/``stage_3_linter``.
* parent_audit_id chains rows in pipeline order; first row has parent=null.
* hmac_signature must be supplied by the caller (or the persistence
  layer); this orchestrator computes a deterministic placeholder so
  unit tests can run without the production HMAC service.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import uuid
from dataclasses import dataclass
from typing import Optional, Protocol

from src.audit_trail.hmac_verify import compute_signature
from src.audit_trail.loader import StageRow

from . import (
    DECISION_PASS,
    DECISION_PROCEED,
    DECISION_WATCH,
    DEFAULT_MODEL,
    HIGH_STAKES_MODEL,
    LINTER_VERSION,
    LLM_PROMPT_VERSION,
    RULE_ENGINE_VERSION,
    STAGE_OUTCOME_REJECT,
    STAGE_OUTCOME_TIER_A,
    STAGE_OUTCOME_WATCH,
)
from .stage1a_multiplicative_knockout import (
    EraFitInput,
    FraudSignatureInput,
    Stage1AResult,
    evaluate as stage1a_evaluate,
)
from .stage1b_tier_a_composite import (
    Stage1BResult,
    TierAInput,
    evaluate as stage1b_evaluate,
)
from .stage2_llm_rubric import (
    EvidenceCorpus,
    Stage2Result,
    score_all_patterns,
)
from .stage3_linter import Stage3Result, lint as stage3_lint


# ---------------------------------------------------------------------------
# Data adapter protocol — orchestrator depends on this; production wiring is
# the caller's responsibility (the orchestrator does not query the DB itself).
# ---------------------------------------------------------------------------


class P3DataAdapter(Protocol):
    """Pluggable adapter for Stage 1 + Stage 2 inputs.

    ``fetch_stage1_inputs`` returns the deterministic facts for Stage 1A/1B.
    ``fetch_evidence_corpus`` returns ONLY the source-evidence corpus for
    Stage 2; this method MUST NOT have access to Stage-1 outputs (this
    is the load-bearing isolation; tests verify by spying on call args).
    """

    def fetch_stage1_inputs(
        self, ticker: str
    ) -> tuple[FraudSignatureInput, EraFitInput, TierAInput]:
        ...

    def fetch_evidence_corpus(self, ticker: str) -> EvidenceCorpus:
        ...


# ---------------------------------------------------------------------------
# Outcome envelope
# ---------------------------------------------------------------------------


@dataclass
class P3Outcome:
    """End-to-end P3 result — what gets persisted + returned to caller."""

    p3_run_id: uuid.UUID
    ticker: str
    decision: str  # DECISION_PROCEED | DECISION_WATCH | DECISION_PASS
    stage1a: Stage1AResult
    stage1b: Optional[Stage1BResult]
    stage2: Optional[Stage2Result]
    stage3: Optional[Stage3Result]
    composition_disagreement: bool  # first-class field (Section 4.3 audit)
    operator_review_required: bool
    aggregate_score: float
    versions: dict
    audit_rows: list  # list of audit_provenance row dicts
    created_at: _dt.datetime

    def to_dict(self) -> dict:
        return {
            "p3_run_id": str(self.p3_run_id),
            "ticker": self.ticker,
            "decision": self.decision,
            "composition_disagreement": self.composition_disagreement,
            "operator_review_required": self.operator_review_required,
            "aggregate_score": round(self.aggregate_score, 4),
            "stage1a": self.stage1a.to_audit_payload(),
            "stage1b": self.stage1b.to_audit_payload() if self.stage1b else None,
            "stage2": self.stage2.to_audit_payload() if self.stage2 else None,
            "stage3": self.stage3.to_audit_payload() if self.stage3 else None,
            "versions": self.versions,
            "audit_rows": list(self.audit_rows),
            "created_at": self.created_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# HMAC helper — single canonical scheme via src.audit_trail.hmac_verify
# ---------------------------------------------------------------------------


def _audit_hmac_key() -> Optional[bytes]:
    """Read AUDIT_HMAC_KEY env var.

    Single audit-chain secret shared with the audit_trail verifier per v3
    spec Section 5 Q1. Returns None when unset; tests run in unkeyed mode
    with a deterministic placeholder secret.
    """
    env = os.environ.get("AUDIT_HMAC_KEY")
    if env:
        return env.encode("utf-8")
    return None


_DEV_PLACEHOLDER_KEY = b"audit-dev-key-do-not-use-in-prod"


# ---------------------------------------------------------------------------
# Audit row builder
# ---------------------------------------------------------------------------


def _build_audit_row(
    *,
    recommendation_id: Optional[uuid.UUID],
    stage: str,
    substage: str,
    payload: dict,
    parent_audit_id: Optional[uuid.UUID],
    versions: dict,
    created_at: _dt.datetime,
) -> dict:
    """Return a dict shaped for INSERT into audit_provenance.

    ``recommendation_id`` may be None during P3-only runs (P3 outputs
    don't yet have an associated execution_recommendation row). When None,
    HMAC signing is deferred — the row goes out with ``hmac_signature=""``
    and ``persist_audit_rows`` re-signs after the recommendation_id is
    stitched (Postgres requires NOT NULL on the FK).

    Per v3 spec Section 5 Q1: signed payload includes ``created_at``.
    """
    audit_id = uuid.uuid4()
    row_payload = {
        "audit_id": str(audit_id),
        "recommendation_id": str(recommendation_id) if recommendation_id else None,
        "stage": stage,
        "drill_payload": {**payload, "substage": substage},
        "parent_audit_id": str(parent_audit_id) if parent_audit_id else None,
        "versions": versions,
        # Stored as ISO string so the dict round-trips through json.dumps
        # cleanly. _sign_row_payload re-parses for canonicalization.
        "created_at": _isoformat_utc(created_at),
    }
    row_payload["hmac_signature"] = _sign_row_payload(row_payload)
    return row_payload


def _isoformat_utc(value: _dt.datetime) -> str:
    """ISO8601 with explicit UTC marker — must match audit_trail _isoformat."""
    if value.tzinfo is None:
        return value.isoformat() + "Z"
    return value.isoformat()


def _parse_isoformat_utc(value: str) -> _dt.datetime:
    """Inverse of ``_isoformat_utc``; tolerates trailing 'Z'."""
    if value.endswith("Z"):
        return _dt.datetime.fromisoformat(value[:-1]).replace(
            tzinfo=_dt.timezone.utc
        )
    return _dt.datetime.fromisoformat(value)


def _sign_row_payload(row_payload: dict) -> str:
    """Sign a row payload using the canonical audit_trail scheme.

    Builds a StageRow proxy with the (possibly placeholder)
    ``recommendation_id`` and calls ``compute_signature``. Per the
    canonical-payload contract, the recommendation_id is part of the
    signed bytes, so when the orchestrator runs without a stitched
    recommendation_id (P3-only mode), the signature is computed over
    the deferred-stitch sentinel (all-zero UUID). ``persist_audit_rows``
    re-signs each row after the real recommendation_id is bound (Postgres
    NOT NULL FK requires it before INSERT anyway).

    Per v3 spec Section 5 Q1.
    """
    key = _audit_hmac_key() or _DEV_PLACEHOLDER_KEY
    return compute_signature(_row_payload_to_stagerow(row_payload), key)


_DEFERRED_REC_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")


def _row_payload_to_stagerow(row_payload: dict) -> StageRow:
    """Build a StageRow from the dict shape used by the orchestrator.

    When recommendation_id is None (P3-only run), uses the deferred
    sentinel UUID; persist_audit_rows re-signs after stitching.
    """
    parent = row_payload.get("parent_audit_id")
    rec_id_raw = row_payload.get("recommendation_id")
    rec_id = uuid.UUID(rec_id_raw) if rec_id_raw else _DEFERRED_REC_ID
    created_at = row_payload["created_at"]
    if isinstance(created_at, str):
        created_at = _parse_isoformat_utc(created_at)
    return StageRow(
        audit_id=uuid.UUID(row_payload["audit_id"]),
        recommendation_id=rec_id,
        stage=row_payload["stage"],
        drill_payload=dict(row_payload["drill_payload"]),
        hmac_signature="",  # placeholder — we are computing it
        parent_audit_id=uuid.UUID(parent) if parent else None,
        versions=dict(row_payload["versions"]),
        created_at=created_at,
    )


# ---------------------------------------------------------------------------
# Decision aggregation
# ---------------------------------------------------------------------------


# Stage 2 aggregate-score thresholds for final decision (when Stage 1B = A)
S2_PROCEED_THRESHOLD = 0.55
S2_WATCH_THRESHOLD = 0.35


def _final_decision(
    stage1a: Stage1AResult,
    stage1b: Optional[Stage1BResult],
    stage2: Optional[Stage2Result],
    stage3: Optional[Stage3Result],
) -> tuple[str, bool]:
    """Compose final decision; return (decision, composition_disagreement)."""
    if stage1a.outcome == STAGE_OUTCOME_REJECT:
        return DECISION_PASS, False
    if stage1b is None:
        return DECISION_PASS, False
    if stage1b.outcome == STAGE_OUTCOME_REJECT:
        return DECISION_PASS, False
    # Stage 1B says A or WATCH; Stage 2 modulates
    s2_score = stage2.aggregate_score if stage2 else 0.0
    s1b_to_decision = {
        STAGE_OUTCOME_TIER_A: DECISION_PROCEED,
        STAGE_OUTCOME_WATCH: DECISION_WATCH,
    }
    s1b_decision = s1b_to_decision.get(stage1b.outcome, DECISION_WATCH)

    if stage2 is None:
        return s1b_decision, False

    # Map S2 score to decision
    if s2_score >= S2_PROCEED_THRESHOLD:
        s2_decision = DECISION_PROCEED
    elif s2_score >= S2_WATCH_THRESHOLD:
        s2_decision = DECISION_WATCH
    else:
        s2_decision = DECISION_PASS

    disagreement = s1b_decision != s2_decision

    # Conservative composition rule:
    #   * If both agree -> their value.
    #   * If disagree -> take the more conservative of the two.
    rank = {DECISION_PROCEED: 2, DECISION_WATCH: 1, DECISION_PASS: 0}
    final = (
        s1b_decision
        if rank[s1b_decision] <= rank[s2_decision]
        else s2_decision
    )
    return final, disagreement


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def score_ticker(
    ticker: str,
    adapter: P3DataAdapter,
    *,
    high_stakes: bool = False,
    llm_caller=None,
    recommendation_id: Optional[uuid.UUID] = None,
) -> P3Outcome:
    """Run the full P3 pipeline for one ticker.

    Args:
        ticker: stock ticker.
        adapter: data adapter providing Stage 1 and Stage 2 inputs.
        high_stakes: if True, route Stage 2 to Opus regardless of
            per-pattern contested flag.
        llm_caller: optional callable used to mock LLM responses in tests.
        recommendation_id: optional UUID to stitch audit rows to a
            downstream execution_recommendations row; None in P3-only runs.
    """
    versions = {
        "rule_engine_version": RULE_ENGINE_VERSION,
        "llm_prompt_version": LLM_PROMPT_VERSION,
        "linter_version": LINTER_VERSION,
        "model_default": DEFAULT_MODEL,
        "model_high_stakes": HIGH_STAKES_MODEL,
    }
    audit_rows: list = []
    p3_run_id = uuid.uuid4()
    now = _dt.datetime.now(tz=_dt.timezone.utc)

    # ---------- Stage 1A ----------
    fraud_input, era_input, tier_a_input = adapter.fetch_stage1_inputs(ticker)
    stage1a_result = stage1a_evaluate(fraud_input, era_input)
    s1a_row = _build_audit_row(
        recommendation_id=recommendation_id,
        stage="stage_1_mechanical",
        substage="stage_1a",
        payload=stage1a_result.to_audit_payload(),
        parent_audit_id=None,
        versions=versions,
        created_at=now,
    )
    audit_rows.append(s1a_row)
    s1a_audit_uuid = uuid.UUID(s1a_row["audit_id"])

    if stage1a_result.outcome == STAGE_OUTCOME_REJECT:
        return P3Outcome(
            p3_run_id=p3_run_id,
            ticker=ticker,
            decision=DECISION_PASS,
            stage1a=stage1a_result,
            stage1b=None,
            stage2=None,
            stage3=None,
            composition_disagreement=False,
            operator_review_required=False,
            aggregate_score=0.0,
            versions=versions,
            audit_rows=audit_rows,
            created_at=now,
        )

    # ---------- Stage 1B ----------
    stage1b_result = stage1b_evaluate(tier_a_input)
    s1b_row = _build_audit_row(
        recommendation_id=recommendation_id,
        stage="stage_1_mechanical",
        substage="stage_1b",
        payload=stage1b_result.to_audit_payload(),
        parent_audit_id=s1a_audit_uuid,
        versions=versions,
        created_at=now,
    )
    audit_rows.append(s1b_row)
    s1b_audit_uuid = uuid.UUID(s1b_row["audit_id"])

    if stage1b_result.outcome == STAGE_OUTCOME_REJECT:
        return P3Outcome(
            p3_run_id=p3_run_id,
            ticker=ticker,
            decision=DECISION_PASS,
            stage1a=stage1a_result,
            stage1b=stage1b_result,
            stage2=None,
            stage3=None,
            composition_disagreement=False,
            operator_review_required=False,
            aggregate_score=0.0,
            versions=versions,
            audit_rows=audit_rows,
            created_at=now,
        )

    # ---------- Stage 2 (INFORMATION-ISOLATED) ----------
    # NOTE: we DELIBERATELY discard stage1a_result and stage1b_result here.
    # The evidence corpus is fetched fresh from the adapter; the only
    # arguments to score_all_patterns are the corpus and tuning knobs.
    # Reviewers: do not pass stage1a_result / stage1b_result into
    # score_all_patterns. Section 4.3 + Section 5 Q1 lock.
    evidence = adapter.fetch_evidence_corpus(ticker)
    if not isinstance(evidence, EvidenceCorpus):
        raise TypeError(
            "adapter.fetch_evidence_corpus must return EvidenceCorpus; "
            "any other type may carry Stage-1 leakage"
        )
    model_override = HIGH_STAKES_MODEL if high_stakes else None
    stage2_result = score_all_patterns(
        evidence,
        model=model_override,
        llm_caller=llm_caller,
    )
    # Defence-in-depth: assert the flag set by Stage 2
    assert stage2_result.saw_rule_output is False, (
        "Stage 2 saw_rule_output flag must be False (info-isolation)"
    )

    s2_row = _build_audit_row(
        recommendation_id=recommendation_id,
        stage="stage_1_mechanical",
        substage="stage_2_llm_rubric",
        payload=stage2_result.to_audit_payload(),
        parent_audit_id=s1b_audit_uuid,
        versions=versions,
        created_at=now,
    )
    audit_rows.append(s2_row)
    s2_audit_uuid = uuid.UUID(s2_row["audit_id"])

    # ---------- Stage 3 (deterministic linter) ----------
    stage3_result = stage3_lint(
        stage2_result.to_audit_payload(),
        stage1b=stage1b_result.to_audit_payload(),
    )
    s3_row = _build_audit_row(
        recommendation_id=recommendation_id,
        stage="stage_1_mechanical",
        substage="stage_3_linter",
        payload=stage3_result.to_audit_payload(),
        parent_audit_id=s2_audit_uuid,
        versions=versions,
        created_at=now,
    )
    audit_rows.append(s3_row)

    # ---------- Final decision + disagreement ----------
    decision, disagreement = _final_decision(
        stage1a_result, stage1b_result, stage2_result, stage3_result
    )
    operator_review = stage3_result.operator_review_required or disagreement

    return P3Outcome(
        p3_run_id=p3_run_id,
        ticker=ticker,
        decision=decision,
        stage1a=stage1a_result,
        stage1b=stage1b_result,
        stage2=stage2_result,
        stage3=stage3_result,
        composition_disagreement=disagreement,
        operator_review_required=operator_review,
        aggregate_score=stage2_result.aggregate_score,
        versions=versions,
        audit_rows=audit_rows,
        created_at=now,
    )


# ---------------------------------------------------------------------------
# Persistence helper (caller injects DB cursor)
# ---------------------------------------------------------------------------


def persist_audit_rows(cursor, outcome: P3Outcome) -> None:
    """INSERT each audit row into audit_provenance.

    Caller is responsible for transaction management. The
    ``recommendation_id`` field is required by the migration; if None
    here, this function raises (caller must stitch the recommendation
    UUID before calling).

    Re-signs each row using ``compute_signature`` with the canonical
    audit_trail scheme — defer-signed rows (P3-only runs that wrote
    rows under the deferred-sentinel UUID) are re-bound to the real
    recommendation_id here, so ``audit_trail.hmac_verify.verify_chain``
    will validate them cleanly. Per v3 spec Section 5 Q1.
    """
    for row in outcome.audit_rows:
        if row.get("recommendation_id") is None:
            raise ValueError(
                "audit_provenance.recommendation_id is NOT NULL — caller must "
                "stitch a recommendation_id before persisting P3 audit rows"
            )
        # Re-sign with the canonical scheme so audit_trail.verify_chain works.
        row["hmac_signature"] = _sign_row_payload(row)
        # Bind the Python sign-time created_at into the INSERT — if we let
        # Postgres apply its DEFAULT NOW(), the DB row's created_at would
        # diverge from the value signed into the HMAC payload, and the
        # subsequent verify_chain (which canonicalizes the DB roundtripped
        # timestamptz) would always fail. The signed string was produced
        # by _isoformat_utc; parse it back to an aware datetime for psycopg
        # to bind as timestamptz.
        created_at_bind = _parse_isoformat_utc(row["created_at"])
        cursor.execute(
            """
            INSERT INTO audit_provenance
              (audit_id, recommendation_id, stage, drill_payload,
               hmac_signature, parent_audit_id, versions, created_at)
            VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s::jsonb, %s)
            """,
            (
                row["audit_id"],
                row["recommendation_id"],
                row["stage"],
                json.dumps(row["drill_payload"]),
                row["hmac_signature"],
                row["parent_audit_id"],
                json.dumps(row["versions"]),
                created_at_bind,
            ),
        )


def stitch_recommendation_id(
    outcome: P3Outcome, recommendation_id: uuid.UUID
) -> None:
    """Bind a real recommendation_id to all audit rows in this outcome.

    Used after the orchestrator has run in P3-only mode (recommendation_id=
    None) and the downstream emitter has produced an
    execution_recommendations row. Re-signs each row using the canonical
    HMAC scheme so subsequent ``persist_audit_rows`` writes verify under
    ``audit_trail.hmac_verify``.
    """
    rec_str = str(recommendation_id)
    for row in outcome.audit_rows:
        row["recommendation_id"] = rec_str
        row["hmac_signature"] = _sign_row_payload(row)
