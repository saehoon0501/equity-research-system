# System Constitution — DRAFT v0

**Status:** DRAFT — pending operator review via `/spec-approve constitution v0.1`.
**Last edit:** 2026-05-11.
**Purpose:** Single canonical file of hard system rules. Every skill and subagent reads this first; the `evaluator` hard-fails violations. Derived from BUILD_LOG.md decisions + `2026-04-29-empirical-foundation-design-v3.md` Section 7 + `evaluator.md` HG-1..HG-12.

Adopts the `.specify/memory/constitution.md` pattern from `github/spec-kit` (Dec 2025).

---

## 1. Runtime invariants (Path A — locked)

1. **Substrate is Claude Code.** No separate Anthropic API key. Subagents dispatched via the `Task` tool against `.claude/agents/*.md` definitions. (BUILD_LOG decision 1.)
2. **MCP grants are declared at tool-level**, never server-level shorthand. `mcp__edgar__get_company_facts` ✅; `mcp__edgar` ❌. Edits to `.claude/agents/*.md` require a Claude Code restart to take effect. (BUILD_LOG 2026-04-26 wiring caveat.)
3. **Subagents run in isolated context.** They do not see PMSupervisor preferences, operator history, or sibling subagent outputs. Isolation is load-bearing for the bull/bear adversarial pair (avoids sycophancy collapse) and for the evaluator's independence.
4. **Search-agent fan-out is mandatory** for fresh data. `cdd-lead`, `bear-case`, `quantitative-analyst`, `strategic-analyst` do NOT directly call edgar/yfinance/market_data/fred/fundamentals — they dispatch search-agent. Keeps orchestrator context clean.

## 2. Output discipline (mechanical, model-invariant)

5. **Every numerical / dated / named-fact claim has an Evidence Index reference.** A claim without an `evidence_id` is a violation regardless of how true it is. (HG-4.)
6. **The mechanical contamination check is non-negotiable.** Each `evidence_id` in any output must (a) exist as a row in `evidence_index`, (b) have a `source_date` predating the claim's `resolution_date`. Evaluator runs this as a Postgres query, not a vibes check. This is the load-bearing protection that compensates for the model-family-diversity waiver in Path A. (HG-1.)
7. **Framework citations must use canonical short-keys.** Every framework invocation in a memo cites a key from `.claude/references/canonical-frameworks.md` (e.g. `mauboussin_moat_2024`). Free-form references are violations. (HG-8.)
8. **No "n/a" — use "SKIPPED — <reason>" instead.** Tier-conditional skips (e.g. DCF on speculative tier) must be marked SKIPPED with the rule cited, never silently dropped. (HG-8 tier-conditional rule.)

## 3. Memo-structural invariants

9. **Tier classification is required.** Every CDD-ensemble memo carries a `tier` field in `{core_fundamental, thematic_growth, speculative_optionality}`. Defaults to the more conservative tier on ambiguity. Bear-case re-classification disagreements surface BOTH tiers. (HG-7.)
10. **CompanyDeepDive memos have ≥3 falsifiable predictions.** Each prediction = specific KPI + target value or direction + specific resolution_date. Vague predictions are violations. (HG-2.)
11. **BearCase memos have ≥1 unrebutted concern OR an explicit named-address statement.** Both empty → violation. (HG-3.)
12. **ExitSignalModel outputs carry `tax_cost_estimate` + `reasoning_trace`.** Tax-aware logic must show its work — whether it suppressed, accepted, or modified the original signal. (HG-5.)
13. **DailyMonitor digest items carry per-item justification, including zeros.** "No thesis implication" alone is too thin; must name a thesis pillar or give reasoned absence. (HG-6.)

## 4. Governance invariants (HMAC-attested)

14. **Four distinct HMAC scopes; never collapse.** `AUDIT_HMAC_KEY` / `PEAK_PAIN_HMAC_KEY` / `PREMORTEM_HMAC_SECRET` / `WATCHLIST_HMAC_SECRET`. Single source of truth for canonical-payload serialization: `src/audit_trail/hmac_verify.py`. A compromise in one scope must not invalidate others.
15. **`Decimal` values get serialized as JSON strings; `float` as JSON numbers.** Surfaced by the `peak_dd_pct` regression. NUMERIC columns participating in HMAC payloads must be wrapped `Decimal(str(...))` at signing time to survive a Postgres round-trip without HMAC drift.
16. **Operator sign-offs are append-only.** `/launch-confirm`, `/spec-approve` write to `docs/superpowers/launch-readiness-log.md` and `docs/superpowers/specs/v<version>-signoff-attestation.md` respectively; never overwrite, never delete.
17. **All 33 launch gates require operator sign-off before v0.5 entry.** Hard gates green ≠ operator gates green. (§7.3a Phase 4 Q3.)

## 5. Phase-gate invariants

18. **No PM stage without bear-case present.** No conviction rollup without all 4 CDD-ensemble memos in place. No size without entry-check + premortem. (Section 7 PB sequencing.)
19. **Premortem cadence floors are hard.** Mode B = 180d, B' = 120d, C = 60d. Plus 4 event triggers (thesis-confirmation, consecutive M-2, auto-tighten threshold, mode reclass). Below-floor cadence is a violation. (`/premortem` spec.)
20. **Conviction rollup precedence: LOW > HIGH > MEDIUM.** LOW dominates when ≥2 NON-SURVIVOR matches in top-3, OR ≥2 kills fired, OR <3/5 debate. HIGH gate is monotonic: 4/5 debate AND 0 kills AND ≥2 SURVIVOR AND ≤1 anchor-drift channel. (Phase 4 Q2.)

## 6. Audit-loop invariants

21. **Two consecutive zero-bug audit passes = convergence.** Not one. (2026-04-29 convergence rule.)
22. **TIMESTAMP-WITHOUT-TIMEZONE in HMAC paths is a defect.** Use TIMESTAMPTZ; canonicalize all timestamps to UTC ISO-8601 before signing. (Audit pass 9 cluster.)
23. **Idempotency keys are required on every persistence path.** A retried INSERT must not double-count. (Audit pass 3 finding.)

---

## Evaluator behavior under this constitution

The `evaluator` agent treats every rule above as a hard gate (block release on violation) unless the rule explicitly says "soft signal." HG-1..HG-12 in `.claude/agents/evaluator.md` map onto rules 5–13 here; rules 1–4 + 14–23 are system-level invariants the evaluator surfaces via diagnostic but does not gate (because they're enforced upstream — at MCP-grant time, at HMAC-signing time, at migration time).

When the evaluator's verdict is `REJECT`, the returning subagent must cite which numbered rule was violated.

---

## Amendment process

Constitution amendments go through `/spec-approve constitution v<n>` with HMAC attestation. Append-only history in `docs/superpowers/constitution-changelog.md` (to be created on first amendment). v0 → v0.1 only after operator sign-off.
