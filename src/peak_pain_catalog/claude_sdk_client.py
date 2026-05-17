"""Subscription-auth client adapter for the peak-pain catalog extractor.

Per BUILD_LOG.md decision 1 (Path A) the project does NOT use ANTHROPIC_API_KEY —
Claude Code is the runtime. This module wraps `claude-agent-sdk` so the
catalog's 3-LLM consensus pipeline can run against the operator's Max 20x
subscription via the local `claude` CLI's OAuth session, not against API
billing.

Replaces the prior ``get_anthropic_client_from_env()`` path that required
``ANTHROPIC_API_KEY``. The two factories now coexist: tests + CI keep using
the API-key path when ``ANTHROPIC_API_KEY`` is set; production runs (operator
priority/lazy catalog runs) default to this subscription-auth client.

Interface contract (matches ``extractor.AnthropicClient`` Protocol):

    .messages_create(*, model, max_tokens, system, messages) -> Any

Returns a dict shaped ``{"content": [{"text": "..."}]}`` so the existing
``_coerce_response_text`` in ``extractor.py`` parses it without changes.

Concurrency note: the underlying ``claude-agent-sdk`` ``query()`` is async;
this adapter wraps each call in ``asyncio.run`` for sync-call ergonomics
matching the existing extractor pipeline. For the catalog's priority run
(~6,750 calls), the priority_runner orchestrates batching and rate-limit
handling at a higher level.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

_LOG = logging.getLogger(__name__)


class ClaudeSdkClient:
    """Sync adapter over ``claude_agent_sdk.query()`` for the extractor's
    ``AnthropicClient`` Protocol.

    Auth: defers to the local ``claude`` CLI's OAuth session. No env var
    setup is required beyond the operator already being logged in via
    ``claude /login``. If both ``claude /login`` AND ``ANTHROPIC_API_KEY``
    are present, the CLI uses the API key — to force subscription auth,
    unset ``ANTHROPIC_API_KEY`` before running.

    Args:
        cwd: Working directory the CLI uses for context loading. Defaults
            to ``/tmp`` to skip the project's CLAUDE.md (which would otherwise
            inject ~22k tokens of cache-creation overhead per call).
        max_turns: Cap on agent turns per call. Set to 1 since extractor calls
            are single-shot prompt → response, no tool use needed.
    """

    def __init__(self, *, cwd: str = "/tmp", max_turns: int = 1) -> None:
        # Lazy import so unit tests that stub the AnthropicClient Protocol
        # do not require claude-agent-sdk installed.
        try:
            from claude_agent_sdk import (  # type: ignore[import-not-found]
                query,
                ClaudeAgentOptions,
                AssistantMessage,
                TextBlock,
                ResultMessage,
            )
        except ImportError as exc:
            raise ImportError(
                "claude-agent-sdk not installed. "
                "Install with `pip install claude-agent-sdk` or use "
                "get_anthropic_client_from_env() if you have an API key."
            ) from exc

        self._query = query
        self._options_cls = ClaudeAgentOptions
        self._assistant_msg_cls = AssistantMessage
        self._text_block_cls = TextBlock
        self._result_msg_cls = ResultMessage
        self._cwd = cwd
        self._max_turns = max_turns

    def messages_create(
        self,
        *,
        model: str,
        max_tokens: int,
        system: str,
        messages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Execute a single prompt → response round-trip via the CLI session.

        ``max_tokens`` is accepted for protocol parity but the CLI does not
        expose a per-call output cap; the model's own max_output_tokens
        (typically 32000 for Sonnet 4.6) governs. The extractor's prompts
        are bounded by feature-spec size and rarely approach this ceiling.
        """
        # Concatenate user messages into a single prompt (extractor only
        # passes one user message in production, but be defensive).
        prompt_parts: list[str] = []
        for m in messages:
            if isinstance(m, dict) and m.get("role") == "user":
                content = m.get("content", "")
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and "text" in block:
                            prompt_parts.append(str(block["text"]))
                        elif isinstance(block, str):
                            prompt_parts.append(block)
                elif isinstance(content, str):
                    prompt_parts.append(content)
        prompt = "\n\n".join(prompt_parts)

        async def _run() -> str:
            options = self._options_cls(
                system_prompt=system,
                model=model,
                cwd=self._cwd,
                max_turns=self._max_turns,
            )
            collected = ""
            async for message in self._query(prompt=prompt, options=options):
                if isinstance(message, self._assistant_msg_cls):
                    for block in message.content:
                        if isinstance(block, self._text_block_cls):
                            collected += block.text
                # ResultMessage carries cost/duration but the extractor does
                # not consume it; logging here would spam the catalog run.
            return collected

        try:
            text = asyncio.run(_run())
        except RuntimeError as exc:
            # asyncio.run raises if called from inside an existing loop.
            # Catalog runners are sync top-level entry points so this should
            # not happen in production; surface clearly if it does.
            raise RuntimeError(
                "ClaudeSdkClient.messages_create called from inside an event "
                "loop. This adapter is sync; use it from a sync orchestrator."
            ) from exc

        return {"content": [{"text": text}]}


def get_claude_sdk_client(*, cwd: str = "/tmp") -> ClaudeSdkClient:
    """Factory matching the get_anthropic_client_from_env() signature.

    Use this in priority_runner / lazy_runner when ``ANTHROPIC_API_KEY`` is
    unset — the operator runs the catalog against their subscription instead
    of API billing.
    """
    return ClaudeSdkClient(cwd=cwd)
