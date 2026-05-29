# Brief: execution-daemon

## Problem
The reactive CFD layer has four foundation modules — `broker-cfd-adapter` (Route), `reactive-signal-model` (Edge), `survival-gate` (Survive), `decision-trace-telemetry` (the trace) — but **nothing runs them**. They are pure/leaf modules with no driver. There is no process that, on the fast clock, enforces the §13 lexicographic chain (Survive ⊳ Preserve ⊳ Edge ⊳ Return), drives the async order lifecycle, and assembles the per-decision telemetry row. Several load-bearing contracts the foundation specs *declare* — persist-then-act, `assess` cadence, single-threaded op-state freshness, double-send guard — have **no owner**, and the telemetry row-assembly obligation (inject `run_id`/`walk_forward_window`, map substrate→trace, link decision↔fill) is currently **floating** — flagged across `reactive-signal-model` and `survival-gate` as un-owned (*"if lost, the first live write throws `run_id NOT NULL`"*). Without the daemon, the layer cannot place a single paper trade or emit a single trace.

## Current State
- **broker-cfd-adapter** — tasks approved, implementation started (MCP package scaffolded). Exposes importable leaf funcs: `submit_decision`, `get_positions`, `get_account_assets`, `get_history`, `validate_symbol`, `list_tradable_symbols`; async submit→poll→reconcile + double-send guard inside `core`.
- **reactive-signal-model** — design generated (awaiting approval). Exposes `decide(features, direction, snapshot, runtime_threshold) -> ReactiveDecision` with a `DecisionSubstrate`; explicitly defers `run_id`/`walk_forward_window` injection to this spec.
- **survival-gate** — tasks generated (awaiting approval). Exposes `admit` / `assess` / `check_capitalization`; **declares the persist-then-act + assess-cadence + single-threaded-loop contracts ON the daemon**.
- **decision-trace-telemetry** — implementation in progress (6/12). **LANDED** write API: `schema.py` (`CorrelationKeys` / `DecisionTraceRow` / `FillOutcomeRow`), `trace_writer.py` (`write_decision_trace` / `write_fill_outcome`; `conn=None` dry-run; `ON CONFLICT (trace_id) DO NOTHING` idempotency; fail-fast on missing `run_id`/`code_version`/`param_version`), `reader.py` (`query_trace`).
- **No execution-daemon module** — the §13 control flow exists only as prose in `docs/exploration-systematic-flow-architecture-2026-05-28.md` §11–§16.

## Desired Outcome
A persistent, non-LLM fast-clock process (proposed `src/reactive/daemon/`) that, per evaluation tick: enforces Survive ⊳ Preserve ⊳ Edge ⊳ Return; drives the async submit→poll→reconcile order lifecycle in **paper mode**; assembles and writes the decision + fill telemetry rows with the complete 4-key correlation contract; honors persist-then-act + `assess` cadence + single-threaded op-state freshness; force-flattens before close; manages the **full version-pinned position lifecycle with atomic hot-swap**; and exposes kill-switch / safe-mode / versioned-config-select command seams for the future `in-session-monitor`.

## Approach
**Single spec** (operator decision 2026-05-30). The per-tick control flow is one tightly-coupled loop and is **not** split across spec boundaries — splitting would invent cross-spec contracts on what is really one process (the exact maintenance cost the cross-spec sync checks exposed). Internal seams become **bounded task clusters**, each with its own inner-ring tests (P14):
- **process/scheduler/event-queue** — the single-threaded persistent loop, the `assess`-cadence timer, the after-market event queue the tuning loop drains.
- **gate-orchestrator** — the §13 walk (`assess`/`admit` → `decide` → size → `submit_decision`), persist-then-act ordering, resize-on-advisory (gate REJECT never mutates the order).
- **telemetry-row-assembler** — substrate→row mapping (`feature_values`→`signal_values`, `binding_constraint`→`gate_link`), `trace_id` mint, `run_id`/`walk_forward_window` injection, decision↔fill parent linking, derived `liq_proximity`/`stop_out`/`declined`; testable against the landed writer's `conn=None` dry-run.
- **lifecycle-manager** — flat-before-close action + verify-flat handshake; **full** version-pinned position lifecycle + atomic hot-swap version-management (per scope choice below).
- **command-surface** — kill-switch / safe-mode / versioned-config-select seams (exposed for `in-session-monitor`; the monitor itself is a downstream spec).

Leaf executor + event emitter only — **never dispatches an agent** (P1).

## Scope
- **In**: persistent single-threaded eval loop + scheduler; §13 lexicographic orchestration of the four deps; async submit→poll→reconcile + double-send-guard handling; telemetry row-assembly (decision + fill rows, full 4-key correlation, decision↔fill linking, derived gate fields); persist-then-act + `assess`-cadence enforcement; op-state freshness; flat-before-close action + verify-flat handshake; **full version-pinned position lifecycle + atomic hot-swap version-management** (operator 2026-05-30); after-market event queue (emit side); kill-switch / safe-mode / versioned-config command seams.
- **Out**: live real-money routing (paper/dry-run only, §11.5); the Survive/Edge/Return *logic* (owned by the deps — the daemon orchestrates, never re-computes margin / probability / sizing); fitting/tuning + calibration (`walkforward-tuning-loop`); the in-session supervisory LLM loop itself (`in-session-monitor`); the trace table DDL + write primitives (`decision-trace-telemetry`, landed); structural LLM self-modification.

## Boundary Candidates
- process-loop / scheduler / event-queue (the only piece with genuine concurrency + persistence concerns; where the single-threaded-loop + persist-then-act contracts bind)
- gate-orchestrator (the §13 walk)
- telemetry-row-assembler (self-contained; dry-run testable in isolation)
- lifecycle-manager (flat-before-close + version-pinned lifecycle + hot-swap)
- command-surface (the `in-session-monitor` command seams)

## Out of Boundary
- Re-computing any Survive / Edge / Return value — orchestrate-only, downstream-conservative (P7); never upsize or override a dep's verdict.
- Owning kill-switch / safe-mode **state** — `survival-gate` owns the logic; the daemon persists the emitted transitions and exposes the command seam.
- The trace table schema + write primitives — `decision-trace-telemetry` (landed); the daemon assembles rows and passes its own `conn`.
- Tuning / fitting / calibration — `walkforward-tuning-loop`.
- The `in-session-monitor`'s deliberative LLM loop — a separate downstream spec; the daemon only exposes its command seams. The deterministic reflex (gate / kill-switch / safe-mode) fires **first**, no LLM in the hot path.
- Agent dispatch / orchestration of any kind (P1, T1).

## Upstream / Downstream
- **Upstream (deps, build-order)**: `broker-cfd-adapter`, `reactive-signal-model`, `decision-trace-telemetry`, `survival-gate` — all imported in-process as leaf modules (never via MCP, §14.10).
- **Downstream**: `walkforward-tuning-loop` (drains the daemon's event queue; reads the trace via `reader.query_trace`; writes versioned params the daemon hot-swaps); `in-session-monitor` (commands through the daemon's exposed kill-switch / safe-mode / versioned-config seams).

## Existing Spec Touchpoints
- **Extends**: none (new module).
- **Adjacent**: all four foundation specs (consumes their interfaces — revalidates on any signature/shape change); `decision-trace-telemetry`'s landed `src/reactive/telemetry/` (the write API); the P2 `parameters` / `run_parameters_snapshot` machinery + the reactive-layer param-version table (the hot-swap read source).

## Constraints
- **P1** — leaf executor + event emitter, NEVER an agent dispatcher (roadmap Constraints; §14.10). A long-lived Python process is a **new shape for this repo** (all else is per-call MCP servers / slash commands) — the process model + its supervisor must stay P1-clean (not an orchestrator).
- **P2** — params pinned by value, read as a whole versioned object once per cycle (atomic pointer-flip, §14.5); no mid-cycle live re-resolution.
- **P3** — the daemon mints `run_id` (scope on a persistent process is a design-time decision — see below).
- **P7** — orchestrate-only, downstream-conservative; never upsize or override a dep's verdict.
- **P14** — inner-ring tests per internal cluster before any outer-ring scoring; the telemetry-row-assembler tests against the landed `conn=None` dry-run.
- **P15** — the daemon emits no probabilities of its own (`reactive-signal-model` owns the derived probability).
- **§13** lexicographic precedence is invariant; the deterministic reflex (survival gate / kill-switch / safe-mode) fires first, no LLM round-trip.
- **T4** — no aggregate cost cap today (a concern for the tuning batch, not the daemon's hot path, which carries no LLM cost).
- **Paper-only v0.1** (§11.5). **Full version-pinned lifecycle + hot-swap IN scope** per operator 2026-05-30 — note §14.11 #1 flagged these *"moot for the paper phase"* under §16.1 intraday-flat (the book is flat at every deploy boundary, so no overnight hold exercises version-pinning in paper). Building now is a deliberate **first-principles-target** choice; consequence: this machinery's inner-ring coverage is **partly forward-looking** (synthetic multi-version fixtures, not paper-exercised paths).
- **Design-time open questions** (resolve in `/kiro-spec-design`, not blockers to the brief): (1) DB connection/lifecycle model vs the single-threaded loop + persist-then-act (one serialized `conn` vs a dedicated write `conn`); (2) `run_id` scope (per session / day / daemon-start) + how the daemon learns the current `walk_forward_window` (read the param-version table the tuning loop writes? a window-boundary scheduler signal?); (3) event-queue substrate (DB table / file) — a shared seam with `walkforward-tuning-loop`; (4) atomic hot-swap read source — P2 `run_parameters_snapshot` vs a reactive-layer param-version table; whether the reactive `ParamSnapshot` + the survival `SurvivalParameters` are pinned jointly per cycle; (5) the flat-before-close action ↔ verify-flat retry/escalation handshake with `survival-gate`; and whether a broker-side resting/auto-close (if the CFD product supports it) makes flat-before-close structural (survives daemon death) — cross-check `broker-cfd-adapter`.
