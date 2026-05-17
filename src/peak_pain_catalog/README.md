# peak_pain_catalog

3-LLM iterative-consensus extraction pipeline for the peak-pain archetype catalog.

Validates the ~160-case catalog at `.claude/references/empirical/peak-pain-archetypes/catalog-v0.1.md` against the v3 spec contract:

- **Section 4.4** — two-layer schema (universal-core + sector-specific).
- **Phase 4 Q4** — feature-typed consensus rule (categorical exact / ordinal within-±1).
- **Section 5 Q3** — 3-LLM iterative-consensus pipeline (5-iteration cap).
- **Section 6 Q6 PB#7** — priority subset strategy (~45 cases pre-launch + lazy tail).
- **Section 5 Q1** — HMAC-signed audit chain.
- **Section 7.4** — cold-start parallel track (priority subset runs offline before v0.1 launch).

## Module layout

| File | Responsibility |
|---|---|
| `parser.py` | Slice catalog markdown into `CaseRecord` objects (one per case row). |
| `feature_typing.py` | Declare categorical/ordinal kind per feature + ordinal orderings. |
| `extractor.py` | Single-LLM forced-JSON feature extraction with verbatim-quote requirement. |
| `consensus.py` | 3-LLM iterative-consensus state machine, ≤5 iterations. |
| `persistence.py` | Build payload, HMAC-sign, UPSERT into `peak_pain_archetypes`. |
| `priority_runner.py` | Run the ~45-case priority subset (15 calibration + 30 canonical). |
| `lazy_runner.py` | Lazy validation for tail (~115 cases) on first-retrieval. |
| `cli.py` | `priority-run` / `validate-case` / `list-priority` commands. |

## Model mix

Default 3-LLM triplet (`consensus.DEFAULT_MODEL_MIX`):

```
LLM #1: claude-sonnet-4-6   # cost-efficient primary
LLM #2: claude-sonnet-4-6   # independent Sonnet for cheap diversity
LLM #3: claude-opus-4-7     # Opus for tie-breaking on edge cases
```

Override per-call by passing `model_mix=` to `run_consensus`.

## Consensus rule (Phase 4 Q4)

Per feature, the 3 extracted values are checked pairwise:

- **Categorical features** (`founder_in_place`, `moat_state`, `regulatory_standing`, ...): exact-match required (case- and whitespace-tolerant).
- **Ordinal features** (`cash_runway`, `margin_trajectory`, `industry_tailwind`, ...): within ±1 step on the declared ordering counts as agreement.

Largest agreement band determines the grade:

| Band size | Iter | Grade |
|---|---|---|
| 3 | 1 | HIGH |
| 3 | ≥2 | MEDIUM |
| 2 | ≤5 | retry with surfaced disagreement |
| 2 | =5 (cap) | LOW |
| 1 | =5 (cap) | DISPUTED |

Roll-up to `validation_status`:
- Any DISPUTED feature (core or extension) → `disputed`.
- Any LOW universal-core feature (no DISPUTED) → `pending`.
- Otherwise → `validated`.

## Usage

### Cold-start (offline, pre-launch)

```bash
# Dry-run: HMAC-sign payloads to stdout, no Postgres writes
python -m src.peak_pain_catalog.cli priority-run --dry-run

# Production: write to Postgres
# Auth: subscription (Claude Code OAuth) by default per BUILD_LOG decision 1.
# Make sure `claude /login` is active and ANTHROPIC_API_KEY is UNSET.
# (If ANTHROPIC_API_KEY is set, the legacy API-billing path is used instead.)
export PEAK_PAIN_HMAC_KEY=$(openssl rand -hex 32)
export PEAK_PAIN_DSN="postgresql://postgres@127.0.0.1/equity_research"
python -m src.peak_pain_catalog.cli priority-run
```

**Auth model:** the runner checks `ANTHROPIC_API_KEY`. If set, it uses the legacy `anthropic` SDK with API-key billing (CI / dev convenience). If unset, it uses `claude-agent-sdk` which delegates to your local `claude` CLI's OAuth session, billing against your subscription tier (Max 20x recommended for the ~6,750-call priority run). See `src/peak_pain_catalog/claude_sdk_client.py` for the adapter.

### Lazy tail validation (called by VETO retrieval at runtime)

```python
from src.peak_pain_catalog.lazy_runner import validate_on_first_retrieval

result = validate_on_first_retrieval(
    "TWLO-2022",
    catalog_md_path=".claude/references/empirical/peak-pain-archetypes/catalog-v0.1.md",
    dsn=os.environ["PEAK_PAIN_DSN"],
)
if not result.retrieval_safe:
    # drop from current top-N; queue for operator review
    ...
```

## Outputs

Per validated case the pipeline writes one row to `peak_pain_archetypes`
(see `db/migrations/011_v3_counterfactual_retrieval.sql`):

- `universal_core_features` — `{feature: value}` (6 entries).
- `sector_extensions` — `{feature: value}` (per-sector subset).
- `universal_core_consensus` — rich per-feature JSONB:
  ```json
  {
    "cash_runway": {
      "value": ">24mo",
      "consensus": "HIGH",
      "iterations": 1,
      "agreement_count": 3,
      "verbatim_quotes": ["..."],
      "per_iteration_values": [{"iter": 1, "values": [">24mo", ">24mo", ">24mo"]}]
    }
  }
  ```
- `validation_status` — `validated` / `pending` / `disputed`.
- `consensus_method` — `feature-typed-v0.1` (bumped when the rule changes).
- `notes` — embeds the HMAC signature: `[hmac=<hex>;alg=sha256;ts=<iso>] ...`.

## What this module does NOT do

- **Catalog hygiene cadence (PB#6)** — separate scheduler subagent.
- **Counterfactual VETO retrieval** — separate Wave C subagent (consumes the
  validated rows produced here).
- **Catalog drift detection** — separate.
- **Strict-equality consensus** — superseded by Phase 4 Q4 feature-typed rule.

## Testing

```bash
pytest tests/test_peak_pain_catalog.py -v
```

Smoke tests use a stub `AnthropicClient` returning canned JSON — no live API
calls. Coverage:

- Catalog markdown parser → CaseRecord roundtrip.
- Feature-typing rule (categorical exact, ordinal within-±1).
- Consensus state machine: HIGH (unanimous), MEDIUM (converged-after-iter), LOW (2/3 at cap), DISPUTED (no agreement at cap).
- Persistence: HMAC signature stable + verifiable.
