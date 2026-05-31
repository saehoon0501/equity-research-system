# Implementation Plan — walkforward-tuning-loop

Markdown orchestrator (`.claude/commands/walkforward-tune.md`) + pure leaf helpers in `src/skills/walkforward_tune/` (first resident of `src/skills/`) + an HG validator + migration 053 + tests. **Consumes** `reactive-replay-harness` (`replay_candidate(candidate, window) -> ReplayResult`, importing its `OutcomeRecord`/`ReplayResult`/`ReplayWindow`/`Candidate` — no re-declaration). Strict left→right dependency: `types → {read, fit, cpcv, metric, gate, publish, audit}`; `metric` imports `calibration`; no leaf imports another leaf.

Build order: inner ring first (P14). `types.py` is the load-bearing barrier — every cross-leaf shape (`OOSSample`, `OOSMatrix`, `GateVerdict`, `Partition`, `TrialSet`, `ReadSet`, `TunerActionAudit`, `GateParams`, `Event`) is pinned there before the leaf fan-out, so the parallel leaves cannot diverge on shape.

- [x] 1. Foundation: owned contract types + audit migration

- [x] 1.1 Owned in-memory contract types (`types.py`) — the dependency-root barrier
  - `src/skills/walkforward_tune/types.py`: frozen dataclasses for every walkforward-owned cross-leaf shape — `ReadSet` (firewalled trace slice + drained events), `TrialSet` (≥2 `Candidate`s + trial metadata for effective_N), `Partition` (CPCV split; carries/derives a `ReplayWindow` OOS span), `OOSSample` (one config×partition: survival-net return + skew + kurtosis + n_obs), `OOSMatrix` (per-config×per-partition `OOSSample`s for the trial set + incumbent + trial metadata), `GateParams` (DSR/PSR/MinTRL/PBO/MinBTL/decision-rule knobs), `GateVerdict` (promote/selected_config/reasons/dsr/psr/min_trl_met/pbo/effective_n/lexicographic_ok), `TunerActionAudit` (the 9-field audit row), `Event` (drained event)
  - **Import — do NOT re-declare** `OutcomeRecord`, `ReplayResult`, `ReplayWindow`, `Candidate` from `src.reactive.replay` (the consumed `reactive-replay-harness` contract); reuse `Label` from `src.calibration.scorer` (P9)
  - Pin `OOSSample` fields precisely — `metric` produces them and `gate` consumes them via `OOSMatrix`; this is the shape contract the parallel leaves must not diverge on
  - Observable: pure stdlib+typing module; imports clean; `get_type_hints` resolves on every dataclass; `OutcomeRecord`/`ReplayResult`/`ReplayWindow`/`Candidate` are imported (asserted) not redeclared; no leaf/consumer-spec import
  - _Requirements: 4.5, 8.1, 10.3_
  - _Boundary: types_

- [x] 1.2 (P) Migration 053 — `walkforward_tuner_audit` append-only table
  - `db/migrations/053_walkforward_tuner_audit.sql`: table per the Data Models DDL (audit_id PK, run_id, code_version, param_version, walk_forward_window nullable, promoted, track, gate_metrics JSONB, hypothesis JSONB, created_at); all columns immutable
  - Append-only guard: BEFORE UPDATE/DELETE row trigger + BEFORE TRUNCATE statement trigger sharing one RAISE function (mig 003/048 pattern); claims number **053** (verified free — 054 taken by in-session-monitor)
  - Observable: applying the migration creates the table + triggers; an UPDATE/DELETE/TRUNCATE raises; the 4 correlation keys are present for joinability
  - _Requirements: 8.1, 8.4_
  - _Boundary: db/migrations_

- [x] 2. Core compute leaves (pure; parallel after types)

- [x] 2.1 (P) CPCV partition scheme (`cpcv.py`)
  - `make_partitions(history, n_groups, k_test, embargo) -> list[Partition]`: combinatorial purged cross-validation — purge label-overlapping observations + embargo after each test block (the leakage-firewall realization, R2.2/2.3); each `Partition`'s OOS span maps to a `ReplayWindow`. Pure, no I/O
  - Observable: purge removes label-overlapping observations; embargo follows each test block; **no OOS observation appears in the matching IS set** (assert the firewall property); deterministic
  - _Requirements: 2.2, 2.3, 4.1_
  - _Depends: 1.1_
  - _Boundary: cpcv_

- [x] 2.2 (P) Survival-net metric + calibration (`metric.py`)
  - `score(outcome_records: list[OutcomeRecord]) -> OOSSample`: survival-net risk-adjusted return reflecting §13 (survival breaches / stop-outs dominate the ranking) + calibration (Brier/reliability via `src/calibration/metrics.py`), computed over the harness's `OutcomeRecord`s — **NOT the `counterfactual_ledger`**. Pure
  - **Tests MUST construct the real `src.reactive.replay.types.OutcomeRecord` frozen dataclass (all 9 fields), not a loose dict/fake** — the unit-green/integration-broken trap class; the metric reads `realized_outcome`/`survival_events`/`predicted_probability`/`realized_label` off the real shape
  - Observable: survival-net metric reflects the §13 ordering (a survival breach dominates an edge gain); calibration delegates to `calibration.metrics`; computed over real `OutcomeRecord`s
  - _Requirements: 4.3, 4.4_
  - _Depends: 1.1_
  - _Boundary: metric_

- [x] 2.3 (P) Deterministic promotion gate (`gate.py`) — the statistical crux
  - `evaluate_gate(matrix: OOSMatrix, params: GateParams) -> GateVerdict`: select the highest survival-net config from the trial set, then run IN ORDER — PSR/MinTRL sufficiency (skew/kurtosis-aware, vs a non-trivial benchmark Sharpe) → DSR + PBO/CSCV (overfitting-corrected; deflate by `effective_N`; MinBTL caps trial-set breadth to available history) → decision-rule (margin / consecutive partitions / anti-churn hysteresis) → §13 lexicographic guard. Pure + deterministic; no I/O, no LLM; never consults IS-Sharpe (5.5); any insufficiency/degeneracy ⇒ `promote=false` (P7)
  - **Formula correctness is self-test-proof (Bailey–López de Prado, no repo precedent): tests must anchor to values EXTERNAL to the implementer — at least one hand-computed reference value per statistic (DSR, PSR, MinTRL, PBO) + the invariant properties below; cite the source formula in comments** (the reviewer verifies formula-vs-source, not just self-consistency)
  - Observable: selects the highest survival-net config; **DSR falls as trial count rises** (the deflation — more trials ⇒ harder to promote); **a degenerate trial set (N=1) ⇒ no-promote** (not a spurious pass); **PSR falls with negative skew / fatter tails while MinTRL rises** (Bailey–López de Prado source; corrected 2026-05-31 after external formula verification — the prior "rises" wording was inverted, the gate code follows the source); **IS-Sharpe never changes the verdict**; insufficient-data ⇒ no-promote; §13 guard rejects an Edge/Return gain that lowers Survive/Preserve; identical inputs ⇒ identical verdict
  - _Requirements: 4.5, 5.1, 5.2, 5.3, 5.4, 5.5, 6.2, 6.3_
  - _Depends: 1.1_
  - _Boundary: gate_

- [x] 2.4 (P) Trial-set assembly (`fit.py`)
  - `assemble_trial_set(proposed_configs, base, memory) -> TrialSet`: validate LLM-proposed `ParamSnapshot`/`SurvivalParameters` configs against their pinned shapes; apply rolling (edge/return) vs anchored (tail/risk) in-sample memory; produce one hashed `Candidate` (with a `param_version`) per config. The trial set must be non-trivial (≥2 configs) so the gate's deflation is non-degenerate. The *judgment* (which configs / the falsifiable hypothesis) is the orchestrator's LLM step — this leaf is the deterministic assembler; code candidates are produced by the orchestrator, not here. Pure
  - Observable: produces a non-trivial trial set (≥2 configs); rolling vs anchored windowing applied; rejects shape-invalid configs; deterministic per-config hash
  - _Requirements: 3.1, 3.2, 3.4, 3.5_
  - _Depends: 1.1_
  - _Boundary: fit_

- [x] 2.5 (P) Firewall-bounded read + event drain (`read.py`)
  - `read_firewalled(keys, is_boundary, conn=None) -> ReadSet`: wraps `reader.query_trace(filters={..., 'until': is_boundary})` (model trace for behavioral analysis); `drain_events(conn=None) -> list[Event]`: `SELECT … execution_daemon_event_queue WHERE drained_at IS NULL` → process → `UPDATE … SET drained_at=NOW()`, surfacing anomaly events (safe_mode/kill_switch/lifecycle) for the fit (R10.5). **Does NOT read `counterfactual_ledger`** and does NOT fetch replay inputs. `conn=None` dry-run supported
  - Observable: firewall predicate excludes `event_ts > is_boundary` (no OOS leak into the read); drain marks `drained_at`, idempotent (re-drain returns nothing); dry-run path touches no DB
  - _Requirements: 2.1, 10.1, 10.2, 10.5_
  - _Depends: 1.1_
  - _Boundary: read_

- [x] 3. Handoff, audit, and validator

- [x] 3.1 (P) Version publish + IS-boundary advance (`publish.py`)
  - `publish(...)` on a promote verdict: write validated values into `parameters` rows (reactive + survival namespaces) so `parameters_active` resolves to them (5.7: paper-track only while paper-phase); stamp the advanced `walk_forward_window` label so the daemon re-sources it at next hot-swap (7.3, 1.4). **Never** deploys/hot-swaps (7.2). Idempotent on `run_id`. `conn=None` dry-run
  - Observable: a promote writes resolvable `parameters_active` rows + stamps the boundary label; re-running the same `run_id` is idempotent; no deploy/hot-swap path; dry-run touches no DB
  - _Requirements: 1.4, 5.7, 7.1, 7.2, 7.3_
  - _Depends: 1.1_
  - _Boundary: publish_

- [x] 3.2 Tuner-action audit assembly + append-only write (`audit.py`)
  - `write_audit(audit, conn=None) -> dict`: assemble the audit envelope — gate metrics (derived, P15), the **falsifiable** promotion hypothesis + observable falsifiers, the four correlation keys — persist append-only to `walkforward_tuner_audit` (mig 053) + `memos/envelopes/walkforward-tune__<run_id>.json` (P4). Emitted on **both** promote and decline (8.1). `conn=None` dry-run
  - Observable: a row is appended on promote AND on decline; the envelope carries derived gate metrics + falsifiable hypothesis + the 4 keys; dry-run writes the envelope but no DB row
  - _Requirements: 8.1, 8.2, 8.3_
  - _Depends: 1.1, 1.2_
  - _Boundary: audit_

- [x] 3.3 HG validator for the audit envelope (`tuner_action_audit_shape.py` + registry)
  - `src/eval/gates/tuner_action_audit_shape.py`: `validate_tuner_action_audit(env) -> TunerActionAuditResult` enforcing envelope shape + the **P15 falsifiability/derived-metrics check** + the 4 correlation keys; register `artifact_type="tuner_action_audit_envelope"` in `src/eval/gates/_registry.py` (data-only edit). Realizes R6's evaluator obligation
  - Observable: rejects an envelope missing any of the 4 keys / the hypothesis / the falsifiers / derived gate metrics; registered in the gates `REGISTRY` and discoverable by artifact_type
  - _Requirements: 8.4, 6.1_
  - _Depends: 1.1, 3.2_
  - _Boundary: src/eval/gates_

- [x] 4. Orchestrator + validation

- [x] 4.1 Cycle orchestrator (`.claude/commands/walkforward-tune.md`)
  - NEW markdown slash command: cycle control flow (read firewalled trace + drain → LLM fit propose trial set → CPCV partition + **call `replay_candidate` per config per partition** + thread `OutcomeRecord`s into `metric` → gate select-best+deflate → publish on promote + advance boundary → emit audit on promote/decline); firewall enforcement; checkpoint/resume per `run_id` (R9.1); code-track full-inner-ring gate (6.1); kill-switch (5.6); adopts `/research-company` conventions (run_id P3, PARAMETERS_USED P2, envelope persistence P4, halt-and-degrade, `post_agent_validate.sh`/`orchestrator_step.py` cost/retry)
  - **REVIEWED, not unit-tested** — LLM-executed control flow; its coverage is review + the 4.2 leaf-wiring E2E (which does NOT exercise the markdown path); the live slash-command path is LLM-in-the-loop (out of scope here)
  - Observable: the command file exists with all 7 cycle phases, firewall/gate enforcement, checkpoint/resume, and the consumed-`replay_candidate` call documented; references only leaves + the harness contract (no forbidden imports)
  - _Requirements: 1.1, 1.2, 1.3, 3.3, 5.6, 6.1, 9.1, 9.2, 9.3_
  - _Depends: 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3_
  - _Boundary: orchestrator_

- [x] 4.2 E2E cycle test (Python leaf-wiring, stub harness) — the conservative decline path
  - `tests/unit/skills/walkforward_tune/test_e2e_cycle.py`: seeded `read → fit → CPCV partition + stub `reactive-replay-harness` replay → metric → gate **decline** (MinTRL not met) → audit `insufficient_oos`, incumbent retained` — composing the leaves directly with a stub `replay_candidate` (the orchestrator↔harness wiring: calls replay per config per partition, threads returned `OutcomeRecord`s into metric). The conservative path, most important to prove first (P7)
  - Observable: the E2E asserts the decline→`insufficient_oos`→incumbent-retained path end-to-end through the leaves with a stub harness; no live MCP/DB/LLM
  - _Requirements: 1.1, 4.1, 5.4, 8.1, 9.1_
  - _Depends: 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2_
  - _Boundary: tests_

- [x] 4.3 Integration test (`integration_live`) — migration guard + publish round-trip
  - `tests/integration/test_walkforward_tuner_audit_migration.py`: mig 053 guard rejects UPDATE/DELETE/TRUNCATE; an audit row joins to a seeded `decision_process_trace` row by the 4 keys; publish round-trip writes resolvable `parameters_active` rows + stamps the boundary label (dry-run + live). Marked `integration_live` (auto-skips without `-m` + live DB)
  - Observable: `pytest -m integration_live` exercises the guard + the 4-key join + publish round-trip against a live DB, or auto-skips cleanly without one
  - _Requirements: 7.1, 7.3, 8.1, 8.4_
  - _Depends: 1.2, 3.1, 3.2_
  - _Boundary: tests_

## Implementation Notes
- Consumed contract (landed, verified 2026-05-31 in this worktree): `src.reactive.replay.harness.replay_candidate` + `src.reactive.replay.types.{OutcomeRecord(9 fields),ReplayResult,ReplayWindow,Candidate}`. `OutcomeRecord` fields: period, symbol, decision, predicted_probability, fills, total_return_pnl, survival_events, realized_outcome, realized_label. Import, never re-declare (design Allowed Dependencies).
- Migration **053 is free** (049–052 + 054 taken; 053 unclaimed). mig 051 `execution_daemon_event_queue` + `drained_at` are LANDED (was DESIGNED) — the drain contract is real.
- Reuse: `src/calibration/metrics.py` (Brier/reliability), `src/calibration/scorer.py` (`Label`). P2 machinery: `parameters`/`parameters_active`/`run_parameters_snapshot` (mig 034).
- **Gate (2.3) is the risk locus** — DSR/PSR/MinTRL/PBO/MinBTL formula correctness is self-test-proof; anchor tests to hand-computed reference values + invariant properties + formula-vs-source comments; the reviewer must verify formulas against the Bailey–López de Prado source, not just that tests pass.
- **Metric (2.2) must use the real `OutcomeRecord`** in tests (frozen dataclass from `src.reactive.replay.types`), not a fake — the unit-green/integration-broken trap.
- The markdown orchestrator (4.1) is reviewed, not unit-tested; do not report it as "tested."
- venv: provision like RRH's `.venv-replay` — needs `httpx` (RRH `data_client` imports it at module load), `psycopg`, `numpy` (+ `scipy` if the gate uses `scipy.stats` for the normal CDF / skew-kurtosis terms — prefer a small in-module implementation to keep the inner ring lean), `pytest`, `python-dotenv`. Built in `.venv-wf` (psycopg+httpx+numpy+pytest+dotenv); gate uses an in-module normal-CDF/moments (no scipy).

## Implementation Notes (build close-out 2026-05-31)
- **All 13 sub-tasks implemented + APPROVED** via a staged workflow (types barrier → parallel leaves+migration → audit→validator → orchestrator+integration), each with an independent kiro-review pass; 191 pure-unit leaf tests green in `.venv-wf`; `integration_live` (4.3) auto-skips by default (6/6 pass against the live DB). Markdown orchestrator (4.1) is review-only (not unit-tested).
- **GATE INVARIANT PROSE WAS INVERTED (corrected 2026-05-31).** The 2.3 observable + design.md Testing-Strategy bullet originally said "DSR rises with trial count / PSR rises with negative skew." An independent formula-verifier recomputed external Bailey–López de Prado anchors (PSR 0.8389490, MinTRL 13.174945, DSR 0.95780, PBO 0.0/⅓) and proved `gate.py` matches the SOURCE to ~1e-12: **DSR falls as N rises (deflation); PSR falls with negative skew / fatter tails; MinTRL rises.** The implementer correctly followed the source over the inverted prose; the gate code + its tests are correct. Prose fixed in both docs. Lesson: BLdP stats are self-test-proof — verify formulas against the published source + hand-computed anchors, never trust self-consistent unit tests.
- **2.5 read.py — drain commit-boundary bug, caught + fixed.** The workflow LOST 2.5's review (impl agent didn't emit StructuredOutput; files landed on disk + green). An independent re-review caught that the drain `UPDATE … SET drained_at=NOW()` ran with NO `conn.transaction()`/commit (unlike sibling write-leaves publish/audit) — on a non-autocommit connection it rolls back at connection close, re-draining the same rows next cycle → R10.2 idempotency defeated at runtime, invisible to fake-based tests. Fixed: wrapped the UPDATE in `with conn.transaction():` + added `test_drain_events_commits_the_watermark_in_a_transaction` (asserts commit; non-vacuous).
- **HG-41** registered for `tuner_action_audit_envelope` (additive edits to `src/eval/gates/{__init__,_fingerprints,_outcome,_registry}.py`, +70 lines, no logic change). The 5 failing `tests/unit/eval/gates/test_envelope_shape.py` are PRE-EXISTING `pm_supervisor`/`decision_cell_matrix` contract drift in another spec — unrelated to walkforward (143 gates tests pass incl. the new validator).
- Non-blocking carryforwards: 1.1 reviewer suggested locking `GateParams.benchmark_sharpe` (done in 2.3); fit's param-hash payload is a hardcoded field list (R10.4 revalidation risk if `ParamSnapshot` gains a knob); code-track deploy mechanics remain the execution-daemon seam (v0.1 = param track + code-candidate production/gate/audit).
