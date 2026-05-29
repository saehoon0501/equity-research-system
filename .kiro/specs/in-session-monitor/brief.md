# Brief: in-session-monitor

> Source of record: `docs/exploration-systematic-flow-architecture-2026-05-28.md` §15 (the §14.3 revision that introduced the in-session LLM), with §14.7 (calibration as the named behavioral diagnostic), §14.8 (telemetry substrate + correlation keys), §14.10 (P1 placement), §14.11 #2/#4 (autonomy + no aggregate cost cap). Placement was flagged "confirmed at discovery" — **confirmed here as a distinct spec** (§15 recommendation + roadmap dependency-order entry, doubly-sourced).

## Problem

The committed build pushes **autonomous LLM authority into the live levered session** (§15), stacked on **autonomous between-session promotion** (§14.11 #2) — two compounding expansions of LLM blast-radius into real money, with the §11.5 kill switch + deterministic survival gate as the *entire* backstop. But that deterministic reflex only catches the **hard-survival** band (margin-distance breach). Subtler behavioral degradation — e.g. the softmax **calibration breaking down** (a stated 70% no longer realizing ~70%) while the model is *still inside survival limits* — goes uncaught. The after-market `walkforward-tuning-loop` would catch it, but its walk-forward boundaries are **weeks apart** (§14.6, significance-sized per PSR/MinTRL). So a model that has silently drifted out of its calibrated envelope keeps firing orders at retail latency for weeks, with no human in the loop and nothing reading its behavior intra-session.

## Current State

- **Landed:** `decision-trace-telemetry` shipped the model-process trace + the **4 correlation keys** (`run_id, code_version, param_version, walk_forward_window`) and the append-only reader surface (mig 048). Calibration (Brier / reliability) is the *named* behavioral diagnostic (§14.7).
- **Landed 2026-05-30 (seams now reconciled — see §Reconciliation):** `execution-daemon` (requirements + design **approved**) is the monitored process; it owns the safe-mode + timed-flatten actions, the atomic hot-swap, and exposes the **command surface** this loop commands (three seams: `engage-kill-switch` / `set-safe-mode-grade` / `select-validated-config`). `walkforward-tuning-loop` (requirements generated) populates + OOS-validates the config menu and writes it to the **P2 param-version registry**. Both name `in-session-monitor` as a first-class downstream consumer.
- **Foundation:** `survival-gate` owns the deterministic Survive reflex + kill switch (fires first); `broker-cfd-adapter` owns order/fill mechanics.
- **Gap:** §14.3 originally said "no LLM in-session, not even for anomalies." §15 **overturned** that for *monitoring + intervention* (fitting stays after-market). Nothing yet reads telemetry intra-session to catch sub-survival drift and intervene. This spec fills exactly that gap.

## Desired Outcome

A scheduled in-session LLM supervisory loop that, on a regular cadence:
1. **Reads** recent decision-trace telemetry + the calibration diagnostic;
2. **Judges** whether the model is behaving inside its calibrated envelope (derived from Brier/reliability, P15 — never an asserted confidence);
3. **Intervenes when it isn't** — by *commanding existing deterministic mechanisms only* (halt / tighten / select a safer already-validated config), then resumes;
4. **Audits** every intervention with a falsifiable rationale (P11 envelope + HG validator; P15), correlated to the model trace via the 4 shared keys.

The deterministic reflex still fires first; the LLM never sits in the survival hot path — it is the slower deliberative **second line** that catches drift the reflex can't see.

## Approach

A **distinct scheduled Claude Code orchestration spec** (markdown per P1 — a vanilla orchestration like the tuning loop, §14.10), **sibling to `walkforward-tuning-loop`**, fired on a regular in-session cadence by a scheduler. It is **never dispatched by the daemon** (P1 / §14.10 — the daemon is a leaf executor + event emitter, not an agent dispatcher).

Two-loop separation (§15 consequence): the after-market tuning loop **populates and validates** the config menu; this monitor **selects from** that menu (+ halt / tighten) and **never fits**. The shared seam is the **P2 param-version registry**. **Selection vs. deployment are split (confirmed by the daemon's approved design 2026-05-30):** this monitor **commands `select-validated-config`**; the **`execution-daemon` performs the atomic hot-swap** (its Req 9.4 — `commands` + `lifecycle`). The monitor never pointer-flips the version itself — it issues a gated selection command and the daemon adopts it (§14.5).

**"Fix" scope is operator-locked to reading #2** (§15): (a) *operational* — halt / flatten / restart a wedged component, clear bad state; **and** (b) *apply a pre-validated config* — select among validated param sets / tighten to a safer known version, then resume. It may **NOT** fit new values live (reading #3 rejected — no out-of-sample exists intra-session, §14.4).

**Central invariant (§15):** intervention is expressed **only as commands into the existing deterministic mechanisms** — kill switch (§11.5), reproducible safe-mode (§14.3), versioned-config-select (§14.5 / P2) — **never a new direct-mutation path**. One auditable halt path.

## Scope

- **In**:
  - The scheduled-cadence supervisory loop + its control flow.
  - Behavioral judgment over telemetry: calibration / reliability drift and behavior-envelope drift *while still inside survival limits*.
  - Intervention authority = "fix" scope #2 (operational halt/flatten/restart + apply-pre-validated-config / tighten), expressed via existing mechanisms only.
  - Its own **intervention-audit** record — why it halted/tightened/selected a config — falsifiable (P15), with its own envelope + HG validator (P11), correlated via the 4 keys.
- **Out**:
  - Fitting or validating any new param/code version (that is `walkforward-tuning-loop`, under §14.4 OOS discipline).
  - The hard-survival deterministic reflex / Survive branch (survival-gate + daemon — fires first, no LLM round-trip).
  - Owning the kill-switch / safe-mode / config-select *mechanisms* themselves (it commands them; it owns none).
  - The model-trace schema + correlation keys (decision-trace-telemetry).
  - Order-trigger / fill mechanics (execution-daemon / broker-cfd-adapter).
  - Gap-risk / real-time per-instrument halt detection (survival-gate domain, out of boundary per R7) — explicitly **not** this spec's concern.

## Boundary Candidates

- The scheduled-cadence trigger + loop driver.
- The behavioral-judgment surface (telemetry read → calibration-drift / envelope-drift detection).
- The intervention-command surface (judgment → existing-mechanism command mapping; halt / tighten / select-validated-config).
- The intervention-audit envelope + its HG validator (P11).

## Out of Boundary

- **Fitting / validating configs** — selects from the validated menu, never populates or validates it (the sharpest line vs `walkforward-tuning-loop`).
- **Hard-survival enforcement** — the deterministic reflex owns the Survive band and fires first; the LLM never blocks survival on a round-trip (the line vs `survival-gate`).
- **New direct-mutation paths** — any intervention not routed through kill-switch / safe-mode / versioned-config-select is out of bounds (§15 invariant).
- **Gap / halt detection**, order/fill mechanics, and the timed-flatten *action* (other specs).

## Upstream / Downstream

- **Upstream**:
  - `decision-trace-telemetry` — reads recent model trace + the calibration diagnostic; consumes the 4 correlation keys.
  - `execution-daemon` — the monitored process; exposes the **command surface** this loop commands, now pinned to **three gated seams** (`commands.py`): `engage-kill-switch`, `set-safe-mode-grade`, `select-validated-config`. Daemon-enforced contracts the monitor inherits: commands apply **only** through these paths and any **direct position/value mutation is rejected** (daemon Req 9.3); a tightened safe-mode grade is reflected but the daemon **never self-loosens** (Req 7.4 — loosening only via the explicit operator/after-market path); the **deterministic reflex (kill-switch/safe-mode) applies before and independently of any supervisory input** (Req 7.3 — reflex-first); a `select-validated-config` is adopted **via the daemon's atomic hot-swap** (Req 9.4).
  - `walkforward-tuning-loop` — populates + OOS-validates the config menu this loop selects from; writes the P2 param-version table this loop pointer-flips among.
- **Downstream**: none — **terminal in the build order** (last spec). Its audit record is read by the operator and joinable into the after-market tuner's context via the shared keys, but no spec depends on it.

## Existing Spec Touchpoints

- **Extends**: none (new).
- **Adjacent**:
  - `survival-gate` — *not* a roadmap dependency of this spec, but **touched**: the kill switch is survival-gate's mechanism, and the **reflex-fires-first ordering** is the boundary line (deterministic Survive reflex first; this LLM is the slower second line catching sub-survival drift). Do not duplicate or pre-empt the reflex.
  - The **P2 param-version table** — shared seam with `walkforward-tuning-loop` (write-vs-select; §14.5 atomic pointer-flip).
  - The `src/eval/gates/` HG-validator pattern — this spec gets its own per P11.
  - The scheduler/cron dispatch pattern (§14.9) — same shape as the tuning loop's after-market trigger, run intra-session here.

## Constraints

- **P1** — markdown orchestration; scheduled Claude Code loop, not a Python orchestrator; never daemon-dispatched (§14.10).
- **§15 design invariant** — commands into existing mechanisms only (kill switch / safe-mode / versioned-config-select); no new mutation path; deterministic reflex fires first, LLM is the second line.
- **§14.4 / §15 two-loop separation** — selects from the validated menu; never fits or validates.
- **P7** — interventions only ever *more* conservative (halt / tighten / select-safer); never loosen.
- **P11** — owns its own intervention-audit envelope + HG validator (the *why* of intervention lives here, not in `decision-trace-telemetry`, per §14.8).
- **P15** — drift/anomaly flags **derived** from calibration (Brier/reliability); never an asserted `P(X)≈N%`.
- **§13** — the monitor's only lexicographic relationship is the reflex-first ordering; it does not itself enforce Survive.
- **T4 / §14.11 #4** — **no aggregate cost cap**; the in-session monitor cadence has no aggregate halt (eyes-open risk-acceptance — cadence × cost is unbounded, so cadence must be set conservatively).
- **Correlation contract** — audit correlates to the model trace via the **landed 4 keys**: `run_id, code_version, param_version, walk_forward_window` (mig 048 / `decision-trace-telemetry` schema). A rename either side is a cross-spec break.
- **v0.1 paper-only** (§11.5 / §16.1) — full in-session autonomy is acceptable only in the paper/challenger phase; before any live real-money cutover the gates + kill switch must be proven green (P14 + §11.5).

## Open Questions (defer to design)

- **Trigger model (still open, now concrete).** Fixed-interval scheduled cadence (pull telemetry on a clock — the inferable default from §15 "regular in-session cadence" + §14.8) vs. a **hybrid** that *also* consumes daemon-emitted anomaly events. ⚠️ The caveat is now **confirmed and sharpened by the landed daemon design:** the daemon's `execution_daemon_event_queue` (mig 051; event_types include `command | safe_mode | kill_switch`) is **drained after-market by `walkforward-tuning-loop`** — that loop is the single `drained_at` setter (SELECT + watermark). It is **not** the monitor's queue. So a hybrid in-session push must be designed around that contention: either a **read-only, non-draining** view of recent events (never touch `drained_at`) or a separate in-session signal — a second drainer would corrupt the tuner's watermark. Decide explicitly at design; do **not** make the monitor a second drainer.
- **⚠️ Command *transport* — the biggest unresolved seam (semantics pinned, transport is not).** The daemon's command surface is exposed as **in-process `commands.py` seams** (daemon Req 9.2 "expose seams"; Req 9.3 "when a command is *received*"). But the monitor is a **markdown Claude Code orchestration** and the daemon is a **persistent Python process that is not an MCP server** (§14.10 — "MCP is the Claude→tool seam, not a daemon→tool one"): separate process, no in-process call path. So *how a command actually reaches the daemon* is undefined in the landed daemon spec. It splits:
  - **kill-switch / safe-mode** — plausibly via **shared state** the daemon reads fresh each loop (survival-gate's op-state-freshness guarantee exists precisely so "a just-engaged kill switch is observed by every subsequent admit"). The monitor should reuse **whatever channel the Operator uses to halt the daemon** (daemon req: Operator "halts it") — that channel is itself not yet defined.
  - **select-validated-config** — the real hole. The daemon adopts the *latest published* version from the registry at hot-swap (daemon Req 8/9.4); there is **no defined channel for "force this specific (non-latest, safer) version."** That inbound channel likely needs its own table — and because the daemon owns inbound the way it owns the outbound mig-051 queue, that table is probably the **daemon's**, not the monitor's (softening the ≥054 math below — the monitor's *audit* table is separate from any *command-intake* table).
  Resolve at design, coordinating a possible `execution-daemon` design follow-up.
- **Cadence value.** How often the loop fires — design-time, bounded by T4 (no aggregate cost cap → set conservatively).
- **Audit-store shape + migration number.** If the P11 intervention-audit is a DB table (vs. a JSON envelope on disk), it must claim a migration **≥ 054** — `048` (telemetry) / `049–050` (survival-gate) / `051–052` (execution-daemon) / `053+` (walkforward tuner-audit) are taken; coordinate the exact number with `walkforward-tuning-loop` (which claimed "053+" un-pinned). Note the monitor's audit owns only the **why**; the **what** of each command is already emitted by the daemon as a `command`/`safe_mode`/`kill_switch` event — the two join via the 4 keys, so do not re-record the command itself.

### Reconciliation (2026-05-30 — execution-daemon + walkforward-tuning-loop landed)
The two seams above were marked "shapes not yet pinned"; both landed specs resolve them and name `in-session-monitor` explicitly. Net result — **no boundary contradiction; three refinements folded in above:**
1. **Command surface *semantics* pinned** to the daemon's three gated seams + the Req 7.3/7.4/9.3/9.4 contracts (reflex-first, no-self-loosen, reject-direct-mutation, adopt-via-hot-swap). The §15 "commands-into-existing-mechanisms only" invariant is exactly what the daemon enforces — confirmation, not change. **But the command *transport* is not pinned** (the daemon exposes in-process seams; the monitor is an out-of-process markdown orchestration, no MCP) — see the ⚠️ Command transport open question, the biggest remaining seam.
2. **Selection vs. deployment split corrected** — monitor commands `select-validated-config`; the daemon owns the atomic hot-swap (the brief previously said the monitor "pointer-flips").
3. **Trigger/queue contention made concrete** — the anomaly queue is the tuner's after-market drain target (mig 051, single `drained_at` setter); the monitor must not become a second drainer.

Remaining revalidation triggers (re-check when these change): the daemon's `commands.py` seam signatures + the `select-validated-config` direction-of-change guard (does the daemon enforce *toward-safer*, or does the monitor carry that P7 obligation alone?); the P2 param-version **registry shape** (deferred to `walkforward-tuning-loop` design — the "menu" the monitor selects from is not yet a pinned schema).
