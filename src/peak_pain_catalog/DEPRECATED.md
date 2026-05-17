# DEPRECATED 2026-05-17

The `peak_pain_archetypes` named-historical-analog catalog has been retired
from the live `/research-company` pipeline. This module is preserved in the
codebase for reference and historical reproducibility of pre-2026-05-17 runs,
but it is **no longer imported** by any analog-retrieval production code path.

**Exception:** `src/peak_pain_catalog/claude_sdk_client.py` is a generic
Claude SDK subscription-auth wrapper (not analog-retrieval logic) that is
still imported by `src/orchestrator/test_full_pipeline.py` as the
no-API-key fallback client for L4 daily-monitor LLM calls. Phase 3 of the
removal plan deliberately keeps this single import alive to avoid scope
creep. A future refactor should move `claude_sdk_client.py` to a neutral
location (e.g., `src/anthropic_auth/`), but that is out of scope for the
peak_pain_archetypes removal.

## Rationale

Named-historical-analog matching anchored bear-DCFs at NON-SURVIVOR drawdown
magnitudes regardless of Q1-falsifier clearance, producing structural HOLD
bias on names that had already cleared the cited bear arcs. See the GOOGL
2026-05-17 calibration sweep + BUILD_LOG.md for the removal rationale.

Adversarial pressure for analog-driven displacement-thesis testing is now
handled by `pm-supervisor.md` §2.6 stress-test using mechanism +
falsifying-observable framing rather than named historical analogs.

## Module surface (preserved for reference)

- `claude_sdk_client.py` — Claude SDK client wrapper
- `cli.py` — catalog-build CLI
- `consensus.py` — multi-pass consensus voting
- `extractor.py` — per-case feature extraction
- `feature_typing.py` — universal-core + sector-extension feature schemas
- `lazy_runner.py` / `priority_runner.py` — orchestration
- `parser.py` — historical-case parser
- `persistence.py` — DB I/O against `peak_pain_archetypes` table

## DB table

The underlying Postgres table `peak_pain_archetypes` is renamed to
`peak_pain_archetypes_retired_20260517` under Phase 4 of the removal plan
(HMAC-gated; not yet executed as of 2026-05-17). Until that migration runs,
the table remains queryable but is not consumed by any code path.

## Resurrection procedure

If a future operator wants to restore analog-driven veto pressure:

1. Revert commits `48b02e4` through `2509730` on `remove-peak-pain-archetypes`
2. Restore §3.5 in `.claude/commands/research-company.md`
3. Restore `counterfactual_top_3` field on `ConvictionInputs` + helpers
4. Re-enable HG-22/23/27/28/29 references in `.claude/agents/evaluator.md`

Do NOT attempt partial restoration — the framework is structurally coupled
across all four phases.
