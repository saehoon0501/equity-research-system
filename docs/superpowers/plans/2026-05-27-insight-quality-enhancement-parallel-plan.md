# Insight-Quality Enhancement — Final Parallel Implementation Plan

> Branch: `feature/insight-quality-enhancement` · Grounded 2026-05-27 via a 5-thread uncertainty-resolution loop + a 6-lens SE review, both primary-source/repo verified.
> **Status: FINAL (rev 2).** Rev 1 absorbed all 8 showstoppers (S1–S8) + SE-review corrections. **Rev 2 (2026-05-27)** fixes the 10 code-review findings: migration-number collision (→045; 014 and 044 already taken), gate-registry depth (per-artifact `_validate_*` bodies, not just the top dispatcher), reversion-contract reuse (only the envelope module is missing), cache-key seed dimension, horizon column naming (`t_plus_1y` not `365`), the false `correlation_mod`/`liquidity_mod` reuse premise, and several previously-unfalsifiable criteria (κ baseline, evidence producer audit, hook matcher, WS-5 quality metric, ESCALATE threshold, key-rotation verification).

## Context

The pipeline's agents/overlays produce signals and briefs but have **no automatic measure of insight quality** and several ungrounded design choices. This plan adds an autonomous (no human in-loop per run) scoring + gating layer and corrects four grounded findings, reusing existing infrastructure wherever it exists. The one accepted human touchpoint is a **one-time frozen anchor set** (judge calibration fixture) — not an in-loop reviewer.

The SE review found the original "Phase 0 is the only blocker / disjoint ownership" model was false in three places (shared `evaluator_gates/__init__.py`, `additionalProperties:false` envelopes, undeclared WS-3→WS-4 edge) and that several enabling pieces (evidence persistence, calibration columns, LLM replay cache, model knob, CI) don't exist. **Phase 0 is expanded accordingly.**

## Engineering decisions locked for this plan (previously open)

| Decision | Value |
|---|---|
| BoN-MAV candidate count `N` | **5** (cap ≤5), matching the existing `SELF_CONSISTENCY_N=5` precedent |
| Verifier/judge model vs producer | **Different model than the producer** (synthesizer `opus` → verifier/judge `sonnet`). True cross-vendor is a documented upgrade path; same-vendor still cuts self-preference. |
| Self-consistency N for scorers | **5 @ temp 0.7, median**, reusing `stage2_llm_rubric.py`; runs **first-pass only**, not on retries |
| Conformal target / min calibration | **α = 0.10 (90% coverage)**; **abstain wholesale below 100 calibration points** |
| Brier/log-loss CI | **block bootstrap**, block size 5, **1000 reps, 95% CI** (report width; monitoring, not a hard gate) |
| Directional-ECE pass | reliability-curve slope within **[0.8, 1.2]** (display-only, never headline) |
| Per-envelope scoring latency | **regression if > 1.5× rolling-median** baseline (relative, not absolute) |
| Per-pass cost cap (WS-5) | **≤ $15/pass** (N+1 calls), distinct from the $60 per-attempt retry ceiling; candidate+verifier usage summed into one `attempt_cost_usd` |
| Calibration acceptance | **backfilled-history only** (live calibration is post-ship monitoring, not a project gate) |
| WS-7 coverage gaps | **deferred to optional Phase 3** (not on the critical path) |

## Reuse map (verified — do NOT rebuild)

| Need | Reuse | Path |
|---|---|---|
| Gate registry + result-dataclass pattern, `validate_all()` | extend (after P0-4 registry refactor) | `src/evaluator_gates/__init__.py`, `envelope_shape.py` |
| Retry/cost state machine | plug new gates in | `src/agent_harness/orchestrator_step.py`, `scripts/post_agent_validate.sh` |
| LLM-judge output schema + confidence | pattern for advisory judge | `src/p4_debate/phase_c_judge.py` |
| Rubric scoring w/ self-consistency N=5 | pattern for scorers | `src/p3_mechanical_scorer/stage2_llm_rubric.py` |
| Placeholder Label→Verdict scorer | **replace** | `src/eval/scorer.py` |
| Outcome table (columns `t_plus_{30d,90d,1y}_return` + `delta_vs_benchmark_*`) | reuse; extend via migration **045** | `db/migrations/013_v3_calibration_capture.sql` |
| Conviction [0,1], write-back seam (`DEFAULT_COMPONENT_WEIGHTS`) | calibration target | `src/p7_recommendation_emitter/continuous_conviction.py` |
| Overlay classifiers | wrap outputs, don't fork | `src/p8_tactical_overlay/…::classify`, `p9_flow_overlay/…::classify_flow`, `p10_reversion_overlay/…::classify_reversion` |
| Return/percentile utils | reuse | `src/backtesting/framework.py`, `src/mcp/market_data/server.py`, `src/l4_daily_monitor/drift_detector.py::_percentile` |
| `reasoning_path_taken` opcode enum | extend with `reasoning_trace` | `src/agent_harness/envelopes/*.py` |
| `(model_id, model_version)` pinning convention | mirror into envelopes | `db/migrations/013` (`debate_consensus_history`) |
| Seed precedent | mirror | `src/backtesting/framework.py`, `src/regime_sidecar/bma.py` |

## Parallelization model

```
Phase 0 ─ EXPANDED CONTRACT FREEZE (blocking, single owner) ─┐ unblocks all
   ┌──────┬──────┬──────┬──────┬──────┬─────────────────────┘
   ▼      ▼      ▼      ▼      ▼      ▼
  WS-1   WS-2   WS-3   WS-4   WS-5   WS-6     ← Phase 1 parallel (WS-3 coverage-gate waits on WS-4)
   └──────┴──────┴──────┴──────┴──────┴────┐
                                           ▼  Phase 2 — INTEGRATION + E2E + CI gates
                                           ▼  Phase 3 — OPTIONAL coverage gaps (WS-7)
```

Success = falsifiable by an automated test. "Looks better" is never a criterion.

---

## Phase 0 — Expanded contract freeze (BLOCKING, single owner)

Each deliverable below resolves a specific showstopper (S#). All must land before Phase 1 starts.

**P0-1 — Envelope schema extension (+ the `additionalProperties` trap, S2).** Add `reasoning_trace:[{op,rationale}]` (1:1 with `reasoning_path_taken`), `axis_a`, `axis_b`, `gate_decision`, and the calibration emission block to every module in `src/agent_harness/envelopes/*.py`. **Critically, add the new keys to `properties` of the `additionalProperties:false` schemas (`flow.py:94`, `tactical.py:69`) — that is the actual S2 fix** (verified in impl: the splice `SCHEMA["properties"].update(insight_quality_properties())`). *Correction (verified 2026-05-27): `envelope_shape.py` (HG-23) uses `REQUIRED_TOP_LEVEL` + a `FORBIDDEN_TOP_LEVEL` deny-list, NOT a closed allowlist, and has no `additionalProperties:false` — so it needs no change; just keep the new keys OUT of `REQUIRED_TOP_LEVEL` (adding them breaks backward-compat) and absent from `FORBIDDEN_TOP_LEVEL`.* Add the missing `src/agent_harness/envelopes/reversion.py` module **reusing the contract that already exists** (`ReversionSignal` in `p10_reversion_overlay/contracts.py`, HG-36 `reversion_envelope_shape.py`, `_validate_reversion_envelope` @ `__init__.py:716` — do NOT recreate these) and **wire mean-reversion-overlay into pm-supervisor as a soft-modulator (required, not optional)** so WS-3's p10 wrap has a real consumer.
- [ ] New fields **validate** (not merely "old tests still green") on flow + tactical envelopes; HG-23 no longer flags them as forbidden.
- [ ] `len(reasoning_trace)==len(reasoning_path_taken)` on a smoke run for every agent.
- [ ] `agent_harness/envelopes/reversion.py` exists and reuses the existing `ReversionSignal`/HG-36 contract (no duplicate contract); pm-supervisor reads the mean-reversion envelope as a named soft-modulator consumer.

**P0-2 — Migration `045_calibration_resolver.sql` (S4).** (Number is **045** — both `014_v3_system_health.sql` and `044_eval_loop_dead_path_removal.sql` already exist; highest current migration is 044. Re-verify against `db/migrations/` before writing.) Add `label_binary`, `excess_return`, `label_method_version`, a `primary_horizon` enum **whose values map 1:1 to the existing columns** (`30d`→`t_plus_30d_return`, `90d`→`t_plus_90d_return`, `1y`→`t_plus_1y_return`; "1y" = the 365-calendar-day window already used by mig-013's resolver query), and a **write-once emission snapshot** carrying `continuous_score`, `p_beat_benchmark`, `model_version` (so Brier labels are reproducible). Keep `recommendation_outcomes` STATE-guards (only `t_plus_*` mutable).
- [ ] Migration number is unused (verify against `db/migrations/` before writing); schema migrates cleanly; emission snapshot is write-once (assert second write rejected).
- [ ] `primary_horizon` joins to the matching `t_plus_*_return` column (assert the join resolves; no `t_plus_365` reference anywhere).

**P0-3 — Evidence persistence (S1, highest-risk).** Two halves, BOTH required: (a) Add `evidence_documents(evidence_id FK, source_uri, raw_text, fetched_at, content_hash)` and make `src/mcp/{edgar,market_data,fundamentals}/server.py` persist fetched bodies keyed to `source_uri` at fetch time; (b) **close the producer gap** — every agent that emits `evidence_index_refs` must actually `INSERT` the claim rows into `evidence_index` during a run.
- [ ] After a sample run, `evidence_documents` holds the source text for every `evidence_index_ref`, and a scorer can fetch the grounding passage by ref.
- [ ] **Producer audit (half b):** enumerate the agents that emit `evidence_index_refs`; assert each one INSERTs the rows it references during a run (no agent emits a ref it didn't insert) — so WS-1 faithfulness/citation-P/R never scores against empty grounding.

**P0-4 — Gate-registry refactor (S3).** Convert BOTH layers: (a) `validate_all`'s top-level `if/elif` artifact dispatcher + flat `GATE_IDS`, AND (b) the **hardcoded gate-run lists inside each `_validate_*` body** (`_validate_pm_envelope` @ `__init__.py:471`, `_validate_reversion_envelope` @ `:716`, etc.) into a **per-artifact gate registry**. Without (b), WS-6 still has to edit the `_validate_*` bodies — the same regions P0-1's HG-23 edit touches — and the parallel claim fails.
- [ ] A new gate registers by appending to a registry entry only; **neither `validate_all` nor any `_validate_*` body is edited** when adding it. (This is the precondition for WS-6 to run collision-free with Phase 0.)

**P0-5 — LLM response-replay cache + model pinning (S5).** Add a cache keyed `(model_version, prompt_sha, temperature, max_tokens, sample_index)`. The **`sample_index` dimension is required** so self-consistency's N=5 temp-0.7 samples each cache as a distinct entry rather than collapsing to one (which would degenerate the median and trip spurious cache-miss failures). Pin the **resolved** model id (not alias) into every envelope's `model_version`.
- [ ] CI replays scorer/judge calls from cache; a cache miss **fails** the run.
- [ ] An N=5 self-consistency call produces **5 distinct cache entries** (assert), and its stored median is recomputed deterministically from them.
- [ ] Envelope `model_version` is a resolved id; CI asserts effective model == pinned.

**P0-6 — Model-selection mechanism (S6).** Add a per-agent header field (`verifier_model`, `judge_model`) read by the dispatch path; default producer `opus`, verifier/judge `sonnet`.
- [ ] A designated agent dispatches on a non-opus model (assert effective model ≠ producer).

**P0-7 — `market_data` PIT + total-return fix (S8).** Add an `as_of`/raw-unadjusted mode to `get_prices`; compute **dividend-inclusive total return** (reconstruct from the Massive dividends endpoint, or route the resolver's `adj_close` to a total-return source); fix the `adj_close = c` split-only mislabel in `polygon_provider.py:144`.
- [ ] Total return for a known dividend-payer over 365d matches a hand-computed total-return within tolerance; a delisted ticker (`FSR`) resolves (not dropped).

**P0-8 — Golden score-block fixtures.** Ship golden envelopes with **fully populated** `axis_a`/`axis_b`/`gate_decision` blocks (for WS-6 gating-on-scores tests) and a fixed **`tests/fixtures/bon_panel/` of 10 envelopes** (the WS-5 quality-lift baseline panel).
- [ ] Fixtures exist under `tests/fixtures/` (incl. `bon_panel/`) and validate against the P0-1 schema.

**P0-9 — CI runner + hook registration (S7).** *Note (verified 2026-05-27): the repo has NO `pyproject.toml`/`setup.py`; bare `uv run pytest` fails. Tests run as `PYTHONPATH="$PWD" uv run --with pytest --with <runtime deps> pytest tests/unit` — CI must use this form, and `tests/unit/mcp` + `tests/unit/regime_sidecar` need extra SDK deps (yfinance/polygon/psycopg) or are excluded.* Add a CI workflow that runs the inner-cycle suite; **register `scripts/post_agent_validate.sh` in `.claude/settings.json`** as a `PostToolUse` hook **with `matcher: "Task"`** (the Agent-dispatch tool), shape: `{"PostToolUse":[{"matcher":"Task","hooks":[{"type":"command","command":"scripts/post_agent_validate.sh"}]}]}`.
- [ ] CI runs `pytest tests/unit` + the gate-dispatcher integration test on PR.
- [ ] **End-to-end hook check:** dispatching one `Agent()` causes the hook to actually execute (assert it wrote its validation-state log) — not merely that `validate_all`-direct unit tests pass (which would mask a mis-registered hook).

**P0-10 — `ScoreProvider` / `GateDecision` interface stubs.**
- [ ] Stubs typecheck and import from all six WS modules.

---

## Phase 1 — Parallel workstreams

Each WS: deterministic where it can be, quantified criteria, explicit degrade behavior (default **advisory-only on failure; never auto-PASS, never silent skip-to-FAIL**).

### WS-1 — Articulation scorer (Axis A) · `src/scoring/articulation/`
RAGAS faithfulness + answer-relevancy (LLM, cached); **ALCE citation P/R = deterministic set-overlap** of `frameworks_cited` vs evidence index (NOT an LLM call); **VERISCORE** (long-form factuality, replaces FActScore); UNION coherence (pinned local model); G-Eval clarity (advisory).
- [ ] Each sub-metric writes `axis_a`; faithfulness flags a seeded unsupported-claim fixture (recall > 0).
- [ ] Citation P/R matches hand-computed values on ≥5 fixtures within ±0.05 **deterministically** (no LLM in that path).
- [ ] No `FActScore` import. Scoring latency ≤ 1.5× rolling-median baseline.
- [ ] **Degrade:** scorer error ⇒ `axis_a=null, mode=advisory`; never blocks the gate alone.

### WS-2 — Sophistication scorer (Axis B) · `src/scoring/sophistication/`
ROSCOE + ReCEval on `reasoning_trace[].rationale`; CoT-faithfulness intervention; **novelty-frontier / perplexity-surprise on a version-pinned local model**.
- [ ] Computed from rationale sentences; label-only input **abstains/raises** (no silent number).
- [ ] Intervention flags a post-hoc fixture; scores stored as **percentile-vs-rolling-baseline** (relative; ROSCOE/ReCEval uncalibrated on analytical prose).
- [ ] High-novelty + ungrounded fixture scores **low** (novelty ANDed with grounding). **Degrade:** as WS-1.

### WS-3 — Conformal overlay wrapper · `src/conformal/` (+ wraps p8/p9/p10 outputs)
**ACI / Conformal-PID** wrapper; abstain when set non-singleton or calibration < 100; persist + version the calibration buffer.
- [ ] **Wrapper-disabled ⇒ bit-identical** to raw `classify*` (regression identity).
- [ ] Abstain fires on a constructed ambiguous case **and** below 100 calibration points.
- [ ] **(needs WS-4)** long-run realized coverage within **90% ± 5%** over a time-ordered replay; logged to a rolling monitor.
- [ ] **Degrade:** insufficient calibration ⇒ abstain wholesale (no bogus set).

### WS-4 — Calibration backlog + resolver · `src/calibration/` (+ migration 045 from P0-2)
Build the **missing resolver job** (poll `market_data.get_prices` PIT for ticker+SPY, backfill returns, UPSERT-on-conflict/idempotent) + **Brier + log-loss + reliability diagram w/ block-bootstrap CI** on the snapshotted `continuous_score`. Replace placeholder `src/eval/scorer.py`. Horizon = the existing columns **`t_plus_{30d,90d,1y}_return`**; `primary_horizon ∈ {30d,90d,1y}` per signal type (tactical/flow→`30d`, fundamental→`90d`/`1y`), each joined to its matching column (no `t_plus_365`).
- [ ] Resolver backfills `label_binary`+`excess_return` using **point-in-time** data only (assert reads ≤ resolve_at); idempotent re-run writes identical values.
- [ ] Delisted `FSR` resolves via total-return (P0-7), not dropped; multi-horizon rows clustered by `rec_id`.
- [ ] Brier reported with 95% block-bootstrap CI; ECE absent from headline. **Acceptance: backfilled history only.**

### WS-5 — Synthesis best-of-N + verifier (BoN-MAV) · pm-supervisor path (`phase_d_pm_supervisor.py`)
Single synthesizer → **N=5** candidates → **sonnet verifier** ranks/selects; self-consistency+critic fallback. Aggregate conviction **inputs** (debate_add_count, kills_fired, drift) across passes **before** the deterministic `conviction_rollup` — don't average final convictions. Cache `(input_sha, model_version, n, temp) → [candidates, verifier_pick]`.
- [ ] Generates N=5; **verifier model = sonnet ≠ synthesizer opus** (assert).
- [ ] Quality lift on the fixed **`tests/fixtures/bon_panel/` (10 envelopes)**: the **composite quality score** = mean(Axis-A faithfulness percentile, Axis-B sophistication percentile) of the verifier-selected candidate must be **≥ the single-pass (N=1) baseline** computed on the same panel, **at ≤ $15/pass**; per-pass cost recorded as one `attempt_cost_usd`.
- [ ] No MAD path unless (heterogeneous models) AND (verifiable step) flags set. Falls back to self-consistency on verifier error (fault-injection test).

### WS-6 — Hybrid gate · `evaluator_gates/` (registers via P0-4 registry), `scripts/` hook, CI
Deterministic companion checks (reuse shape validators) = hard spine; **sonnet** judge = advisory + abstain-to-escalate (temp 0, position-swap, cached); frozen **anchor set (30–50 labeled envelopes; operator-built once; owner: operator)** whose **baseline judge↔label κ is computed and stored at the moment the anchor set is frozen** (the quarantine reference); master-key trap; **ESCALATE-rate monitor**.
- [ ] Deterministic checks hard-FAIL on schema-invalid + citation-missing fixtures.
- [ ] **Linchpin:** judge never flips a verdict to PASS alone (can only downgrade to ESCALATE); judge *error* ⇒ ESCALATE (not PASS).
- [ ] Master-key trap (`":"`, `"Thought process:"`) scores 0 (must-pass).
- [ ] Anchor set runs each CI cycle; **judge auto-quarantines to advisory when live judge↔label κ drops > 10pp below the stored baseline κ** (baseline from the anchor-set freeze).
- [ ] **ESCALATE-rate monitor alerts when > 20% of gated envelopes ESCALATE over a rolling 50-run window** (guards the stealth-gate failure where the advisory judge escalates everything).

---

## Ownership matrix (collision-free after Phase 0 fixes)

| WS | Owned paths | Depends on |
|----|-------------|------------|
| Phase 0 | `src/agent_harness/envelopes/*`, `evaluator_gates/__init__.py` (two-layer registry refactor), migration **045**, `evidence_documents`+MCP persistence+producer audit, LLM cache (incl. `sample_index`), model knob, `market_data` fix, fixtures (+`bon_panel/`), CI/hook | — |
| WS-1 | `src/scoring/articulation/` | P0-1, **P0-3 (evidence)** |
| WS-2 | `src/scoring/sophistication/` | P0-1 |
| WS-3 | `src/conformal/` | P0-1; **WS-4 for the coverage criterion** |
| WS-4 | `src/calibration/` + resolver | P0-2, **P0-7 (PIT/total-return)** |
| WS-5 | pm-supervisor synthesis | **P0-6 (model knob)**, P0-5 (cache) |
| WS-6 | `evaluator_gates/` gates (via registry), `scripts/` hook, CI | P0-4, **P0-6**, P0-8 (fixtures) |

The shared-file collisions the review found are eliminated **only because P0-4 converts both the top-level dispatcher AND the per-artifact `_validate_*` gate-run lists into a registry** — WS-6 then registers gates by appending registry entries, never editing `__init__.py` bodies. (If P0-4's body-level registry is descoped, WS-6 must instead be **serialized to start after Phase 0**; it cannot run truly parallel while editing `_validate_*`.)

---

## Cross-cutting requirements

**Reproducibility checklist (non-deterministic components):** pin resolved model versions into envelopes (P0-5); LLM response cache, CI replays, cache-miss = fail; temp=0 for all gating-adjacent calls (self-consistency temp>0 only *inside* an aggregator whose median is the stored output); write-once emission snapshot (P0-2); BoN cache stores candidates **and** verifier pick; anchor-set drift = diff vs cached, not live recompute; thread/log RNG seeds (mirror `backtesting/framework.py`); persist conformal calibration-buffer state.

**Cost budget:** scoring runs all axes first-pass, **only the failed-gate axis on retries**; self-consistency N=5 first-pass only; WS-5 capped ≤ $15/pass; hook sums candidate+verifier usage into one `attempt_cost_usd`; E2E target recorded against the existing $60 ceiling concept.

**Halt-and-degrade (4 new components):** scorer down ⇒ axis=null/advisory; judge error ⇒ ESCALATE; resolver failure ⇒ idempotent resume (UPSERT); conformal under-calibrated ⇒ abstain. Default everywhere: advisory-only, never auto-PASS, never silent skip-to-FAIL.

**Security:** rotate `POLYGON_API_KEY` at the provider (**owner: operator**) and **verify the old key returns 401 before closing the task** (it was leaked in plaintext in conversation); never let scorer/judge prompts ingest `.env`.

---

## Phase 2 — Integration + E2E + CI gates
Wire scorers (WS-1/2) + gate (WS-6) + calibration (WS-4) into `.claude/commands/research-company.md` + the registered hook; connect overlays (WS-3) + synthesis (WS-5).
- [ ] Full `/research-company <ticker>` emits envelopes with `axis_a`/`axis_b`/`gate_decision` populated.
- [ ] Deterministic FAIL ⇒ overall FAIL regardless of judge.
- [ ] **No regression:** existing validation + all prior tests pass.
- [ ] One emission→resolve calibration cycle completes on a **backdated** test rec (autonomous loop closes).
- [ ] **WS-3×WS-4 join (carried from Phase 1):** promote `tests/unit/conformal/test_conformal_wrapper.py::test_long_run_coverage_within_band` (currently `run=False` xfail) to a real test — feed the WS-4 resolver's realized labels through a time-ordered replay into `ConformalWrapper.observe()` and assert realized coverage in [0.85, 0.95]. WS-4 has landed, so the original "pending WS-4" blocker is closed; this is the integration replay only.
- [ ] Inner-cycle CI gates block merge; outer-cycle suite scheduled (tracked, non-blocking).

## Phase 3 — Optional coverage gaps (WS-7, reuse-first, NOT on critical path)
> **Prerequisite (correction):** the implemented sizing formula `src/sizing/composable.py` (`v0.5_composable`) exposes only `conviction/regime/drawdown/cash` — it has **no `correlation_mod` or `liquidity_mod` slot** (those appear only in the superseded `docs/v2-final-spec.md` Kelly formula). So WS-7 must **first extend `CalibratedWeights` with the new multiplier dimensions** before "wiring" anything; this is not a dormant-slot reuse.
1. **Liquidity/tradability + sizing haircut** — `liquidity_profile` on flow-overlay (ADV math already in `gex_aggregator`); **add a `liquidity_mod` dimension to `composable.py`** + the haircut term.
2. **Portfolio-fit risk** — beta + corr-to-book (extend flow-overlay or a thin `risk-overlay`); **add a `correlation_mod` dimension to `composable.py`** and feed corr-to-book into it.
3. **Balance-sheet/credit stress** — `credit_stress` block on quantitative-analyst (interest coverage, maturity wall vs current curve, cash runway) via existing EDGAR+FRED grants.

## Inner / outer cycle (test architecture)
- **Inner (per-PR, BLOCKS):** `pytest tests/unit` (+ new `tests/unit/{scoring,conformal,calibration}/`), gate-dispatcher integration test, schema backward-compat (incl. flow/tactical validate the new fields), golden-envelope, deterministic-spine + master-key trap, cassette-replay judge within tolerance, conformal identity, calibration replay determinism (pinned `parameters_version` + frozen price fixtures + seeded bootstrap).
- **Outer (nightly, TRACKED):** E2E ticker panel, anchor-set agreement, Brier/log-loss/coverage trends, conformal coverage monitor, cost/latency from `logs/validation_attempts.jsonl`, drift via `_percentile`.
- **EVAL→UPDATE loop:** Loop A (intra-run delta-prompt retry) exists; Loop B (cross-run) = resolver → metrics → `parameters`-table recalibration of `continuous_conviction` weights at N≥50/cell (append-only INSERT, read via `parameters_active` next run) — gated by anchor-set regression. Only human touchpoint: the one-time frozen anchor set.

## Verification (end-to-end)
1. `pytest tests/unit -q` and `pytest -m integration tests/integration/test_validate_all_artifact_types.py` (P0 backward-compat + registry).
2. Run `/research-company AAPL` in a scratch run_id; confirm new blocks present and `gate_decision` honors the deterministic spine.
3. Backdate a rec, run the WS-4 resolver, confirm Brier/log-loss with CIs and ECE absent from headline; re-run to confirm idempotency.
4. Confirm a Massive total-return figure matches a hand-computed dividend-inclusive return for a payer.

## Execution order
Phase 0 (all 10 deliverables) → Phase 1 in parallel (WS-6 + WS-4 first as the autonomous-CI backbone; WS-3 coverage-gate after WS-4) → Phase 2 → Phase 3 (optional).
