"""Phase 1 backtest harness for tactical overlay.

Per Section 2.1 v5-final consensus doc, Phase 1 acceptance is:
- Hard gate: all 5 enum values appear VALID in renderer output (correctness check)
- Fire-rate logging: per-label counts logged for Phase 2 baseline; NO threshold-setting

Per Section 2 v3-final Plan C v5 falsifiability Phase 1:
1. Read pm-supervisor envelopes for ticker (cohort)
2. For each, compute tactical_signal_bin at envelope's created_at date
   (in this harness's pure-compute scope, the bin is INJECTED — agent dispatch
   handles real classification)
3. Apply cell selector + disposition mapping
4. Assert all emitted dispositions are in valid enum (INV-2.1-A)
5. Log per-label fire rate descriptively

DETERMINISM: pure compute on inputs. Real Phase 1 run uses tactical-overlay agent
to compute bins from live MCP data; this harness is the offline verification
layer that confirms the mapping logic is correct and INV-2.1-A holds across the
cohort.
"""
from __future__ import annotations

import glob
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from src.p8_tactical_overlay.contracts import TacticalDisposition
from src.p8_tactical_overlay.overlay import (
    tactical_cell_size_pct,
    tactical_disposition,
)

VALID_DISPOSITION_VALUES = frozenset(TacticalDisposition.__args__)


@dataclass
class EnvelopeResult:
    """Outcome of running one pm-supervisor envelope through the overlay."""

    run_id: str
    ticker: str
    conviction: Optional[str]
    tactical_bin: str  # the bin used (injected or computed)
    cell_size_pct: float
    cell_disposition: str


@dataclass
class Phase1Report:
    """Aggregate Phase 1 report across a cohort."""

    cohort_size: int
    results: list[EnvelopeResult] = field(default_factory=list)
    # Per-label counts (4 renderer labels; 5th comparator HOLD-active subcase
    # is implicit from the cell_disposition itself)
    disposition_counts: dict[str, int] = field(default_factory=dict)
    # Hard-gate flags
    all_dispositions_valid: bool = False
    invalid_dispositions: list[str] = field(default_factory=list)
    # Observational flags (Section 2.1 v5 — descriptive only at Phase 1)
    notes: list[str] = field(default_factory=list)


def _load_envelope(path: str) -> Optional[dict]:
    """Safe loader; returns None on parse failure."""
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _band_lookup(conviction: str) -> tuple[float, float]:
    """Returns (min_pct, max_pct) for HIGH/MEDIUM; LOW returns (0,0) (selector hard-zeroes anyway)."""
    if conviction == "HIGH":
        return (3.0, 6.0)
    if conviction == "MEDIUM":
        return (1.5, 3.0)
    return (0.0, 0.0)


def run_phase1(
    envelope_dir: str,
    ticker: Optional[str] = None,
    tactical_bin_injector: Optional[callable] = None,
) -> Phase1Report:
    """Walk pm-supervisor envelopes; apply overlay; report Phase 1 correctness.

    Args:
        envelope_dir: path to memos/envelopes (or test fixture dir).
        ticker: optionally filter envelopes to this ticker.
        tactical_bin_injector: optional callable(envelope_dict) -> str returning
            the tactical_bin for that envelope. If None, defaults to 'positive'
            (assumes positive bin for all envelopes — useful for INV-2.1-A
            correctness verification on the load-bearing BUY-HIGH/BUY-MED case).

    Returns:
        Phase1Report with cohort_size, results, disposition_counts, gate flags.
    """
    pattern = os.path.join(envelope_dir, "pm-supervisor__*.json")
    paths = [p for p in sorted(glob.glob(pattern)) if not p.endswith(".context.json")]

    report = Phase1Report(cohort_size=0)
    injector = tactical_bin_injector or (lambda env: "positive")

    for path in paths:
        env = _load_envelope(path)
        if env is None:
            report.notes.append(f"skipped (parse failure): {os.path.basename(path)}")
            continue

        env_ticker = env.get("ticker", "?")
        if ticker is not None and env_ticker != ticker:
            continue

        conviction = env.get("conviction") or env.get("conviction_tier")
        run_id = env.get("run_id") or os.path.basename(path).split("__")[1].replace(".json", "")

        if conviction not in ("HIGH", "MEDIUM", "LOW"):
            report.notes.append(
                f"skipped (no valid conviction): {run_id} → {conviction!r}"
            )
            continue

        tactical_bin = injector(env)
        if tactical_bin not in ("positive", "neutral", "negative", "unavailable"):
            report.notes.append(
                f"injector produced invalid bin {tactical_bin!r} for {run_id}; skipped"
            )
            continue

        band_min, band_max = _band_lookup(conviction)
        cell_size = tactical_cell_size_pct(
            conviction, tactical_bin, band_min, band_max
        )
        cell_disp = tactical_disposition(conviction, tactical_bin)

        report.results.append(EnvelopeResult(
            run_id=run_id,
            ticker=env_ticker,
            conviction=conviction,
            tactical_bin=tactical_bin,
            cell_size_pct=cell_size,
            cell_disposition=cell_disp,
        ))
        report.cohort_size += 1
        report.disposition_counts[cell_disp] = (
            report.disposition_counts.get(cell_disp, 0) + 1
        )

    # Section 2.1 v5-final Phase 1 hard gate: enum-validity correctness check
    report.invalid_dispositions = [
        r.cell_disposition for r in report.results
        if r.cell_disposition not in VALID_DISPOSITION_VALUES
    ]
    report.all_dispositions_valid = len(report.invalid_dispositions) == 0

    # Observational notes (Section 2.1 v5 — descriptive only at Phase 1)
    if report.cohort_size > 0:
        most_common = max(report.disposition_counts.items(),
                          key=lambda kv: kv[1])
        report.notes.append(
            f"most-common disposition: {most_common[0]} "
            f"({most_common[1]}/{report.cohort_size})"
        )

    return report


def format_report(report: Phase1Report) -> str:
    """Render Phase 1 report as human-readable text."""
    lines: list[str] = []
    lines.append(f"Phase 1 cohort size: {report.cohort_size}")
    lines.append(f"All dispositions valid (INV-2.1-A): {report.all_dispositions_valid}")
    if not report.all_dispositions_valid:
        lines.append(f"  invalid dispositions: {report.invalid_dispositions}")
    lines.append("Per-disposition counts:")
    for disp in sorted(report.disposition_counts.keys()):
        cnt = report.disposition_counts[disp]
        share = cnt / report.cohort_size if report.cohort_size else 0
        lines.append(f"  {disp}: {cnt} ({share:.0%})")
    lines.append("Notes (descriptive, no thresholds at Phase 1):")
    for note in report.notes:
        lines.append(f"  - {note}")
    return "\n".join(lines)
