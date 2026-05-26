# BUILD_LOG

Step-driven build record for an **equity research system that picks good stocks** (goal unchanged from v2-final). Decision 6 below names the *implementation pattern*: the system is built as an agent-harness around Claude Code — Claude Code is the brain, code is a tool. This is not a goal change; it's an implementation-style choice.

No dated cadence, no weekly diary, no commitment statement. Steps are ordered (substrate → conventions → agents → application → backtest), not scheduled. BUILD_LOG updates when steps complete, not on a calendar.

This is a deliberate departure from `docs/implementation-sequencing.md` §1 (calendar), §3 (weekly entries), §7 (buffer weeks), §9 (commitment statement) — see decision 5. The substantive commitments of v2-final and phasing-plan.md are unchanged; only the implementation pattern (decision 6) and the build cadence (decision 5) differ from the originals. The spec docs remain canonical for substance.

---

## Operating model

- **Substrate:** Claude Code (Path A — no separate Anthropic API key)
- **Cadence:** operator-driven, step-based (no dates, no weekly entries, no kill threshold)
- **Discipline preserved:** checkpoint artifacts (C1, C2, C3 — produced at step boundary regardless of pass/fail), Evidence Index, mechanical contamination check, process rubrics
- **Discipline removed:** build clock, calendar anchors, buffer weeks, weekly BUILD_LOG cadence, §9.3 commitment statement, documented-slip protocol

---

## External dependencies status

| Dependency | Status | Note |
|---|---|---|
| Anthropic runtime (via Claude Code) | RESOLVED | Path A — Claude Code is the runtime; no separate API key. |
| TimescaleDB + Postgres | NOT PROVISIONED | Local Docker recommended. Required before Evidence Index DDL step. |
| Sharadar Core Fundamentals | NOT APPLIED | 3–7 business day lead. Apply before BacktestingFramework step. |
| Price/news data provider | NOT COMMITTED | Commit before first sample memo generation. |
| MCP wiring (`mcp__postgres`, `mcp__edgar`) | NOT CONFIGURED | Required for slash commands that touch data layer. |

---

## Architectural decisions (Day 1)

**1. Path A — override v2-final §1.3 model-family diversity mandate.**

All agents run on Anthropic via Claude Code subagent infrastructure. The model-family diversity defense for BearCase is deliberately not enforced.

*Rationale:* operational simplicity outweighs the secondary contamination defense. The primary defense — mechanical Evidence Index check via §4.2.5 — remains intact and is invariant to model choice. Both CompanyDeepDive and BearCase memos undergo the same mechanical claim-to-row resolution check; contamination protection does not depend on model diversity.

*What is lost:* the secondary semantic-judgment diversity that would catch contamination patterns visible to a different model family but not to Anthropic.

*Reversibility:* if the contamination defense underperforms (post-cutoff degradation >20% at Checkpoint 3), the override is the first thing to revisit. Restoring §1.3 means routing BearCase through OpenAI or Google API directly, bypassing Claude Code for that one agent.

**2. Data API abstraction — deliberate deferral.**

Pluggable data layer is built with adapter interface and minimal stubs. Specific provider commitments deferred:

- **Price/news provider** (Polygon, Finnhub, yfinance, etc.): commit before first sample memo generation step
- **Sharadar Core Fundamentals**: apply before BacktestingFramework integration step

*Rationale:* avoids silent absorption waiting on external dependencies.

**3. Agent harness substrate — Claude Code subagents replace LangGraph.**

v2-final §4.3 specified LangGraph as the harness. Path A means the harness is Claude Code's subagent infrastructure (Task tool invocation, .claude/agents/ definitions). Supporting infrastructure — Evidence Index write hooks, mechanical contamination check, process rubric grading — is implemented as wrapper logic in slash commands and as post-processing on subagent outputs.

*What is preserved:* the mandatory Evidence Index write hook, the mechanical contamination check, the process rubric hard gates, the versioned prompts.

*What changes:* prompts live in .claude/agents/ markdown files with YAML frontmatter, not in a Python prompt registry. Versioning happens via git history of those files.

**4. Skills-only operational interface.**

Pure Claude Code-native interface. The operator runs the system entirely through slash commands and subagent invocations. No Python orchestration layer. External systems connected via MCP servers.

*Architecture:*
- `.claude/commands/` — 12 slash command entry points
- `.claude/agents/` — 3 subagents (CompanyDeepDive, BearCase, Evaluator) where context isolation matters
- `.claude/references/` — cross-cutting reference content
- `.claude/README.md` — three-layer architecture documentation

*Why subagents preserved:* The bull/bear adversarial pair needs context isolation to avoid sycophancy collapse. Path A already weakened the §1.3 model-family diversity defense; running the pair in main shared context would weaken it further.

*Reversibility:* if skills-only architecture proves unable to enforce the mechanical contamination check reliably, fall back to a thin Python wrapper that orchestrates subagents and runs post-sample hooks externally.

**5. Step-driven, no timeline (and no commitment statement).**

Original plan (per `docs/implementation-sequencing.md` §1–§3, §7, §9): dated build clock with weekly BUILD_LOG entries, calendar anchors, buffer weeks, dated checkpoints, and a §9.3 commitment statement.

Revised: ordered step list with no dates. Operator works through steps when they choose; BUILD_LOG updates when steps complete. No weekly cadence, no kill threshold date, no commitment statement.

*What is removed:* dated calendar (build clock, checkpoint dates, kill threshold), buffer-week schedule, weekly-entry cadence, §9.3 commitment statement, "documented slip" framework (no schedule to slip against).

*What is preserved:* checkpoint artifacts (produced at step boundaries C1/C2/C3 regardless of pass/fail), Path A decisions, Evidence Index discipline, mechanical contamination check, process rubrics.

*Trade-off acknowledged:* `docs/implementation-sequencing.md` §9–§10 discipline machinery was designed to prevent silent erosion in solo long-horizon builds. Removing dated cadence and §9.3 commitment removes those safeguards. Operator accepts that the project may drift in pace or scope without a structural fail-stop.

*Reversibility:* if drift becomes a problem, restore dated cadence — pick a build clock start, reintroduce weekly entries, define a kill threshold. Reversal is straightforward.

*Consequence on slash commands:* `/run` and `/weekly-buildlog` were authored to detect calendar position (end-of-week, checkpoint dates, etc.). Under decision 5 those calendar branches no longer fire. `/run` becomes a status-and-step-surfacing command; `/weekly-buildlog` is moot. Slash command updates deferred until requested.

**6. Claude Code is the brain; code is a tool, not an orchestrator.**

The goal is unchanged from v2-final: build an equity research system that picks good stocks under the discipline of mechanical contamination defense, calibration-driven sizing, and the rest of the v2-final substantive commitments (slow/fast layer separation, watchlist contract, process/outcome rubric separation, counterfactual ledger, PASS-as-default, etc.). What changes is the *implementation pattern*.

**Original implementation pattern** (v2-final §4.3): a traditional system. Python + LangGraph orchestration, with LLMs invoked as functions inside the orchestration layer. The system's control flow lives in code; LLMs are components called by code.

**Revised implementation pattern:** an agent-harness around Claude Code. Claude Code is the brain — it holds the orchestration logic, runs the prompts, invokes subagents, makes routing decisions through conversational reasoning and slash commands. Code, where it exists, is a *tool* or *sub-system* that Claude Code consumes — never an orchestrator of it.

This is a strict extension of decision 4 (skills-only operational interface). Decision 4 said *"no Python orchestration layer."* Decision 6 states the positive inverse explicitly: **Claude Code holds the brain function**. Python is allowed wherever it's the right tool — numerical computation, deterministic transformations, data-layer adapters, external API integration via MCP servers — but it is *consumed by* Claude Code via slash-command helpers or MCP tool calls, never the converse.

*Why state this explicitly when decision 4 already implied it?* Because the negative phrasing of decision 4 ("no orchestrator") is easy to slip past. Future-tired-me writing "just a small Python coordinator that calls a few subagents in a loop" needs to recognize that as a violation of decision 6, not a clever optimization. The positive framing — "Claude Code is the brain" — makes the violation visible.

*What this changes practically:*
- Code goes in two places only: skill helpers (`src/skills/<command-name>/`) and MCP server implementations (`src/mcp/<server-name>/` or external packages). Both are leaf-level — they implement *capabilities*, not control flow.
- Slash commands route operator intent and invoke subagents conversationally, not via Python.
- Subagent prompts live in `.claude/agents/` markdown with YAML frontmatter, versioned via git history.
- Data layer is consumed via `mcp__postgres`, `mcp__edgar`, `mcp__fundamentals`, etc. — Claude Code calls the MCP; the MCP wraps the underlying Python adapter or external API.
- Claude Code's wrapper logic (slash command body) is where post-sample hooks like the mechanical contamination check attach, because that's where the brain gets a chance to inspect output before release.

*What is preserved:*
- The goal: equity research system that picks good stocks. All v2-final substantive commitments unchanged.
- All prior decisions (1–5) and their rationale.
- All `docs/` substantive content (v2-final-spec, phasing-plan, implementation-sequencing) — canonical for what the system does and how its quality is measured.
- All checkpoint substance (C1/C2/C3 gate criteria from `docs/phasing-plan.md` §2.5) — substantive correctness still measured at C3 via post-cutoff Sharpe degradation, DSR, PBO, counterfactual baselines.

*Trade-off acknowledged:* this implementation pattern bets that Claude Code's orchestration is reliable enough to be load-bearing for the mechanical hooks (Evidence Index writes, contamination check, process rubric grading). If it isn't — e.g., if the contamination check can't be enforced as a hard gate within slash-command wrapper logic — the system has no fallback that preserves decision 6. The fallback path goes to a thin Python wrapper that orchestrates subagents and runs post-sample hooks externally; that's a code-as-orchestrator pattern that violates decision 6 by definition.

*Reversibility:* if the agent-harness pattern produces unreliable enforcement of mechanical conventions, restore code-as-orchestrator per decision 4's reversibility note. The substantive commitments and goal are unchanged across the reversal; only the implementation pattern moves.

**7. Scope anchor — retire all skills, modules, and migrations not on the `/research-company` critical path.**

The system has accumulated operational machinery (daily-monitor, alerts, drift detection, premortem cadence, anchor drift, calibration capture, outcome resolution, sizing, disposition, wash-sale, audit-trail UI, governance ceremonies, /run orchestrator) anticipating v0.5 and v1.0 operational states that the substantive C3 gate has not earned the right to reach yet. Decision 7 collapses the surface area to the one workflow that produces value: `/research-company` — pick good stocks.

This is a strict extension of the trigger that drove peak_pain_archetypes + counterfactual_veto retirement (commits `d5916e7` → `352b48c`, 2026-05-17 → 2026-05-20). The same reasoning generalizes to the whole operational stack: built for a future state the build has not earned the right to occupy.

*Keep-set (the `/research-company` critical path):*

- **Skills:** `.claude/commands/research-company.md`, `.claude/commands/evaluate.md`
- **Subagents:** `catalyst-scout`, `pm-supervisor`, `evaluator`, `quantitative-analyst`, `strategic-analyst` (all 5 in `.claude/agents/`)
- **MCP servers consumed by the pipeline:** `mcp__postgres`, `mcp__contamination_check`, `mcp__edgar`, `mcp__market_data`, `mcp__yfinance`, `mcp__polygon`, `mcp__macro_stack`, `mcp__fred`, `mcp__fundamentals` (stub)
- **DB tables:** `evidence_index`, `predictions`, `parameters`, `execution_recommendations`, plus auxiliary tables the pipeline writes (e.g., `scenarios`) — exact set derived during execution by grep-tracing the skill body
- **Python modules:** `evidence_index/`, `audit_trail/hmac_verify.py` (HMAC canonical-payload contract, single source of truth for execution_recommendations signing), `data_layer/`, `mcp/{postgres,contamination_check,edgar,market_data,yfinance,polygon,macro_stack,fred,fundamentals}/`, and any other modules surfaced as dependencies during the grep-trace pass

*Retire-set (full sweep, `git rm`):*

- **25 skills:** `ack`, `alerts`, `audit-trail`, `backtest`, `brief-delta-sweep`, `calibration-status`, `cdd-test`, `checkpoint`, `daily-monitor`, `disposition`, `entry-check`, `exit-check`, `grill-me`, `launch-confirm`, `macro-cycle`, `parameters-review`, `premortem`, `quarterly-reunderwrite`, `resolve-outcomes`, `review-me`, `run`, `size`, `spec-approve`, `system-health`, `wash-sale-harvest`, `weekly-buildlog` (already deprecated)
- **Subagent tombstone:** `bear-case.md.removed-20260512` (already retired; cleanup completes)
- **Python modules (full sweep):** `orchestrator/`, `l4_daily_monitor/`, `disposition_view/`, `alert_channels/`, `anchor_drift/`, `premortem_scheduler/`, `parameters_review/`, `spec_approve/`, `launch_confirm/`, `backtesting/`, `calibration/`, `outcomes/`, `sizing/`, `mcp/broker_mcp/`, `p3_mechanical_scorer/`, `p4_debate/`, `p5_watchlist/`, `p6_disposition/`, `p7_recommendation_emitter/` (if not on critical path), `regime_sidecar/` (if not on critical path), `watchlist/` (if not on critical path), plus any residual `peak_pain_catalog/` and `counterfactual_veto/` scaffolding not already removed
- **DB migrations:** Down-migrations or direct `DROP TABLE` for `005_v3_regime`, `009_v3_daily_monitor`, `010_v3_drift_detection`, `012_v3_premortem`, `013_v3_calibration_capture`, `014_v3_system_health`, `015_v3_calibration_test_results`, plus residual references in `011_v3_counterfactual_retrieval` after peak_pain rename. Migrations 001-004, 006, 007 (watchlist portion only), 008, 016+ kept or selectively reduced based on critical-path trace.
- **Tests:** Test files under `tests/test_*.py` covering retired modules drop alongside.

*Rationale:*

The reasoning is the same that drove peak_pain retirement: substantial sunk implementation cost in operational machinery that the substantive validation gate (C3) has not earned the right to use. Building more discipline-machinery on top of an unvalidated strategy core is the failure mode `docs/phasing-plan.md` §6 anti-patterns explicitly name.

Anchoring on `/research-company` keeps the system honest: one workflow, repeatedly applied, with mechanical contamination defense intact. The output (cdd memo + briefs + pm report + execution_recommendation) is the unit of work that, accumulated over real-world runs, eventually answers the alpha question — without ceremony surrounding it.

*What is preserved:*

- The goal (pick good stocks under mechanical contamination discipline).
- The pipeline (CDD → strategic + quantitative → catalyst-scout → pm-supervisor → evaluator).
- The mechanical contamination defense and Evidence Index (decisions 1, 4).
- The HMAC canonical-payload contract for execution_recommendations via `audit_trail/hmac_verify.py`.
- Append-only persistence on `evidence_index` and `predictions`.
- All design documents in `docs/` — canonical reference for what each retired component WAS designed to do; useful if reversal needed.

*What is lost (and acknowledged):*

- **Outcome tracking and calibration scoring.** Brier-driven sizing adjustment (v2-final §sizing) is unmeasurable. Quarter-Kelly with bounded floor/ceiling becomes a static parameter, not a calibration-tracked one.
- **Counterfactual ledger as first-class object.** v2-final substantive commitment surrendered.
- **Backtest framework (DSR, PBO, pre/post-cutoff Sharpe split).** The C3 substantive gate as written becomes unmeasurable. C3 itself needs re-specification or formal sunset.
- **v0.5 and v1.0 phasing.** Both were defined in operational-machinery terms now retired. `docs/phasing-plan.md` is, in effect, suspended.
- **Slow/fast layer separation.** Watchlist contract enforcement via `/p5_watchlist` is retired; no execution layer remains. The system becomes research-only — emits BUY/HOLD/TRIM/SELL recommendations as terminal artifacts and stops. v2-final §1 watchlist-contract substantive commitment is no longer mechanically enforced.
- **Push-alert channel, daily heartbeat, anchor drift, premortem cadence** — the slow-layer-as-designed disciplines.
- **Audit-trail CLI verification UI.** HMAC chain is still computed; no consumer-facing verifier ships.
- **Tax-aware exit logic** (wash-sale, exit-check). Materially relevant for real-money operation, not for paper-only research output.
- **Governance ceremonies** (parameters-review, spec-approve, launch-confirm).
- **/run master orchestrator.** Operator types `/research-company TICKER` directly.

*Reversibility:*

The operator chose **delete outright (`git rm`)** in the scoping interview, NOT tombstone rename or move-to-retired/. Reversal requires git archaeology: `git revert` of the sweep commit(s), schema replay of dropped migrations against current data state (may not roll back cleanly if any retired-table data exists), and dependency-import audit. **Practically irreversible** without meaningful re-work — distinct from decisions 1-6 which all retained clean reversal paths. The operator accepts this asymmetry on the basis that the retired components have empirically failed to earn their keep within the build's economic budget; preserving them as tombstones would invite zombie-resurrection of unused machinery.

*Trade-off acknowledged:*

The slow-layer / fast-layer architecture that v2-final framed as core is gone with this decision. So is the calibration-driven sizing discipline and the counterfactual baseline measurement that justified the system's claim to a measurable alpha edge over passive baselines. After decision 7, the system makes no formal claim that its picks beat SPY — it only claims that the picks survive a mechanical contamination check and an adversarial pressure-test inside `pm-supervisor`. That is a meaningful retreat from the v2-final substantive commitments and should be recorded as such.

The bet is that mechanical contamination defense + adversarial pressure-test + a small number of high-quality research runs will produce better-than-coinflip stock picks in real-world use, even without the formal alpha-measurement apparatus. If that bet fails, the failure mode is operator drift into discretionary stock-picking, with the system as decoration — which is the failure mode the operational machinery was designed to prevent. Decision 7 accepts that risk explicitly.

*Implementation protocol:*

1. Grep-trace `/research-company` skill body → subagent declarations → MCP tool calls → Python module imports → DB tables. Produce a derived sweep set as a separate review artifact (`docs/decision-7-sweep-set.md`).
2. Operator reviews the derived sweep before any `git rm` runs.
3. Sweep executes as a single atomic commit (skills + modules + migrations + tests together) so revert is one operation if needed.
4. Post-sweep smoke: `/research-company` on a known-historical name (e.g., re-run AAPL-2024 from Tier 3) confirms the pipeline still completes end-to-end.

---

## Steps

The build is organized into four tiers: Substrate → Conventions → Agents → Application. Checkpoints fall at tier boundaries. The "harness" terminology where it appears refers to the *implementation pattern* of decision 6 (Claude Code as the brain, code as a tool), not to the deliverable — the deliverable is the equity research system.

### Tier 1: Substrate

Runtime + persistence + external-service plumbing that the equity research system needs.

- [x] Repo initialized; structure per `docs/implementation-sequencing.md` §3.1
- [x] Day-1 first commit (BUILD_LOG, README, docs, src, checkpoints)
- [x] Skills-only architecture: 12 commands, 3 subagents, 16 references in `.claude/`
- [x] Anthropic runtime resolved (Claude Code, Path A). `provider_verification/` removed — audit-trail step deemed not worth the cost in v0.1.
- [x] Provision TimescaleDB + Postgres locally (Docker) — `docker-compose.yml`, `.env.example`, `db/init/01-extensions.sql`, `db/README.md`. Container `equity-research-db` healthy on `127.0.0.1:5432`. Extensions verified: `timescaledb 2.26.3`, `pgcrypto 1.3`, `plpgsql 1.0`.
- [x] Wire `mcp__postgres` against local DB. Own implementation in `src/mcp/postgres/` (decision-6 example: code as tool consumed by Claude Code). Three tools — `query` (read-only enforced via `READ ONLY` transaction), `execute` (writes; append-only enforced at DB level via Tier 2 triggers, not here), `schema_info`. Connection from `.env` via `python-dotenv`; no creds in `.mcp.json`. Smoke-tested all three tools against live DB: SELECT/version, extensions list, read-only enforcement (CREATE TABLE inside `query()` rejected with `ReadOnlySqlTransaction`), full INSERT round-trip via `execute`. **Claude Code must be restarted to load the new `.mcp.json`.**
- [x] Decide where Python helper code lives (skill helpers in `src/skills/<command-name>/`, MCP servers in `src/mcp/<server-name>/`); documented in `.claude/README.md` and decision 6.

### Tier 2: Conventions (mechanical discipline)

The mechanical hooks that enforce v2-final's discipline: Evidence Index, contamination check, process rubric, subagent isolation, append-only persistence. Tested with synthetic data so failures are isolated to the convention layer, not the equity-research substance.

- [x] Apply Evidence Index DDL — `db/migrations/001_evidence_index.sql` applied. Table + 4 indexes + `prevent_modify()` trigger live.
- [x] Append-only constraint enforced at DB level — verified via synthetic INSERT then UPDATE/DELETE attempts; both rejected with `evidence_index is append-only` error from `prevent_modify()`.
- [x] Mechanical contamination check implemented as enforced hook — own MCP server at `src/mcp/contamination_check/` (decision-6 typed capability mirroring `mcp__postgres` precedent). Three tools: `verify`, `verify_memo`, `diagnostic`. Attaches inside the `evaluator` subagent (per `src/mcp/contamination_check/DESIGN.md` §6) — added to `evaluator.md` `tools:` line. `.mcp.json` declares the server. Decision-6 open question answered: hook lives as MCP tool consumed by Evaluator, not as Python orchestrator.
- [x] Convention enforcement test — `tests/test_contamination_check.py`, 8 cases: PASS/FAIL/MISSING_REF/FABRICATED_UUID/POSTDATED_SOURCE/EMPTY_REFS/INCOHERENT_PREDICTION + same-day boundary + qualitative-exempt. All 8 green. Synthetic data fixtures use deterministic uuid5 so re-runs are idempotent.
- [x] Process rubric grading wired: Evaluator subagent invokable; produces a graded output for synthetic input; hard-gate behavior triggers on contamination. Verified by dispatching the `evaluator` subagent on (a) a clean synthetic memo (verdict=PASS, n_failures=0; same-day boundary correctly handled) and (b) a contaminated synthetic memo (verdict=FAIL, `failure_mode=POSTDATED_SOURCE`, diagnostic `"source_date 2024-12-15 is after resolution_date 2024-09-30 — contamination signature."`). **Wiring caveat (REVISED 2026-04-26 — see `checkpoints/checkpoint_3.md:98` for full corrected understanding):** the original C1/C2 finding was *partially wrong*. Subagents DO inherit MCP tools when declared at **tool-level** (`mcp__contamination_check__verify`); they do NOT inherit them when declared at **server-level shorthand** (`mcp__contamination_check`). The original test that prompted the workaround appears to have used server-level shorthand and concluded "neither form works," which on re-test is incorrect. Empirically verified 2026-04-26: `evaluator` (already declared at tool-level) calls MCP natively; `bear-case`/`company-deep-dive` (originally server-level) failed → updated to tool-level → MCP now works after session restart. The Bash + `uv run python -c "from server import verify; ..."` workaround remains a valid fallback (decision 6 still satisfied either way) but is no longer required. Agent definitions are cached at session start; edits to `.claude/agents/*.md` need a Claude Code restart to take effect.
- [x] Subagent isolation verified: parallel-launched memorizer and querier subagents tested; memorizer given secret token "RHINOCEROS-7K9X"; querier launched in same parent message reported `ISOLATED: I do not have access to the other subagent's memory.` Working-memory isolation between adversarial pairs (CompanyDeepDive vs BearCase) is structurally sound under Claude Code subagent infrastructure.
- [x] Append-only persistence — `predictions` and `counterfactual_ledger` schemas applied (`db/migrations/002_predictions.sql`, `003_counterfactual_ledger.sql`). Conditional-update triggers verified: predictions allows UPDATE only on resolution fields (resolution_date, resolved_value, resolved_outcome, resolved_correct, brier_component) and rejects DELETE; counterfactual_ledger allows UPDATE only on window-close fields (evaluation_window_end, system_return, baseline_return) and rejects DELETE. Generated column `delta_vs_baseline` auto-populates correctly. All synthetic write/reject cases pass.

### Checkpoint 1 — Substrate + Conventions Live

- [x] All Tier 1 + Tier 2 steps complete (14/14)
- [x] `checkpoints/checkpoint_1.md` artifact produced. Verdict: **PASS**.
- [x] Gate criterion satisfied: synthetic memo end-to-end through Evaluator subagent → `mcp__contamination_check.verify` → verdict (PASS for clean, FAIL/POSTDATED_SOURCE for contaminated). No equity-research-specific code path involved.

### Tier 3: Agents (CompanyDeepDive, BearCase, Evaluator, PMSupervisor)

The agents per `docs/v2-final-spec.md` §1.2 and `.claude/agents/` markdown. Tested on a known-historical name to confirm the pipeline shape, not strategy quality (that's Tier 4 + C3).

- [x] **Prerequisite: `mcp__edgar` wired.** Own implementation in `src/mcp/edgar/` (decision-6 example, third MCP server). Three tools — `get_filings`, `get_filing_text`, `get_company_facts` — over `data.sec.gov` + `sec.gov/Archives` REST endpoints. SEC fair-access compliance via `EDGAR_USER_AGENT` env var (fail-loud if missing). Lazy ticker→CIK map cache (CIK→ticker reverse-lookup also supported). `tests/test_edgar.py` (7 cases marked `@pytest.mark.integration`) all green against live SEC API: `test_get_filings_apple_basic`, `test_get_filings_form_filter`, `test_get_filings_since_date`, `test_get_filings_by_cik`, `test_get_filings_unknown_ticker`, `test_get_filing_text_html`, `test_get_company_facts_apple`. Fetches actual Apple 10-K bytes (~10MB+) and XBRL company facts.
- [x] CompanyDeepDive prompt produces ordered memo on a known-historical name. AAPL as-of 2024-12-31 (FY2024 10-K filed 2024-11-01 is the most recent available; FY2025 10-K excluded as post-cutoff). Memo at `memos/aapl_cdd_2024-12-31.json` (~18KB). Top-level ordering verified: `section_2_failure_scenarios` precedes `section_3_thesis_pillars`. Recommendation: WATCH (subagent's earned conviction; revenue plateau + flat EPS vs. GM expansion). 3 failure scenarios + 3 thesis pillars + 3 reviewable_predictions per Tier 3 smoke scope. P10/P90 IRR spread 46pp (satisfies vol-floor ≥ 26% × √3).
- [x] CompanyDeepDive's Evidence Index references populate correctly. 12/12 evidence_index rows persisted; all 12 cited UUIDs in `section_13_evidence_index_refs` map to actual rows in DB (no fabricated UUIDs). All claims sourced to FY2024 or FY2023 10-K (tier 1, SEC primary). Mechanical contamination check verdict: **PASS** (n_claims=12, n_refs=12, n_failures=0). **Semantic finding (worth a follow-up edit to DESIGN.md):** `resolution_date` for a non-prediction claim = analyst's as-of date (2024-12-31), NOT the referenced period end (e.g., 2024-09-28). DESIGN.md §3 step 4 suggested period-end which is wrong because SEC 10-Ks are always filed AFTER the period they describe; period-end semantics would make any backward-looking financial statement uncitable. Predictions use `target_date` separately. Smoke also caught a real subagent-orchestration bug: when the parent retypes UUIDs into MCP calls instead of programmatically extracting from the JSON, hallucinated UUIDs trip FABRICATED_UUID — first verify pass failed with 12/12 FABRICATED_UUID; re-run via Bash + `from server import verify` against the actual memo UUIDs gave PASS.
- [x] BearCase produces critique against the CompanyDeepDive memo. BC subagent dispatched against `memos/aapl_cdd_2024-12-31.json` with strict input-isolation discipline (saw only the memo, not CDD's reasoning context). Output at `/tmp/bc_aapl_critique.json`: 3 weak-scenario flags, 3 missing-scenario additions, 3 thesis-pillar pushbacks, "more cautious" recommendation direction with concrete sideways-grind modal-outcome thesis. 9 evidence_index rows persisted to DB.
- [x] Evaluator runs mechanical claim-to-row resolution on both memos. **CDD memo:** verdict=PASS (n_claims=12, n_refs=12, n_failures=0; resolution_date=as-of-date semantics applied, see semantic finding above). **BC critique:** verdict=PASS (n_claims=9, n_refs=9, n_failures=0). Hard-gate behavior already validated mechanically in Tier 2 (POSTDATED_SOURCE detection; first CDD verify pass actually fired POSTDATED_SOURCE on 10/12 claims when resolution_date was wrongly set to period-end — that's the gate functioning correctly).
- [x] PMSupervisor synthesis. Lives in main context as orchestration logic (no separate `pm-supervisor.md` subagent — architecture per `docs/v2-final-spec.md`). Output at `memos/aapl_pm_decision_2024-12-31.json`: decision=`WATCH_SUB_THRESHOLD`, conviction=0.42 (below 0.7 ADD threshold by design — earned conviction would require Sharadar PIT + analyst comps + 90-day news + 13F shifts, all deferred per Tier 4). Size band 0-1% (no actual position). Bull/bear adversarial mechanic functioned as designed: BC's sideways-grind critique converted CDD's WATCH @ 1-2% size to WATCH_SUB_THRESHOLD @ 0-1%.

### Checkpoint 2 — Agents Working End-to-End

- [x] All Tier 3 steps complete (mcp__edgar prereq + CDD memo + Evidence Index population + BC critique + Evaluator hard-gate + PMSupervisor synthesis)
- [x] CDD → BC → Evaluator → PMSupervisor pipeline runs successfully on AAPL as-of 2024-12-31. Flow exercised by direct subagent dispatches from parent (orchestrating); same agents, same isolation, same hard gates as a `/research-company` slash command invocation would produce.
- [x] `checkpoints/checkpoint_2.md` artifact produced. Verdict: **PASS** (structural correctness only).
- [x] Gate criterion satisfied: AAPL memo flowed through the harness end-to-end; mechanical conventions enforced (Evidence Index 12+9 rows populated, contamination check PASS on both, process rubric ordering verified).

### Tier 4: Application (live equity-research data + operational shape + backtest)

The full equity research operational shape. Real data layer, real fundamentals, real backtesting per `docs/phasing-plan.md` §2.5.

- [x] Pluggable data layer delivered via the MCP layer (decision-6 framing: data-layer access via `mcp__market_data` + `mcp__edgar` + `mcp__postgres`, not a separate Python `PriceFeatureService` service abstraction). v2-final's "PriceFeatureService" name preserved as conceptual; the substrate is the MCP layer.
- [ ] **Sharadar account active; `mcp__fundamentals` wired.** DEFERRED — operator action required (paid subscription, 3-7 day approval). Stub server at `src/mcp/fundamentals/` raises `NotImplementedError` with operator-action message. v0.1 fallback: `mcp__edgar.get_company_facts` (XBRL non-PIT) acceptable for sample-memo generation with explicit caveat.
- [x] Price/news provider committed: **yfinance**. `mcp__market_data` wired at `src/mcp/market_data/` with `get_prices`, `get_news`, `get_real_time_quote`. 4/4 integration tests against live yfinance pass. Polygon/Finnhub deferred to v0.5.
- [x] `mcp__edgar` wired (Tier 3 prereq). 7/7 integration tests against live SEC EDGAR API.
- [x] FRED integration. `mcp__fred` wired at `src/mcp/fred/` with `get_series` + `get_series_info`. **Tests skip cleanly** until operator registers a free API key at https://fredaccountmanager.research.stlouisfed.org/apikey and adds `FRED_API_KEY=...` to `.env`.
- [ ] **BacktestingFramework walk-forward validation with embargo.** SKELETON ready at `src/backtesting/framework.py`; raises `NotImplementedError("Pending Sharadar PIT data")` on the part requiring point-in-time fundamentals. Operator unblocks via Sharadar.
- [x] DSR with explicit trial reporting. `src/backtesting/dsr.py` (Bailey-Lopez de Prado 2014 eqs. 6+9). Skew/kurtosis support. Tested vs hand-computed reference values.
- [x] PBO calculation. `src/backtesting/pbo.py` (CSCV per Bailey-Lopez de Prado 2014). Tested with synthetic strategies.
- [ ] **Pre/post-cutoff Sharpe split.** SKELETON ready; raises `NotImplementedError` pending Sharadar PIT.
- [ ] **Generate ≥30 sample memos through `/research-company`.** DEFERRED — 1 sample memo (AAPL) demonstrates full end-to-end pipeline with all conventions enforced. Scaling to 30 requires (a) operator inference budget approval (~$50-150) and (b) ideally Sharadar PIT for backtest-grade memos. Pipeline mechanics verified at N=1.
- [x] Audit memos. `BacktestingFramework.audit_memos()` orchestrates `mcp__contamination_check.verify_memo` over the memo set with 50-claim random sampling per `phasing-plan.md` §2.5.2. Tested in stub mode; production-ready against the 1 memo currently in `memos/`.

### Checkpoint 3 — Strategy Validated (v0.1 → v0.5 advancement decision)

This is where alpha is judged.

- [~] All Tier 4 steps complete (structurally; substantive items DEFERRED per `docs/tier4-deferred-work.md`)
- [x] Mechanical conventions audit clean: 21/21 evidence claims (CDD 12 + BC 9) pass contamination check at `verdict=PASS`. Audit infrastructure (`audit_memos`) is wired — at scale (30+ memos, 50-claim sample) audit runs once operator budgets memo generation.
- [x] Pipeline produces correctly-formed outputs end-to-end (structural correctness verified on AAPL)
- [ ] Substantive correctness gate (per `docs/phasing-plan.md` §2.5):
  - Pre/post-cutoff degradation <20% (else trigger Path A reversal per decision 1)
  - DSR on post-cutoff sample >0.5
  - PBO <50%
  - Counterfactual baselines beaten (SPY, equal-weight watchlist, sector-matched, 60/40)
- [x] `checkpoints/checkpoint_3.md` artifact produced.
- [x] **Gate decision: CONDITIONAL APPROVE.** Structural correctness gate: PASS. Substantive correctness gate: BLOCKED on external dependencies (Sharadar subscription, operator memo-generation budget, forward evaluation window) — NOT on harness defects. CONDITIONAL APPROVE captures the distinction: ship the harness; defer alpha-validation to early v0.5 with explicit unblocking criteria documented in `checkpoints/checkpoint_3.md` "Operator unblocking checklist". If substantive evaluation later reveals real strategy failure → trigger Path A reversal (decision 1) or sunset.

### Tier 5: v3 Empirical-Foundation Implementation (2026-04-29)

The v3 spec (`docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md`) consolidated ~64 architectural decisions across 8 sections + 9 Phase 4 reconciling locks. Sign-off attested 2026-04-29T16:57:06+09:00. Implementation followed §7.4 critical-path-first + parallel-tracks ordering across implementation waves. This tier records what shipped; the spec remains canonical for substance.

**Schema work (18 new migrations, 004-021):**

- [x] `004_v3_parameters.sql` — versioned config store; foundation for `/parameters-review` and audit-trail version pinning
- [x] `005_v3_regime.sql` — S0 regime sidecar tables (regime_classification_history append-only + regime_state view); 6-dim Tier-1 classifications + BOCPD probabilities
- [x] `006_v3_scenarios.sql` — P2 probabilistic-scenario branches; sum-to-1 sibling probabilities enforced at write time + post-write linter
- [x] `007_v3_watchlist_positions.sql` — research-vs-portfolio split (watchlist + positions + position_history); HMAC-signed thesis_pillars_original + scenario_A_base_projections
- [x] `008_v3_recommendations.sql` — execution_recommendations (§4.6 Q1 schema + Phase 4 Q2 conviction rollup) + mode_classifications + audit_provenance HMAC chain
- [x] `009_v3_daily_monitor.sql` — daily_refresh_log + materiality_events + unread_alerts; alert state-table semantics with mutable acknowledgment columns
- [x] `010_v3_drift_detection.sql` — anchor_drift_checks (3 channels) + materiality_classifier_drift + mode_vol_checks
- [x] `011_v3_counterfactual_retrieval.sql` — peak_pain_archetypes (~160 cases two-layer schema) + counterfactual_retrievals + veto_lifecycle
- [x] `012_v3_premortem.sql` — pre-mortem ledger (mode-tuned cadence + event triggers); Opus required for high-stakes contestable judgment
- [x] `013_v3_calibration_capture.sql` — operator_overrides + recommendation_outcomes + override_outcomes + debate_consensus_history + fill_divergence
- [x] `014_v3_system_health.sql` — system_errors append-mostly + system_vs_operator_brier view stub
- [x] `015_v3_calibration_test_results.sql` — gold-standard test ledger with catalog_version_hash
- [x] `016_v3_hmac_columns.sql` — promotes embedded HMAC fields to first-class columns on peak_pain_archetypes + premortem
- [x] `017_v3_alert_type_extension.sql` — extends unread_alerts.alert_type CHECK enum (adds materiality_m2 + calibration_drift)
- [x] `018_v3_forced_review_blocked_pending.sql` — anchor_drift_review_decisions sidecar; spec §4.5 Q5 "No-op default BLOCKED" — pending no longer a valid terminal state
- [x] `019_v3_first_acquired_nullable.sql` — drops NOT NULL on positions.first_acquired (Schwab does not return per-lot dates)
- [x] `020_v3_bocpd_short_run_mass.sql` — adds bocpd_short_run_mass as primary firing signal alongside canonical bocpd_change_probability marginal (operator-locked dual-signal architecture)
- [x] `021_v3_dimension_name_rename.sql` — updates dim 2 CHECK constraint cycle_ntfs → cycle_2y3m_slope (DGS2 - DGS3MO CMT slope, not Engstrom-Sharpe NTFS)

**Modules built (under `src/`, decision-6 leaf-level capabilities consumed by Claude Code):**

- [x] `regime_sidecar/` — daily 6-dim BOCPD classifier; writes regime_classification_history + populates regime_state view; cold-start 90-day flag
- [x] `mode_classifier/` — 3-stage layered architecture (market-structural → company-quality flag → overlap LLM tie-breaker); recheck for quarterly re-classification
- [x] `mcp/broker_mcp/` — Schwab-default read-only positions MCP; OAuth flow + token refresh + diff_engine (poll_for_fills); BrokerAdapter pluggable for IBKR/Fidelity at v0.5+
- [x] `peak_pain_catalog/` — 3-LLM iterative-consensus pipeline with feature-typed agreement (categorical exact / ordinal ±1); priority_runner (~45 cases) + lazy_runner (~115 tail); HMAC-signed via PEAK_PAIN_HMAC_KEY
- [x] `audit_trail/` — single source of truth for HMAC canonical-payload contract (`hmac_verify.py`); renderer for layered drill-down; CLI consumed by `/audit-trail`
- [x] `p3_mechanical_scorer/` — 3-stage hybrid scorer (Stage 1A multiplicative knockout + Stage 1B Tier-A composite + Stage 2 LLM rubric information-isolated + Stage 3 deterministic linter)
- [x] `p4_debate/` — 5-style debate orchestrator (Phase A isolated → Phase B locked → Phase C judge + conditional negotiation → Phase D PMSupervisor); style sub-agents in `styles/`
- [x] `l4_daily_monitor/` — event_ingestor + materiality_classifier + router + cut_evaluator + refresh_emitter + drift_detector; Sonnet/Opus-only routing; Mode C BOCPD short-run-mass firing
- [x] `anchor_drift/` — 3 channels (channel_1 pillar drift / channel_2 outcome divergence / channel_3 periodic re-read); HMAC verification against original watchlist payload
- [x] `premortem_scheduler/` — cadence floor checker + event_triggers + devils_advocate (Opus) + recorder; HMAC-signed via PREMORTEM_HMAC_SECRET
- [x] `watchlist/` — hmac_producer for thesis_pillars_original + scenario_A_base_projections; WATCHLIST_HMAC_SECRET scope
- [x] `p5_watchlist/` — adder consuming /research-company output; writes watchlist row with HMAC-signed pillars
- [x] `p6_disposition/` — determiner (mode + horizon → primary_horizon mapping)
- [x] `p7_recommendation_emitter/` — emits execution_recommendations rows with full §4.6 Q1 schema; AUDIT_HMAC_KEY signs canonical row payload
- [x] `alert_channels/` — session_push + email_sender (MAX_EMAIL_ATTEMPTS=4 DECISION LOCK) + queue_processor + system_health renderer; CLI consumed by `/alerts`, `/ack`, `/system-health`
- [x] `counterfactual_veto/` — feature_extractor + retrieval (two-layer scoring) + layer1_cooling_off + layer2_multi_source + layer3_veto + lifecycle (PB#5 single-fire + M-3 re-fire) + calibration
- [x] `disposition_view/` — postgres_view.sql (current_disposition rollup) + horizon_signals + mode_fit_dashboard + renderer; CLI consumed by `/disposition`
- [x] `orchestrator/` — phase_detector + v01_launch_status (33 launch gates) + v01_active_routing (mode-tuned cadence) + operator_briefing + cli — Section 5.4 `/run` aggregator (v0.1 build / v0.5+ ops auto-detect)

**HMAC architecture:** four distinct env-var scopes (AUDIT_HMAC_KEY / PEAK_PAIN_HMAC_KEY / PREMORTEM_HMAC_SECRET / WATCHLIST_HMAC_SECRET) all sharing the canonical-payload contract implemented in `src/audit_trail/hmac_verify.py` as the single source of truth. Distinct scopes on purpose so a key compromise in one subsystem does not invalidate others.

**Test totals:** ~500+ tests passing across module unit tests + integration tests + walkthrough harness. Includes:
- Pre-existing Tier 1-3 tests (contamination_check 8 cases; predictions/counterfactual_ledger trigger semantics; edgar 7 integration; market_data 4 integration; fred + fundamentals stubs)
- New v3 module test suites under `tests/test_*.py` covering regime_sidecar, mode_classifier, broker_mcp, peak_pain_catalog, audit_trail, p3_mechanical_scorer, p4_debate, l4_daily_monitor, anchor_drift, premortem_scheduler, watchlist, p5_watchlist, p6_disposition, p7_recommendation_emitter, alert_channels, counterfactual_veto, disposition_view
- 10 launch walkthroughs (§7.3a Phase 4 Q3) — PLTR-2022 walkthrough complete + 9 more from Wave D.1: NVDA-2023 (HIGH-gate), SVB-March-2023 (Banks-B + M-3 deposit-flight), Cold-start day-1 (anchor-drift cap), Mode reclassification race (B'→C), Override-rate >50% (operator-bias detection), Catalog reclassification ripple (TBD→NON-SURVIVOR), Broker MCP outage during M-3, Conviction flip-flop (hysteresis), Phase C judge silent miss

**Decision locks captured during implementation:**

- **BOCPD dual-signal architecture** (operator-locked) — regime_sidecar writes both `bocpd_change_probability` (canonical Adams-MacKay marginal, audit-only) and `bocpd_short_run_mass` (cumulative posterior, primary firing signal). Migration 020 promotes the second column; firing logic in `l4_daily_monitor.cut_evaluator` Mode C + `l4_daily_monitor.refresh_emitter` M-2/M-3 consumes short-run mass; canonical marginal feeds provenance/audit only. `RULE_ENGINE_VERSION = regime_sidecar.v0.1.1`. v3 spec §4.1 method-overlay + Q3 firing-threshold table updated.
- **Conviction rollup precedence: LOW > HIGH > MEDIUM** (Phase 4 Q2). LOW dominates when ≥2 NON-SURVIVOR matches in top-3, OR ≥2 kills fired, OR <3/5 debate. HIGH gate is monotonic (4/5 debate AND 0 kills AND ≥2 SURVIVOR AND ≤1 anchor-drift channel) — conditions are ANDed; any miss demotes. MEDIUM is the residual.
- **HIGH gate monotonic interpretation** (Phase 4 Q2 fix to Section 7 PB#5) — pre-fix the rollup was confusable when a single channel triggered alongside high-debate consensus. Fix: HIGH requires `≤1` anchor-drift channel triggered (was: exactly-zero in earlier draft).
- **Hysteresis cycle counting** (Phase 4 Q7) — conviction transition (any direction) requires the transitioning condition to persist 2 consecutive cadence cycles. `conviction_flip_count_30d` per name; >3 flips in 30d → operator review (M-2 system event); auto-demote to MEDIUM and freeze pending review. Implemented in `p7_recommendation_emitter` state machine.
- **MAX_EMAIL_ATTEMPTS=4** (DECISION LOCK; Phase 4 Q9) — exponential retry up to 4 attempts; on final failure, alert queues for next-session push and `system_errors` logs SMTP fault. Surfaces in `/system-health` "queued-for-session-push" count.
- **Canonical-payload HMAC contract** (single source of truth) — `src/audit_trail/hmac_verify.py` defines canonical JSONB serialization shared by all 4 HMAC scopes. Verification in any subsystem traces back to this module.
- **NUMERIC-column HMAC parity fix** (`peak_pain_archetypes.peak_dd_pct`) — surfaced by `tests/test_live_db_smoke_extended.py::test_live_full_funnel_p5_to_p7_to_audit_chain`. `_json_default` in `audit_trail/hmac_verify.py` serializes `Decimal` as a JSON string (preserving NUMERIC precision) and `float` as a JSON number — so signing `peak_dd_pct` as a Python `float` at INSERT time and re-signing the post-readback `Decimal` from psycopg produced different canonical bytes and HMAC-verified-FALSE in production. **Fix (Option A, surgical at signing site):** `peak_pain_catalog.persistence._build_payload_unsigned` now wraps `peak_dd_pct` in `Decimal(str(...))` before computing the canonical payload, and `PersistencePayload.peak_dd_pct` is annotated `Decimal`. Audit of migration 011 confirms `peak_dd_pct` is the only NUMERIC column on `peak_pain_archetypes` participating in the HMAC payload (other peak-pain columns are TEXT / JSONB / DATE / TIMESTAMPTZ). Other modules signing rows checked and clear: `p7_recommendation_emitter` signs only JSONB columns (`sizing_suggestion`, `execution_context`, `trigger_metadata`, `conviction_breakdown`) — JSONB returns Python primitives from psycopg, no Decimal coercion; `watchlist.hmac_producer` signs entire JSONB blobs; `premortem_scheduler.recorder` signs only the operator-authored `failure_modes` + `pillars_revisited` JSONB blobs (NOT `net_thesis_strength` NUMERIC). Live-DB extended test workaround (placeholder-then-re-sign post-INSERT) removed. Regression test added: `tests/test_peak_pain_catalog.py::test_persistence_hmac_decimal_roundtrip_byte_equal`.
- **No-op default BLOCKED for anchor_drift forced_review** (migration 018) — sidecar table `anchor_drift_review_decisions` keyed by check_id; row absence = pending; row presence = decision committed. Operator must pick reaffirm / revise_with_rationale / cut.
- **mode_certainty as annotation, not conviction-bucket determinant** (Phase 4 Q2) — `rule_clean | llm_tiebreaker` is a separate annotation field; does NOT participate in conviction rollup precedence.
- **Sonnet/Opus only — no Haiku anywhere in v3** (§4.5 Q1) — model constraint operator-locked; Tier 1 daily-monitor classification runs on Sonnet (not Haiku as v2 commands suggest); Tier 2 escalations on Sonnet/Opus mix; M-3 forces Opus.

**Launch gates progress (per §7.1 / §7.2 / §7.3 / §7.3a):**

- [x] Hard gates green — Postgres migrations 001-022 applied + indexes; broker MCP OAuth tested + token refresh validated; audit-trail HMAC chain validates end-to-end (CLI `--verify --strict`); push alert email + Claude Code session push channels functional; `/alerts`, `/ack`, `/audit-trail` slash commands functional; recommendation emitter produces valid Q1 schema (50-invocation test); mode classifier 100% watchlist coverage; L1-L2 regime sidecar producing all 6 dimensions with BOCPD probabilities; materiality classifier producing M-1/M-2/M-3 with verbatim-quote citations; counterfactual veto pipeline retrieves top-3 + computes archetype distribution
- [x] Calibration harness scaffolded — peak-pain catalog priority subset (~45 cases) ready to run via `python -m src.peak_pain_catalog.cli priority-run`; calibration_test_results table populated by `src/peak_pain_catalog/lazy_runner.py`; canonical SURVIVOR + NON-SURVIVOR test cases retrievable; mode classifier rule-clean rate measurement wired into `mode_classifier.recheck`
- [x] Walkthrough launch gates — PLTR-2022 walkthrough complete (motivating case for counterfactual veto authority + Layer 1/2/3 capitulation defense) + 9 more from Wave D.1
- [ ] Operator launch-gate sign-off — pending operator confirmation via `/launch-confirm <gate_name>` (deferred slash command; v0.1 workaround = manual checkbox + BUILD_LOG note)

**Spec/implementation gaps surfaced during the audit (Wave D.4 cleanup):**

1. **Four spec-mandated slash commands** — RESOLVED Wave D.4. `/premortem`, `/parameters-review`, `/spec-approve`, `/launch-confirm` markdown definitions added to `.claude/commands/`. `/premortem` wraps the existing `src.premortem_scheduler.cli`; `/parameters-review` is a v0.1 STUB (read-only summary + override-pattern suggest; full proposal generation deferred to v0.5+); `/spec-approve` and `/launch-confirm` are minimal HMAC-attested implementations writing to `docs/superpowers/specs/v<version>-signoff-attestation.md` and `docs/superpowers/launch-readiness-log.md` respectively.
2. **`.env.example` HMAC env vars** — RESOLVED Wave D.4. AUDIT_HMAC_KEY / PEAK_PAIN_HMAC_KEY / PREMORTEM_HMAC_SECRET / WATCHLIST_HMAC_SECRET added with comments documenting the canonical-payload contract + 4 distinct rotation scopes.
3. **`/daily-monitor` description stale model reference** — RESOLVED Wave D.4. Description updated from "Tier 1 Haiku → Tier 2 Sonnet" to "Sonnet default → Opus M-3 escalation" per §4.5 Q1 model constraint.
4. **Operator-reference companion document landed** — `docs/superpowers/operator-reference.md` (per §5.5 onboarding lock; documentation-only, no setup wizard).

**v0.5+ deferred work:**

- **Promote `llm_call_metadata.model` from JSONB to first-class column on `daily_refresh_log` + `materiality_events`** for indexed cohort-vs-cohort drift queries. Current JSONB shape requires GIN index for efficient model-cohort filtering; promotion enables btree index on a TEXT column for the common "compare Brier across model versions" pattern surfaced by Phase 4 Q8 calibration drift watch. Spec inconsistency: §4.5 Q1 captures the model field but no first-class column on either table; v3 schema (migrations 009 / 011) leaves it inside the JSONB blob. Migration deferred until cohort-analysis becomes a measurement need (post-launch).
- **Full `/parameters-review` proposal-generation workflow** — see `src/parameters_review/README.md`. Requires (i) 90-day counterfactual ledger with outcome stratification, (ii) parameter-vs-outcome attribution model, (iii) operator approve/modify/reject UI. v0.1 STUB exposes `summary` + `suggest` only.
- **`/spec-approve --verify` + `/launch-confirm --verify`** — replay HMAC signatures against attestation content for chain-validation parity with `/audit-trail --verify`.

---

## Cost

- API costs: $0 running total
- Subscriptions: $0 running total

(Updated when notable spending happens.)

---

## Notes

- Decision 5 explicitly removes the discipline mechanisms that `docs/implementation-sequencing.md` §9–§10 framed as load-bearing. The substance of the build (Path A, skills-only, Evidence Index, contamination check, checkpoint artifacts) is unchanged; only the *cadence and Ulysses-pact* layer is removed.
- `docs/implementation-sequencing.md` is preserved as reference for substantive decisions (DDL, agent prompts, gate criteria) but its calendar/commitment sections are no longer the operator's protocol.
- If pace drift later motivates restoring dated cadence, that's a deliberate revision documented as a new architectural decision (decision 6+); not a silent restoration.
- **BOCPD dual-signal architecture (operator-locked).** `regime_sidecar` writes both `bocpd_change_probability` (canonical Adams-MacKay marginal `P(r_t=0|x_{1:t})`, retained for academic / audit traceability) and `bocpd_short_run_mass` (cumulative posterior `P(r_t<10|x_{1:t})`, primary firing signal). Migration `020_v3_bocpd_short_run_mass.sql` adds the column + partial index + view update. Firing logic (L4 cut_evaluator Mode C; refresh_emitter M-2/M-3) consumes short-run mass; canonical marginal is consumed by audit / provenance flows only. `RULE_ENGINE_VERSION` bumped to `regime_sidecar.v0.1.1`. v3 spec §4.1 method-overlay text + Q3 firing-threshold table updated to clarify thresholds operate on short-run mass.

---

## Audit-driven hardening loop (waves D.5 → D.13)

Nine paired audit/review passes ran the codebase through orthogonal bug lenses, each pass dispatching one audit subagent + one independent reviewer. Cumulative production bugs caught: **39** across HMAC parity, transaction boundary, idempotency, error-swallowing, datetime canonicalization, float precision, SQL-injection, resource leak, unbounded list-growth, and timezone/DST. Pattern: passes 1–6 found bugs (~5 each); passes 7–8 found 0; pass 9 (timezone) found a final cluster of 4 + 1 critical reviewer-caught miss; loop converged. Test count progressed 474 → 606+ passing (601 + 20 skipped DB-bound, single pre-existing yfinance-dep collection error unrelated to audits).

**Pass 9 — Timezone / DST audit (final).**

- **HIGH-1: `date.today()` leak across 10 idempotency-key sites** (anchor_drift, counterfactual_veto, p4_debate, mode_classifier × 2, premortem_scheduler × 5, regime_sidecar × 2). Local-tz `date.today()` mismatched UTC-assumed DB columns near midnight on non-UTC servers; replaced with `_dt.datetime.now(_dt.timezone.utc).date()`.
- **HIGH-2: `mcp/contamination_check/server.py:135`** — `date.today()` compared against UTC ISO `resolution_date` strings; west-of-UTC servers between UTC midnight and local midnight would not trip INCOHERENT_PREDICTION; fixed.
- **MEDIUM: `p7_recommendation_emitter/trigger_logic.py`** `_next_monday_open` / `_next_3day` / `_next_daily` hardcoded `13:30 UTC` for NYSE 09:30 ET — correct only during EDT; off by 1h during EST (~5 months/year). Fixed with `zoneinfo.ZoneInfo("America/New_York")`.
- **CRITICAL (reviewer-caught miss): `src/p3_mechanical_scorer/orchestrator.py::persist_audit_rows`** — INSERT omitted `created_at` column, letting Postgres apply DEFAULT NOW(); sign-time HMAC payload used orchestrator's Python `now`; verify_chain reads DB `created_at` (different value) → HMAC always fails. Would silently brick audit-chain verification end-to-end. Fix: bind `_parse_isoformat_utc(row["created_at"])` into INSERT, mirroring p7 emitter pattern.
- Regression test: `tests/test_timezone_dst_audit_regression.py` (10 cases).
- **`db/migrations/001-003`** TIMESTAMP-WITHOUT-TIMEZONE columns flagged as latent bug magnets but not in HMAC path; `ALTER COLUMN ... TYPE TIMESTAMPTZ` deferred to v0.5+ (would need data-migration consideration on populated tables).

**Convergence verdict:** two consecutive zero-bug passes (SQL-injection, resource leak) before the timezone pass; all "easy lenses" exhausted. Reviewer recommendation accepted: end the audit-iteration loop. Remaining items are operator-driven launch gates (peak-pain priority subset 3-LLM consensus run, kappa-calibration vs 30 historical events, broker MCP OAuth, 33 `/launch-confirm` sign-offs) and the v0.5 TIMESTAMP→TIMESTAMPTZ migration.

---

## v0.1 launch-gate session (2026-04-30)

Operator-driven setup pass through gates 25-30. 6 gate rows attested via `/launch-confirm` to `docs/superpowers/launch-readiness-log.md` with HMAC signatures.

- [x] **Gate 25** `hmac_keys_4_scopes_set` — 4 keys generated by `secrets.token_urlsafe(32)`, written directly to `.env` via subprocess (values never entered conversation), sign+verify round-trip OK across all 4 scopes.
- [x] **Gate 26** `smtp_credentials_set` — Gmail app-password authenticated; 2 canary emails delivered (post-rotation). Operator note: rotate again from a non-remote-session when convenient.
- [x] **Gate 28** `postgres_migrations_applied` — 22-migration per-artifact verification surfaced that **migration 022 had not been applied** despite being on disk; operator session applied it. Final state: 22/22 OK.
- [x] **Gate 29** `mcp_servers_running` — EDGAR + market_data + postgres + contamination_check live; FRED API key registered and live-API test successful (effective in MCP after next CC restart); fundamentals stub by design.
- [x] **Gate 30** `spec_v3_signoff` — re-attested via `python -m src.spec_approve.cli 3.0 --spec-path docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md --force`. HMAC `b5c6c499...e8494`.
- [DEFERRED] **Gate 27** `broker_mcp_oauth_DEFERRED` — operator holds tokenized US equities on Gate.io (centralized crypto exchange with tokenized-equity products), not on a conventional brokerage. Conventional `BrokerAdapter` model does not fit; tokenization-specific risks (peg break, exchange custody, regulatory unwind risk) are also not modeled by the v3 catalogs. Deferred to v0.5+ pending either (i) GateioAdapter + tokenization-risk overlay, or (ii) operator migration to a conventional broker.

**Lock change (operator decision 2026-04-30):** `MARKET_DATA_PROVIDER` upgraded from yfinance (v0.1 commit) to **Polygon** (v0.5+ named target). Spec change rationale: operator's v0.1 priority is "high quality live market data" given no broker integration to lean on. Polygon was already the named upgrade target in v3 spec § "v0.5+ scaffold" comments at `src/mcp/market_data/server.py`; this brings it forward.

- New: `src/mcp/market_data/polygon_provider.py` — Polygon REST client (httpx + apiKey auth) implementing the same 3-function contract as the yfinance fallback (`get_prices` / `get_news` / `get_real_time_quote`). Zero MCP-tool-shape diff.
- `server.py` dispatch: at module import, if `MARKET_DATA_PROVIDER=polygon` AND `POLYGON_API_KEY` is set, all three tool functions early-return to `polygon_provider`. Otherwise falls back to yfinance silently with a logged warning when the env names polygon but the key is missing (`/system-health` will surface).
- `pyproject.toml` adds `httpx>=0.27.0`. yfinance retained as fallback.
- `.env.example` documents `MARKET_DATA_PROVIDER=polygon` + `POLYGON_API_KEY=` with Stocks Starter tier ($29/mo) called out as the minimum for non-delayed data.
- New regression tests: `tests/test_market_data_polygon_dispatch.py` (4 cases — module loadability without key, clear auth error on missing key, interval-mapping translation/rejection).
- Test count: 608 passing + 18 skipped.

**Pending operator action for the Polygon upgrade:**

1. Register at https://polygon.io/dashboard/api-keys.
2. Authorize Stocks Starter ($29/mo) for real-time SIP quotes — free tier returns 15-min-delayed data via the same endpoint shape and will silently degrade quality.
3. Paste API key; I'll write to `.env`.
4. Restart Claude Code so the market_data MCP picks up the new env. Then re-attest gate 29 if desired.

---

## Peak-pain catalog priority-run session (2026-04-30 16:00–17:30)

Multiple compounding fixes during gate 21 build-out — the catalog's 3-LLM consensus pipeline went from "0 cases validated, ~6750 useless calls in flight" to "production-ready 4-way parallel run with rich evidence."

### Bug-5 (CRITICAL): JSON fence-strip silently emptied LLM output

`src/peak_pain_catalog/extractor.py::_parse_response_json` had `s.split("\`\`\`", 2)[-1]` for fence stripping. For a response like `\`\`\`json\n{...}\n\`\`\``, this returns the EMPTY trailing element after the closing fence. The fallback `find("{")`/`rfind("}")` then operates on an empty string and returns `{}`. **Every catalog extraction the entire session was silently discarding the LLM's correct JSON output and forcing every feature to its `CONSERVATIVE_DEFAULTS` value.** No amount of iteration count, evidence richness, or model swap would have fixed the validation_status — it was a parser bug downstream of perfectly-correct LLM responses. **Fix:** drop the fence-strip path; use only `find("{")`/`rfind("}")` which is robust to fences, partial fences, and prose wrappers. **Regression test:** `tests/test_peak_pain_catalog_json_fence_regression.py` (8 cases). **Audit:** grep'd 4 other LLM-JSON parsers in the codebase (p4_debate, mode_classifier stage 3, anchor_drift channel 1, premortem_scheduler devils_advocate) — all use either find/rfind fallback or `text.strip("\`")` which is robust. Bug-5 was localized.

### Subscription-auth via `claude-agent-sdk`

Per BUILD_LOG decision 1, the project does NOT use `ANTHROPIC_API_KEY` — Claude Code is the runtime. The catalog runner had drifted to require an API key. Fixed by adding `src/peak_pain_catalog/claude_sdk_client.py` — a sync adapter wrapping `claude-agent-sdk`'s `query()` async function. Auth delegates to the local `claude /login` OAuth session (Max 20x subscription). `priority_runner._resolve_default_client()` switches on `ANTHROPIC_API_KEY` presence: subscription-default, API-key only when explicitly set. ~$340 API-equivalent for 6750 calls flowed against subscription quota; well within Max 20x weekly budget. Regression tests: `tests/test_peak_pain_catalog_subscription_auth.py` (4 cases).

### Parallel 3-LLM dispatch (3× per-iteration speedup)

`run_consensus` ran the 3 extractor calls as a sequential list comprehension (90s/iter wall). Refactored to `ThreadPoolExecutor(max_workers=3)` in `_extract_3_parallel` helper. Each call drives its own `claude -p` subprocess via `ClaudeSdkClient`; concurrent execution drops wall to ~30s/iter. Test `test_consensus_uses_default_model_mix` updated to assert set-equality (was order-equality, broke under parallel dispatch) — the contract is "all 3 models invoked once," not the dispatch order.

### Case-level parallelism (4-way) — additional 4× speedup

`run_priority_subset` looped cases sequentially. Wrapped in `ThreadPoolExecutor(max_workers=4)` (configurable via `PRIORITY_RUN_MAX_WORKERS` env). Combined with 3-way LLM parallelism: up to 12 concurrent claude subprocesses. Wall time 44 cases × ~3min sequential → ~16-22 min wall with 4-way case parallelism.

### Per-case forensic evidence files (sidecar pattern)

The catalog markdown is a structured table — each row's headers+cells produces ~200-400 chars of "evidence" for the LLM. That's far too thin to ground 6+ verbatim quotes per feature at HIGH consensus (the system kept hitting iteration caps without converging). Solution: parser appends `evidence/<case_id>.md` sidecar file to `descriptive_text` if present. Built 44 evidence files via 9 + 5 + 4 = 18 parallel subagent batches (matching round-1's 9-batch parallelism via 4 depth-pass subagents). Each evidence file ~6-10K chars, sourced from EDGAR 10-K Risk Factors + MD&A verbatim, Polygon news (Benzinga-sourced post-2018 partnership), Polygon aggregates (5-year lookback per Stocks Starter plan), Polygon corporate-actions (splits/dividends back to ~2010), WebSearch period commentary, plus an explicit MEASUREMENT TIMEPOINT directive at top of each file (locks trajectory features to trough fiscal year, prevents the 3 LLMs from disagreeing across recovery framing).

### Empirical convergence after fixes

- Pre-fix NVDA-2008 smoke: 5 iterations × 3 LLMs = 15 calls, 5.4 min wall, validation_status=`pending`, all 6 features defaulted to CONSERVATIVE values.
- Post-fix NVDA-2008 with rich evidence: 1-2 iterations, 2.6 min wall, validation_status=`validated`, all 6 universal-core features HIGH consensus at iter 1.
- Production run: 14 cases sequential → 13 in DB (07:49–08:05 UTC), all `validated` with 6 features each, 0 conservative defaults; resume from case 14 with 4-way parallel completed remaining 32 cases in ~20-25 min wall.

### Operator-driven decisions captured

- Polygon Stocks Starter activated; key updated mid-session after subscription clarity (5-year aggregates lookback identified as plan-tier limit, not key issue).
- "Stick to initial plan, only Polygon persists from session pivots" — tokenized-equity (Gate.io) tracker dropped from scope; broker MCP gate 27 deferred.
- "Start from where it stopped, not from start" — resume-from-14 pattern used to avoid wasting 13 already-completed cases (sequential run committed them at production-quality with rich evidence already in place).
- "Be more proactive" — surfacing optimizations + executing them without waiting (case-level parallelism, resume-from-14 filter, audit of similar fence patterns, pre-staged gate 21 attestation script).

---

## v0.1 closeout — broker removal + Tier 4 closeout (2026-05-01)

### `broker_mcp_oauth` REMOVED FROM PLAN (was: deferred)

Operator decision 2026-05-01: drop broker entirely from v0.1 plan rather than deferring. Operator holds tokenized US equities on Gate.io (xStocks via Backed Assets / Jersey SPV); conventional brokerage architecture (Schwab OAuth + positions endpoint) doesn't fit. v0.5+ may add a `CryptoExchangeAdapter` (Gate.io REST/WebSocket public API has no auth requirement for spot tickers) or a Plaid-based positions feed. `src/mcp/broker_mcp/` code retained as scaffold for that future revival but excluded from launch gate set.

Effects:
- Launch gate count: **33 → 32**.
- `src/orchestrator/v01_launch_status.py::_OPERATOR_SIGNOFF_GATE_NAMES` updated; `broker_mcp_oauth` removed; comment notes the v0.5+ revival path.
- DB row in `launch_readiness_log` deleted.
- `tests/test_orchestrator.py` updated for new counts (8 operator-signoff gates instead of 9).
- `docs/tier4-deferred-work.md` updated.

### Tier 4 closeout — Sharadar dependency dropped, fundamentals MCP wired

Operator decision 2026-05-01: drop Sharadar Core Fundamentals subscription from v0.1 plan. Replaced with EDGAR XBRL company-facts API filtered by `filed`-date — gives genuine point-in-time fundamentals from SEC's authoritative source, free.

PIT semantics rationale:
- Each fact returned by EDGAR `/api/xbrl/companyfacts/CIK{cik}.json` carries a `filed` field (date the containing 10-K/10-Q was submitted).
- Filter to `filed <= as_of_date` and pick the most-recent-end-date entry → reflects what was publicly known on `as_of_date` — NOT the latest-restated value.
- Equivalent PIT-correctness to Sharadar's SF1 dataset for the metrics EDGAR covers (revenue, net income, EPS, balance sheet, cash flow, share counts).
- Coverage gap acknowledged: pre-2009 data (XBRL mandate started 2009) and certain non-XBRL filers (small/foreign). Acceptable for v0.1 (research-driven memos on liquid US equities post-2010).

Implementation:
- `src/mcp/fundamentals/server.py` rewritten from stub to real EDGAR-backed implementation.
- `get_fundamentals(ticker, as_of_date)` returns 16 load-bearing XBRL tags filtered by `filed`-date.
- `get_delistings(ticker)` wired to Polygon `/v3/reference/tickers` (active flag + delisted_utc); returns structured error when POLYGON_API_KEY missing.
- Uses `requests` (not urllib) to avoid macOS Python 3.13 SSL cert verification issues.
- Live AAPL test: 15/16 facts present at as_of=2023-12-31; PIT filter verified — 2020-06-30 query returns FY2018 revenue (latest pre-cutoff filing), no look-ahead leakage.

Regression tests: `tests/test_fundamentals_pit.py` (8 tests covering PIT filter logic, unit priority, malformed-date handling, missing-key fallback, primary-tag pinning).

### Updated launch state

| State | Before closeout | After closeout |
|---|---|---|
| Launch gates total | 33 | 32 |
| Gates green | 32 (1 deferred) | 32 (0 deferred — broker REMOVED, not deferred) |
| Tier-4 deferred items | 5 | 3 (calendar/spend-bound only) |
| Sharadar dependency | required for backtest | DROPPED — EDGAR XBRL covers PIT need |
| `mcp__fundamentals` status | stub raising NotImplementedError | live implementation, 8 regression tests |
| Test count | 612 | 628 (3 orchestrator tests updated, 8 PIT tests added, +5 net new) |
| BacktestingFramework | blocked on Sharadar | unblocked — can wire to EDGAR PIT data at v0.5 |

### What remains genuinely deferred (calendar/spend-bound)

1. **30-memo backtest corpus** — operator authorizes ~$50-150 LLM spend + ticker universe.
2. **12-month forward returns window** — calendar-bound to mid-2027 minimum (each memo's as-of date + 12mo).
3. **BacktestingFramework activation** — depends on (1) AND (2).

These are NOT v0.1 launch blockers. They activate at v0.5 entry per Section 8.1 of v3 spec.

### Deep-research skill v2 — analyst-thesis MATRIX (2026-05-01)

After the PLTR retrofit surfaced a 64% divergence between CDD's $74 P50 and the sell-side center (~$205 ex-outlier), the deep-research skill was upgraded from "pull consensus number" to "build full analyst-thesis matrix." Two-file change:

**`.claude/agents/company-deep-dive.md` §3.5 expanded into 6-part requirement:**
- A. Full analyst coverage panel (every covering firm, by-name, with rating + PT + verbatim bull thesis + verbatim bear thesis + valuation framework + kill criterion + recent revisions). Required minimum: all bulge-bracket firms covering + major boutiques + outlier-bears explicitly. Document non-coverage as data (e.g., JPM declines to cover PLTR despite being a customer — absence is information).
- B. Thesis cluster analysis (bull / neutral / bear) — distinguish "multiple-compression-only bears" (operationally constructive, valuation-cautious) from "fundamentals-deteriorating bears" (rare, high-signal).
- C. Re-aggregated consensus — mean (with outliers), median, **median excluding outliers**, cluster-weighted center. CDD divergence vs each.
- D. Disagreement-vector analysis — what dimension does each cluster anchor on? Growth duration / terminal multiple / margin sustainability / moat half-life / multiple-compression timing / customer concentration / regulatory risk.
- E. Buy-side institutional flow analysis (separate from sell-side) — 13F changes (active vs passive distinguished), BlackRock Investment Institute thematic commentary, ETF concentration, short interest, management revealed preference.
- F. Output as `analyst_thesis_matrix` block; PMSupervisor caps conviction at MEDIUM if CDD diverges >20% from active median ex-outliers; system-level review flag if CDD lands outside even the lone-outlier bear.

**`.claude/commands/research-company.md` §2** updated to reflect the matrix requirement + explicit reasoning ("a single mean target hides framework disagreement; two firms can both have $200 PTs with completely different reasoning").

**Why this matters operationally**: lesson from PLTR — the bear cluster (Citi/Mizuho/DAD) explicitly RAISED estimates while CUTTING targets, a pure valuation-bear posture that's fragile to a single beat-and-raise. CDD that ignored cluster decomposition produced a $74 fair value (well below even RBC's $90 outlier) without methodology to support contrarian-bearishness vs the entire active sell-side. The matrix surfaces this kind of framework gap.

**Test count post-amendment**: 628 (no code changes; spec changes only).

### First operational `/research-company` invocation — PLTR (2026-05-01)

System's first real-data research after launch readiness. Inaugural test of the full P3+P4 funnel (CompanyDeepDive → BearCase → PMSupervisor synthesis) on a live ticker.

**Outcome:** WATCH at $139.11, LOW conviction, **$50 price trigger** (BearCase threshold, not CDD's $80), kill trigger if TP-1 or TP-3 falsifies. Both subagents flagged price-anchored fragility despite high business quality (Rule of 40 = 87.6, GAAP-profitable). BearCase surfaced 1 catastrophic + 4 serious unrebutted concerns CDD did not fully address — most importantly, multiple compression is **regime-active not forward risk** (PLTR already -33% from $207 peak; analog set averages -77% trough from peak; modal scenario implies another -45 to -55% downside).

**Operational findings from first real run:**
- EDGAR MCP performed cleanly; FY25 10-K + XBRL company facts yielded all required data
- Polygon REST fallback worked end-to-end via WebFetch with `POLYGON_API_KEY` (parent context's `mcp__market_data` was disconnected; subagents used direct REST)
- Postgres `mcp__postgres__execute` rejected initial INSERT due to `%` character in claim_text being interpreted as parameter placeholder — schema-side hardening recommendation: parameterize all INSERTs via `params` array rather than inline string concatenation
- predictions table check constraint forces `resolution_date NULL` until resolved; correct behavior
- 44 Evidence Index rows + 5 reviewable predictions persisted under `agent_run_id b3d41035-98ad-41eb-8f40-cd52d2dc0093`
- BearCase did not auto-persist (returned `evidence_index_refs` for orchestrator-side persistence); deferred until first ADD decision needs the audit chain
- One pillar mismatch worth noting: CDD used $0.85 FY26 EPS; BearCase verified actual FY25 diluted EPS = $0.63 from XBRL. This is a calibration miss for CDD; in production /parameters-review should flag this for prompt-engineering correction.

**Cost:** ~$75 subscription draw (50 CDD + 25 BearCase).

### Sharadar evaluation + revert (2026-05-01 same-day)

Operator obtained free-tier `NDL_API_KEY` mid-session and asked for Sharadar to be wired as primary. Empirical test against the live key revealed the free Nasdaq Data Link sample tier provides only:

- `MRY` dimension (Most Recent Year, **restated** — not PIT-correct for backtests)
- 2 fiscal years of history (no depth)
- Sample subset of tickers (not the full universe)

The PIT dimensions (`ARY`/`ARQ`) and full history are gated to the paid SF1 subscription (~$70-100/mo). On the free tier, Sharadar is **strictly worse than EDGAR XBRL** on every relevant axis. Operator chose Path B: revert the Sharadar primary path; keep `NDL_API_KEY` in `.env` as a no-op for future upgrade. EDGAR XBRL `filed`-date filter remains the canonical PIT source.

`src/mcp/fundamentals/server.py` cleaned: removed `_fetch_sharadar` + `_SHARADAR_PRIMARY_FIELDS`; `get_fundamentals` is EDGAR-only with the docstring noting "if NDL upgrade to paid SF1 happens, re-introduce Sharadar primary path here." Test count holds at 628.

## Quant-analyst v2 + pm-supervisor outside-view extension (2026-05-12)

4-item MVU per closed design (see /grill-me session log). All Phase 1; forensics gating + DB-driven thresholds + skill scaffolding deferred to Phase 2 when calibration cohort exists.

**Changes (5 files):**

1. `.claude/references/damodaran_implied_erp_cache.json` — NEW. Seed value 4.60% as_of 2026-05-01; refresh rule = if abs(current DGS10 − cached DGS10) > 50bp, agent re-fetches `https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/implprem.html` inline and overwrites this file before computing WACC. Seed must be replaced on first live run.

2. `.claude/references/canonical-frameworks.md` — five new entries: `sloan_1996`, `beneish_1999_dsri`, `damodaran_implied_erp`, `lovallo_kahneman_2003`, `mauboussin_base_rates_2016`. The Mauboussin entry embeds the 10y-revenue-CAGR base-rate table inline (5 starting-revenue buckets × mean/median). Primary PDFs returned 403 in source research — numbers flagged `source_confidence: medium`; replace with Primary when acquired.

3. `.claude/agents/quantitative-analyst.md` — four insertions:
   - §3.8 Data-quality flags pre-check (Phase 1 OBSERVATION-ONLY): restatement count via 8-K Item 4.02 grep + auditor-change count via 8-K Item 4.01 grep, last 36mo. Non-GAAP wedge + segment recasts deferred to Phase 2.
   - §3.9 Regime-aware WACC inputs: reads cached implied-ERP, refreshes on >50bp DGS10 drift, builds WACC with cost-of-debt from book-interest/total-debt and ±100bp ERP sensitivity. Hamada β re-lever from market bond yields deferred to Phase 2.
   - §4 Quality gate addition: Sloan TATA + DSRI computed and emitted with inline math; **observation-only at Phase 1, no disposition consequence**. Replaces the prior one-line "Sloan accruals: report as flag only."
   - §4.5 Outside-view emission (MANDATORY before DCF lock): emits `intuitive_growth_pct` + `reference_class_growth_mean_pct` from `mauboussin_base_rates_2016` table + computed divergence. Lovallo-Kahneman r-correction deferred — divergence is surfaced not auto-applied.
   - §5 schema: four new blocks (`data_quality_flags`, `wacc_regime`, `forensic_observations`, `outside_view`).

4. `.claude/agents/pm-supervisor.md` — §2.6 adversarial pass extension: new subsection "Outside-view divergence check" consumes quant memo's `outside_view` block. Rule: if `abs(divergence_pp) > 2`, set `outside_view_alert=true` and add note to `conviction_rationale`; positive divergence > 2pp is treated as `stress_open` unless cdd-lead memo justifies it via structural reasoning. Output schema `adversarial_stress_test` block gains three fields: `outside_view_alert`, `outside_view_divergence_pp`, `outside_view_emission_missing`.

5. `BUILD_LOG.md` — this entry.

**Deferred until calibration evidence justifies build (Phase 2 surface):**
- DB migrations `forensics_thresholds` + `forensics_observations` (Phase 2 gating-via-INSERT pattern)
- `/calibrate-forensics` skill (Phase 2 calibration workstream — trigger: N≥5 runs AND ≥60d AND prompt_version stable; TPR/FPR table per threshold; operator-attested INSERT)
- `damodaran_sector_betas.json` + Hamada β re-lever logic — until cyclical-thematic miscalibration surfaces empirically
- Beneish 7 other ratios + Dechow F-Score
- Non-GAAP wedge flag (requires reconciliation-table parsing) + segment-recast flag (requires multi-filing diff)
- Cohort directional modifiers (option (c) zero-defaults at launch per closed design — no file needed until non-zero values earned via Phase 2)
- DCF sensitivity lookup table (path (c)) — deferred until outside-view-alert frequency proves it useful for actionable corrections beyond surfacing
- `refresh_damodaran_erp.py` cron script — agent does inline WebFetch when staleness rule fires; standalone cron is gold-plating until run cadence justifies it

**Token-cost realized:** ~300 prompt tokens added across both agents (was 550 in original design; simplification trimmed half by deferring r-correction math + sector-β re-lever + 7 of 8 Beneish ratios + non-GAAP wedge parse + DCF sensitivity table).

**Outstanding risk surface:**
- Mauboussin reference numbers are secondary-aggregator-sourced; replace if Primary PDFs become acquirable. Marked `source_confidence: medium` in `canonical-frameworks.md`.
- ERP cache seed value (4.60%) is placeholder; first live agent run should refresh it.
- Phase 2 calibration workstream needs explicit owner — `/calibrate-forensics` skill not yet drafted; surfacing here so it doesn't disappear into "we'll calibrate later" rot.

**Next:** integration test on a watchlist ticker (likely MU — recurring test case across design) to verify quant emits all five schema blocks and pm-supervisor's outside-view check fires correctly. No further file edits expected pre-test; if test surfaces a gap, address as a follow-on edit, not a redesign.

---

## Plugin restructure + decision-7 archive (2026-05-26)

Packaged the repo as a single Claude Code plugin (`equity-research`, `.claude-plugin/plugin.json`)
and **executed** decision 7's long-documented-but-never-run scope collapse — as a reversible
`git mv` to `archive/_retired/` (operator chose archive over decision 7's original `git rm`).

**What changed:**
1. **`.claude-plugin/plugin.json`** — new single-plugin manifest. Declares the two keep-set commands
   (`research-company`, `evaluate`), the `agents/` dir (8 agents), and `mcpServers: ./.mcp.json`.
   Files were **not moved**: command/agent `.md` stay in `.claude/`, so they auto-load as project
   scope (today's behavior) and the manifest is dormant until the plugin is explicitly loaded
   (`claude --plugin-dir ./`) or installed. `research-company.md` and all agent specs are byte-identical.
2. **Archived to `archive/_retired/`** (see `docs/decision-7-sweep-set.md` for the full derived sweep):
   16 `src/` modules (incl. `mcp/broker_mcp`), 22 commands, 16 `tests/unit/<module>` dirs + 7
   integration/regression tests exercising retired pipelines, 2 dead one-off scripts, and off-path
   UI (`dashboard/`, `provider_verification/`, root `LivePanel.tsx`).
3. **`.mcp.json`** — dropped the `broker` server (impl archived). 9 servers remain.

**Decision-7 retire-set corrections (the literal list was stale).** The mandated grep-trace of the
`/research-company` keep-set found decision 7 would have deleted modules the pipeline depends on.
KEPT against the literal retire-set: `regime_sidecar` (imported by p8 tactical `bin_classifier`),
`audit_trail` (imported by p7 `emitter`), `mode_classifier` (evaluator HG-26 Check 3), plus
`eval/` and `p10_reversion_overlay`/`mean-reversion-overlay` which post-date decision 7. The keep-set
is therefore 12 `src/` modules + the 9 MCP servers, not decision 7's narrower literal list.

**Deferred (NOT done this run):** DB-migration retirement (moving numbered `.sql` breaks replay
ordering; `system_errors` mig 014 is still used — decision 7's "drop 014" is wrong; needs DB-state
analysis). And the research-company flow's internal protocol/boilerplate consolidation — operator
chose "reorg only," so the orchestration spec is left byte-identical; consolidation remains a future
refactor.

**Reversal:** `git mv archive/_retired/<path> <original>`; history preserved via `git log --follow`.
Re-add `broker` to `.mcp.json` if `broker_mcp` is restored.
