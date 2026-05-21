# Phase 1 acceptance spec — tactical-overlay enum coverage gate

**Status:** locked 2026-05-22 (closes G-CHECK-1 from observability-readiness-v5-final).
**Scope:** tactical-overlay rollout Phase 1. Defines the operational meaning of the Section 2.1 v5 acceptance criterion "all 5 enum values appear VALID in renderer output."

## Why this spec exists

Section 2.1 v5 §"Phase 1 acceptance" says: *"Hard gate: all 5 enum values appear VALID in renderer output (correctness check). Fire-rate logging for Phase 2 baseline; no threshold-setting at Phase 1."*

The criterion was unfalsifiable as written: no sampling unit (per-run? per-distinct-ticker? per-N-runs?), no acceptance window (calendar time? envelope count?), and no resolution path if some surfaces never fire (e.g., LOW-CONVICTION VETO requires a LOW-conviction run with `tactical_bin = unavailable`, which may not occur naturally in the first N runs).

## The 5 renderer surfaces

Per `src/p8_tactical_overlay/overlay.py::_DISPOSITION_MAP` (12-cell matrix) + Section 2.1 v5 §"Renderer rules":

| # | Surface | Trigger | cell_disposition value |
|---|---|---|---|
| 1 | `BUY-HIGH` | conviction=HIGH ∧ tactical_bin=positive | `BUY-HIGH` |
| 2 | `BUY-MED` | conviction=MEDIUM ∧ tactical_bin=positive | `BUY-MED` |
| 3 | `HOLD` | any (conviction, bin) routed to HOLD per matrix (9 of 12 cells) | `HOLD` |
| 4 | `AVOID` | conviction=LOW ∧ tactical_bin ∈ {negative, neutral, positive} | `AVOID` |
| 5 | `LOW-CONVICTION VETO` | conviction=LOW ∧ tactical_bin=unavailable (renders as `HOLD` cell + veto flag) | `HOLD` + veto annotation |

Surface 5 is a renderer flag, not a distinct enum value. The flag is what makes it the 5th surface even though the underlying `cell_disposition` is `HOLD`.

## Sampling unit + acceptance window

**Sampling unit:** envelope (i.e., one tactical-overlay run = one envelope = one observation point). NOT per-ticker (a single ticker can produce multiple envelopes across mode changes / recurring research). NOT per-N-runs (artificial batching).

**Acceptance window:** the first `M` envelopes where `M = max(envelope_count_at_Phase_2_trigger, 50)`. In practice this is the same window as the Phase 2 trigger condition (`envelope_count ≥ 50`). Phase 1 closes at the SAME moment Phase 2 fires — no separate closeout event.

**Rationale for collapsing Phase 1 window onto Phase 2 trigger:** decoupling created an unbounded "Phase 1 may close before Phase 2 starts" ambiguity. Collapsing means Phase 1 acceptance is a precondition for Phase 2 quadrant analysis; if Phase 1 hasn't seen all 5 surfaces by envelope 50, Phase 2 can't reliably read returns spread (some surfaces are unobserved, so quadrant decisions for those rows are vacuous).

## Acceptance gate (mechanical check)

A query over the first 50 envelopes' tactical-overlay outputs (read from `memos/envelopes/tactical-overlay__<run_id>.json` filtered by `created_at` ≤ Phase 2 trigger date):

```
1. count(envelopes where cell_disposition == "BUY-HIGH") ≥ 1
2. count(envelopes where cell_disposition == "BUY-MED") ≥ 1
3. count(envelopes where cell_disposition == "HOLD" AND NOT low_conviction_veto) ≥ 1
4. count(envelopes where cell_disposition == "AVOID") ≥ 1
5. count(envelopes where cell_disposition == "HOLD" AND low_conviction_veto == true) ≥ 1
```

All 5 ≥ 1 → Phase 1 PASSES. Phase 2 quadrant analysis begins.

If any surface = 0 → **partial pass**: log which surfaces did/didn't fire and proceed to Phase 2 anyway, but mark the missing-surface row in the Phase 2 quadrant matrix as "INSUFFICIENT DATA — defer to next 50-envelope batch." Do NOT stall Phase 2 indefinitely waiting for a rare surface (e.g., AVOID may be rare if the universe of tickered names is skewed against LOW-conviction outcomes).

## Why partial-pass not hard-fail

Hard-fail would create an unbounded waiting condition: a rare surface (e.g., AVOID) may legitimately not appear in 50 envelopes for a watchlist composed primarily of HIGH/MEDIUM-conviction names. Refusing to start Phase 2 would defeat the purpose of Phase 2 evaluation.

Partial-pass with explicit "INSUFFICIENT DATA" annotation per row is honest: Phase 2 can still evaluate the surfaces that DID fire, and the missing-surface annotation flags which Phase 2 quadrant decisions are pending more data.

## Open variation (not blocking Phase 2 start)

If Phase 1 surfaces have lopsided counts (e.g., 45 HOLDs, 3 BUY-HIGHs, 1 BUY-MED, 1 AVOID, 0 LOW-CONVICTION VETO), the Phase 2 trigger fires but several quadrant rows have very thin data. The Phase 2 quadrant decision matrix (returns spread × ack-rate) should annotate confidence per row, not just produce decisions. This is Phase 2's concern, not Phase 1's, and is left to the Phase 2 spec (separate doc; written when Phase 2 trigger approaches).

## Falsification

This spec is falsified if any of:
- Phase 2 trigger fires but Phase 1 acceptance query can't be mechanically run (envelopes not on disk, schema drift, file naming irregular).
- All 5 surfaces fire but Phase 2 quadrant analysis still can't compute returns spread (linkage gap to `counterfactual_ledger` — addressed separately by G-CHECK-4).
- An additional 6th surface emerges in practice (e.g., a renderer error mode that's neither one of the 5 listed) — would require a Section 2.1 v6 amendment.
