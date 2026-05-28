"""Calibration metrics — Brier / log-loss / reliability / block-bootstrap CI.

No live DB/API. Pure functions over frozen (scores, labels).
"""

from __future__ import annotations

import math

import pytest

from src.calibration import metrics as M


class TestBrierAndLogLoss:
    def test_brier_perfect_is_zero(self):
        scores = [1.0, 0.0, 1.0, 0.0]
        labels = [True, False, True, False]
        assert M.brier_score(scores, labels) == pytest.approx(0.0)

    def test_brier_worst_is_one(self):
        scores = [0.0, 1.0]
        labels = [True, False]
        assert M.brier_score(scores, labels) == pytest.approx(1.0)

    def test_brier_half_is_quarter(self):
        scores = [0.5, 0.5, 0.5, 0.5]
        labels = [True, False, True, False]
        assert M.brier_score(scores, labels) == pytest.approx(0.25)

    def test_log_loss_finite_on_confident_wrong(self):
        # eps-clipping keeps it finite rather than +inf.
        scores = [0.0]
        labels = [True]
        val = M.log_loss(scores, labels)
        assert math.isfinite(val)
        assert val > 30.0  # ~ -log(1e-15)

    def test_log_loss_near_zero_when_confident_right(self):
        scores = [1.0, 0.0]
        labels = [True, False]
        assert M.log_loss(scores, labels) == pytest.approx(0.0, abs=1e-12)

    def test_rejects_out_of_range_scores(self):
        with pytest.raises(ValueError):
            M.brier_score([1.5], [True])

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            M.brier_score([], [])

    def test_rejects_length_mismatch(self):
        with pytest.raises(ValueError):
            M.brier_score([0.5, 0.5], [True])


class TestReliabilityDiagram:
    def test_fixed_bin_count(self):
        bins = M.reliability_diagram([0.1, 0.9], [False, True], n_bins=10)
        assert len(bins) == 10

    def test_empty_bins_are_nan_zero(self):
        bins = M.reliability_diagram([0.05], [True], n_bins=10)
        # only the first bin is populated.
        assert bins[0].count == 1
        assert bins[0].mean_observed == pytest.approx(1.0)
        assert all(b.count == 0 for b in bins[1:])
        assert math.isnan(bins[5].mean_predicted)

    def test_score_one_lands_in_last_bin(self):
        bins = M.reliability_diagram([1.0], [True], n_bins=10)
        assert bins[-1].count == 1


class TestECEOffHeadline:
    def test_ece_computed(self):
        # perfectly calibrated -> ECE 0.
        scores = [0.0, 0.0, 1.0, 1.0]
        labels = [False, False, True, True]
        assert M.expected_calibration_error(scores, labels) == pytest.approx(0.0)

    def test_ece_absent_from_headline(self):
        rep = M.calibration_report([0.2, 0.8, 0.4, 0.6], [False, True, False, True])
        head = rep.headline
        # Headline keys: only n + brier + log_loss. No ece anywhere.
        assert set(head.keys()) == {"n", "brier", "log_loss"}
        assert "ece" not in head
        flat = str(head).lower()
        assert "ece" not in flat
        # ECE is still available off-headline as a diagnostic.
        assert isinstance(rep.ece, float)


class TestBlockBootstrapCI:
    def test_ci_brackets_point(self):
        scores = [0.6] * 20 + [0.4] * 20
        labels = [True] * 20 + [False] * 20
        ci = M.block_bootstrap_ci(M.brier_score, scores, labels)
        assert ci.lower <= ci.point <= ci.upper
        assert ci.level == 0.95

    def test_locked_defaults(self):
        assert M.BLOCK_SIZE == 5
        assert M.N_REPS == 1000
        assert M.CI_LEVEL == 0.95

    def test_seeded_reproducible(self):
        scores = [0.3, 0.7, 0.55, 0.45, 0.8, 0.2, 0.6, 0.4, 0.51, 0.49]
        labels = [False, True, True, False, True, False, True, False, True, False]
        ci_a = M.block_bootstrap_ci(M.brier_score, scores, labels, seed=12345)
        ci_b = M.block_bootstrap_ci(M.brier_score, scores, labels, seed=12345)
        assert ci_a == ci_b

    def test_seed_drives_resampling(self):
        # The bootstrap is seed-driven: the point estimate is seed-invariant, but
        # the resampled CI is a function of the seed. With a coarse n the
        # percentile endpoints across two seeds *can* coincide, so we assert the
        # seed genuinely steers resampling by showing not-all-seeds-equal across
        # a spread of seeds (and same-seed reproducibility is covered above).
        scores = [0.3, 0.7, 0.55, 0.45, 0.8, 0.2, 0.6, 0.4, 0.51, 0.49,
                  0.35, 0.65, 0.7, 0.3, 0.52, 0.48, 0.9, 0.1, 0.55, 0.45]
        labels = [bool(i % 2) for i in range(len(scores))]
        cis = [
            M.block_bootstrap_ci(M.brier_score, scores, labels, seed=s)
            for s in range(8)
        ]
        assert all(c.point == cis[0].point for c in cis)  # point seed-invariant
        bounds = {(c.lower, c.upper) for c in cis}
        assert len(bounds) > 1  # seed steers the resampled CI

    def test_small_sample_below_one_block(self):
        # n < block_size must not crash (block size clamps to n).
        ci = M.block_bootstrap_ci(M.brier_score, [0.5, 0.5, 0.5], [True, False, True])
        assert ci.lower <= ci.point <= ci.upper


class TestCalibrationReport:
    def test_report_records_bootstrap_provenance(self):
        rep = M.calibration_report(
            [0.2, 0.8, 0.4, 0.6, 0.55, 0.45], [False, True, False, True, True, False]
        )
        assert rep.n == 6
        assert rep.block_size == 5
        assert rep.n_reps == 1000
        assert rep.seed == M.DEFAULT_BOOTSTRAP_SEED
        assert rep.brier.lower <= rep.brier.point <= rep.brier.upper
        assert rep.log_loss.lower <= rep.log_loss.point <= rep.log_loss.upper

    def test_report_reproducible(self):
        args = ([0.2, 0.8, 0.4, 0.6], [False, True, False, True])
        a = M.calibration_report(*args)
        b = M.calibration_report(*args)
        assert a.headline == b.headline
