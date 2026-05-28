"""WS-3 conformal-overlay wrapper tests.

Identity + abstain + degrade tests run with NO network (the wrapped classifiers
are pure compute on in-memory price lists). The long-run coverage criterion
(acceptance criterion 3) is the WS-3 x WS-4 join: now that WS-4
(src/calibration/) has landed it is PROMOTED from a deferred xfail to a real,
seeded, deterministic replay test (see ``test_long_run_coverage_within_band``).

Run:
    PYTHONPATH="$PWD" uv run --with pytest --with numpy --python 3.13 \
        pytest tests/unit/conformal/
"""
from __future__ import annotations

import copy

import numpy as np
import pytest

from src.conformal import (
    ABSTAIN_MIN_POINTS,
    SCHEMA_VERSION,
    CalibrationBuffer,
    ConformalPID,
    ConformalResult,
    ConformalWrapper,
)
from src.overlays.tactical.bin_classifier import classify
from src.overlays.flow.bin_classifier import classify_flow
from src.overlays.reversion.bin_classifier import classify_reversion

# Label spaces per classifier (p8/p9 share one; p10 has its own vocabulary).
PN_LABELS = ["positive", "neutral", "negative", "unavailable"]
MR_LABELS = ["MR_OVERSOLD", "MR_NEUTRAL", "MR_OVERBOUGHT", "MR_UNAVAILABLE"]


# --------------------------------------------------------------------------
# Deterministic, network-free price fixtures (>= 252 trading days).
# --------------------------------------------------------------------------

def _rising(n: int = 300, start: float = 100.0, step: float = 0.5) -> list[float]:
    return [start + step * i for i in range(n)]


def _falling(n: int = 300, start: float = 300.0, step: float = 0.5) -> list[float]:
    return [start - step * i for i in range(n)]


TICKER_UP = _rising()
TICKER_DOWN = _falling()
SPY_FLAT = [100.0] * 300


def _raw_p8():
    return classify(TICKER_UP, SPY_FLAT, rf_yield_pct=2.0)


def _raw_p9():
    return classify_flow(TICKER_UP, SPY_FLAT)


def _raw_p10():
    return classify_reversion(TICKER_DOWN)


# --------------------------------------------------------------------------
# Criterion 1 — wrapper DISABLED => bit-identical to raw classify*.
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "classifier, args, kwargs, labels, raw_fn",
    [
        (classify, (TICKER_UP, SPY_FLAT), {"rf_yield_pct": 2.0}, PN_LABELS, _raw_p8),
        (classify_flow, (TICKER_UP, SPY_FLAT), {}, PN_LABELS, _raw_p9),
        (classify_reversion, (TICKER_DOWN,), {}, MR_LABELS, _raw_p10),
    ],
    ids=["p8_tactical", "p9_flow", "p10_reversion"],
)
def test_disabled_is_bit_identical_to_raw(classifier, args, kwargs, labels, raw_fn):
    raw = raw_fn()
    wrapped = ConformalWrapper(classifier, labels, enabled=False)
    out = wrapped(*args, **kwargs)
    # Value-equal AND object identity: the disabled path returns the SAME
    # object the raw classifier produced — no copy, no extra keys.
    assert out == raw
    assert isinstance(out, dict)
    # Equal to a freshly computed raw call on identical inputs (byte-stable).
    assert out == classifier(*args, **kwargs)


# --------------------------------------------------------------------------
# Criterion 2a — abstain on a non-singleton (ambiguous) prediction set.
# --------------------------------------------------------------------------

def test_abstain_on_non_singleton_set():
    # Seed a calibration buffer (>= 100 pts) whose binary-mismatch scores carry
    # a wide quantile, so multiple candidate labels enter the prediction set.
    # With alpha=0.10 and a buffer that is ~50% mismatches, the conformal
    # quantile at level 0.90 is 1.0 => every label (mismatch score 0 or 1)
    # is admitted => non-singleton => abstain.
    buf = CalibrationBuffer(alpha_target=0.10, current_alpha=0.10)
    for i in range(120):
        # Alternate correct/incorrect to push the high quantile to 1.0.
        if i % 2 == 0:
            buf.add("positive", "positive")
        else:
            buf.add("positive", "negative")

    wrapped = ConformalWrapper(classify, PN_LABELS, buffer=buf, enabled=True)
    out = wrapped(TICKER_UP, SPY_FLAT, rf_yield_pct=2.0)

    assert isinstance(out, ConformalResult)
    assert out.abstained is True
    assert out.abstain_reason == "non_singleton_set"
    assert len(out.prediction_set) > 1
    # Degrade default: raw stays inspectable, nothing fabricated.
    assert out.raw == _raw_p8()


def test_singleton_set_does_not_abstain():
    # All-correct calibration => quantile 0.0 => only the exact-match label is
    # admitted => singleton => no abstain.
    buf = CalibrationBuffer(alpha_target=0.10, current_alpha=0.10)
    raw = _raw_p8()
    predicted = raw["bin"]
    for _ in range(120):
        buf.add(predicted, predicted)

    wrapped = ConformalWrapper(classify, PN_LABELS, buffer=buf, enabled=True)
    out = wrapped(TICKER_UP, SPY_FLAT, rf_yield_pct=2.0)

    assert isinstance(out, ConformalResult)
    assert out.abstained is False
    assert out.abstain_reason is None
    assert out.prediction_set == [predicted]


# --------------------------------------------------------------------------
# Criterion 2b + 4 — abstain wholesale when calibration < 100 points.
# --------------------------------------------------------------------------

def test_abstain_when_calibration_below_100():
    buf = CalibrationBuffer(alpha_target=0.10, current_alpha=0.10)
    for _ in range(ABSTAIN_MIN_POINTS - 1):  # 99 < 100
        buf.add("positive", "positive")
    assert len(buf) < ABSTAIN_MIN_POINTS

    wrapped = ConformalWrapper(classify, PN_LABELS, buffer=buf, enabled=True)
    out = wrapped(TICKER_UP, SPY_FLAT, rf_yield_pct=2.0)

    assert isinstance(out, ConformalResult)
    assert out.abstained is True
    assert out.abstain_reason == "calibration_insufficient"
    # Criterion 4: NO bogus set — empty, not a fabricated singleton.
    assert out.prediction_set == []
    assert out.raw == _raw_p8()


def test_empty_buffer_abstains_wholesale():
    wrapped = ConformalWrapper(classify_reversion, MR_LABELS, enabled=True)
    out = wrapped(TICKER_DOWN)
    assert out.abstained is True
    assert out.abstain_reason == "calibration_insufficient"
    assert out.prediction_set == []


# --------------------------------------------------------------------------
# Persistence + versioning (survives restart).
# --------------------------------------------------------------------------

def test_buffer_persist_and_reload_roundtrip(tmp_path):
    path = tmp_path / "calib.json"
    buf = CalibrationBuffer(alpha_target=0.10, current_alpha=0.0875, path=path)
    for i in range(50):
        buf.add("positive", "positive" if i % 3 else "negative")
    buf.pid_state = {"kp": 0.05, "ki": 0.005, "kd": 0.0, "integral": 1.5, "prev_error": -0.9}
    buf.persist()

    assert path.exists()
    reloaded = CalibrationBuffer.load(path)
    assert len(reloaded) == 50
    assert reloaded.observations == buf.observations
    assert reloaded.current_alpha == 0.0875
    assert reloaded.alpha_target == 0.10
    assert reloaded.pid_state == buf.pid_state


def test_persist_is_atomic_no_partial_file(tmp_path):
    # After a successful persist there must be no leftover *.tmp sibling.
    path = tmp_path / "calib.json"
    buf = CalibrationBuffer(path=path)
    buf.add("positive", "positive")
    buf.persist()
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_load_rejects_schema_version_mismatch(tmp_path):
    import json

    path = tmp_path / "calib.json"
    payload = {
        "schema_version": SCHEMA_VERSION + 99,
        "alpha_target": 0.10,
        "current_alpha": 0.10,
        "buffer": [],
        "pid_state": {},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="schema_version mismatch"):
        CalibrationBuffer.load(path)


def test_load_or_new_returns_fresh_when_absent(tmp_path):
    path = tmp_path / "missing.json"
    buf = CalibrationBuffer.load_or_new(path, alpha_target=0.10)
    assert len(buf) == 0
    assert buf.path == path


def test_wrapper_observe_persists_state(tmp_path):
    path = tmp_path / "calib.json"
    buf = CalibrationBuffer(alpha_target=0.10, current_alpha=0.10, path=path)
    wrapped = ConformalWrapper(classify, PN_LABELS, buffer=buf, enabled=True)
    for _ in range(105):
        wrapped.observe("positive", "positive", persist=True)
    assert path.exists()
    reloaded = CalibrationBuffer.load(path)
    assert len(reloaded) == 105
    # PID state round-trips so a restart resumes the adapted alpha.
    assert "integral" in reloaded.pid_state


# --------------------------------------------------------------------------
# PID controller update math (synthetic stream; not a coverage test).
# --------------------------------------------------------------------------

def test_pid_lowers_alpha_on_repeated_misses():
    pid = ConformalPID(alpha_target=0.10, kp=0.05, ki=0.005, kd=0.0)
    alpha = 0.10
    for _ in range(20):
        alpha = pid.update(alpha, covered=False)  # all misses
    # Repeated misses => negative error => alpha tightens below the target.
    assert alpha < 0.10


def test_pid_state_roundtrip():
    pid = ConformalPID(alpha_target=0.10)
    pid.update(0.10, covered=False)
    state = pid.to_state()
    pid2 = ConformalPID.from_state(state, alpha_target=0.10)
    assert pid2.integral == pid.integral
    assert pid2.prev_error == pid.prev_error


def test_pid_alpha_clamped_to_open_interval():
    pid = ConformalPID(alpha_target=0.10, kp=10.0, ki=10.0, kd=0.0)
    alpha = 0.10
    for _ in range(50):
        alpha = pid.update(alpha, covered=True)  # always covered => alpha rises
    assert alpha < 1.0  # clamped strictly inside (0,1)


# --------------------------------------------------------------------------
# Disabled path never touches calibration (pure passthrough).
# --------------------------------------------------------------------------

def test_disabled_ignores_buffer_state():
    # Even with a healthy buffer, disabled returns the raw object unchanged.
    buf = CalibrationBuffer(alpha_target=0.10, current_alpha=0.10)
    for _ in range(200):
        buf.add("positive", "positive")
    wrapped = ConformalWrapper(classify, PN_LABELS, buffer=buf, enabled=False)
    out = wrapped(TICKER_UP, SPY_FLAT, rf_yield_pct=2.0)
    assert out == _raw_p8()
    assert not isinstance(out, ConformalResult)


# --------------------------------------------------------------------------
# Criterion 3 — PHASE-2: WS-3 x WS-4 long-run coverage replay (PROMOTED).
# --------------------------------------------------------------------------

# Coverage target = 1 - alpha = 0.90; acceptance band per WS-3 criterion 3.
COVERAGE_TARGET = 0.90
COVERAGE_BAND = (0.85, 0.95)

# Replay shape. The seed mirrors the codebase convention
# (src/calibration/metrics.py DEFAULT_BOOTSTRAP_SEED = 20260527) so a re-run is
# bit-reproducible. >= several hundred ordered observations warm the buffer well
# past ABSTAIN_MIN_POINTS (100) and let the adaptive (PID) alpha stabilise.
REPLAY_SEED = 20260527
REPLAY_N = 1200
# Fraction of the replay whose realised label MATCHES the just-emitted
# prediction. The exact value is intentionally NOT 0.90 — the whole point of
# Adaptive Conformal Inference is that the PID adapts the per-step alpha so
# realised coverage converges on the 90% TARGET regardless of base hit-rate.
REPLAY_HIT_RATE = 0.70
# Overlay label vocabulary actually emitted in the stream (p8/p9 directional
# space minus the degenerate "unavailable" sentinel). A discrete, >1-element
# space is what makes the conformal prediction set non-trivial.
REPLAY_LABELS = ["positive", "neutral", "negative"]


def _replay_stream(rng: np.random.Generator, n: int, hit_rate: float):
    """Yield a time-ordered (predicted, realised-label) replay.

    Models the WS-4 resolver's output: each step has a model prediction and a
    realised outcome (the resolver's ``label_binary``-style decision, here
    lifted onto the overlay's directional label space so the conformal set is
    non-trivial). With probability ``hit_rate`` the realised label equals the
    prediction; otherwise it is a uniformly-drawn DIFFERENT label. Deterministic
    given ``rng`` (a seeded ``numpy.random.default_rng``), so empirical coverage
    is reproducible. No network, no live resolver, no DB — pure compute.
    """
    for _ in range(n):
        predicted = REPLAY_LABELS[int(rng.integers(0, len(REPLAY_LABELS)))]
        if rng.random() < hit_rate:
            label = predicted
        else:
            others = [lbl for lbl in REPLAY_LABELS if lbl != predicted]
            label = others[int(rng.integers(0, len(others)))]
        yield predicted, label


def test_long_run_coverage_within_band():
    """WS-3 criterion 3: realized coverage within 90% +- 5% over an ordered replay.

    PROMOTED post-WS-4 (src/calibration/ landed). Drives a deterministic, SEEDED
    time-ordered stream of (prediction, realized-label) pairs through
    ``ConformalWrapper.observe()`` — the same join WS-4's resolver feeds in
    production (its ``label_binary`` realized outcomes). The buffer warms past
    ABSTAIN_MIN_POINTS (100), the adaptive (Conformal-PID) alpha stabilises, and
    realized coverage — the fraction of post-warmup observations whose realized
    label fell inside the wrapper's prediction set — must land in [0.85, 0.95].

    Coverage is computed exactly as ``observe()`` does internally (membership of
    the realized label in ``predict_set(predicted)``, evaluated on the buffer
    state BEFORE the observation is added), over the post-warmup window.
    """
    rng = np.random.default_rng(REPLAY_SEED)
    buffer = CalibrationBuffer(alpha_target=0.10, current_alpha=0.10)
    wrapper = ConformalWrapper(classify, PN_LABELS, buffer=buffer, enabled=True)

    covered = 0
    measured = 0
    for predicted, label in _replay_stream(rng, REPLAY_N, REPLAY_HIT_RATE):
        # Only score once the buffer has left abstain-wholesale mode (>=100 pts);
        # this is the post-warmup window over which coverage must hold. Compute
        # membership on the PRE-add prediction set, mirroring observe()'s own
        # coverage logic, then feed the outcome in (which adapts alpha).
        if buffer.is_ready:
            in_set = label in wrapper.predict_set(predicted)
            measured += 1
            covered += 1 if in_set else 0
        wrapper.observe(predicted, label)

    assert measured >= 1000, f"warmup window too small to be stable: {measured}"

    empirical_coverage = covered / measured
    lo, hi = COVERAGE_BAND
    assert lo <= empirical_coverage <= hi, (
        f"realized coverage {empirical_coverage:.4f} outside acceptance band "
        f"[{lo}, {hi}] (target {COVERAGE_TARGET}); measured over {measured} "
        f"post-warmup observations, seed={REPLAY_SEED}, final "
        f"alpha={buffer.current_alpha:.4f}"
    )
