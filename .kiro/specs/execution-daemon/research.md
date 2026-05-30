# Research & Design Decisions — execution-daemon

## Summary
- **Feature**: `execution-daemon`
- **Discovery Scope**: Complex Integration (the convergence node — imports four leaf modules in-process, writes telemetry, runs a persistent loop)
- **Key Findings**:
  - All dependency entry points are **plain synchronous functions**; the repo's only `asyncio` is quarantined inside one MCP websocket server. The single-threaded blocking loop is **mandated** (survival-gate's op-state-freshness / kill-switch-TOCTOU guarantee depends on it), not merely convenient.
  - The house DB convention is direct psycopg3 with a per-module `_dsn()` and a **caller-passed `conn`**; the landed telemetry writer's `conn=None` means **dry-run**, so the daemon must own and pass its own connection. No connection pool exists in-repo.
  - The `parameters` / `parameters_active` / `run_parameters_snapshot` machinery already pins a **whole resolved key→value map per run** (REPEATABLE READ, sha256-hashed). Reactive `ParamSnapshot` and survival `SurvivalParameters` resolve from this **same** machinery (distinct namespaces) — no separate reactive-layer param table exists.
  - `walk_forward_window`'s writer (`walkforward-tuning-loop`) is **un-built** (no spec dir). The window exists only as a nullable correlation column. The daemon must inject it; for v0.1 it bootstraps from the param epoch.
  - Append-only DB table + plpgsql BEFORE-trigger guard is the unambiguous house pattern for event logs (`counterfactual_ledger`, `decision_process_trace`, `survival_gate_events`). No file-queue precedent.
  - **No persistent/daemon process exists in the repo today**; `docker-compose.yml` runs only postgres. The daemon is a genuinely new process shape — launch/supervision designed from scratch, kept P1-clean.

## Research Log

### Loop concurrency model
- **Context**: Brief Q (loop model) — asyncio vs blocking?
- **Findings**: broker `core.py` has zero `asyncio`/`async def`; `submit_decision`/`get_positions`/`get_account_assets`/`get_history` are sync. The "async submit→poll→reconcile" is the *venue's* order semantics (queue-task-id, blocking poll until confirmed/`unconfirmed`), not Python coroutines. `reactive.decide` and `survival.admit`/`assess` are pure sync leaves. Only `src/mcp/massive/server.py` uses asyncio (per-call MCP, not in the daemon's import path).
- **Implications**: eval loop = plain single-threaded blocking `while` loop + a cadence timer. survival-gate design `:77` makes single-threaded serialization a correctness requirement (op-state read-modify-write atomic per evaluation); introducing concurrency is a named revalidation trigger.

### DB connection / transaction pattern
- **Context**: Brief Q1 (connection-lifecycle model).
- **Findings**: `trace_writer.py`/`reader.py`/`regime_sidecar/persistence.py`/`supervisor/emitter.py` each declare a local `_dsn()` from `POSTGRES_*` env. Writers take `conn: Any = None`; for the **writer**, `conn=None` = dry-run (no connection opened), so a live write **requires a caller-passed `conn`**. Batch INSERT runs in one `conn.transaction()` with `ON CONFLICT (trace_id) DO NOTHING RETURNING` (idempotency). No shared pool/`get_conn` helper exists.
- **Implications**: daemon owns **one** psycopg3 connection, opened at startup via the same `_dsn()` convention, serialized through the single-threaded loop (no pool, no dedicated write conn needed — the loop already serializes). Passes `conn` explicitly to `write_decision_trace`/`write_fill_outcome`. Inherits the `conn.transaction()` atomic-batch idiom for persist-then-act.

### Parameter machinery, run_id, hot-swap source
- **Context**: Brief Q2 (run_id scope, window source) + Q4 (hot-swap read source).
- **Findings**: `run_parameters_snapshot` (mig 034) is one row per run capturing the whole resolved map + sha256 hash + `parameters_version_max`, read as a single-txn REPEATABLE READ of `parameters_active`. `run_id` is the snapshot PK; today it is **LLM-minted** by `/research-company` (no Python minting precedent). Reactive + survival params live in the same `parameters` machinery (overlay seeds in migs 038/039/043; survival adds a `survival.*` namespace) — **no separate reactive param table**.
- **Implications**: hot-swap read source = the existing machinery, read as a whole versioned object once per cycle (P2 pointer-flip), reactive + survival namespaces pinned **jointly**. `run_id` scope decision below.

### walk_forward_window provenance
- **Context**: Brief Q2 (how the daemon learns the window).
- **Findings**: exists only as a nullable TEXT correlation column (`decision_process_trace` mig 048 `:75`, `counterfactual_ledger`) and a nullable `CorrelationKeys` field; reactive design states it is not a model input/output, "supplied by the daemon." Exploration §14.6: window-advance = promotion = the after-market `walkforward-tuning-loop` writing validated versions to the P2 param-version table. **That tuning loop has no spec dir — un-built.**
- **Implications**: design-target = daemon reads the window from the pinned param epoch (advanced by the tuning loop); v0.1 = bootstrap window label tied to the param-snapshot epoch. The tuning-loop-driven advance is a **forward contract** (revalidation trigger when `walkforward-tuning-loop` lands), not existing machinery.

### Append-only event-queue substrate
- **Context**: Brief Q3 (event-queue substrate).
- **Findings**: house pattern = DB table + BEFORE-trigger guard rejecting UPDATE/DELETE (and TRUNCATE for `decision_process_trace`). No file-queue precedent (the `memos/envelopes/` JSON files are per-agent artifact handoff, not an event log).
- **Implications**: event queue = new append-only table `execution_daemon_event_queue` with the guard-trigger pattern; the tuning loop drains via SELECT + a drained-watermark. Migration coordination: 048 landed, 049/050 reserved by survival-gate → daemon takes **051+**.

### Process shape / launch / scheduler
- **Context**: Brief process-model question (P1 boundary).
- **Findings**: no persistent process in-repo; `docker-compose.yml` runs only postgres; no APScheduler/crontab/timer primitive. The brief flags the new-shape concern explicitly.
- **Implications**: launch via a new `docker compose` service (or a supervised `python -m src.reactive.daemon` entrypoint) with a restart policy; the `assess`-cadence + walk-forward-boundary scheduler is built in-cluster from a monotonic clock, kept P1-clean (leaf executor + event emitter, never an agent dispatcher).

## Architecture Pattern Evaluation
| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Single-threaded blocking loop (chosen) | One `while` loop, blocking dep calls, cadence timer, one serialized conn | Satisfies op-state-freshness mandate; simplest; matches all-sync deps | Blocking poll can stall the loop on a slow venue call | Bound poll with a timeout; surface `unconfirmed` |
| asyncio event loop | Coroutine-driven concurrency | Non-blocking I/O | **Violates** survival's single-threaded op-state guarantee; no async deps to justify it | Rejected |
| Multi-process / worker pool | Parallel evaluation | Throughput | Breaks kill-switch TOCTOU + op-state atomicity; over-built for one paper account | Rejected |

## Design Decisions

### Decision: Single-threaded blocking loop, one owned connection
- **Selected**: a plain `while` loop on a monotonic cadence; one psycopg3 connection owned by the daemon and serialized through the loop; per-cycle `conn.transaction()` for persist-then-act.
- **Rationale**: mandated by survival-gate op-state freshness; all deps are sync; no pool exists to reuse; simplest correct shape.
- **Trade-offs**: a slow blocking venue poll stalls the loop — bounded by the broker's poll timeout + `unconfirmed` outcome; acceptable for one paper account.

### Decision: `run_id` scoped to the pinned-param epoch
- **Selected**: the daemon mints a `run_id` at startup and at **each atomic hot-swap** that adopts a new param-config version. Each mint writes a new `run_parameters_snapshot` row (REPEATABLE-READ resolve of `parameters_active` over the reactive + survival namespaces). All decision/fill traces in that epoch carry that `run_id`; `walk_forward_window` moves with it.
- **Alternatives**: per-calendar-session/day (rejected — decouples run_id from the param map it should key); per-decision (rejected — defeats correlation).
- **Rationale**: aligns `run_id` with `run_parameters_snapshot`'s "one row per resolved param map" semantics (P2/P3); makes the epoch boundary = snapshot row = window advance, one coherent seam.
- **Follow-up**: confirm the snapshot-write path is reusable from Python (today it is markdown-orchestrated for `/research-company`) — this is a build item, not a reuse.

### Decision: event queue + position-version state as new append-only tables (051/052)
- **Selected**: `execution_daemon_event_queue` (mig 051) and `execution_daemon_position_version` (mig 052), both append-only with the house guard trigger. Op-state + survival events reuse `survival_gate_state` / `survival_gate_events`; the trace reuses `decision_process_trace`; the param map reuses `run_parameters_snapshot`.
- **Rationale**: adopt every existing table; build only the two genuinely new persistence concerns (a drainable event queue; per-position version pins for the version-pinned lifecycle).
- **Trade-offs**: two new migrations; coordination required so they land at 051/052 (not 048–050).

### Decision: `walk_forward_window` bootstrapped for v0.1
- **Selected**: the daemon injects `walk_forward_window` onto every `CorrelationKeys`, sourced from the pinned-param epoch with a bootstrap label for v0.1.
- **Rationale**: the writer (`walkforward-tuning-loop`) is un-built; the column is nullable; a bootstrap value satisfies the trace contract now and the tuning-loop-driven advance slots in later.
- **Follow-up**: revalidation trigger when `walkforward-tuning-loop` lands.

## Synthesis Outcomes
- **Generalization**: one `trace_assembler` interface serves both decision rows and fill rows (fill = decision + `parent_trace_id` + later `event_ts`, same correlation keys); one `commands` interface serves kill-switch / safe-mode / versioned-config-select as gated supervisory commands.
- **Build vs adopt**: ADOPT the landed telemetry writer, the `parameters`/`run_parameters_snapshot` machinery, `survival_gate_state`/`_events`, the append-only-guard trigger pattern, and the `_dsn()` psycopg3 convention. BUILD the loop/scheduler, gate-orchestrator, trace-assembler, lifecycle-manager, command-surface, and the two new tables.
- **Simplification**: one connection (no pool, no dedicated write conn — the loop serializes); no asyncio; no tuning-loop-coupled window reader now (bootstrap); no version-management machinery beyond what Req 8 demands.

## Risks & Mitigations
- **Blocking-poll stall** — a slow venue poll halts the loop, delaying `assess`. Mitigation: bound the broker poll timeout; on timeout surface `unconfirmed` and continue; `assess` cadence is a hard upper bound.
- **`run_id`/snapshot write path is markdown-orchestrated today** — no Python precedent. Mitigation: build a small Python snapshot-resolver mirroring the `/research-company` §1.5 REPEATABLE-READ read; inner-ring test it.
- **Version-pinned lifecycle is paper-moot** — its inner-ring coverage is synthetic multi-version fixtures, not paper-exercised paths (operator-accepted, brief 2026-05-30).
- **Floating window contract** — `walkforward-tuning-loop` un-built; the window-advance contract is forward-looking. Mitigation: bootstrap + revalidation trigger.
- **Migration-number collision** — must land at 051/052 (049/050 reserved by survival-gate, 048 landed). Mitigation: pin numbers in the File Structure Plan + verify against `db/migrations/` at author time.

## References
- `docs/exploration-systematic-flow-architecture-2026-05-28.md` §11–§16 — two-clock architecture, §13 lexicographic chain, §14.5/§14.6 version-pinned lifecycle + window-advance, §16.1 intraday-flat.
- `src/reactive/telemetry/{schema,trace_writer,reader}.py` — landed write/read API.
- `db/migrations/003` (counterfactual_ledger_guard), `034` (run_parameters_snapshot), `048` (decision_process_trace) — adopted patterns.
- `.kiro/specs/{broker-cfd-adapter,reactive-signal-model,survival-gate,decision-trace-telemetry}/design.md` — dependency contracts.

---

# Gap Analysis (post-design validation pass — 2026-05-30)

> Run *after* design approval as a validation pass: does the design's reuse surface match what is actually implemented today, and what is the implementation-readiness gap before `/kiro-spec-tasks`? (`/kiro-validate-gap` is normally pre-design; here it confirms the design and informs task sequencing.)

## Dependency-maturity gap (dominant finding)
The daemon is **last in build order** and imports four leaf modules in-process. Their *actual on-disk* state diverges sharply from their spec phase:

| Dependency | Spec phase | Implemented on disk? | Daemon import surface |
|---|---|---|---|
| decision-trace-telemetry | tasks-generated, ready | ✅ `src/reactive/telemetry/{schema,trace_writer,reader}.py` | `write_decision_trace` / `write_fill_outcome` callable **now** |
| broker-cfd-adapter | tasks-generated, ready | ✅ substantially — `core.py` exposes `submit_decision` / `get_positions` / `get_account_assets` / `get_history` / `validate_symbol` + full module set (config, gate_client, mappers, models, paper, symbol_cache, validation) | callable **now** (confirm exact signatures at task time — mid-implementation; keyword-only `clients=` params) |
| reactive-signal-model | tasks-generated, ready | ❌ **spec-only** — no `src/reactive/signal_model.py`; `decide()` does not exist | **MISSING** |
| survival-gate | tasks-generated, **not ready** | ❌ **spec-only** — no `src/survival/`; `admit`/`assess` do not exist | **MISSING** |

→ The daemon **cannot be wired end-to-end** until `reactive.decide` + `survival.gate` are implemented. But its dep-independent clusters **can** be built + inner-ring-tested now.

## Requirement → Asset Map (gaps tagged Missing / Unknown / Constraint)
| Req area | Existing asset to reuse | Gap |
|---|---|---|
| 4.x telemetry assembly | telemetry writer/reader/schema (landed) | **Missing** `trace_assembler` (build); writer reusable as-is + `conn=None` dry-run test seam |
| 1.4 / 8.1 param pin + hot-swap | `parameters` / `parameters_active` / `run_parameters_snapshot` (mig 004/034) | **Missing** Python resolver — the REPEATABLE-READ snapshot read is markdown-orchestrated (`/research-company` §1.5); build daemon `params` |
| 5.4 op-state + events persist | `survival_gate_state` / `_events` (survival design, migs 049/050) | **Constraint** — those tables are **not yet on disk** (survival unimplemented); daemon persist path depends on them |
| 9.1 event queue | append-only-guard pattern (mig 003/048) | **Missing** — build table mig 051 + `event_queue` |
| 8.2 / 8.3 version pin | none | **Missing** — build table mig 052 + `lifecycle` version-pin |
| 2.x / 3.x orchestration | broker `core` (present); `reactive.decide` + `survival.gate` (**Missing**) | **Blocked** on reactive + survival impl |
| 6.x flatten | survival assess directives (**Missing**); broker close (present) | **Blocked** (partial) on survival |
| connection | `_dsn()` convention (telemetry / regime_sidecar / mcp servers) | Reuse — copy local `_dsn()` |

## Implementation approach options
- **Option A (Extend existing)** — N/A: greenfield process shape, nothing to extend.
- **Option B (New, all-at-once)** — build the whole daemon once all four deps land. Clean, but serializes the entire daemon behind reactive + survival and wastes the window where dep-independent clusters are buildable.
- **Option C (Hybrid, phased) — RECOMMENDED**:
  - **Phase 1 (buildable now, no missing deps; inner-ring-first per P14):** migrations 051/052 + guards; `config` / `db` / `types`; `trace_assembler` (tested against `write_decision_trace(conn=None)` dry-run); `params` resolver (synthetic param rows); `event_queue` emit + drain contract; `commands` surface (synthetic op-state). All testable with **no** reactive/survival code.
  - **Phase 2 (gated on reactive + survival impl):** `orchestrator` (§13 wiring), `lifecycle` flatten action (needs survival `assess` directives + broker close), the end-to-end loop, integration tests.

## Effort / Risk
- `trace_assembler` — **S**, Low (landed writer + dry-run seam; pure mapping).
- `params` resolver — **M**, Medium (no Python precedent for the REPEATABLE-READ snapshot read; mirror markdown §1.5).
- migrations 051/052 + `event_queue` — **S**, Low (house guard pattern).
- `lifecycle` — **M**, Medium (version-pinned lifecycle paper-moot → synthetic fixtures; flatten gated on survival).
- `orchestrator` + end-to-end loop — **L**, **High** (blocked on two unbuilt deps; highest-coupling control flow — §13 + persist-then-act + op-state freshness).
- `commands` — **S**, Low.

## Research-needed (carry into tasks)
- Confirm broker `core` signatures at task time (sync; keyword-only `clients=`; arg names) — broker is mid-implementation and the orchestrator binds to them.
- `run_parameters_snapshot` Python write path — extract a shared resolver vs. build daemon-local.
- **Migration-number coordination** — 049/050 are reserved by survival-gate but **not yet on disk** (current max = 048); the daemon's 051/052 assume survival lands first per build order. Verify at author time; renumber only if ordering is violated.
- `walk_forward_window` advance — `walkforward-tuning-loop` un-built (v0.1 bootstrap).

## Recommendation for the tasks phase
Sequence `/kiro-spec-tasks` as **Option C**: a **Phase-1 task cluster** (dep-independent, buildable now, inner-ring-first) and a **Phase-2 cluster** (orchestrator + lifecycle + e2e) explicitly marked **blocked-on-deps** (reactive-signal-model + survival-gate implementation) so it is not started prematurely. The design itself needs no change — it already encodes the reuse decisions; this pass only adds the build-readiness sequencing.

---

# Gap Analysis — Refresh 2 (downstream consumers landed — 2026-05-30)

> Re-run because the picture shifted *after* Refresh 1: the daemon's two **downstream consumers** — `walkforward-tuning-loop` (requirements R1–R10) and `in-session-monitor` (brief + init) — now exist and have **reconciled their seams against the daemon's approved design**. This converts two of the daemon's previously-floating forward contracts into cross-checked seams **and surfaces one real gap in the approved design** (Refresh 1 predated these consumer specs).

## What changed since Refresh 1
- **broker-cfd-adapter** advanced materially: 4.2 decision routing + live-send gate, 4.3 async submit→poll→reconcile + double-send guard, 5.1 FastMCP server (6 tools). The daemon's broker import surface is now firmer (confirm exact sync signatures + keyword-only `clients=` at task time).
- **reactive-signal-model + survival-gate STILL spec-only** (no `src/reactive/signal_model.py`, no `src/survival/`). **Phase-2 blocker UNCHANGED.**

## Forward contracts now RESOLVED from the consumer side
- **`walk_forward_window` advance** (was Research-Needed / forward contract) → **aligned, bootstrap-until-tuner.** `walkforward-tuning-loop` Req 7.3 publishes the advanced window *alongside the promoted version* in the P2 registry, "such that the execution-daemon re-sources it at its next hot-swap." Daemon `params` reads it from the registry at hot-swap; the v0.1 bootstrap bridges only until the tuner first runs. Shape now pinned both sides.
- **Event-queue drain** → **confirmed, single-drainer.** `walkforward-tuning-loop` Req 10.2 ("consume/drain… not own the emit side") + the in-session-monitor brief pin the tuner as the **sole `drained_at` setter** (SELECT + watermark) of mig-051 `execution_daemon_event_queue`. Confirms the daemon's emit-side design; **adds a hard constraint: exactly one drainer** — the in-session-monitor must NOT become a second drainer (needs a read-only, non-draining view if it reads events in-session).

## NEW GAP — command **transport** (a hole in the *approved* daemon design)
- The approved design exposes the command surface as **in-process `commands.py` seams** ("when a supervisory command is received", Req 9.2/9.3). But the `in-session-monitor` is an **out-of-process markdown Claude Code orchestration**, and the daemon is a **persistent Python process that is NOT an MCP server** (§14.10) → **there is no defined channel for how a command actually reaches the daemon.** The monitor brief calls this "the biggest unresolved seam."
  - **kill-switch / safe-mode**: plausibly via shared state the daemon reads fresh each loop (reuse the Operator's halt channel — itself not yet defined).
  - **`select-validated-config`**: the real hole — the daemon adopts the *latest* published version at hot-swap (Req 8/9.4); there is **no inbound channel to force a specific non-latest, safer version.**
- **Tag**: Research-Needed → **`execution-daemon` design follow-up.** The rest of the design is sound; this one cluster (`commands` intake) is under-specified.
- **Options**: (a) **daemon-owned inbound command table** polled each loop — symmetric with the outbound mig-051 queue, P1-clean (daemon reads its own table; the monitor INSERTs a gated command row); (b) shared op-state for kill-switch/safe-mode + a separate config-selection table for the version pin; (c) v0.1-minimal — ship only the Operator kill-switch channel now and defer config-transport (the monitor is terminal/last in build order). Recommend (a) — one auditable intake mirroring the one auditable outbound queue.

## NEW ambiguity — `select-validated-config` toward-safer (P7) guard
- Shared-ownership question the monitor brief leaves open: does the **daemon** enforce that a selected config is *toward-safer* (P7), or does the **monitor** carry that obligation alone? The approved daemon design did not assign it. Recommend the daemon enforce toward-safer **at intake** (downstream-conservative, P7) so a buggy/compromised monitor cannot loosen — resolve in the same design follow-up.

## Requirement → Asset delta (vs Refresh 1)
| Req area | Status change |
|---|---|
| 4.2 `walk_forward_window` inject | Unknown → **aligned** (tuner publishes; daemon re-sources at hot-swap) |
| 9.1 event queue | Missing → **build, single-drainer** semantics now mandatory |
| 9.2/9.3 command surface | **Constraint → GAP**: in-process seams defined, **inbound transport undefined** for the out-of-process commander |
| 2.x/3.x orchestration; 6.x flatten | **Blocked** on reactive + survival — unchanged |

## Recommendation
1. **Before** `/kiro-spec-tasks` locks the `commands` cluster, run a scoped **`/kiro-spec-design execution-daemon` follow-up** (or a design addendum) to pin the command-transport intake + the toward-safer guard. Everything else in the design stands.
2. Then `/kiro-spec-tasks` with the same Option-C phasing; the `event_queue` task must encode **single-drainer** (`drained_at` = tuner only) and the `commands` task must include the chosen inbound-transport mechanism.
3. Effort/Risk delta: inbound command-transport = new **S/M**, **Medium** (cross-process seam, P1 placement). All other items unchanged from Refresh 1.

---

# Design Follow-up — R2 resolution (design.md Revision 2, 2026-05-30)

The command-transport gap + the two consumer-resolved forward contracts are now folded into `design.md` Revision 2 (re-approval required; `design.approved` reset to false).

- **Decision — command transport = a daemon-owned inbound `execution_daemon_command_intake` table** (Refresh-2 option (a)). The out-of-process commander (`in-session-monitor` / Operator) INSERTs a gated command row; the daemon **polls it first each cycle**, validates (gated seam only; reject direct mutation; **toward-safer guard**), applies via an op-state write / version-select, and marks `applied`/`rejected`. Symmetric with the outbound mig-051 event queue — one auditable intake, one auditable emit. The daemon is the sole reader/applier; the commander is the sole inserter (state-guard whitelist on `applied_at`/`status`/`reject_reason`).
- **Decision — co-locate `command_intake` in mig 052** (with `position_version`), keeping the daemon at **051/052** and avoiding a 053+ renumber cascade through `walkforward-tuning-loop` (053+) and `in-session-monitor` (≥054). Roadmap ledger unchanged.
- **Decision — toward-safer (P7) enforced at the daemon intake**: `set-safe-mode-grade` tighten-only; `select-validated-config` must name a P2-registry member and must not loosen survival. A buggy/compromised monitor cannot loosen — downstream-conservative.
- **Resolved — `walk_forward_window`**: re-sourced from the P2 registry at hot-swap (the tuner publishes it alongside the promoted version per its Req 7.3); v0.1 bootstrap label until the tuner first publishes.
- **Resolved — event queue is emit-only, single external drainer**: the tuner is the sole `drained_at` setter; the daemon never drains; `in-session-monitor` (if it reads events in-session) must use a non-draining SELECT.
- **Synthesis**: generalized `commands` into one intake+gated-apply surface (poll → validate → apply → mark) covering all three command types; adopted the existing append-only-guard + state-guard-whitelist patterns for the intake table (build-vs-adopt); no new file vs R1 (the intake-poll lives in `commands.py`).

---

# Design Follow-up — R2.1 (validate-design GO-with-conditions — 2026-05-30)

`/kiro-validate-design` returned **GO (conditional)** with 3 critical issues; resolved into `design.md` Revision 2.1 (re-approval still required — `design.approved` stays false).

- **Issue 1 — `run_id`/snapshot semantics mismatch → option (b), operator-chosen.** The daemon now owns a new `execution_daemon_epoch` table (`epoch_id` = `run_id`, pinned-hash, window, open/close; mig 052 co-located → still 051/052) **instead of reusing `run_parameters_snapshot`**. Keeps the LLM `/research-company` run lifecycle (`run_status` in_progress/failed) + the P6 orphan reconciler uncontaminated. `params` writes the epoch table, not the snapshot table.
- **Issue 2 — Phase-2 readiness not encoded → resolved + narrowed.** git re-check 2026-05-30: **`reactive.decide` now LANDED** (`src/reactive/signal_model.py` + features/params/types + unit tests, Phase-1 inner-ring merged at `7ab701f`); **`survival.gate` still spec-only** (no `src/survival/`, `ready=False`). So Phase 2 (orchestrator + lifecycle + e2e) is blocked on **survival-gate only**, not two deps. Encoded as a §Build Phasing section; `/kiro-spec-tasks` must mark Phase-2 sub-tasks `_Depends:_` blocked-on-survival-gate.
- **Issue 3 — command-intake write-auth → noted, no in-repo precedent.** grep found no `GRANT`/`CREATE ROLE` pattern in migrations/src. Mandate: a dedicated DB role/grant for the commander + an `issued_by` allowlist before any live cutover; v0.1 paper accepts a documented permissive default; the residual **halt-DoS via spurious `engage_kill_switch`** is accepted eyes-open (the toward-safer guard already prevents loosening).
