"""Inner-ring test for the OrderEvaluation projection (task 4.5).

Boundary: evaluation (Requirements 2, 10). Asserts the Observable from tasks.md
4.5 + test 5.11 + the §Open-Questions "the projection input" contract on
``src/survival/types.py:OrderEvaluation`` (the cross-spec input the daemon must
populate, reject-leaning by default):

  * a normal **in-universe**, non-excluded open with a **known** margin delta
    yields an ``OrderEvaluation`` whose ``additional_used_margin`` is positive
    (= ``volume × reference_price × leverage``) that the **real** ``gate.admit``
    ALLOWs on a synthetic flat-account state (Req 2, 10);
  * an **unknown-margin** order (no leverage / no price) yields
    ``additional_used_margin is None`` → ``admit`` REJECTs ``margin_distance``
    (the ``None`` sentinel is never coerced to ``0.0``);
  * an **out-of-universe** symbol yields ``in_universe is False`` → ``admit``
    REJECTs ``universe``;
  * an **excluded** order (the slow-layer §12.6 catalyst/quality screen flagged
    it, or the screen is unknown → fail-safe excluded) yields
    ``is_excluded is True`` → ``admit`` REJECTs ``entry_exclusion``;
  * the bare ``OrderEvaluation()`` survival default is itself reject-leaning
    (``additional_used_margin is None`` / ``in_universe is False`` /
    ``is_excluded is True``) — the projection must never read looser than that.

The seam is exercised against the **real pure** ``survival.admit`` over a
SYNTHETIC ``AccountState`` / ``OperationalState`` / ``SurvivalParameters`` /
``ClockState`` (P14 inner ring — no LLM, no MCP, no live DB). ``evaluation.py``
imports ONLY the ``OrderEvaluation`` type from survival; the projection itself is
a pure leaf.
"""

from __future__ import annotations

from src.reactive.daemon.evaluation import build_order_evaluation
from src.survival.gate import admit
from src.survival.params import DEFAULTS as SURVIVAL_DEFAULTS
from src.survival.types import (
    AccountState,
    ClockState,
    OperationalState,
    OrderEvaluation,
    ProposedOrder,
)

# --- Synthetic fixtures ----------------------------------------------------

# A v0.1 config universe allow-list (S&P 500 ∩ Gate-441 stand-in). The
# projection takes it by value; the orchestrator (4.1) threads the real list.
_UNIVERSE: frozenset[str] = frozenset({"AAPL", "MSFT"})

# A v0.1 config broker-instrument leverage (e.g. 5x CFD). A real margin delta is
# ``volume × reference_price × leverage`` — strictly positive for a real open.
_LEVERAGE = 5.0

_SYMBOL = "AAPL"
_VOLUME = 1.0
_REFERENCE_PRICE = 100.0
# volume × price × leverage = 1 × 100 × 5 = 500 — small vs the synthetic equity
# below, so the projected margin level stays well ABOVE the safe-mode buffer and
# admit does NOT reject margin_distance on the clean path.
_EXPECTED_MARGIN = _VOLUME * _REFERENCE_PRICE * _LEVERAGE


def _flat_account() -> AccountState:
    """A synthetic activated, flat account whose equity/used-margin keep the
    projected margin level above the safe-mode buffer for a small add.

    equity / (used_margin + add) × 100 = 100000 / (1000 + 500) × 100 ≈ 6667%,
    far above the 100% safe-mode buffer in SURVIVAL_DEFAULTS → no margin breach.
    """
    return AccountState(
        activated=True,
        equity=100_000.0,
        used_margin=1_000.0,
        free_margin=99_000.0,
        margin_level=10_000.0,
        balance=100_000.0,
        stop_out_level=50.0,
        positions=[],
    )


def _clear_op_state() -> OperationalState:
    """No kill switch, no safe-mode halt — survival permits new exposure."""
    return OperationalState(
        kill_switch_engaged=False,
        safe_mode_grade="NONE",
        entered_at=None,
        triggered_by=None,
    )


def _clock() -> ClockState:
    """An open session with no imminent closure (unused by the admit walk)."""
    return ClockState(session_open=True, seconds_to_next_closure=None)


def _open_order(symbol: str = _SYMBOL, volume: float = _VOLUME) -> ProposedOrder:
    """A survival-shaped opening ProposedOrder (LONG open) carrying a stop-loss —
    so admit's outcome is driven by the OrderEvaluation legs, not missing_sl."""
    return ProposedOrder(
        symbol=symbol,
        intent="BUY",
        direction="LONG",
        volume=volume,
        stop_loss=90.0,
    )


def _admit(order: ProposedOrder, evaluation: OrderEvaluation):
    return admit(
        order,
        _flat_account(),
        _clear_op_state(),
        SURVIVAL_DEFAULTS,
        _clock(),
        evaluation,
    )


# --- Observable 1: clean in-universe open → known margin → admit ALLOWs -----


def test_clean_open_yields_admit_acceptable_evaluation() -> None:
    """An in-universe, non-excluded open with a known leverage+price projects a
    POSITIVE ``additional_used_margin`` that the real ``gate.admit`` ALLOWs."""
    evaluation = build_order_evaluation(
        symbol=_SYMBOL,
        volume=_VOLUME,
        reference_price=_REFERENCE_PRICE,
        leverage=_LEVERAGE,
        universe=_UNIVERSE,
        is_excluded=False,
    )

    assert isinstance(evaluation, OrderEvaluation)
    assert evaluation.additional_used_margin == _EXPECTED_MARGIN
    assert evaluation.additional_used_margin is not None
    assert evaluation.additional_used_margin > 0.0
    assert evaluation.in_universe is True
    assert evaluation.is_excluded is False

    decision = _admit(_open_order(), evaluation)
    assert decision.decision == "ALLOW"
    assert decision.binding_constraint is None


# --- Observable 2: unknown margin → None → admit REJECTs margin_distance ----


def test_unknown_leverage_yields_none_margin_and_admit_rejects() -> None:
    """No leverage (genuinely unknown) projects ``additional_used_margin is
    None`` — the unknown sentinel, never ``0.0`` — and ``admit`` rejects."""
    evaluation = build_order_evaluation(
        symbol=_SYMBOL,
        volume=_VOLUME,
        reference_price=_REFERENCE_PRICE,
        leverage=None,
        universe=_UNIVERSE,
        is_excluded=False,
    )

    assert evaluation.additional_used_margin is None
    # in-universe / not-excluded so the rejection is specifically the margin leg
    assert evaluation.in_universe is True
    assert evaluation.is_excluded is False

    decision = _admit(_open_order(), evaluation)
    assert decision.decision == "REJECT"
    assert decision.binding_constraint == "margin_distance"


def test_unknown_reference_price_yields_none_margin() -> None:
    """A missing reference price is equally a margin-unknown → ``None`` (never
    coerced to ``0.0``, which would make the order fail open)."""
    evaluation = build_order_evaluation(
        symbol=_SYMBOL,
        volume=_VOLUME,
        reference_price=None,
        leverage=_LEVERAGE,
        universe=_UNIVERSE,
        is_excluded=False,
    )
    assert evaluation.additional_used_margin is None

    decision = _admit(_open_order(), evaluation)
    assert decision.decision == "REJECT"
    assert decision.binding_constraint == "margin_distance"


# --- Observable 3: out-of-universe → reject-leaning → admit REJECTs universe -


def test_out_of_universe_symbol_yields_reject_leaning_evaluation() -> None:
    """A symbol outside the v0.1 allow-list projects ``in_universe is False`` →
    ``admit`` rejects ``universe`` (the universe leg precedes margin in the
    walk)."""
    evaluation = build_order_evaluation(
        symbol="TSLA",  # not in _UNIVERSE
        volume=_VOLUME,
        reference_price=_REFERENCE_PRICE,
        leverage=_LEVERAGE,
        universe=_UNIVERSE,
        is_excluded=False,
    )
    assert evaluation.in_universe is False

    decision = _admit(_open_order(symbol="TSLA"), evaluation)
    assert decision.decision == "REJECT"
    assert decision.binding_constraint == "universe"


# --- Observable 4: excluded → reject-leaning → admit REJECTs entry_exclusion -


def test_excluded_order_yields_reject_leaning_evaluation() -> None:
    """An order the slow-layer §12.6 screen flagged projects ``is_excluded is
    True`` → ``admit`` rejects ``entry_exclusion`` (exclusion enabled in
    SURVIVAL_DEFAULTS)."""
    evaluation = build_order_evaluation(
        symbol=_SYMBOL,
        volume=_VOLUME,
        reference_price=_REFERENCE_PRICE,
        leverage=_LEVERAGE,
        universe=_UNIVERSE,
        is_excluded=True,
    )
    assert evaluation.in_universe is True
    assert evaluation.is_excluded is True

    decision = _admit(_open_order(), evaluation)
    assert decision.decision == "REJECT"
    assert decision.binding_constraint == "entry_exclusion"


def test_unknown_exclusion_defaults_to_excluded_fail_safe() -> None:
    """When the §12.6 screen result is genuinely unknown (omitted), the
    projection fail-safes to EXCLUDED (unknown → excluded → reject) — the v0.1
    default with the live screen wiring a tracked follow-on."""
    evaluation = build_order_evaluation(
        symbol=_SYMBOL,
        volume=_VOLUME,
        reference_price=_REFERENCE_PRICE,
        leverage=_LEVERAGE,
        universe=_UNIVERSE,
        # is_excluded omitted → unknown → fail-safe excluded
    )
    assert evaluation.is_excluded is True

    decision = _admit(_open_order(), evaluation)
    assert decision.decision == "REJECT"
    assert decision.binding_constraint == "entry_exclusion"


# --- Observable 5: bare survival OrderEvaluation() default is reject-leaning -


def test_bare_order_evaluation_default_is_reject_leaning() -> None:
    """The survival contract's bare ``OrderEvaluation()`` rejects every open —
    the projection must never produce anything looser than this floor."""
    bare = OrderEvaluation()
    assert bare.additional_used_margin is None
    assert bare.in_universe is False
    assert bare.is_excluded is True

    decision = _admit(_open_order(), bare)
    assert decision.decision == "REJECT"
    # off-universe is the first failing leg on the bare default
    assert decision.binding_constraint == "universe"


# --- Boundary purity: evaluation imports ONLY OrderEvaluation from survival --


def test_evaluation_module_imports_only_the_orderevaluation_type() -> None:
    """The projection is a pure leaf: it pulls in only ``OrderEvaluation`` from
    survival (the type it must populate), never ``gate`` / ``params`` logic
    (Req 10 — the daemon consumes survival verdicts, never recomputes them)."""
    import ast
    import inspect

    import src.reactive.daemon.evaluation as evaluation_module

    source = inspect.getsource(evaluation_module)
    tree = ast.parse(source)
    survival_imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("src.survival"):
                assert node.module == "src.survival.types", (
                    f"evaluation must import only from src.survival.types, got "
                    f"{node.module!r}"
                )
                survival_imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("src.survival"), (
                    f"evaluation must not plain-import {alias.name!r}"
                )

    assert survival_imports == ["OrderEvaluation"], (
        f"evaluation must import only the OrderEvaluation type, got "
        f"{survival_imports}"
    )
