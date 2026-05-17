"""Tests for src.calibration.believability."""

from __future__ import annotations

import pytest

from src.calibration.believability import (
    StyleBrier,
    _aggregate_styles,
    _extract_verdict,
    synthesize_with_believability,
)


# --------------------------------------------------------------------------- #
# _extract_verdict                                                            #
# --------------------------------------------------------------------------- #


def test_extract_verdict_dict_path():
    blob = {"value": {"verdict": "ADD"}, "growth": {"verdict": "WATCH"}}
    assert _extract_verdict(blob, "value") == "ADD"
    assert _extract_verdict(blob, "growth") == "WATCH"


def test_extract_verdict_json_string():
    blob = '{"value": {"verdict": "pass"}}'
    assert _extract_verdict(blob, "value") == "PASS"


def test_extract_verdict_missing_returns_none():
    assert _extract_verdict({"value": {}}, "value") is None
    assert _extract_verdict({}, "value") is None
    assert _extract_verdict("not json", "value") is None


# --------------------------------------------------------------------------- #
# _aggregate_styles                                                           #
# --------------------------------------------------------------------------- #


def test_aggregate_styles_assigns_inverse_brier_weights():
    """Style-A always-correct (Brier ≈ 0) should get higher weight than
    Style-B always-wrong (Brier ≈ 1)."""
    # Two BUY recs, both alpha-positive (delta=+0.05).
    # value calls ADD (matches → favorable), quant_technical calls PASS
    # (predicts against → un-favorable for that style).
    rows = [
        (
            {
                "value": {"verdict": "ADD"},
                "quant_technical": {"verdict": "PASS"},
            },
            "BUY",
            0.05,
        ),
        (
            {
                "value": {"verdict": "ADD"},
                "quant_technical": {"verdict": "PASS"},
            },
            "BUY",
            0.05,
        ),
    ]
    cells = _aggregate_styles(rows)
    by_style = {sb.style: sb for sb in cells}
    # value's Brier: (0.65-1)^2 = 0.1225 every row → mean 0.1225
    # quant_technical's Brier: (0.35-1)^2 = 0.4225 → mean 0.4225
    assert by_style["value"].brier == pytest.approx(0.1225)
    assert by_style["quant_technical"].brier == pytest.approx(0.4225)
    # value should weight higher (inverse-brier) than quant_technical
    assert (
        by_style["value"].weight_inverse_brier
        > by_style["quant_technical"].weight_inverse_brier
    )
    # Weights normalize to 1.0
    assert sum(sb.weight_inverse_brier for sb in cells) == pytest.approx(1.0)


def test_aggregate_styles_empty_when_no_rows():
    assert _aggregate_styles([]) == []


def test_aggregate_styles_skips_unknown_verdicts():
    rows = [
        ({"value": {"verdict": "WHATEVER"}}, "BUY", 0.05),
    ]
    assert _aggregate_styles(rows) == []


# --------------------------------------------------------------------------- #
# synthesize_with_believability                                               #
# --------------------------------------------------------------------------- #


def test_synthesize_falls_back_to_equal_weight_with_no_history():
    """No Brier data → equal-weight average of verdicts."""
    style_verdicts = {"value": "ADD", "growth": "ADD", "quant_technical": "PASS"}
    out = synthesize_with_believability(style_verdicts, style_briers=[])
    # 2 ADDs + 1 PASS at equal weight = (1 + 1 + 0) / 3 ≈ 0.667 → ADD
    assert out["verdict"] == "ADD"
    assert out["fallback_equal_weight"] is True
    assert out["weighted_score"] == pytest.approx(2 / 3)


def test_synthesize_lets_high_believability_style_dominate():
    """A perfectly-calibrated style should drag the verdict toward its call."""
    style_verdicts = {"value": "PASS", "growth": "ADD"}
    style_briers = [
        # value calibrated tight; growth extremely poorly-calibrated
        StyleBrier(style="value", n=50, brier=0.05, weight_inverse_brier=0.95),
        StyleBrier(style="growth", n=50, brier=0.49, weight_inverse_brier=0.05),
    ]
    out = synthesize_with_believability(style_verdicts, style_briers)
    # value=PASS (score=0) at 0.95 weight + growth=ADD (score=1) at 0.05 weight
    # → 0.05 ⇒ PASS
    assert out["verdict"] == "PASS"
    assert out["fallback_equal_weight"] is False
    assert out["weighted_score"] == pytest.approx(0.05)


def test_synthesize_renormalizes_when_only_some_styles_have_history():
    """If only one of the present styles has history, it gets full weight."""
    style_verdicts = {"value": "ADD", "growth": "PASS"}
    style_briers = [
        StyleBrier(style="value", n=50, brier=0.05, weight_inverse_brier=1.0),
        # No growth history.
    ]
    out = synthesize_with_believability(style_verdicts, style_briers)
    # value (ADD=1) at full weight; growth missing → 0 contribution
    assert out["weighted_score"] == pytest.approx(1.0)
    assert out["verdict"] == "ADD"
