"""Feature extraction at peak-pain trigger (v3 spec Section 4.5 Q6 / Section 4.4).

When a watchlist candidate hits 2× the mode-tuned cut threshold (Section 4.5
Q6 activation gate: B/20pp, B'/24pp, C/30pp drawdown vs benchmark), this
module extracts the candidate's CURRENT structural features so the retrieval
layer can match against the peak-pain archetype catalog.

We REUSE the peak_pain_catalog 3-LLM consensus pipeline rather than
duplicating extraction logic (per task brief — don't duplicate). The candidate
is wrapped as a CaseRecord with `outcome='TBD'` (we don't know yet which
archetype it will become — that's exactly what the catalog retrieval is
trying to estimate).

Output schema mirrors what `retrieval.py` consumes:

    {
        "universal_core": {
            "founder_insider_stake_direction": "increasing",
            "cash_runway": ">24mo",
            ... (6 features)
        },
        "sector_extensions": {
            "customer_engagement": "holding",
            ... (variable per sector)
        },
        "consensus": {
            "founder_insider_stake_direction": "HIGH",
            ... (per-feature HIGH/MEDIUM/LOW/DISPUTED)
        },
        "sector": "tech_saas",
        "ticker": "PLTR",
        "extraction_date": "2026-04-29",
    }

Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
           Section 4.4 (universal core + sector extensions),
           Section 4.5 Q6 (peak-pain trigger activation gate),
           Section 5 Q3 + Phase 4 Q4 (3-LLM iterative-consensus pipeline).
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any

from src.peak_pain_catalog.consensus import (
    ConsensusResult,
    DEFAULT_MODEL_MIX,
    run_consensus,
)
from src.peak_pain_catalog.extractor import AnthropicClient
from src.peak_pain_catalog.parser import CaseRecord


@dataclass(frozen=True)
class CandidateFeatures:
    """Materialized current-features view for a peak-pain candidate.

    Attributes:
        ticker:             Candidate ticker (e.g., 'PLTR').
        sector:             Canonical sector key (e.g., 'tech_saas').
        extraction_date:    ISO date the extraction ran.
        universal_core:     6 universal-core feature values (Section 4.4 Layer 1).
        sector_extensions:  Sector-specific feature values (Section 4.4 Layer 2).
        consensus:          Per-feature HIGH/MEDIUM/LOW/DISPUTED grade.
        verbatim_quotes:    Per-feature audit quotes from the agreement band.
        raw_consensus:      Underlying ConsensusResult (audit chain).
    """

    ticker: str
    sector: str
    extraction_date: str
    universal_core: dict[str, str]
    sector_extensions: dict[str, str]
    consensus: dict[str, str]
    verbatim_quotes: dict[str, list[str]] = field(default_factory=dict)
    raw_consensus: ConsensusResult | None = None

    def to_dict(self) -> dict[str, Any]:
        """Plain-dict view for retrieval input + audit chain serialization."""
        return {
            "ticker": self.ticker,
            "sector": self.sector,
            "extraction_date": self.extraction_date,
            "universal_core": dict(self.universal_core),
            "sector_extensions": dict(self.sector_extensions),
            "consensus": dict(self.consensus),
        }


def extract_candidate_features(
    *,
    ticker: str,
    sector: str,
    descriptive_text: str,
    client: AnthropicClient,
    extraction_date: str | None = None,
    model_mix: tuple[str, str, str] = DEFAULT_MODEL_MIX,
    period: str | None = None,
) -> CandidateFeatures:
    """Extract candidate features at peak-pain trigger via 3-LLM consensus.

    The candidate is wrapped as a CaseRecord with `outcome='TBD'` and
    `era_category='recent'` — these are the right values for a live ticker
    we're evaluating, NOT a historical archetype.

    Args:
        ticker:           Candidate ticker.
        sector:           Canonical sector key from
                          ``peak_pain_catalog.parser.SECTOR_HEADINGS``.
        descriptive_text: Concatenated structural-features text (financials
                          summary, recent filings excerpts, founder/insider
                          stake notes, etc.) the LLM extractor will ground on.
        client:           Anthropic client (or test stub) for the 3 LLM calls.
        extraction_date:  ISO date of extraction; defaults to today.
        model_mix:        3-LLM triplet; defaults to (sonnet, sonnet, opus)
                          per Section 5 Q3.
        period:           Optional period string (defaults to 'YYYY' from
                          extraction_date).

    Returns:
        CandidateFeatures with universal_core + sector_extensions populated
        plus per-feature consensus grades for downstream retrieval scoring.
    """
    # UTC date — ``date.today()`` reads the server's local timezone; the
    # ``extraction_date`` is used in ``case_id`` and as the period default,
    # both of which require a UTC-stable value across server timezones.
    today = extraction_date or _dt.datetime.now(_dt.timezone.utc).date().isoformat()
    period_str = period or today[:4]
    case = CaseRecord(
        case_id=f"{ticker}-CANDIDATE-{today}",
        ticker=ticker,
        period=period_str,
        sector=sector,
        era_category="recent",
        outcome_raw="TBD",
        outcome="TBD",
        peak_dd_pct=float("nan"),
        raw_row_cells=[],
        column_headers=[],
        descriptive_text=descriptive_text,
    )

    consensus = run_consensus(case, client=client, model_mix=model_mix)

    universal_core: dict[str, str] = {}
    sector_extensions: dict[str, str] = {}
    grades: dict[str, str] = {}
    quotes: dict[str, list[str]] = {}

    for feat, fc in consensus.universal_core.items():
        universal_core[feat] = fc.value
        grades[feat] = fc.consensus
        quotes[feat] = list(fc.verbatim_quotes)

    for feat, fc in consensus.sector_extensions.items():
        sector_extensions[feat] = fc.value
        grades[feat] = fc.consensus
        quotes[feat] = list(fc.verbatim_quotes)

    return CandidateFeatures(
        ticker=ticker,
        sector=sector,
        extraction_date=today,
        universal_core=universal_core,
        sector_extensions=sector_extensions,
        consensus=grades,
        verbatim_quotes=quotes,
        raw_consensus=consensus,
    )


def candidate_from_dict(payload: dict[str, Any]) -> CandidateFeatures:
    """Inverse of `CandidateFeatures.to_dict` — used by tests + lifecycle.refresh."""
    return CandidateFeatures(
        ticker=payload["ticker"],
        sector=payload["sector"],
        extraction_date=payload["extraction_date"],
        universal_core=dict(payload.get("universal_core") or {}),
        sector_extensions=dict(payload.get("sector_extensions") or {}),
        consensus=dict(payload.get("consensus") or {}),
        verbatim_quotes={},
        raw_consensus=None,
    )
