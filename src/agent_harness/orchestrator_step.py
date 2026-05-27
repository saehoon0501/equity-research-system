"""Per-attempt orchestrator step — stateful CLI for /research-company.

The orchestrator (an LLM running prompted procedure in the main session)
cannot itself express a multi-iteration retry loop with fingerprint
deduplication and cost ledgers reliably in prose. This module is the
state machine, called once per attempt via Bash.

Per-attempt contract:

    Orchestrator dispatches Agent(agent_type, prompt) → envelope at <path>.
    Orchestrator runs: python3 -m src.agent_harness.orchestrator_step \\
                           --envelope <path> \\
                           --run-id <uuid> \\
                           --agent-type pm-supervisor \\
                           --attempt-cost-usd <cost> \\
                           [--case-ids <ids>] \\
                           [--catalyst-indicators <path>] \\
                           [--max-attempts 3] \\
                           [--cost-ceiling-usd 60]
    Script reads state at logs/validation_state/<run_id>__<agent_type>.json
    Script runs validate_all on the envelope.
    Script appends to state, decides PASS/RETRY/ESCALATE, writes:
        - logs/validation_attempts.jsonl   (append-only audit row)
        - logs/validation_state/...json    (running state)
        - stdout: structured JSON the orchestrator parses
    Exit codes:
        0  PASS — validation succeeded; orchestrator proceeds.
       10  RETRY — validation failed but recoverable; stdout carries the
                   delta-prompt body for the next Agent dispatch.
       11  ESCALATE — terminal failure (stuck loop, cost ceiling, max
                      attempts); orchestrator halts and surfaces the
                      stdout error report.
        2  Unparseable input or arguments.

This design keeps the retry control flow in code (deterministic, testable)
while leaving the actual Agent re-dispatch where it must live — in the
orchestrator session.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from src.agent_harness.delta_prompt import build_delta_prompt
from src.evaluator_gates import VALID_ARTIFACT_TYPES, validate_all

logger = logging.getLogger(__name__)

# WS-6 hybrid gate id whose result_dict carries the canonical gate_decision
# block ({verdict, deterministic, advisory, escalated}). Kept as a literal so
# this module has no import dependency on the hybrid-gate module.
_HYBRID_GATE_ID = "HG-40"

# Phase-2 axis enrichment (P2-A) is opt-in and default-OFF — it can hit LLMs,
# so the hot validation path stays cheap unless explicitly enabled. Mirrors
# the llm_cache LLM_CACHE_ENABLED truthy convention (1/true/yes/on).
_INSIGHT_SCORING_FLAG = "INSIGHT_SCORING_ENABLED"


def _flag_enabled(name: str, env: dict[str, str] | None = None) -> bool:
    """Default-OFF env flag parse (mirrors llm_cache convention)."""
    env = os.environ if env is None else env
    return str(env.get(name, "")).strip().lower() in ("1", "true", "yes", "on")


def _extract_gate_decision(validation: Any) -> dict[str, Any] | None:
    """Pull the hybrid gate's result_dict['gate_decision'], or None.

    Locates the HG-40 outcome in the AggregateValidationResult and returns its
    canonical gate_decision block. Returns None when the hybrid gate did not
    run or did not emit a gate_decision (caller then skips silently).
    """
    for g in getattr(validation, "gates", []) or []:
        if getattr(g, "gate_id", None) == _HYBRID_GATE_ID:
            rd = getattr(g, "result_dict", None)
            if isinstance(rd, dict):
                gd = rd.get("gate_decision")
                if isinstance(gd, dict):
                    return gd
            return None
    return None


def _enrich_envelope_poststep(
    *,
    envelope: dict[str, Any],
    envelope_path: Path,
    validation: Any,
    insight_scoring_enabled: bool,
) -> None:
    """Best-effort, decision-preserving envelope-file enrichment (P2-A).

    A PURE SIDE-EFFECT run AFTER the PASS/RETRY/ESCALATE decision is fixed:
      1. Persist the hybrid gate's gate_decision onto the envelope file
         (always on, cheap). Skipped silently when absent.
      2. When ``insight_scoring_enabled`` (default OFF), splice the advisory
         axis_a/axis_b blocks via the enrichment adapter.

    NEVER raises and NEVER changes the decision: any failure is logged and
    swallowed; the only effect is the envelope-file writeback. Returns early
    without touching the file when there is nothing to write.
    """
    try:
        out = dict(envelope)
        mutated = False

        gate_decision = _extract_gate_decision(validation)
        if gate_decision is not None:
            out["gate_decision"] = gate_decision
            mutated = True

        if insight_scoring_enabled:
            # Import lazily so the default-OFF hot path never imports the
            # scoring stack (which may pull heavier deps).
            from src.scoring.enrichment import enrich_envelope

            out = enrich_envelope(out)
            mutated = True

        if not mutated:
            return

        with open(envelope_path, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, default=str)
    except Exception as exc:  # noqa: BLE001 - never break the decision path
        logger.warning(
            "envelope enrichment post-step failed (decision unaffected): %s",
            exc,
        )


# Exit codes — keep stable; the orchestrator pattern-matches on these.
EXIT_PASS = 0
EXIT_USAGE_ERROR = 2
EXIT_RETRY = 10
EXIT_ESCALATE = 11

# Default thresholds — overridable per-invocation.
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_COST_CEILING_USD = 60.0


@dataclass
class StepState:
    """State persisted between attempts of the same (run_id, agent_type)."""

    run_id: str
    agent_type: str
    attempt_count: int = 0
    fingerprints: list[str] = field(default_factory=list)
    cumulative_cost_usd: float = 0.0
    status: Literal["in_progress", "passed", "escalated"] = "in_progress"
    last_escalation_reason: str | None = None
    created_at: float = field(default_factory=time.time)
    last_updated_at: float = field(default_factory=time.time)

    @classmethod
    def load(cls, path: Path) -> "StepState":
        """Load state from disk; return a fresh state if file doesn't exist."""
        if not path.exists():
            # Caller passes the run_id + agent_type via the path; we
            # reconstruct them from the filename in case the caller
            # didn't supply them on a fresh start.
            return cls(run_id="", agent_type="")
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        return cls(**d)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.last_updated_at = time.time()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2)


def _state_path(state_dir: Path, run_id: str, agent_type: str) -> Path:
    """Per-(run_id, agent_type) state file path."""
    safe_agent = agent_type.replace("/", "_")
    return state_dir / f"{run_id}__{safe_agent}.json"


def _append_audit_row(audit_path: Path, row: dict[str, Any]) -> None:
    """JSONL append for the audit log."""
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with open(audit_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")


@dataclass
class StepDecision:
    """What this attempt resolved to."""

    decision: Literal["PASS", "RETRY", "ESCALATE"]
    exit_code: int
    attempt_n: int
    fingerprint: str
    validation_summary: dict[str, str]
    failed_gate_ids: list[str]
    escalation_reason: str | None
    delta_prompt: str | None
    cumulative_cost_usd: float

    def to_stdout_payload(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "exit_code": self.exit_code,
            "attempt_n": self.attempt_n,
            "fingerprint": self.fingerprint,
            "validation_summary": self.validation_summary,
            "failed_gate_ids": self.failed_gate_ids,
            "escalation_reason": self.escalation_reason,
            "cumulative_cost_usd": self.cumulative_cost_usd,
            # delta_prompt is large — emitted as a separate top-level
            # field so the orchestrator can extract it whole and pass
            # straight to the next Agent dispatch.
            "delta_prompt": self.delta_prompt,
        }


def run_step(
    *,
    envelope_path: Path,
    run_id: str,
    agent_type: str,
    attempt_cost_usd: float,
    artifact_type: str = "pm_envelope",
    case_ids: list[str] | None = None,
    catalyst_indicators: list[dict] | None = None,
    resolve_evidence_db: bool = False,
    db_dsn: str | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    cost_ceiling_usd: float = DEFAULT_COST_CEILING_USD,
    state_dir: Path = Path("logs/validation_state"),
    audit_path: Path = Path("logs/validation_attempts.jsonl"),
    strict_envelope_shape: bool = False,
) -> StepDecision:
    """Process one attempt.

    Reads state, runs validators, updates state, builds delta-prompt if
    needed, returns a StepDecision.

    Args:
        envelope_path: path to the agent's just-returned envelope JSON.
        run_id: stable identifier for the /research-company run.
        agent_type: e.g. "pm-supervisor".
        attempt_cost_usd: cost of THIS attempt (orchestrator measures it).
        case_ids / catalyst_indicators / resolve_evidence_db / db_dsn /
            strict_envelope_shape: pass-through to validate_all.
        max_attempts: hard cap on attempts (default 3).
        cost_ceiling_usd: cumulative cost ceiling.
        state_dir: directory for per-run-per-agent state files.
        audit_path: append-only JSONL audit log.

    Returns:
        StepDecision with the decision + exit code.
    """
    state_path = _state_path(state_dir, run_id, agent_type)
    state = StepState.load(state_path)
    # Fresh-state path: filename-based reconstruction was skipped; set explicitly.
    if not state.run_id:
        state.run_id = run_id
        state.agent_type = agent_type

    # Pre-validate cost-ceiling guard: even though this attempt already
    # ran, if cumulative_cost + this attempt's cost ≥ ceiling, escalate
    # so the orchestrator doesn't try again.
    projected_cumulative = state.cumulative_cost_usd + attempt_cost_usd

    # Run validators on the just-returned envelope.
    with open(envelope_path, "r", encoding="utf-8") as f:
        envelope = json.load(f)

    validation = validate_all(
        envelope,
        artifact_type=artifact_type,
        resolve_evidence_db=resolve_evidence_db,
        case_ids_for_counterfactual=case_ids,
        db_dsn=db_dsn,
        catalyst_indicators=catalyst_indicators,
        strict_envelope_shape=strict_envelope_shape,
    )

    # Composite fingerprint across all failed gates (matches dispatcher
    # logic so behavior is identical whether invoked Python-side or
    # bash-side).
    fp_parts: list[str] = []
    for g in validation.gates:
        if not g.valid and g.error_fingerprint:
            fp_parts.append(f"{g.gate_id}:{g.error_fingerprint}")
    fingerprint = "|".join(sorted(fp_parts)) if fp_parts else "ok"

    # Update state: this attempt happened, cost accumulates, fingerprint
    # appended to history.
    state.attempt_count += 1
    state.cumulative_cost_usd = projected_cumulative
    state.fingerprints.append(fingerprint)

    failed_gate_ids = [g.gate_id for g in validation.failed_gates()]
    validation_summary = dict(validation.summary)

    audit_row = {
        "run_id": run_id,
        "agent_type": agent_type,
        "attempt_n": state.attempt_count,
        "fingerprint": fingerprint,
        "validation_passed": validation.valid,
        "validation_summary": validation_summary,
        "failed_gate_ids": failed_gate_ids,
        "attempt_cost_usd": attempt_cost_usd,
        "cumulative_cost_usd": state.cumulative_cost_usd,
        "envelope_path": str(envelope_path),
    }

    # ----- Phase-2 envelope-enrichment post-step (P2-A) ----------------
    # Pure side-effect on the envelope FILE, run after the decision inputs
    # (validation.valid + escalation guards below) are finalized. It writes
    # gate_decision (always) and — opt-in, default OFF — advisory axis_a/
    # axis_b. It never raises and never participates in the decision below.
    _enrich_envelope_poststep(
        envelope=envelope,
        envelope_path=envelope_path,
        validation=validation,
        insight_scoring_enabled=_flag_enabled(_INSIGHT_SCORING_FLAG),
    )

    # ----- PASS branch -------------------------------------------------
    if validation.valid:
        state.status = "passed"
        state.save(state_path)
        audit_row["decision"] = "PASS"
        _append_audit_row(audit_path, audit_row)
        return StepDecision(
            decision="PASS",
            exit_code=EXIT_PASS,
            attempt_n=state.attempt_count,
            fingerprint=fingerprint,
            validation_summary=validation_summary,
            failed_gate_ids=[],
            escalation_reason=None,
            delta_prompt=None,
            cumulative_cost_usd=state.cumulative_cost_usd,
        )

    # ----- Escalation guards ------------------------------------------
    escalation_reason: str | None = None

    # Stuck loop: same fingerprint twice in a row.
    if (
        len(state.fingerprints) >= 2
        and state.fingerprints[-1] == state.fingerprints[-2]
    ):
        escalation_reason = "stuck_loop"

    # Cost ceiling: projected cumulative already crossed.
    elif state.cumulative_cost_usd >= cost_ceiling_usd:
        escalation_reason = "cost_ceiling"

    # Max attempts: this WAS the last attempt and it failed.
    elif state.attempt_count >= max_attempts:
        escalation_reason = "max_attempts_exhausted"

    if escalation_reason is not None:
        state.status = "escalated"
        state.last_escalation_reason = escalation_reason
        state.save(state_path)
        audit_row["decision"] = "ESCALATE"
        audit_row["escalation_reason"] = escalation_reason
        _append_audit_row(audit_path, audit_row)
        return StepDecision(
            decision="ESCALATE",
            exit_code=EXIT_ESCALATE,
            attempt_n=state.attempt_count,
            fingerprint=fingerprint,
            validation_summary=validation_summary,
            failed_gate_ids=failed_gate_ids,
            escalation_reason=escalation_reason,
            delta_prompt=None,
            cumulative_cost_usd=state.cumulative_cost_usd,
        )

    # ----- RETRY branch ------------------------------------------------
    state.save(state_path)
    extra_context_lines = [
        f"This is attempt {state.attempt_count + 1} of {max_attempts}. "
        f"Cumulative cost so far: ${state.cumulative_cost_usd:.2f} "
        f"(ceiling ${cost_ceiling_usd:.2f})."
    ]
    # Point the retrying agent at the on-disk history rather than
    # duplicating it into prompt context. The agent has Read tool access
    # and can pull exactly the depth it needs.
    if state.attempt_count >= 2:
        extra_context_lines.append("")
        extra_context_lines.append(
            f"Prior-attempt history for this (run_id, agent_type) is "
            f"persisted on disk — read it before deciding your approach, "
            f"especially to confirm your last patch actually changed the "
            f"failure mode (vs. an identical-signature stuck loop):\n"
            f"  - Compact state (fingerprints[] across attempts, "
            f"cumulative cost, status): {state_path}\n"
            f"  - Per-attempt audit rows (filter by run_id + agent_type for "
            f"validation_summary, failed_gate_ids, decision per attempt): "
            f"{audit_path}"
        )
    delta_prompt = build_delta_prompt(
        validation,
        prior_artifact_path=str(envelope_path),
        agent_type=agent_type,
        extra_context="\n".join(extra_context_lines),
    )
    audit_row["decision"] = "RETRY"
    _append_audit_row(audit_path, audit_row)
    return StepDecision(
        decision="RETRY",
        exit_code=EXIT_RETRY,
        attempt_n=state.attempt_count,
        fingerprint=fingerprint,
        validation_summary=validation_summary,
        failed_gate_ids=failed_gate_ids,
        escalation_reason=None,
        delta_prompt=delta_prompt,
        cumulative_cost_usd=state.cumulative_cost_usd,
    )


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="orchestrator_step",
        description=(
            "Per-attempt validate + decide + delta-prompt step for "
            "/research-company. Exit 0 PASS / 10 RETRY / 11 ESCALATE / "
            "2 usage error."
        ),
    )
    parser.add_argument("--envelope", required=True, help="path to envelope/memo JSON")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--agent-type", required=True)
    parser.add_argument(
        "--artifact-type",
        default="pm_envelope",
        choices=VALID_ARTIFACT_TYPES,
        help=(
            "which gate set to run (pm_envelope | quant_memo | "
            "strategic_memo | catalyst_memo | cdd_memo); default pm_envelope"
        ),
    )
    parser.add_argument(
        "--attempt-cost-usd",
        type=float,
        required=True,
        help=(
            "best-effort cost estimate of the attempt that JUST produced "
            "the envelope being validated"
        ),
    )
    parser.add_argument(
        "--case-ids",
        default=None,
        help="comma-separated case_ids for counterfactual catalog check",
    )
    parser.add_argument(
        "--catalyst-indicators",
        default=None,
        help="path to JSON with catalyst-scout §4 indicator list",
    )
    parser.add_argument("--resolve-evidence-db", action="store_true")
    parser.add_argument("--db-dsn", default=None)
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=DEFAULT_MAX_ATTEMPTS,
    )
    parser.add_argument(
        "--cost-ceiling-usd",
        type=float,
        default=DEFAULT_COST_CEILING_USD,
    )
    parser.add_argument(
        "--state-dir",
        default="logs/validation_state",
        help="directory for per-(run_id, agent_type) state files",
    )
    parser.add_argument(
        "--audit-path",
        default="logs/validation_attempts.jsonl",
        help="JSONL audit log path (append-only)",
    )
    parser.add_argument("--strict-shape", action="store_true")
    args = parser.parse_args(argv)

    envelope_path = Path(args.envelope)
    if not envelope_path.is_file():
        sys.stderr.write(f"envelope file not found: {envelope_path}\n")
        return EXIT_USAGE_ERROR

    case_ids: list[str] | None = None
    if args.case_ids:
        case_ids = [c.strip() for c in args.case_ids.split(",") if c.strip()]

    catalyst_indicators: list[dict] | None = None
    if args.catalyst_indicators:
        ind_path = Path(args.catalyst_indicators)
        if not ind_path.is_file():
            sys.stderr.write(
                f"catalyst indicators file not found: {ind_path}\n"
            )
            return EXIT_USAGE_ERROR
        try:
            with open(ind_path, "r", encoding="utf-8") as f:
                parsed = json.load(f)
            if isinstance(parsed, list):
                catalyst_indicators = parsed
            elif isinstance(parsed, dict) and isinstance(
                parsed.get("indicators"), list
            ):
                catalyst_indicators = parsed["indicators"]
            else:
                sys.stderr.write(
                    "catalyst indicators must be a list or "
                    '{"indicators": [...]} dict\n'
                )
                return EXIT_USAGE_ERROR
        except (OSError, json.JSONDecodeError) as exc:
            sys.stderr.write(f"unable to parse catalyst indicators: {exc}\n")
            return EXIT_USAGE_ERROR

    try:
        decision = run_step(
            envelope_path=envelope_path,
            run_id=args.run_id,
            agent_type=args.agent_type,
            attempt_cost_usd=args.attempt_cost_usd,
            artifact_type=args.artifact_type,
            case_ids=case_ids,
            catalyst_indicators=catalyst_indicators,
            resolve_evidence_db=args.resolve_evidence_db,
            db_dsn=args.db_dsn,
            max_attempts=args.max_attempts,
            cost_ceiling_usd=args.cost_ceiling_usd,
            state_dir=Path(args.state_dir),
            audit_path=Path(args.audit_path),
            strict_envelope_shape=args.strict_shape,
        )
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"unable to read/parse envelope: {exc}\n")
        return EXIT_USAGE_ERROR

    sys.stdout.write(
        json.dumps(decision.to_stdout_payload(), indent=2, default=str) + "\n"
    )
    return decision.exit_code


if __name__ == "__main__":
    raise SystemExit(_cli())


__all__ = [
    "EXIT_PASS",
    "EXIT_RETRY",
    "EXIT_ESCALATE",
    "EXIT_USAGE_ERROR",
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_COST_CEILING_USD",
    "StepDecision",
    "StepState",
    "run_step",
]
