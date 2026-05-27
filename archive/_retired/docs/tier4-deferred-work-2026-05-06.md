# Operator-Action Items After 2026-05-06 v3 Implementation Audit

Per the v3 audit ran 2026-05-06 ([audit transcript see end of session]), 7 operational defects were identified. **#1 fixed in this session** (Channel 2 anchor-drift adapter). The remaining 6 items either require operator decisions, substantial authoring, or are correctly-deferred per spec §8.1 / §6.4.

## Closed in this session

### #1 Channel 2 anchor-drift fundamentals adapter — FIXED

- **Was**: `_default_fundamentals_fn` imported non-existent `mcp_clients.fundamentals`; silently returned `no_actuals` for every production call.
- **Now**: Migration `026_latest_actuals.sql` creates a Postgres-backed cache table; `_default_fundamentals_fn` queries it. Cache populated for all 10 watchlist tickers; UPDATE script `scripts/update_scenario_a_canonical.py` reconciled `scenario_A_base_projections` schema (added canonical `revenue/gross_margin/fcf` top-level keys + re-signed HMAC).
- **Verified**: Channel 2 now fires correctly — AMZN (85% FCF gap), MSFT (31%), ORCL (147%), VRT (32%). Bear thesis on AI-capex names automated.

## Requires operator decision

### #2 `broker_mcp` Schwab adapter — Gate.io scope mismatch

- **Spec contract**: §3.1 + §7.1 hard-gate #2 + §7.3 sign-off #3 + §7 Q5 + §4.6 all assume conventional broker MCP (Schwab default) at v0.1 launch.
- **Reality**: Operator's account is on Gate.io (tokenized US equities); Schwab adapter built (~25 tests) but not in live launch path.
- **Required action**: Run `/spec-approve 3.1` with explicit amendment removing broker MCP from v0.1 hard gates OR commit to Schwab as a parallel custodian. Without amendment, the audit's "32/32 green" claim has a silent gate-count reduction (33→32) that's not in the spec text.
- **Impact if deferred further**: Audit trail integrity — the spec says one thing, the launch posture another. PMSupervisor input rules may interact incorrectly with this divergence under v1.0 real-money execution.

### #3 `mcp__fundamentals` MCP server — Sharadar subscription needed

- **Spec contract**: §3.1 lists `mcp__fundamentals__*` as a v0.1 dependency for PIT XBRL fundamentals.
- **Reality**: Stub server raises `NotImplementedError`. Workaround in this session: cached TTM data in `latest_actuals` manually populated from prior research.
- **Required action**: Operator subscribes to Sharadar (estimated $200/mo); credentials added to `.env` (`SHARADAR_API_KEY`); stub replaced with live adapter at `src/mcp/fundamentals/server.py`.
- **Impact if deferred further**: Channel 2 is currently fed manual cache (this session); refresh requires re-running the UPDATE pattern. P3 Stage 1B per-share-value computations remain degraded. Sharadar PIT is materially better than EDGAR XBRL for backtest validity (PIT-as-of-published vs as-restated).

### #4 Pre-loaded scenario template library — ~65 templates not present

- **Spec contract**: §4.2 calls for ~25 durable + ~15 new + ~25 discredited scenario kill-criterion templates pre-loaded at v0.1 launch.
- **Reality**: No template-library file in `.claude/references/` or `src/`. Scenario population is operator-driven post-launch.
- **Required action**: Either (a) author the 65 templates as a one-time content-authoring sprint (~2-4 weeks operator effort) OR (b) defer to v0.5+ explicitly via `/spec-approve` amendment.
- **Impact if deferred further**: Operator-driven scenario authoring is feasible at v0.1's small watchlist (10 names) but doesn't scale to v0.5's larger universe. The templates' main value is consistency across tickers and avoiding scenario-quality regression as more names are added.

### #6 4/10 §7.3a walkthrough gates — narrative-only, no reproducer tests

- **Spec contract**: §7.3a treats all 10 walkthroughs as HMAC-attested launch gates with reproducer tests.
- **Reality**: 4 are documented narratives only — `override-rate-50`, `catalog-reclass-ripple`, `broker-mcp-outage`, `phase-c-judge-silent-miss`.
- **Required action**: Either (a) author the 4 missing reproducer test files (each ~200-500 lines) OR (b) `/spec-approve` amendment formally downgrading these 4 to "spec-narrative" tier.
- **Impact if deferred further**: Audit-trail integrity again. Sign-off claimed gates that don't have reproducers; future regression doesn't have automated detection for these scenarios.

## Correctly deferred per spec — NO action needed

### #5 `parameters_review` read-only — DEFERRED v0.5+ per §8.1

Spec §8.1 explicitly defers the proposal-generation flow ("calibration haircut applied at v0.5+"). Read-only summary stub at `src/parameters_review/cli.py` is the correct v0.1 surface. **Dismiss.**

### #7 NTFS uses CMT 2y3m slope proxy — DEFERRED v0.5+ per §6.4

Spec §6.4 lists "MSGARCH (R) production-grade vol-regime detection" and Engstrom-Sharpe NTFS as v0.5+ upgrade paths. Migration 021 renamed the CMT-proxy column appropriately and documented the divergence. **Dismiss.**

## Action priority for operator

| Priority | Item | Effort | Required by |
|---|---|---|---|
| HIGH | #3 Sharadar subscription | $200/mo + 1 day wiring | Continued Channel 2 freshness; v0.5+ calibration |
| MEDIUM | #2 `/spec-approve` amendment for broker_mcp | 30 min operator review | Spec-vs-launch consistency |
| MEDIUM | #6 Author 4 reproducer tests | 2-4 days engineering | Walkthrough gate integrity |
| LOW | #4 Author 65 scenario templates | 2-4 weeks content | v0.5+ scaling |

Items #5 and #7 require no action.
