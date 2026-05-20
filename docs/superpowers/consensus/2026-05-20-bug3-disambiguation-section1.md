# Bug 3 Disambiguation — Section 1 Consensus

**Date:** 2026-05-20
**Session purpose:** Resolve A1-tight TRIM vs A7-tight HOLD divergence from Phase 5a Wave 2 sweep; decide diagnostic + remediation path.
**Status:** LOCKED (1 consensus item; 3 /review-me iterations terminated on anti-pattern signal escalating to /spec-approve gate).

---

## Operator profile

- Operator role: SE (software engineer); investment-decision-logic ↔ /review-me, harness/data-format/context-engineering ↔ /grill-me per `feedback_role_se_delegates_domain.md`
- Risk preference: hard-stop on /review-me anti-pattern signal (3+ substantive catches per iteration); operator overrides accepted with explicit acknowledged-risk logging
- Concurrent workstreams: 6-bug post-mortem from Phase 5a (committed `9cf9823`), monitor_sweep_run.sh stop-criteria (`b476d11`), Phase 5a Wave 2 (4 fresh-session dispatches completed today)

---

## The position / thesis

**The observation:** GOOGL Phase 5a Wave 2 produced clean Gate 1-3 results on all 4 runs, but Gate 4 surfaced one flag — A1-tight (run_id `d9e4f537`) emitted `summary_code=TRIM` at MEDIUM conviction while A7-tight (run_id `8f0cc43c`) emitted `HOLD` at MEDIUM despite both producing near-identical DCF base (~$205, -6.3% vs baseline $218.60).

**The ambiguity:** A1-tight has `kills_fired=1` (§2.6 stress_failed on spot/IV divergence); A7-tight has `kills_fired=0`. Conviction was MEDIUM in both via the same deterministic rule. The single differing input to summary_code derivation is `kills_fired` itself — an LLM-emitted binary field in pm-supervisor's §2.6 pass.

**Two competing interpretations:**
1. **Framework-coherent** — different perturbations legitimately activate different §2.6 stress sub-tests (e.g., A1-tight's tighter terminal growth creates Gordon-growth-vs-implied-growth tension that A7-tight's higher discount rate doesn't trigger).
2. **LLM-stochastic** — Bug 3 recurrence; the LLM emitted `kills_fired` non-deterministically given functionally similar inputs.

The decision required: what's the diagnostic + remediation action to disambiguate?

---

## Consensus Item #1 — Bug 3 disambiguation path (LOCKED)

### Decision

Sequenced 4-phase remediation with /spec-approve gate before instrumentation:

| Phase | Action | Estimate | Blocking? | Notes |
|---|---|---|---|---|
| **0** | /spec-approve cycle on §2.6 stress sub-test enum: canonical sub-test list + cited fields + firing conditions | 2-3d | YES — gates Phase A semantics + Phase B enum | Breaks the circular dependency caught at /review-me v3 S11 |
| **A** | Multi-envelope inspection (4 envelopes × 2 runs) using locked enum as load-bearing-field whitelist; 3-outcome decision tree | 10min once Phase 0 lands | No (can run for context now; binding interpretation post-Phase 0) | O1/O2/O3 below |
| **B** | pm-supervisor.md §2.6 strict-enum + `kills_fired_evidence[]` schema + content-level HG-29 + dual-read shim for `frameworks_cited` migration | ~2d | YES — gates Phase C | 1.5d code + 0.5d shim per /review-me v3 S12 |
| **B.5** | Deterministic Python kernel for stress sub-tests (`src/p7_recommendation_emitter/stress_test_kernel.py`) | ~2d | No (long-term; deferred to Bug 3 sub-plan in 6-bug post-mortem) | Eliminates bug class at source |
| **C** | N≥5 retries on A1-tight (`deee5742`) + A7-tight (`67bf9200`), parallelized across 2 fresh sessions | ~5hr wallclock | No (verification only) | If `kills_fired` flips on any A1-tight rerun → Bug 3 confirmed; if all consistent → framework-coherent |

### Phase A 3-outcome decision tree (post-Phase 0)

| Outcome | Definition | Action |
|---|---|---|
| **O1** | All 3 upstream envelopes (quant + strategic + catalyst-scout) byte-identical across A1-tight vs A7-tight on load-bearing fields | Bug 3 confirmed at pm-supervisor; Phase B unblocks |
| **O2** | Upstream envelopes differ on load-bearing fields (where "load-bearing" = the field set defined by Phase 0's locked enum) | New **Bug 7** filed (upstream determinism); Bug 3 demoted to dependent; Phase B/C PAUSED until Bug 7 resolves |
| **O3** | Upstream differs on non-load-bearing fields only (narrative wording, ordering — no numeric/categorical shift) | Bug 3 stands at pm-supervisor; Phase B unblocks; log Bug 7-lite for later |

### Phase B specifications (locked at v3, pending Phase 0)

#### B.1 — pm-supervisor.md §2.6 strict-enum (subject to Phase 0 ratification)

```
Initial canonical sub-test enum (Phase 0 may revise):
- STRESS_IV_SPOT_DIVERGENCE
- STRESS_REVERSE_DCF_BREACH
- STRESS_GORDON_GROWTH_VIOLATION
- STRESS_CAPITAL_ALLOCATION_BREAK

Rules:
- Each sub-test has explicit firing condition citing specific upstream field(s) + threshold
- Extensions go through /review-me + pm-supervisor.md commit
- LLM may NOT emit sub-test names outside the enum → HARD FAIL `STRESS_UNENUMERATED` error code
- No "STRESS_OTHER" or narrative-only escape hatch
```

#### B.2 — `kills_fired_evidence[]` schema

```
{
  sub_test_name: <enum-value>,           # from B.1
  upstream_envelope_uuid: <run_id>,      # determinism anchor
  upstream_field_path: <restricted-grammar-string>,
  field_type: "currency" | "percentage" | "ratio" | "count" | "string_categorical",
  threshold: <number | string>,          # number for numeric types, string for string_categorical
  threshold_direction: "above" | "below" | "equals",
  observed_value: <number | string>,     # type matches field_type
  narrative: <optional string>           # NEVER load-bearing for gate
}
```

**Path grammar (locked):** dotted paths only. Array access requires explicit integer index (`frameworks_cited.0.output.x`) OR canonical framework_id (`frameworks_cited.mauboussin_reverse_dcf.output.implied_growth_pct`). No wildcards, no filters, no `[?expr]` syntax. Validator REJECTS paths that don't parse.

**Schema migration required:** `frameworks_cited` becomes a keyed object (`{framework_key: framework_entry}`) instead of an array. Atomic migration via dual-read shim (~0.5d) reading both array-form and keyed-form for 2 weeks, then sunset the array path.

#### B.3 — HG-29 strengthened to content-level validation

```
Per-field-class tolerance:
- field_type="currency"          → relative ±0.1%   (e.g., $487.18B vs $487.20B = MATCH)
- field_type="percentage"        → absolute ±0.05pp (e.g., 17.85% vs 17.92% = MISMATCH)
- field_type="ratio"             → relative ±0.5%   (e.g., 1.10 vs 1.105 = MATCH)
- field_type="count"             → exact match, no tolerance
- field_type="string_categorical" → exact match (case-sensitive, post-trim)

Validator procedure (per kills_fired_evidence[] entry):
1. Resolve upstream_field_path against memos/envelopes/<pre-pm-agent>__<upstream_envelope_uuid>.json per locked grammar
2. Match field_type to tolerance row above; compute resolved_value
3. Assert |resolved_value - observed_value| within tolerance (numeric) OR equal (string)
4. Assert threshold direction is honored against observed_value
5. Assert sub_test_name in canonical enum (B.1)
HARD FAIL on any assertion failure. This mechanically distinguishes framework-coherent
(observed_value derivable from upstream) from LLM-stochastic (LLM hallucinated values).
```

#### B.4 — Grandfather sunset

- Soft-warning until 2026-06-15 (no `kills_fired_evidence` field = warning, not fail)
- Slide to 2026-06-30 if Phase B lands after 2026-06-01
- After sunset, missing field on any envelope with `kills_fired ≥ 1` = HARD FAIL

---

## Critical architectural findings

### CAF-1 — Circular dependency between Phase A and Phase B.1

**The discovery (via /review-me v3 S11):** Phase A's load-bearing-field set classification (used to decide O1 vs O2 vs O3) is defined BY Phase B.1's strict enum. If we run Phase A before B.1 lands, the classification has no canonical reference — LLM-judgment on what "load-bearing" means.

**The resolution:** Phase 0 (/spec-approve cycle on §2.6 enum) lands BEFORE Phase A. Phase A then uses the locked enum as its whitelist. Phase B implementation comes after.

**Generalized lesson:** any new HG that depends on a "field is load-bearing" classification needs the load-bearing-field set as a separate spec-locked artifact, not embedded inline in the gate spec.

### CAF-2 — frameworks_cited schema migration blast radius

**The discovery (via /review-me v3 S12):** Migrating `frameworks_cited` from array to keyed object touches 7+ downstream consumers (analyst_briefs DB rows, evaluator HG-15/20/21/28/32, contamination check, brief-delta-sweep, disposition view, audit-trail reader). The original 1.5d estimate assumed atomic cutover; realistic implementation requires dual-read shim.

**The resolution:** Phase B includes 0.5d dual-read shim. Sunset the array path 2 weeks after B lands on a separate dated cutover commit.

### CAF-3 — String-categorical tolerance gap

**The discovery (via /review-me v3 S13):** Original tolerance table covered numerics only. §2.6 stress sub-tests cite categorical fields (`power_name`, `moat_classification`, `capital_allocation_grade`) too. Missing tier would either reject valid string evidence or silently accept mismatches.

**The resolution:** Added 5th tier `field_type="string_categorical"` with exact-match (case-sensitive, post-trim) semantics.

---

## Design changes from prior baseline

| Element | Pre-Section-1 baseline | Section 1 lock |
|---|---|---|
| Bug 3 sub-plan diagnostic action | Operator choice between (a) inspect / (b) instrument / (c) re-run | Sequenced 4-phase remediation (0+A+B+B.5+C) with /spec-approve gate |
| §2.6 stress sub-test definition | LLM-judgment per pm-supervisor.md spec prose | Strict-enum (4 initial sub-tests; extensions via /review-me) |
| kills_fired field | Binary integer count | Augmented with `kills_fired_evidence[]` array with full provenance |
| HG-29 (summary_code derivation determinism) | Process-rubric soft-check | Content-level validator with upstream envelope cross-validation |
| frameworks_cited shape | Array of framework entries | Keyed object (post-migration); dual-read shim for 2 weeks |
| Tolerance for HG-29 numeric comparison | (not defined) | 5-tier field_type table (currency/percentage/ratio/count/string_categorical) |
| Phase 5a Wave 2 A1-tight TRIM | FLAGGED as ambiguous Bug 3 candidate | Pending resolution via Phase A → Phase C |
| Total cost estimate for Bug 3 sub-plan | ~1d code | ~5-7d engineering + ~5hr Phase C wallclock |

---

## Deferred items

| Deferred item | Reason | Activation trigger |
|---|---|---|
| Phase B.5 Python kernel for stress sub-tests | Bug-class-elimination is long-term; B.1-B.4 unblock immediate flag | After Phase B lands AND Phase C results characterize Bug 3 base rate |
| Bug 7 (upstream determinism) | Only fires if Phase A's O2 outcome surfaces | Phase A O2 finding (upstream load-bearing field divergence between runs) |
| Bug 7-lite (upstream non-load-bearing drift) | Lower priority cosmetic gap | Phase A O3 finding; deprioritized backlog item |
| Phase 5b sweep expansion (A2/A3/A4/A6a/A6b) | Wave 2's flagged A1-tight blocks Phase 5b admissibility | After Section 1 resolution (Phase A outcome + Phase B/C) |

---

## What's locked vs what's open

### Locked
- Diagnostic + remediation sequencing (Phase 0 → A → B → C)
- Phase A 3-outcome decision tree (O1/O2/O3)
- §2.6 strict-enum framing (canonical list pending Phase 0 ratification)
- kills_fired_evidence[] schema with restricted path grammar
- HG-29 content-level validator with 5-tier tolerance
- Grandfather sunset 2026-06-15 (sliding to 2026-06-30 if Phase B late)
- /spec-approve as the gating mechanism for Phase 0
- frameworks_cited dual-read shim for migration safety

### Open (for future sections or follow-up)
- **Phase 0 enum content** — the actual list of canonical sub-tests with firing conditions is operator-+-/review-me work in Phase 0 itself; this consensus only locks that Phase 0 must happen, not what it concludes
- **Phase B.5 Python kernel architecture** — deferred to Bug 3 sub-plan in 6-bug post-mortem (commit `9cf9823`)
- **Phase 5b axis selection** — gated on Wave 2 final resolution
- **Sister-surface fall-throughs in /daily-monitor, /entry-check, /size** — per 6-bug post-mortem S7; out of scope for this section

---

## Convergence record

| Iteration | Substantive catches | Direction |
|---|---|---|
| v1 → v2 | 5 substantive (S1-S5) + 1 CRITICAL (S3 HG-29 structural-only) + 2 polish | added |
| v2 → v3 | 3 substantive (S8 tolerance per-field-class; S9 path grammar lock; S10 Phase A outcome branches) | tightened |
| v3 | 3 substantive (S11 CRITICAL circular dependency; S12 migration blast radius; S13 string-categorical tolerance) | **anti-pattern triggered** |
| Resolution | Operator confirmed escalation per /review-me protocol Step 7 — /spec-approve gate added at Phase 0; sequencing inverted | **escalated, not patched** |

The loop terminated NOT on convergence but on the /review-me anti-pattern signal (3 substantive at v3 → "plan moving target → escalate to spec-level"). The operator confirmation of the push-back is the lock event for Section 1, not a v4 review.

---

*Section 1 closed. Next: Phase A inspection can begin in parallel with Phase 0 /spec-approve cycle (Phase A finding is preliminary until Phase 0 lands).*
