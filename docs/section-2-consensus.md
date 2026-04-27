# Section 2 Consensus — The Refined Funnel (Control Flow)

**Date:** 2026-04-26
**Session:** Q&A consensus review with operator (saehoon0501) — Section 2 of the consensus-documentation-protocol series
**Status:** Locked — 5 wiring items + 3 open-floor items
**Purpose:** Capture all wiring decisions for the funnel control flow that connects L1-L8 lanes into a working pipeline. Implementation can proceed from this document.

**Predecessor:** [Section 1 consensus](section-1-consensus.md) — locked the bet, architectural multipliers, mode model, 5-style debate, L7 + L8 lanes.

**Note on revision:** an initial draft of this document was committed (commit `3bbe15e`) reflecting system's recommendations as defaults under operator's "next" auto-acceptance. Operator returned to engage substantively; this revision reflects actual operator-system consensus including a critical clarification (watchlist ≠ portfolio) and the removal of S3 (tax bucket sidecar).

---

## 1. What this section locks

The funnel diagrammed in `.claude/references/empirical/00-overview.md` (sidecars + 9 phases + loop-backs) was structurally complete after Section 1, but **wiring details** (how sidecars feed phases, how events trigger phases, how loop-backs route, what's a research artifact vs a real-money artifact) were only diagrammed, not specified.

Section 2 specifies the wiring so that future consumer skills (regime-capture, name-discovery, swing-vs-invest, daily-refresh, etc.) can each instantiate one or more phases without re-deciding wiring at skill-build time.

---

## 2. Funnel architecture (post-Section 2 revision)

**4 always-on sidecars** (was 5; S3 tax bucket removed per open-floor #2):

| Sidecar | Source | What it provides |
|---|---|---|
| S0 | L1 (regime capture) | Current regime classification + shift probability (probability-distribution form per Section 3 Q3) |
| S1 | calibration history | Brier-trend per agent (rolling 90d) — applied as conviction haircut at v0.5+ |
| S2 | counterfactual ledger | Every PASS/exit/trim baseline-tracked, mode-tagged |
| S4 | L7 (smart-money monitor) | Insider-cluster / drawdown-period institutional accumulation / 13G filings — fires events |

(S3 tax bucket removed — operator does not need automated tax calculations in v0.1; `/wash-sale-harvest` skill remains for ad-hoc decisions.)

**9 phases (linear with explicit loop-backs):**

P1 trend capture → P2 scenario writing → P3 name discovery → P4 deep dive (5-style debate, Phase A→B→C-conditional→D) → P5 **watchlist** add → P6 disposition determination → P7 entry execution (real-money buy) → P8 daily refresh (the loop) → P9 exit.

**Critical clarification: watchlist (P5) ≠ portfolio (P7).** The watchlist is a research artifact — curated approved-to-buy names with conviction + recommended size bands + kill criteria. The portfolio is real-money positions. Different objects, different constraints. Operator uses the watchlist to *facilitate* allocation decisions; the operator chooses which names to actually buy and how much.

---

## 3. The 5 locked wiring items

### Item 1 — S0 (regime context) feeds phases via hybrid pull/push

**Pull pattern** (each phase fetches at invocation time):
- P1 trend capture: pulls regime classification at session start
- P3 name discovery: pulls era-fit context (which secular trends are tailwinded vs headwinded by current regime)
- P6 disposition determination: pulls vol regime classification (drives swing/long disposition rule)
- P4 deep dive (Macro/Regime style agent): pulls full L1 reference + current regime classification

Stale-acceptable threshold: regime read ≤5 trading days old. Beyond that, force refresh before invoking phase.

**Push pattern** (regime shifts trigger events):
- L1 detects a regime shift → S0 fires regime-shift event
- Subscribers: P8 (daily refresh) escalates affected positions to materiality-2; P1/P2 chain re-runs for sensitivity-tagged-HIGH positions; `/parameters-review` flagged as worth running

**Engineering analogy:** pull = config-fetch at request time; push = event-driven cache invalidation for high-impact state changes.

### Item 2 — Phase C (negotiation) trigger via LLM-as-judge with standardized criteria

**Trigger spec.** A separate neutral judge agent receives Phase B outputs from all 5 style agents. Each Phase B output is structured:

```
{
  style: "Value" | "Growth" | "Quality" | "Macro-Regime" | "Quant-Technical",
  load_bearing_claims: [
    { id: "C1", text: "...", supports_recommendation: "ADD"|"PASS"|"WATCH" },
    ...
  ],
  non_negotiables: [
    { id: "N1", text: "..." },
    ...
  ]
}
```

**Judge prompt** (standardized; runs every memo; deterministic rubric):

> You are inspecting 5 style agents' Phase B outputs to determine whether Phase C negotiation is needed.
>
> A "conflict" exists between style A and style B when:
> - **Type 1 (direct contradiction):** A's load-bearing claim asserts X is true; B's non-negotiable asserts X is false (or asserts Y where Y mutually excludes X).
> - **Type 2 (material magnitude disagreement):** A's load-bearing claim requires a variable to be in range R1; B's non-negotiable asserts the same variable is in range R2 where R1 and R2 are disjoint.
> - **Type 3 (mutually exclusive prerequisite):** A's load-bearing claim requires regime / condition X to hold; B's non-negotiable asserts the regime / condition is the opposite.
>
> Output format:
> ```
> conflicts: [
>   { style_a, claim_id, style_b, non_negotiable_id, type: "Type 1|2|3", explanation }, ...
> ]
> phase_c_needed: true | false
> ```

**Quality safeguards:**
- Judge's decisions are logged to Postgres (auditable).
- Per `/parameters-review` cadence (monthly read-only / annual change-authority): operator inspects sample of judge calls. If judge consistently triggers Phase C on non-conflicts (over-sensitive) or skips on real conflicts (under-sensitive), the prompt is recalibrated.
- The judge's prompt is a `parameters` table entry — versioned, recalibratable.

**Why LLM-as-judge over mechanical text-matching:** mechanical matching misses semantic conflict. "Growth will sustain" vs "Growth is decelerating" should trigger Phase C but won't textually match.

**Why not always-on Phase C:** non-trivial LLM cost for the (probably majority) no-conflict case; ceremony where there's nothing to negotiate.

### Item 3 — Regime-shift re-underwrite scope = sensitivity-tagged subset

**Mechanism:**
- At P5 (watchlist-add), each name is tagged with regime-sensitivity: HIGH / MEDIUM / LOW. Tag is set by the Macro/Regime style agent during Phase A based on:
  - Sector regime-sensitivity (banks/insurers/REITs HIGH; consumer staples LOW; industrial/energy MEDIUM)
  - Business-model regime-sensitivity (rate-duration sensitive HIGH; recurring-subscription LOW; cyclical-capital-equipment MEDIUM)
  - Thesis regime-dependence (thesis explicitly bets on regime → HIGH; thesis is regime-agnostic compounder → LOW)
- When S0 fires regime-shift event, only HIGH-sensitivity names auto-re-underwrite (P1/P2 chain re-runs). MEDIUM names get a flagged-for-quarterly-review note. LOW names ignored.

**Why sensitivity-tagged over mode-conditional:** mode (B/B'/C) is too coarse. An NVDA B'-mode name can be more rate-sensitive than a META B'-mode name. Sensitivity tag captures position-specific regime exposure that mode doesn't.

**Tag is mutable** — operator can override at quarterly review; Macro agent revisits tag on each per-name re-underwrite.

### Item 4 — S4 (smart-money) routing rules + 3-gate pipeline clarification

**Three event categories with routing rules:**

| Event category | Source signal | Ticker on watchlist? | Routes to |
|---|---|---|---|
| **Catastrophic / fraud-signature** | L3-d fraud signature triggered (3+/6 of: charismatic-CEO + board-lacking-domain-expertise + novel-accounting + secrecy + dismissed-bear-research + related-party-transactions) | Yes — held name | **P9 (exit consideration, fast-path)** |
| **Smart-money positive on candidate** | Insider cluster / LSV-accumulation / 13D-activist / 13G-new-5% on a name | No — not on watchlist | **P3 (candidate-discovery trigger)** |
| **Smart-money positive on watchlisted name** | Same signals on a name already on watchlist | Yes — on watchlist | **P4 (reunderwrite trigger; potential size-band re-spec)** |

**Critical clarification — the 3-gate pipeline:**

```
L7 event fires (e.g., insider cluster on a name not on watchlist)
        ↓
   P3 candidate-discovery  ← Gate 1: L3-d red flags? era-mismatch? Tier-A signal check?
        ↓ (if passes Gate 1)
   P4 deep dive (5-style debate)  ← Gate 2: PMSupervisor decision = ADD / WATCH / PASS
        ↓ (only if ADD)
   P5 watchlist add  ← Gate 3: research artifact added with conviction + size band + kill criteria
        ↓
   ON WATCHLIST (research approved)
```

L7 is a discovery signal, not an admission ticket. Most L7-fired candidates will be PASSed at P3 or P4. Only the small subset that survives all 3 gates lands on the watchlist.

**Why the catastrophic fast-path to P9:** fraud signatures are time-sensitive. Routing them to P4 reunderwrite (full 5-style debate cycle) is too slow. Fast-path to P9 means exit consideration immediately; PMSupervisor still has final call but operates on the catastrophic-event input directly.

### Item 5 — Mode-classification at phase-entry time (not at signal-detection)

**Rule:** L7 detects signals without classifying mode. L7 fires generic events with ticker + signal type + signal data. Downstream phase (P3 if not on watchlist; P4 if on watchlist) classifies mode at receive time using Section 1's classification rule (vol / cap / profitability / growth thresholds).

**Phase-specific mode-conditional logic:**

| Mode (assigned at phase-entry) | Smart-money signal type relevant | Phase action |
|---|---|---|
| B (steady) | Drawdown-period institutional accumulation (LSV 1994 ride-along) | Treat as confirmation; if not on watchlist → P3 candidate; if on watchlist → P4 size-up consideration |
| B' (compounder) | Same as B | Same as B |
| C (thematic) | 13G new-5% holder, mid-cap fund initiation, conference catalyst (wait-for-arrival) | Held name → P6 disposition / sizing-band change ("arrival is happening, size up") |
| Cross-mode | Insider cluster (Cohen-Malloy-Pomorski opportunistic) | New name → P3; held name → P4 |
| Cross-mode | Activist 13D from curated activist roster | New name → P3; held name → P4 |

**Why mode-classification at phase-entry, not at L7:** L7's job is signal detection (insider buys, 13F changes, etc.). Mode-classification is a downstream decision concern. Cleaner separation: L7 does signal detection; phases do decision logic. L7 can fire events without needing the classification rule loaded.

---

## 4. The 3 open-floor items locked

### Item 6 — 5% cap is portfolio-level, enforced at P7 only

**Critical clarification (operator-driven):** the 5% per-name cap applies to **portfolio** (real-money positions), NOT to **watchlist** (research artifact).

- **Watchlist (P5)** has NO cap. The watchlist is a research artifact — names that have passed P3 + P4 + are research-approved with conviction + recommended size bands + kill criteria. May contain 30, 50, even 100 names if research approves them. Size bands are guidance for the operator, not commitments.
- **Portfolio (P7)** has the 5% cap. When operator decides to actually buy shares, the entry execution downsizes if cumulative real-money exposure on the name would exceed 5% of portfolio value. Operator can override with explicit acknowledgment.
- **Price-appreciation exemption.** Positions that grow above 5% via price appreciation (not new buys) are NOT force-trimmed. Winners can compound past 5% naturally; only new buys above the cap are blocked.

**Why operator drives this:** the watchlist *facilitates* operator's allocation decision; it doesn't constrain it. Operator decides which approved names to buy and how much, subject to the 5% portfolio cap at execution time. The system's job is to produce a high-quality watchlist; the operator's job is to allocate against it.

### Item 7 — S3 (tax bucket sidecar) removed from v0.1

**Operator decision:** automated tax-aware exit logic is not needed in v0.1. Sidecars drop from 5 to 4 (S0 / S1 / S2 / S4).

**Implications:**
- P9 (exit) does NOT consider LT/ST tax cost in exit shape. Thesis-pillar-fail = exit immediately regardless of holding period.
- The existing `/wash-sale-harvest` skill remains available for ad-hoc operator-driven decisions; not auto-surfaced.
- Munger's 3.5%/yr tax math (per L6 Pattern #6) is now an operator-side concern, not system-side. Operator manually considers tax when deciding to harvest.

**Revisit trigger:** at v0.5+ scale-up if tax cost becomes a material drag, S3 can be added back.

### Item 8 — `/parameters-review` skill UI is interactive CLI in Claude Code

**Format:** invoke `/parameters-review` in Claude Code → conversation walks through each proposed parameter change one-by-one → for each, operator responds ACCEPT / MODIFY / REJECT inline → on session close, approved changes write to versioned `parameters` Postgres table with operator's annotations preserved.

**The conversation IS the interface.** No separate Markdown artifact needed; the conversation transcript serves as the audit trail.

**Cadence reminder** (from Section 1 Item 5):
- Drawdown / risk monitoring: real-time / event-driven (`/daily-monitor`)
- Ledger inspection: monthly (operator runs `/parameters-review` for read-only signal)
- Parameter recalibration: annually OR on-trigger (operator runs `/parameters-review` with change-authority)

Operator can override any cadence whenever.

---

## 5. Funnel diagram update reflecting Section 2 wiring

The funnel diagram in `.claude/references/empirical/00-overview.md` needs annotation reflecting these wiring decisions:

- **Sidecars: 4** (S0 / S1 / S2 / S4) — S3 removed
- **S0 sidecar** shows pull arrows to P1/P3/P6/P4-Macro-agent + push arrows to P8 + regime-shift event-fire to sensitivity-tagged-HIGH names
- **P4 internal:** Phase A → Phase B → conflict-detection-judge (LLM-as-judge with 3-Type rubric) → Phase C (conditional) → Phase D
- **S4 sidecar** shows three event-routing rules (catastrophic to P9; positive on candidate to P3; positive on watchlisted to P4)
- **P5 (watchlist add)** shows NO cap — research artifact only
- **P7 (entry execution)** shows 5% portfolio-cap enforcement gate + price-appreciation exemption
- **P9 (exit)** simplified — no tax-bucket consideration; thesis-pillar-fail = immediate exit

This is a documentation-only update; the wiring spec is locked here in Section 2.

---

## 6. What remains open for Section 3+

**Section 3** — L1 (regime capture) substantive review: which Tier A signals to operationalize into S0; how to handle post-QE regime-change uncertainty (Pattern #20 caveat); single classification vs probability distribution; regime-shift event-fire threshold.

**Sections 4-7** — L2 / L3 / L4 / L5+L6 substantive reviews.

**Section 8** — Coexistence with v2-final + what's still missing strategically.

---

## 7. Implementation handoff notes

For the engineer (or future-self) implementing skills that instantiate these phases:

- **Read Section 1 consensus first** — `docs/section-1-consensus.md`. It defines the modes, parameters, and architectural findings that the wiring here serves.
- **Each phase = potential consumer skill.** When building `/regime-capture`, instantiate P1 logic per this wiring. When building `/name-discovery`, instantiate P3 with S2 + S4 inputs and L3-e + L3-d gates.
- **Sidecars are services, not one-off reads.** S0 and S4 specifically need persistent state (Postgres) and event-firing capability (poll + diff approach is acceptable for v0.1; real event bus when scale demands).
- **The LLM-as-judge for Phase C trigger is a separate agent context.** Don't co-locate it with style agents; the judge needs to be unbiased.
- **Sensitivity-tagging in Item 3 is a Macro-agent output.** Skill invocations that don't include the Macro agent must default to MEDIUM and flag for next quarterly review.
- **Watchlist != portfolio.** Skills that operate on the watchlist (research) do not enforce portfolio-level caps. Skills that operate on actual buys (entry execution) do. Don't conflate.

---

**End of Section 2 consensus (revised after operator engagement).** Ready for Section 3 (L1 regime capture review).
