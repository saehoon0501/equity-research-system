# src/eval/

Outer-ring Eval surface per CLAUDE.md P14.

**Status:** Layer 1 (scorer) only. Layers 2 (resolver) and 3 (model_health)
deferred to `archive/_retired/docs/superpowers/specs/2026-05-23-eval-loop-creation-design.md`
(DRAFT, not approved as of 2026-05-23).

## Layers

| Layer | Module | Purity | Inputs | Outputs |
|---|---|---|---|---|
| 1 | `scorer.py` | pure function, no I/O | (label, excess_return, margin) | hit / miss |
| 2 | `resolver.py` | DB + market_data | (run_id, horizon) | scored row |
| 3 | `model_health.py` | aggregate | scored rows | calibration trigger |

## Build order (per P14)

Inner ring (`tests/unit/eval/`) coverage before any new layer.

## Source

- HIGH-4 consensus 2026-05-16: 4-bin, sector-conditional, 90d/1y/3y/5y, categorical
- `counterfactual_ledger` (mig 030) is the universal-write source for Layer 2 inputs
- Hit/miss rule table is a domain decision → `/review-me`
