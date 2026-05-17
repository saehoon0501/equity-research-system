# Parameter Review Queue

Append-only log of rubric / parameter tensions surfaced during live runs that require operator + system discussion before formal `/parameters-review` proposal generation.

Entries describe the situation and stakes — they do **not** prescribe a fix. Resolution path: surface in next `/parameters-review` cycle, discuss via `/grill-me` if substantive design tension, then propose a versioned change via the `parameters` table with `change_rationale` populated.

---

## Item PRQ-001 — Tier-classification rubric: "Public ≥10 years" gate

**Date surfaced:** 2026-05-17
**Surfaced during:** `/research-company PLTR` run, Phase 2a tier classification (run_id `A7CF1601-7B3D-49FF-944A-E8D0D099CD5E`)
**Affected artifact:** `.claude/commands/research-company.md` §2 step 1 — tier classification rubric

### Situation

The `core_fundamental` tier requires three concurrent gates:

1. trailing 12mo revenue > $1B
2. AND positive op income in ≥4 of last 8 quarters
3. AND **public for ≥10 years**

Gates 1 and 2 measure business fundamentals directly. Gate 3 measures *vintage as a listed security* — a tenure proxy. The skill cites "examples: AAPL, MSFT, JPM, KO, JNJ" — all listed pre-2000.

Default-conservative-on-ambiguity resolution means a name failing **only** gate 3 falls to `thematic_growth`, which carries:
- tighter sleeve cap (≤25% vs ≤80%)
- different sizing aggressiveness
- different framework-applicability defaults (no point targets, etc.)

### Why this needs further review and discussion

**1. The gate conflates two distinct properties.** Tenure as a public security and through-cycle business durability are correlated but not identical. The conceptual target of `core_fundamental` (capital permanence, stable cash flows, mature disclosure regime, predictable framework applicability) is fundamental quality. The gate as written measures listing age. A company can be a $90B+ mkt cap, multi-year FCF-positive, dominant-moat business but still fail gate 3 because it IPO'd in 2020. Conversely, a 1995 IPO that has degraded into a melting-ice-cube passes the tenure gate purely on survivorship.

**2. The 10-year cliff is theoretically ungrounded.** There is no documented derivation in the spec for why the threshold is 10 years rather than 5, 7, or 12. If the underlying intent is "the company has been through a full business cycle under public-disclosure discipline," then a 2018 IPO (cleared COVID + rate-hike cycle) and a 2014 IPO satisfy that condition equally well — yet only the 2014 passes.

**3. Concrete misclassification candidates under current rule.** Without prejudicing the outcome of any of these — a non-exhaustive list of names where gate 3 is the *binding* constraint that pushes the classification to `thematic_growth`:
   - PLTR (IPO Sept 2020) — this run; gates 1 + 2 cleared (revenue $6.5B+ annualized, 6 consecutive positive QTD op income)
   - CRWD (IPO June 2019)
   - SNOW (IPO Sept 2020)
   - DDOG (IPO Sept 2019)
   - ZS (IPO March 2018)
   - NET (IPO Sept 2019)

   For each of these the tenure gate may or may not be the decisive variable — the point is that gate 3 alone can flip the tier even when gates 1 and 2 both clear comfortably and the company is plausibly through-cycle durable.

**4. Calibration implications.** Tier classification is a hard branch — it shapes sleeve cap allocation, framework applicability, and conviction-rollup precedence downstream. A misclassified tier propagates as silent error into every recommendation involving the affected name. Calibration history then attributes the error to the analyst rather than the rubric, masking the source.

**5. The discipline argument for keeping the gate intact.** Hard rules prevent rationalization. Once tenure becomes negotiable, every plausible "story" company gets promoted up a tier and the conservative-on-ambiguity default collapses. The gate as written does some useful work — it imposes a discipline on the system that softer formulations would lose. So the question is not whether the gate has any value but whether its current form is the right form.

### What is NOT being prescribed here

This entry deliberately does not propose:
- a replacement threshold value
- a replacement criterion (margin-stability, mkt-cap floor, etc.)
- a soft-rule formulation
- a per-sector carve-out

Those are resolution choices that require operator + system deliberation in `/parameters-review` or `/grill-me`. The entry's purpose is to document the tension so it does not get lost between runs.

### For this run

PLTR classification was finalized as `thematic_growth` regardless. The tier is robust to gate-3 relaxation — PLTR also fails the *spirit* of `core_fundamental` on op-income volatility through 2023, FCF-margin variability, and valuation-regime risk. The rubric defect does not change the answer for this specific name. The entry is logged so the rubric question does not get re-litigated next time the gate binds on a different name.
