# Decision-7 Sweep Set (derived artifact + execution record)

**Status:** EXECUTED 2026-05-26 via `git mv` to `archive/_retired/` (reversible — not `git rm`).
**Branch:** `refactor/plugin-restructure`.

This is the derived sweep set that BUILD_LOG decision 7 §"Implementation protocol" step 1
mandates ("Produce a derived sweep set as a separate review artifact … Operator reviews the
derived sweep before any removal runs"). It was produced by grep-tracing the `/research-company`
keep-set (commands → agents → MCP tool calls → Python imports → DB tables) and corrects decision
7's literal retire-set where the trace contradicts it.

The operator chose **archive (reversible `git mv`)** over decision 7's original `git rm`, so
everything below is moved under `archive/_retired/<original-path>` and recoverable with a single
`git mv` back. History is preserved (`git log --follow`).

## Keep-set corrections (decision 7's literal retire-set was stale / wrong)

The grep-trace found three modules decision 7 named for deletion that are **on the critical path**,
plus two that **post-date** decision 7 and are deliberate recent work. All five are KEPT:

| Module | Decision-7 said | Trace verdict | Why |
|---|---|---|---|
| `src/regime_sidecar/` | retire | **KEEP** | `src/p8_tactical_overlay/bin_classifier.py` calls `regime_sidecar.fred_client.resolve_latest_value_in_window` at runtime (risk-free-rate resolution in the tactical overlay) |
| `src/audit_trail/` | retire | **KEEP** | `src/p7_recommendation_emitter/emitter.py` has a top-level `from src.audit_trail.hmac_verify import …` (HMAC canonical-payload signing of `execution_recommendations`) |
| `src/mode_classifier/` | retire | **KEEP (soft)** | evaluator HG-26 Check 3 references `mode_classifier/adapters.py` output when a run carries `realized_vol_252d` |
| `src/eval/` | (not yet existed) | **KEEP** | P14 outer-ring scorer scaffold (commits `66ff39d`, `cb4e08f`) — newer than decision 7 |
| `src/p10_reversion_overlay/` + `mean-reversion-overlay` agent | (not yet existed) | **KEEP** | v0.4.0 standalone mean-reversion overlay (commit `caaf87b`) — newer than decision 7 |

## Keep-set (the `/research-company` + `/evaluate` surface)

- **Commands:** `research-company.md`, `evaluate.md` (`.claude/commands/`)
- **Agents (8):** quantitative-analyst, strategic-analyst, tactical-overlay, flow-overlay,
  mean-reversion-overlay, catalyst-scout, pm-supervisor, evaluator (`.claude/agents/`)
- **Python (`src/`, unchanged at repo root):** p8_tactical_overlay, p9_flow_overlay,
  p10_reversion_overlay, evaluator_gates, p7_recommendation_emitter, agent_harness, data_layer,
  regime_sidecar, audit_trail, evidence_index, mode_classifier, eval,
  mcp/{postgres, contamination_check, edgar, market_data, yfinance, polygon, macro_stack, fred, fundamentals}
- **scripts/** (kept), **`.claude/references/**`**, **db/**, kept **tests/**, **.mcp.json** (9 servers)

## Retire-set — archived to `archive/_retired/`

- **16 `src/` modules:** l4_daily_monitor, disposition_view, alert_channels, anchor_drift,
  premortem_scheduler, parameters_review, spec_approve, launch_confirm, backtesting, sizing,
  p3_mechanical_scorer, p4_debate, p5_watchlist, p6_disposition, watchlist, mcp/broker_mcp
- **22 commands:** ack, alerts, audit-trail, backtest, brief-delta-sweep, checkpoint, daily-monitor,
  disposition, entry-check, exit-check, grill-me, launch-confirm, macro-cycle, parameters-review,
  premortem, quarterly-reunderwrite, review-me, size, spec-approve, system-health, wash-sale-harvest,
  weekly-buildlog
- **Tests:** 16 `tests/unit/<module>/` dirs (matching the retired modules + `tests/unit/mcp/test_broker_mcp.py`);
  4 integration tests (test_e2e_integration, test_live_db_smoke, test_live_db_smoke_extended,
  test_mode_reclass_walkthrough); 3 regression tests (test_hmac_integration,
  test_timezone_dst_audit_regression, test_datetime_audit_regression). All archived tests
  exercise retired functionality (debate / watchlist / disposition / daily-monitor / anchor-drift /
  premortem / alert pipelines) — none cover a kept module's only test path.
- **2 one-off data scripts** importing retired modules: persist_watchlist_2026_05_06.py,
  update_scenario_a_canonical.py
- **Off-path UI/scaffolding:** dashboard/ (Vite research-dashboard), provider_verification/,
  root LivePanel.tsx

**Config side-effect:** the `broker` server was removed from `.mcp.json` (and from the gitignored
`.claude/settings.local.json` enable-list) because its implementation `src/mcp/broker_mcp/` is archived.

## Deferred — NOT touched this run

- **DB migrations.** Moving numbered `db/migrations/*.sql` files would break replay ordering, and
  dropping tables needs DB-state analysis + down-migrations. Note `system_errors` (mig 014) is still
  used by the pipeline's terminal-status path, so decision 7's "drop 014" is also wrong. Migration
  retirement is a separate, riskier follow-up requiring live-DB analysis.
- **Protocol consolidation of the `/research-company` flow** (deduping the repeated envelope-persist
  / PARAMETERS_USED / terminal-status / context-sidecar boilerplate). Operator chose "reorg only" —
  the flow spec is left byte-identical. This remains an available future refactor.

## Docs trim (2026-05-27)

Followed up by trimming `docs/` from 60 → 17 files (the other 43 `git mv`'d to
`archive/_retired/docs/`). The trim was driven by a reference trace, not by date: a doc was KEPT
only if a **live** consumer cites it — CLAUDE.md's reading order, a `.claude/agents/*` or
`research-company.md` authority citation, or a `src/`/`scripts/` provenance pointer.

**Kept (17, load-bearing):** `v2-final-spec.md`, `phasing-plan.md` (C3 thresholds), `v2-orchestrator-refactor-consensus.md`,
`high-4-enum-drift-consensus.md`, `implementation-sequencing.md`, `phase_gates.md`, `big-finance-comparison.md`,
`decision-7-sweep-set.md`, and under `superpowers/`: `specs/2026-04-29-empirical-foundation-design-v3.md`,
`specs/v3.1-stress-subtest-enum.md`, `specs/v3.1-signoff-attestation.md`, `specs/2026-05-07-flow-b-v1…-design.md`,
`specs/2026-05-23-ring-architecture….md`, `audits/2026-05-18-parameter-externalization…checklist.md`,
`consensus/2026-05-21-section2.1-label-vocabulary.md`, `plans/2026-05-21-section2-tactical-overlay-v3-final.md`,
`research/2026-05-22-step3…promotion.md`.

**Archived (43):** the section-1..8 consensus drafts + `phase_1_acceptance_spec`, all 10 launch-walkthroughs,
launch-readiness-log + operator-reference + v0.1-launch-readiness-audit, superseded plans/specs
(eval-loop create/delete designs, v3.0-signoff, v3.1-frameworks-cited-migration, two superseded plans),
the phase5a postmortem, two research notes, two GOOGL sweep docs, `constitution.md`, `ecosystem-patterns`,
`g_check_4_verification_spec`, `parameter-review-queue`, `harness-reference`, `tier4-deferred-work*`,
and the two bug3/calibration-overlay consensus notes.

**Why not "remove all of docs/" (operator's initial hypothesis):** BUILD_LOG *points to* `docs/` for
canonical substance (C3 thresholds in `phasing-plan.md §2.5`, DDL/gate-criteria in `v2-final-spec.md`,
the v3 design spec) rather than reproducing it, and CLAUDE.md + ~40 live agent/`src` citations resolve
into the kept subset — so a wholesale removal would break the documented authority chain.

Residual cosmetic dangling pointers (content preserved in `archive/`): BUILD_LOG/README historical-narrative
mentions of `harness-reference`/`tier4-deferred-work`/`operator-reference`/`launch-readiness-log` (left as
written-time-accurate history). The two *current* module READMEs (`src/eval/`, `src/mcp/fundamentals/`)
were repointed to their `archive/_retired/docs/…` locations.

## Reversal

`git mv archive/_retired/<path> <original-path>` restores any item; `git log --follow` preserves
history across the move. Re-add `broker` to `.mcp.json` if `broker_mcp` is restored.
