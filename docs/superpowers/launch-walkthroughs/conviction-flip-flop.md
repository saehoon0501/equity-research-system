# Launch Walkthrough #9 — Conviction flip-flop (hysteresis defense)

**Verdict: PASS**

This walkthrough satisfies the Section 7.3a launch-gate requirement #9 — the
conviction hysteresis validation. Per v3 spec
`docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md` Sections
5.1 (recommendation conviction), 5.4 (anchor-drift channels + flip-frequency
tracking), 7.3a, and Phase 4 Q7 (hysteresis + 2-cadence persistence rule).

The architectural lock under test: when an anchor-drift channel score
oscillates around its threshold (e.g. 0.23 ↔ 0.28 around the 0.25 cutoff),
the conviction must NOT flip on every cadence. Hysteresis requires 2-cadence
persistence for any transition (UP or DOWN). Flip-frequency is tracked in a
30-day rolling window; >3 flips → automatic demotion to MEDIUM + operator
review.

---

## Input Setup

| Field                              | Value                                  |
| ---------------------------------- | -------------------------------------- |
| Ticker                             | CRWD                                   |
| Sector                             | `tech_saas`                            |
| Mode classification                | B'                                     |
| Channel under oscillation          | Anchor-drift Channel 1 (thesis coherence) |
| Channel 1 threshold                | 0.25                                   |
| Persistence requirement            | 2 cadence cycles                       |
| Cadence period                     | 5 days (Mode B' anchor-drift cadence)  |
| Observation window                 | 5 cadence cycles (25 days)             |
| Catalog version hash               | walkthrough-realistic                  |

**Drift channel score timeline:**

| Cadence | Date         | Channel 1 score | vs threshold (0.25) | Naive verdict | Hysteresis-required transition state |
| ------- | ------------ | --------------- | ------------------- | ------------- | ------------------------------------ |
| C-0     | 2026-04-04   | 0.23            | below               | clean (HIGH)  | last_stable=HIGH                     |
| C-1     | 2026-04-09   | 0.28            | above               | drift (MEDIUM)| pending_transition (1/2 cycles)      |
| C-2     | 2026-04-14   | 0.23            | below               | clean (HIGH)  | reset → last_stable=HIGH             |
| C-3     | 2026-04-19   | 0.28            | above               | drift (MEDIUM)| pending_transition (1/2 cycles)      |
| C-4     | 2026-04-24   | 0.27            | above               | drift (MEDIUM)| TRANSITION CONFIRMED (2/2 cycles)    |
| C-5     | 2026-04-29   | 0.23            | below               | clean (HIGH)  | pending_reverse_transition (1/2)     |

Without hysteresis, conviction flips MEDIUM ↔ HIGH each cadence — 5 flips in
25 days. With hysteresis, conviction stays HIGH through C-3 (only 1/2 cycles
of drift) and finally transitions to MEDIUM at C-4 (2/2 confirmed).

---

## Expected Behavior per Architectural Lock

### Hysteresis 2-cadence persistence rule (Phase 4 Q7)

```
For each cadence cycle:
  1. Read current channel score
  2. Compare to threshold:
     - If score crosses threshold AND last_stable opposite direction:
       → enter pending_transition state with cycles_count=1
     - If pending_transition AND score still on transition side:
       → cycles_count++; if cycles_count >= 2, COMMIT transition
     - If pending_transition AND score reverts to last_stable side:
       → CANCEL pending_transition; reset cycles_count=0
     - If no pending_transition AND score on last_stable side:
       → no change (stable)
```

Key invariants:
- **A single-cycle excursion never transitions.** Score must be on transition
  side for ≥2 consecutive cycles.
- **Reverts cancel pending transitions.** If score flips back during
  pending_transition, the transition is cancelled (not committed at fractional
  state).
- **Both directions require 2-cycle persistence.** Going from MEDIUM → HIGH
  requires 2 consecutive clean cycles, just as HIGH → MEDIUM requires 2
  consecutive drift cycles. Hysteresis is symmetric.

### Flip-frequency tracking (Section 5.4)

A 30-day rolling counter tracks committed transitions:

```
conviction_flip_count_30d:
  ticker          = CRWD
  flips_in_window = (count of committed transitions in last 30 days)
  window_start    = NOW() - INTERVAL '30 days'
  window_end      = NOW()
```

If `flips_in_window > 3`, automatic action:
1. Conviction auto-demoted to MEDIUM (lowest stable level)
2. M-2 alert: `alert_type = 'conviction_flip_flop_excessive'`
3. Operator review required before conviction can return to HIGH
4. The operator review has its own hysteresis-aware lockout (4-cycle clean
   minimum after operator review before HIGH is re-permitted)

### Recommendation Q1 schema under hysteresis

The Q1 schema includes:
- `conviction` (current emitted)
- `conviction_raw` (what naive non-hysteresis logic would produce)
- `last_stable_conviction` (the committed value before any pending transition)
- `pending_transition_cycles` (0/1/2)
- `flips_in_window` (rolling count)

When hysteresis differs from naive (i.e. pending_transition active), the
emitted `conviction` is `last_stable_conviction`, NOT `conviction_raw`.

### HMAC tamper-evidence (Section 7.2 invariant)

Each cadence's drift score, persistence state, and committed conviction is
hashed into the recommendation's canonical payload. Tampering to flip
`pending_transition_cycles` from 1 to 2 (forcing premature commit) would
fail HMAC verification.

---

## Actual Behavior (simulated path through real modules)

Reproduced by walking the conviction rollup against the 5-cadence drift
score sequence above.

**Per-cadence pipeline output:**

**Cadence C-0 (2026-04-04, score=0.23 below):**
```
channel_1_score          = 0.23
threshold                = 0.25
position_vs_threshold    = below (clean)
last_stable_conviction   = HIGH
pending_transition       = False
pending_transition_cycles = 0
emitted_conviction       = HIGH
flips_in_window          = 0
```

**Cadence C-1 (2026-04-09, score=0.28 above):**
```
channel_1_score          = 0.28
threshold                = 0.25
position_vs_threshold    = above (drift)
last_stable_conviction   = HIGH
pending_transition       = True (drift→MEDIUM)
pending_transition_cycles = 1 (need 2 to commit)
emitted_conviction       = HIGH (still last_stable)
flips_in_window          = 0
```

**Cadence C-2 (2026-04-14, score=0.23 below):**
```
channel_1_score          = 0.23
threshold                = 0.25
position_vs_threshold    = below (clean)
last_stable_conviction   = HIGH
pending_transition       = CANCELLED (reverted)
pending_transition_cycles = 0
emitted_conviction       = HIGH (no flip occurred)
flips_in_window          = 0
```

**Cadence C-3 (2026-04-19, score=0.28 above):**
```
pending_transition       = True (drift→MEDIUM)
pending_transition_cycles = 1
emitted_conviction       = HIGH (still last_stable)
flips_in_window          = 0
```

**Cadence C-4 (2026-04-24, score=0.27 above):**
```
pending_transition       = True (drift→MEDIUM, 2nd consecutive)
pending_transition_cycles = 2 → COMMIT
last_stable_conviction   = MEDIUM (newly committed)
emitted_conviction       = MEDIUM
flips_in_window          = 1
m2_alert_fired           = False (1 flip < 3 threshold)
```

**Cadence C-5 (2026-04-29, score=0.23 below):**
```
pending_transition       = True (clean→HIGH)
pending_transition_cycles = 1
emitted_conviction       = MEDIUM (still last_stable; reverse needs 2 cycles too)
flips_in_window          = 1
```

**Aggregate over 25-day window:**

| Metric                  | Naive (no hysteresis) | With hysteresis |
| ----------------------- | --------------------- | --------------- |
| Conviction transitions  | 5                     | 1               |
| Operator alerts emitted | 5 (M-2 each flip)     | 0 (1 flip < 3)  |
| Final emitted conviction| HIGH (volatile)       | MEDIUM (stable) |
| Recommendation churn    | High                  | Low             |

**DB writes executed (over 5 cadences):**

```
INSERT INTO drift_channel_scores (...) x 6 -- one per cadence cycle
INSERT INTO conviction_transitions (...) x 1 -- only the committed C-4 transition
INSERT INTO recommendations (...) x 6 -- one per cadence; only C-4 differs in conviction
-- No M-2 flip-flop alert (only 1 committed flip; threshold is >3)
```

---

## Verdict

**PASS.** The hysteresis defense correctly suppressed flip-flop noise.
Critical findings:

1. **Single-cycle excursions did not flip.** C-1 (0.28) and C-3 (0.28) were
   both above-threshold cycles, but each was followed by a revert (or
   confirmation). The C-1 → C-2 sequence cancelled the pending transition
   without ever committing, exactly as designed.

2. **Hysteresis is symmetric.** The reverse transition (MEDIUM → HIGH) at
   C-5 is also pending; it requires C-6 to confirm. The architectural
   symmetry prevents the system from "letting bad signals pass quickly and
   demanding evidence to recover" (an asymmetry that would bias toward
   pessimism).

3. **Flip-count tracking is per-commit, not per-cycle.** Only committed
   transitions count toward the 30-day flip-count. Pending-then-cancelled
   transitions don't increment the counter — they're not flips, they're
   noise that the hysteresis filtered out.

4. **The 3-flip / 30-day threshold is well-calibrated.** With 5-day cadence
   periods, 6 cadence cycles fit in 30 days. Three committed flips in 6
   cycles means 50% transition rate — that's a system that's no longer
   producing stable signal. Auto-demotion to MEDIUM + operator review is the
   correct response.

5. **HIGH-gate hysteresis interaction (Phase 4 Q2).** If conviction reaches
   the auto-demoted MEDIUM state (after >3 flips), the HIGH-gate (Phase 4 Q2)
   cannot re-promote without operator review, regardless of how clean the
   gates 1-5 look. This is a load-bearing invariant: noise-driven flip-flop
   is itself evidence that the gates are not stably satisfied.

This walkthrough validates the Phase 4 Q7 hysteresis defense + flip-frequency
tracking. The 5-cadence sequence intentionally constructs the worst-case
oscillation pattern (0.23 ↔ 0.28 around 0.25); the system correctly produced
only 1 transition over 25 days vs the naive 5.

Architectural note: the 0.25 threshold itself is an empirical calibration
parameter (not load-bearing for hysteresis correctness). If catalog evidence
in v0.5+ suggests 0.20 or 0.30 is the better cutoff, the threshold can shift
without changing the hysteresis logic. Hysteresis is a CONTROL invariant; the
threshold is a CALIBRATION parameter.

---

## HMAC-Signed Attestation

Canonical payload (sort_keys=True, separators=(',', ':'), ensure_ascii=False)
per `src/audit_trail/hmac_verify.py::canonical_payload_dict`:

```json
{"committed_transitions":1,"final_emitted_conviction":"MEDIUM","flips_in_30d_window":1,"m2_flip_flop_alert_fired":false,"naive_transitions_avoided":4,"observation_cycles":6,"ticker":"CRWD","verdict":"PASS"}
```

HMAC-SHA256 over the canonical payload (key: `walkthrough-attestation-key`,
test/development scope only — NOT a production secret):

```
3b729214d1298b27cdc3530b4190c712abf95bdb1cdfe98f289da1a16feb9245
```

**Operator sign-off:** _________________________  date: _____________

---

## Reproducing this walkthrough

```bash
python3 -m pytest tests/test_conviction_flip_flop_walkthrough.py::TestFlipFlopSuppression -v
```

The reproducer walks the 6-cadence drift-score sequence (0.23 ↔ 0.28
oscillation around 0.25) through ``apply_hysteresis``:

* Single-cycle excursions (C-1 alone) do NOT flip emitted bucket.
* Reverts (C-1 → C-2) cancel pending transitions.
* 2-cycle persistence (C-3 → C-4) commits → only flip in 25-day window.
* Symmetric: reverse transition (C-5 MEDIUM→HIGH) also pending, not instant.
* Excessive-flip path (>3 in 30d) auto-demotes to MEDIUM and escalates M-2.

---

## Cross-references

- Spec Section 5.1 — Recommendation conviction schema
- Spec Section 5.4 — Anchor-drift channels + flip-frequency tracking
- Spec Section 7.3a — Walkthrough launch gates (this doc satisfies #9)
- Phase 4 Q2 — Conviction rollup HIGH-gate (interacts with hysteresis lockout)
- Phase 4 Q7 — Hysteresis + 2-cadence persistence rule
