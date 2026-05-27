"""Unit tests for P0-6 (model-selection header reader) + P0-5 model pinning.

Acceptance bar (plan P0-6): a designated agent can be made to dispatch on a
non-opus model — i.e. effective_model(agent, role) != the producer model.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.llm_cache.agent_model import (
    JUDGE,
    PRODUCER,
    VERIFIER,
    AgentModelHeader,
    effective_model,
    read_agent_header,
)
from src.llm_cache.model_pin import MODEL_ALIASES, pin_resolved_model

REPO_ROOT = Path(__file__).resolve().parents[3]
AGENTS_DIR = REPO_ROOT / ".claude" / "agents"


# ---------------------------------------------------------------------------
# model_pin (resolved-id pinning)
# ---------------------------------------------------------------------------


def test_pin_alias_to_resolved():
    assert pin_resolved_model("opus") == "claude-opus-4-5"
    assert pin_resolved_model("sonnet") == "claude-sonnet-4-5"


def test_pin_resolved_id_passthrough():
    assert pin_resolved_model("claude-opus-4-5") == "claude-opus-4-5"


def test_pin_case_insensitive():
    assert pin_resolved_model("OPUS") == "claude-opus-4-5"


def test_pin_empty_raises():
    with pytest.raises(ValueError):
        pin_resolved_model("")


def test_pin_in_sync_with_p3_p4_constants():
    """The alias table must agree with the resolved ids the codebase pins."""
    from src.p3_mechanical_scorer import DEFAULT_MODEL, HIGH_STAKES_MODEL
    from src.p4_debate import MODEL_OPUS, MODEL_SONNET

    assert MODEL_ALIASES["opus"] == MODEL_OPUS == HIGH_STAKES_MODEL
    assert MODEL_ALIASES["sonnet"] == MODEL_SONNET == DEFAULT_MODEL


# ---------------------------------------------------------------------------
# Frontmatter parsing (synthetic, dir-injected)
# ---------------------------------------------------------------------------


def _write_agent(tmp_path: Path, name: str, body: str) -> Path:
    d = tmp_path / ".claude" / "agents"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.md").write_text(body, encoding="utf-8")
    return d


def test_reader_parses_model_fields(tmp_path):
    d = _write_agent(
        tmp_path,
        "demo",
        '---\nname: demo\ntools: "Read, Bash"\n'
        "model: opus\nverifier_model: sonnet\n---\n# Demo\n",
    )
    hdr = read_agent_header("demo", agents_dir=d)
    assert hdr.name == "demo"
    assert hdr.model == "opus"
    assert hdr.verifier_model == "sonnet"
    assert hdr.judge_model is None


def test_effective_model_resolves_per_role(tmp_path):
    d = _write_agent(
        tmp_path,
        "demo",
        "---\nname: demo\nmodel: opus\nverifier_model: sonnet\n---\n# Demo\n",
    )
    assert effective_model("demo", PRODUCER, agents_dir=d) == "claude-opus-4-5"
    assert effective_model("demo", VERIFIER, agents_dir=d) == "claude-sonnet-4-5"


def test_verifier_judge_fall_back_to_producer(tmp_path):
    d = _write_agent(tmp_path, "demo", "---\nname: demo\nmodel: opus\n---\n# Demo\n")
    hdr = read_agent_header("demo", agents_dir=d)
    assert hdr.effective_model(VERIFIER) == "claude-opus-4-5"
    assert hdr.effective_model(JUDGE) == "claude-opus-4-5"


def test_unknown_role_raises():
    hdr = AgentModelHeader(name="x", model="opus")
    with pytest.raises(ValueError):
        hdr.effective_model("nonsense")


def test_missing_agent_raises(tmp_path):
    d = tmp_path / ".claude" / "agents"
    d.mkdir(parents=True)
    with pytest.raises(FileNotFoundError):
        read_agent_header("nope", agents_dir=d)


# ---------------------------------------------------------------------------
# Real repo agents — the acceptance bar
# ---------------------------------------------------------------------------


def test_pm_supervisor_verifier_is_non_opus():
    """Designated agent (pm-supervisor, WS-5 BoN verifier role) dispatches on a
    non-opus model — the P0-6 acceptance assertion."""
    producer = effective_model("pm-supervisor", PRODUCER, agents_dir=AGENTS_DIR)
    verifier = effective_model("pm-supervisor", VERIFIER, agents_dir=AGENTS_DIR)
    assert producer == "claude-opus-4-5"
    assert verifier == "claude-sonnet-4-5"
    assert verifier != producer


def test_evaluator_judge_is_non_opus():
    """Designated agent (evaluator, WS-6 advisory judge role) dispatches on a
    non-opus model."""
    producer = effective_model("evaluator", PRODUCER, agents_dir=AGENTS_DIR)
    judge = effective_model("evaluator", JUDGE, agents_dir=AGENTS_DIR)
    assert judge == "claude-sonnet-4-5"
    assert judge != producer


def test_producers_default_opus():
    """Plain producers keep model: opus and have no verifier/judge override."""
    for name in ("quantitative-analyst", "strategic-analyst", "catalyst-scout"):
        hdr = read_agent_header(name, agents_dir=AGENTS_DIR)
        assert hdr.model == "opus", name
        assert hdr.effective_model(PRODUCER) == "claude-opus-4-5", name
