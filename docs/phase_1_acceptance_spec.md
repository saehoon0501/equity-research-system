# Phase 1 acceptance spec — tactical-overlay enum coverage gate (v2)

**Status:** v2 locked 2026-05-22 (folds Reviewer A iteration-1 catches: decouple events; partial-pass termination cap; ticker-concentration logging; re-enumerate surfaces incl. null/halt + Stage-incomplete; pin JSON paths).
**Scope:** tactical-overlay rollout Phase 1. Defines the operational meaning of the Section 2.1 v5 acceptance criterion "all 5 enum values appear VALID in renderer output."

## Why this spec exists

Section 2.1 v5 §"Phase 1 acceptance" was unfalsifiable as written (no sampling unit, no window, no resolution path on rare-surface absence). This spec closes those gaps and is itself an artifact of the /review-me v5-final + iteration-2 review pass.

## The 5 renderer surfaces (plus 2 filtered states)

Per `src/p8_tactical_overlay/overlay.py::_DISPOSITION_MAP` (12-cell matrix) + Section 2.1 v5 §"Renderer rules":

| # | Surface | Trigger | cell_disposition value |
|---|---|---|---|
| 1 | `BUY-HIGH` | conviction=HIGH ∧ tactical_bin=positive | `BUY-HIGH` |
| 2 | `BUY-MED` | conviction=MEDIUM ∧ tactical_bin=positive | `BUY-MED` |
| 3 | `HOLD` (without veto) | any (conviction, bin) ∈ HIGH/MEDIUM routing to HOLD (8 cells of 12) | `HOLD` |
| 4 | `AVOID` | conviction=LOW ∧ tactical_bin ∈ {negative, neutral, positive} | `AVOID` |
| 5 | `LOW-CONVICTION VETO` | conviction=LOW ∧ tactical_bin=unavailable | `HOLD` + veto annotation |

### Filtered states (NOT counted toward the 5-surface gate)

- **null/halt state:** tactical-overlay agent errored, upstream MCP (e.g., `mcp__market_data__get_prices`) failed, or required parameters were unavailable. Envelope persisted at `memos/envelopes/tactical-overlay__<run_id>.degraded` (sentinel marker — see /research-company §0 hook contract). Filter these from the Phase 1 acceptance scan; track separately via fire-rate of `.degraded` sentinels.
- **Stage-incomplete state:** tactical_cell is null pending pm-supervisor Stage 3 completion (Section 2 v3-final timing race). Envelope JSON has `tactical_cell: null` with `phase_1_provisional: true`. Filter these — but if the same run_id later gets a Stage 3 cell completion, the Stage-3-completed envelope is the one counted.

Rationale: these states are not renderer-surfaces — they're error/transient states. Counting them toward the 5-surface gate would falsely "pass" Phase 1 by surfacing failures.

## Sampling unit + acceptance window (v2 — decoupled events)

**Sampling unit:** envelope (one tactical-overlay run = one observation point after filtering). NOT per-ticker (a single ticker can produce multiple envelopes). NOT per-N-runs.

**Phase 1 pass event:** record `phase_1_pass_envelope_idx` independently when all 5 surfaces first reach ≥1 in the rolling envelope count. Could be earlier or later than Phase 2 trigger.

**Phase 2 trigger event:** separate condition: `envelope_count ≥ 50 AND ticker_count ≥ 5`.

**Both events tracked separately** in `docs/phase_gates.md` §1 — Phase 1 row + Phase 2 row + the gap (envelopes between Phase 1 pass and Phase 2 trigger) as a diagnostic signal for v6 design. v1 collapsed them; v2 preserves the diagnostic signal.

**Patch-trigger pinning (iteration-2 nit fold):** the Phase 1 pass envelope_idx MUST be recorded in `phase_gates.md` in the SAME commit as the envelope that crossed the threshold — not via retrospective backfill. Pinning the patch to envelope-write prevents the "diagnostic we promised but didn't capture" failure mode.

**Pass-state labels (iteration-2 nit fold):** Phase 1 pass outcome MUST be labeled explicitly in `phase_gates.md`:
- `PASS_FULL_5` — all 5 surfaces ≥1 within the window.
- `PASS_4_WITH_ARCH_ABSENCE(<surface_name>)` — 4 of 5 surfaces present, named surface treated as architecturally absent per the N=200 cap.
- `PASS_3_OR_FEWER_WITH_ARCH_ABSENCE(<surface_names>)` — only if ≤1 missing AND escalated per falsification clause.

v6 design reviewers MUST be able to distinguish these states without parsing prose.

**Partial-pass termination cap (v2 NEW):** if any surface remains at 0 after `envelope_count ≥ 200`, treat as "architecturally absent" — surface is removed from the Phase 1 gate set and recorded as such in `phase_gates.md`. Prevents "INSUFFICIENT DATA — defer" from becoming an immortal todo. Recorded outcome: "AVOID never observed in 200 envelopes; treated as architecturally absent per Phase 1 spec v2."

## Acceptance gate (mechanical query — v2 with paths pinned)

A query over the first N envelopes' tactical-overlay outputs:

**JSON file scope:** `memos/envelopes/tactical-overlay__<run_id>.json` files where:
- filename pattern: `tactical-overlay__[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.json` (UUIDv4 in the run_id position)
- `.degraded` sentinel files EXCLUDED (filtered states above)
- `phase_1_provisional: true` files EXCLUDED unless a corresponding Stage-3-completed envelope exists (in which case the completed one is counted)

**JSON key path:** the `cell_disposition` value lives at `.tactical_cell.cell_disposition` (top-level → tactical_cell object → cell_disposition string). The veto flag is derivable as: `conviction == "LOW" AND .tactical_cell.cell_disposition == "HOLD"`. Reference: `src/evaluator_gates/tactical_envelope_shape.py` for the canonical envelope shape.

**Per-surface count query (shell + jq pseudo-code):**

```bash
# Surface 1: BUY-HIGH
ls memos/envelopes/tactical-overlay__*.json 2>/dev/null \
  | xargs -I{} jq -r 'select(.tactical_cell.cell_disposition == "BUY-HIGH") | .run_id' {} \
  | wc -l

# (Repeat per surface; LOW-CONVICTION VETO requires joining envelope to pm-supervisor envelope
#  for conviction value, or extracting conviction directly from tactical_cell if persisted there.)
```

## Acceptance criteria (v2 with hard cap)

```
At envelope_count = N (sliding):
  if all 5 surfaces ≥ 1 → Phase 1 PASSES at envelope_idx=N (record in phase_gates.md §1)
  if any surface = 0 AND N < 200 → partial-pass with annotation
  if any surface = 0 AND N >= 200 → treat absent surfaces as "architecturally absent"
                                    → Phase 1 PASSES with the remaining surfaces gate set
                                    → record absence + reasoning in phase_gates.md §1
```

## Ticker-concentration diagnostic (v2 NEW)

Log per-ticker envelope counts within the Phase 1 window. If any ticker contributes >40% of envelopes:

- NOT a hard fail (operator's actual research cadence may legitimately concentrate on hot names)
- Surface in `phase_gates.md` §1 as a diagnostic: "ticker XXX contributed Y% of envelopes; surface distribution may not generalize"
- Helps Phase 2 quadrant analysis interpret which rows are ticker-skewed vs broadly grounded

## Falsification (v2 unchanged)

Spec is falsified if any of:
- Phase 2 trigger fires but Phase 1 acceptance query can't mechanically run (envelopes not on disk, filename irregular).
- All 5 surfaces fire but Phase 2 quadrant analysis still can't compute returns spread (linkage gap to ledger — addressed separately by G-CHECK-4).
- A 6th renderer surface emerges in practice that is neither one of the 5 listed nor a filtered state → would require Section 2.1 v6 amendment.
- `envelope_count = 200` reached with > 1 surface still missing → suggests systematic gate-design failure, not data-sparsity; escalate to v6 design review.
