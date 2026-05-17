"""Regression tests for `_parse_response_json` fence-handling bug.

Caught 2026-04-30 during gate-21 (peak-pain catalog priority validation):
the prior fence-strip path used ``s.split("```", 2)[-1]`` which for a
fully-fenced response like ``"```json\\n{...}\\n```"`` returns the EMPTY
trailing element after the closing fence — silently emptying the payload
and forcing every feature to its CONSERVATIVE_DEFAULTS value. This caused
every catalog extraction the entire session to default; validation_status
always rolled up to LOW or DISPUTED (never `validated`) regardless of how
rich the evidence file was, because the LLM's correct JSON output was
discarded by the parser.

The fix: locate the outermost ``{...}`` substring with ``find("{")`` /
``rfind("}")`` and parse it directly — robust to fences, partial fences,
and prose wrappers.
"""

from __future__ import annotations

import pytest

from src.peak_pain_catalog.extractor import _parse_response_json


def test_parse_fully_fenced_json_response():
    """The bug case: response wrapped in ```json ... ``` fences MUST parse."""
    raw = '```json\n{"founder_in_place": {"value": "yes", "verbatim_quote": "..."}}\n```'
    result = _parse_response_json(raw)
    assert "founder_in_place" in result
    assert result["founder_in_place"]["value"] == "yes"


def test_parse_unfenced_json_response():
    """Bare JSON (no fences) must still parse — the system prompt asks for this."""
    raw = '{"feature": {"value": "x", "verbatim_quote": "y"}}'
    result = _parse_response_json(raw)
    assert result == {"feature": {"value": "x", "verbatim_quote": "y"}}


def test_parse_json_with_leading_prose():
    """Some models add a preamble — the parser should locate {...} regardless."""
    raw = 'Here is the result:\n```json\n{"k": "v"}\n```\nLet me know if you need more.'
    result = _parse_response_json(raw)
    assert result == {"k": "v"}


def test_parse_json_partially_fenced():
    """Asymmetric fence (open only) must not break extraction."""
    raw = '```json\n{"k": "v"}\n'
    result = _parse_response_json(raw)
    assert result == {"k": "v"}


def test_parse_empty_returns_empty_dict():
    """Defensive — empty input → empty dict."""
    assert _parse_response_json("") == {}
    assert _parse_response_json("   ") == {}


def test_parse_no_braces_returns_empty():
    """Garbage with no JSON object → empty dict (caller falls back to defaults)."""
    assert _parse_response_json("just prose, no JSON here") == {}


def test_parse_malformed_json_returns_empty():
    """Malformed JSON inside braces → empty dict (graceful degradation)."""
    raw = '{"unclosed": "value"'
    assert _parse_response_json(raw) == {}


def test_parse_full_extraction_response_shape():
    """End-to-end shape — what the extractor actually receives from Sonnet,
    fenced with all 6 universal-core + sector_extension features."""
    raw = """```json
{
  "founder_insider_stake_direction": {"value": "flat", "verbatim_quote": "no share-count delta"},
  "cash_runway": {"value": ">24mo", "verbatim_quote": "$1.26 billion in cash"},
  "founder_in_place": {"value": "yes", "verbatim_quote": "Jen-Hsun Huang co-founded NVIDIA in April 1993"},
  "margin_trajectory": {"value": "deteriorating", "verbatim_quote": "GM declined to 29.4%"},
  "revenue_trajectory": {"value": "declining", "verbatim_quote": "FY09 -16% y/y"},
  "industry_tailwind": {"value": "weakening", "verbatim_quote": "Global economic conditions have reduced demand"}
}
```"""
    result = _parse_response_json(raw)
    assert len(result) == 6
    assert result["founder_in_place"]["value"] == "yes"
    assert "verbatim_quote" in result["cash_runway"]
    assert result["industry_tailwind"]["value"] == "weakening"
