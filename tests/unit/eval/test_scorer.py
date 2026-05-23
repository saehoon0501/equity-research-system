"""Inner-ring unit tests for src/eval/scorer.py — Layer 1 scorer.

These tests cover SIGNATURE + SHAPE only. Semantic table-driven cases
(per-label hit/miss correctness) require the rule table from /review-me
and are deferred to a follow-on commit.

Per docs/superpowers/specs/2026-05-23-ring-architecture-and-layer1-scaffold-design.md §5.3.
"""

import pytest

from src.eval.scorer import Label, ScoreInput, Verdict, score


class TestEnums:
    def test_label_has_all_four_bins(self):
        assert {l.value for l in Label} == {"BUY", "HOLD", "TRIM", "SELL"}

    def test_label_is_string_enum(self):
        assert Label.BUY == "BUY"
        assert isinstance(Label.BUY.value, str)

    def test_verdict_has_hit_and_miss(self):
        assert {v.value for v in Verdict} == {"hit", "miss"}


class TestScoreInputDataclass:
    def test_constructable_with_required_fields(self):
        inp = ScoreInput(label=Label.BUY, excess_return_pct=5.0, margin_pct=2.0)
        assert inp.label is Label.BUY
        assert inp.excess_return_pct == 5.0
        assert inp.margin_pct == 2.0

    def test_is_frozen(self):
        inp = ScoreInput(label=Label.BUY, excess_return_pct=5.0, margin_pct=2.0)
        with pytest.raises(Exception):
            inp.excess_return_pct = 10.0  # type: ignore[misc]


class TestScoreSignature:
    def test_returns_verdict_type(self):
        inp = ScoreInput(label=Label.BUY, excess_return_pct=5.0, margin_pct=2.0)
        result = score(inp)
        assert isinstance(result, Verdict)

    def test_all_labels_produce_valid_verdict(self):
        for label in Label:
            inp = ScoreInput(label=label, excess_return_pct=0.0, margin_pct=2.0)
            result = score(inp)
            assert result in (Verdict.HIT, Verdict.MISS)

    def test_deterministic_same_input_same_output(self):
        inp = ScoreInput(label=Label.BUY, excess_return_pct=5.0, margin_pct=2.0)
        assert score(inp) == score(inp)


@pytest.mark.skip(reason="Semantic cases pending /review-me hit/miss rule table per spec §5.2")
class TestSemanticRules:
    """Filled in once /review-me confirms the per-label hit/miss rule table.

    Anticipated cases per spec §5.3:
        - Each label × {strongly hit, marginal hit, marginal miss, strongly miss}
        - Boundary cases at excess_return == ±margin
        - Zero excess return for HOLD
        - Sign-flip edge: BUY with deeply negative excess_return must MISS
    """

    def test_placeholder(self):
        pass
