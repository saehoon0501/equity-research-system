"""In-Session Monitor: the intervention decision (leaf).

The pure-map decision leaf — `decide(verdict, active, menu, params) ->
InterventionIntent` — that turns the judge's `EnvelopeVerdict` into one of the
bounded §15 reading-#2 intervention intents (design §Leaf — intervene). It owns
the verdict→intent MAPPING and the conservative-only guard; it neither computes
the verdict (judge) nor carries the command (command_writer). Satisfies
requirements 3.1 (operational authority — halt / tighten), 3.2 (select a
pre-validated config), 3.3 (never fit / never select-unvalidated), 5.1
(conservative-only), 9.3 (select only from the published validated-version menu).

The verdict→intent mapping (design §Leaf — intervene; severity-banded — the bands
themselves are P2-pinned and applied upstream in the judge, so this leaf reads a
discrete `Severity`, never a raw number — P15):

  * IN_ENVELOPE / INSUFFICIENT             -> NONE (no actionable drift).
  * `severe` DRIFTED (calibration collapse) -> HALT_NEW_ENTRIES (engage-kill-switch).
  * `mild` DRIFTED                          -> SELECT_SAFER_CONFIG if the validated
                                               menu offers a distinct candidate,
                                               else TIGHTEN_SAFE_MODE — the
                                               least-disruptive action that
                                               restores the envelope.

THREE structural invariants:

  1. Conservative-only (R5.1). A move is admitted ONLY when it is STRICTLY more
     conservative than the live state — i.e. `verdict.severity > active.severity`
     on the SHARED `Severity` ordering (`EnvelopeVerdict.severity` and
     `ActiveState.severity` carry the same `IntEnum` precisely so this is one
     comparison, design §Leaf — intervene: "`result.severity <= active.severity`
     is the conservative-only guard"). Anything not-more-conservative is rejected
     to NONE. This is redundant with the daemon's toward-safer guard (defense in
     depth, P6) — the monitor never relies on it alone.

  2. Menu-only / toward-safer (R9.3, R3.3). `SELECT_SAFER_CONFIG` is chosen ONLY
     when the validated-version `menu` contains a member DISTINCT from
     `active.version`. The menu is the P2 `parameters` machinery published by
     `walkforward-tuning-loop` (design Revalidation — RESOLVED 2026-05-30); the
     daemon re-validates membership + non-survival-loosening at apply-time.

  3. Never-fit (R1.4, R3.3). `decide` NEVER parses / ranks version strings to
     invent a "safer" version — `VersionRef` has no safety field, and ranking
     would BE fitting (the thing never-fit forbids). The candidate predicate is
     PURELY STRUCTURAL: *is there a validated member other than the active one?*
     The concrete never-fit behaviour is `mild DRIFTED + no distinct candidate ->
     TIGHTEN_SAFE_MODE`, never SELECT.

SCOPE (design §Requirements Traceability — `decide` owns R5.1 only):
  * It does NOT branch on `active.kill_switch_engaged` / `active.safe_mode_grade`
    — R5.2 ("don't relax an engaged reflex") is the command_writer's, Phase 2.
    The severity comparison is `decide`'s WHOLE guard.
  * It does NOT emit the wedged-component `operator_action_required` flag — that
    is an `InterventionAudit` field set by the audit leaf / orchestrator; none of
    `decide`'s inputs carry a wedged signal. `decide`'s slice of the
    wedged-component response (design §Leaf — intervene) is just the `severe ->
    HALT_NEW_ENTRIES` it already produces.

`params` is part of the design signature but `decide` is a pure severity→intent
map: severity is already banded by the judge and no `MonitorParams` field drives
the intent choice or the menu predicate, so it is accepted and unused (kept to
honour the contract, not to fabricate a params-driven branch).

Pure leaf (P1): stdlib + own-layer `types` only — no DB, no MCP, no LLM, no
metrics recompute. Dependency direction (design §Allowed Dependencies): `types →
diagnostic → judge → intervene → ...` — imports only `types`, nothing downward,
nothing from execution-daemon / walkforward-tuning-loop.
"""

from __future__ import annotations

from src.reactive.monitor.types import (
    ActiveState,
    EnvelopeState,
    EnvelopeVerdict,
    InterventionIntent,
    MonitorParams,
    Severity,
    VersionRef,
)


def _has_safer_candidate(menu: list[VersionRef], active: VersionRef) -> bool:
    """Structural menu predicate (never-fit): does the validated-version `menu`
    contain a member DISTINCT from the active version?

    Purely structural identity comparison — NO version-string ranking, NO
    "safety" parsing (that would be fitting, R1.4/R3.3). `VersionRef` is a frozen
    dataclass so equality is by-value over its three version keys; any member that
    is not equal to `active` is a distinct validated candidate the monitor may
    select toward (the daemon re-validates not-loosening at apply-time, R9.3)."""
    return any(ref != active for ref in menu)


def decide(
    verdict: EnvelopeVerdict,
    active: ActiveState,
    menu: list[VersionRef],
    params: MonitorParams,
) -> InterventionIntent:
    """Map an `EnvelopeVerdict` to a bounded `InterventionIntent` (design §Leaf).

    Pure: reads its inputs, mutates none, returns one of the four
    `InterventionIntent` members. Precedence:

      1. State gate — only a DRIFTED verdict is actionable; IN_ENVELOPE /
         INSUFFICIENT -> NONE (R2.4 / no actionable drift).
      2. Conservative-only guard (R5.1) — reject to NONE unless the verdict's
         banded severity is STRICTLY more conservative than the live
         `active.severity` (shared `Severity` ordering). This also absorbs a
         defensive DRIFTED+NONE: NONE is never `>` any active severity.
      3. Severity band -> intent: SEVERE -> HALT_NEW_ENTRIES; MILD ->
         SELECT_SAFER_CONFIG if the menu offers a distinct validated candidate,
         else TIGHTEN_SAFE_MODE.

    Args:
        verdict: the judge's `EnvelopeVerdict` (state + banded severity).
        active: the live state intervene must not loosen (`active.severity` is the
            conservative-only reference; `kill_switch_engaged` / `safe_mode_grade`
            are NOT consulted here — R5.2 is Phase-2 command_writer).
        menu: the validated-version menu (P2 `parameters` machinery published by
            walkforward); `SELECT_SAFER_CONFIG` selects only a member distinct
            from `active.version`, toward-safer, never fitting (R9.3 / R3.3).
        params: P2-pinned knobs — part of the design signature; unused (the
            severity is already banded upstream; no knob drives this map).

    Returns:
        One of EXACTLY four `InterventionIntent` members — the operator-granted
        authority bound (a fifth would mint authority beyond §15 reading #2).
    """
    del params  # design-signature parameter; this pure map binds no numeric knob.

    # Precedence 1 — state gate: only DRIFTED is actionable.
    if verdict.state is not EnvelopeState.DRIFTED:
        return InterventionIntent.NONE

    # Precedence 2 — conservative-only guard (R5.1): admit ONLY a strictly
    # more-conservative move. `verdict.severity <= active.severity` means the move
    # would not increase conservatism (equal or looser) -> reject to NONE. The
    # shared `Severity` IntEnum makes this one comparison (no intent→grade table).
    if verdict.severity <= active.severity:
        return InterventionIntent.NONE

    # Precedence 3 — severity band -> intent.
    if verdict.severity is Severity.SEVERE:
        # Calibration collapse -> halt new entries (engage-kill-switch).
        return InterventionIntent.HALT_NEW_ENTRIES

    # MILD: select a safer validated config if one exists (structural, never-fit),
    # else tighten safe mode — the least-disruptive action that restores the
    # envelope.
    if _has_safer_candidate(menu, active.version):
        return InterventionIntent.SELECT_SAFER_CONFIG
    return InterventionIntent.TIGHTEN_SAFE_MODE


__all__ = ["decide"]
