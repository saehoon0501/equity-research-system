"""P7 emitter — composes + signs + writes execution_recommendations rows.

Per v3 spec Section 4.6 Q1 (recommendation output schema) +
Section 5 Q1 (audit-trail HMAC chain) +
Section 7 Q4 (layered drill-down lock).

End-to-end flow per emission:

    Inputs (debate_result + mode + anchor-drift state + counterfactual
            top-3 matches + S0 regime + portfolio context + prior emission)
        |
        +-- compute sizing (sizing.compute_sizing)
        +-- compute conviction (conviction_rollup.roll_up_conviction)
        +-- apply hysteresis (hysteresis.apply_hysteresis)
        +-- build execution_context (execution_context.build_execution_context)
        +-- compute trigger_metadata (trigger_logic.compute_trigger_metadata)
        |
        +-- compose execution_recommendation row (Section 4.6 Q1 schema)
        +-- HMAC-sign canonical row payload using AUDIT_HMAC_KEY
        +-- INSERT execution_recommendations + per-stage audit_provenance
            chain rows (each chained via parent_audit_id)
        |
        +-- return recommendation_id

HMAC integration uses ``audit_trail.canonical_payload_dict`` +
``compute_signature_dict`` (single source of truth for all rows in the
chain). The shared key scope is ``AUDIT_HMAC_KEY``. Watchlist anchor HMACs
(``WATCHLIST_HMAC_SECRET``) are a SEPARATE scope and are not consumed
here — they're verified by the anchor-drift sidecar.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence
from uuid import UUID

from src.audit_trail.hmac_verify import (
    _json_default,
    canonical_payload_dict,
    compute_signature_dict,
)
from src.p7_recommendation_emitter.conviction_rollup import (
    ConvictionInputs,
    ConvictionRollup,
    roll_up_conviction,
)
from src.p7_recommendation_emitter.execution_context import (
    ExecutionContext,
    aggregate_risk_flags,
    build_execution_context,
)
from src.p7_recommendation_emitter.hysteresis import (
    HysteresisInputs,
    HysteresisResult,
    apply_hysteresis,
)
from src.p7_recommendation_emitter.sizing import (
    SizingContext,
    SizingSuggestion,
    compute_sizing,
)
from src.p7_recommendation_emitter.trigger_logic import (
    TRIGGER_NEW_CANDIDATE,
    TriggerInputs,
    TriggerMetadata,
    compute_trigger_metadata,
)

_LOG = logging.getLogger(__name__)

AUDIT_HMAC_ENV = "AUDIT_HMAC_KEY"


class P7EmitError(RuntimeError):
    """Raised when emission preconditions fail."""


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@dataclass
class EmitInputs:
    """Bundle of upstream inputs the emitter consumes."""

    ticker: str
    mode: str  # 'B' / 'B_prime' / 'C'
    company_quality_flag: str  # 'HIGH' / 'STANDARD'
    mode_certainty: str  # 'rule_clean' / 'llm_tiebreaker'

    # P4 debate
    debate_add_count: int  # styles voting ADD (0..5)
    debate_consensus_summary: str  # human-readable, e.g., "4/5 (Quant dissents)"

    # P3 kill criteria
    kills_fired: int

    # S2 counterfactual top-3 archetype tags ('SURVIVOR' / 'NON_SURVIVOR')
    counterfactual_top_3: Sequence[str]

    # S6 anchor-drift channel state (0..3 channels triggered)
    anchor_drift_channels_triggered: int

    # P6 disposition (primary recommendation BUY/HOLD/TRIM/SELL + pacing)
    primary_recommendation: str
    suggested_pacing: str

    # Trigger logic source
    triggered_by: str  # one of trigger_logic._VALID_TRIGGERS
    materiality_event_ref: Optional[UUID] = None

    # Sizing context
    available_cash_pct: Optional[float] = None
    portfolio_underperformance_pp_vs_bench: Optional[float] = None
    s0_vol_z: Optional[float] = None

    # Execution context payloads (caller pre-fetches from MCPs / audit chain)
    current_price: Optional[float] = None
    fair_value_payload: Optional[Mapping[str, Any]] = None
    near_term_catalysts_raw: Optional[Sequence[Mapping[str, Any]]] = None
    technical_signals_raw: Optional[Mapping[str, Any]] = None

    # Sidecar payloads for risk-flag aggregation
    s0_regime_state: Optional[Mapping[str, Any]] = None
    s4_smart_money: Optional[Mapping[str, Any]] = None
    extra_risk_flags: Sequence[str] = ()

    # Hysteresis prior-state inputs
    prior_conviction_bucket: Optional[str] = None
    prior_pending_target: Optional[str] = None
    prior_pending_transition: bool = False
    flip_history_30d: Sequence[_dt.date] = ()

    # Trigger-logic prior emission state
    prior_recommendation: Optional[str] = None
    prior_recommendation_date: Optional[_dt.date] = None

    # Versioning bundle (Section 5 Q1)
    rule_engine_version: str = "v0.1.0"
    debate_prompt_version: str = "v0.1.0"
    model_id: str = "claude-opus-4-7"
    model_version: str = "claude-opus-4-7[1m]"
    parameters_version: Optional[UUID] = None

    # Optional override: explicit emit timestamp; defaults to NOW() UTC.
    now: Optional[_dt.datetime] = None

    # Per-stage drill payloads to write into audit_provenance.
    # Keys: 'stage_1_mechanical', 'stage_2_debate', 'stage_3_kill_criteria',
    # 'stage_4_counterfactual', 'materiality'.
    stage_drill_payloads: Mapping[str, Mapping[str, Any]] = field(
        default_factory=dict
    )


@dataclass
class EmitOutcome:
    """Returned to caller after a successful emission."""

    recommendation_id: UUID
    ticker: str
    recommendation: str
    conviction: str
    audit_signature: str
    audit_chain_ids: list[UUID] = field(default_factory=list)
    sizing_payload: dict = field(default_factory=dict)
    conviction_breakdown: dict = field(default_factory=dict)
    trigger_metadata: dict = field(default_factory=dict)
    execution_context: dict = field(default_factory=dict)
    escalate_m2: bool = False  # per hysteresis flip-frequency


# ---------------------------------------------------------------------------
# HMAC helpers
# ---------------------------------------------------------------------------


def _read_audit_key(explicit: Optional[bytes] = None) -> bytes:
    if explicit is not None:
        return explicit
    val = os.environ.get(AUDIT_HMAC_ENV)
    if not val:
        raise P7EmitError(
            f"{AUDIT_HMAC_ENV} env var is not set; refusing to emit "
            "an unsigned recommendation per Section 5 Q1 audit-chain lock"
        )
    return val.encode("utf-8")


def _row_canonical_payload(row: dict) -> dict:
    """The portion of the execution_recommendations row that is signed.

    The audit_signature is computed over a deterministic projection of the
    row — every column except (a) the ``audit_signature`` itself, and
    (b) the four narrow-UPDATE-allowed state-machine columns that
    migration 008's ``exec_recs_guard`` trigger explicitly permits to
    mutate post-insert.

    Per ``db/migrations/008_v3_recommendations.sql`` lines 181-205, the
    trigger blocks UPDATE on every column EXCEPT this set:

      - conviction_pending_transition
      - conviction_pending_target
      - conviction_flip_count_30d
      - conviction_frozen_pending_review

    ``conviction_changed_from_prior`` is INCLUDED in the trigger's
    rejection clause (line 189) — i.e., it is immutable post-insert —
    so it MUST be part of the signed payload. Excluding it would be
    a tamper-detection gap (a future bug that mutated this column in
    Postgres would not invalidate the row's HMAC).

    Per v3 spec Section 5 Q1 audit-trail lock + Section 7 Q4.
    """
    # Only the four narrow-UPDATE-allowed columns (per migration 008
    # trigger) plus the signature itself are excluded.
    excluded = {
        "audit_signature",
        "conviction_pending_transition",
        "conviction_pending_target",
        "conviction_flip_count_30d",
        "conviction_frozen_pending_review",
    }
    return {k: v for k, v in row.items() if k not in excluded}


# ---------------------------------------------------------------------------
# Stage chain helpers
# ---------------------------------------------------------------------------


_STAGE_ORDER: tuple[str, ...] = (
    "stage_1_mechanical",
    "stage_2_debate",
    "stage_3_kill_criteria",
    "stage_4_counterfactual",
    "materiality",
)


def _build_audit_chain(
    *,
    rec_id: UUID,
    drill_payloads: Mapping[str, Mapping[str, Any]],
    versions: Mapping[str, Any],
    now: _dt.datetime,
    key: bytes,
) -> list[dict]:
    """Build per-stage audit_provenance rows, chained via parent_audit_id.

    Each row payload follows the canonical scheme used by ``audit_trail.
    canonical_payload`` (StageRow.to_payload form) so ``verify_chain``
    validates them after read-back.
    """
    rows: list[dict] = []
    parent: Optional[UUID] = None
    for i, stage in enumerate(_STAGE_ORDER):
        payload = drill_payloads.get(stage)
        if payload is None:
            # Default to a stub so the chain is complete (every recommendation
            # has all 5 stages per Section 5.2; missing payloads → empty drill).
            payload = {"stage": stage, "note": "no drill payload provided"}
        audit_id = uuid.uuid4()
        # Use the same ``now`` for every stage in the chain. The chain
        # ordering invariant in ``audit_trail.hmac_verify.verify_chain``
        # is ``parent.created_at <= r.created_at`` (inclusive ``<=``), so
        # equal timestamps satisfy it without needing a millisecond stagger.
        # Per v3 spec Section 5 Q1.
        ts = now
        canonical = {
            "audit_id": str(audit_id),
            "recommendation_id": str(rec_id),
            "stage": stage,
            "drill_payload": dict(payload),
            "parent_audit_id": str(parent) if parent else None,
            "versions": dict(versions),
            "created_at": ts.isoformat(),
        }
        sig = compute_signature_dict(canonical, key)
        rows.append(
            {
                "audit_id": audit_id,
                "recommendation_id": rec_id,
                "stage": stage,
                "drill_payload": dict(payload),
                "hmac_signature": sig,
                "parent_audit_id": parent,
                "versions": dict(versions),
                "created_at": ts,
            }
        )
        parent = audit_id
    return rows


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------


def emit_recommendation(
    inp: EmitInputs,
    *,
    conn: Any = None,
    hmac_key: Optional[bytes] = None,
) -> EmitOutcome:
    """Compose, sign, and persist one execution_recommendations row + chain.

    Args:
        inp: bundle of upstream inputs.
        conn: psycopg-style connection. None → dry-run; HMAC computed and
            EmitOutcome returned but no DB write.
        hmac_key: explicit HMAC key bytes. Falls back to AUDIT_HMAC_KEY env.

    Per v3 spec Section 4.6 Q1 + Section 5 Q1 + Section 7 Q4.
    """
    key = _read_audit_key(hmac_key)
    now = inp.now or _dt.datetime.now(_dt.timezone.utc)

    # 1. Sizing.
    sizing_ctx = SizingContext(
        mode=inp.mode,
        available_cash_pct=inp.available_cash_pct,
        portfolio_underperformance_pp_vs_bench=(
            inp.portfolio_underperformance_pp_vs_bench
        ),
        s0_vol_z=inp.s0_vol_z,
    )
    sizing: SizingSuggestion = compute_sizing(sizing_ctx)

    # 2. Conviction rollup (deterministic).
    conv_in = ConvictionInputs(
        debate_add_count=inp.debate_add_count,
        kills_fired=inp.kills_fired,
        counterfactual_top_3=list(inp.counterfactual_top_3),
        anchor_drift_channels_triggered=inp.anchor_drift_channels_triggered,
    )
    conv: ConvictionRollup = roll_up_conviction(conv_in)

    # 3. Hysteresis.
    hyst_in = HysteresisInputs(
        proposed_bucket=conv.bucket,
        prior_bucket=inp.prior_conviction_bucket,
        prior_pending_target=inp.prior_pending_target,
        prior_pending_transition=inp.prior_pending_transition,
        flip_history_30d=list(inp.flip_history_30d),
        now_date=now.date(),
    )
    hyst: HysteresisResult = apply_hysteresis(hyst_in)

    # 4. Risk flags + execution_context.
    risk_flags = aggregate_risk_flags(
        s0_regime_state=inp.s0_regime_state,
        s2_counterfactual_top_3=list(inp.counterfactual_top_3),
        s4_smart_money=inp.s4_smart_money,
        extra=list(inp.extra_risk_flags),
    )
    exec_ctx: ExecutionContext = build_execution_context(
        current_price=inp.current_price,
        fair_value_payload=inp.fair_value_payload,
        near_term_catalysts_raw=inp.near_term_catalysts_raw,
        suggested_pacing=inp.suggested_pacing,
        technical_signals_raw=inp.technical_signals_raw,
        risk_flags=risk_flags,
    )

    # 5. Trigger metadata.
    trig_in = TriggerInputs(
        mode=inp.mode,
        triggered_by=inp.triggered_by,
        now=now,
        materiality_event_ref=inp.materiality_event_ref,
        prior_recommendation=inp.prior_recommendation,
        prior_recommendation_date=inp.prior_recommendation_date,
        new_recommendation=inp.primary_recommendation,
    )
    trig: TriggerMetadata = compute_trigger_metadata(trig_in)

    # 6. Compose conviction_breakdown JSONB (Section 4.6 Q1 schema).
    conviction_breakdown = {
        "debate_consensus": inp.debate_consensus_summary,
        "kills_fired": f"{inp.kills_fired} of 7",
        "counterfactual_top_3": list(inp.counterfactual_top_3),
        "mode_certainty": (
            "rule-clean (no LLM tie-breaker)"
            if inp.mode_certainty == "rule_clean"
            else "llm_tiebreaker"
        ),
        "drift_channels": (
            f"{inp.anchor_drift_channels_triggered} of 3 triggered"
        ),
        "rolled_up_via": conv.breakdown.get("rolled_up_via"),
        "hysteresis_rationale": hyst.rationale,
        "triggered_rules": conv.triggered_rules,
    }

    # 7. Compose row.
    rec_id = uuid.uuid4()
    row: dict[str, Any] = {
        "recommendation_id": rec_id,
        "ticker": inp.ticker,
        "date": now.date(),
        "recommendation": inp.primary_recommendation,
        "conviction": hyst.effective_bucket,
        "conviction_breakdown": conviction_breakdown,
        # State-machine columns — not signed.
        "conviction_pending_transition": hyst.pending_transition,
        "conviction_pending_target": hyst.pending_target,
        "conviction_changed_from_prior": (
            inp.prior_conviction_bucket is not None
            and inp.prior_conviction_bucket != hyst.effective_bucket
        ),
        "conviction_flip_count_30d": hyst.flip_count_30d,
        "conviction_frozen_pending_review": hyst.frozen_pending_review,
        "mode": inp.mode,
        "company_quality_flag": inp.company_quality_flag,
        "mode_certainty": inp.mode_certainty,
        "sizing_suggestion": sizing.to_payload(),
        "execution_context": exec_ctx.to_payload(),
        "trigger_metadata": trig.to_payload(),
        "audit_available": True,
        "rule_engine_version": inp.rule_engine_version,
        "debate_prompt_version": inp.debate_prompt_version,
        "model_id": inp.model_id,
        "model_version": inp.model_version,
        "parameters_version": (
            str(inp.parameters_version) if inp.parameters_version else None
        ),
        "created_at": now,
    }

    # 8. Sign canonical projection.
    canonical = _row_canonical_payload(row)
    # uuid + datetime serializers handled by canonical_payload_dict._json_default.
    audit_signature = compute_signature_dict(canonical, key)
    row["audit_signature"] = audit_signature

    # 9. Build per-stage audit_provenance chain.
    versions_bundle = {
        "rule_engine_version": inp.rule_engine_version,
        "debate_prompt_version": inp.debate_prompt_version,
        "model_id": inp.model_id,
        "model_version": inp.model_version,
        "parameters_version": (
            str(inp.parameters_version) if inp.parameters_version else None
        ),
    }
    audit_rows = _build_audit_chain(
        rec_id=rec_id,
        drill_payloads=inp.stage_drill_payloads,
        versions=versions_bundle,
        now=now,
        key=key,
    )

    outcome = EmitOutcome(
        recommendation_id=rec_id,
        ticker=inp.ticker,
        recommendation=row["recommendation"],
        conviction=row["conviction"],
        audit_signature=audit_signature,
        audit_chain_ids=[r["audit_id"] for r in audit_rows],
        sizing_payload=row["sizing_suggestion"],
        conviction_breakdown=row["conviction_breakdown"],
        trigger_metadata=row["trigger_metadata"],
        execution_context=row["execution_context"],
        escalate_m2=hyst.escalate_m2,
    )

    if conn is None:
        return outcome

    _persist(conn, row, audit_rows)
    return outcome


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _persist(conn: Any, row: dict, audit_rows: list[dict]) -> None:
    """Write execution_recommendations + audit_provenance rows atomically.

    Atomicity contract (per Section 5 Q1 audit-chain lock):
        The execution_recommendations row + ALL N audit_provenance chain
        rows MUST commit together or not at all. A partial write (e.g.,
        the recommendation row commits but the chain breaks midway through
        the per-stage INSERTs) leaves an unverifiable audit chain — an
        operator running ``/audit-trail`` would see a recommendation with
        a missing parent link, which the tamper-evidence verifier would
        flag as ``audit-chain-broken``.

    We wrap the writes in an explicit transaction:
      * psycopg3 (``conn.transaction()`` available) — preferred. The
        context-manager ROLLBACKs on exception and COMMITs on clean exit.
      * psycopg2 / fallback — emit BEGIN + COMMIT/ROLLBACK manually iff
        ``conn.autocommit`` is True (otherwise the caller already owns
        the txn boundary and we just delegate to its eventual commit).

    Test fakes that lack ``transaction``/``autocommit`` degrade gracefully
    (no transaction boundary; a single-shot test won't notice).
    """
    txn = getattr(conn, "transaction", None)
    if callable(txn):
        # psycopg3 path — atomic block.
        with txn():
            _do_persist(conn, row, audit_rows)
        return

    # psycopg2 / legacy path.
    autocommit_was_on = bool(getattr(conn, "autocommit", False))
    began = False
    if autocommit_was_on:
        # Force a transaction window for the multi-row write.
        try:
            conn.autocommit = False
            began = True
        except Exception:  # pragma: no cover - test conn may not allow toggling
            began = False

    raised = False
    try:
        _do_persist(conn, row, audit_rows)
    except Exception:
        raised = True
        if hasattr(conn, "rollback"):
            try:
                conn.rollback()
            except Exception:  # pragma: no cover
                pass
        raise
    finally:
        # Restore autocommit setting either way (don't leak our toggling).
        if began:
            try:
                conn.autocommit = True
            except Exception:  # pragma: no cover
                pass
    if raised:
        # Defensive: should not reach here because `raise` above re-raised,
        # but keeps the type-flow explicit.
        return  # pragma: no cover

    # Clean path — commit the multi-row write as a unit.
    if hasattr(conn, "commit"):
        try:
            conn.commit()
        except Exception:  # pragma: no cover
            pass


def _do_persist(conn: Any, row: dict, audit_rows: list[dict]) -> None:
    """Inner write routine — the actual N+1 INSERTs."""
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO execution_recommendations (
                recommendation_id, ticker, date,
                recommendation, conviction, conviction_breakdown,
                conviction_pending_transition, conviction_pending_target,
                conviction_changed_from_prior, conviction_flip_count_30d,
                conviction_frozen_pending_review,
                mode, company_quality_flag, mode_certainty,
                sizing_suggestion, execution_context, trigger_metadata,
                audit_available,
                rule_engine_version, debate_prompt_version,
                model_id, model_version, parameters_version,
                audit_signature, created_at
            ) VALUES (
                %s, %s, %s,
                %s, %s, %s::jsonb,
                %s, %s, %s, %s, %s,
                %s, %s, %s,
                %s::jsonb, %s::jsonb, %s::jsonb,
                %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                str(row["recommendation_id"]),
                row["ticker"],
                row["date"],
                row["recommendation"],
                row["conviction"],
                json.dumps(row["conviction_breakdown"], default=_json_default),
                row["conviction_pending_transition"],
                row["conviction_pending_target"],
                row["conviction_changed_from_prior"],
                row["conviction_flip_count_30d"],
                row["conviction_frozen_pending_review"],
                row["mode"],
                row["company_quality_flag"],
                row["mode_certainty"],
                json.dumps(row["sizing_suggestion"], default=_json_default),
                json.dumps(row["execution_context"], default=_json_default),
                json.dumps(row["trigger_metadata"], default=_json_default),
                row["audit_available"],
                row["rule_engine_version"],
                row["debate_prompt_version"],
                row["model_id"],
                row["model_version"],
                row["parameters_version"],
                row["audit_signature"],
                row["created_at"],
            ),
        )
        for ar in audit_rows:
            cur.execute(
                """
                INSERT INTO audit_provenance (
                    audit_id, recommendation_id, stage,
                    drill_payload, hmac_signature, parent_audit_id,
                    versions, created_at
                ) VALUES (
                    %s, %s, %s,
                    %s::jsonb, %s, %s,
                    %s::jsonb, %s
                )
                """,
                (
                    str(ar["audit_id"]),
                    str(ar["recommendation_id"]),
                    ar["stage"],
                    json.dumps(ar["drill_payload"], default=_json_default),
                    ar["hmac_signature"],
                    str(ar["parent_audit_id"]) if ar["parent_audit_id"] else None,
                    json.dumps(ar["versions"], default=_json_default),
                    ar["created_at"],
                ),
            )
    finally:
        cur.close()


__all__ = [
    "AUDIT_HMAC_ENV",
    "EmitInputs",
    "EmitOutcome",
    "P7EmitError",
    "emit_recommendation",
]
