"""End-to-end orchestrator — Phase A -> B -> C-conditional -> D + persistence.

Per v3 spec Section 2.3 + Section 4.8 + migration
``013_v3_calibration_capture.sql`` table ``debate_consensus_history``.

Pipeline::

    P4Inputs(ticker, mode, sector?, candidate_facts, scenarios?, lane_refs?,
             s0_regime_context?)
        |
        +--> Phase A (5 styles parallel; isolated; Sonnet)
        |
        +--> Phase B (5 styles parallel; locked claims; Sonnet)
        |
        +--> Phase C judge (single Opus call; Type 1/2/3 conflict detection)
        |        |
        |        +-- if phase_c_needed: Phase C negotiation (3 rounds max; Sonnet)
        |
        +--> Phase D PMSupervisor synthesis (Opus; dissent preservation enforced)
        |
        +--> persist row to debate_consensus_history (append-only)

The persistence layer follows the same pattern as
``mode_classifier.orchestrator.classify_ticker`` — the orchestrator is
DB-aware but degrades gracefully (it can be run in-memory only with
``persist=False`` for tests + dry-runs).

The Evaluator hard-gate (``.claude/agents/evaluator.md``) runs OUTSIDE
this pipeline per Section 2.4 finding 3 — DO NOT integrate it here.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from . import (
    MODEL_OPUS,
    MODEL_SONNET,
    PROMPT_VERSION_PHASE_D,
)
from .phase_a_isolated import PhaseAResult, run_phase_a
from .phase_b_locked import PhaseBLockedSet, run_phase_b
from .phase_c_judge import PhaseCJudgeResult, run_phase_c_judge
from .phase_c_negotiation import PhaseCNegotiationResult, run_phase_c_negotiation
from .phase_d_pm_supervisor import PhaseDSynthesis, run_phase_d

_LOG = logging.getLogger(__name__)


@dataclass
class P4Inputs:
    """Bundled inputs for one debate run."""

    ticker: str
    mode: str  # B / B_prime / C
    candidate_facts: str  # verbatim block
    scenarios: str = ""  # P2 scenario set (text)
    lane_refs: str = ""  # L1 / L3 reference text
    s0_regime_context: Optional[str] = None  # only for macro_regime
    sector: Optional[str] = None  # for sector overrides
    recommendation_id: Optional[uuid.UUID] = None  # forward-ref
    parameters_version: Optional[uuid.UUID] = None


@dataclass
class P4DebateResult:
    """Full debate output, ready for persistence + downstream consumption."""

    debate_id: uuid.UUID
    ticker: str
    debate_date: _dt.date
    phase_a: PhaseAResult
    phase_b: PhaseBLockedSet
    phase_c_judge: PhaseCJudgeResult
    phase_c_negotiation: Optional[PhaseCNegotiationResult]
    phase_d: PhaseDSynthesis
    debate_prompt_version: str = PROMPT_VERSION_PHASE_D
    model_id: str = MODEL_OPUS
    model_version: str = MODEL_OPUS  # alias for migration column

    def per_style_outputs_payload(self) -> dict:
        """Build the JSONB payload for ``debate_consensus_history.per_style_outputs``.

        Schema per migration 013::

            {
              <style_id>: {
                verdict, claims, non_negotiables, weight,
                phase_a_preliminary: {...},
                phase_c_refinement: {...} | null
              },
              ...
            }
        """
        out: dict[str, dict] = {}
        weights = self.phase_d.weights_used
        last_round = (
            self.phase_c_negotiation.rounds[-1]
            if self.phase_c_negotiation and self.phase_c_negotiation.rounds
            else None
        )
        for sid, lk in self.phase_b.locks.items():
            phase_a_out = self.phase_a.per_style.get(sid)
            refinement = (
                last_round.per_style.get(sid).to_payload()
                if (last_round and sid in last_round.per_style)
                else None
            )
            out[sid] = {
                "verdict": lk.verdict,
                "rationale": lk.rationale,
                "load_bearing_claims": [
                    {
                        "id": c.claim_id,
                        "text": c.text,
                        "supports_recommendation": c.supports_recommendation,
                    }
                    for c in lk.load_bearing_claims
                ],
                "non_negotiables": [
                    {"id": n.constraint_id, "text": n.text}
                    for n in lk.non_negotiables
                ],
                "weight": weights.get(sid, 0.0),
                "phase_a_preliminary": (
                    {
                        "verdict": phase_a_out.preliminary_verdict,
                        "rationale": phase_a_out.preliminary_rationale,
                        "key_observations": phase_a_out.key_observations,
                        "regime_sensitivity": phase_a_out.regime_sensitivity,
                    }
                    if phase_a_out
                    else None
                ),
                "phase_c_refinement": refinement,
            }
        return out

    def phase_d_synthesis_payload(self) -> dict:
        """Build the JSONB payload for ``debate_consensus_history.phase_d_synthesis``."""
        return {
            "final_decision": self.phase_d.decision,
            "recommended_conviction": self.phase_d.recommended_conviction,
            "dissent_trace": [d.to_payload() for d in self.phase_d.dissent_trace],
            "override_reasoning": self.phase_d.override_reasoning,
            "non_negotiables_not_addressed": [
                n.to_payload()
                for n in self.phase_d.non_negotiables_not_addressed
            ],
            "mode": self.phase_d.mode,
            "sector": self.phase_d.sector,
            "weights_used": dict(self.phase_d.weights_used),
            "phase_c": {
                "phase_c_triggered": self.phase_c_judge.phase_c_needed,
                "judge_confidence": self.phase_c_judge.judge_confidence,
                "conflict_count": len(self.phase_c_judge.conflicts),
                "rounds_run": (
                    len(self.phase_c_negotiation.rounds)
                    if self.phase_c_negotiation
                    else 0
                ),
                "resolved_conflicts": (
                    list(self.phase_c_negotiation.resolved_conflicts)
                    if self.phase_c_negotiation
                    else []
                ),
                "unresolved_conflicts": (
                    list(self.phase_c_negotiation.unresolved_conflicts)
                    if self.phase_c_negotiation
                    else []
                ),
            },
        }


# --------------------------------------------------------------------------- #
# Persistence                                                                 #
# --------------------------------------------------------------------------- #


def persist_debate(
    *,
    result: P4DebateResult,
    recommendation_id: Optional[uuid.UUID],
    conn: Any,
) -> uuid.UUID:
    """Append a row to ``debate_consensus_history`` (append-only).

    ``conn`` is a psycopg / psycopg2 connection-like object with
    ``cursor()`` returning an object that supports ``execute(sql, args)``
    and is a context-manager. We use named-args plain SQL so this works
    against psycopg v3 and psycopg2 alike.
    """
    sql = """
        INSERT INTO debate_consensus_history (
            debate_id,
            recommendation_id,
            ticker,
            debate_date,
            per_style_outputs,
            phase_c_triggered,
            phase_c_judge_confidence,
            phase_d_synthesis,
            debate_prompt_version,
            model_id,
            model_version
        ) VALUES (
            %(debate_id)s,
            %(recommendation_id)s,
            %(ticker)s,
            %(debate_date)s,
            %(per_style_outputs)s::jsonb,
            %(phase_c_triggered)s,
            %(phase_c_judge_confidence)s,
            %(phase_d_synthesis)s::jsonb,
            %(debate_prompt_version)s,
            %(model_id)s,
            %(model_version)s
        )
    """
    args = {
        "debate_id": str(result.debate_id),
        "recommendation_id": str(recommendation_id) if recommendation_id else None,
        "ticker": result.ticker,
        "debate_date": result.debate_date,
        "per_style_outputs": json.dumps(result.per_style_outputs_payload()),
        "phase_c_triggered": result.phase_c_judge.phase_c_needed,
        "phase_c_judge_confidence": result.phase_c_judge.judge_confidence,
        "phase_d_synthesis": json.dumps(result.phase_d_synthesis_payload()),
        "debate_prompt_version": result.debate_prompt_version,
        "model_id": result.model_id,
        "model_version": result.model_version,
    }
    with conn.cursor() as cur:
        cur.execute(sql, args)
    if hasattr(conn, "commit"):
        conn.commit()
    return result.debate_id


# --------------------------------------------------------------------------- #
# End-to-end runner                                                           #
# --------------------------------------------------------------------------- #


def run_debate(
    inputs: P4Inputs,
    *,
    client: Any = None,
    sonnet_model: str = MODEL_SONNET,
    opus_model: str = MODEL_OPUS,
    parallel: bool = True,
    persist: bool = False,
    conn: Any = None,
) -> P4DebateResult:
    """Run Phase A -> B -> C-conditional -> D end-to-end.

    Args:
        inputs: Bundle of inputs (ticker, mode, candidate facts, etc.).
        client: Optional pre-built Anthropic client (single client used
            across all phases).
        sonnet_model: Model id for Phase A / B / C-negotiation.
        opus_model: Model id for Phase C-judge / Phase D.
        parallel: Run within-phase styles in a thread pool (default True).
        persist: If True, append a row to ``debate_consensus_history``.
        conn: Required when ``persist=True``; psycopg-compatible
            connection.

    Returns:
        :class:`P4DebateResult` with all phases populated + row id.
    """
    debate_id = uuid.uuid4()
    # Use UTC date — ``date.today()`` reads the server's local timezone, so
    # ``debate_date`` (persisted to ``debate_consensus_history``) would
    # off-by-one near the UTC day boundary on any non-UTC server.
    debate_date = _dt.datetime.now(_dt.timezone.utc).date()

    _LOG.info(
        "P4 debate start: ticker=%s mode=%s sector=%s debate_id=%s",
        inputs.ticker, inputs.mode, inputs.sector, debate_id,
    )

    phase_a = run_phase_a(
        ticker=inputs.ticker,
        candidate_facts=inputs.candidate_facts,
        lane_refs=inputs.lane_refs,
        scenarios=inputs.scenarios,
        s0_regime_context=inputs.s0_regime_context,
        client=client,
        model=sonnet_model,
        parallel=parallel,
    )
    _LOG.info(
        "Phase A complete: %d styles produced output",
        len(phase_a.per_style),
    )

    phase_b = run_phase_b(
        phase_a=phase_a,
        candidate_facts=inputs.candidate_facts,
        client=client,
        model=sonnet_model,
        parallel=parallel,
    )
    _LOG.info(
        "Phase B complete: %d styles locked claims",
        len(phase_b.locks),
    )

    judge_result = run_phase_c_judge(
        locked=phase_b,
        client=client,
        model=opus_model,
    )
    _LOG.info(
        "Phase C judge: needed=%s confidence=%.2f conflicts=%d",
        judge_result.phase_c_needed,
        judge_result.judge_confidence,
        len(judge_result.conflicts),
    )

    negotiation: Optional[PhaseCNegotiationResult] = None
    if judge_result.phase_c_needed and judge_result.conflicts:
        negotiation = run_phase_c_negotiation(
            locked=phase_b,
            judge_result=judge_result,
            client=client,
            model=sonnet_model,
            parallel=parallel,
        )
        _LOG.info(
            "Phase C negotiation: %d rounds, %d resolved, %d unresolved",
            len(negotiation.rounds),
            len(negotiation.resolved_conflicts),
            len(negotiation.unresolved_conflicts),
        )

    phase_d = run_phase_d(
        phase_a=phase_a,
        locked=phase_b,
        judge_result=judge_result,
        negotiation=negotiation,
        mode=inputs.mode,
        sector=inputs.sector,
        client=client,
        model=opus_model,
    )
    _LOG.info(
        "Phase D synthesis: decision=%s conviction=%.2f dissenters=%d",
        phase_d.decision,
        phase_d.recommended_conviction,
        sum(1 for d in phase_d.dissent_trace if d.verdict != phase_d.decision),
    )

    result = P4DebateResult(
        debate_id=debate_id,
        ticker=inputs.ticker,
        debate_date=debate_date,
        phase_a=phase_a,
        phase_b=phase_b,
        phase_c_judge=judge_result,
        phase_c_negotiation=negotiation,
        phase_d=phase_d,
        model_id=opus_model,
        model_version=opus_model,
    )

    if persist:
        if conn is None:
            raise ValueError(
                "persist=True requires a `conn` (psycopg-compatible connection)"
            )
        persist_debate(
            result=result,
            recommendation_id=inputs.recommendation_id,
            conn=conn,
        )
        _LOG.info("Persisted debate row id=%s", result.debate_id)

    return result


__all__ = [
    "P4Inputs",
    "P4DebateResult",
    "run_debate",
    "persist_debate",
]
