# Section 2 Consensus — The Refined Funnel (Control Flow)

**Date:** 2026-04-26
**Session:** Q&A consensus review with operator (saehoon0501) — Section 2 of the consensus-documentation-protocol series
**Status:** Locked — 5 items + 3 open-floor defaults
**Purpose:** Capture all wiring decisions for the funnel control flow that connects L1-L8 lanes into a working pipeline. Implementation can proceed from this document.

**Predecessor:** [Section 1 consensus](section-1-consensus.md) — locked the bet, architectural multipliers, mode model, 5-style debate, L7 + L8 lanes.

---

## 1. What this section locks

The funnel diagrammed in `.claude/references/empirical/00-overview.md` (5 sidecars + 9 phases + loop-backs) was structurally complete after Section 1, but **wiring details** (how sidecars feed phases, how events trigger phases, how loop-backs route) were only diagrammed, not specified.

Section 2 specifies the wiring so that future consumer skills (regime-capture, name-discovery, swing-vs-invest, daily-refresh, etc.) can each instantiate one or more phases without re-deciding wiring at skill-build time.

---

## 2. Funnel architecture (recap)

**5 always-on sidecars feeding all phases:**

| Sidecar | Source | What it provides |
|---|---|---|
| S0 | L1 (regime capture) | Current regime classification + shift probability |
| S1 | calibration history | Brier-trend per agent (rolling 90d) — applied as conviction haircut at v0.5+ |
| S2 | counterfactual ledger | Every PASS/exit/trim baseline-tracked, mode-tagged |
| S3 | tax bucket | Per-position cost basis + LT/ST + wash-sale window |
| S4 | L7 (smart-money monitor) | Insider-cluster / drawdown-period institutional accumulation / 13G filings — fires events |

**9 phases (linear with explicit loop-backs):**

P1 trend capture → P2 scenario writing → P3 name discovery → P4 deep dive (5-style debate, Phase A→B→C-conditional→D) → P5 watchlist add → P6 disposition determination → P7 entry execution → P8 daily refresh (the loop) → P9 exit.

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
- L1 detects a regime shift (e.g., yield curve inverts; credit spreads widen >100bp from low; dollar regime flips; vol regime classification changes) → S0 fires regime-shift event
- Subscribers: P8 (daily refresh) escalates affected positions to materiality-2; P1/P2 chain re-runs for sensitivity-tagged-high positions; `/parameters-review` flagged as worth running

**Engineering analogy:** pull = config-fetch at request time; push = event-driven cache invalidation for high-impact state changes.

### Item 2 — Phase C (negotiation) trigger via LLM-as-judge

**Mechanism:**
1. After Phase A (each style agent isolated research) and Phase B (each style locks load-bearing claims + non-negotiables), a separate neutral agent reads all Phase B outputs.
2. Neutral agent's task: identify whether any style's non-negotiable directly contradicts another style's load-bearing claim. Output: `conflict_detected: true | false` plus list of conflicting claim-pairs.
3. If `conflict_detected = true`: invoke Phase C, bounded to 3 rounds max. Phase C focuses negotiation on the specific conflicting claims, not the full memo.
4. If `conflict_detected = false`: skip Phase C, go straight to Phase D PMSupervisor synthesis.

**Why LLM-as-judge over mechanical text-matching:** mechanical matching misses semantic conflict. "Growth will sustain at 25%" vs "Growth is decelerating to 12%" should trigger Phase C but won't textually match. LLM judge handles semantic comparison.

**Why not always-on Phase C:** non-trivial LLM cost for the (probably majority) no-conflict case; ceremony where there's nothing to negotiate.

**Failure mode to monitor:** judge agent could itself become sycophantic (over-detecting conflict to seem useful, or under-detecting to please both sides). Mitigation: judge's output is auditable; periodic spot-check during /parameters-review whether judge's decisions correlate with downstream PMSupervisor synthesis quality.

### Item 3 — Regime-shift re-underwrite scope = sensitivity-tagged subset

**Mechanism:**
- At P5 (watchlist-add), each position is tagged with regime-sensitivity: HIGH / MEDIUM / LOW. Tag is set by the Macro/Regime style agent during Phase A based on:
  - Sector regime-sensitivity (banks/insurers/REITs HIGH; consumer staples LOW; industrial/energy MEDIUM)
  - Business-model regime-sensitivity (rate-duration sensitive HIGH; recurring-subscription LOW; cyclical-capital-equipment MEDIUM)
  - Thesis regime-dependence (thesis explicitly bets on regime → HIGH; thesis is regime-agnostic compounder → LOW)
- When S0 fires regime-shift event, only HIGH-sensitivity positions queue for P1/P2 chain re-run. MEDIUM positions get a flagged-for-quarterly-review note. LOW positions ignored (no action needed).

**Why sensitivity-tagged over mode-conditional:** mode (B/B'/C) is too coarse. An NVDA B'-mode position can be more rate-sensitive than a META B'-mode position. Sensitivity tag captures position-specific regime exposure that mode doesn't.

**Tag is mutable** — operator can override at quarterly review; Macro agent revisits tag on each per-position re-underwrite.

### Item 4 — S4 (smart-money) routing rules

**Three event categories with routing rules:**

| Event category | Source signal | Ticker on watchlist? | Routes to |
|---|---|---|---|
| **Catastrophic / fraud-signature** | L3-d fraud signature triggered (3+/6 of: charismatic-CEO + board-lacking-domain-expertise + novel-accounting + secrecy + dismissed-bear-research + related-party-transactions) | Yes — held name | **P9 (exit consideration, fast-path)** |
| **Smart-money positive on candidate** | Insider cluster / LSV-accumulation / 13D-activist / 13G-new-5% on a name | No — not on watchlist | **P3 (candidate addition, name-discovery trigger)** |
| **Smart-money positive on held name** | Same signals on a name already on watchlist | Yes — held name | **P4 (reunderwrite trigger; potential size-up via PMSupervisor)** |

**Why the catastrophic fast-path:** fraud signatures are time-sensitive. Routing them to P4 reunderwrite (which takes a full 5-style debate cycle) is too slow. Fast-path to P9 means exit consideration immediately; PMSupervisor still has final call but operates on the catastrophic-event input directly.

### Item 5 — Mode-conditional smart-money routing

**Rule:** L7 classifies the name's mode at detection time (using the Item 1 classification rule from Section 1). Routing then varies per mode:

| Mode | Smart-money signal type that fires | Routing |
|---|---|---|
| B (steady) | Drawdown-period institutional accumulation (LSV 1994 ride-along) — 2+ Tier-1 institutions added during drawdown/flat with reasonable valuation | New name → P3; held name → P4 (size-up consideration) |
| B' (compounder) | Same as B | Same as B |
| C (thematic) | 13G new-5% holder, mid-cap fund initiation, conference catalyst (wait-for-arrival) | Held name → P6 (disposition / sizing change — "arrival is happening, size up") |
| Cross-mode | Insider cluster (Cohen-Malloy-Pomorski opportunistic) | New name → P3; held name → P4 |
| Cross-mode | Activist 13D from curated activist roster | New name → P3; held name → P4 |

**Why mode-classification at signal time vs downstream:** L7 already needs mode context to know whether the LSV-accumulation signal applies (only B/B' modes need it; C-mode wouldn't have institutional accumulation in 13Fs). Doing mode-classification once at L7 is cheaper than doing it twice (L7 detection + downstream phase entry).

**Mode-classification on candidates not yet on watchlist:** L7 runs the rule with limited input (market cap, vol, profitability profile from public data). Tagged as "proposed mode" — locked at watchlist-add (P5) when full memo data is available; AI may revise if proposed mode doesn't match memo evidence.

---

## 4. The 3 open-floor defaults locked

### Default A — Aggregate-per-name 5% cap enforcement

**Mechanism:** the 5% per-name cap (Section 1 Item 2) is enforced at two points:
- **At P5 (watchlist-add):** if proposed thesis size band would put cumulative exposure on the name above 5% (across all theses for that name — with single-mode-per-name there's only one thesis, but defensive enforcement), block ADD. Operator must reduce sizing or override with explicit acknowledgment.
- **At P7 (entry execution):** if current realized position size + proposed entry size would exceed 5%, downsize the entry to fit the cap. Operator can override.

**Catastrophic-loss exemption:** if a position's market value exceeded 5% due to price appreciation (not new buys), don't force trim — just block additions. Letting winners run is fine; the cap protects against concentrated entry, not against compounding.

### Default B — S3 (tax bucket) timing

**Read patterns:**
- **At P9 (exit):** S3 read provides tax-cost calculation that informs exit shape. WAIT_FOR_LT_THRESHOLD recommendation only fires when (a) thesis-pillar-fail flag is NOT set, (b) position is <12 months old, (c) waiting to LT threshold doesn't risk material additional drawdown.
- **At quarterly review (`/quarterly-reunderwrite`):** S3 read surfaces tax-loss-harvest opportunities — positions with realized losses ≥ TBD threshold (operator to set; suggested $3k/position absolute or 10% of cost basis) flagged as harvest candidates. Operator decides per-position; wash-sale rule mechanics handled per `wash-sale-paths.md`.

**Write patterns:** S3 updated on every entry (cost basis recorded) and on every exit (realized gain/loss + tax-bucket impact).

### Default C — `/parameters-review` skill UI

**Output format:** structured Markdown artifact at `docs/parameters-reviews/YYYY-Q-N.md` with sections:

```markdown
# Parameters Review — [period]

## Ledger inspection summary
- Names PASSed: N (top 5 by counterfactual outperformance vs baseline: ...)
- Held positions vs benchmark: B-book +X% / B'-book +Y% / C-book +Z%
- Mode-classification accuracy: [B-named-but-acted-C: N; etc.]
- Drawdown alerts (if any)

## Proposed parameter changes
1. **[parameter name]** old: X → proposed new: Y
   Rationale: [cited ledger evidence]
   Operator decision: [ACCEPT | MODIFY (specify) | REJECT]

2. **[parameter name]** ...

## Recommended actions
- [Operator-side actions surfaced — e.g., "consider tax-loss-harvesting NVDA at -12% basis"]
```

**Operator workflow:** read the artifact → mark each proposed change ACCEPT / MODIFY / REJECT in the doc → invoke `/parameters-review --commit` → approved changes write to versioned `parameters` Postgres table with the operator's annotations preserved.

**Cadence reminder:** monthly read-only inspection (no parameter changes); annual full review with change-authority. Operator can override cadence whenever.

---

## 5. Funnel diagram update reflecting Section 2 wiring

The funnel diagram in `.claude/references/empirical/00-overview.md` now needs annotation reflecting these wiring decisions. Specifically:

- S0 sidecar shows pull arrows to P1/P3/P6/P4-Macro-agent + push arrows to P8 + regime-shift event-fire to sensitivity-tagged-high positions
- P4 internal: Phase A → Phase B → conflict-detection-judge → Phase C (conditional) → Phase D
- S4 sidecar shows three event-routing rules (catastrophic to P9; positive on candidate to P3; positive on held to P4 — except mode-C wait-for-arrival routes to P6)
- P5 + P7 show 5%-cap enforcement gates
- P9 + quarterly review show S3 tax-bucket reads

This is a documentation-only update; the wiring spec is locked here in Section 2.

---

## 6. What remains open for Section 3+

**Section 3** — L1 (regime capture) substantive review: whether the 53 sources / 41 patterns / lead-lag table actually captures the regime signals operator needs; whether the Goyal-Welch-Zafirov OOS audit is the right meta-evidence; whether copper-gold post-2020 break is correctly demoted; etc.

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

---

**End of Section 2 consensus.** Ready for Section 3 (L1 regime capture review).
