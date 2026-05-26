# P3 mechanical scorer

Critical-path component #3 in v0.1. Implements the **3-stage hybrid scorer** for P3 name discovery per
`docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md` Section 4.3.

## Architecture

```
Stage 1A   Multiplicative knockout  (any fail -> REJECT)
            - Fraud signature 3+/6 (L3-e #8, #21)
            - Era-fit binary       (L3-e #20, #24)

Stage 1B   Additive equal-weight 4-criterion Tier-A composite
            - Founder/CEO duration >= 15y          (L3-e #1)
            - Per-share-value primary metric       (L3-e #2)
            - ROIIC > 15% sustained                 (L3-e #3)
            - Pivot-creates-multi-bag (not original) (L3-e #4)
            >=3 = A / 2 = WATCH / <=1 = REJECT
            LEI-style proportional re-weighting on missing data

Stage 2    LLM rubric (INFORMATION-ISOLATED from Stage 1)
            - Per-pattern single-attribute call (anchoring-bias mitigation)
            - 3-level ordinal {LOW, MEDIUM, HIGH} -> {0.0, 0.5, 1.0}
            - Forced JSON; verbatim evidence required (no quote -> LOW)
            - Self-consistency N=5 at temp=0.7; median rating
            - saw_rule_output: false enforced in audit

Stage 3    Deterministic linter
            - Cross-checks LLM vs Stage-1-known facts
            - Flags: contradictions, HIGH without evidence, round-number,
              position bias, verbosity
            - Routes to operator review; logs to S2 ledger
```

## Information isolation (load-bearing)

Per Section 4.3 + Section 5 Q1 lock + L8 finding, Stage 2 LLM **MUST NOT** see Stage 1
mechanical output. We enforce this in five places:

1. `stage2_llm_rubric.build_prompt(pattern, evidence)` — signature accepts ONLY pattern
   + evidence; no parameter could carry Stage 1 output.
2. `stage2_llm_rubric.score_all_patterns` calls `_assert_info_isolation(evidence)`,
   which scans the `EvidenceCorpus` for forbidden Stage-1 attributes and forbidden
   Stage-1 phrases inside source documents — raises `AssertionError` on violation.
3. `orchestrator.score_ticker` deliberately discards `stage1a_result`/`stage1b_result`
   between Stage 1 and Stage 2 — only `adapter.fetch_evidence_corpus(ticker)` feeds
   Stage 2. A defence-in-depth assert checks the Stage 2 result's `saw_rule_output`
   flag is False.
4. `cli.JsonFileAdapter.fetch_evidence_corpus` rejects evidence documents that contain
   Stage-1 keys.
5. `stage3_linter._check_info_isolation` validates the audit's `saw_rule_output`
   flag and quarantines runs missing/violating it.

Reviewers: do not add a `stage1` parameter to `build_prompt` or `score_all_patterns`.

## LLM call patterns

- One call per pattern (single-attribute) × N=5 samples (self-consistency) × number of
  active patterns. With 6 patterns: 30 LLM calls per ticker.
- Default model is **Sonnet** (`claude-sonnet-4-5`); contested patterns auto-route to
  **Opus** (`claude-opus-4-5`). Section 4.5 model constraint: NO Haiku.
- Forced JSON; verbatim evidence required; failures default to LOW per spec.
- High-stakes mode: pass `high_stakes=True` to `score_ticker` to route ALL patterns
  to Opus (e.g., for already-held positions).

## Decision composition

| Stage 1A | Stage 1B | Stage 2 score | Final |
|---|---|---|---|
| REJECT | — | — | PASS |
| PROCEED | REJECT | — | PASS |
| PROCEED | A | >= 0.55 | PROCEED |
| PROCEED | A | 0.35-0.55 | WATCH (disagreement = true) |
| PROCEED | A | < 0.35 | PASS (disagreement = true) |
| PROCEED | WATCH | >= 0.35 | WATCH |
| PROCEED | WATCH | < 0.35 | PASS (disagreement = true) |

`composition_disagreement` is a first-class field in the audit (Section 4.3).

## CLI

```bash
python -m p3_mechanical_scorer.cli score --ticker NVDA
python -m p3_mechanical_scorer.cli score --ticker NVDA --high-stakes
python -m p3_mechanical_scorer.cli score --ticker NVDA \
  --inputs-json /path/to/p3_inputs.json --output-json /tmp/nvda_out.json
python -m p3_mechanical_scorer.cli score --ticker NVDA --no-llm  # smoke test
```

`p3_inputs.json` schema is documented in the CLI module docstring.

## Persistence

Audit rows write to `audit_provenance` (migration `008_v3_recommendations.sql`).
The migration's enum requires `stage='stage_1_mechanical'` — sub-stages are
disambiguated via `drill_payload.substage` (`stage_1a`, `stage_1b`,
`stage_2_llm_rubric`, `stage_3_linter`). HMAC chain via `parent_audit_id`.
Counterfactual veto retrieval (`counterfactual_ledger`) is a separate Wave C
component and is NOT exercised by P3.

## What this module does NOT do

- Counterfactual retrieval / VETO authority (separate Wave C subagent).
- Mode classification (separate `src/mode_classifier`).
- 5-style debate (separate P4 subagent).
- DB-querying data adapter (v0.5+; v0.1 ships JSON-file adapter only).

## Versioning

| Component | Version key | v0.1 value |
|---|---|---|
| Mechanical rules | `RULE_ENGINE_VERSION` | `p3-mechanical-v0.1` |
| Stage 2 prompts | `LLM_PROMPT_VERSION` | `p3-stage2-rubric-v0.1` |
| Stage 3 linter | `LINTER_VERSION` | `p3-stage3-linter-v0.1` |

Bump on prompt/rule/threshold changes.
