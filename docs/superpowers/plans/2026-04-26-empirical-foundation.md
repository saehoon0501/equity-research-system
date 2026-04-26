# Empirical Domain Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce the project's ground-zero empirical-domain knowledge library (6 curated, source-cited, distilled lanes) under `.claude/references/empirical/`, with an `00-overview.md` entry point synthesized after lane research completes.

**Architecture:** 6 parallel `general-purpose` subagent dispatches (one per lane) using `WebSearch` + `WebFetch` to produce markdown reference files following a fixed Section A/B/C/D output schema. Main context performs validation and synthesis after all lanes complete. No code, no tests, no consumer skills built here — markdown reference material only.

**Tech Stack:** Claude Code subagent dispatch (`Agent` tool, `subagent_type=general-purpose`); WebSearch / WebFetch for sourcing; Markdown for output; Git for version control.

**Spec:** `docs/superpowers/specs/2026-04-26-empirical-foundation-design.md`

---

## File Structure

Files this plan creates:

```
.claude/references/empirical/
  00-overview.md                          # main-context synthesis (Task 10)
  L1-regime-capture.md                    # Task 2
  L2-scenario-writing.md                  # Task 3
  L3-successful-companies/                # Task 4 (subfolder + multiple files)
    00-overview.md
    a-tech-platforms.md
    b-consumer.md
    c-financials-healthcare.md
    d-cyclicals-and-misses.md
    e-cross-era-patterns.md
  L4-refresh-discipline.md                # Task 5
  L5-technical-playbooks.md               # Task 6
  L6-horizon-disposition.md               # Task 7
```

Each lane file follows a fixed Section A (curated sources) / B (distilled patterns) / C (open questions) / D (lane-specific extras, optional) schema per spec §6.

---

## Shared Subagent Prompt Template

Every lane subagent receives a prompt built from this template. Variable parts are marked `{{LIKE_THIS}}` and filled per-task.

````
You are a research subagent producing one lane of the equity-research-system's empirical-domain knowledge library.

## Your lane
**{{LANE_ID}}: {{LANE_NAME}}**

{{LANE_SCOPE_PARAGRAPH}}

## Your deliverable
A single markdown file at the exact path: `{{DELIVERABLE_PATH}}`
{{L3_ONLY_SUBFOLDER_INSTRUCTION}}

## Output schema — every lane file MUST contain these sections in order

### Section A — Curated sources (15-30 entries)

Format per entry:
```
- [title](url) — 1-line annotation [Tier N]
```

**Tier definitions:**
- Tier 1 — academic papers + practitioners with verifiable track record (named PMs, fund letters from established funds, peer-reviewed research, books by practitioners with public records)
- Tier 2 — established financial press, respected practitioner blogs, hedge-fund letters from non-marquee funds
- Tier 3 — other (used only if it covers ground Tier 1/2 doesn't)

**Diversity rule:** No single author or site cited more than 3 times across this lane. Mix academic + practitioner + case studies.

**Anti-hallucination rule:** Every URL you cite MUST be one you actually fetched via WebFetch (or surfaced via WebSearch and confirmed reachable). If a source can't be fetched, drop it. Do not cite a URL you have not retrieved.

### Section B — Distilled patterns (10-20 bullets)

What the literature *empirically establishes*. Each bullet must cite the Section A source(s) it rests on. Patterns must be specific and actionable, not generic wisdom.

❌ "Markets are cyclical."
✅ "Credit spreads widen 3-9 months before equity drawdowns ≥20% in 7 of last 10 cycles (sources: [3], [11])."

### Section C — Open questions / disagreements

Where credible sources disagree, stated explicitly. Future skill-builders need to know where uncertainty lives.

### Section D — Lane-specific extras (optional)

If the lane has a natural tabular or structured output (lead-lag table, pattern table, etc.), include it here.

## Workflow

1. WebSearch broadly for the lane topic across academic + practitioner + case-study sources
2. WebFetch the most promising results to confirm they exist and read their substance
3. Iterate — multiple WebSearch / WebFetch rounds; aim for ~30-90 minutes of focused depth
4. Draft Section A with tier labels and diversity check
5. Draft Section B citing only Section A entries
6. Draft Section C with explicit disagreements
7. Add Section D if natural to the lane
8. Write the deliverable file via the Write tool to the exact path above

## Quality bar
- Thoroughness over speed
- Source diversity over volume
- Concrete patterns over generic wisdom
- Cite source-of-claim on every Section B bullet
- Drop any source you can't fetch

## When done
Write the file and report back with: (a) deliverable path, (b) source counts by tier, (c) author/site distribution to confirm diversity rule satisfied, (d) any sources you considered and dropped (with reason).
````

---

## Task 1: Pre-flight — create target directory

**Files:**
- Create directory: `.claude/references/empirical/`
- Create directory: `.claude/references/empirical/L3-successful-companies/`

- [ ] **Step 1: Create directories**

```bash
mkdir -p /Users/sehoonbyun/Documents/equity-research-system/.claude/references/empirical/L3-successful-companies
```

- [ ] **Step 2: Verify created**

```bash
ls -la /Users/sehoonbyun/Documents/equity-research-system/.claude/references/empirical/
```

Expected: shows `L3-successful-companies/` subdirectory.

- [ ] **Step 3: No commit yet** — directories will be committed alongside the lane files in Task 11.

---

## Task 2: Dispatch L1 — Regime capture from cross-asset signals

**Files:**
- Create: `.claude/references/empirical/L1-regime-capture.md` (written by subagent)

- [ ] **Step 1: Dispatch L1 subagent**

Use the shared prompt template above with these substitutions:

- `{{LANE_ID}}`: L1
- `{{LANE_NAME}}`: Regime capture from cross-asset signals
- `{{DELIVERABLE_PATH}}`: `/Users/sehoonbyun/Documents/equity-research-system/.claude/references/empirical/L1-regime-capture.md`
- `{{L3_ONLY_SUBFOLDER_INSTRUCTION}}`: (empty — L1 is single-file)
- `{{LANE_SCOPE_PARAGRAPH}}`:

  > What in rates / credit / FX / commodities / equity vol reliably identifies regime? Lead-lag relationships across assets — e.g., do credit spreads precede equity drawdowns and at what lag? Does the yield curve invert before recessions, and how does the lag vary by cycle? When does the dollar lead vs lag equities? What does VIX term structure indicate about regime change? Distinguish empirically validated lead-lag relationships from spurious correlations. Surface what 50+ years of data say about which signals practitioners actually use vs which are folklore.

  Section D for this lane should include a lead-lag relationship table (signal → asset class affected → typical lag → cycles validated in → confidence level).

Tool call:
```
Agent({
  description: "L1 empirical research — regime capture from cross-asset signals",
  subagent_type: "general-purpose",
  prompt: <shared template + L1 substitutions>,
  run_in_background: true
})
```

- [ ] **Step 2: Note background agent ID** for monitoring.

---

## Task 3: Dispatch L2 — Probabilistic scenario writing

**Files:**
- Create: `.claude/references/empirical/L2-scenario-writing.md` (written by subagent)

- [ ] **Step 1: Dispatch L2 subagent**

Substitutions:

- `{{LANE_ID}}`: L2
- `{{LANE_NAME}}`: Probabilistic scenario writing (3 / 5 / 10 year horizons)
- `{{DELIVERABLE_PATH}}`: `/Users/sehoonbyun/Documents/equity-research-system/.claude/references/empirical/L2-scenario-writing.md`
- `{{L3_ONLY_SUBFOLDER_INSTRUCTION}}`: (empty)
- `{{LANE_SCOPE_PARAGRAPH}}`:

  > How practitioners actually write multi-year scenarios (3, 5, 10 year horizons). What makes a scenario falsifiable vs decorative. The empirical track record of multi-year forecasting — what hit rates do macro forecasters historically achieve? When are scenarios useful even if their point predictions are wrong? Common forecasting failures: anchoring on recent history, narrative confirmation bias, single-path determinism. Practitioner techniques for probabilistic branching ("if X then Y, with P(X)=…"). Updating cadence: how to revise scenarios as new data arrives without overfitting to noise. Sources: Druckenmiller / Soros reflexivity, Marks's memos on cycles, Tetlock's superforecasting work, GMO 7-year forecasts, Hussman / Grantham archives, etc.

- [ ] **Step 2: Note background agent ID**.

---

## Task 4: Dispatch L3 — Successful-company pattern library (LARGEST)

**Files:**
- Create: `.claude/references/empirical/L3-successful-companies/00-overview.md` (written by subagent)
- Create: `.claude/references/empirical/L3-successful-companies/a-tech-platforms.md` (written by subagent)
- Create: `.claude/references/empirical/L3-successful-companies/b-consumer.md` (written by subagent)
- Create: `.claude/references/empirical/L3-successful-companies/c-financials-healthcare.md` (written by subagent)
- Create: `.claude/references/empirical/L3-successful-companies/d-cyclicals-and-misses.md` (written by subagent)
- Create: `.claude/references/empirical/L3-successful-companies/e-cross-era-patterns.md` (written by subagent)

- [ ] **Step 1: Dispatch L3 subagent** (this lane is the largest — budget more depth)

Substitutions:

- `{{LANE_ID}}`: L3
- `{{LANE_NAME}}`: Successful-company pattern library
- `{{DELIVERABLE_PATH}}`: `/Users/sehoonbyun/Documents/equity-research-system/.claude/references/empirical/L3-successful-companies/` (folder, see sub-files below)
- `{{L3_ONLY_SUBFOLDER_INSTRUCTION}}`:

  > Your output is split across 6 files inside the folder above:
  > - `00-overview.md` — local TOC + 1-paragraph summary per sub-file + how to navigate
  > - `a-tech-platforms.md` — case studies of: MSFT, AAPL, AMZN, GOOGL, META, NVDA, PLTR (plus 2-3 more practitioner choices)
  > - `b-consumer.md` — case studies of: KO, NKE, COST, LULU, SBUX, MCD (plus 2-3 more)
  > - `c-financials-healthcare.md` — case studies of: V, MA, UNH, DHR, BRK.B, ISRG (plus 2-3 more)
  > - `d-cyclicals-and-misses.md` — successful cyclicals (e.g. CAT, DE, energy super-major case studies) AND survivorship counterfactuals (companies that looked like next-X and went to zero — Theranos, WeWork-IPO-thesis, Beyond Meat, Peloton, Pets.com / dot-com era, Enron-as-misclassified-growth, etc.)
  > - `e-cross-era-patterns.md` — synthesis ACROSS all the above. The patterns that recur regardless of era / sector / tech background. This is the load-bearing file for the "next Palantir" question.
  >
  > Each individual case study under a-d should include: business model evolution + key inflection, growth rate trajectory + duration of supernormal growth, historical / macro background that enabled success (the right thing in the right decade), capital allocation pattern, founder / management archetype.
  >
  > Each sub-file follows the same Section A/B/C/D schema. Section A in each sub-file lists sources cited *for the cases in that sub-file*. The cross-era patterns file (`e-cross-era-patterns.md`) is the most important — it should contain the extracted patterns the operator can use as discovery criteria for future "next-X" candidates.
  >
  > You may adjust the sub-file split if you find a better cut. Document any change in `00-overview.md`.

- `{{LANE_SCOPE_PARAGRAPH}}`:

  > Case studies of major multi-bagger US-listed companies across eras (1970s-2020s), sectors (tech, consumer, financials, healthcare, industrials, energy), and technology regimes (PC era, internet era, mobile era, cloud era, AI era). For each case: what was the business model and how did it evolve? What was the growth rate trajectory and how long did supernormal growth last? What was the historical / macro background that enabled success — the right business in the right decade? What was the capital allocation pattern? What was the founder / management archetype?
  >
  > Critical discipline: include survivorship counterfactuals. For every Palantir there are ~50 lookalikes that went to zero. Document at least 8-12 such cases (Theranos, WeWork's pre-IPO thesis, Beyond Meat, Peloton, Pets.com, dot-com losers, Enron mis-classified-as-growth, Valeant, GE-as-conglomerate, etc.) so future name-discovery skills can defend against survivorship bias.
  >
  > The load-bearing question this lane answers: what cross-era patterns reliably distinguish multi-baggers from look-alikes that fail? Pattern candidates to test: founder skin-in-the-game, customer concentration trajectory, gross-margin trajectory, capital efficiency / FCF conversion, TAM expansion via adjacent moves, network effects, pricing power, optionality value (call options on adjacent markets), management capital allocation, narrative reflexivity — but the empirical question is which of these actually held up across cases.

- [ ] **Step 2: Note background agent ID** (this one will run longest).

---

## Task 5: Dispatch L4 — View-refresh discipline

**Files:**
- Create: `.claude/references/empirical/L4-refresh-discipline.md` (written by subagent)

- [ ] **Step 1: Dispatch L4 subagent**

Substitutions:

- `{{LANE_ID}}`: L4
- `{{LANE_NAME}}`: View-refresh discipline
- `{{DELIVERABLE_PATH}}`: `/Users/sehoonbyun/Documents/equity-research-system/.claude/references/empirical/L4-refresh-discipline.md`
- `{{L3_ONLY_SUBFOLDER_INSTRUCTION}}`: (empty)
- `{{LANE_SCOPE_PARAGRAPH}}`:

  > How practitioners balance "shift the view when warranted" against "stay disciplined to the thesis." Anchor-drift defense — what techniques empirically reduce slow drift away from a thesis without re-evaluation? Trigger-based re-evaluation: pre-defining what new information would change a view (catalyst calendar, invalidation thresholds, KPI hits/misses). Pre-mortem cadence — does running pre-mortems quarterly vs annually vs ad-hoc produce different decision quality? When to capitulate vs persist on a thesis: empirical evidence on hold-loser-too-long vs cut-winner-too-early failure modes. Practitioner sources: Klarman, Marks, Buffett's "20-punch card" framework, Schwager's market wizard interviews, Tetlock on belief-updating, behavioral finance literature on disposition effect.

- [ ] **Step 2: Note background agent ID**.

---

## Task 6: Dispatch L5 — Technical execution playbooks

**Files:**
- Create: `.claude/references/empirical/L5-technical-playbooks.md` (written by subagent)

- [ ] **Step 1: Dispatch L5 subagent**

Substitutions:

- `{{LANE_ID}}`: L5
- `{{LANE_NAME}}`: Technical execution playbooks (entry / exit, what survives empirical scrutiny)
- `{{DELIVERABLE_PATH}}`: `/Users/sehoonbyun/Documents/equity-research-system/.claude/references/empirical/L5-technical-playbooks.md`
- `{{L3_ONLY_SUBFOLDER_INSTRUCTION}}`: (empty)
- `{{LANE_SCOPE_PARAGRAPH}}`:

  > Empirically validated technical patterns only. Trend-following (CTA literature, Jegadeesh-Titman momentum, AQR work). Volume / breadth confirmation — what does academic literature plus practitioner work say about volume as a true signal vs noise? Volatility regime signals (VIX term structure, realized-vol regime classification). ATR-based stop methodology vs fixed-percentage stops — empirical comparison. Breakout failures vs follow-through. Mean-reversion thresholds — at what z-score / lookback does mean-reversion historically work, and in what regimes does it fail (i.e., during trending markets)? **What TA folklore to discard:** head-and-shoulders, Elliott waves, candlestick patterns claimed to predict reversals — survey what actually fails empirical scrutiny. Distinguish trader-survivor-bias claims from peer-reviewed signal validation.

  Section D for this lane should include a "patterns that survived empirical scrutiny vs folklore that didn't" table.

- [ ] **Step 2: Note background agent ID**.

---

## Task 7: Dispatch L6 — Multi-horizon disposition

**Files:**
- Create: `.claude/references/empirical/L6-horizon-disposition.md` (written by subagent)

- [ ] **Step 1: Dispatch L6 subagent**

Substitutions:

- `{{LANE_ID}}`: L6
- `{{LANE_NAME}}`: Multi-horizon disposition (swing trade vs long-term investment vs both)
- `{{DELIVERABLE_PATH}}`: `/Users/sehoonbyun/Documents/equity-research-system/.claude/references/empirical/L6-horizon-disposition.md`
- `{{L3_ONLY_SUBFOLDER_INSTRUCTION}}`: (empty)
- `{{LANE_SCOPE_PARAGRAPH}}`:

  > How does a discretionary PM decide, for a given name, whether the right play is swing trade (weeks-to-months), long-term investment (years), or both (core position + tactical trim/add)? Decision rules per name × per timeframe — what does the empirical literature plus practitioner writing say about which characteristics put a name in which bucket? Volatility regime, trend strength, fundamental momentum, narrative reflexivity, position lifecycle. How to scale in vs full position at entry. How to scale out: time-stops, trailing stops, partial profits at target, full exit on thesis-break. Position lifecycle frameworks (Druckenmiller "biggest positions when conviction highest"; Marks on second-level thinking; Soros on changing your mind dramatically). What changes a disposition (regime shift, fundamentals deteriorate, narrative breaks, valuation extremes). Distinguish framework-quality writing from PnL-anecdote-driven writing.

- [ ] **Step 2: Note background agent ID**.

---

## Tasks 2-7 dispatch note

**Critical:** Tasks 2 through 7 should be dispatched in **a single message with 6 parallel `Agent` tool calls**, since the subagents are independent and run concurrently. Doing so kicks all 6 off at once and minimizes wall-clock time.

After dispatch, wait for all 6 to complete (notifications fire on completion). Do not poll, do not use sleep — the runtime notifies when each subagent finishes.

---

## Task 8: Validate lane outputs against schema

**Files:**
- Read: all lane files written by Tasks 2-7

- [ ] **Step 1: Verify all expected files exist**

```bash
ls -la /Users/sehoonbyun/Documents/equity-research-system/.claude/references/empirical/
ls -la /Users/sehoonbyun/Documents/equity-research-system/.claude/references/empirical/L3-successful-companies/
```

Expected: `L1-regime-capture.md`, `L2-scenario-writing.md`, `L4-refresh-discipline.md`, `L5-technical-playbooks.md`, `L6-horizon-disposition.md` plus L3 sub-folder with at least `00-overview.md` + 5 sub-files (a through e).

- [ ] **Step 2: Spot-check schema compliance per file**

For each lane file (and each L3 sub-file), use Read to confirm:
- Has `## Section A` heading with ≥10 entries (target 15-30)
- Each Section A entry has format `- [title](url) — annotation [Tier N]` with N ∈ {1, 2, 3}
- Has `## Section B` heading with ≥8 bullets (target 10-20)
- Section B bullets cite Section A entries (e.g. by `[N]` or by named source)
- Has `## Section C` heading and is non-empty
- Section D present if natural to the lane

If any lane fails: re-dispatch that lane's subagent with explicit feedback on what was missing.

- [ ] **Step 3: Diversity rule check**

For each lane, count author/site occurrences in Section A. If any author or site appears more than 3 times, flag the lane and ask the subagent to diversify.

A simple grep approach:
```bash
# Spot-check approach: scan for any obvious monoculture (e.g., everything from one substack)
grep -oE 'https?://[^/]+' /Users/sehoonbyun/Documents/equity-research-system/.claude/references/empirical/L*.md | sort | uniq -c | sort -rn | head -20
```

If a single domain appears more than ~5 times across one lane (rough heuristic for the diversity rule, since same-domain ≠ same-author but is a useful proxy), flag it.

- [ ] **Step 4: No commit yet** — commit happens in Task 11 after synthesis.

---

## Task 9: Spot-check fetched URLs (anti-hallucination)

**Files:** None modified — read-only validation.

- [ ] **Step 1: Sample 2-3 URLs from each lane's Section A**

Pick varied URLs (not all from same author). Use WebFetch on each to confirm:
- URL resolves
- Content matches the annotation in the lane file (broadly — exact wording not required, but topic must match)

Example for one URL:
```
WebFetch(url="https://...", prompt="Confirm this page is about X (matching the annotation in the lane file).")
```

- [ ] **Step 2: If any URL fails to resolve or content doesn't match**

Document which URL in which lane. Re-dispatch that lane's subagent with feedback: "Source [N] URL doesn't resolve / mismatches annotation. Replace it with a verified source."

- [ ] **Step 3: If all spot-checks pass**, proceed to Task 10.

---

## Task 10: Synthesize `00-overview.md` (main context)

**Files:**
- Create: `.claude/references/empirical/00-overview.md`

- [ ] **Step 1: Read all lane files into main context**

```
Read each lane file in turn (L1, L2, L3 sub-files, L4, L5, L6). Build a working understanding of what each lane established.
```

- [ ] **Step 2: Write `00-overview.md`** with this structure:

```markdown
# Empirical Domain Library — Overview

This is the entry point for the project's ground-zero empirical-domain knowledge library.
It is reference material consumed by future skills. Do not modify lane files casually —
they are source-of-truth for the project's empirical claims.

## Table of contents

- **[L1 — Regime capture from cross-asset signals](L1-regime-capture.md)**
  <one-paragraph summary of what L1 established>

- **[L2 — Probabilistic scenario writing](L2-scenario-writing.md)**
  <one-paragraph summary>

- **[L3 — Successful-company pattern library](L3-successful-companies/00-overview.md)**
  <one-paragraph summary>

- **[L4 — View-refresh discipline](L4-refresh-discipline.md)**
  <one-paragraph summary>

- **[L5 — Technical execution playbooks](L5-technical-playbooks.md)**
  <one-paragraph summary>

- **[L6 — Multi-horizon disposition](L6-horizon-disposition.md)**
  <one-paragraph summary>

## Cross-lane synthesis

<patterns that recur across multiple lanes — e.g. if L1 + L3 + L5 all converge
on "regime change is the highest-leverage signal," surface it here. List 4-8 cross-lane
patterns with citations to the lane(s) they recur in.>

## Dependency map for downstream skill builders

<which lanes a future skill would load to answer which question — e.g.:>

| If you're building... | Load these lanes |
|---|---|
| A regime-capture skill | L1, L2 |
| A name-discovery skill ("next Palantir") | L3, plus L1 for regime context |
| A swing-vs-invest disposition skill | L3, L5, L6 |
| A view-refresh skill (daily update discipline) | L4, plus catalyst awareness from L1 |
| A technical-execution skill (entry/exit) | L5, L6 |

## Builder's guide

- **Don't dump the whole library into a skill's context.** Load lanes selectively per skill scope.
- **Cite tier-1 patterns** when justifying a skill's logic. Tier-2/3 sources are supporting, not load-bearing.
- **Section C disagreements are first-class.** A skill that pretends consensus exists where Section C says it doesn't is mis-specified.
- **Refresh cadence:** the library is not auto-updated. When a downstream skill discovers a load-bearing claim has shifted, that triggers a manual refresh of the affected lane.
```

- [ ] **Step 3: Confirm 00-overview.md saved at `.claude/references/empirical/00-overview.md`**.

---

## Task 11: Final acceptance check + commit

**Files:** All files in `.claude/references/empirical/`.

- [ ] **Step 1: Walk through spec §12 acceptance criteria**

```
- [ ] All 6 lane files (or sub-files for L3) exist under `.claude/references/empirical/`
- [ ] Each lane file has Sections A, B, C present and non-empty
- [ ] Each Section A entry has a Tier label
- [ ] Each Section B bullet cites at least one Section A entry
- [ ] No single author/site appears more than 3 times in any lane's Section A
- [ ] Spot-check of 2-3 random URLs per lane confirms they fetch and match the annotation
- [ ] `00-overview.md` exists with TOC, cross-lane synthesis, dependency map, builder's guide
- [ ] All files committed to git in a single coherent commit
```

If any criterion fails, fix before committing.

- [ ] **Step 2: Stage only empirical-foundation files**

```bash
git add .claude/references/empirical/ docs/superpowers/plans/2026-04-26-empirical-foundation.md
git status
```

Expected: only files under `.claude/references/empirical/` and the plan file are staged. If other files appear staged, unstage them — the project has many work-in-progress changes that should not be bundled into this commit.

- [ ] **Step 3: Commit**

```bash
git commit -m "$(cat <<'EOF'
Add empirical-domain knowledge library (6 curated lanes + overview)

Ground-zero empirical reference material for the equity-research-system,
produced by 6 parallel general-purpose research subagents per the
2026-04-26 empirical-foundation design spec. Lanes:

- L1 regime capture from cross-asset signals
- L2 probabilistic scenario writing
- L3 successful-company pattern library (sub-folder, 6 files)
- L4 view-refresh discipline
- L5 technical execution playbooks
- L6 multi-horizon disposition (swing / invest / both)

Plus 00-overview.md as the entry point with TOC, cross-lane synthesis,
dependency map for downstream skill builders, and builder's guide.

No consumer skills built here — those follow as separate brainstorming
cycles. Not part of v0.1 build clock.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 4: Verify commit**

```bash
git log -1 --stat
```

Expected: shows new files under `.claude/references/empirical/` plus the plan file.

---

## Self-Review

**1. Spec coverage check.** Walking spec sections against tasks:

- §1 Goal — Tasks 2-7 (lane research) + Task 10 (overview synthesis) cover this
- §2 Non-goals — explicit constraints, no tasks needed (just adherence)
- §3 Funnel — informs lane scopes in Tasks 2-7
- §4 Architecture — Tasks 2-7 (parallel subagent dispatch) + Task 10 (synthesis)
- §5 Lane definitions — Tasks 2-7 each carry their lane's scope paragraph
- §6 Output schema — embedded in shared subagent prompt template
- §7 File layout — Task 1 creates dirs; Tasks 2-7 + Task 10 produce files
- §8 00-overview.md — Task 10
- §9 Subagent prompt template — embedded above + per-task substitutions
- §10 Cost & timing — informational (no task needed)
- §11 Risks & mitigations — Task 8 (schema validation) + Task 9 (URL spot-check) cover anti-hallucination, diversity, generic-wisdom risks
- §12 Acceptance criteria — Task 11 step 1 walks through this list
- §13 Out of scope — adhered to (no consumer-skill tasks in plan)

All covered.

**2. Placeholder scan.** Searched for "TBD", "TODO", "implement later", generic stubs. The plan uses `{{TEMPLATE_VARIABLES}}` which are filled per-task in Tasks 2-7 — these are not placeholders, they're template-variable substitution syntax with the substitution values explicitly given in each task. No real placeholders remain.

**3. Type / signature consistency.** Lane IDs (L1-L6) consistent across all tasks. Deliverable paths consistent with file structure section. Section A/B/C/D schema referenced identically across all lane tasks via the shared template.

No issues found.
