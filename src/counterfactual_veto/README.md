# `src/counterfactual_veto/` — Counterfactual VETO pipeline

Implements **v3 spec Section 4.5 Q6 (d')** Layer 3 counterfactual VETO authority — the critical-path defense against reflex-cut behavior on watchlist names that hit 2× cut threshold.

## Purpose

When a candidate's drawdown exceeds 2× the mode-tuned cut floor (B/20pp, B'/24pp, C/30pp vs benchmark), this pipeline gates the cut decision through three layers:

1. **Layer 1 — Cooling-off floor (universal)**: B/72h, B'/48h, C/24h.
2. **Layer 2 — Multi-source confirmation**: ≥2 independent kill-criteria fired (BOCPD-collapsed); verbatim primary-source quote; operator pre-mortem within 30 days.
3. **Layer 3 — Counterfactual VETO authority**: top-3 retrieval against the peak-pain archetype catalog. ≥2 SURVIVOR-leaning → cut blocked pending operator override. ≥2 NON-SURVIVOR → cut proceeds. Mixed → operator review.

The veto **operates on top of mode polarity** — it can block Mode-C "cut-fast" names when their structural features look like historical SURVIVOR archetypes. This is the **PLTR-2022 problem** (Section 7.3a Walkthrough #1).

## Module map

| File | Role |
|---|---|
| `__init__.py` | Public re-exports + mode-tuned constants. |
| `feature_extractor.py` | Wrap candidate as a CaseRecord and run the existing 3-LLM consensus pipeline (`peak_pain_catalog.consensus.run_consensus`). |
| `retrieval.py` | Mechanical similarity scoring (0.7 · core + 0.3 · sector); Bayesian shrinkage λ=1.0 at v0.1; active-pool filter. |
| `layer1_cooling_off.py` | Mode-tuned cooling-off floor. |
| `layer2_multi_source.py` | Independent-kill counter with BOCPD collapse + verbatim primary-source check + premortem lookup. |
| `layer3_veto.py` | Archetype-distribution rule + VetoStatus dataclass. |
| `lifecycle.py` | PB#5 single-fire + M-3 refresh state machine; `veto_lifecycle` table writer. |
| `orchestrator.py` | End-to-end pipeline; persists `counterfactual_retrievals` + `veto_lifecycle` + (when SURVIVOR-dominant) `unread_alerts`. |
| `cli.py` | `python -m src.counterfactual_veto.cli evaluate --ticker NVDA --drawdown-pct 25` |

## Data flow

```
Layer 4 daily monitor (drawdown > 2× cut floor)
    │
    ▼
feature_extractor.extract_candidate_features
    │  (reuses peak_pain_catalog 3-LLM consensus pipeline)
    ▼
CandidateFeatures (universal_core + sector_extensions + per-feature consensus)
    │
    ▼
orchestrator.run_pipeline
    ├── layer1_cooling_off  → if blocking, return WAIT
    ├── layer2_multi_source → if !satisfied, return BLOCKED_MULTI_SOURCE
    └── layer3_veto → retrieve_top_3 → archetype_distribution
                                ├── ≥2 SURVIVOR  → BLOCKED_VETO
                                ├── ≥2 NON-SURVIVOR → PROCEED
                                └── mixed        → MIXED_REVIEW
            │
            ▼
        write counterfactual_retrievals row
        write veto_lifecycle row (if veto invoked)
        write unread_alerts row (if SURVIVOR-dominant) → triggers M-3 push
```

## Dependencies

- `src/peak_pain_catalog/` — catalog data + 3-LLM consensus extraction (re-used).
- `src/mode_classifier/` — produces the mode label that picks the cooling-off floor.
- `src/regime_sidecar/` — provides BOCPD correlation groups for Layer 2 collapse.
- `src/anchor_drift/` — fires M-3 events that trigger `lifecycle.refresh_on_m3`.
- DB: migrations `011_v3_counterfactual_retrieval.sql`, `016_v3_hmac_columns.sql`, `017_v3_alert_type_extension.sql`.

## Calibration gate (Section 7.2)

Validation metric is **archetype-coverage agreement** (NOT NDCG@3 per PB#4):

- ≥80% of 15 calibration test cases retrieve top-3 distribution within ±1 of operator-annotated expected.
- ≥90% canonical SURVIVOR cases retrieve ≥2 SURVIVOR matches.
- ≥90% canonical NON-SURVIVOR cases retrieve ≥2 NON-SURVIVOR matches.

The test set lives at `.claude/references/empirical/peak-pain-archetypes/calibration-test-set-v0.1.md` (15 cases per Section 4.4 PB#7).

## What this module DOES NOT do

- **Catalog feature extraction** — already lives in `peak_pain_catalog/extractor.py` + `consensus.py`. We import and call.
- **Mode classification** — handled by `mode_classifier/`. We receive the mode label.
- **Materiality classification** — handled by `l4_daily_monitor/`. We receive the M-3 event payload.
- **Recommendation emission** — handled by a separate Wave-C subagent.

## CLI quickstart (offline / acceptance test mode)

```bash
python -m src.counterfactual_veto.cli evaluate \
    --ticker PLTR \
    --mode C \
    --drawdown-pct 65 \
    --features-json fixtures/pltr_2022_candidate.json \
    --catalog-json fixtures/peak_pain_catalog_v0_1.json \
    --fires-json fixtures/pltr_2022_kills.json \
    --trigger-at 2022-12-15T20:30:00+00:00
```

Output is a JSON summary of the VetoDecision (cut_status, cooling_off, multi_source, veto + top-3).

## PLTR-2022 Walkthrough (Section 7.3a Walkthrough #1)

The motivating case: PLTR drew down ~65% from its 2021 peak by late 2022. A naive Mode-C cut-fast policy would have exited at the trough (≈$6). The structural picture at that trough:

| Feature | Value | Why it matches SURVIVOR archetypes |
|---|---|---|
| founder_insider_stake_direction | increasing | Karp + Thiel adding |
| cash_runway | >24mo | Net cash positive, high gross margins |
| founder_in_place | yes | Karp, Thiel still active |
| margin_trajectory | improving | gross margin expansion through 2022 |
| revenue_trajectory | growing | +24% 2022 YoY |
| industry_tailwind | intact | gov/AI tailwinds |

Top-3 retrieval against the catalog returns SURVIVOR archetypes (NVDA-2008, AAPL-2003, AMZN-2001) → veto fires → cut blocked → operator override required. PLTR subsequently 8x'd over 2023-2024.

The unit test in `tests/test_counterfactual_veto.py` asserts this exact path.
