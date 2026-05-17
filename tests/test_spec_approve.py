"""Smoke tests for spec_approve.cli (v0.1 minimal implementation).

Tests the attestation file write + HMAC stamping in a tmp directory.
Hermetic — no DB; no env-var leakage between tests.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def test_cli_module_imports() -> None:
    """The CLI module loads cleanly."""
    from spec_approve import cli  # noqa: F401


def test_writes_attestation_to_custom_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--out` writes to the specified path with the expected body fields."""
    from spec_approve.cli import main

    monkeypatch.setenv("AUDIT_HMAC_KEY", "test-key-not-secret")

    out = tmp_path / "v9.9-signoff-attestation.md"
    rc = main(
        [
            "9.9",
            "--operator", "smoke@test.local",
            "--spec-path", "docs/superpowers/specs/fake-9.9.md",
            "--scope-summary", "smoke test scope",
            "--out", str(out),
        ]
    )
    assert rc == 0
    body = out.read_text(encoding="utf-8")
    assert "v9.9 Spec Sign-off Attestation" in body
    assert "smoke@test.local" in body
    assert "smoke test scope" in body
    assert "## HMAC signature" in body
    # Signature is hex-encoded SHA256 (64 chars).
    sig_block_lines = [
        line.strip()
        for line in body.splitlines()
        if len(line.strip()) == 64 and all(c in "0123456789abcdef" for c in line.strip())
    ]
    assert sig_block_lines, "expected a hex sha256 signature in body"


def test_refuses_to_overwrite_without_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Existing attestation file → exit 3 unless --force."""
    from spec_approve.cli import main

    monkeypatch.setenv("AUDIT_HMAC_KEY", "test-key-not-secret")
    out = tmp_path / "v9.9-signoff-attestation.md"
    out.write_text("pre-existing", encoding="utf-8")

    rc = main(["9.9", "--out", str(out)])
    assert rc == 3
    assert out.read_text(encoding="utf-8") == "pre-existing"

    rc = main(["9.9", "--out", str(out), "--force"])
    assert rc == 0
    assert "Sign-off Attestation" in out.read_text(encoding="utf-8")
