"""Retry-with-delta-prompt dispatcher.

Wraps a subagent dispatch with Tier-1 validation. On failure, builds a
targeted delta-prompt and re-dispatches. Bounded by:

- max_attempts (default 3)
- cost_ceiling_usd (default 60)
- stuck-loop fingerprint detection (escalate when the same error
  fingerprint appears twice in a row)

The dispatcher does NOT own the Agent-tool call. It accepts an
``agent_runner`` callable that returns a parsed envelope dict (and
optionally a written artifact path + cost estimate). This keeps the
harness deterministic + unit-testable without mocking the Agent tool.

Audit rows are appended to a JSON-lines file at
``logs/validation_attempts.jsonl`` per-run-id, OR to Postgres
``validation_attempts`` when ``--persist-pg`` and a DSN are configured.

DETERMINISM (in unit tests): pass a deterministic ``agent_runner`` and
``audit_sink``. The retry control flow is itself a pure state machine
over the AggregateValidationResult sequence.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, Protocol

from src.eval.gates import (
    AggregateValidationResult,
    validate_all,
)
from src.shared.agent_harness.delta_prompt import (
    build_delta_prompt,
    build_delta_prompt_spec,
    serialize_delta_prompt_spec,
)

logger = logging.getLogger(__name__)


# ---------- Result types -----------------------------------------------------


@dataclass
class AgentRunOutput:
    """What an ``agent_runner`` callable must return.

    Fields:
        artifact: parsed envelope dict (or any dict the validators accept).
        artifact_path: optional filesystem path where the artifact was
            persisted; used in the delta-prompt's "reuse prior" hint.
        cost_estimate_usd: best-effort cost estimate for this attempt.
        duration_ms: wall-clock for this attempt.
    """

    artifact: dict[str, Any]
    artifact_path: str | None = None
    cost_estimate_usd: float = 0.0
    duration_ms: int = 0


class AgentRunner(Protocol):
    """Callable signature the dispatcher expects.

    The orchestrator implements this by calling the Agent tool and
    parsing the returned artifact. In tests, pass a fake.
    """

    def __call__(self, prompt: str, *, attempt_n: int) -> AgentRunOutput: ...


# ---------- Audit sink ------------------------------------------------------


class AuditSink(Protocol):
    """Where validation_attempts rows get written.

    Implementations: JSONL file, Postgres, in-memory list (tests).
    """

    def write(self, row: dict[str, Any]) -> None: ...


class JsonlAuditSink:
    """Append-only JSONL sink under ``logs/validation_attempts.jsonl``."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, row: dict[str, Any]) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")


class InMemoryAuditSink:
    """Test-only sink that just retains rows in a list."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def write(self, row: dict[str, Any]) -> None:
        self.rows.append(dict(row))


# ---------- Attempt records + escalation -----------------------------------


EscalationReason = Literal[
    "stuck_loop",
    "cost_ceiling",
    "max_attempts_exhausted",
    "agent_error",
]


@dataclass
class AttemptRecord:
    """One attempt's outcome inside a DispatchResult."""

    attempt_n: int
    prompt_kind: Literal["initial", "delta"]
    error_fingerprint: str  # composite across all failed gates
    validation_passed: bool
    validation_summary: dict[str, str]
    failed_gate_ids: list[str]
    cost_estimate_usd: float
    duration_ms: int
    delta_prompt_hash: str | None  # hash of the delta-prompt sent (delta attempts only)
    artifact_path: str | None
    escalation_reason: EscalationReason | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class DispatchResult:
    """Result of a full dispatch-with-validation cycle."""

    agent_type: str
    run_id: str
    final_artifact: dict[str, Any] | None
    final_artifact_path: str | None
    final_validation: AggregateValidationResult | None
    attempts: list[AttemptRecord] = field(default_factory=list)
    cumulative_cost_usd: float = 0.0
    escalated: bool = False
    escalation_reason: EscalationReason | None = None

    @property
    def passed(self) -> bool:
        return (
            not self.escalated
            and self.final_validation is not None
            and self.final_validation.valid
        )

    @property
    def attempt_count(self) -> int:
        return len(self.attempts)


class DispatchEscalation(Exception):
    """Raised on terminal failure (stuck loop, cost ceiling, max attempts).

    Carries the full DispatchResult so the orchestrator can surface the
    audit trail to the operator.
    """

    def __init__(self, result: DispatchResult, reason: EscalationReason) -> None:
        super().__init__(
            f"dispatch escalated ({reason}) after {result.attempt_count} "
            f"attempt(s) for agent_type={result.agent_type}"
        )
        self.result = result
        self.reason = reason


# ---------- Core: dispatch_with_validation ----------------------------------


def _compute_error_fingerprint(result: AggregateValidationResult) -> str:
    """Composite fingerprint across all failed gates for stuck-loop detection.

    Two attempts that fail on the same (gate_id, error_fingerprint) tuples
    have an identical composite — that's how the loop detects "delta-prompt
    didn't land."
    """
    parts: list[str] = []
    for g in result.gates:
        if not g.valid and g.error_fingerprint:
            parts.append(f"{g.gate_id}:{g.error_fingerprint}")
    return "|".join(sorted(parts)) if parts else "ok"


def _hash_prompt(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


def dispatch_with_validation(
    *,
    agent_type: str,
    run_id: str,
    initial_prompt: str,
    agent_runner: AgentRunner,
    audit_sink: AuditSink | None = None,
    max_attempts: int = 3,
    cost_ceiling_usd: float = 60.0,
    resolve_evidence_db: bool = False,
    case_ids_for_counterfactual: list[str] | None = None,
    db_dsn: str | None = None,
    catalyst_indicators: list[dict] | None = None,
    strict_envelope_shape: bool = False,
) -> DispatchResult:
    """Dispatch + validate + retry loop.

    Args:
        agent_type: name of the agent being dispatched (for audit + prompt
            header). E.g. "pm-supervisor", "quantitative-analyst".
        run_id: stable identifier for the /research-company run.
        initial_prompt: the full agent prompt for attempt 1.
        agent_runner: callable that takes (prompt, attempt_n) and returns
            an AgentRunOutput. The orchestrator wraps the Agent tool here.
        audit_sink: where to write per-attempt audit rows. Defaults to a
            JSONL sink at logs/validation_attempts.jsonl.
        max_attempts: hard cap on attempts (default 3).
        cost_ceiling_usd: cumulative cost ceiling (default $60). Escalate
            when cumulative cost ≥ ceiling on the NEXT attempt boundary.
        resolve_evidence_db: pass-through to validate_all.
        case_ids_for_counterfactual: pass-through to validate_all.
        db_dsn: pass-through to validate_all.
        catalyst_indicators: pass-through to validate_all.
        strict_envelope_shape: pass-through to validate_all.

    Returns:
        DispatchResult with the final passing artifact, or escalates via
        DispatchEscalation.

    Raises:
        DispatchEscalation: on stuck-loop / cost-ceiling / max-attempts.
    """
    if audit_sink is None:
        audit_sink = JsonlAuditSink("logs/validation_attempts.jsonl")

    dispatch_result = DispatchResult(
        agent_type=agent_type,
        run_id=run_id,
        final_artifact=None,
        final_artifact_path=None,
        final_validation=None,
    )

    prompt = initial_prompt
    prompt_kind: Literal["initial", "delta"] = "initial"
    prior_fingerprints: list[str] = []
    delta_prompt_hash: str | None = None

    for attempt_n in range(1, max_attempts + 1):
        # Pre-attempt cost-ceiling guard: if we've already burned the
        # ceiling on prior attempts, escalate before spending more.
        if dispatch_result.cumulative_cost_usd >= cost_ceiling_usd:
            _escalate(
                dispatch_result, "cost_ceiling", audit_sink, run_id, agent_type
            )

        # Run the agent.
        run_start = time.time()
        try:
            run_output = agent_runner(prompt, attempt_n=attempt_n)
        except Exception as exc:  # noqa: BLE001 — surface as audit row
            _record_attempt(
                dispatch_result=dispatch_result,
                attempt_n=attempt_n,
                prompt_kind=prompt_kind,
                error_fingerprint=f"agent_error:{type(exc).__name__}",
                validation_passed=False,
                validation_summary={"agent_runner": "fail"},
                failed_gate_ids=[],
                cost_estimate_usd=0.0,
                duration_ms=int((time.time() - run_start) * 1000),
                delta_prompt_hash=delta_prompt_hash,
                artifact_path=None,
                audit_sink=audit_sink,
                run_id=run_id,
                agent_type=agent_type,
                notes=[f"agent_runner raised: {exc}"],
            )
            _escalate(
                dispatch_result,
                "agent_error",
                audit_sink,
                run_id,
                agent_type,
            )

        dispatch_result.cumulative_cost_usd += run_output.cost_estimate_usd

        # Validate.
        validation = validate_all(
            run_output.artifact,
            resolve_evidence_db=resolve_evidence_db,
            case_ids_for_counterfactual=case_ids_for_counterfactual,
            db_dsn=db_dsn,
            catalyst_indicators=catalyst_indicators,
            strict_envelope_shape=strict_envelope_shape,
        )
        fingerprint = _compute_error_fingerprint(validation)
        failed_gate_ids = [g.gate_id for g in validation.failed_gates()]

        _record_attempt(
            dispatch_result=dispatch_result,
            attempt_n=attempt_n,
            prompt_kind=prompt_kind,
            error_fingerprint=fingerprint,
            validation_passed=validation.valid,
            validation_summary=dict(validation.summary),
            failed_gate_ids=failed_gate_ids,
            cost_estimate_usd=run_output.cost_estimate_usd,
            duration_ms=run_output.duration_ms,
            delta_prompt_hash=delta_prompt_hash,
            artifact_path=run_output.artifact_path,
            audit_sink=audit_sink,
            run_id=run_id,
            agent_type=agent_type,
        )

        if validation.valid:
            dispatch_result.final_artifact = run_output.artifact
            dispatch_result.final_artifact_path = run_output.artifact_path
            dispatch_result.final_validation = validation
            return dispatch_result

        # Stuck-loop detection: same fingerprint twice in a row means
        # the delta-prompt isn't landing. Escalate without burning the
        # remaining attempts.
        if prior_fingerprints and prior_fingerprints[-1] == fingerprint:
            dispatch_result.final_artifact = run_output.artifact
            dispatch_result.final_artifact_path = run_output.artifact_path
            dispatch_result.final_validation = validation
            _escalate(
                dispatch_result, "stuck_loop", audit_sink, run_id, agent_type
            )
        prior_fingerprints.append(fingerprint)

        # If this was the final attempt, escalate as exhausted.
        if attempt_n >= max_attempts:
            dispatch_result.final_artifact = run_output.artifact
            dispatch_result.final_artifact_path = run_output.artifact_path
            dispatch_result.final_validation = validation
            _escalate(
                dispatch_result,
                "max_attempts_exhausted",
                audit_sink,
                run_id,
                agent_type,
            )

        # Build delta-prompt for the next attempt.
        prior_artifact_path = run_output.artifact_path
        prompt = build_delta_prompt(
            validation,
            prior_artifact_path=prior_artifact_path,
            agent_type=agent_type,
            extra_context=f"This is attempt {attempt_n + 1} of {max_attempts}.",
        )
        delta_prompt_hash = _hash_prompt(prompt)
        prompt_kind = "delta"

    # Unreachable — the in-loop escalations cover all exit paths.
    raise RuntimeError("dispatcher: unreachable loop exit")  # pragma: no cover


def _record_attempt(
    *,
    dispatch_result: DispatchResult,
    attempt_n: int,
    prompt_kind: Literal["initial", "delta"],
    error_fingerprint: str,
    validation_passed: bool,
    validation_summary: dict[str, str],
    failed_gate_ids: list[str],
    cost_estimate_usd: float,
    duration_ms: int,
    delta_prompt_hash: str | None,
    artifact_path: str | None,
    audit_sink: AuditSink,
    run_id: str,
    agent_type: str,
    notes: list[str] | None = None,
) -> None:
    record = AttemptRecord(
        attempt_n=attempt_n,
        prompt_kind=prompt_kind,
        error_fingerprint=error_fingerprint,
        validation_passed=validation_passed,
        validation_summary=validation_summary,
        failed_gate_ids=failed_gate_ids,
        cost_estimate_usd=cost_estimate_usd,
        duration_ms=duration_ms,
        delta_prompt_hash=delta_prompt_hash,
        artifact_path=artifact_path,
        notes=list(notes or []),
    )
    dispatch_result.attempts.append(record)
    audit_sink.write(
        {
            "run_id": run_id,
            "agent_type": agent_type,
            "attempt_n": attempt_n,
            "prompt_kind": prompt_kind,
            "error_fingerprint": error_fingerprint,
            "validation_passed": validation_passed,
            "validation_summary": validation_summary,
            "failed_gate_ids": failed_gate_ids,
            "cost_estimate_usd": cost_estimate_usd,
            "duration_ms": duration_ms,
            "delta_prompt_hash": delta_prompt_hash,
            "artifact_path": artifact_path,
            "cumulative_cost_usd": dispatch_result.cumulative_cost_usd,
            "notes": record.notes,
        }
    )


def _escalate(
    dispatch_result: DispatchResult,
    reason: EscalationReason,
    audit_sink: AuditSink,
    run_id: str,
    agent_type: str,
) -> "None":
    dispatch_result.escalated = True
    dispatch_result.escalation_reason = reason
    if dispatch_result.attempts:
        dispatch_result.attempts[-1].escalation_reason = reason
    audit_sink.write(
        {
            "run_id": run_id,
            "agent_type": agent_type,
            "escalation": reason,
            "attempts": dispatch_result.attempt_count,
            "cumulative_cost_usd": dispatch_result.cumulative_cost_usd,
        }
    )
    raise DispatchEscalation(dispatch_result, reason)


__all__ = [
    "AgentRunOutput",
    "AgentRunner",
    "AuditSink",
    "JsonlAuditSink",
    "InMemoryAuditSink",
    "AttemptRecord",
    "DispatchResult",
    "DispatchEscalation",
    "EscalationReason",
    "dispatch_with_validation",
]
