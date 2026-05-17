"""P4 — 5-style debate orchestrator (Phase A→B→C-conditional→D).

Per v3 spec ``docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md``
Section 2.3 (five-style debate architecture), Section 2.4 (three critical
architectural findings), and Section 4.8 (L8 / 5-style debate).

Pipeline::

    Phase A (isolated)   -> 5 styles run in parallel, no cross-style visibility
        |
    Phase B (locked)     -> each style writes immutable load-bearing claims
        |                   + non-negotiables; locked for Phase C
        |
    Phase C (judge)      -> LLM-as-judge over Phase B claims; if conflicts of
        |                   Type 1 / 2 / 3 detected, run bounded negotiation
        |                   (3 rounds max). Phase B locks remain immutable.
        |
    Phase D (PMSupervisor) -> synthesizes ADD / WATCH / PASS with EXPLICIT
                              dissent preservation per L8 + Section 2.4 #1
                              (PMSupervisor MUST NOT force consensus).

Three architectural invariants from Section 2.4:

1. **PMSupervisor MUST NOT force consensus** — sycophancy is the dominant
   MAD failure mode (ICML 2025); Phase D output explicitly preserves
   dissenting views per agent.
2. **Persona drift is real** — Phase B locks load-bearing claims and
   non-negotiables in writing; Phase C cannot modify Phase B locks.
3. **Evaluator stays OUTSIDE the debate** — the existing ``.claude/agents/
   evaluator.md`` hard-gate runs after Phase D, not inside the debate loop.

Model selection (Section 6 Q1 + this package's own selection rationale):

* Phase A (isolated style cases) — Sonnet (claude-sonnet-4-5)
* Phase B (locked claim extraction) — Sonnet (claude-sonnet-4-5)
* Phase C judge (3-Type rubric) — Opus (claude-opus-4-5; high-stakes adjudication)
* Phase C negotiation rounds — Sonnet (claude-sonnet-4-5)
* Phase D PMSupervisor synthesis — Opus (claude-opus-4-5; final decision)
"""

from __future__ import annotations

# Style identifiers — used as JSONB keys in debate_consensus_history.per_style_outputs.
STYLE_VALUE: str = "value"
STYLE_GROWTH: str = "growth"
STYLE_QUALITY_MOAT: str = "quality_moat"
STYLE_MACRO_REGIME: str = "macro_regime"
STYLE_QUANT_TECHNICAL: str = "quant_technical"

ALL_STYLES: tuple[str, ...] = (
    STYLE_VALUE,
    STYLE_GROWTH,
    STYLE_QUALITY_MOAT,
    STYLE_MACRO_REGIME,
    STYLE_QUANT_TECHNICAL,
)

# Verdict ∈ {ADD, WATCH, PASS} per Section 2.3 Phase D output schema.
VERDICT_ADD: str = "ADD"
VERDICT_WATCH: str = "WATCH"
VERDICT_PASS: str = "PASS"

ALL_VERDICTS: tuple[str, ...] = (VERDICT_ADD, VERDICT_WATCH, VERDICT_PASS)

# Mode identifiers re-exported for the weighting matrix.
MODE_B: str = "B"
MODE_B_PRIME: str = "B_prime"
MODE_C: str = "C"

# Phase C trigger conflict types (Section 4.8).
CONFLICT_TYPE_1: str = "type_1_direct_contradiction"
CONFLICT_TYPE_2: str = "type_2_magnitude_disagreement"
CONFLICT_TYPE_3: str = "type_3_mutually_exclusive_prerequisite"

# Mode-style weighting matrix per Section 2.3 (must sum to 1.0 within mode).
# Cell value = decision weight applied during Phase D synthesis.
WEIGHT_MATRIX: dict[str, dict[str, float]] = {
    MODE_B: {
        STYLE_VALUE: 0.30,
        STYLE_GROWTH: 0.05,
        STYLE_QUALITY_MOAT: 0.35,
        STYLE_MACRO_REGIME: 0.20,
        STYLE_QUANT_TECHNICAL: 0.10,
    },
    MODE_B_PRIME: {
        STYLE_VALUE: 0.15,
        STYLE_GROWTH: 0.35,
        STYLE_QUALITY_MOAT: 0.30,
        STYLE_MACRO_REGIME: 0.10,
        STYLE_QUANT_TECHNICAL: 0.10,
    },
    MODE_C: {
        STYLE_VALUE: 0.10,
        STYLE_GROWTH: 0.35,
        STYLE_QUALITY_MOAT: 0.20,
        STYLE_MACRO_REGIME: 0.20,
        STYLE_QUANT_TECHNICAL: 0.15,
    },
}

# Sector overrides per Section 2.3 (line 185 — "Banks/insurers-B" is ONE class):
#   - Biotech in C-mode: catalyst-binary, optionality-weighted
#   - Banks/insurers in B-mode: book-value-anchored, rate-cycle-driven
#
# Operator-facing sector tags ("Banks", "Insurers", "Financials") are
# normalized via `_normalize_sector` before lookup so callers may pass any of
# them and get the single Banks/insurers override.
SECTOR_OVERRIDES: dict[tuple[str, str], dict[str, float]] = {
    ("Biotech", MODE_C): {
        STYLE_GROWTH: 0.50,
        STYLE_MACRO_REGIME: 0.25,
        STYLE_QUANT_TECHNICAL: 0.15,
        STYLE_QUALITY_MOAT: 0.05,
        STYLE_VALUE: 0.05,
    },
    ("Banks/insurers", MODE_B): {
        STYLE_VALUE: 0.35,
        STYLE_MACRO_REGIME: 0.30,
        STYLE_QUALITY_MOAT: 0.25,
        STYLE_GROWTH: 0.05,
        STYLE_QUANT_TECHNICAL: 0.05,
    },
}

# Sector-name normalizer per Section 2.3 line 185: "Banks", "Insurers", and
# "Financials" all map to the single "Banks/insurers" override class. Other
# sector tags pass through unchanged.
_SECTOR_NORMALIZE: dict[str, str] = {
    "banks": "Banks/insurers",
    "insurers": "Banks/insurers",
    "financials": "Banks/insurers",
    "banks/insurers": "Banks/insurers",
}


def _normalize_sector(sector: str | None) -> str | None:
    """Map operator-friendly sector names → canonical override key.

    Case-insensitive lookup against ``_SECTOR_NORMALIZE``. Unrecognized
    names round-trip unchanged (so "Biotech" still resolves to itself).
    """
    if sector is None:
        return None
    return _SECTOR_NORMALIZE.get(sector.strip().lower(), sector)

# Model identifiers (single point of edit; matches mode_classifier convention).
MODEL_SONNET: str = "claude-sonnet-4-5"
MODEL_OPUS: str = "claude-opus-4-5"

# Prompt versions (recalibratable via parameters table per Section 4.8).
PROMPT_VERSION_PHASE_A: str = "p4.phase_a.v1.2026-04-29"
PROMPT_VERSION_PHASE_B: str = "p4.phase_b.v1.2026-04-29"
PROMPT_VERSION_PHASE_C_JUDGE: str = "p4.phase_c_judge.v1.2026-04-29"
PROMPT_VERSION_PHASE_C_NEGOTIATION: str = "p4.phase_c_negotiation.v1.2026-04-29"
PROMPT_VERSION_PHASE_D: str = "p4.phase_d.v1.2026-04-29"

# Phase C negotiation upper bound per Section 2.3 ("bounded to 3 rounds").
PHASE_C_MAX_ROUNDS: int = 3


def get_weights(mode: str, sector: str | None = None) -> dict[str, float]:
    """Resolve mode-style weights, applying sector override if applicable.

    Args:
        mode: One of ``MODE_B``, ``MODE_B_PRIME``, ``MODE_C``.
        sector: Optional sector tag; if it matches a key in
            ``SECTOR_OVERRIDES`` for ``(sector, mode)`` the override is used.

    Returns:
        Mapping ``style_id -> weight`` summing to 1.0.

    Raises:
        ValueError: if ``mode`` is not one of the three canonical modes.
    """
    if mode not in WEIGHT_MATRIX:
        raise ValueError(
            f"unknown mode {mode!r}; expected one of "
            f"{tuple(WEIGHT_MATRIX.keys())}"
        )
    canonical = _normalize_sector(sector)
    if canonical is not None and (canonical, mode) in SECTOR_OVERRIDES:
        return dict(SECTOR_OVERRIDES[(canonical, mode)])
    return dict(WEIGHT_MATRIX[mode])


__all__ = [
    "STYLE_VALUE",
    "STYLE_GROWTH",
    "STYLE_QUALITY_MOAT",
    "STYLE_MACRO_REGIME",
    "STYLE_QUANT_TECHNICAL",
    "ALL_STYLES",
    "VERDICT_ADD",
    "VERDICT_WATCH",
    "VERDICT_PASS",
    "ALL_VERDICTS",
    "MODE_B",
    "MODE_B_PRIME",
    "MODE_C",
    "CONFLICT_TYPE_1",
    "CONFLICT_TYPE_2",
    "CONFLICT_TYPE_3",
    "WEIGHT_MATRIX",
    "SECTOR_OVERRIDES",
    "MODEL_SONNET",
    "MODEL_OPUS",
    "PROMPT_VERSION_PHASE_A",
    "PROMPT_VERSION_PHASE_B",
    "PROMPT_VERSION_PHASE_C_JUDGE",
    "PROMPT_VERSION_PHASE_C_NEGOTIATION",
    "PROMPT_VERSION_PHASE_D",
    "PHASE_C_MAX_ROUNDS",
    "get_weights",
]
