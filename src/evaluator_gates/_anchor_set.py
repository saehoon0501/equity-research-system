"""Frozen anchor-set loader + kappa baseline (WS-6).

The hybrid gate's advisory judge is *quarantined to advisory-only* when it
drifts away from a frozen reference of human judgement. That reference is the
**anchor set**: a small (operator target: 30-50) collection of envelopes that
an operator has hand-labelled with the ground-truth verdict the judge *should*
produce (``PASS`` / ``ESCALATE``).

Two numbers matter:

* the **baseline kappa** — Cohen's kappa between the judge verdict and the
  operator label *measured once at freeze time* and stored alongside the set.
  This is the quarantine reference.
* the **live kappa** — the same agreement statistic recomputed each CI cycle
  against the (unchanged) frozen labels using the *current* judge. When the
  live kappa drops more than ``QUARANTINE_DROP_PP`` percentage points below
  the stored baseline, the judge is auto-quarantined to advisory-only.

This module is pure / deterministic / no-network. The judge function is
injected so tests can pass a mock and CI can replay from the cache.

OPERATOR DEFERRAL
-----------------
The *real* 30-50 envelope anchor set with genuine operator labels is an
operator task — labels cannot be fabricated by this code (doing so would make
the quarantine reference meaningless). What ships here is:

  * the LOADER (``load_anchor_set``) that reads a frozen anchor-set JSON,
  * the kappa MATH (``cohens_kappa``),
  * the baseline COMPUTATION + FREEZE (``compute_baseline_kappa`` /
    ``freeze_anchor_set``),
  * the live-vs-baseline QUARANTINE check (``quarantine_decision``),
  * a SMALL SYNTHETIC fixture (``tests/fixtures/anchor_set/synthetic_anchor_set.json``)
    used only by the unit tests.

The synthetic fixture is explicitly flagged ``"synthetic": true`` and carries
fewer than the operator minimum; ``load_anchor_set(require_operator=True)``
rejects it so it can never be mistaken for the production reference.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Sequence

# The two verdicts the judge + operator labels live in. The hybrid gate's
# judge can only ever emit PASS (no objection) or ESCALATE (objection); it
# can never emit FAIL — that is the deterministic spine's sole privilege.
VERDICTS: tuple[str, ...] = ("PASS", "ESCALATE")

# Operator minimum for a *production* anchor set (WS-6 spec: 30-50).
OPERATOR_MIN_LABELS = 30
OPERATOR_MAX_LABELS = 50

# Quarantine trigger: live kappa more than this many percentage POINTS below
# the frozen baseline kappa => quarantine the judge to advisory-only.
QUARANTINE_DROP_PP = 10.0

# A judge function maps (artifact_type, envelope_dict) -> verdict in VERDICTS.
JudgeFn = Callable[[str, dict], str]


# --------------------------------------------------------------------------- #
# Data structures
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class AnchorItem:
    """One labelled anchor envelope."""

    anchor_id: str
    artifact_type: str
    envelope: dict
    operator_label: str  # one of VERDICTS

    def __post_init__(self) -> None:
        if self.operator_label not in VERDICTS:
            raise ValueError(
                f"anchor {self.anchor_id!r}: operator_label "
                f"{self.operator_label!r} not in {VERDICTS}"
            )


@dataclass
class AnchorSet:
    """A loaded anchor set + its frozen baseline metadata (if frozen)."""

    set_id: str
    items: list[AnchorItem]
    synthetic: bool = False
    baseline_kappa: float | None = None
    frozen_at: str | None = None
    notes: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.items)

    def labels(self) -> list[str]:
        return [it.operator_label for it in self.items]


# --------------------------------------------------------------------------- #
# Kappa math (pure)
# --------------------------------------------------------------------------- #
def cohens_kappa(
    a: Sequence[str],
    b: Sequence[str],
    *,
    categories: Iterable[str] = VERDICTS,
) -> float:
    """Cohen's kappa for two equal-length sequences of categorical labels.

    Returns 1.0 for perfect agreement, 0.0 for chance-level, negative for
    worse-than-chance. The degenerate all-agree-single-category case (po==1,
    pe==1) is defined here as 1.0 (perfect agreement), matching the common
    convention used for monitoring rather than returning NaN.
    """
    if len(a) != len(b):
        raise ValueError(f"length mismatch: {len(a)} vs {len(b)}")
    n = len(a)
    if n == 0:
        raise ValueError("cannot compute kappa over an empty sample")

    cats = list(categories)
    # observed agreement
    agree = sum(1 for x, y in zip(a, b) if x == y)
    po = agree / n

    # expected agreement by chance from the marginals
    pe = 0.0
    for c in cats:
        pa = sum(1 for x in a if x == c) / n
        pb = sum(1 for y in b if y == c) / n
        pe += pa * pb

    if pe >= 1.0:
        # Both raters used a single identical category for everything.
        return 1.0 if po >= 1.0 else 0.0
    return (po - pe) / (1.0 - pe)


def judge_label_kappa(anchor_set: AnchorSet, judge_fn: JudgeFn) -> float:
    """Compute Cohen's kappa between the judge and the operator labels."""
    judge_verdicts = [
        judge_fn(it.artifact_type, it.envelope) for it in anchor_set.items
    ]
    for v in judge_verdicts:
        if v not in VERDICTS:
            raise ValueError(f"judge emitted {v!r} not in {VERDICTS}")
    return cohens_kappa(judge_verdicts, anchor_set.labels())


# --------------------------------------------------------------------------- #
# Load / freeze
# --------------------------------------------------------------------------- #
_DEFAULT_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "anchor_set"
    / "synthetic_anchor_set.json"
)


def load_anchor_set(
    path: str | Path | None = None,
    *,
    require_operator: bool = False,
) -> AnchorSet:
    """Load a frozen anchor set from JSON.

    Args:
        path: anchor-set JSON path. Defaults to the synthetic test fixture.
        require_operator: when True, reject synthetic sets and sets below the
            operator minimum size — used by production callers so the
            synthetic fixture can never stand in for the real reference.
    """
    p = Path(path) if path is not None else _DEFAULT_FIXTURE
    with open(p, "r", encoding="utf-8") as f:
        raw = json.load(f)

    items = [
        AnchorItem(
            anchor_id=str(row["anchor_id"]),
            artifact_type=str(row["artifact_type"]),
            envelope=dict(row["envelope"]),
            operator_label=str(row["operator_label"]),
        )
        for row in raw.get("items", [])
    ]
    aset = AnchorSet(
        set_id=str(raw.get("set_id", p.stem)),
        items=items,
        synthetic=bool(raw.get("synthetic", False)),
        baseline_kappa=raw.get("baseline_kappa"),
        frozen_at=raw.get("frozen_at"),
        notes=list(raw.get("notes", [])),
    )

    if require_operator:
        if aset.synthetic:
            raise ValueError(
                f"anchor set {aset.set_id!r} is synthetic; a production "
                "quarantine reference requires the operator-labelled set "
                "(deferred operator task — see _anchor_set.py docstring)."
            )
        if len(aset) < OPERATOR_MIN_LABELS:
            raise ValueError(
                f"anchor set {aset.set_id!r} has {len(aset)} labels; "
                f"operator minimum is {OPERATOR_MIN_LABELS}."
            )
    return aset


def compute_baseline_kappa(anchor_set: AnchorSet, judge_fn: JudgeFn) -> float:
    """Compute the freeze-time baseline kappa (judge<->operator labels)."""
    return judge_label_kappa(anchor_set, judge_fn)


def freeze_anchor_set(
    anchor_set: AnchorSet,
    judge_fn: JudgeFn,
    *,
    frozen_at: str,
) -> AnchorSet:
    """Return a copy of the set with the baseline kappa computed + stamped.

    This is what an operator runs once after labelling: it measures the
    judge<->label agreement and records it as the immutable quarantine
    reference.
    """
    baseline = compute_baseline_kappa(anchor_set, judge_fn)
    return AnchorSet(
        set_id=anchor_set.set_id,
        items=list(anchor_set.items),
        synthetic=anchor_set.synthetic,
        baseline_kappa=baseline,
        frozen_at=frozen_at,
        notes=list(anchor_set.notes),
    )


# --------------------------------------------------------------------------- #
# Quarantine decision
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class QuarantineDecision:
    """Outcome of the per-cycle live-vs-baseline kappa check."""

    quarantined: bool
    baseline_kappa: float
    live_kappa: float
    drop_pp: float  # (baseline - live) * 100, in percentage points
    threshold_pp: float
    reason: str


def quarantine_decision(
    anchor_set: AnchorSet,
    judge_fn: JudgeFn,
    *,
    drop_pp_threshold: float = QUARANTINE_DROP_PP,
) -> QuarantineDecision:
    """Decide whether to quarantine the judge based on live kappa drift.

    The judge is quarantined (forced advisory-only) when the live kappa is
    more than ``drop_pp_threshold`` percentage points below the frozen
    baseline kappa stored on the set.
    """
    if anchor_set.baseline_kappa is None:
        raise ValueError(
            f"anchor set {anchor_set.set_id!r} has no frozen baseline_kappa; "
            "call freeze_anchor_set first."
        )
    baseline = float(anchor_set.baseline_kappa)
    live = judge_label_kappa(anchor_set, judge_fn)
    drop_pp = (baseline - live) * 100.0
    quarantined = drop_pp > drop_pp_threshold
    reason = (
        f"live kappa {live:.3f} is {drop_pp:.1f}pp below baseline {baseline:.3f} "
        f"(> {drop_pp_threshold:.0f}pp) -> QUARANTINE"
        if quarantined
        else f"live kappa {live:.3f} within {drop_pp_threshold:.0f}pp of "
        f"baseline {baseline:.3f} -> healthy"
    )
    return QuarantineDecision(
        quarantined=quarantined,
        baseline_kappa=baseline,
        live_kappa=live,
        drop_pp=drop_pp,
        threshold_pp=drop_pp_threshold,
        reason=reason,
    )


__all__ = [
    "VERDICTS",
    "OPERATOR_MIN_LABELS",
    "OPERATOR_MAX_LABELS",
    "QUARANTINE_DROP_PP",
    "JudgeFn",
    "AnchorItem",
    "AnchorSet",
    "cohens_kappa",
    "judge_label_kappa",
    "load_anchor_set",
    "compute_baseline_kappa",
    "freeze_anchor_set",
    "QuarantineDecision",
    "quarantine_decision",
]
