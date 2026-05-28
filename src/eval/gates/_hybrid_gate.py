"""WS-6 hybrid gate: deterministic spine (HARD) + advisory LLM judge.

A hybrid gate combines:

  * **Deterministic spine** — the existing shape validators (imported, NOT
    re-implemented). This is the only thing that can HARD-FAIL the gate.
  * **Advisory judge** — the sonnet judge in :mod:`_judge`. It is *advisory*:
    it can DOWNGRADE a spine-pass to an ``ESCALATE`` recommendation, but it can
    NEVER flip a verdict to ``PASS`` on its own, and it can never HARD-FAIL.

Verdict matrix (the linchpin):

    spine     judge        gate.valid (hard)   gate verdict
    ------    ----------   -----------------   ------------
    FAIL      (not run)    False               FAIL
    PASS      PASS         True                PASS
    PASS      ESCALATE     True                ESCALATE   (advisory downgrade)
    PASS      error        True                ESCALATE   (fail-safe; never PASS)

Crucially ``gate.valid`` — the *hard* bool that feeds the aggregate
``validate_all`` roll-up — is driven ONLY by the spine. A judge ``ESCALATE``
is surfaced in the outcome's ``result_dict`` (``hybrid_verdict``) and counted
by the ESCALATE-rate monitor; it does NOT by itself make the gate hard-invalid
(that would make the judge a sole hard gate, which is forbidden). Downstream
escalation handling reads ``hybrid_verdict == "ESCALATE"``.

The gate registers itself by appending runners to ``REGISTRY`` (in
``_registry.py``) and by inserting its gate id into the runtime ``GATE_IDS``
dict at import — neither edits ``__init__.py`` nor any ``_validate_*`` body.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from typing import Callable, Optional

from src.eval.gates._outcome import GATE_IDS, make_outcome
from src.eval.gates._judge import (
    JUDGE_ESCALATE,
    JUDGE_PASS,
    JudgeVerdict,
    resolve_judge_model,
    run_judge,
)

_LOG = logging.getLogger(__name__)

# Deterministic spine validators — imported, never re-implemented (WS-6 spec:
# "reuse existing shape validators").
from src.eval.gates.envelope_shape import validate_envelope_shape
from src.eval.gates.quant_memo_shape import validate_quant_memo_shape
from src.eval.gates.strategic_memo_shape import validate_strategic_memo_shape
from src.eval.gates.catalyst_memo_shape import validate_catalyst_memo_shape
from src.eval.gates.cdd_memo_shape import validate_cdd_memo_shape
from src.eval.gates.tactical_envelope_shape import (
    validate_tactical_envelope_shape,
)
from src.eval.gates.reversion_envelope_shape import (
    validate_reversion_envelope_shape,
)
from src.eval.gates.evidence_uuid_check import validate_evidence_refs_syntactic

# Gate identity. Registered into the runtime GATE_IDS dict (NOT a source edit
# to _outcome.py) so make_outcome can resolve it — same mechanism the registry
# unit test uses for its dummy gate.
HYBRID_GATE_NAME = "hybrid_gate"
HYBRID_GATE_ID = "HG-40"
GATE_IDS.setdefault(HYBRID_GATE_NAME, HYBRID_GATE_ID)

# Hybrid verdicts (the gate-level synthesis, distinct from gate.valid).
HYBRID_PASS = "PASS"
HYBRID_FAIL = "FAIL"
HYBRID_ESCALATE = "ESCALATE"

# Judge lifecycle status — makes the (otherwise silent) judge-unconfigured state
# OBSERVABLE so an operator/monitor can tell a dead/misconfigured judge apart
# from "deliberately off" (BUG 2). Surfaced on HybridResult.judge_status and in
# the gate_decision advisory block.
#   * "configured"   — a judge backend was available AND produced a verdict.
#   * "unconfigured" — NO judge backend (no judge_fn/compute_fn/cache); the
#                      advisory judge abstained because it cannot run at all.
#                      This is the production default until Phase-2 wiring.
#   * "errored"      — a CONFIGURED judge raised / returned malformed / hit the
#                      master-key trap / position-swap disagreement (degraded).
#   * "abstained"    — the judge was deliberately NOT invoked (spine-FAIL path).
JUDGE_STATUS_CONFIGURED = "configured"
JUDGE_STATUS_UNCONFIGURED = "unconfigured"
JUDGE_STATUS_ERRORED = "errored"
JUDGE_STATUS_ABSTAINED = "abstained"

# Map a judge verdict token to the golden-fixture advisory vocabulary.
# The contract fixtures spell the advisory judge as "agree" (no objection) /
# "abstain" (objection / escalate), NOT as PASS/ESCALATE.
_ADVISORY_JUDGE_VOCAB = {JUDGE_PASS: "agree", JUDGE_ESCALATE: "abstain"}

# WARNING-once latch: the judge-unconfigured WARNING is emitted at most once per
# process so the registry/validate_all hot path does not flood the logs while
# still being loud enough for an operator to notice a dead judge in prod.
_WARNED_UNCONFIGURED = False


def _warn_unconfigured_once() -> None:
    """Emit the judge-unconfigured WARNING at most once per process.

    Phase-2 integration MUST wire ``judge_fn``/``compute_fn`` (or a replay
    cache) and decide ``judge_required`` per environment. Until then a missing
    judge in production is *acceptable* (spine still hard-FAILs) but must never
    be silent — this WARNING + ``judge_status="unconfigured"`` is the signal.
    """
    global _WARNED_UNCONFIGURED
    if not _WARNED_UNCONFIGURED:
        _WARNED_UNCONFIGURED = True
        _LOG.warning(
            "WS-6 hybrid gate: advisory judge is UNCONFIGURED (no "
            "judge_fn/compute_fn/cache). Spine-PASS envelopes stand as PASS "
            "and the ESCALATE-rate monitor will read 0%% for the judge. A "
            "misconfigured/missing-in-prod judge is INDISTINGUISHABLE from "
            "'deliberately off' unless this is observed. Phase-2 wiring MUST "
            "provide a judge backend and set judge_required per environment."
        )

# ESCALATE-rate monitor: alert when > this fraction of gated envelopes ESCALATE
# over the rolling window.
ESCALATE_RATE_THRESHOLD = 0.20
ESCALATE_WINDOW = 50


# --------------------------------------------------------------------------- #
# Deterministic spine: artifact_type -> (validator, callable returning .valid)
# --------------------------------------------------------------------------- #
def _spine_for(artifact_type: str):
    """Return the deterministic spine validator(s) for an artifact type.

    Returns a callable ``env -> (valid: bool, detail: dict)``. The detail dict
    records each spine check's pass/fail so a hard-FAIL is explainable.
    """

    def _shape_only(validator):
        def _run(env):
            res = validator(env)
            valid = bool(getattr(res, "valid", False))
            return valid, {"shape": valid}

        return _run

    def _shape_plus_evidence(validator):
        def _run(env):
            shape = validator(env)
            shape_ok = bool(getattr(shape, "valid", False))
            ev = validate_evidence_refs_syntactic(env.get("evidence_index_refs"))
            ev_ok = bool(getattr(ev, "valid", False))
            return (shape_ok and ev_ok), {"shape": shape_ok, "evidence": ev_ok}

        return _run

    table = {
        # pm_envelope spine = envelope shape + syntactic evidence refs.
        "pm_envelope": _shape_plus_evidence(validate_envelope_shape),
        "quant_memo": _shape_plus_evidence(validate_quant_memo_shape),
        "strategic_memo": _shape_plus_evidence(validate_strategic_memo_shape),
        "catalyst_memo": _shape_plus_evidence(validate_catalyst_memo_shape),
        "cdd_memo": _shape_only(validate_cdd_memo_shape),
        "tactical_envelope": _shape_only(validate_tactical_envelope_shape),
        "reversion_envelope": _shape_only(validate_reversion_envelope_shape),
    }
    return table.get(artifact_type)


# --------------------------------------------------------------------------- #
# ESCALATE-rate monitor (rolling window)
# --------------------------------------------------------------------------- #
@dataclass
class EscalateRateMonitor:
    """Rolling-window monitor over hybrid verdicts.

    Tracks the last ``window`` gated-envelope verdicts and alerts when the
    fraction of ESCALATE verdicts exceeds ``threshold``. FAIL verdicts (spine
    hard-fails) also count as "not a clean PASS" but the monitored metric is
    specifically the ESCALATE rate per the WS-6 spec.
    """

    window: int = ESCALATE_WINDOW
    threshold: float = ESCALATE_RATE_THRESHOLD

    def __post_init__(self) -> None:
        self._verdicts: deque[str] = deque(maxlen=self.window)

    def record(self, verdict: str) -> None:
        self._verdicts.append(verdict)

    @property
    def n(self) -> int:
        return len(self._verdicts)

    @property
    def escalate_count(self) -> int:
        return sum(1 for v in self._verdicts if v == HYBRID_ESCALATE)

    @property
    def escalate_rate(self) -> float:
        if not self._verdicts:
            return 0.0
        return self.escalate_count / len(self._verdicts)

    @property
    def alerting(self) -> bool:
        # Only meaningful once the window is full (rolling 50-run window per
        # the spec); a partial window can't represent the steady-state rate.
        if len(self._verdicts) < self.window:
            return False
        return self.escalate_rate > self.threshold

    def status(self) -> dict:
        return {
            "n": self.n,
            "window": self.window,
            "escalate_count": self.escalate_count,
            "escalate_rate": round(self.escalate_rate, 4),
            "threshold": self.threshold,
            "alerting": self.alerting,
            "window_full": self.n >= self.window,
        }


# Process-global monitor instance used by the registry runner. Tests construct
# their own EscalateRateMonitor to assert behaviour deterministically.
_GLOBAL_MONITOR = EscalateRateMonitor()


def global_monitor() -> EscalateRateMonitor:
    return _GLOBAL_MONITOR


# --------------------------------------------------------------------------- #
# Core hybrid evaluation
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class HybridResult:
    """Synthesis of spine + judge for one envelope."""

    spine_valid: bool
    spine_detail: dict
    judge: Optional[JudgeVerdict]
    hybrid_verdict: str  # HYBRID_PASS | HYBRID_FAIL | HYBRID_ESCALATE
    # gate.valid (hard) is driven ONLY by the spine.
    hard_valid: bool
    # Judge lifecycle status (BUG 2): one of JUDGE_STATUS_*. Makes the
    # judge-unconfigured state explicit/observable instead of silent.
    judge_status: str = JUDGE_STATUS_CONFIGURED
    # The resolved judge model id (when a judge backend ran); surfaced in the
    # gate_decision advisory block to match the golden fixture's judge_model.
    judge_model: Optional[str] = None

    def to_gate_decision(self) -> dict:
        """Map this hybrid result onto the canonical ``gate_decision`` shape.

        Returns a dict with EXACTLY the golden-fixture key set
        ``{verdict, deterministic, advisory, escalated}`` (see
        ``tests/fixtures/golden_score_blocks/*.json`` and the
        ``GateDecision`` TypedDict in ``src/scoring/contracts.py``):

          * ``verdict``       — the final hybrid verdict (PASS / FAIL /
            ESCALATE), spelled exactly as the fixture does.
          * ``deterministic`` — the spine outcome, each hard companion-check
            mapped to the fixture vocabulary ``"pass"``/``"fail"`` (the spine
            stores booleans internally).
          * ``advisory``      — the judge's advisory output, or ``None`` when
            no judge was run at all. When present it always carries
            ``judge_status`` (configured/unconfigured/errored/abstained) so an
            operator can detect a dead/misconfigured judge (BUG 2), plus the
            ``judge`` token in the fixture vocabulary ("agree"/"abstain") and,
            when known, ``judge_model``.
          * ``escalated``     — ``True`` iff the verdict is ESCALATE.

        Phase-2 wiring persists this via ``env['gate_decision'] =
        result.to_gate_decision()``.
        """
        deterministic = {
            k: ("pass" if v else "fail")
            for k, v in self.spine_detail.items()
        }

        advisory = self._advisory_block()

        return {
            "verdict": self.hybrid_verdict,
            "deterministic": deterministic,
            "advisory": advisory,
            "escalated": self.hybrid_verdict == HYBRID_ESCALATE,
        }

    def _advisory_block(self) -> Optional[dict]:
        """Build the gate_decision ``advisory`` sub-block.

        ``None`` ONLY when the judge was genuinely never part of the decision
        (spine-FAIL with no judge run) — there is nothing advisory to report.
        Otherwise the block always carries ``judge_status`` so the unconfigured
        state stays visible (BUG 2), never silent.
        """
        # spine-FAIL with no judge run at all: no advisory signal to surface.
        if self.judge is None and self.judge_status == JUDGE_STATUS_ABSTAINED:
            return None

        block: dict = {"judge_status": self.judge_status}
        if self.judge is not None:
            block["judge"] = _ADVISORY_JUDGE_VOCAB.get(
                self.judge.verdict, self.judge.verdict
            )
        else:
            # Unconfigured: no verdict token; record null so the key is present.
            block["judge"] = None
        if self.judge_model is not None:
            block["judge_model"] = self.judge_model
        return block


def _judge_is_configured(judge_fn, compute_fn, cache) -> bool:
    """True when *some* judge backend is available to attempt a verdict.

    A judge is configured if any of: an injected ``judge_fn`` (tests / custom
    composition), a live ``compute_fn`` round-trip, or a replay/record cache
    that can serve the verdict. When none is present the judge is *deliberately
    unconfigured* — distinct from "attempted and errored".
    """
    # A cache alone cannot invoke the judge (nothing to ask it about); it
    # supplements judge_fn/compute_fn, not substitutes. Treating cache-only as
    # 'configured' would flip the unconfigured path to ESCALATE under
    # LLM_CACHE_ENABLED=1 in CI (no judge_fn/compute_fn wired) — the very
    # situation the unconfigured-judge-keeps-spine-PASS test guards against.
    return judge_fn is not None or compute_fn is not None


def evaluate_hybrid(
    artifact_type: str,
    envelope: dict,
    *,
    compute_fn: Optional[Callable[..., str]] = None,
    judge_fn: Optional[Callable[[str, dict], JudgeVerdict]] = None,
    cache=None,
    run_judge_when_spine_fails: bool = False,
    judge_input_text: Optional[str] = None,
    judge_required: bool = False,
) -> HybridResult:
    """Run spine then (advisory) judge and synthesize a hybrid verdict.

    Args:
        artifact_type: which spine to run.
        envelope: parsed artifact dict.
        compute_fn: model round-trip thunk forwarded to :func:`run_judge`.
        judge_fn: optional full judge override ``(artifact_type, env) ->
            JudgeVerdict`` — used by tests to inject a deterministic judge
            (kappa monitor, error path). When set, ``compute_fn`` is ignored.
        cache: P0-5 LLM cache (forwarded to run_judge).
        run_judge_when_spine_fails: default False — when the spine hard-fails
            there's no point asking the advisory judge (and it can't rescue a
            FAIL anyway). Tests may set True to assert the no-rescue property.
        judge_input_text: forwarded to run_judge's master-key trap.

    Returns:
        HybridResult. ``hard_valid`` == spine validity (judge can NEVER flip
        it to True or False). ``hybrid_verdict`` is FAIL iff spine failed;
        otherwise PASS or ESCALATE per the (advisory, downgrade-only) judge.
    """
    spine = _spine_for(artifact_type)
    if spine is None:
        # Unknown artifact type for the hybrid gate: fail-safe to FAIL on the
        # spine (it has no shape contract we can attest to).
        return HybridResult(
            spine_valid=False,
            spine_detail={"error": f"no spine for artifact_type={artifact_type!r}"},
            judge=None,
            hybrid_verdict=HYBRID_FAIL,
            hard_valid=False,
            judge_status=JUDGE_STATUS_ABSTAINED,  # judge not run on spine-FAIL
        )

    spine_valid, spine_detail = spine(envelope)

    # Spine hard-fail: gate is hard-invalid. Judge cannot rescue (linchpin).
    if not spine_valid:
        judge_verdict = None
        judge_status = JUDGE_STATUS_ABSTAINED  # default: judge not run
        judge_model = None
        if run_judge_when_spine_fails:
            judge_verdict = _invoke_judge(
                artifact_type,
                envelope,
                compute_fn=compute_fn,
                judge_fn=judge_fn,
                cache=cache,
                judge_input_text=judge_input_text,
            )
            judge_status = (
                JUDGE_STATUS_ERRORED
                if judge_verdict.degraded
                else JUDGE_STATUS_CONFIGURED
            )
            judge_model = resolve_judge_model()
        # Even if the judge said PASS, hybrid_verdict stays FAIL and hard_valid
        # stays False — the judge can never flip a FAIL to PASS.
        return HybridResult(
            spine_valid=False,
            spine_detail=spine_detail,
            judge=judge_verdict,
            hybrid_verdict=HYBRID_FAIL,
            hard_valid=False,
            judge_status=judge_status,
            judge_model=judge_model,
        )

    # Spine passed. If NO judge backend is configured, the judge *abstains*
    # (it is not run) — distinct from "attempted and errored". An unconfigured
    # advisory judge must NOT degrade every passing envelope to ESCALATE in
    # environments where the judge isn't wired (that would make the advisory
    # judge effectively block release — exactly what it must never do). The
    # hybrid verdict then follows the spine: PASS. Setting ``judge_required``
    # forces an ESCALATE when the judge cannot run (use when the judge is
    # mandatory for the pipeline). The linchpin is untouched either way: the
    # judge can never flip to PASS on its own and never rescues a spine FAIL.
    if not _judge_is_configured(judge_fn, compute_fn, cache):
        # BUG 2: the judge-unconfigured state must be LOUD, not silent. Emit a
        # one-time WARNING and stamp judge_status="unconfigured" so a dead/
        # misconfigured judge in production is observable (and is NOT
        # indistinguishable from a configured-judge PASS).
        _warn_unconfigured_once()
        if judge_required:
            return HybridResult(
                spine_valid=True,
                spine_detail=spine_detail,
                judge=JudgeVerdict(
                    verdict=JUDGE_ESCALATE,
                    rationale="judge required but unconfigured -> ESCALATE",
                    degraded=True,
                ),
                hybrid_verdict=HYBRID_ESCALATE,
                hard_valid=True,
                judge_status=JUDGE_STATUS_UNCONFIGURED,
            )
        return HybridResult(
            spine_valid=True,
            spine_detail=spine_detail,
            judge=None,  # abstained — not run because no backend exists
            hybrid_verdict=HYBRID_PASS,
            hard_valid=True,
            judge_status=JUDGE_STATUS_UNCONFIGURED,
        )

    # Spine passed and a judge backend exists: ask the advisory judge. It can
    # only keep PASS or downgrade to ESCALATE; it can never hard-fail and can
    # never be the sole hard gate. A configured judge that ERRORS escalates.
    judge_verdict = _invoke_judge(
        artifact_type,
        envelope,
        compute_fn=compute_fn,
        judge_fn=judge_fn,
        cache=cache,
        judge_input_text=judge_input_text,
    )
    if judge_verdict.verdict == JUDGE_ESCALATE:
        hybrid_verdict = HYBRID_ESCALATE
    else:
        hybrid_verdict = HYBRID_PASS

    # A CONFIGURED judge that degraded (raised / malformed / master-key trap /
    # position-swap disagreement) -> "errored"; otherwise it ran cleanly.
    judge_status = (
        JUDGE_STATUS_ERRORED if judge_verdict.degraded else JUDGE_STATUS_CONFIGURED
    )

    return HybridResult(
        spine_valid=True,
        spine_detail=spine_detail,
        judge=judge_verdict,
        hybrid_verdict=hybrid_verdict,
        hard_valid=True,  # driven by spine ONLY
        judge_status=judge_status,
        judge_model=resolve_judge_model(),
    )


def _invoke_judge(
    artifact_type: str,
    envelope: dict,
    *,
    compute_fn,
    judge_fn,
    cache,
    judge_input_text,
) -> JudgeVerdict:
    """Resolve the judge verdict, honoring an injected judge_fn override.

    If no compute_fn and no judge_fn are supplied we cannot perform a model
    round-trip; fail-safe to ESCALATE (never PASS).
    """
    if judge_fn is not None:
        try:
            v = judge_fn(artifact_type, envelope)
        except Exception:  # noqa: BLE001
            return JudgeVerdict(
                verdict=JUDGE_ESCALATE,
                rationale="injected judge_fn raised -> ESCALATE (fail-safe)",
                degraded=True,
            )
        if not isinstance(v, JudgeVerdict):
            return JudgeVerdict(
                verdict=JUDGE_ESCALATE,
                rationale="injected judge_fn returned non-JudgeVerdict -> ESCALATE",
                degraded=True,
            )
        return v
    if compute_fn is None:
        return JudgeVerdict(
            verdict=JUDGE_ESCALATE,
            rationale="no judge compute_fn available -> ESCALATE (fail-safe)",
            degraded=True,
        )
    return run_judge(
        artifact_type,
        envelope,
        compute_fn=compute_fn,
        cache=cache,
        judge_input_text=judge_input_text,
    )


# --------------------------------------------------------------------------- #
# Registry runner factory
# --------------------------------------------------------------------------- #
def make_hybrid_runner_for(
    artifact_type: str,
    *,
    compute_fn: Optional[Callable[..., str]] = None,
    judge_fn: Optional[Callable[[str, dict], JudgeVerdict]] = None,
    cache=None,
    monitor: Optional[EscalateRateMonitor] = None,
):
    """Return a GateRunner ``(env, ctx) -> (GateOutcome, key, val)``.

    The returned runner:
      * runs the hybrid evaluation,
      * records the verdict in the (global by default) ESCALATE-rate monitor,
      * emits a GateOutcome whose ``valid`` is the HARD (spine-only) bool,
        carrying the advisory verdict + monitor status in result_dict.
    """
    mon = monitor if monitor is not None else _GLOBAL_MONITOR

    def _runner(env: dict, ctx):  # ctx: GateContext (unused fields tolerated)
        result = evaluate_hybrid(
            artifact_type,
            env,
            compute_fn=compute_fn,
            judge_fn=judge_fn,
            cache=cache,
        )
        mon.record(result.hybrid_verdict)
        result_dict = {
            "hybrid_verdict": result.hybrid_verdict,
            "hard_valid": result.hard_valid,
            "spine_valid": result.spine_valid,
            "spine_detail": result.spine_detail,
            "judge_status": result.judge_status,  # BUG 2: observable judge state
            # Canonical contract block (BUG 1): Phase-2 wiring persists this as
            # env['gate_decision']. Carried in result_dict so it is available
            # without re-deriving from the HybridResult fields.
            "gate_decision": result.to_gate_decision(),
            "judge_verdict": result.judge.verdict if result.judge else None,
            "judge_degraded": result.judge.degraded if result.judge else None,
            "judge_master_key_trapped": (
                result.judge.master_key_trapped if result.judge else None
            ),
            "judge_position_swap_consistent": (
                result.judge.position_swap_consistent if result.judge else None
            ),
            "escalate_monitor": mon.status(),
        }
        # Fingerprint for stuck-loop detection on hard-fail.
        if not result.hard_valid:
            fp = "spine_fail:" + ",".join(
                k for k, v in result.spine_detail.items() if v is False
            ) or "spine_fail"
        else:
            fp = "ok"
        outcome = make_outcome(HYBRID_GATE_NAME, result.hard_valid, result_dict, fp)
        summary_val = "pass" if result.hard_valid else "fail"
        # Surface ESCALATE in the summary string for operator visibility while
        # keeping the hard pass/fail semantics intact.
        if result.hard_valid and result.hybrid_verdict == HYBRID_ESCALATE:
            summary_val = "pass(escalate)"
        return outcome, HYBRID_GATE_NAME, summary_val

    return _runner


__all__ = [
    "HYBRID_GATE_NAME",
    "HYBRID_GATE_ID",
    "HYBRID_PASS",
    "HYBRID_FAIL",
    "HYBRID_ESCALATE",
    "JUDGE_STATUS_CONFIGURED",
    "JUDGE_STATUS_UNCONFIGURED",
    "JUDGE_STATUS_ERRORED",
    "JUDGE_STATUS_ABSTAINED",
    "ESCALATE_RATE_THRESHOLD",
    "ESCALATE_WINDOW",
    "EscalateRateMonitor",
    "global_monitor",
    "HybridResult",
    "evaluate_hybrid",
    "make_hybrid_runner_for",
]
