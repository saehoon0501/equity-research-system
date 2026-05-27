"""ALCE citation precision / recall — DETERMINISTIC set-overlap (WS-1, Axis A).

This is the *non-LLM* sub-metric of the articulation scorer. It computes
ALCE-style citation precision/recall as a pure set-overlap of the envelope's
``frameworks_cited`` keys against a "supported" set drawn from the evidence
index.

DETERMINISM CONTRACT (acceptance criterion 2):
  - NO LLM, NO network, NO DB import is reachable from this module.
  - Importing this module must succeed with ``anthropic`` / ``psycopg``
    absent. There is intentionally nothing here but stdlib + the
    ``frameworks_cited`` dual-read shim (also pure stdlib).
  - Given the same inputs the result is bit-for-bit reproducible.

Definitions (ALCE adaptation for the framework-citation setting):
  cited     = set of framework keys the envelope cites
              (``frameworks_cited`` — dual-read list/keyed-object form).
  supported = set of framework keys actually grounded in the evidence index.
  precision = |cited ∩ supported| / |cited|        (of what we cited, how
              much is grounded — guards against fabricated citations).
  recall    = |cited ∩ supported| / |supported|    (of what is grounded,
              how much did we cite — guards against under-citation).

Empty-denominator handling is explicit and deterministic:
  - |cited| == 0      -> precision = 0.0  (nothing cited can't be precise).
  - |supported| == 0  -> recall    = 0.0  (nothing to recall).
  - F1 with either component 0 -> 0.0.

PRODUCTION GROUNDING (live path; offline BLOCKER):
  In production ``supported`` is derived from the ``evidence_documents``
  table (migration 046) joined on ``source_uri`` to the framework's cited
  source URIs. That requires a live Postgres (POSTGRES_* env). Offline /
  in CI the caller passes the supported set explicitly (a fixture), which
  is exactly what makes this path deterministic and testable with no
  network. See ``compute_citation_pr`` ``supported`` parameter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Pure-stdlib dual-read accessor (no LLM / DB). Reused, not redefined.
from src.evaluator_gates._frameworks_cited_shim import get_framework_keys

# Identifies this sub-metric as never an LLM path.
CITATION_METHOD = "alce-setoverlap-v1"


@dataclass(frozen=True)
class CitationScore:
    """Deterministic ALCE precision/recall result for one envelope."""

    precision: float
    recall: float
    f1: float
    n_cited: int
    n_supported: int
    n_overlap: int
    cited: tuple[str, ...]
    supported: tuple[str, ...]
    method: str = CITATION_METHOD
    mode: str = "advisory"  # WS-1: never blocks the gate alone.

    def to_block(self) -> dict[str, Any]:
        """Serialize into the ``axis_a.citation`` sub-block."""
        return {
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "n_cited": self.n_cited,
            "n_supported": self.n_supported,
            "n_overlap": self.n_overlap,
            "cited": list(self.cited),
            "supported": list(self.supported),
            "method": self.method,
            "mode": self.mode,
        }


def _safe_ratio(numerator: int, denominator: int) -> float:
    """Deterministic ratio with explicit zero-denominator -> 0.0."""
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def compute_citation_pr(
    cited: set[str],
    supported: set[str],
) -> CitationScore:
    """Compute ALCE precision/recall/F1 from two key sets. Pure function.

    Args:
        cited:     framework keys the envelope cites.
        supported: framework keys grounded in the evidence index.

    Returns:
        A ``CitationScore`` (frozen) — no side effects, no I/O.
    """
    cited_set = {k for k in cited if isinstance(k, str)}
    supported_set = {k for k in supported if isinstance(k, str)}
    overlap = cited_set & supported_set

    n_cited = len(cited_set)
    n_supported = len(supported_set)
    n_overlap = len(overlap)

    precision = _safe_ratio(n_overlap, n_cited)
    recall = _safe_ratio(n_overlap, n_supported)
    if precision <= 0.0 or recall <= 0.0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)

    return CitationScore(
        precision=precision,
        recall=recall,
        f1=f1,
        n_cited=n_cited,
        n_supported=n_supported,
        n_overlap=n_overlap,
        cited=tuple(sorted(cited_set)),
        supported=tuple(sorted(supported_set)),
    )


def score_citation(
    envelope: dict[str, Any],
    supported: set[str],
) -> CitationScore:
    """Compute citation P/R for an envelope against a supported set.

    The cited set is read from ``envelope["frameworks_cited"]`` via the
    dual-read shim (accepts both legacy list and v3.1 keyed-object forms).
    The ``supported`` set is supplied by the caller: in production it is
    resolved from ``evidence_documents``; offline it is a fixture.

    Pure / deterministic — no LLM, no network, no DB.
    """
    cited = get_framework_keys(envelope)
    return compute_citation_pr(cited, supported)
