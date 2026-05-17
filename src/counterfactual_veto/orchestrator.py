"""End-to-end counterfactual VETO pipeline (v3 spec Section 4.5 Q6 d').

Composes the three layers + lifecycle persistence into a single decision call.

Pipeline:

    1. Layer 1 (cooling-off): if not expired → return WAIT.
    2. Layer 2 (multi-source): if not satisfied → cut blocked at L2 (returns
       a status that the recommendation emitter must surface to operator).
    3. Layer 3 (counterfactual VETO): retrieve top-3, classify archetype mix.
    4. Persist counterfactual_retrievals row + veto_lifecycle row.
    5. If veto_invoked AND archetype_distribution is SURVIVOR-dominant →
       fire an unread_alerts row of type='counterfactual_veto', severity=3
       (per migration 017 alert_type_extension allowing 'counterfactual_veto').

The orchestrator is the integration point — Layers 1/2/3 are pure functions
of their inputs, this module owns DB writes and clock dependencies.

Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
           Section 4.5 Q6 (3-layer architecture),
           Section 6 Q6 PB#5 (lifecycle persistence),
           Section 7 PB#4 (operator alert queue),
           db/migrations/{009,011,017}.
"""

from __future__ import annotations

import datetime as _dt
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Sequence

from . import MODE_2X_THRESHOLDS
from .feature_extractor import CandidateFeatures
from .layer1_cooling_off import CoolingOffStatus, evaluate_cooling_off
from .layer2_multi_source import (
    KillCriterionFire,
    MultiSourceStatus,
    PremortemLookupFn,
    evaluate_multi_source,
)
from .layer3_veto import VetoStatus, evaluate_veto, is_survivor_dominant
from .lifecycle import (
    PgExecuteFn,
    VetoLifecycleRecord,
    write_veto_lifecycle_row,
)
from .retrieval import CatalogCase


# Final cut-status labels (composite of all three layer outcomes).
CUT_STATUS_NOT_ACTIVATED_BELOW_2X = "not_activated_below_2x_threshold"
CUT_STATUS_WAIT_COOLING_OFF = "wait_cooling_off"
CUT_STATUS_BLOCKED_MULTI_SOURCE = "blocked_multi_source"
CUT_STATUS_BLOCKED_VETO = "blocked_veto_operator_override_required"
CUT_STATUS_MIXED_REVIEW = "blocked_veto_mixed_review_required"
CUT_STATUS_PROCEED = "proceed_per_mode_polarity"


@dataclass(frozen=True)
class VetoDecision:
    """Final pipeline output — composite of all 3 layer outcomes.

    Attributes:
        ticker:                  Candidate ticker.
        retrieval_id:            UUID of the counterfactual_retrievals row.
        veto_id:                 UUID of the veto_lifecycle row (None if veto
                                 not invoked).
        cut_status:              One of CUT_STATUS_* labels.
        cooling_off:             Layer 1 result.
        multi_source:            Layer 2 result (None if Layer 1 blocked).
        veto:                    Layer 3 result (None if Layer 1 or 2 blocked).
        m3_alert_fired:          True iff an unread_alerts row was inserted.
        rationale:               Human-readable summary for audit chain.
    """

    ticker: str
    retrieval_id: str
    veto_id: str | None
    cut_status: str
    cooling_off: CoolingOffStatus | None = None
    multi_source: MultiSourceStatus | None = None
    veto: VetoStatus | None = None
    m3_alert_fired: bool = False
    rationale: str = ""


@dataclass(frozen=True)
class PipelineInputs:
    """Bundle of inputs to ``run_pipeline`` (keeps signature manageable)."""

    ticker: str
    mode: str  # 'B' / 'B_prime' / 'C'
    candidate: CandidateFeatures
    catalog: list[CatalogCase]
    fires: Sequence[KillCriterionFire]
    trigger_event_at: _dt.datetime
    drawdown_vs_benchmark_pp: float
    parameters_version: str | None = None
    catalog_version_hash: str = "unknown"
    recommendation_ref: str | None = None


def _maybe_emit_unread_alert(
    *,
    ticker: str,
    veto: VetoStatus,
    retrieval_id: str,
    drawdown_pp: float,
    execute: PgExecuteFn,
) -> bool:
    """Insert an unread_alerts row when veto fires SURVIVOR-dominant.

    Per task brief: only fire the alert when both conditions hold:
      - veto_invoked is True (status != not_triggered)
      - archetype_distribution is SURVIVOR-dominant (≥2 SURVIVOR-leaning)

    Mixed-review status does NOT trip the alert at v0.1 — it's surfaced via
    /daily-monitor's existing mode_reclass / kill_criterion paths instead.
    """
    if not (veto.veto_invoked and is_survivor_dominant(veto.archetype_distribution)):
        return False

    payload = {
        "retrieval_id": retrieval_id,
        "archetype_distribution": dict(veto.archetype_distribution),
        "top_3_case_ids": [m.case.case_id for m in veto.top_3_matches],
        "drawdown_vs_benchmark_pp": drawdown_pp,
        "rationale": veto.rationale,
    }
    summary = (
        f"VETO fired for {ticker}: SURVIVOR-dominant top-3 "
        f"({payload['archetype_distribution']}); "
        f"cut blocked pending operator override"
    )

    sql = (
        "INSERT INTO unread_alerts "
        "(severity, alert_type, ticker, summary, payload) "
        "VALUES ($1, $2, $3, $4, $5::jsonb)"
    )
    execute(sql, (3, "counterfactual_veto", ticker, summary, json.dumps(payload)))
    return True


def _persist_retrieval_row(
    *,
    inputs: PipelineInputs,
    retrieval_id: str,
    veto: VetoStatus,
    execute: PgExecuteFn,
) -> None:
    """INSERT counterfactual_retrievals row (migration 011).

    Maps ``layer3_veto.VetoStatus.status`` → migration 011 CHECK enum:
        'not_triggered'              → 'not_triggered'
        'operator_override_required' → 'blocked'  (op override needed)
        'mixed_review_required'      → 'blocked'  (mixed mix → review)
        'blocked'                    → 'blocked'
    """
    db_status_map = {
        "not_triggered": "not_triggered",
        "operator_override_required": "blocked",
        "mixed_review_required": "blocked",
        "blocked": "blocked",
    }
    db_status = db_status_map.get(veto.status, "blocked")

    top_ids = [m.case.case_id for m in veto.top_3_matches]
    top_sims = [round(float(m.similarity), 6) for m in veto.top_3_matches]

    sql = (
        "INSERT INTO counterfactual_retrievals "
        "(retrieval_id, candidate_ticker, retrieval_date, "
        "drawdown_vs_benchmark_pp, top_3_case_ids, top_3_similarities, "
        "archetype_distribution, veto_invoked, veto_status, "
        "parameters_version, catalog_version_hash, recommendation_ref) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9, $10, $11, $12)"
    )
    execute(
        sql,
        (
            retrieval_id,
            inputs.ticker,
            # UTC date — ``date.today()`` reads the server's local timezone
            # and would write the wrong ``retrieval_date`` near the UTC day
            # boundary. DB ``retrieval_date`` is a UTC day key.
            _dt.datetime.now(_dt.timezone.utc).date().isoformat(),
            inputs.drawdown_vs_benchmark_pp,
            top_ids,
            top_sims,
            json.dumps(dict(veto.archetype_distribution)),
            bool(veto.veto_invoked),
            db_status,
            inputs.parameters_version,
            inputs.catalog_version_hash,
            inputs.recommendation_ref,
        ),
    )


def run_pipeline(
    inputs: PipelineInputs,
    *,
    premortem_lookup: PremortemLookupFn,
    execute: PgExecuteFn,
    now: _dt.datetime | None = None,
) -> VetoDecision:
    """Run the full 3-layer counterfactual veto pipeline.

    Args:
        inputs:           Bundle of pipeline inputs (PipelineInputs).
        premortem_lookup: Callable injected into Layer 2 multi-source check.
        execute:          DB execute callable for retrieval + lifecycle +
                          unread_alerts INSERTs.

                          ATOMICITY CONTRACT: when veto fires, this
                          function may invoke ``execute`` up to THREE
                          times (counterfactual_retrievals + veto_lifecycle
                          + unread_alerts). Caller MUST wrap ``execute``
                          in a single transaction so all three rows commit
                          together — otherwise a mid-pipeline failure
                          could persist a retrieval row + a veto_lifecycle
                          row WITHOUT firing the operator alert (silent
                          veto), or vice-versa (alert pointing at a
                          retrieval_id that never persisted). The
                          production wiring uses ``mcp__postgres__execute``
                          inside an explicit ``BEGIN``/``COMMIT`` block;
                          tests use a list-recording stub which is
                          implicitly atomic (in-memory).
        now:              Optional clock injection for tests.

    Returns:
        VetoDecision composite outcome.

    Activation gate (Section 4.5 Q6):
        Before any layer runs, drawdown_vs_benchmark_pp MUST be ≥ the mode's
        2× threshold (B/20pp, B'/24pp, C/30pp). On tiny drawdowns we short-
        circuit with cut_status='not_activated_below_2x_threshold' and emit no
        DB writes — the pipeline is gate-only at that point.
    """
    eval_now = now or _dt.datetime.now(_dt.timezone.utc)
    retrieval_id = str(uuid.uuid4())

    # ---------- Activation gate — 2× cut threshold ----------
    # Per v3 spec Section 4.5 Q6: pipeline is gated by the 2× threshold.
    # Drawdowns below the floor must NOT enter the 3-layer pipeline at all
    # (otherwise the pipeline runs on tiny drawdowns and may emit alerts /
    # DB writes for non-capitulation events).
    threshold_pp = MODE_2X_THRESHOLDS[inputs.mode]
    if abs(inputs.drawdown_vs_benchmark_pp) < threshold_pp:
        return VetoDecision(
            ticker=inputs.ticker,
            retrieval_id=retrieval_id,
            veto_id=None,
            cut_status=CUT_STATUS_NOT_ACTIVATED_BELOW_2X,
            cooling_off=None,
            multi_source=None,
            veto=None,
            m3_alert_fired=False,
            rationale=(
                f"Drawdown {abs(inputs.drawdown_vs_benchmark_pp):.2f}pp below "
                f"{threshold_pp}pp 2x threshold for mode {inputs.mode} — "
                f"pipeline not activated"
            ),
        )

    # ---------- Layer 1 — cooling-off ----------
    cooling = evaluate_cooling_off(
        mode=inputs.mode,
        trigger_event_at=inputs.trigger_event_at,
        now=eval_now,
    )

    if cooling.blocking:
        return VetoDecision(
            ticker=inputs.ticker,
            retrieval_id=retrieval_id,
            veto_id=None,
            cut_status=CUT_STATUS_WAIT_COOLING_OFF,
            cooling_off=cooling,
            rationale=(
                f"Layer 1 cooling-off floor active "
                f"({cooling.duration_h}h, mode {inputs.mode}, "
                f"{cooling.remaining_seconds // 3600}h remaining)"
            ),
        )

    # ---------- Layer 2 — multi-source confirmation ----------
    multi = evaluate_multi_source(
        ticker=inputs.ticker,
        fires=inputs.fires,
        premortem_lookup=premortem_lookup,
        evaluated_at=eval_now,
    )
    if not multi.all_satisfied:
        return VetoDecision(
            ticker=inputs.ticker,
            retrieval_id=retrieval_id,
            veto_id=None,
            cut_status=CUT_STATUS_BLOCKED_MULTI_SOURCE,
            cooling_off=cooling,
            multi_source=multi,
            rationale=(
                f"Layer 2 multi-source confirmation failed: "
                f"{multi.cut_blocked_reason}"
            ),
        )

    # ---------- Layer 3 — counterfactual VETO ----------
    veto = evaluate_veto(candidate=inputs.candidate, catalog=inputs.catalog)

    # Persist retrieval row (always — every pipeline run is logged).
    _persist_retrieval_row(
        inputs=inputs,
        retrieval_id=retrieval_id,
        veto=veto,
        execute=execute,
    )

    # Persist veto_lifecycle row when veto invoked.
    veto_id: str | None = None
    if veto.veto_invoked:
        veto_id = str(uuid.uuid4())
        record = VetoLifecycleRecord(
            veto_id=veto_id,
            retrieval_id=retrieval_id,
            ticker=inputs.ticker,
            initial_fire_date=eval_now.date(),
            status="active",
            last_archetype_distribution=dict(veto.archetype_distribution),
        )
        write_veto_lifecycle_row(record, execute=execute)

    # Maybe fire unread_alerts row (SURVIVOR-dominant only).
    alert_fired = _maybe_emit_unread_alert(
        ticker=inputs.ticker,
        veto=veto,
        retrieval_id=retrieval_id,
        drawdown_pp=inputs.drawdown_vs_benchmark_pp,
        execute=execute,
    )

    if veto.status == "operator_override_required":
        cut_status = CUT_STATUS_BLOCKED_VETO
    elif veto.status == "mixed_review_required":
        cut_status = CUT_STATUS_MIXED_REVIEW
    else:
        cut_status = CUT_STATUS_PROCEED

    return VetoDecision(
        ticker=inputs.ticker,
        retrieval_id=retrieval_id,
        veto_id=veto_id,
        cut_status=cut_status,
        cooling_off=cooling,
        multi_source=multi,
        veto=veto,
        m3_alert_fired=alert_fired,
        rationale=veto.rationale,
    )
