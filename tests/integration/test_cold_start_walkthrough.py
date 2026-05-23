"""Cold-start day-1 launch walkthrough reproducer (Section 7.3a #4).

Validates the cold-start cap on conviction. Per Phase 4 Q2 + Section 7.5:

  HIGH conviction requires (post day-90) all of:
    1. Mode classifier rule_clean=True
    2. Debate consensus ≥4/5 ADD
    3. Counterfactual top-3 ≥2 SURVIVOR-leaning matches
    4. Anchor-drift channels triggered: 0
    5. Catalog HMAC integrity: PASS

On day-1 (cold-start), gate #4 is *trivially* satisfied — anchor-drift
channels return NULL because no thesis_pillars_original baseline exists yet.
The ``channels_triggered=0`` value is vacuous, not earned. The cold-start cap
sits OUTSIDE the rollup layer (it modulates emitted conviction post-rollup);
this reproducer asserts the architectural intent: a system that emits HIGH
on a vacuous-zero day-1 has no empirical foundation. The fix is to apply the
cold-start cap as a downstream demote step.

Asserts:
  * Raw rollup against a clean day-1 input set returns HIGH (gates 1-5 pass).
  * Applying a deterministic ``apply_cold_start_cap`` demotes to MEDIUM.
  * The cap distinguishes vacuous-zero (cold_start=True) from earned-zero
    (cold_start=False) — same gate inputs, different emitted conviction.

The cold-start cap helper is defined in this test module (a small adapter
around the rollup output); the architectural lock is the precedence rule.
The full ``cold_start`` propagation lives at the recommendation-emitter
layer, but the conviction-cap policy is what this walkthrough validates.

Reproduces ``docs/superpowers/launch-walkthroughs/cold-start-day-1.md``.
"""

from __future__ import annotations

from src.p7_recommendation_emitter.conviction_rollup import (
    CONVICTION_HIGH,
    CONVICTION_MEDIUM,
    ConvictionInputs,
    ConvictionRollup,
    roll_up_conviction,
)


def apply_cold_start_cap(
    rollup: ConvictionRollup, *, cold_start: bool
) -> ConvictionRollup:
    """Section 7.5 cold-start cap: demote HIGH→MEDIUM when cold_start=True.

    The cap exists because gate #4 (anchor-drift channels triggered)
    cannot evaluate meaningfully on day-1 (no thesis_pillars_original
    baseline). channels_triggered=0 is vacuous, not earned. The cap
    closes the loophole.

    Returns a NEW rollup; does not mutate the input.
    """
    if not cold_start:
        return rollup
    if rollup.bucket != CONVICTION_HIGH:
        return rollup  # already MEDIUM/LOW; cap is no-op
    return ConvictionRollup(
        bucket=CONVICTION_MEDIUM,
        breakdown={
            **rollup.breakdown,
            "rolled_up_via": "MEDIUM (cold-start cap applied)",
            "cold_start_cap_applied": True,
            "cap_reason": (
                "anchor-drift channels triggered=0 is vacuous on day-1 "
                "(no thesis_pillars_original baseline yet); cap demotes "
                "HIGH to MEDIUM per Section 7.5 + Phase 4 Q2"
            ),
        },
        triggered_rules=[
            *rollup.triggered_rules,
            "cold_start=True → MEDIUM cap (vacuous-zero loophole)",
        ],
    )


class TestColdStartCap:
    """Section 7.3a #4 — the cold-start cap on conviction."""

    def _clean_buy_inputs(self) -> ConvictionInputs:
        """A canonical day-1 NVDA-shaped clean BUY input.

        Gates 1-5 all pass; cold-start cap is the only thing keeping it
        from emitting HIGH.
        """
        return ConvictionInputs(
            debate_add_count=5,
            kills_fired=0,
            anchor_drift_channels_triggered=0,  # vacuous on day-1
            debate_total=5,
        )

    def test_raw_rollup_returns_HIGH_when_gates_1_to_5_pass(self) -> None:
        """Without the cold-start cap, the rollup emits HIGH on a clean day-1."""
        result = roll_up_conviction(self._clean_buy_inputs())
        assert result.bucket == CONVICTION_HIGH

    def test_cold_start_cap_demotes_HIGH_to_MEDIUM(self) -> None:
        """Day-1 with cold_start=True caps the emitted conviction at MEDIUM."""
        raw = roll_up_conviction(self._clean_buy_inputs())
        capped = apply_cold_start_cap(raw, cold_start=True)
        assert capped.bucket == CONVICTION_MEDIUM
        assert capped.breakdown["cold_start_cap_applied"] is True
        assert "vacuous" in capped.breakdown["cap_reason"]

    def test_post_cold_start_no_cap_HIGH_stays_HIGH(self) -> None:
        """Day-91+ (cold_start=False) does NOT apply the cap; HIGH remains HIGH.

        This is the architectural symmetry: same gate inputs, different
        emitted conviction depending on whether the channels_triggered=0
        is vacuous (cold-start) or earned (post-day-90).
        """
        raw = roll_up_conviction(self._clean_buy_inputs())
        post_cap = apply_cold_start_cap(raw, cold_start=False)
        assert post_cap.bucket == CONVICTION_HIGH
        # Underlying rollup unchanged; no cap metadata injected.
        assert "cold_start_cap_applied" not in post_cap.breakdown

    def test_cold_start_cap_no_op_on_non_HIGH(self) -> None:
        """If rollup is already MEDIUM/LOW the cap is a no-op (idempotent)."""
        # Force MEDIUM via 3/5 debate.
        inp = ConvictionInputs(
            debate_add_count=3,
            kills_fired=0,
            anchor_drift_channels_triggered=0,
            debate_total=5,
        )
        raw = roll_up_conviction(inp)
        assert raw.bucket == CONVICTION_MEDIUM
        capped = apply_cold_start_cap(raw, cold_start=True)
        # Same MEDIUM bucket; no spurious cap metadata.
        assert capped.bucket == CONVICTION_MEDIUM
        assert capped is raw  # short-circuit: no-op returns the input

    def test_cold_start_does_not_promote(self) -> None:
        """The cap demotes only; cold_start=True cannot turn LOW into MEDIUM."""
        # Force LOW via <3/5 debate.
        inp = ConvictionInputs(
            debate_add_count=1,
            kills_fired=0,
            anchor_drift_channels_triggered=0,
            debate_total=5,
        )
        raw = roll_up_conviction(inp)
        assert raw.bucket == "LOW"
        capped = apply_cold_start_cap(raw, cold_start=True)
        assert capped.bucket == "LOW"  # no promotion
