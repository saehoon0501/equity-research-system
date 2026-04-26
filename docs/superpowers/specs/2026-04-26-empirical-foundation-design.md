# Empirical Domain Library — Design Spec

**Date:** 2026-04-26
**Status:** Approved for implementation planning
**Operator:** saehoon0501
**Project:** equity-research-system

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

The library is shaped to support this funnel, captured from operator's stated workflow:

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

## 4. Architecture

```
6 parallel general-purpose subagents (one per lane, L1–L6)
                    │
       Each writes its lane file(s) under
       .claude/references/empirical/
                    │
       Main context synthesizes
       .claude/references/empirical/00-overview.md
       as the entry point
```

- No code. Markdown only.
- Subagents have `WebSearch` + `WebFetch`.
- L3 (successful-company patterns) is the largest lane — splits internally into a sub-folder.

## 5. Lane definitions

| Lane | Empirical question | Funnel phase served |
|---|---|---|
| **L1. Regime capture from cross-asset signals** | What in rates / credit / FX / commodities / vol reliably identifies regime? Lead-lag relationships. Signal vs noise. | "news/indexes/futures → capture a trend" |
| **L2. Probabilistic scenario writing (3/5/10y)** | How practitioners write falsifiable multi-year scenarios. Common forecasting failures. How to update without anchoring. | "write a scenario for 3/5/10 years" |
| **L3. Successful-company pattern library** | Case studies of major multi-baggers across eras / sectors / tech regimes. Per case: business-model evolution, growth-rate trajectory + duration, historical/macro background enabling success, capital allocation, founder/management archetype. Cross-era pattern extraction. **Includes counterfactuals (companies that looked like winners and weren't) for survivorship-bias defense.** | "research stocks likely to be the next Palantir case" |
| **L4. View-refresh discipline** | Anchor-drift defenses. Trigger-based re-evaluation. Pre-mortem cadence. When to capitulate vs persist on a thesis. | "repeat daily for updates — balance shift vs stubborn" |
| **L5. Technical execution playbooks** | Empirically validated technical patterns only — trend, volume / breadth, vol regime, ATR-stops. Failure modes. What TA folklore to discard. | "technical analysis for entry and exit" |
| **L6. Multi-horizon disposition (swing / invest / both)** | Decision rules per name × per timeframe. How PMs scale in/out. Position lifecycle. What changes a disposition. | "swing trade vs long-term investing vs both" |

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
  00-overview.md                          # entry point — TOC, cross-lane synthesis, "how to use"
  L1-regime-capture.md
  L2-scenario-writing.md
  L3-successful-companies/                # split internally — large lane
    00-overview.md                        # local index
    a-tech-platforms.md                   # MSFT / AAPL / AMZN / GOOGL / META / NVDA / PLTR / etc.
    b-consumer.md                         # KO / NKE / COST / LULU / etc.
    c-financials-healthcare.md            # V / MA / UNH / DHR / etc.
    d-cyclicals-and-misses.md             # cyclicals + survivorship counterfactuals
    e-cross-era-patterns.md               # synthesized patterns across all cases
  L4-refresh-discipline.md
  L5-technical-playbooks.md
  L6-horizon-disposition.md
```

The L3 sub-split is a soft suggestion — the L3 subagent may adjust if it finds better cuts.

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

- Decide how the library integrates with the existing `v2-final-spec.md` paradigm
- Build consumer skills (regime-capture, scenario-writing, name-discovery, swing-vs-invest disposition)
- Decide whether the library replaces, augments, or sits beside the current `/research-company` flow
- Maintenance cadence (when to refresh lanes; how to add new sources)
