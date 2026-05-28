"""Per-agent model-selection reader (Phase-0 deliverable P0-6).

Background
----------
Agent dispatch in this repo is performed by Claude Code itself, which reads
the YAML frontmatter of ``.claude/agents/<name>.md`` — including the
``model:`` line — natively at dispatch time. There is therefore no existing
*Python* reader of that header (verified: ``grep`` for frontmatter parsing in
``src/`` finds none; the only code that touches ``.claude/agents/*.md`` is the
consistency test ``tests/integration/test_flow_overlay_agent_md_migration_consistency.py``,
which regex-parses the body, not the model header).

P0-6 adds a *role-aware* selection mechanism. Producers keep ``model: opus``;
the verifier and judge roles (WS-5 BoN verifier, WS-6 advisory judge) run on a
*different, cheaper* model (``sonnet``) to cut self-preference bias. We express
that as two new optional header fields, ``verifier_model`` and ``judge_model``,
and provide this reader as the dispatch-path consumer of those fields.

The acceptance bar (plan P0-6): *a designated agent can be made to dispatch on
a non-opus model* — i.e. ``effective_model(agent, role="verifier") != producer``.

This reader is the single Python entry point any orchestration code (or a CI
assertion) uses to resolve the effective model for an (agent, role) pair from
the frontmatter, with the resolved-id pinning from :mod:`llm_cache.model_pin`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .model_pin import pin_resolved_model

# Repo root = three parents up from this file
# (.../src/llm_cache/agent_model.py → .../src/llm_cache → .../src → repo root).
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_AGENTS_DIR = _REPO_ROOT / ".claude" / "agents"

# Valid roles a caller can ask the effective model for.
PRODUCER = "producer"
VERIFIER = "verifier"
JUDGE = "judge"
_ROLES = (PRODUCER, VERIFIER, JUDGE)

# The header field consulted for each role. ``producer`` reads the canonical
# ``model:`` line; verifier/judge read their own field and fall back to
# ``model:`` when unset.
_ROLE_TO_FIELD = {
    PRODUCER: "model",
    VERIFIER: "verifier_model",
    JUDGE: "judge_model",
}


@dataclass(frozen=True)
class AgentModelHeader:
    """Parsed model-selection fields from one agent's frontmatter."""

    name: str
    model: Optional[str] = None
    verifier_model: Optional[str] = None
    judge_model: Optional[str] = None

    def raw_for_role(self, role: str) -> Optional[str]:
        if role not in _ROLES:
            raise ValueError(f"unknown role {role!r}; expected one of {_ROLES}")
        field = _ROLE_TO_FIELD[role]
        value = getattr(self, field)
        if value:
            return value
        # verifier/judge fall back to the producer model when not specified.
        return self.model

    def effective_model(self, role: str = PRODUCER) -> Optional[str]:
        """Resolved (versioned) model id for ``role`` (None if unset)."""
        raw = self.raw_for_role(role)
        return pin_resolved_model(raw) if raw else None


def _parse_frontmatter(text: str) -> dict:
    """Parse the leading ``---``-delimited YAML-ish frontmatter into a dict.

    We avoid a hard PyYAML dependency: the agent headers are flat
    ``key: value`` pairs (the ``tools``/``description`` values may be quoted
    and contain colons, so we split only on the FIRST colon). This mirrors
    the lightweight regex-parsing already used in the repo's agent-md
    consistency test rather than introducing a new dependency.
    """
    out: dict = {}
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return out
    # Drop the opening fence, then take everything up to the closing fence.
    body = stripped[3:]
    end = body.find("\n---")
    if end == -1:
        return out
    block = body[:end]
    for line in block.splitlines():
        line = line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        # Strip matching surrounding quotes from the value.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        out[key] = value
    return out


def read_agent_header(
    agent_name: str,
    *,
    agents_dir: Optional[Path] = None,
) -> AgentModelHeader:
    """Read the model-selection header for ``agent_name``.

    ``agent_name`` is the bare name (``"pm-supervisor"``), matching the
    ``.md`` filename and the ``name:`` field.
    """
    base = Path(agents_dir) if agents_dir is not None else _DEFAULT_AGENTS_DIR
    # Flat layout (.claude/agents/<name>.md) first; fall back to a recursive
    # search for the nested layout main's reorg introduced
    # (.claude/agents/<group>/<name>.md, e.g. supervisor/pm-supervisor.md).
    path = base / f"{agent_name}.md"
    if not path.is_file():
        matches = sorted(base.rglob(f"{agent_name}.md"))
        if matches:
            path = matches[0]
        else:
            raise FileNotFoundError(f"agent definition not found: {agent_name}.md under {base}")
    fm = _parse_frontmatter(path.read_text(encoding="utf-8"))
    return AgentModelHeader(
        name=fm.get("name", agent_name),
        model=fm.get("model"),
        verifier_model=fm.get("verifier_model"),
        judge_model=fm.get("judge_model"),
    )


def effective_model(
    agent_name: str,
    role: str = PRODUCER,
    *,
    agents_dir: Optional[Path] = None,
) -> Optional[str]:
    """Convenience: resolved model id for (agent, role) from the header."""
    return read_agent_header(agent_name, agents_dir=agents_dir).effective_model(role)
