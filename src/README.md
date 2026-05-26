# src/

Supporting Python infrastructure for the equity research system.

Per Path A (BUILD_LOG.md Day 1 architectural decisions), agent definitions live in `.claude/agents/` (Claude Code subagent infrastructure), not in `src/agents/`. The Python modules in this directory are the substrate that agents read from and write to.

> **2026-05-26 — decision-7 scope collapse.** The `/research-company` keep-set now is:
> `p8_tactical_overlay`, `p9_flow_overlay`, `p10_reversion_overlay`, `evaluator_gates`,
> `p7_recommendation_emitter`, `agent_harness`, `data_layer`, `regime_sidecar`, `audit_trail`,
> `evidence_index`, `mode_classifier`, `eval`, and `mcp/` (9 servers). Modules below that no longer
> appear in this directory — including `backtesting/` — were archived to `archive/_retired/src/`
> (reversible). The build-sequence table and dependency graph below are **historical**; see
> [`docs/decision-7-sweep-set.md`](../docs/decision-7-sweep-set.md) for the authoritative keep/retire list.

---

## Build sequence (per implementation-sequencing.md §4 — FTE track)

| Module | Built in | Purpose |
|---|---|---|
| `data_layer/` | Week 2 (interface) + Week 4 (Sharadar integration) | Pluggable adapter pattern. Functions like `fetch_prices(ticker)` try providers in fallback chain. Provider-agnostic interface so future swaps don't require rewriting calling code. Per BUILD_LOG.md Day 1, specific provider commitments deferred (price/news ~week 4, Sharadar ~week 10). |
| `evidence_index/` | Week 3 | Load-bearing. Append-only database tracking every claim made by every agent. Schema per v2-final §4.2.5 includes evidence_id, agent_id, claim_text, source_uri, source_date, source_quality_tier, surfaced_date, retention storage_tier. Three downstream consumers: citation rubric, contamination defense, postmortem traceability. |
| `agent_harness/` | Week 6 | Path A: Python wrappers around Claude Code subagent invocations. Replaces v2-final §4.3 LangGraph harness. Provides: token/cost tracking, mandatory Evidence Index write hook, mechanical contamination check (every dated claim → Evidence Index validation), process-rubric grading hook, versioned prompts via git history of `.claude/agents/` files. |
| `backtesting/` | Weeks 10–11 | Walk-forward validation with embargo, effective_cutoff = stated_cutoff + 6 months, pre/post-cutoff Sharpe split, DSR with explicit trial reporting, PBO, realistic friction modeling (spread, market impact, commission, tax), counterfactual baselines (SPY, equal-weight, sector-matched, 60/40). Built on vectorbt per v2-final §2.6. |

---

## Module dependencies

```
data_layer ──── (foundation; depends on external providers via adapter pattern)
        │
        ├──→ evidence_index (consumes filings/news for source citations)
        ├──→ backtesting (consumes prices, fundamentals)
        └──→ agent_harness (consumes via tool exposure to subagents)

evidence_index ──── (load-bearing; consumed by every agent for citation)
        │
        ├──→ agent_harness (mandatory write hook + mechanical contamination check)
        └──→ backtesting (postmortem traceability when predictions resolve)

agent_harness ──── (depends on data_layer + evidence_index)
        │
        └──→ Claude Code subagents in .claude/agents/

backtesting ──── (depends on data_layer + evidence_index)
        │
        └──→ Phase gate evaluation at Checkpoint 3
```

---

## Anti-patterns to avoid

Per implementation-sequencing.md §8:

- **Don't start data_layer in week 1.** Week 1 is foundation: repo, databases, verification artifacts, interface design only. Implementation begins week 2.
- **Don't build elaborate caching before basic adapters work.** Caching is week-9 buffer territory, not week-2 feature.
- **Don't add Evidence Index fields "later".** Schema decisions in week 3 are load-bearing for v0.5 and v1.0; adding fields after data is populated is harder than adding now.
- **Don't build CPCV.** Phasing-plan.md explicitly defers CPCV to "do it once you have a strategy worth defending." Walk-forward + embargo is v0.1 scope.
- **Don't optimize backtest parameters post-hoc.** DSR with trial reporting catches this if run honestly. Choose parameters before measuring outcomes.

---

## Status (Day 1)

All four modules: empty. Build begins week 2 per the schedule above.
