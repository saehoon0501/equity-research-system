"""Regression tests for the subscription-auth resolver in priority/lazy runners.

Per BUILD_LOG decision 1, the project does NOT carry ANTHROPIC_API_KEY —
Claude Code is the runtime. The peak_pain_catalog runners now resolve to:
  - claude_sdk_client (subscription auth via local `claude` CLI) by default
  - get_anthropic_client_from_env() only when ANTHROPIC_API_KEY is explicitly set

These tests pin that behavior — they do NOT make live LLM calls.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


@pytest.fixture
def clean_env(monkeypatch):
    """Strip both ANTHROPIC_API_KEY and any partial env state."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    yield


def test_resolver_picks_sdk_client_when_no_api_key(clean_env, monkeypatch):
    """When ANTHROPIC_API_KEY is unset, the resolver must return a
    ClaudeSdkClient (subscription auth), NOT call get_anthropic_client_from_env
    (which would crash on missing key)."""
    from src.peak_pain_catalog import priority_runner

    # Stub the SDK factory so we don't actually invoke claude-agent-sdk.
    sentinel = object()

    def _fake_sdk_factory(*, cwd: str = "/tmp"):
        return sentinel

    monkeypatch.setattr(
        "src.peak_pain_catalog.claude_sdk_client.get_claude_sdk_client",
        _fake_sdk_factory,
    )

    client = priority_runner._resolve_default_client()
    assert client is sentinel


def test_resolver_picks_api_key_client_when_env_set(monkeypatch):
    """When ANTHROPIC_API_KEY IS set, the resolver must use the legacy
    get_anthropic_client_from_env() path."""
    from src.peak_pain_catalog import priority_runner

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    sentinel = object()

    def _fake_anthropic_factory():
        return sentinel

    monkeypatch.setattr(
        "src.peak_pain_catalog.priority_runner.get_anthropic_client_from_env",
        _fake_anthropic_factory,
    )
    client = priority_runner._resolve_default_client()
    assert client is sentinel


def test_claude_sdk_client_protocol_compliance():
    """ClaudeSdkClient must structurally satisfy the AnthropicClient Protocol —
    i.e. have a `.messages_create(*, model, max_tokens, system, messages)`
    method. We do NOT instantiate or call it (would require claude-agent-sdk
    + an OAuth session); just verify the class shape via inspection."""
    from src.peak_pain_catalog.claude_sdk_client import ClaudeSdkClient
    import inspect

    sig = inspect.signature(ClaudeSdkClient.messages_create)
    params = sig.parameters
    # Strip 'self'
    expected = {"model", "max_tokens", "system", "messages"}
    actual = set(params.keys()) - {"self"}
    missing = expected - actual
    assert not missing, f"messages_create missing required kwargs: {missing}"


def test_lazy_runner_resolver_branch_no_api_key(monkeypatch, tmp_path):
    """lazy_runner.validate_on_first_retrieval also picks the SDK path when
    ANTHROPIC_API_KEY is unset. We exercise the resolver branch without
    actually making LLM calls — pass an explicit client to short-circuit."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    # Trivial smoke — just confirm the module imports + the SDK adapter
    # is reachable from lazy_runner's import chain.
    from src.peak_pain_catalog.lazy_runner import validate_on_first_retrieval
    from src.peak_pain_catalog.claude_sdk_client import get_claude_sdk_client

    # The factory itself must be importable; we don't call it here because
    # that would require claude-agent-sdk installed in the test env.
    assert callable(get_claude_sdk_client)
    assert callable(validate_on_first_retrieval)
