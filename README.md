# Equity Research System

A two-layer investment research system combining LLM-driven watchlist research (slow layer) with quantitative timing/sizing overlay (execution layer). US equities, multi-month horizon, real-money individual investor at small size.

**Status:** v0.1 build — paper-only foundation phase.

**Operating model:** FTE (~40 hours/week)

**Build clock:** 2026-04-26 → kill threshold 2026-10-10 (24 weeks)

---

## Documents

Design documents in `docs/`:

- **[`v2-final-spec.md`](docs/v2-final-spec.md)** — Component specification (architecture). Slow/fast layer separation, agent definitions, quant models, evaluation framework, infrastructure spine.
- **[`phasing-plan.md`](docs/phasing-plan.md)** — v0.1 / v0.5 / v1.0 phasing with phase gates, kill criteria, and the month-18 honest-answer rubric that determines v1.0 continuation.
- **[`implementation-sequencing.md`](docs/implementation-sequencing.md)** — v0.1 week-by-week build plan with dated start, checkpoints, named buffer, and documented-slip protocol.

The build is governed by **[`BUILD_LOG.md`](BUILD_LOG.md)** — the project's operational record. Every week ends with an entry. Every checkpoint produces a written artifact in `checkpoints/`.

---

## Architectural commitments (preserved from v2-final)

- **Slow/fast layer separation with strict watchlist contract.** Execution layer can only act on names the watchlist layer has approved.
- **Mechanical contamination defense via Evidence Index.** Every dated claim must cite a row that resolves to a real source predating the claim's resolution date. Mechanical, not semantic — invariant to model choice.
- **Process vs outcome rubric separation.** Process rubrics enforced as hard gates at output time. LearningLoop (Phase 2, deferred) optimizes against outcome rubrics only — has zero access to process scores as features.
- **Counterfactual ledger.** First-class object measuring system performance against simple baselines (SPY, equal-weight watchlist, sector-matched, 60/40).
- **PASS as default.** CompanyDeepDive's recommended_action defaults to PASS; BUY requires earned conviction.
- **Hard human-approval gate on trades.** No automated trading authority granted to any agent.
- **Calibration-driven sizing.** Quarter-Kelly default, adjusted within bounded floor (1/8) / ceiling (1/2 Kelly) based on Brier-score trends over rolling 90-day windows.
- **Wide P10/P90 ranges.** With realized-volatility honesty floor.
- **Thesis-pillar-fail trigger as highest-priority exit signal.** Never tax-suppressed.

## Path A architectural decision (Day 1)

All agents run on Anthropic via Claude Code subagent infrastructure. v2-final §1.3 model-family diversity for BearCase is deliberately not enforced. Primary contamination defense (mechanical Evidence Index check) remains intact and is invariant to model choice.

**Reversibility:** if contamination defense underperforms at Checkpoint 3 (post-cutoff degradation >20%), this is the first override to reconsider. Restoring §1.3 means routing BearCase through OpenAI or Google API directly, bypassing Claude Code for that one agent.

See [`BUILD_LOG.md`](BUILD_LOG.md) Day 1 entry for full rationale.

---

## Phase scope

### v0.1 (current — 2026-04-26 to ~2026-07-25)

Paper-only foundation. Infrastructure spine + one agent end-to-end (CompanyDeepDive) + backtest harness. No real money. Validates that mechanical contamination defense produces materially better post-cutoff Sharpe than public-frameworks baselines (Profit Mirage paper documented 50–72% Sharpe decay in published frameworks; v0.1 gate requires ≤20%).

### v0.5 (after gate — duration 9–12 months)

Limited real money. Full agent stack (6 agents). Watchlist limited to 3–5 names at extra-high conviction bar (≥0.7 final_conviction). 10–20% of intended capital. Validates operational machinery — reconciliation, safety rails, daily orchestration, calibration tracking.

### v1.0 (after gate — open-ended; month-18 evaluation)

Full deployment. 30–50 names. Full capital. The alpha question, asked honestly only after v0.1 and v0.5 have validated that the system has earned the right to ask it.

---

## Repo structure

```
equity-research-system/
├── BUILD_LOG.md                    # Project's operational record (load-bearing)
├── README.md                       # This file
├── .gitignore
├── .claude/
│   └── agents/                     # Subagent definitions (built week 7+)
├── provider_verification/          # API training-data verification artifacts
│   ├── README.md
│   ├── anthropic.md                # Path A: only Anthropic verified at v0.1
│   ├── api_keys/                   # Sample API call responses (no keys)
│   └── artifacts/                  # Screenshots, T&C captures (gitignored)
├── checkpoints/                    # C1, C2, C3 written artifacts
├── docs/
│   ├── v2-final-spec.md
│   ├── phasing-plan.md
│   └── implementation-sequencing.md
├── src/
│   ├── README.md                   # Describes planned structure per build week
│   ├── data_layer/                 # Built week 2 (interface) + week 4 (impl)
│   ├── evidence_index/             # Built week 3 (load-bearing)
│   ├── agent_harness/              # Built week 6 (Claude Code wrappers per Path A)
│   └── backtesting/                # Built weeks 10–11
├── tests/
└── memos/                          # Sample memos generated week 12 onward
```

---

## How to read this repo if you're returning to it tired

If you're future-tired-you returning to this six months in:

1. Read **`BUILD_LOG.md`** first. The most recent entries tell you where you are.
2. The Day 1 entry tells you what was committed to architecturally and why.
3. **`checkpoints/`** has the formal pass/fail artifacts for each phase gate. If a checkpoint says ✗ on a criterion, that's the criterion that failed. Do not argue around it.
4. **`docs/phasing-plan.md`** §6 names the failure modes the structure protects against. If you're tempted to skip a gate, check which failure mode you're walking toward.
5. **`docs/implementation-sequencing.md`** §10 mirrors that for the build phase.

The thresholds are written so motivated reasoning can't relax them. If you want to soften something while reading, that's the threshold doing its job. Tighten, don't relax.

---

## Status board

- [x] Day 1 first commit (2026-04-26)
- [ ] Anthropic API verification artifact captured
- [ ] Database provisioned
- [ ] §9.3 commitment statement written
- [ ] Week 1 deliverables complete
- [ ] Checkpoint 1 (target: 2026-05-23)
- [ ] Checkpoint 2 (target: 2026-06-20)
- [ ] Checkpoint 3 generation (target: 2026-07-18)
- [ ] Checkpoint 3 evaluation + phase gates (target: 2026-07-25)
- [ ] v0.1 → v0.5 advancement decision
