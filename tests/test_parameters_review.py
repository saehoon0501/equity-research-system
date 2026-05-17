"""Smoke tests for parameters_review.cli (v0.1 STUB).

Hermetic — no DB; only argument-parsing + the propose stub message are
covered. The DB-touching subcommands (summary / suggest) are validated
by integration tests once a v0.5+ harness wraps them.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def test_cli_module_imports() -> None:
    """The CLI module loads cleanly."""
    from parameters_review import cli  # noqa: F401


def test_cli_help_does_not_crash(capsys: pytest.CaptureFixture[str]) -> None:
    """`--help` exits 0 and prints something useful."""
    from parameters_review.cli import main

    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "parameters_review" in out.lower() or "STUB" in out


def test_propose_stub_emits_v05_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`propose` prints the expected stub JSON pointing to v0.5+ scope."""
    from parameters_review.cli import main

    rc = main(["propose"])
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["status"] == "stub"
    assert "v0.5+" in payload["message"]
    assert "Section 5.4" in payload["spec_ref"]


def test_no_subcommand_errors() -> None:
    """No subcommand → argparse exits with usage error."""
    from parameters_review.cli import main

    with pytest.raises(SystemExit) as exc:
        main([])
    # argparse exit code for missing required subparser is 2
    assert exc.value.code == 2
