# mode_classifier

Critical-path component #2 of the v0.1 equity-research system.
Classifies tickers into B / B' / C bins and assigns a HIGH/STANDARD
company-quality flag per
`docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md`
**Section 2.2** (layered architecture, lines 95-130) and Section 7 PB#3.

## Layered architecture

```
DataAdapter ── Stage 1 (mechanical rule) ─┬─ rule_clean ──> bin
                                          └─ overlap   ──> Stage 3 (LLM tie-breaker)
                                                                │
                                                                ▼
                                                              bin
QualityAdapter ── Stage 2 (HIGH/STANDARD flag on chosen bin) ───┘
                                                                │
                                                                ▼
                                                  mode_classifications row
```

| Stage | File | Pure? | Description |
|---|---|---|---|
| 1 | `stage1_market_structural.py` | yes | Section 1 Item 1 rule: cap / vol / profitability / growth |
| 2 | `stage2_company_quality.py` | yes | Section 7 PB#3 quality refinement: founder tenure / ROIIC / profitability-path |
| 3 | `stage3_overlap_tiebreaker.py` | no (LLM I/O) | Forced-JSON, verbatim-evidence, N=5 self-consistency tie-breaker |
| Orchestrator | `orchestrator.py` | no (DB I/O) | Composes 1→2→(3); INSERTs into `mode_classifications` |
| Recheck | `recheck.py` | no (DB I/O) | Phase 4 Q5 quarterly mismatch detection |
| CLI | `cli.py` | no | `python -m mode_classifier.cli ...` |

Adapters (`adapters.py`) are dependency-injected so the same module can
run against fixtures in tests, against the default yfinance + EDGAR
data sources at the CLI, or against a future `mcp__fundamentals` PIT
adapter when Sharadar lands in v0.5.

## Stage 1 rule (verbatim from Section 2.2)

```
IF market_cap > $50B AND vol < 25% AND profitable >5y AND growth < 12% -> bin: B
IF market_cap > $50B AND profitable AND (vol > 25% OR growth > 15%)    -> bin: B'
IF market_cap < $50B OR not_yet_profitable OR narrative-driven          -> bin: C
```

**Overlap detection.** When more than one rule fires (boundary cases
e.g. cap=$60B + growth=14% + vol=30%) OR no rule fires (data missing),
the orchestrator hands off to Stage 3.

## Stage 2 refinement (verbatim)

```
HIGH-quality flag if (founder >=10yr tenure if B, >=5yr if B') AND
                    (ROIIC > 15% sustained 5yr if B) AND
                    profitability-path-clear
STANDARD flag otherwise
```

C-bin handling is conservative — same 5-year founder threshold as B'
plus profitability-path-clear. Missing data → STANDARD.

## Stage 3 LLM tie-breaker

Per Section 2.2 lines 116-121:

* **Single-attribute** call — bin only, no joint sizing/horizon output
* **Forced JSON** schema: `{bin, confidence, rationale, evidence_quotes}`
* **Verbatim evidence** required — every quote in `evidence_quotes`
  must be a substring of the prompt's EVIDENCE block; if none can be
  verified, the sample defaults to `bin = "C"` (conservative)
* **Self-consistency N=5 at temp=0.7**, modal vote with conservative
  tie-break (C > B' > B)
* **Sonnet by default**, **Opus on `high_stakes=True`** (Section 6 Q1)

The module imports `anthropic` and uses `client.messages.create(...)`.
For tests inject a fake `client` whose `messages.create` returns
objects with the same shape (see `tests/test_mode_classifier.py`).

## Persistence — `mode_classifications` table

Schema per `db/migrations/008_v3_recommendations.sql` lines 231-264.
Append-only (the trigger `mode_classifications_no_modify` rejects
UPDATE/DELETE). Reclassifications chain via `prior_classification_id`.
The orchestrator emits exactly the columns the migration declares; the
JSONB `rule_outcomes` and `llm_tiebreaker` payloads match the migration's
documented shapes (`{B_match, B_prime_match, C_match, overlap_detected, ...}`
and `{model, prompt_version, rating, confidence, rationale, evidence_quotes,
self_consistency}`).

## CLI

```bash
# Classify a single ticker, persist to DB
python -m mode_classifier.cli classify --ticker NVDA

# Dry-run (no DB write)
python -m mode_classifier.cli classify --ticker NVDA --no-persist

# Force Opus for the tie-breaker
python -m mode_classifier.cli classify --ticker NVDA --high-stakes

# Phase 4 Q5 quarterly bulk recheck
python -m mode_classifier.cli recheck-all
```

## Out of scope (handled elsewhere)

* Pre-mortem trigger on reclassification — separate subagent
* `/disposition` view dashboard integration — separate skill
* Cold-start handling (S0 sidecar) — separate component
* Mode-implied-vol semi-annual check — separate quarterly job
* HMAC signing for `audit_provenance` — separate audit-trail skill

## Reference indexes

| Spec ref | What it pins |
|---|---|
| Section 2.2 (lines 95-130) | Layered architecture, all three stages |
| Section 7 PB#3 | Quality refinement criteria |
| Phase 4 Q1 | Layered architecture reconciliation S1+S7 |
| Phase 4 Q5 | Per-name quarterly re-classification |
| Section 6 Q1 | Sonnet/Opus default + escalation |
| Migration 008 | `mode_classifications` table contract |
