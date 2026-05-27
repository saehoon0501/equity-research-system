"""Postgres loader for audit_provenance + execution_recommendations.

Per v3 spec Section 5.2: top-level summary + per-stage drill on demand. This
module is the read-only query layer; writes are owned by the recommendation
emitter (Section 4.6).

The connection contract:
  - We do not couple to any specific Postgres driver. The loader functions
    accept a `conn` argument (anything implementing PEP-249 cursor-context
    semantics with `.execute(sql, params)` and `.fetchone()/.fetchall()`).
  - Tests pass a fake conn; production passes psycopg2/psycopg3/asyncpg-sync
    or whatever is wired by the caller (typically the slash command's Bash
    invocation through psql, or an MCP-mediated query).

Schema reference: db/migrations/008_v3_recommendations.sql
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Optional, Protocol
from uuid import UUID

# v3 spec Section 5.2 stage list — must match audit_provenance.stage CHECK.
VALID_STAGES: tuple[str, ...] = (
    "stage_1_mechanical",
    "stage_2_debate",
    "stage_3_kill_criteria",
    "stage_4_counterfactual",
    "materiality",
)


class _Cursor(Protocol):
    """Minimal PEP-249-ish cursor protocol used by the loader."""

    def execute(self, sql: str, params: Optional[tuple[Any, ...]] = None) -> Any: ...
    def fetchone(self) -> Optional[tuple[Any, ...]]: ...
    def fetchall(self) -> list[tuple[Any, ...]]: ...
    def close(self) -> None: ...


class _Connection(Protocol):
    """Minimal connection protocol — `.cursor()` returns _Cursor."""

    def cursor(self) -> _Cursor: ...


@dataclass(frozen=True)
class StageRow:
    """One row from audit_provenance.

    Mirrors the schema in db/migrations/008_v3_recommendations.sql exactly so
    the HMAC verifier can recompute canonical payloads without lossy
    intermediate types.
    """

    audit_id: UUID
    recommendation_id: UUID
    stage: str
    drill_payload: Mapping[str, Any]
    hmac_signature: str
    parent_audit_id: Optional[UUID]
    versions: Mapping[str, Any]
    created_at: datetime


@dataclass(frozen=True)
class AuditSummary:
    """Top-level audit summary for a single recommendation.

    Per v3 spec Section 5.2:
      audit_summary:
        recommendation_id, ticker, recommendation, date
        decision_path:
          stage_1_mechanical:    { outcome, score, drill_link }
          stage_2_debate:        { consensus, dissenter, drill_link }
          stage_3_kill_criteria: { fired, drill_link }
          stage_4_counterfactual:{ top_3_archetype, veto_status, drill_link }
          materiality:           { classification, trigger, drill_link }
        versions: { rule_engine, debate_prompt, model, parameters }
    """

    recommendation_id: UUID
    ticker: str
    recommendation: str
    conviction: str
    date: date
    audit_available: bool
    versions: Mapping[str, Any]
    # decision_path[stage] -> dict with stage-specific summary keys + drill_link
    decision_path: Mapping[str, Mapping[str, Any]]


# -----------------------------------------------------------------------------
# Public loader functions
# -----------------------------------------------------------------------------


def get_audit_summary(conn: _Connection, rec_id: UUID | str) -> AuditSummary:
    """Return the top-level audit summary for a single recommendation.

    Joins execution_recommendations with the per-stage rollup of
    audit_provenance (one drill_link per stage). The drill_payload itself
    is NOT loaded here — only the small per-stage summary keys needed for
    the top-level decision_path.

    Per v3 Section 5.2 layered drill-down: cheap top-level summary first,
    drill on operator request.

    Raises:
        LookupError: rec_id not found.
    """
    rec_uuid = _coerce_uuid(rec_id)
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT recommendation_id, ticker, recommendation, conviction,
                   date, audit_available,
                   rule_engine_version, debate_prompt_version,
                   model_id, model_version, parameters_version
            FROM execution_recommendations
            WHERE recommendation_id = %s
            """,
            (str(rec_uuid),),
        )
        row = cur.fetchone()
        if row is None:
            raise LookupError(f"recommendation_id {rec_uuid} not found")

        (
            rid,
            ticker,
            recommendation,
            conviction,
            rec_date,
            audit_available,
            rule_engine_version,
            debate_prompt_version,
            model_id,
            model_version,
            parameters_version,
        ) = row

        versions = {
            "rule_engine_version": rule_engine_version,
            "debate_prompt_version": debate_prompt_version,
            "model_id": model_id,
            "model_version": model_version,
            "parameters_version": (
                str(parameters_version) if parameters_version is not None else None
            ),
        }

        # Pull per-stage summary keys. Each row has audit_id (drill_link),
        # plus a small projection of drill_payload for the top-level view.
        cur.execute(
            """
            SELECT stage, audit_id, drill_payload
            FROM audit_provenance
            WHERE recommendation_id = %s
            ORDER BY created_at ASC, audit_id ASC
            """,
            (str(rec_uuid),),
        )
        decision_path: dict[str, dict[str, Any]] = {}
        for stage, audit_id, drill_payload in cur.fetchall():
            payload = _coerce_jsonb(drill_payload)
            decision_path[stage] = _summarize_stage(stage, payload, audit_id)

        return AuditSummary(
            recommendation_id=_coerce_uuid(rid),
            ticker=ticker,
            recommendation=recommendation,
            conviction=conviction,
            date=rec_date,
            audit_available=bool(audit_available),
            versions=versions,
            decision_path=decision_path,
        )
    finally:
        cur.close()


def get_stage_drill(conn: _Connection, rec_id: UUID | str, stage: str) -> StageRow:
    """Return the full audit_provenance row for one stage.

    Per v3 Section 5.2: drill_link surfaces verbatim quotes, agent outputs,
    3-LLM iterative-consensus iterations, retrieval results, kill-criteria
    evaluation chain.

    Raises:
        ValueError: stage not in VALID_STAGES.
        LookupError: no row exists for (rec_id, stage).
    """
    if stage not in VALID_STAGES:
        raise ValueError(
            f"stage {stage!r} not in {VALID_STAGES} — see v3 Section 5.2"
        )
    rec_uuid = _coerce_uuid(rec_id)
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT audit_id, recommendation_id, stage, drill_payload,
                   hmac_signature, parent_audit_id, versions, created_at
            FROM audit_provenance
            WHERE recommendation_id = %s AND stage = %s
            ORDER BY created_at ASC, audit_id ASC
            LIMIT 1
            """,
            (str(rec_uuid), stage),
        )
        row = cur.fetchone()
        if row is None:
            raise LookupError(
                f"no audit_provenance row for recommendation_id={rec_uuid} stage={stage}"
            )
        (
            audit_id,
            recommendation_id,
            stage_db,
            drill_payload,
            hmac_signature,
            parent_audit_id,
            versions,
            created_at,
        ) = row
        return StageRow(
            audit_id=_coerce_uuid(audit_id),
            recommendation_id=_coerce_uuid(recommendation_id),
            stage=stage_db,
            drill_payload=_coerce_jsonb(drill_payload),
            hmac_signature=hmac_signature,
            parent_audit_id=(
                _coerce_uuid(parent_audit_id) if parent_audit_id is not None else None
            ),
            versions=_coerce_jsonb(versions),
            created_at=created_at,
        )
    finally:
        cur.close()


def get_chain_for_recommendation(
    conn: _Connection, rec_id: UUID | str
) -> list[StageRow]:
    """Return all audit_provenance rows for a recommendation, chain-ordered.

    Returned in created_at ASC so the HMAC chain (parent_audit_id pointing
    back to a prior row) verifies front-to-back. Used by `verify_chain`.
    """
    rec_uuid = _coerce_uuid(rec_id)
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT audit_id, recommendation_id, stage, drill_payload,
                   hmac_signature, parent_audit_id, versions, created_at
            FROM audit_provenance
            WHERE recommendation_id = %s
            ORDER BY created_at ASC, audit_id ASC
            """,
            (str(rec_uuid),),
        )
        rows: list[StageRow] = []
        for r in cur.fetchall():
            (
                audit_id,
                recommendation_id,
                stage_db,
                drill_payload,
                hmac_signature,
                parent_audit_id,
                versions,
                created_at,
            ) = r
            rows.append(
                StageRow(
                    audit_id=_coerce_uuid(audit_id),
                    recommendation_id=_coerce_uuid(recommendation_id),
                    stage=stage_db,
                    drill_payload=_coerce_jsonb(drill_payload),
                    hmac_signature=hmac_signature,
                    parent_audit_id=(
                        _coerce_uuid(parent_audit_id)
                        if parent_audit_id is not None
                        else None
                    ),
                    versions=_coerce_jsonb(versions),
                    created_at=created_at,
                )
            )
        return rows
    finally:
        cur.close()


def get_latest_for_ticker(conn: _Connection, ticker: str) -> UUID:
    """Return the latest recommendation_id for a ticker.

    Per v3 Section 5.4: `/audit-trail <ticker> --latest` resolves to the
    most recent row by (date DESC, created_at DESC).

    Raises:
        LookupError: no recommendation exists for the ticker.
    """
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT recommendation_id
            FROM execution_recommendations
            WHERE ticker = %s
            ORDER BY date DESC, created_at DESC
            LIMIT 1
            """,
            (ticker,),
        )
        row = cur.fetchone()
        if row is None:
            raise LookupError(f"no execution_recommendations row for ticker {ticker!r}")
        return _coerce_uuid(row[0])
    finally:
        cur.close()


# -----------------------------------------------------------------------------
# Internal helpers
# -----------------------------------------------------------------------------


def _summarize_stage(
    stage: str, payload: Mapping[str, Any], audit_id: Any
) -> dict[str, Any]:
    """Project the per-stage summary keys per v3 Section 5.2 schema.

    Surfaces only the small fields needed for the top-level decision_path.
    Full payload available via get_stage_drill().
    """
    drill_link = f"/audit-trail {{rec_id}} --stage {stage}"  # rec_id formatted by renderer
    summary: dict[str, Any] = {"drill_link": drill_link, "audit_id": str(audit_id)}

    if stage == "stage_1_mechanical":
        summary["outcome"] = payload.get("outcome")
        summary["score"] = payload.get("score")
    elif stage == "stage_2_debate":
        summary["consensus"] = payload.get("consensus")
        summary["dissenter"] = payload.get("dissenter")
    elif stage == "stage_3_kill_criteria":
        summary["fired"] = payload.get("fired")
    elif stage == "stage_4_counterfactual":
        summary["top_3_archetype"] = payload.get("top_3_archetype")
        summary["veto_status"] = payload.get("veto_status")
    elif stage == "materiality":
        summary["classification"] = payload.get("classification")
        summary["trigger"] = payload.get("trigger")
    return summary


def _coerce_uuid(value: Any) -> UUID:
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def _coerce_jsonb(value: Any) -> Mapping[str, Any]:
    """Postgres JSONB may arrive as dict (psycopg2 default) or str (raw)."""
    if value is None:
        return {}
    if isinstance(value, (dict, list)):
        return value  # type: ignore[return-value]
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        return json.loads(value)
    return value  # type: ignore[return-value]
