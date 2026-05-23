"""Smoke tests for launch_confirm.cli (v0.1 minimal implementation).

Hermetic — writes to tmp_path; no DB; no shared-log mutation.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[3] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def test_cli_module_imports() -> None:
    """The CLI module loads cleanly."""
    from launch_confirm import cli  # noqa: F401


def test_appends_row_with_header_init(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """First invocation writes the header + one row; second appends."""
    from launch_confirm.cli import main

    monkeypatch.setenv("AUDIT_HMAC_KEY", "test-key")
    log = tmp_path / "launch-readiness-log.md"

    rc = main(
        [
            "hard_gates_green",
            "--operator", "smoke@test.local",
            "--note", "first attestation",
            "--log-path", str(log),
        ]
    )
    assert rc == 0
    body = log.read_text(encoding="utf-8")
    assert "# Launch Readiness Log" in body
    assert "hard_gates_green" in body
    assert "smoke@test.local" in body

    rc = main(
        [
            "walkthrough_demo",
            "--operator", "smoke@test.local",
            "--log-path", str(log),
        ]
    )
    assert rc == 0
    body = log.read_text(encoding="utf-8")
    # Header still present once.
    assert body.count("# Launch Readiness Log") == 1
    assert "walkthrough_demo" in body
    assert "hard_gates_green" in body


def test_unkeyed_does_not_block_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Missing AUDIT_HMAC_KEY → warn-and-proceed; row still appended."""
    from launch_confirm.cli import main

    monkeypatch.delenv("AUDIT_HMAC_KEY", raising=False)
    log = tmp_path / "launch-readiness-log.md"

    rc = main(["unkeyed_gate", "--log-path", str(log)])
    assert rc == 0
    err = capsys.readouterr().err
    assert "AUDIT_HMAC_KEY" in err
    assert "unkeyed_gate" in log.read_text(encoding="utf-8")


def test_pipe_in_note_is_escaped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `|` character in note must not break the Markdown table row."""
    from launch_confirm.cli import main

    monkeypatch.setenv("AUDIT_HMAC_KEY", "test-key")
    log = tmp_path / "launch-readiness-log.md"

    rc = main(
        [
            "pipe_test",
            "--note", "a | b | c",
            "--log-path", str(log),
        ]
    )
    assert rc == 0
    body = log.read_text(encoding="utf-8")
    assert "a \\| b \\| c" in body
