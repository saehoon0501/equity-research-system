# `src/p4_debate/` — 5-style debate orchestrator (Phase A -> B -> C-conditional -> D)

Implements the P4 deep-dive funnel stage per v3 spec
`docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md`
Section 2.3 (five-style debate architecture), Section 2.4 (three
critical architectural findings), and Section 4.8 (L8 / 5-style debate).

## Architectural invariants (Section 2.4)

1. **PMSupervisor MUST NOT force consensus.** Sycophancy is the
   dominant MAD failure mode (ICML 2025 — Talk Isn't Always Cheap;
   Peacemaker or Troublemaker). Phase D output explicitly preserves
   dissenting views per agent. Enforced structurally:
   `_validate_phase_d_payload` in `phase_d_pm_supervisor.py` BACKFILLS
   missing dissent entries from Phase B locks if the LLM omits them.
2. **Persona drift is real.** Phase B locks load-bearing claims and
   non-negotiables in writing; Phase C cannot modify Phase B locks.
   Enforced structurally: `PhaseBStyleLock` is `frozen=True`; Phase C
   takes locked sets as input and produces NEW state in
   `PhaseCRoundResult` rather than mutating locks.
3. **Evaluator stays OUTSIDE the debate.** The existing
   `.claude/agents/evaluator.md` hard-gate runs as a separate stage AFTER
   Phase D. This package does NOT integrate the evaluator.

## Pipeline

```
P4Inputs(ticker, mode, sector?, candidate_facts, scenarios?, lane_refs?,
         s0_regime_context?)
    |
    +--> Phase A — 5 styles parallel; isolated; Sonnet
    |
    +--> Phase B — 5 styles parallel; locked claims + non-negotiables; Sonnet
    |
    +--> Phase C judge — single Opus call; 3-Type rubric (direct
    |        contradiction / magnitude disagreement / mutually-exclusive
    |        prerequisite). Output: phase_c_needed bool + conflicts list.
    |
    +--> Phase C negotiation (only if needed) — bounded to 3 rounds;
    |        Sonnet; conflicting styles refine WITHIN their locks.
    |
    +--> Phase D PMSupervisor synthesis — Opus; ADD/WATCH/PASS with
    |        explicit dissent_trace, override_reasoning, and
    |        non_negotiables_not_addressed.
    |
    +--> persist row to debate_consensus_history (append-only)
```

## Files

| File | Purpose |
|---|---|
| `__init__.py` | Constants, weight matrix (B/B'/C), sector overrides, prompt versions, `get_weights()` resolver. |
| `_base.py` (in `styles/`) | `StylePersona` frozen dataclass — locked persistent identity per style. |
| `styles/value.py` | Buffett / Klarman / Marks / Tepper. Distressed-contrarian variant via cash-as-option rule. |
| `styles/growth.py` | Druckenmiller-long-equities / Tiger / Coatue / Baillie Gifford. TAM × penetration × take-rate. |
| `styles/quality_moat.py` | Mauboussin / Munger / GMO / Terry Smith. ROIC-WACC spread × duration × reinvestment. |
| `styles/macro_regime.py` | Bridgewater / Druckenmiller / Soros. Consumes S0 + L1 lane reference; emits regime-sensitivity tag. |
| `styles/quant_technical.py` | AQR / CTA-systematic / Renaissance. Factor loadings, momentum, crowding. |
| `_llm.py` | Anthropic SDK glue — lazy import, `LLMUnavailableError`, `extract_json`. |
| `phase_a_isolated.py` | 5 parallel isolated style runs. Manufactured independence. |
| `phase_b_locked.py` | 5 parallel locked claim sets. `PhaseBStyleLock` frozen for immutability. |
| `phase_c_judge.py` | LLM-as-judge over Phase B; 3-Type rubric; Opus. |
| `phase_c_negotiation.py` | Bounded 3-round negotiation; conflicting styles refine within locks. |
| `phase_d_pm_supervisor.py` | Synthesis with dissent preservation enforced structurally. |
| `orchestrator.py` | End-to-end runner + `debate_consensus_history` persistence. |
| `cli.py` | `python -m p4_debate.cli debate ...` entry point. |

## Mode-style weighting matrix (Section 2.3)

| Style | B | B' | C |
|---|---|---|---|
| Value | 30% | 15% | 10% |
| Growth | 5% | 35% | 35% |
| Quality / Moat | 35% | 30% | 20% |
| Macro / Regime | 20% | 10% | 20% |
| Quant / Technical | 10% | 10% | 15% |

Sector overrides:

* **Biotech-C**: Growth 50% / Macro 25% / Quant 15% / Quality 5% / Value 5%
* **Banks-B / Insurers-B**: Value 35% / Macro 30% / Quality 25% / Growth 5% / Quant 5%

Resolved at runtime via `get_weights(mode, sector=None)`.

## Model selection (Section 6 Q1 + this package)

| Phase | Model | Rationale |
|---|---|---|
| Phase A (isolated cases) | Sonnet | 5 parallel calls; volume + cost rationale |
| Phase B (locked claims) | Sonnet | 5 parallel calls; structured-extraction task |
| Phase C judge | **Opus** | High-stakes binary trigger; tight rubric; Section 4.8 specifies dedicated parameters-table prompt entry |
| Phase C negotiation | Sonnet | Up to 3 rounds × N conflicting styles; refinement task |
| Phase D PMSupervisor | **Opus** | Final synthesis; dissent-preservation invariant; this is the load-bearing decision |

## Dissent preservation mechanism

Three layers of enforcement:

1. **Prompt-level**: `_SYSTEM_PROMPT` in `phase_d_pm_supervisor.py`
   includes the literal text "YOU MUST NOT FORCE CONSENSUS" and requires
   ALL 5 styles to appear in `dissent_trace`.
2. **Validator-level**: `_validate_phase_d_payload` post-processes the
   LLM output and BACKFILLS missing dissent entries from Phase B locks.
   The LLM cannot omit a dissenting style by accident or by design.
3. **Override-reasoning-required**: when any style's verdict differs
   from the synthesis decision, `override_reasoning` is required. If
   the LLM omits it, the validator inserts a flag string for operator
   review.

## CLI

```sh
python -m p4_debate.cli debate \
    --ticker NVDA \
    --mode B_prime \
    --candidate-facts memos/aapl_cdd_2024-12-31.json \
    --scenarios path/to/scenarios.txt \
    --s0-regime path/to/regime.txt \
    --persist
```

Exit codes: 0 success / 1 I/O error / 2 usage / 3 LLM unavailable / 4 DB error.

## Testing

`tests/test_p4_debate.py` exercises each phase independently with a
fake LLM client (no network) and verifies:

* Each style renders its locked persona correctly.
* Phase A produces preliminary verdicts; macro_regime emits
  regime_sensitivity.
* Phase B parses and freezes claims; invalid payloads default valid=False.
* Phase C judge correctly identifies Type 1/2/3 conflicts.
* Phase C negotiation respects max-3-round bound + early termination.
* Phase D dissent preservation: missing styles backfilled; override
  reasoning required when dissent differs from decision.
* Mode-style weight matrix sums to 1.0 within mode; sector overrides
  apply correctly.
