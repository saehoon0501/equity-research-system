"""P3 mechanical scorer CLI.

Usage::

    python -m p3_mechanical_scorer.cli score --ticker NVDA
    python -m p3_mechanical_scorer.cli score --ticker NVDA --high-stakes
    python -m p3_mechanical_scorer.cli score --ticker NVDA \\
        --inputs-json /path/to/p3_inputs.json --output-json /tmp/out.json

The CLI is intentionally adapter-agnostic. v0.1 ships the
:class:`JsonFileAdapter` which loads Stage-1 facts and Stage-2 evidence
from a JSON file (operator-curated). v0.5+ will swap in a real
DataAdapter querying Postgres + EDGAR + Sharadar; that adapter lives in
``src/data_layer`` (out of scope for this build).

Input JSON shape (matches adapter contract)::

    {
      "tickers": {
        "NVDA": {
          "stage1": {
            "fraud_signature": {
              "charismatic_ceo_with_mystique": false,
              "board_lacks_domain_or_co_opted": false,
              "novel_accounting_or_metrics": false,
              "secrecy_under_trade_secret_cover": false,
              "dismissed_bear_research": false,
              "related_party_transactions": false,
              "evidence": {}
            },
            "era_fit": {
              "era_fit": true,
              "rationale": "Structurally captures AI-compute infra via CUDA",
              "evidence_quote": "..."
            },
            "tier_a": {
              "founder_ceo_duration_ge_15y": true,
              "per_share_value_primary_metric": false,
              "roiic_gt_15_sustained": true,
              "pivot_creates_multi_bag": true,
              "evidence": {}
            }
          },
          "evidence_corpus": [
            {"source_id": "10K-2024", "kind": "filing",
             "text": "Verbatim filing excerpts ..."}
          ]
        }
      }
    }

NOTE: for tests we accept missing files gracefully — the CLI prints a
message and exits 2.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional

from .orchestrator import score_ticker
from .stage1a_multiplicative_knockout import EraFitInput, FraudSignatureInput
from .stage1b_tier_a_composite import TierAInput
from .stage2_llm_rubric import EvidenceCorpus

_LOG = logging.getLogger("p3.cli")


class JsonFileAdapter:
    """Adapter loading inputs from a flat JSON file. v0.1 stand-in."""

    def __init__(self, path: Path):
        with path.open("r", encoding="utf-8") as fh:
            self._raw = json.load(fh)

    def _get_ticker_block(self, ticker: str) -> dict:
        block = self._raw.get("tickers", {}).get(ticker)
        if block is None:
            raise KeyError(
                f"ticker {ticker!r} not present in inputs JSON; available: "
                f"{sorted(self._raw.get('tickers', {}).keys())}"
            )
        return block

    def fetch_stage1_inputs(
        self, ticker: str
    ) -> tuple[FraudSignatureInput, EraFitInput, TierAInput]:
        block = self._get_ticker_block(ticker)
        s1 = block.get("stage1", {})
        fraud_d = dict(s1.get("fraud_signature", {}))
        era_d = dict(s1.get("era_fit", {}))
        tier_d = dict(s1.get("tier_a", {}))
        # Filter to known fields (defensive)
        fraud = FraudSignatureInput(
            **{k: fraud_d.get(k) for k in (
                "charismatic_ceo_with_mystique",
                "board_lacks_domain_or_co_opted",
                "novel_accounting_or_metrics",
                "secrecy_under_trade_secret_cover",
                "dismissed_bear_research",
                "related_party_transactions",
            )},
            evidence=fraud_d.get("evidence", {}) or {},
        )
        era = EraFitInput(
            era_fit=era_d.get("era_fit"),
            rationale=era_d.get("rationale"),
            evidence_quote=era_d.get("evidence_quote"),
        )
        tier_a = TierAInput(
            **{k: tier_d.get(k) for k in (
                "founder_ceo_duration_ge_15y",
                "per_share_value_primary_metric",
                "roiic_gt_15_sustained",
                "pivot_creates_multi_bag",
            )},
            evidence=tier_d.get("evidence", {}) or {},
        )
        return fraud, era, tier_a

    def fetch_evidence_corpus(self, ticker: str) -> EvidenceCorpus:
        block = self._get_ticker_block(ticker)
        docs = block.get("evidence_corpus", [])
        # Defensive: ensure no Stage-1 keys leak into corpus (info-isolation).
        forbidden_keys = {"stage1", "stage_1", "tier_a", "rule_output", "fraud_signature"}
        for d in docs:
            stray = forbidden_keys & set(d.keys())
            if stray:
                raise ValueError(
                    f"evidence document for {ticker} contains forbidden "
                    f"Stage-1 keys {stray}"
                )
        return EvidenceCorpus(ticker=ticker, documents=list(docs))


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="p3_mechanical_scorer.cli",
        description="P3 hybrid scorer (Section 4.3, v3 spec).",
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    score = sub.add_parser("score", help="Run the P3 pipeline for a ticker.")
    score.add_argument("--ticker", required=True, help="Ticker symbol.")
    score.add_argument(
        "--inputs-json",
        type=Path,
        default=None,
        help="Path to inputs JSON. If omitted, looks for ./p3_inputs.json.",
    )
    score.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="If set, write outcome JSON to this path; otherwise print to stdout.",
    )
    score.add_argument(
        "--high-stakes",
        action="store_true",
        help="Route Stage 2 to Opus regardless of per-pattern contested flag.",
    )
    score.add_argument(
        "--no-llm",
        action="store_true",
        help=(
            "Skip live LLM calls; inject a deterministic stub that returns "
            "LOW for every pattern. Useful for smoke-testing Stage 1 only."
        ),
    )
    return p


def _stub_llm_caller(system: str, user: str, model: str, temperature: float) -> dict:
    """Return a deterministic LOW rating; used by --no-llm and tests."""
    return {
        "rating": "LOW",
        "confidence": 0.5,
        "evidence_quotes": [],
        "rationale": "no-llm stub: defaulting to LOW",
        "defer_to_human": True,
        "tie_break_applied": False,
    }


def main(argv: Optional[list] = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if args.cmd != "score":
        parser.print_help()
        return 2

    inputs_path = args.inputs_json or Path("p3_inputs.json")
    if not inputs_path.exists():
        print(
            f"ERROR: inputs JSON not found at {inputs_path}. "
            "Pass --inputs-json or create p3_inputs.json.",
            file=sys.stderr,
        )
        return 2

    adapter = JsonFileAdapter(inputs_path)
    llm_caller = _stub_llm_caller if args.no_llm else None
    outcome = score_ticker(
        ticker=args.ticker,
        adapter=adapter,
        high_stakes=args.high_stakes,
        llm_caller=llm_caller,
    )
    out = outcome.to_dict()
    if args.output_json:
        args.output_json.write_text(json.dumps(out, indent=2), encoding="utf-8")
        _LOG.info("wrote outcome to %s", args.output_json)
    else:
        print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
