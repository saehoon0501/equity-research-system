# Phase 5a Post-mortem + 3-Bug Remediation Plan — v1 (DRAFT, awaiting /review-me)

**Status:** v4-FINAL CONVERGED — /review-me iter 4 returned "v4 looks solid, no substantive issues" (explicit lock signal). 4 iterations, 13 substantive catches + 4 polish, arc 5→4→4→0. The v3 flat-not-converging concern was bug-count-driven (3→4→6); v4 held count at 6 and closed the 4 open spec gaps without adding new bugs — healthy convergence. Locked for commit. Sub-plan structure ratified; ready for operator authorization to execute the wave-1 hotfix (Bug 1+1b+6).

**Trigger:** GOOGL Phase 5a perturbation sweep executed 2026-05-19 (4 runs, ~4hr operator time). Per converged pre-registration `8909a87`, 4 axes × directions: A7-loose (`wacc.erp 4.40`), A7-tight (`5.00`), A1-loose (`a1_premium 2.0pp`), A1-tight (`1.0pp`). Per pre-reg materiality routing, results were to be compared vs baseline `d438b802` ($218.60 / $114.86 / $338.50) with ≥2% IV shift triggering /grill-me adjudication.

**Headline finding:** the 4 runs produced **zero scientifically valid sweep data points**. **Six** independent bugs surfaced after two /review-me iterations (Bug 4 elevated per iter 1 S2; Bug 5 extracted as shared retrieval helper per iter 2 S11; Bug 6 added for PARAMETERS_USED block injection per iter 2 S12). Phase 5a cannot be re-executed until all 6 are closed.

---

## Bug 1 — §1.5 tagged-snapshot non-determinism (CRITICAL)

### Diagnosis

The `/research-company` orchestrator's §1.5 Step 3 spec says: *"If TAG IS NOT NULL, replace `parameters_active`'s default `tag IS NULL` filter by querying the underlying `parameters` table with `WHERE tag = $TAG` plus the standard DISTINCT ON / latest-effective_at logic."*

This is an LLM-prompted action. Under adversarial test (4 sweep tags, 4 fresh-main-session dispatches), 3 of 4 runs **silently fell through** to `parameters_active` (tag IS NULL) despite the tag being correctly resolved by the PreToolUse gate and properly recorded in `run_parameters_snapshot.tag`.

### Evidence

| Run | tag in DB | swept value seeded | snapshot value | Sweep applied? |
|---|---|---|---|---|
| 37ae3333 (A7-loose) | `51ee7736-...` ✓ | wacc.erp=4.40 | **wacc.erp=4.60** | NO |
| a6f4e54c (A7-tight) | `67bf9200-...` ✓ | wacc.erp=5.00 | **wacc.erp=4.60** | NO |
| 285e3423 (A1-loose) | `10b79db7-...` ✓ | a1_premium=2.0 | **a1_premium=1.5** | NO |
| 7ee43faf (A1-tight) | `deee5742-...` ✓ | a1_premium=1.0 | a1_premium=1.0 | YES |

Direct DB-side diff between baseline d438b802 snapshot and A1-loose snapshot returns ZERO key-value differences — they are byte-equivalent. (The `effective_parameters_hash` recorded differs only because the LLM computed canonical-JSON serialization non-deterministically — a separate sub-bug.)

### Root cause

The §1.5 query is LLM-executed (the orchestrator is an LLM agent following the spec markdown). LLM agents don't reliably execute conditional branching ("IF tag is not null, change the query"). 1 of 4 worked; 3 of 4 didn't. No mechanical guard catches the fall-through.

HG-33 (parameter_snapshot_lineage_verification) passes because it only validates snapshot ↔ envelope hash matching, not snapshot ↔ tagged-parameter consistency.

### Remediation

**Option 1 (Recommended) — Move §1.5 Step 3 out of LLM execution into deterministic code.**

Create `scripts/snapshot_parameters.py` (or extend an existing parameter-orchestration script). The orchestrator invokes it as a subprocess with `--run-id`, `--ticker`, `--tag` arguments. The script:
1. Queries `parameters` with explicit tag predicate
2. Computes canonical JSON deterministically (Python `json.dumps(sort_keys=True, separators=(',', ':'))`)
3. INSERTs the row into `run_parameters_snapshot`
4. Returns the snapshot hash on stdout

The orchestrator reads stdout, NOT generates the SQL itself.

**Option 2 (Belt-and-suspenders) — Add a DB-side AFTER INSERT trigger on `run_parameters_snapshot`.**

```sql
CREATE OR REPLACE FUNCTION validate_tagged_snapshot()
RETURNS TRIGGER AS $$
DECLARE
  expected_map jsonb;
BEGIN
  IF NEW.tag IS NULL THEN
    RETURN NEW;
  END IF;
  SELECT jsonb_object_agg(parameter_key, value)
  INTO expected_map
  FROM (
    SELECT DISTINCT ON (parameter_key) parameter_key, value
    FROM parameters
    WHERE tag = NEW.tag AND effective_at <= NEW.run_started_at
    ORDER BY parameter_key, effective_at DESC
  ) sub;
  IF NEW.effective_parameters_jsonb <> expected_map THEN
    RAISE EXCEPTION 'snapshot tag-mismatch for run_id %: snapshot does not match tagged parameter rows', NEW.run_id;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_validate_tagged_snapshot
AFTER INSERT ON run_parameters_snapshot
FOR EACH ROW EXECUTE FUNCTION validate_tagged_snapshot();
```

This raises an exception that aborts the run if the snapshot doesn't match the tagged rows. Combined with Option 1, makes fall-through unambiguous and detectable.

### Effort estimate
~0.5d for Option 1 + Option 2 combined. New migration 038.

---

## Bug 1b — `effective_parameters_hash` non-determinism (CRITICAL) — promoted per S5

### Diagnosis

The `effective_parameters_hash` field on `run_parameters_snapshot` is supposed to be a SHA-256 of the canonical-JSON-serialized `effective_parameters_jsonb`. The /research-company §1.5 spec specifies: `canonical_json(EFFECTIVE_MAP)  # sort_keys=True, separators=(',', ':')`. Empirically: A1-loose's snapshot is BYTE-EQUIVALENT to baseline's at the JSONB level (DB-side direct diff returns zero key-value differences), but the recorded hashes differ (`490470a6...` vs `a6de5f97...`).

The hash computation is LLM-executed (the orchestrator computes the canonical JSON and SHA-256). LLMs do not reliably implement canonical JSON serialization or cryptographic hashing.

### Impact (system-wide, not just sweeps)

Every downstream gate that relies on hash consistency (HG-33 lineage verification, contamination check chain, evidence_graph determinism) is built on an unreliable hash. If two byte-equivalent inputs produce different hashes, the chain integrity claim is false. This affects production runs too, not just sweeps.

### Remediation

Move hash computation into the same `scripts/snapshot_parameters.py` from Bug 1. Python's `hashlib.sha256` + `json.dumps(..., sort_keys=True, separators=(',', ':'))` produces deterministic output. The orchestrator reads the hash from script stdout; LLM never computes it.

### Effort estimate
Folded into Bug 1's `snapshot_parameters.py` — net zero additional work.

---

## Bug 2 — Quant subagent abandons ceteris paribus on swept runs (CRITICAL)

### Diagnosis

Even on the ONE run that successfully applied the perturbation (A1-tight `7ee43faf`), the quant subagent re-derived ALL DCF inputs from scratch instead of inheriting the baseline ceteris paribus. The swept axis was `dcf.austere_terminal_growth_dgs10_premium_pct` (1.5 → 1.0pp); only that one input should have changed. Instead:

| Input | Baseline d438b802 | A1-tight 7ee43faf | Same axis perturbed? |
|---|---|---|---|
| β | 1.10 | **1.05** | NO (β is not in any perturbation axis) |
| Effective tax rate | 0.17 | **0.16** | NO |
| Weight equity | 0.98 | **0.94** | NO |
| Weight debt | 0.02 | **0.06** | NO |
| WACC | 9.55% | **9.40%** | NO (only A1 in this sweep) |
| DCF Narrative base | $218.60 | **$460.00** | Side effect of all above changes |
| DCF Narrative bull | $338.50 | **$610.00** | Same |
| DCF Austere base | $187.12 | **$385.00** | Same |

A1-tight is the *tightening* direction (lower terminal-growth premium → lower terminal value → lower IV). The expected DCF base shift was negative (e.g., $218.60 → ~$200 territory). Instead, IV moved +110% to $460.

The quant subagent's own envelope note acknowledges the re-derivation: *"dispatch brief revised inherited DCF to 440 with prob-weight 446; austere narrowed to 385 (12.5pct gap from 14.4pct prior); reflects updated cohort + Cloud-backlog conversion economics post-Q1 2026 print."* It improvised a NEW cash-flow model rather than re-running the EXISTING model with the swept parameter.

### Root cause

The `quantitative-analyst.md` spec describes warm-start behavior in qualitative terms ("inherit from prior brief") AND positively permits time-based refresh on new fundamentals. The A1-tight subagent's own note ("reflects updated cohort + Cloud-backlog conversion economics post-Q1 2026 print") confirms the subagent believed it was *allowed* to refresh on new earnings data, NOT just on swept parameters.

The §1.5 PARAMETERS_USED block injection only carries the parameter values themselves; it doesn't carry the prior_brief's actual computed inputs (β, weights, tax) — those live in the prior envelope. The subagent treated the new Q1 2026 print availability as license to refresh the full cohort + cash-flow trajectory.

**Per /review-me iter 1 S1 — explicit precedence rule needed:**

The spec must explicitly resolve: does sweep-tagged dispatch (`tag != NULL`) OVERRIDE the normal warm-start refresh-on-new-fundamentals policy?

- **If YES (recommended for sweeps):** sweep-tagged runs FREEZE all non-perturbed inputs to the immediate prior_brief's values regardless of new data availability. New fundamentals are ignored in favor of controlled-experiment isolation.
- **If NO:** sweep results are inherently contaminated by time-based refresh; pre-reg materiality routing arithmetic is unreliable. Phase 5a as designed is unfit-for-purpose, period.

Without this precedence rule, HG-34 (proposed below) will trip on legitimate warm-start refreshes during non-sweep runs. The rule must be explicit, sweep-tag-scoped, and enforced by the gate.

### Remediation

**Add a "sweep-tagged ceteris paribus contract" section to `quantitative-analyst.md`:**

```markdown
## Sweep-tagged ceteris paribus contract (HARD RULE — supersedes warm-start refresh policy)

**Precedence:** When PARAMETERS_USED carries `tag` != NULL, this contract
OVERRIDES the normal warm-start refresh-on-new-fundamentals policy
described elsewhere in this spec. Sweep-tagged runs are controlled
experiments, NOT routine warm-start re-runs. New earnings prints, new
filings, new macro data published after prior_brief's emit-time are
INTENTIONALLY IGNORED for sweep runs to preserve the perturbation
isolation property.

**Procedure:**

1. Read prior_brief via DB (existing warm-start path).
2. For EVERY computed input (β, tax rate, debt weights, cohort, FCF
   projections, revenue growth path, margin path, fade rates, terminal
   values), inherit the prior_brief value verbatim. This applies REGARDLESS
   of whether new fundamentals became available since prior_brief.
3. The ONLY values that may differ between this run and prior_brief are
   parameters whose value in PARAMETERS_USED block differs from the value
   used by prior_brief. Call this set the "swept axis set."
4. Compute the swept axis set by comparing each PARAMETERS_USED block entry
   against the prior_brief's `parameters_used.effective_parameters_hash`
   chain. Any difference = a perturbation. Everything else = inherited.
5. Emit the swept axis set in your envelope under `sweep_axis_set: [...]`
   along with a per-axis old → new mapping.

Violation = HARD FAIL via evaluator HG-34.

**Non-sweep runs (tag IS NULL):** the existing warm-start refresh policy
applies unchanged. Subagent may refresh on new fundamentals per existing
discipline. This contract does not constrain production runs.
```

**Stale-prior_brief refresh requirement (per /review-me iter 2 S10):**

Sweep-tagged dispatch freezing to prior_brief is correct for *relative* IV-shift arithmetic but misleading if prior_brief is stale (e.g., prior_brief from Q4 2025 print while Q1 2026 has been published). Materiality routing reads absolute levels, so the entire sweep can drift if the operating point is stale.

**Procedure for pre-reg cycle:**
1. Before minting sweep tags, the operator MUST run a fresh production (`tag IS NULL`) `/research-company` dispatch to ensure prior_brief reflects the most-recent fundamentals.
2. The fresh production run becomes the `seed_brief_id` that all subsequent sweep-tagged runs inherit from.
3. `seed_brief_id` MUST be no older than `MAX(most_recent_earnings_print_date, NOW() - 7d)`. If older, abort the sweep and re-seed.
4. The pre-reg commit body explicitly references `seed_brief_id: <uuid>` and `seed_brief_emitted_at: <ISO>`; cert-hash falsifiability test verifies this metadata is present and matches a real `analyst_briefs` row.
5. All sweep runs in the cycle inherit from this single seed_brief_id (not from each other). Chained sweeps are explicitly prohibited at the pre-reg level unless the pre-reg declares them.

**Add new evaluator gate HG-34 (sweep_ceteris_paribus_consistency):**

For runs where `tag` != NULL AND prior_brief exists:
1. Pull prior_brief's quant envelope from `analyst_briefs` or `memos/envelopes/`.
2. Compare current envelope's `wacc_regime.beta_used`, `effective_tax_rate`, `weight_equity`, `weight_debt`, `cost_of_debt_method` against prior's.
3. For every input NOT in the run's `sweep_axis_set`, current must equal prior. HARD FAIL on mismatch.
4. For DCF assumptions (revenue growth path, margin path, FCF projections), compare against prior's equivalent. Allow modest tolerance (±1% per Tier-2 LLM extraction floor) but flag any larger drift as HARD FAIL.

### Effort estimate
~1-2d. New section in quantitative-analyst.md + new HG-34 in evaluator.md.

### HG-34 retrieval mechanism (closing /review-me iter 1 S3 spec gap)

**Canonical source:** `analyst_briefs` table is the canonical source-of-record. Path:
1. Pull current run's `prior_brief_id` from quant envelope (existing field `warm_start_source_brief_id`).
2. `SELECT content FROM analyst_briefs WHERE brief_id = $1` to retrieve prior_brief's full structured content.
3. Parse YAML envelope from the `content` column.
4. Extract baseline WACC inputs + DCF assumptions.

**Conflict-resolution rule:** if `memos/envelopes/quantitative-analyst__<prior_run_id>.json` exists AND diverges from the DB-stored `analyst_briefs.content`, the DB row wins. The filesystem envelope is a debug artifact, not authoritative.

**Chained sweeps:** if prior_brief itself was a sweep-tagged run (i.e., `analyst_briefs.tag != NULL`), the ceteris paribus inheritance traces to the IMMEDIATE prior — current run's perturbation is layered on top of prior sweep's parameter state. The "tagged ↔ tagged" inheritance chain is supported via the same mechanism.

---

## Bug 4 — Swept-axis direction monotonicity violation (CRITICAL) — elevated per /review-me iter 1 S2

### Diagnosis

A1-tight `7ee43faf` emitted DCF base = **$460** (vs baseline $218.60 — i.e., +110% upward). The A1 axis is `dcf.austere_terminal_growth_dgs10_premium_pct`, and A1-tight is the *tightening* direction (1.5pp → 1.0pp, i.e., LOWER terminal growth → LOWER terminal value → LOWER IV).

**Pre-reg's §7 sensitivity arithmetic (8909a87):** "+17% IV per 100bp premium" → tightening 50bps should yield ~**-8.5% IV** → $218.60 × 0.915 ≈ **$200**. Actual is $460 — wrong direction AND wrong magnitude (off by ~230% absolute, ~13× in delta).

This cannot be explained by Bug 2 (ceteris paribus violation) alone. Bug 2 explains *why* β/tax/weights drifted, but β=1.05 vs 1.10 only shifts WACC by ~5bp → IV by ~1-2%. The +110% IV move requires either:

- **Hypothesis A (sign flip):** subagent applied 1.0pp as "loose" (i.e., HIGHER terminal growth premium) instead of "tight" (LOWER). Misinterpreted the swept value's direction.
- **Hypothesis B (wrong-axis perturbation):** subagent applied 1.0pp to a different DCF input (e.g., interpreted it as growth_y1_pct = 1.0pp, or as fade_years scalar, etc.) rather than terminal-growth premium.
- **Hypothesis C (full re-derivation):** subagent improvised new FCF assumptions that happened to yield $460 by coincidence; the swept parameter was simply ignored in the DCF math.

**A1-tight quant envelope evidence:** `terminal_growth_input: "DGS10 4.59pct + 1.0pct premium = 5.59pct (PARAMETERS_USED dcf.austere_terminal_growth_dgs10_premium_pct=1.0; ...)"`. So the subagent DID identify 1.0 correctly as a premium and DID compute terminal growth correctly at 5.59% (vs baseline ~6.09%). The math chain is right at the input level.

But then DCF base $460 follows — far too high. That means the cash-flow projections themselves were inflated despite correct terminal growth. **Hypothesis C is most likely.** Bug 2's ceteris paribus contract should prevent this, but only if HG-34 catches it.

### Root cause

There is no mechanical gate that verifies the SIGN AND MAGNITUDE of the IV response to a swept perturbation. The pre-reg's expected IV shift (e.g., A1-tight expects -7-10%) is documented but not enforced.

### Remediation

**Add HG-35 (swept_axis_direction_monotonicity):**

**Scope (per /review-me iter 2 S9):** HG-35 applies ONLY to swept axes whose IV response sign is unambiguously determinable from finance theory. The monotonicity registry at `.claude/references/parameter_monotonicity.json` is INTENTIONALLY restricted to:
- **DCF inputs:** `dcf.austere_terminal_growth_dgs10_premium_pct` (↑premium ↑IV), `dcf.austere_growth_fade_years` (↑years ↑IV), `dcf.austere_margin_fade_years` (↑years ↑IV — slower margin decay), `dcf.austere_roic_fade_years` (↑years ↑IV)
- **WACC inputs:** `wacc.erp` (↑ERP ↓IV), `wacc.erp_sensitivity_band_bps` (no IV sign — band-only; EXEMPT)

**Non-DCF/non-WACC inputs are EXEMPT from HG-35**: `quality_gate.*` thresholds (binary pass/fail, no IV monotonicity), `sleeve.*` caps (no IV effect if non-binding), `mode.*` classifications (no continuous IV sensitivity), `evaluator.gate.*` (downstream-of-IV, not upstream). Pre-reg axes that fall in the EXEMPT set MUST declare exemption in the pre-reg commit body explicitly (a sentence like "Axis A_X is exempt from HG-35 per registry classification"); commit-hash falsifiability test verifies the exemption declaration exists. Registry-side check: any axis in `parameter_monotonicity.json` with sign field = "exempt" cannot be a hard-fail target.

**Procedure:**
1. Per axis in `sweep_axis_set` AND in the non-exempt registry subset, retrieve the *expected sign* from `.claude/references/parameter_monotonicity.json`.
2. Compare current DCF base to prior_brief's DCF base (retrieved via Bug 5's shared helper).
3. If swept axis moved in the "↑IV" direction, current DCF base MUST be ≥ prior; if "↓IV" direction, current DCF base MUST be ≤ prior. HARD FAIL otherwise.
4. Magnitude check (soft): compare actual IV % shift to pre-reg's predicted range (e.g., A1-tight expects -7-10%); flag if outside [-50%, +50%] of predicted. Soft-finding for /grill-me adjudication, not hard fail.

**Registry registration discipline:** Each known sweepable parameter has a registry entry with `{sign: "↑IV" | "↓IV" | "exempt", finance_theory_citation: "..."}`. Pre-reg authors that introduce a NEW sweepable axis MUST add a registry entry as part of the pre-reg commit; the registry update + the pre-reg commit are a single atomic action. Axes not in the registry cannot be swept (commit-hash falsifiability test enforces this).

**Bootstrap circularity resolution (per /review-me iter 3 S15):** the registry-existence check is enforced AT-EXECUTION-TIME, not at pre-reg-authoring-time. The flow:
1. Author writes pre-reg with new axis, INCLUDING the proposed registry-entry inline in the pre-reg's body (e.g., section "Registry diff: this pre-reg adds entry for `new.parameter.key` with sign=↑IV").
2. /review-me cycle adversarially reviews BOTH the pre-reg AND the proposed registry diff jointly. Reviewer can challenge the sign (e.g., "is ↑IV actually correct for this parameter under all reinvestment-rate regimes?").
3. On convergence, the pre-reg commits AND adds/updates the registry file in a SINGLE atomic commit (via `git add` of both files).
4. After commit, HG-35 reads the post-commit registry state for downstream execution. Future runs see the new axis as registered; cert-hash falsifiability test reads the same commit's diff and confirms the registry entry is present.

No pre-existing-registry-required check at pre-reg-authoring time. First-time-axis introduction is unblocked.

### Effort estimate
~0.5d. New HG-35 in evaluator.md + new monotonicity registry file + per-axis registration discipline. Depends on Bug 5 (shared prior_brief retrieval helper) — see revised sequencing below.

---

## Bug 5 — Shared prior_brief retrieval helper (INFRASTRUCTURE) — extracted per /review-me iter 2 S11

### Diagnosis

Bug 2's HG-34 and Bug 4's HG-35 both require retrieving the prior_brief's full structured content (quant envelope, DCF base/bear/bull, WACC inputs) from `analyst_briefs`. If each gate implements its own retrieval, the two implementations may diverge (one queries by `brief_id`, another by `prior_run_id`; one parses YAML differently than the other). Without a shared helper, Bug 2 and Bug 4 cannot land in parallel — they fight for the same retrieval surface.

### Remediation

Extract the retrieval into `src/p7_evaluator/prior_brief_retrieval.py` (NEW module). Single function:

```python
def fetch_prior_brief_inputs(prior_brief_id: str) -> dict:
    """Returns canonical prior_brief inputs as a flat dict.
    Reads from analyst_briefs.content (DB canonical source).
    Falls back to filesystem envelope ONLY if DB row missing
    (with a warning log).
    """
    # Parses analyst_briefs YAML; returns the FULL prior_brief
    # content as a structured dict. Includes (non-exhaustive):
    # {wacc_inputs: {beta, tax, weight_equity, weight_debt, cost_of_debt_method},
    #  dcf_narrative: {bear, base, bull, growth_path, margin_path, fade_rates, reinvestment_rates},
    #  dcf_austere: {bear, base, bull, growth_path, margin_path, fade_rates, reinvestment_rates, roic_path},
    #  fcf_projections: [...10y array of dicts...],
    #  forensic_observations: {...},
    #  outside_view: {...},
    #  ... (any other fields present in the YAML envelope, returned as-is)}
```

**Schema flexibility (per /review-me iter 3 S16):** the function returns the FULL parsed YAML envelope as a structured dict — NOT a fixed-key contract. Callers (HG-34, HG-35, future consumers) extract the keys they need. The function provides a single canonical parsing path with conflict resolution (DB > filesystem) and stale-warning logging, but does NOT pre-define an exhaustive schema. This avoids locking future expansion behind a schema update.

For Bug 2's HG-34 specifically: HG-34 walks the returned dict for `wacc_inputs.beta`, `wacc_inputs.weight_equity`, `dcf_narrative.growth_path`, `dcf_narrative.margin_path`, `dcf_austere.fade_rates`, etc. as needed. If a field is missing from prior_brief's content, HG-34 emits a soft-finding (cannot enforce ceteris paribus on a field not present) rather than hard-failing. This degrades gracefully.

Both HG-34 (Bug 2) and HG-35 (Bug 4) call this single function. Test coverage: 1 happy path + 1 missing-DB-row fallback + 1 stale-filesystem-vs-current-DB conflict + 1 missing-field soft-degrade.

### Effort estimate
~0.5d. New file + unit tests + reference from HG-34 + HG-35.

---

## Bug 6 — PARAMETERS_USED block injection into dispatch prompts is LLM-formatted (CRITICAL) — added per /review-me iter 2 S12

### Diagnosis

The /research-company §1.5 Step 6 spec instructs the orchestrator to compose per-subagent PARAMETERS_USED header blocks and INJECT them at the top of each dispatch prompt. This is LLM-formatted text generation. Same failure class as Bug 1: the orchestrator can omit keys, misformat values, or silently drop tag-scoped entries.

Even with Bug 1 (snapshot in deterministic Python) and Bug 1b (deterministic hash), the BRIDGE between the snapshot and the subagent's reading is still LLM-mediated. None of Bug 1/1b/2/4 catches a mis-formatted dispatch prompt — HG-33/34/35 verify snapshot ↔ envelope, not snapshot ↔ dispatch-prompt-text.

A subagent reads the PARAMETERS_USED block at the top of its prompt and treats it as ground truth (per quant-analyst.md "block wins" contract). If the block is corrupted in transit, the subagent operates on wrong inputs even though the snapshot in DB is correct.

### Remediation

Extend `scripts/snapshot_parameters.py` (from Bug 1) to ALSO emit the canonical PARAMETERS_USED block as a frozen string per subagent. The orchestrator INTERPOLATES this frozen string verbatim into dispatch prompts — no LLM formatting.

Add HG-36 (parameters_used_block_dispatch_consistency):

**Hook layer (per /review-me iter 3 S14 — original v3 wording incorrectly specified PostToolUse):** the dispatch prompt body is visible to **PreToolUse** hooks on the `Task` tool (the field `tool_input.prompt`). PostToolUse only sees the agent's return value, not its input prompt.

Two implementable paths, operator picks one in the Bug 6 sub-plan:

**Path A — PreToolUse hook capture (recommended):**
1. PreToolUse hook on `Task` tool fires for each subagent dispatch.
2. Hook extracts `tool_input.prompt` body.
3. Parses for `=== PARAMETERS_USED ===` to `=== END PARAMETERS_USED ===` block.
4. Byte-compares against the canonical block emitted by `snapshot_parameters.py` for this run_id + subagent (looked up via per-run scratch file `memos/dispatch/<run_id>__<subagent>.parameters_used.txt` written by the script).
5. On mismatch, hook exits non-zero → Claude Code rejects the dispatch.

**Path B — subagent-side echo (fallback if PreToolUse hook surface is constrained):**
1. Each subagent's spec includes a "first emission step": echo the PARAMETERS_USED block verbatim into the envelope under `parameters_used_block_echo: <string>`.
2. Evaluator HG-36 byte-compares envelope's echo against canonical block.
3. Slightly weaker than Path A (LLM could mis-echo) but doesn't require new hook infrastructure.

Path A is preferred but Path B is acceptable if the PreToolUse hook surface is constrained.

### Effort estimate
~0.5d. Extends Bug 1's snapshot script + new HG-36 in evaluator.md + hook-level parameter prompt capture.

---

## Bug 3 — PM-supervisor summary_code non-determinism (CRITICAL)

### Diagnosis

A7-tight `a6f4e54c` had quant envelope numerics **identical to baseline** (Bug 1 fall-through — same DCF inputs and same DCF outputs). Per pm-supervisor's own conviction_rollup:

| Field | Baseline | A7-tight | Identical? |
|---|---|---|---|
| conviction | MEDIUM | MEDIUM | YES |
| conviction_from_rule | MEDIUM | MEDIUM | YES |
| mode | B_prime | B_prime | YES |
| tier | core_fundamental | core_fundamental | YES |
| size_band_if_long | {0,0,0} | {0,0,0} | YES |
| sleeve_cap_check.status | PASS_SOFT_WARNING | PASS_SOFT_WARNING | YES |
| **summary_code** | **HOLD** | **TRIM** | **NO** |

Identical conviction + identical sleeve + identical mode → DIFFERENT BUY/HOLD/TRIM/SELL bin. The conviction_rationale text differs but both reach MEDIUM via the deterministic "MEDIUM rule" (debate_add_count=3, kills_fired=0, anchor_drift=0).

### Root cause

HG-29 (summary_code derivation determinism) is enforced as a process-rubric soft-finding, not as a mechanical assertion. The actual derivation: `(conviction, technical_exit_signal, valuation_signal) → summary_code` involves pm-supervisor's LLM judgment on whether spot price (398.80) above bull case (338.50) constitutes:
- "overpriced but compounder, hold" (HOLD) OR
- "overpriced beyond bull, take profit" (TRIM)

Both narratives are defensible. The LLM flips between them across runs given identical inputs.

Possible interpretation: A7-tight's TRIM may actually be the *correct discipline* (price > bull = take profit per framework), while baseline's HOLD is the conservative "8th reaffirmation continue" carry-over. This raises a secondary question: is the spec under-specified, OR is the LLM under-disciplined?

### Remediation

**Two sub-options:**

**Option A — Lock the derivation to a deterministic decision-tree in code.**

Move summary_code derivation out of pm-supervisor LLM judgment into a Python function `src/p7_recommendation_emitter/summary_code_derive.py`:

```python
def derive_summary_code(conviction, spot, bear, base, bull,
                       conviction_override=False, kill_fired=False):
    if kill_fired:
        return "SELL"
    if conviction == "HIGH" and spot <= base * 0.85:  # 15% MoS
        return "BUY"
    if spot > bull:
        return "TRIM"  # price > bull always = take profit
    if base * 0.85 < spot <= base * 1.15:
        return "HOLD"
    if base * 1.15 < spot <= bull:
        return "HOLD"  # in compounder band, hold even if rich
    if spot < bear:
        return "BUY"
    return "HOLD"  # default
```

PM-supervisor calls this function via subprocess; envelope `summary_code` field is populated by the function's return value, not by LLM emission. Then HG-29 verifies the envelope summary_code matches the function's output for the run's inputs.

This may be controversial — locks in specific MoS bands and bull-overshoot interpretation. Some operators may want LLM judgment for edge cases.

**Option B — Run N=3 with majority vote on summary_code.**

Each /research-company run dispatches pm-supervisor 3 times in parallel; emit majority-vote summary_code. Expensive (~3× cost on the load-bearing decision step), but preserves LLM judgment while ensuring stability.

**Option C — Spec out the derivation criteria more precisely in pm-supervisor.md.**

Detailed decision tree in prose with examples; rely on LLM following the spec more reliably. Cheapest but weakest — may not actually close the non-determinism.

### Effort estimate
- Option A: ~1d (code + HG-29 strengthen + spec update)
- Option B: ~0.5d (orchestration change), but ~3× runtime cost forever
- Option C: ~0.5d (spec edit), but uncertain effectiveness

### Recommended (with backtest gate per /review-me iter 1 S4)

Option A for the deterministic derivation, with Option C's detailed decision tree as the spec authority that the function implements. The LLM is informed of the rule but cannot deviate.

**Backtest gate (HARD prerequisite before merge):**

The proposed decision tree includes the rule `spot > bull → TRIM`. Applied to baseline `d438b802` (spot=$398.80, bull=$338.50, conviction=MEDIUM), this rule would have emitted **TRIM**, not HOLD. Baseline emitted HOLD.

This is a tree-vs-baseline contradiction. Either:
- **The tree is wrong** (HOLD is the correct discipline at price > bull for compounders; rule needs refinement to handle "MEDIUM + price > bull" as HOLD-not-TRIM)
- **Baseline was wrong** (baseline's 8 consecutive reaffirmations were drift, not discipline; the tree is correct and we've been mis-classifying for weeks)

This MUST be resolved before tree codification. Concrete backtest gate:

1. Implement the proposed `derive_summary_code` function.
2. Run it against:
   - Baseline `d438b802` inputs → check output
   - Last 8 GOOGL warm-start reaffirmations' inputs → check outputs
   - 4-5 other historical /research-company runs across different tickers (AAPL, MSFT, AMZN if available)
3. For each historical run, compare tree output vs envelope's actual emitted summary_code.
4. If tree contradicts ≥1 historical run, dispatch /grill-me to operator: "the tree contradicts baseline X — is the tree wrong, or was the baseline wrong? Operator must resolve before tree codification."
5. Only after operator-resolution of all contradictions does the tree merge.

This is a meta-finding: the perturbation experiment surfaced that the framework's BUY/HOLD/TRIM/SELL discipline may itself be under-specified. The LLM has been improvising the bin assignment; nobody noticed until two parallel runs flipped. The backtest gate forces explicit operator adjudication of the discipline before codification.

---

## Sequencing (revised per /review-me iter 2 S11 — Bug 5 inserted before Bug 2/4)

Bug 1 + Bug 1b are HARD PREREQUISITE — without them, sweep dispatches are scientifically meaningless AND hash chain is broken. Bug 6 lands in the same hotfix wave (shares Bug 1's snapshot script).

Bug 5 (shared prior_brief retrieval helper) must land BEFORE Bug 2 and Bug 4 because both consume it. Without Bug 5, Bug 2 and Bug 4 cannot land in parallel.

Bug 2 (HG-34) and Bug 4 (HG-35) can land in parallel once Bug 5 is in place.

Bug 3 must land AFTER Bug 2, because Bug 3's decision tree consumes quant numerics that Bug 2 stabilizes.

Bug 3 backtest gate may surface operator-decisions that block merge for days/weeks. Treat as variable schedule.

| Order | Bug | Estimate | Blocks Phase 5a retry? |
|---|---|---|---|
| 1 | Bug 1 + Bug 1b + Bug 6 (Python script + DB trigger + deterministic hash + canonical PARAMETERS_USED block + HG-36) | ~1d (incl Bug 6 extension) | YES |
| 2 | Bug 5 (shared prior_brief retrieval helper) | ~0.5d | YES (blocks #3a/#3b) |
| 3a | Bug 2 (ceteris paribus contract + HG-34 + stale-prior_brief refresh rule) | ~1.5-2d | YES |
| 3b (parallel with #3a) | Bug 4 (direction monotonicity HG-35 + parameter registry) | ~0.5d | YES |
| 4 (after #3a lands) | Bug 3 (deterministic summary_code + HG-29 strengthen + **backtest gate** + /grill-me adjudication of historical contradictions) | ~1d code + 1-N weeks for operator backtest adjudication | YES |

**Bug 3 adjudication off-ramp (per /review-me iter 3 S17):** if /grill-me adjudication of tree-vs-historical contradictions exceeds **2 weeks**, escalate to /spec-approve cycle for framework-discipline rewrite. Bug 3 merge gated on the spec-revision outcome instead of operator-Q&A resolution. This prevents Bug 3 from stalling the entire Phase 5a retry indefinitely. The 2-week threshold is calibrated on a typical operator's response cadence; longer than that suggests the contradictions cannot be resolved by Q&A and require framework-level rethinking.
| 5 | Phase 5a retry (re-seed sweep tags + re-execute 4 dispatches after all bugs land + stale-prior_brief refresh ran) | ~4hr operator time | n/a |

### Realistic cost projection (per /review-me iter 2 S13)

| Phase | Engineering | Operator |
|---|---|---|
| Code work (Bugs 1+1b+2+4+5+6) | ~4-5d | minimal |
| Evaluator.md HG-table extensions + cross-references for HG-34/35/36 | ~0.5d | minimal |
| Rubric calibration runs on new HGs (process-rubric vs gate-table alignment) | ~0.5d | minimal |
| Migration 038 review + cycle to lock in DB trigger | ~0.5d | review approval |
| Bug 3 code + backtest harness | ~1d | minimal |
| Bug 3 backtest adjudication (operator answers tree-vs-history contradictions via /grill-me) | minimal | **1-N weeks** |
| Phase 5a retry execution | minimal | ~4hr |

**Realistic total: ~6-7 days engineering + 1-N weeks for Bug 3 backtest adjudication.** Earlier estimate of "~3 days engineering" did not include evaluator gate-table extensions, rubric calibration, or migration review cycles — those are hidden costs in this codebase. The Bug 3 adjudication latency is the variable bottleneck; if the tree-vs-history contradictions are extensive (likely, per /review-me iter 2 Q2 framing), the operator may need to re-architect the framework discipline itself.

**Sister-surfaces follow-up (out of scope here, flagged per S7):** /daily-monitor, /entry-check, /size likely have analogous bugs:
- LLM-conditional-branching fall-throughs (Bug 1 pattern)
- LLM-judgment-on-bins for summary_code-equivalents (Bug 3 pattern)
- LLM-formatted block injection into subagent prompts (Bug 6 pattern)
Schedule as separate plan items after Phase 5a retry validates the /research-company fixes.

---

## Open questions for /review-me

1. **Bug 1 Option 1 vs Option 2:** is the Python-script approach actually safer than just the DB trigger? The trigger alone might suffice if it's well-tested. The script adds operational surface area (subprocess invocation from orchestrator).

2. **Bug 2 — what defines "the swept axis set"?** The proposed mechanism compares PARAMETERS_USED to prior_brief's parameters_used.effective_parameters_hash chain. But what if prior_brief is from a tag != NULL run too (e.g., chained sweep)? Does the inheritance rule still hold? Probably yes (inherit from immediate prior), but the spec needs to be explicit.

3. **Bug 3 — is Option A (deterministic decision tree) actually correct?** A7-tight emitted TRIM despite identical numerics to baseline's HOLD. Was the LLM's TRIM actually more correct (price > bull → take profit)? If so, the "right" answer is to update baseline's discipline, not lock in HOLD. Need framework-discipline review of the actual MoS bands before coding.

4. **Should the sweep results be cleaned up from `run_parameters_snapshot` and `parameters` (4 tags' worth of rows)?** The 4 invalid runs' snapshots are not contaminating future runs (they're keyed by tag), but they sit in the DB as historical artifacts. Retention policy unclear.

5. **What about A1-tight's catastrophically wrong DCF base ($460 vs expected ~$200)?** Even after Bug 2 lands and the ceteris paribus contract is enforced, the prior_brief's DCF base is $218.60 — the new DCF should land near that but slightly LOWER (tightening direction). Is there enough information to re-construct the correct ceteris-paribus-tightened result analytically without re-running the sweep?

---

## Provisional plan structure (revised per /review-me iter 2)

This document is the root remediation artifact. After /review-me convergence on this doc, it gets committed, and the following sub-plans spawn:

- `docs/superpowers/plans/2026-05-XX-bug1-bug1b-bug6-snapshot-determinism-hotfix.md` — combined wave-1 hotfix (Python script + DB trigger + deterministic hash + canonical PARAMETERS_USED block + HG-36)
- `docs/superpowers/plans/2026-05-XX-bug5-prior-brief-retrieval-helper.md` — extracted shared helper plan (blocks Bug 2 + Bug 4)
- `docs/superpowers/plans/2026-05-XX-bug2-bug4-quant-determinism.md` — combined plan for ceteris paribus contract (Bug 2) + direction monotonicity (Bug 4), since both consume Bug 5's retrieval helper
- `docs/superpowers/plans/2026-05-XX-bug3-summary-code-determinism.md` — Bug 3 with backtest gate; merge contingent on operator adjudication of tree vs historical contradictions

Each sub-plan goes through its own writing-plans + subagent-driven-development cycle.

---

## Convergence record

| Iteration | Substantive issues caught | Direction |
|---|---|---|
| v1 → v2 | 5 substantive (S1 sweep-tag/warm-start precedence rule needed; S2 CRITICAL — A1-tight $460 unexplained by Bug 2 alone, elevated to NEW Bug 4 with HG-35 direction-monotonicity gate; S3 HG-34 retrieval mechanism under-specified — added canonical analyst_briefs source + chained-sweep handling; S4 Bug 3 decision tree contradicts baseline — added backtest gate; S5 hash non-determinism elevated to Bug 1b) + 3 polish (S6 sequencing serialized; S7 sister-surfaces flagged; S8 sub-plan structure revised). Net: 3 bugs → 4 bugs (Bug 1 + Bug 1b + Bug 2 + Bug 3 + Bug 4); 1 new HG (HG-35); 1 new prerequisite (Bug 3 backtest gate). | added + tightened |
| v2 → v3 | 4 substantive (S9 HG-35 registry scope DCF+WACC only with exemption discipline; S10 stale-prior_brief refresh requirement added to Bug 2 with seed_brief_id age-bound; S11 Bug 4↔Bug 2 dependency — extracted shared retrieval helper as NEW Bug 5; S12 PARAMETERS_USED block injection LLM-formatted — added NEW Bug 6 with HG-36) + 1 polish (S13 realistic cost projection ~6-7d eng + 1-N weeks adjudication, not the under-counted "~3d"). Net: 4 bugs → 6 bugs; 1 new HG (HG-36); 1 new infrastructure module (Bug 5); registry-scope discipline tightened; cost-realism added. | added + tightened |
| v3 → v4 | 4 substantive (S14 HG-36 hook layer was specified as PostToolUse — corrected to PreToolUse on `Task` tool with subagent-side echo fallback; S15 HG-35 registry bootstrap circularity — resolved with atomic registry-diff-in-pre-reg-commit; S16 Bug 5 schema rigidity — function returns FULL parsed YAML envelope as flexible dict; S17 Bug 3 adjudication off-ramp — 2-week → /spec-approve escalation). All catches addressed in this terminal iteration. | tightened (no new bugs) |
| v4 | **0 substantive (CONVERGED)** — reviewer iter 4 returned "v4 looks solid, no substantive issues." Q1-Q4 closed (dual-path framing clean; atomic-commit operable; flexible dict + soft-degrade unblocks HG-34 spec; 2-week off-ramp strictly better than no off-ramp). Arc 5→4→4→0 = healthy convergence, the flat-then-converged pattern when bug-count holds steady and spec gaps close. | **converged** |

Total: 4 iterations, 13 substantive catches + 4 polish catches, arc 5→4→4→0, terminated on explicit reviewer lock signal "v4 looks solid, no substantive issues." Healthy convergence per /review-me protocol after v3 meta-warning resolved by v4's spec-gap closures without adding new bugs.
