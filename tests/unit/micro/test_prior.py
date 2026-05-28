"""Tests for the /micro slow-layer prior resolver (PM Recommendation → PM report)."""

from __future__ import annotations

from src.micro.prior import from_code, from_report, resolve


def test_from_code_normalizes_and_validates():
    assert from_code("hold") == "HOLD"
    assert from_code(" Buy ") == "BUY"
    assert from_code("STRONG_BUY") is None  # not a canonical 4-bin
    assert from_code(None) is None


def test_from_report_json_envelope():
    assert from_report('{"summary_code": "SELL", "conviction": "HIGH"}') == "SELL"
    assert from_report('{"recommendation": "buy"}') == "BUY"


def test_from_report_markdown_labelled_line():
    memo = "# PM Supervisor Memo: MU\n\n## Recommendation: TRIM\nThesis intact but..."
    assert from_report(memo) == "TRIM"


def test_from_report_ignores_prose_mentions_without_label():
    # A bare "buy" in prose with no labelled recommendation -> no false positive.
    assert from_report("Investors may want to buy on weakness, but we are cautious.") is None
    # A labelled token buried MID-LINE in prose must not match (line-anchored).
    assert from_report("As noted, see recommendation - BUY below for details.") is None
    # A real labelled line still matches even amid surrounding prose.
    assert from_report("Intro paragraph.\n## Recommendation: SELL\nmore text") == "SELL"


def test_from_report_json_blob_prose_not_matched():
    # A parsed JSON object with no recognized key must NOT be regex-scanned for a
    # BUY/SELL mention inside a narrative field.
    envelope = '{"thesis": "we recommend: BUY only if margins recover", "conviction": "LOW"}'
    assert from_report(envelope) is None


def test_resolve_prefers_pm_recommendation():
    out = resolve(recommendation="HOLD", summary_code="SELL", report_text='{"recommendation":"BUY"}')
    assert out == {"summary_code": "HOLD", "source": "pm_recommendation"}


def test_resolve_falls_back_to_ledger_then_report():
    assert resolve(recommendation=None, summary_code="SELL")["source"] == "counterfactual_ledger"
    out = resolve(recommendation=None, summary_code=None, report_text="## Recommendation: BUY")
    assert out == {"summary_code": "BUY", "source": "pm_report"}


def test_resolve_none_when_nothing_found():
    assert resolve()["summary_code"] is None
    assert resolve(report_text="no call here")["source"] == "none"
