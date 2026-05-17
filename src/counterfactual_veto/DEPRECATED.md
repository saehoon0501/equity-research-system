# DEPRECATED 2026-05-17

The `counterfactual_veto` retrieval-and-veto framework has been retired from
the live `/research-company` pipeline. This module is preserved in the
codebase for reference and historical reproducibility of pre-2026-05-17 runs,
but it is **no longer imported** by any production code path (orchestrator
§3.5 retrieval stage removed; conviction-rollup veto path removed; HG-22/27
relaxed).

## Rationale

FEATURE-analog veto against the `peak_pain_archetypes` catalog tied bear-arc
veto firing to named historical analog distributions (≥2 NON-SURVIVOR =
veto). After the GOOGL 2026-05-17 Q1 FY26 print falsified the
Kodak-displacement bear arc the framework was matching against, the veto
was still firing on stale analog-distance similarity — producing structural
HOLD bias. See BUILD_LOG.md for the full calibration sweep.

Adversarial pressure now lives in `pm-supervisor.md` §2.6 stress-test using
mechanism + falsifying-observable framing.

## Module surface (preserved for reference)

- `feature_extractor.py` — universal-core + sector-extension feature derivation
- `retrieval.py` — `retrieve_top_3`, `archetype_distribution`, `load_catalog_from_pg`
- `layer1_cooling_off.py` / `layer2_multi_source.py` / `layer3_veto.py` — multi-layer veto staging
- `calibration.py` — historical-cohort calibration
- `lifecycle.py` — entry/exit/lifecycle bins
- `orchestrator.py` — staged-veto orchestration
- `cli.py` — debug CLI

## DB table

The underlying Postgres table `counterfactual_ledger` continues to receive
universal per-run writes (Consensus Item #4, locked 2026-05-12); only the
`peak_pain_archetypes` retrieval-feature catalog is retired. The
`counterfactual_ledger` table itself is NOT deprecated.

## Resurrection procedure

See `src/peak_pain_catalog/DEPRECATED.md` § Resurrection procedure — the two
modules must be restored together (or not at all).
