# Empirical Domain Library — Design Spec

**Date:** 2026-04-26
**Status:** Implemented + extended via Section 1 + Section 2 consensus
**Operator:** saehoon0501
**Project:** equity-research-system

**Revision history:**
- 2026-04-26 v1: original 6-lane design (L1-L6) — implemented and committed.
- 2026-04-26 v2: extended via consensus-documentation-protocol Q&A sessions:
  - Section 1 consensus (`docs/section-1-consensus.md`, commit `8f10922`) — added L7 (smart-money) + L8 (multi-style debate); locked three-mode model (B/B'/C); 5-style debate replaces bull/bear; mode-aware discipline.
  - Section 2 consensus (`docs/section-2-consensus.md`, commit `e3edf0e`) — funnel control flow wiring locked; watchlist ≠ portfolio clarified; sidecars reduced to 4 (S3 removed); LLM-as-judge for Phase C trigger; 3-gate pipeline (L7 → P3 → P4 → P5).

---

## 1. Goal

Produce the project's **ground-zero empirical-domain knowledge library** — curated, source-cited, distilled — organized so that future skills (regime-capture, scenario-writing, name-discovery, swing-vs-invest disposition, etc.) can be built on top of it without re-doing the underlying research.

The library captures *what historically worked vs what feels like it should work* across:
- Cross-asset signal composition (rates / credit / FX / commodities / equity vol)
- Multi-year scenario writing (3 / 5 / 10 year horizons)
- Successful-company patterns (multi-bagger case studies across eras and sectors)
- View-refresh discipline (anchor-drift defense, trigger-based re-eval)
- Technical execution (entry/exit playbooks that survive scrutiny)
- Multi-horizon disposition (swing trade vs long-term investment vs both)

## 2. Non-goals (explicit)

- **No consumer skills built here.** This deliverable is reference material only. Downstream skills (e.g., a regime-capture skill, a name-discovery skill, a swing-vs-invest skill) come later — each its own brainstorming → spec → plan cycle.
- **Don't resolve the v2-final tension.** The library serves the new framework operator described (top-down macro/regime → thematic scenario → name discovery → technical execution + multi-horizon disposition). How it eventually integrates with the existing v2-final bottom-up watchlist contract is a separate architectural decision deferred until consumer skills are designed.
- **Not part of the v0.1 build clock.** This is parallel research, doesn't gate any `BUILD_LOG.md` step. It does not require Tier 1/2/3/4 readiness.
- **Not subject to Evidence Index / contamination defense.** The empirical library is *project knowledge* (loaded into future skills' contexts as reference material), not date-anchored claims about specific tickers. The contamination defense applies to memos that cite filings; references are cited *by* memos, not subject to the same machinery.

## 3. Operator's investment funnel (the framework being supported)

### 3.1 Original stated workflow

The library was initially shaped to support this funnel, captured from operator's stated workflow:

```
news / indexes / futures
        ↓
capture a trend (regime read)
        ↓
write a scenario for the coming 3 / 5 / 10 years
        ↓
research stocks likely to be the next "Palantir case"
        ↓
put them on the watchlist
        ↓
technical analysis for entry and exit (maximize profit, trade with principles)
        ↓
repeat daily for updates — balance "shift the view when warranted"
                            against "stay disciplined to the thesis"
        ↓
per held name: decide swing trade vs long-term investment vs both
```

This is a discretionary thematic / global-macro / event-driven style funnel (Druckenmiller / Loeb / Tepper / Coleman archetype), distinct from the bottom-up quality-compounder paradigm in `docs/v2-final-spec.md`.

### 3.2 Refined funnel after Section 1 + Section 2 consensus

The linear arrow above is the **intent**. The refined operational model below grounds each step in empirical findings, specifies inputs/outputs/gates, and adds the structural elements the lanes' patterns demand:

- **4 always-on sidecars** (S0/S1/S2/S4 — was 5; S3 tax bucket removed in Section 2)
- **9 phases** with explicit loop-backs and a 3-gate decision pipeline
- **Watchlist ≠ portfolio** — watchlist is research artifact (no cap); portfolio is real-money positions (5% cap at P7)
- **5-style debate** replaces classical bull/bear in P4 (Phase A→B→C-conditional→D)
- **Mode-aware discipline** per B/B'/C name classification

See §16 for the funnel and pipeline diagrams.

## 4. Architecture

### 4.1 Library production architecture

```
v1 — Initial 6 lanes (L1–L6):
  6 parallel general-purpose subagents
                    │
       Each writes its lane file(s) under
       .claude/references/empirical/
                    │
       Main context synthesizes
       .claude/references/empirical/00-overview.md
       as the entry point

v2 — Extension via Section 1 + 2 consensus:
  + 6 parallel deepening subagents (L1-L6 second-pass research)
  + L7 dispatched (smart-money tracking)
  + L8 dispatched (multi-style debate research)
  + 00-overview.md updated with funnel, sidecars, cross-lane
    synthesis S1-S9, dependency map, builder's guide
```

- No code. Markdown only.
- Subagents have `WebSearch` + `WebFetch`.
- L3 (successful-company patterns) is the largest lane — splits internally into a sub-folder.
- **8 lanes total** post-consensus: L1-L8.

## 5. Lane definitions

8 lanes total (6 original + 2 added via Section 1 consensus):

| Lane | Empirical question | Funnel phase served |
|---|---|---|
| **L1. Regime capture from cross-asset signals** | What in rates / credit / FX / commodities / vol reliably identifies regime? Lead-lag relationships. Signal vs noise. | S0 sidecar; consumed at P1 / P3 (era-fit) / P6 (vol regime) / P4 Macro-Regime style agent |
| **L2. Probabilistic scenario writing (3/5/10y)** | How practitioners write falsifiable multi-year scenarios. Common forecasting failures. How to update without anchoring. | P2; supports L8 Macro-Regime style agent |
| **L3. Successful-company pattern library** | Case studies of major multi-baggers across eras / sectors / tech regimes. Per case: business-model evolution, growth-rate trajectory + duration, historical/macro background enabling success, capital allocation, founder/management archetype. Cross-era pattern extraction. **Includes counterfactuals (32 named after deepening) for survivorship-bias defense.** | P3 (gate 1: L3-d red flags + L3-e Tier-A signals); P4 Quality / Growth style agents |
| **L4. View-refresh discipline** | Anchor-drift defenses. Trigger-based re-evaluation. Pre-mortem cadence. When to capitulate vs persist on a thesis. | P8 daily refresh logic |
| **L5. Technical execution playbooks** | Empirically validated technical patterns only — trend, volume / breadth, vol regime, ATR-stops. Failure modes. What TA folklore to discard. | P7 entry execution; P9 exit signaling |
| **L6. Multi-horizon disposition (swing / invest / both)** | Decision rules per name × per timeframe. How PMs scale in/out. Position lifecycle. What changes a disposition. | P6 disposition determination |
| **L7. Smart-money / institutional flow tracking** *(added v2)* | Which institutional-positioning signals empirically deliver alpha vs are folklore. Mode-mapped (insider clusters cross-mode; LSV-style accumulation B/B' ride-along; 13G C wait-for-arrival). | S4 sidecar; fires events into P3 (new candidate) or P4 (held name reunderwrite); catastrophic fast-path to P9 |
| **L8. Multi-style debate as decision architecture** *(added v2)* | Empirical foundation for the 5-style debate (Value / Growth / Quality-Moat / Macro-Regime / Quant-Technical). Refined mode-weighting matrix anchored on Fama-French RMW dominance, AQR Style Premia, Asness "Sin a Little" equal-weight prior, multi-agent debate AI literature on persona-diversity and sycophancy-mitigation. | P4 internal architecture (Phase A→B→C-conditional→D) |

## 6. Per-lane output schema

Every lane file contains the following sections in order:

### Section A — Curated sources

15–30 entries. Format per entry:

```
- [title](url) — 1-line annotation [Tier N]
```

Tier definitions:
- **Tier 1** — academic papers + practitioners with verifiable track record (named PMs, fund letters from established funds, peer-reviewed research, books by practitioners with public records)
- **Tier 2** — established financial press, respected practitioner blogs, hedge-fund letters from non-marquee funds
- **Tier 3** — other (used only if it covers ground Tier 1/2 doesn't)

No exclusions — but tier label required on every entry.

**Diversity requirement:** mix of academic + practitioner + case studies. No single author or site cited more than ~3 times.

### Section B — Distilled patterns

10–20 bullets. What the literature *empirically establishes*. Each bullet cites the source(s) it rests on (via Section A entries). Patterns must be specific and actionable, not generic wisdom.

❌ "Markets are cyclical."
✅ "Credit spreads widen 3–9 months before equity drawdowns ≥20% in 7 of last 10 cycles (sources: [3], [11])."

### Section C — Open questions / disagreements

Where credible sources disagree, stated explicitly. Future skill-builders need to know where uncertainty lives so they don't construct skills that pretend consensus exists where it doesn't.

### Section D — Lane-specific extras (optional)

E.g., L3 will include a cross-era pattern table; L1 will include a lead-lag relationship table; L5 will include a "patterns that survived vs folklore that didn't" table.

## 7. File layout

```
.claude/references/empirical/
  00-overview.md                          # entry point — TOC, refined funnel, sidecars,
                                          #              cross-lane synthesis S1-S9,
                                          #              dependency map, builder's guide
  L1-regime-capture.md                    # 53 sources / 41 patterns / 38-row lead-lag table
  L2-scenario-writing.md                  # 58 sources / 33 patterns / 6 D-tables
  L3-successful-companies/                # split internally — largest lane
    00-overview.md                        # local index
    a-tech-platforms.md                   # MSFT / AAPL / AMZN / GOOGL / META / NVDA / PLTR / etc.
    b-consumer.md                         # KO / NKE / COST / LULU / etc.
    c-financials-healthcare.md            # V / MA / UNH / DHR / BRK / CSU / etc.
    d-cyclicals-and-misses.md             # cyclicals + 32 survivorship counterfactuals
                                          # (incl. SPAC-era, meme-era, crypto-era post-deepening)
    e-cross-era-patterns.md               # 28 cross-era patterns HIGH/MEDIUM/CONTESTED
  L4-refresh-discipline.md                # 60 sources / 28 patterns / 9-row PM case-study table
  L5-technical-playbooks.md               # 55 sources / 40 patterns (26 do-survive / 14 don't)
  L6-horizon-disposition.md               # 86 sources / 45 patterns / 22+16 row decision tables
  L7-smart-money.md                       # (added v2) — 29 sources; signal classification
                                          #              with mode-relevance tagging
  L8-multi-style-debate.md                # (added v2) — 29 sources; refined 5-style taxonomy
                                          #              + mode-weighting matrix
```

Total scale: ~530+ sources / 8 lanes / 250+ patterns / 75+ disagreements / 20+ structured D-tables.

The L3 sub-split is a soft suggestion — the L3 subagent adjusted the cut during execution. L7 and L8 are single-file lanes per Section 1 consensus.

Related strategic docs (committed alongside library):
- `docs/big-finance-comparison.md` — phase-by-phase comparison vs big-firm tooling
- `docs/section-1-consensus.md` — 9 locked items + 3 architectural findings + design changes from v2-final
- `docs/section-2-consensus.md` — funnel control flow wiring (5 wiring items + 3 open-floor items)

## 8. The `00-overview.md` (entry point)

Written by the main context **after** all 6 lane subagents complete. Contains:

1. **TOC** — links to all lane files with 1-paragraph summary per lane
2. **Cross-lane synthesis** — patterns that recur across multiple lanes (e.g., if L1 + L3 + L5 all converge on "regime change is the highest-leverage signal," surface it)
3. **Dependency map** — which lanes a future skill would load to answer which question (e.g., "swing-vs-invest disposition skill should load L3 + L5 + L6")
4. **Builder's guide** — short notes on how to consume this library when building a downstream skill (don't dump all of it into context; load lanes selectively per skill scope; cite tier-1 patterns when justifying a skill's logic)

## 9. Subagent prompt template

Each of the 6 general-purpose subagents receives:

- **Lane scope** — one paragraph from §5
- **Output schema** — A / B / C / D contract from §6
- **Credibility tier definitions** — from §6
- **Source diversity requirement** — from §6
- **Deliverable file path** — exact path under `.claude/references/empirical/`
- **Time / budget guidance** — thoroughness over speed; ~30–90 min equivalent of focused research; multiple WebSearch / WebFetch rounds expected
- **Anti-hallucination instruction** — fetch every URL cited (don't cite a URL you haven't actually retrieved); if a source can't be fetched, drop it

L3 receives an additional instruction: pre-split deliverable into the sub-folder structure in §7, but free to adjust the cut if it finds a better organization.

## 10. Cost & timing estimate

- 6 parallel subagents (L3 likely runs longer than others due to scope)
- Wall-clock: ~10–25 min for all to complete (parallel)
- LLM cost rough estimate: ~$25–60 total
- Synthesis pass (`00-overview.md`): ~$2–5 in main context

## 11. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Subagent fabricates a citation that doesn't exist | Schema requires fetched URLs; spot-check 2–3 links per lane post-hoc |
| Source monoculture (all from same blog network) | Diversity requirement in prompt; cap single author/site at ~3 entries |
| L3 too broad to fit one subagent context | Pre-split into sub-files; subagent free to adjust |
| Generic "investing wisdom" instead of empirical content | Section B requires source citation per bullet; Section C forces explicit acknowledgement of disagreement |
| Subagents drift toward SEO-optimized / shallow sources | Tier-3 allowed but flagged; instructions emphasize practitioners-with-track-record as Tier 1 |
| Lane outputs disagree about same fact (e.g., L1 cites X, L5 contradicts) | Surface disagreements in `00-overview.md` cross-lane synthesis rather than hide them |

## 12. Acceptance criteria

The library is "done" when:

- [ ] All 6 lane files (or sub-files for L3) exist under `.claude/references/empirical/`
- [ ] Each lane file has Sections A, B, C present and non-empty
- [ ] Each Section A entry has a Tier label
- [ ] Each Section B bullet cites at least one Section A entry
- [ ] No single author/site appears more than 3 times in any lane's Section A
- [ ] Spot-check of 2–3 random URLs per lane confirms they fetch and match the annotation
- [ ] `00-overview.md` exists with TOC, cross-lane synthesis, dependency map, builder's guide
- [ ] All files committed to git in a single coherent commit

## 13. Out of scope (will be follow-up projects)

After this library exists, future projects will (each through their own brainstorming → spec → plan cycle):

- Decide how the library integrates with the existing `v2-final-spec.md` paradigm — *partially addressed in Section 1 consensus; full integration remains a follow-up.*
- Build consumer skills (regime-capture, scenario-writing, name-discovery, swing-vs-invest disposition)
- Decide whether the library replaces, augments, or sits beside the current `/research-company` flow
- Maintenance cadence (when to refresh lanes; how to add new sources) — *partially addressed via `/parameters-review` skill in Section 2 consensus.*

---

## 14. Section 1 consensus summary (v2 extension)

Full document: `docs/section-1-consensus.md` (commit `8f10922`).

**9 locked items:**

1. **Three-mode model (B / B' / C)** with hybrid AI classification rule (vol / cap / profitability / growth thresholds); operator override allowed.
   - B (steady compounder): KO / COST / V / MA / BRK / MCO archetype
   - B' (growth compounder): NVDA / AMD / GOOGL / MSFT / META archetype
   - C (thematic / aspirational): RKLB / IONQ / PLTR-pre-2024 / COIN archetype
2. **Single-mode-per-name** with AI classification at watchlist-add (Section 2 confirmed: at phase-entry time, not signal-detection).
3. **Counterfactual ledger mode-tagged** at decision time, immutable; outcomes scored against mode-matching baselines so mode-classification accuracy is itself measurable.
4. **Calibration deferred to v0.5+** — Brier scores collected from day 1; haircut applied after ~50+ resolved predictions.
5. **`/parameters-review` skill** operationalizes cadence (system proposes, operator approves, parameters versioned in Postgres). Cadences: drawdown real-time, ledger inspection monthly, parameter recalibration annually; operator overrides whenever.
6. **Mode-specific discipline** with relative-to-benchmark drawdown auto-tighten triggers (B vs S&P 5pp; B' vs QQQ 7pp; C vs IWO/ARKK 10pp; absolute catastrophic halts at -25% B / -35% B' / -50% C).
7. **5-agent debate replaces bull/bear** (Value / Growth / Quality-Moat / Macro-Regime / Quant-Technical). Phase A isolated → Phase B locked claims + non-negotiables → Phase C conditional negotiation → Phase D PMSupervisor synthesis preserving dissent → Evaluator hard-gate as non-debating anchor outside the debate.
8. **L7 smart-money signals** with mode mapping: insider-cluster (cross-mode), drawdown-period institutional accumulation (B/B' ride-along), 13G new-5%-holder (C wait-for-arrival). Folklore signals (rally-period 13F replication, CNBC options-flow, unfiltered whale-watching) explicitly discarded.
9. **Refined L8 mode-weighting matrix** anchored on Fama-French 2015 RMW dominance + Asness "Sin a Little" equal-weight prior + S&P-DJI/Research-Affiliates evidence. Sector overrides for biotech and financials. Believability-weighting Issue Log as v0.5+ feature.

**3 critical architectural findings:**

| # | Finding | Source | Implementation requirement |
|---|---|---|---|
| 1 | **PMSupervisor MUST NOT force consensus** | "Talk Isn't Always Cheap" ICML 2025 + "Peacemaker or Troublemaker" 2025 | Phase D output preserves dissenting view per agent ("Macro voted PASS for these reasons; I'm overriding with these stated reasons"); never reports synthesized consensus |
| 2 | **Persona drift is a real failure mode** | ChatEval ICLR 2024; Liang et al. "Degeneration-of-Thought" | Each style agent has persistent locked identity (system prompt invariant); load-bearing claims and non-negotiables locked in Phase B before Phase C begins; Phase C cannot modify Phase B locks |
| 3 | **Evaluator stays OUTSIDE the debate as non-debating hard-gate anchor** | MAD failure mode literature | Existing Evaluator subagent retains hard-gate role per `.claude/agents/evaluator.md`; not a participant in Phase A-D debate; rejection authority is final regardless of PMSupervisor synthesis |

---

## 15. Section 2 consensus summary (v2 extension)

Full document: `docs/section-2-consensus.md` (commit `e3edf0e`).

**5 wiring items locked:**

1. **S0 (regime context) feeds phases via hybrid pull/push** — pull for routine reads (P1 / P3 / P6 / P4 Macro-agent); push for regime-shift events forcing P1/P2 chain re-run on sensitivity-tagged-HIGH positions.
2. **Phase C trigger via LLM-as-judge with 3-Type rubric** — separate neutral agent reads Phase B locked claims; outputs `phase_c_needed` based on Type 1 (direct contradiction), Type 2 (material magnitude disagreement), Type 3 (mutually exclusive prerequisite). Decisions auditable; recalibratable via `/parameters-review`.
3. **Regime-shift re-underwrite scope = sensitivity-tagged subset** — each name carries HIGH / MEDIUM / LOW regime-sensitivity tag set by Macro-Regime style agent at watchlist-add. Only HIGH triggers auto-re-underwrite on shift.
4. **S4 (smart-money) routing rules** — catastrophic fraud-signature events fast-path to P9 (exit consideration); positive signals on candidate to P3 (discovery); positive signals on watchlisted to P4 (reunderwrite). **3-gate pipeline** clarified: L7 event → P3 (Gate 1: red-flag check) → P4 (Gate 2: 5-style debate decision) → P5 (Gate 3: watchlist add). Most L7-fired candidates PASS at P3 or P4.
5. **Mode-classification at phase-entry time** (not signal-detection) — L7 detects signals without mode context; downstream phases classify mode at receive time. Cleaner separation: L7 = signal detection; phases = decision logic.

**3 open-floor items locked:**

6. **5% per-name cap is portfolio-level, enforced at P7 only** — watchlist (P5) is a research artifact with NO cap; portfolio (P7) has the 5% cap on real-money positions; price-appreciation winners can compound past 5% naturally (no force-trim).
7. **S3 (tax bucket sidecar) REMOVED from v0.1** — sidecars drop from 5 to 4 (S0 / S1 / S2 / S4). P9 exit doesn't consider LT/ST in v0.1; `/wash-sale-harvest` skill remains for ad-hoc operator use. Revisit at v0.5+ if tax cost becomes material drag.
8. **`/parameters-review` UI = interactive CLI in Claude Code** — conversation IS the interface; no separate Markdown artifact; conversation transcript serves as audit trail.

**Critical clarification — watchlist ≠ portfolio:**

| Object | What it is | Constraint |
|---|---|---|
| Watchlist (P5 output) | Research artifact: curated approved-to-buy names with conviction + recommended size bands + kill criteria | No 5% cap. Operator uses to *facilitate* allocation decisions. |
| Portfolio (P7 output) | Real-money positions: cost basis, current value, realized exposure | 5% cap at P7 entry execution. Operator chooses which names to actually buy. |

---

## 16. Diagrams — Refined funnel + 3-gate pipeline

### 16.1 Refined funnel (sidecars + 9 phases + loop-backs)

```
┌─────────────────── 4 ALWAYS-ON SIDECARS ─────────────────────┐
│                                                                │
│   S0  Regime context        ←  L1                              │
│       (probability distribution over regime states;            │
│        ≤5-trading-day staleness; pulled by P1/P3/P6/P4-Macro;  │
│        push event on regime-shift confluence)                  │
│                                                                │
│   S1  Calibration history   ←  Brier per agent (rolling 90d)   │
│       (collect from day 1; apply haircut at v0.5+)             │
│                                                                │
│   S2  Counterfactual ledger ←  every PASS / exit / trim,       │
│       mode-tagged, baseline-tracked vs SPY/QQQ/IWO/ARKK/60-40  │
│                                                                │
│   S4  Smart-money monitor   ←  L7 events                       │
│       (insider clusters / LSV-accumulation / 13G / activist)   │
│       fires events to P3 / P4 / P9 per routing rules           │
│                                                                │
│   ⚠ S3 (tax bucket) REMOVED in Section 2 — operator-side       │
│        concern in v0.1; revisit at v0.5+                        │
│                                                                │
└────────────────────┬─────────────────────────────────────────────┘
                     │
                     │ (pull at phase entry + push on regime shift)
                     ▼
   ┌──► P1  TREND CAPTURE  (consults L1, L2)
   │        │
   │        ▼
   │   P2  SCENARIO WRITING 3/5/10y  (L2)
   │        │  granular probabilities (60/40 not 75/25);
   │        │  pre-defined kill criteria; falsifiable
   │        ▼
   │   P3  NAME DISCOVERY  (L3 + S4 events)  ◄── Gate 1
   │        │   • L3-d red-flag check (fraud signature 3+/6 = exit)
   │        │   • L3-e Tier-A signal check
   │        │   • Era-mismatch check (right-thing-wrong-decade)
   │        │   PASS → S2 counterfactual ledger
   │        ▼
   │   P4  DEEP DIVE — 5-STYLE DEBATE  ◄── Gate 2
   │        │   Phase A: 5 styles isolated research
   │        │            Value / Growth / Quality / Macro-Regime / Quant-Technical
   │        │   Phase B: each style locks load-bearing claims + non-negotiables
   │        │   Phase C: LLM-as-judge detects conflict (Type 1/2/3)
   │        │            → if conflict: bounded 3-round negotiation
   │        │            → if no conflict: skip to Phase D
   │        │   Phase D: PMSupervisor synthesis, weighted by mode-style matrix
   │        │            • PRESERVES DISSENT (does not force consensus)
   │        │   Evaluator: hard-gate, OUTSIDE the debate
   │        │   PASS → S2 counterfactual ledger
   │        ▼
   │   P5  WATCHLIST ADD  ◄── Gate 3
   │        │   ⚠ NO 5% CAP — research artifact, not portfolio
   │        │   Output: name + mode (B/B'/C) + conviction (0-1, S1 haircut at v0.5+)
   │        │           + sensitivity tag (HIGH/MEDIUM/LOW)
   │        │           + recommended size band (mode-specific)
   │        │           + kill criteria (Annie Duke style)
   │        │           + catalyst calendar
   │        ▼
   │   P6  DISPOSITION DETERMINATION  (L6, always-on per name)
   │        │   classify: swing / long / both
   │        │   determines stop type:
   │        │     time-stop (Tudor Jones) → swing
   │        │     thesis-break-stop (Marks/Buffett) → long-term
   │        ▼
   │   P7  ENTRY EXECUTION  (L5 + 5% PORTFOLIO CAP)
   │        │   • L5 4-factor (trend / 200DMA / volume / cycle modifier)
   │        │   • Mode-specific size band scaling
   │        │   • 5% cap enforced; price-appreciation exempt
   │        │
   │        ▼
   │ ╔═════════════════════════════════════════════════════════╗
   │ ║  P8  DAILY REFRESH (the loop) ←  L4 + S0 events         ║
   │ ║  Trigger-based, NOT timer-based                          ║
   │ ║                                                          ║
   │ ║  Materiality 1: log + monitor                            ║
   │ ║  Materiality 2: targeted memo update ─────► loops to P4  ║
   │ ║  Materiality 3: full reunderwrite ────────► P4 + P5     ║
   │ ║  Regime shift on HIGH-sens name ──────────► P1/P2 chain ║
   │ ║  Catastrophic event ──────────────────────► fast-path P9║
   │ ╚═════════════════════════════════════════════════════════╝
   │        │
   │        ▼
   └─── P9  EXIT  (v2-final §2.3, L4, L6)
            │   • Thesis-pillar-fail = HIGHEST priority (immediate exit)
            │   • Exit signal eval: NONE / TRIM / FULL_EXIT
            │   • ⚠ S3 removed: NO LT/ST consideration in v0.1
            │   • Output → S2 counterfactual ledger logs disposition
            │
            └─► (calibration update from realized outcomes feeds S1 at v0.5+)
```

### 16.2 The 3-gate pipeline (L7 event → watchlist)

```
                   L7 SIGNAL DETECTED
                   (insider cluster / institutional accumulation /
                    activist 13D / 13G new-5%-holder)
                          │
                          │
            ┌─────────────┼──────────────────────┐
            │             │                       │
            ▼             ▼                       ▼
       Catastrophic    On watchlist?         On watchlist?
       (fraud sig.)         YES                    NO
            │                │                       │
            ▼                ▼                       ▼
        FAST-PATH         P4 RE-       ┌── P3  CANDIDATE-DISCOVERY
        TO P9 EXIT        UNDERWRITE   │      ◄── Gate 1
        consideration     (5-style     │      • L3-d red flags?
                          debate)      │      • Era-mismatch?
                                       │      • Tier-A signal check?
                                       │
                                       │      FAIL → PASS (logged to S2)
                                       │      PASS ↓
                                       │
                                       └─► P4  DEEP DIVE
                                              ◄── Gate 2
                                              5-style debate;
                                              PMSupervisor decision
                                              {ADD / WATCH / PASS}

                                              PASS → S2
                                              WATCH → flagged
                                              ADD ↓

                                          ┌─► P5  WATCHLIST ADD
                                          │      ◄── Gate 3
                                          │      • Mode tag (AI classifies)
                                          │      • Sensitivity tag (Macro agent)
                                          │      • Conviction + size band
                                          │      • Kill criteria
                                          │
                                          ▼
                                      ON WATCHLIST
                                      (research-approved;
                                       operator decides actual buys)
```

**Why the pipeline matters:** L7 is a discovery signal, not an admission ticket. Most L7-fired candidates will be PASSed at P3 or P4. Only the small subset that survives all 3 gates lands on the watchlist. The watchlist itself does not constrain the operator's portfolio — it facilitates the operator's allocation decisions.
