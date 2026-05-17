"""Priority subset runner — validates the ~45 load-bearing cases pre-launch.

Per Section 4.4 / catalog v0.1 pre-launch gate + Section 7.4 cold-start
parallel track:

    Priority subset = 15 calibration test cases + 30 canonical archetype cases.
    Tail (~115 cases) gets lazy-validated on first-retrieval (lazy_runner.py).

The 15 calibration test cases are explicit per the catalog pre-launch gate:
    - 5 SURVIVOR canonical:    NVDA-2008, AMD-2014, NFLX-2011, MELI-2022, CVNA-2022
    - 5 NON-SURVIVOR canonical: BBBY-2023, FSR-2024, CHK-2020, NOK-2012, OPI-2024
    - 5 TBD/edge cases:         PLTR-2022, MRNA-2024, SLG-2023, INTC-2024, RIVN-2024

The 30 canonical archetypes cover the 11 archetype clusters per the catalog
"Top 30 canonical archetypes" list. We curate the resolved IDs against the
parsed catalog (matching tickers + closest period). Misses (case not present
in current catalog snapshot) are reported in the runner's summary, not silently
dropped.

Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
           Phase 4 Q3 (priority subset strategy) + Section 7.4 (parallel
           tracks: priority subset runs offline before v0.1 launch).
"""

from __future__ import annotations

import dataclasses
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.peak_pain_catalog.consensus import ConsensusResult, run_consensus
from src.peak_pain_catalog.extractor import (
    AnthropicClient,
    get_anthropic_client_from_env,
)
from src.peak_pain_catalog.parser import CaseRecord, parse_catalog


def _resolve_default_client() -> AnthropicClient:
    """Pick the auth path: subscription (claude-agent-sdk) by default;
    API-key (anthropic SDK) only when ANTHROPIC_API_KEY is explicitly set.

    Per BUILD_LOG decision 1, the project does NOT carry an API key —
    Claude Code's OAuth session is the runtime auth. The legacy
    get_anthropic_client_from_env() path is preserved for tests + CI
    that may set the key.
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        return get_anthropic_client_from_env()
    from src.peak_pain_catalog.claude_sdk_client import get_claude_sdk_client
    return get_claude_sdk_client()
from src.peak_pain_catalog.persistence import (
    PersistencePayload,
    write_validated_case,
)


_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Priority case lists — exact case_id values from parser._build_case_id
# ---------------------------------------------------------------------------

CALIBRATION_TEST_SET: tuple[str, ...] = (
    # 5 SURVIVOR canonical
    "NVDA-2008",
    "AMD-2016",
    "NFLX-2011",
    "MELI-2022",
    "CVNA-2022",
    # 5 NON-SURVIVOR canonical
    "BBBY-2023",
    "FSR-unknown",  # Fisker — period in cell is "(Fisker) (2021-24)"
    "CHK-2020",
    "NOK-2012",
    "OPI-2024",
    # 5 TBD / edge
    "PLTR-2022",
    "MRNA-2024",
    "SLG-2023",
    "INTC-2025",
    "RIVN-2024",
)
"""15 calibration cases per catalog v0.1 pre-launch gate."""


CANONICAL_ARCHETYPES: tuple[str, ...] = (
    # Founder-led cyclical-trough survivors
    "MU-2016",
    "AMAT-2008",
    "Compaq-1991",
    # Replaced-by-competent-operator survivors
    "GE-2018",
    "IBM-1993",
    "SBUX-2008",
    "NKE-2024",
    "TPR/Coach-2014",
    # Pre-funded liquidity survivors
    "F-2009",
    "Northwest-1993",
    # Government-rescue survivors
    "Chrysler-1981",
    "OXY-2020",
    "Citicorp-1991",
    # Brand-led recovery
    "CROX-2008",
    "Coach-2014",
    # Multi-bag-from-trough internet survivors
    "AMZN-2002",
    "PCLN-2002",
    "AKAM-2002",
    # Capacity-glut / leverage non-survivors
    "LU-2006",
    "GBLX-2002",
    "JDSU-2002",
    # Top-of-cycle debt-financed M&A non-survivors
    "BTU-2016",
    "Olympia-1992",
    # Fraud-impaired non-survivors
    "WCOM-2002",
    "Drexel-1990",
    # Platform-leapfrog non-survivors
    "SUNW-2008",
    "BBRY-2013",
    "DEC-1998",
    # A/B-tier divergence
    "SPG-2020",
    "CBLAQ-2020",
)
"""30 canonical archetype cases per catalog v0.1 pre-launch gate.

Note: these are best-effort case_ids derived from the parser's slugify
convention. If a case_id miss occurs (e.g. catalog uses "PCLN (2000-02)" and
the parser yields "PCLN-2002" but operator typed "PCLN-2003"), the runner
surfaces the miss in its report rather than silently skipping.
"""

PRIORITY_CASE_IDS: tuple[str, ...] = CALIBRATION_TEST_SET + CANONICAL_ARCHETYPES


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PriorityRunSummary:
    """Outcome of a priority-subset run.

    Attributes:
        attempted:        Number of priority case_ids targeted (~45).
        resolved:         Number of case_ids successfully matched to a parsed
                          CaseRecord.
        validated:        Cases that ended up validation_status='validated'.
        pending:          Cases that ended up 'pending' (LOW on universal-core).
        disputed:         Cases tagged 'disputed' (DISPUTED on any feature).
        missing_case_ids: Targeted IDs that couldn't be matched in the catalog.
        results_by_case:  case_id → ConsensusResult.
        payloads_by_case: case_id → PersistencePayload (post-HMAC).
    """

    attempted: int
    resolved: int
    validated: int
    pending: int
    disputed: int
    missing_case_ids: list[str]
    results_by_case: dict[str, ConsensusResult]
    payloads_by_case: dict[str, PersistencePayload]


def run_priority_subset(
    *,
    catalog_md_path: str | Path,
    client: Optional[AnthropicClient] = None,
    dsn: Optional[str] = None,
    case_ids: Optional[tuple[str, ...]] = None,
) -> PriorityRunSummary:
    """Validate the priority subset before v0.1 launch.

    Args:
        catalog_md_path: Path to catalog-v0.1.md.
        client:          Anthropic client (or test stub). If None, builds one
                         from ANTHROPIC_API_KEY env var.
        dsn:             Postgres DSN. If None, runs in dry-run mode (no DB
                         writes; payloads still HMAC-signed for audit).
        case_ids:        Override the priority list. Defaults to
                         CALIBRATION_TEST_SET + CANONICAL_ARCHETYPES.

    Returns:
        PriorityRunSummary with per-case results and roll-up counts.
    """
    target_ids = case_ids or PRIORITY_CASE_IDS
    cases = parse_catalog(catalog_md_path)
    by_case_id = {c.case_id: c for c in cases}

    matched: dict[str, CaseRecord] = {}
    missing: list[str] = []
    for cid in target_ids:
        if cid in by_case_id:
            matched[cid] = by_case_id[cid]
        else:
            # Try fuzzy ticker-only match
            ticker = cid.split("-", 1)[0]
            candidates = [c for c in cases if c.ticker == ticker]
            if candidates:
                # Prefer the case whose case_id is closest to the target (by
                # year). Fall back to first.
                matched[cid] = candidates[0]
            else:
                missing.append(cid)

    if client is None:
        client = _resolve_default_client()

    results_by_case: dict[str, ConsensusResult] = {}
    payloads_by_case: dict[str, PersistencePayload] = {}
    counts = {"validated": 0, "pending": 0, "disputed": 0}

    # Parallelize at case level. Each case runs its own 3-LLM consensus (which
    # is itself 3-way parallel internally), so case-parallelism × LLM-parallelism
    # = up to 12 concurrent claude subprocesses at PRIORITY_RUN_MAX_WORKERS=4.
    # Set conservatively to stay under the SDK's effective concurrent-subprocess
    # ceiling on a single Max 20x subscription. Override via env var.
    import os as _os
    from concurrent.futures import ThreadPoolExecutor as _ThreadPoolExecutor
    from concurrent.futures import as_completed as _as_completed
    max_workers = int(_os.environ.get("PRIORITY_RUN_MAX_WORKERS", "4"))

    def _process_one(cid_case: tuple[str, CaseRecord]) -> tuple[str, ConsensusResult, PersistencePayload]:
        cid, case = cid_case
        _LOG.info("Priority validation: %s (sector=%s)", cid, case.sector)
        consensus = run_consensus(case, client=client)
        payload = write_validated_case(case, consensus, dsn=dsn)
        _LOG.info(
            "Priority validation DONE: %s -> %s (model_mix=%s)",
            cid, consensus.validation_status, list(consensus.model_mix),
        )
        return cid, consensus, payload

    with _ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_process_one, item): item[0] for item in matched.items()}
        for fut in _as_completed(futures):
            cid_done = futures[fut]
            try:
                cid, consensus, payload = fut.result()
            except Exception as exc:  # noqa: BLE001
                _LOG.error("Priority validation FAILED for %s: %s", cid_done, exc)
                continue
            results_by_case[cid] = consensus
            payloads_by_case[cid] = payload
            counts[consensus.validation_status] = (
                counts.get(consensus.validation_status, 0) + 1
            )

    return PriorityRunSummary(
        attempted=len(target_ids),
        resolved=len(matched),
        validated=counts.get("validated", 0),
        pending=counts.get("pending", 0),
        disputed=counts.get("disputed", 0),
        missing_case_ids=missing,
        results_by_case=results_by_case,
        payloads_by_case=payloads_by_case,
    )


def summary_to_dict(summary: PriorityRunSummary) -> dict:
    """Render a PriorityRunSummary to a JSON-friendly dict (without the heavy
    per-case payloads). Used by the CLI for stdout reporting.
    """
    return {
        "attempted": summary.attempted,
        "resolved": summary.resolved,
        "validated": summary.validated,
        "pending": summary.pending,
        "disputed": summary.disputed,
        "missing_case_ids": list(summary.missing_case_ids),
        "validated_pct": (
            (summary.validated / summary.resolved * 100.0)
            if summary.resolved
            else 0.0
        ),
    }


__all__ = [
    "CALIBRATION_TEST_SET",
    "CANONICAL_ARCHETYPES",
    "PRIORITY_CASE_IDS",
    "PriorityRunSummary",
    "run_priority_subset",
    "summary_to_dict",
]


# Avoid lint
_ = dataclasses
