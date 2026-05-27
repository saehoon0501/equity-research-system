"""Agent harness — Tier-1 validate → retry-with-delta-prompt wrapper.

This package wraps every subagent dispatch in /research-company with a
validation hook + targeted retry loop. The flow per dispatch is:

    dispatch(agent, initial_prompt)
      → artifact returned
      → validate_all(artifact) [from src.eval.gates]
      → if pass: return DispatchResult
      → if fail: build_delta_prompt(errors, prior_artifact)
                 re-dispatch (≤3 attempts, stuck-loop + cost-ceiling guards)
                 escalate on exhaustion

The harness does NOT call the agent itself — it expects the caller (the
orchestrator) to pass an ``agent_runner`` callable that owns the actual
``Agent(...)`` tool invocation. This keeps the harness testable + the
Agent-tool dependency injectable.
"""

from src.shared.agent_harness.delta_prompt import (
    build_delta_prompt,
    build_delta_prompt_spec,
)
from src.shared.agent_harness.dispatcher import (
    AgentRunOutput,
    AttemptRecord,
    DispatchEscalation,
    DispatchResult,
    InMemoryAuditSink,
    JsonlAuditSink,
    dispatch_with_validation,
)

__all__ = [
    "AgentRunOutput",
    "AttemptRecord",
    "DispatchEscalation",
    "DispatchResult",
    "InMemoryAuditSink",
    "JsonlAuditSink",
    "build_delta_prompt",
    "build_delta_prompt_spec",
    "dispatch_with_validation",
]
