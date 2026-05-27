"""Phase 1 backtest harness for flow overlay.

Mirrors src/overlays/tactical/phase1_harness.py in structure. Phase 1
acceptance:
- Hard gate: all emitted dispositions are in the valid 4-value enum
  (INV-FLOW-2.1-A correctness check)
- Fire-rate logging: per-label counts logged for v0.2 baseline; NO
  threshold-setting at v0.1

This harness is the offline verification layer that confirms the mapping
logic is correct across a cohort of pm-supervisor envelopes. Real Phase 1
data run uses flow-overlay agent to compute bins from live MCP data;
this harness uses an injected bin (default 'positive') to verify the
overlay logic in isolation.
"""
from __future__ import annotations

import glob
import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Optional

from src.overlays.flow.contracts import FlowDisposition
from src.overlays.flow.overlay import (
    flow_cell_size_pct,
    flow_disposition,
)

VALID_DISPOSITION_VALUES = frozenset(FlowDisposition.__args__)


@dataclass
class EnvelopeResult:
    """Outcome of running one pm-supervisor envelope through the flow overlay."""

    run_id: str
    ticker: str
    conviction: Optional[str]
    flow_bin: str
    cell_size_pct: float
    cell_disposition: str


@dataclass
class Phase1Report:
    """Aggregate Phase 1 report across a cohort."""

    cohort_size: int
    results: list[EnvelopeResult] = field(default_factory=list)
    disposition_counts: dict[str, int] = field(default_factory=dict)
    all_dispositions_valid: bool = False
    invalid_dispositions: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _load_envelope(path: str) -> Optional[dict]:
    """Safe loader; returns None on parse failure."""
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _band_lookup(conviction: str) -> tuple[float, float]:
    """Returns (min_pct, max_pct) for HIGH/MEDIUM; LOW returns (0,0)."""
    if conviction == "HIGH":
        return (3.0, 6.0)
    if conviction == "MEDIUM":
        return (1.5, 3.0)
    return (0.0, 0.0)


def run_phase1(
    envelope_dir: str,
    ticker: Optional[str] = None,
    flow_bin_injector: Optional[Callable[[dict], str]] = None,
) -> Phase1Report:
    """Walk pm-supervisor envelopes; apply flow overlay; report Phase 1 correctness.

    Args:
        envelope_dir: path to memos/envelopes (or test fixture dir).
        ticker: optionally filter envelopes to this ticker.
        flow_bin_injector: optional callable(envelope_dict) -> str returning
            the flow_bin for that envelope. If None, defaults to 'positive'
            (useful for INV-FLOW-2.1-A correctness verification on the
            load-bearing BUY-HIGH/BUY-MED case).

    Returns:
        Phase1Report with cohort_size, results, disposition_counts, gate flags.
    """
    pattern = os.path.join(envelope_dir, "pm-supervisor__*.json")
    paths = [p for p in sorted(glob.glob(pattern)) if not p.endswith(".context.json")]

    report = Phase1Report(cohort_size=0)
    injector = flow_bin_injector or (lambda env: "positive")

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

        flow_bin = injector(env)
        if flow_bin not in ("positive", "neutral", "negative", "unavailable"):
            report.notes.append(
                f"injector produced invalid bin {flow_bin!r} for {run_id}; skipped"
            )
            continue

        band_min, band_max = _band_lookup(conviction)
        cell_size = flow_cell_size_pct(conviction, flow_bin, band_min, band_max)
        cell_disp = flow_disposition(conviction, flow_bin)

        report.results.append(EnvelopeResult(
            run_id=run_id,
            ticker=env_ticker,
            conviction=conviction,
            flow_bin=flow_bin,
            cell_size_pct=cell_size,
            cell_disposition=cell_disp,
        ))
        report.cohort_size += 1
        report.disposition_counts[cell_disp] = (
            report.disposition_counts.get(cell_disp, 0) + 1
        )

    report.invalid_dispositions = [
        r.cell_disposition for r in report.results
        if r.cell_disposition not in VALID_DISPOSITION_VALUES
    ]
    report.all_dispositions_valid = len(report.invalid_dispositions) == 0

    if report.cohort_size > 0:
        most_common = max(
            report.disposition_counts.items(), key=lambda kv: kv[1]
        )
        report.notes.append(
            f"most-common disposition: {most_common[0]} "
            f"({most_common[1]}/{report.cohort_size})"
        )

    return report


def format_report(report: Phase1Report) -> str:
    """Render Phase 1 report as human-readable text."""
    lines: list[str] = []
    lines.append(f"Phase 1 cohort size: {report.cohort_size}")
    lines.append(f"All dispositions valid (INV-FLOW-2.1-A): {report.all_dispositions_valid}")
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
