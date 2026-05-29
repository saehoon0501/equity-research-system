# Requirements Document

## Project Description (Input)

**Who / problem.** The reactive CFD execution layer has four foundation modules — `broker-cfd-adapter` (Route), `reactive-signal-model` (Edge), `survival-gate` (Survive), and `decision-trace-telemetry` (the trace) — but **no process runs them**. Several load-bearing contracts the foundation specs *declare* — persist-then-act, `assess` cadence, single-threaded op-state freshness, double-send guard, resize-on-advisory — have **no owner**. The per-decision telemetry row-assembly obligation (mint `trace_id`, inject `run_id`/`walk_forward_window`, map substrate→trace, link decision↔fill) is currently **floating and un-owned**, flagged across the reactive and survival specs.

**Current situation.** `broker-cfd-adapter` is in implementation (MCP package scaffolded); `survival-gate` (tasks generated) and `reactive-signal-model` (design generated) are specced; `decision-trace-telemetry` has **landed its write API** (`src/reactive/telemetry/` — `schema.py`, `trace_writer.py` with `conn=None` dry-run + `ON CONFLICT` idempotency, `reader.py`). The §13 fast-clock control flow exists only as prose in `docs/exploration-systematic-flow-architecture-2026-05-28.md` §11–§16. Nothing places a paper trade or emits a trace.

**What should change.** Introduce `execution-daemon` — a **persistent, non-LLM fast-clock process** (proposed `src/reactive/daemon/`) that, per evaluation tick:
- enforces the §13 lexicographic chain **Survive ⊳ Preserve ⊳ Edge ⊳ Return** (`survival.assess`/`admit` → `reactive.decide` → `sizing_hint` → `broker.submit_decision`), the deterministic reflex firing first with no LLM in the hot path;
- drives the async **submit→poll→reconcile** order lifecycle in **paper mode** (live real-money routing out of scope, §11.5), handling the double-send guard and resize-on-advisory;
- **assembles and writes** the decision + fill telemetry rows through the landed writer — minting `trace_id`, pinning `event_ts`, injecting `run_id` + `walk_forward_window` (the previously-floating seam this spec claims), mapping `feature_values`→`signal_values` / `binding_constraint`→`gate_link`, deriving `liq_proximity`/`stop_out`/`declined`, and linking decision↔fill by `parent_trace_id`;
- honors **persist-then-act**, the **`assess` cadence** bound, and **single-threaded op-state freshness**;
- **force-flattens before close** (action; the gate owns the rule + verify-flat post-condition);
- manages the **full version-pinned position lifecycle with atomic hot-swap** (operator scope decision 2026-05-30 — built now despite §14.11 #1 noting it is "moot for the paper phase" under §16.1 intraday-flat; consequence: its inner-ring coverage is partly forward-looking);
- emits to an after-market **event queue** the tuning loop drains, and **exposes** kill-switch / safe-mode / versioned-config-select **command seams** for the future `in-session-monitor`.

**Shape.** Single spec (Path C) organized as five internal task clusters: process-loop/scheduler, gate-orchestrator, telemetry-row-assembler, lifecycle-manager, command-surface. **Leaf executor + event emitter only — never an agent dispatcher (P1).** Orchestrate-only and downstream-conservative (P7): it never re-computes margin / probability / sizing, and never upsizes or overrides a dep's verdict. Depends on all four foundation specs (imported in-process, not via MCP). Full scope, boundaries, upstream/downstream, constraints, and five non-blocking design-time open questions are in `.kiro/specs/execution-daemon/brief.md`.

## Requirements
<!-- Will be generated in /kiro-spec-requirements phase -->
