"""Smoke tests for the conviction_rollup CLI wrapper (HIGH-1 closure gap).

The pure-Python ``roll_up_conviction`` function has 16 existing tests
(``test_conviction_flip_flop_walkthrough``, ``test_continuous_conviction``).
The CLI wrapper added in HIGH-1 — ``python3 -m src.p7_recommendation_emitter.
conviction_rollup --debate-add-count N ...`` — was test-uncovered. This
file covers the wrapper's actual failure surfaces: argparse, JSON envelope
shape, exit codes. The pm-supervisor §5 mandatory Bash invocation depends
on each of these being stable.

Tests use ``subprocess.run`` rather than calling ``_cli()`` in-process so
they exercise the same surface the synthesizer agent does (real shell-out
+ JSON parse + exit-code check).
"""

from __future__ import annotations

import json
import subprocess
import sys


def _run_cli(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "src.p7_recommendation_emitter.conviction_rollup", *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_cli_msft_inputs_returns_high_with_correct_json_shape():
    """Happy path: HIGH gate satisfied inputs should rollup to HIGH per the
    audit's HIGH-1 finding. Exit 0, JSON envelope has the documented keys."""
    result = _run_cli([
        "--debate-add-count", "4",
        "--kills-fired", "0",
        "--anchor-drift", "0",
    ])
    assert result.returncode == 0, f"CLI exit non-zero: stderr={result.stderr}"

    payload = json.loads(result.stdout)
    # JSON envelope shape contract — pm-supervisor §5 depends on these keys.
    assert "bucket" in payload
    assert "breakdown" in payload
    assert "triggered_rules" in payload
    assert payload["bucket"] == "HIGH"
    assert isinstance(payload["breakdown"], dict)
    assert isinstance(payload["triggered_rules"], list)
    assert len(payload["triggered_rules"]) >= 1


def test_cli_adversarial_inputs_returns_low():
    """LOW path: 2+ kills_fired + low debate trigger LOW.
    Confirms the CLI propagates the deterministic LOW gate verdict."""
    result = _run_cli([
        "--debate-add-count", "2",
        "--kills-fired", "3",
        "--anchor-drift", "2",
    ])
    assert result.returncode == 0, f"CLI exit non-zero: stderr={result.stderr}"

    payload = json.loads(result.stdout)
    assert payload["bucket"] == "LOW"
    # Multiple LOW triggers should appear in triggered_rules (kills + debate)
    assert len(payload["triggered_rules"]) >= 2


def test_cli_missing_required_arg_exits_non_zero():
    """argparse failure surface: missing required flag → non-zero exit + stderr
    message. Synthesizer must be able to detect this failure mechanically."""
    result = _run_cli([
        "--debate-add-count", "4",
        # missing --kills-fired
        "--anchor-drift", "0",
    ])
    assert result.returncode != 0
    assert result.stdout == "" or "bucket" not in result.stdout
    # argparse writes to stderr on missing required arg
    assert "kills-fired" in result.stderr.lower() or "required" in result.stderr.lower()


def test_cli_medium_default_path():
    """When no LOW trigger fires and HIGH gate is not fully satisfied,
    conviction is MEDIUM. Confirms the CLI propagates the fallback cleanly."""
    result = _run_cli([
        "--debate-add-count", "4",
        "--kills-fired", "0",
        "--anchor-drift", "2",  # fails anchor-drift gate (>1)
    ])
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    # HIGH criteria not fully met → MEDIUM
    assert payload["bucket"] == "MEDIUM"
