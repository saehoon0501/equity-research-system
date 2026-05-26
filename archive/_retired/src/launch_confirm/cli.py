"""CLI for /launch-confirm — operator HMAC-attested sign-off on a launch gate.

Usage::

    python -m src.launch_confirm.cli <gate_name> [--operator <id>] \\
        [--note <text>] [--log-path <path>]

Per v3 Section 5.4 + Section 7.3. Appends a sign-off row to the
append-only `docs/superpowers/launch-readiness-log.md` file. Each row is
HMAC-signed (canonical payload + `AUDIT_HMAC_KEY`) for tamper-evidence.

Exit codes:
    0 - success
    1 - IO error (write failure)
    2 - usage error
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys
from pathlib import Path
from typing import Sequence

from src.audit_trail.hmac_verify import compute_signature_dict


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_LOG = _REPO_ROOT / "docs" / "superpowers" / "launch-readiness-log.md"

_LOG_HEADER = """# Launch Readiness Log

Append-only operator-attestation log for v0.1 launch gates per v3 spec
Section 7.3. Each row is HMAC-signed with `AUDIT_HMAC_KEY` against a
canonical payload of `(gate_name, timestamp, operator, note)` using
the contract from `src/audit_trail/hmac_verify.py`.

| Timestamp (UTC) | Gate | Operator | Note | HMAC (truncated) |
|---|---|---|---|---|
"""


def _ensure_log(path: Path) -> None:
    """Create the log file with header if missing."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_LOG_HEADER, encoding="utf-8")


def _truncate(sig: str, n: int = 12) -> str:
    return f"{sig[:n]}...{sig[-4:]}" if len(sig) > n + 4 else sig


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m src.launch_confirm.cli",
        description=(
            "Operator HMAC-attested sign-off on a launch gate. "
            "Per v3 Section 5.4 + Section 7.3."
        ),
    )
    p.add_argument(
        "gate_name",
        help=(
            "Gate identifier (e.g. 'hard_gates_green', "
            "'walkthrough_PLTR_2022', 'calibration_kappa')."
        ),
    )
    p.add_argument(
        "--operator",
        default=os.environ.get("OPERATOR_ID", "saehoon0501"),
        help="Operator identifier. Defaults to $OPERATOR_ID env var "
        "or 'saehoon0501'.",
    )
    p.add_argument(
        "--note",
        default="",
        help="Optional one-line attestation note.",
    )
    p.add_argument(
        "--log-path",
        default=str(_DEFAULT_LOG),
        help="Override the log file path. Defaults to "
        "docs/superpowers/launch-readiness-log.md.",
    )
    args = p.parse_args(argv)

    timestamp = _dt.datetime.now(_dt.timezone.utc).isoformat()
    payload = {
        "gate_name": args.gate_name,
        "timestamp": timestamp,
        "operator": args.operator,
        "note": args.note,
    }
    hmac_key = os.environ.get("AUDIT_HMAC_KEY", "")
    if not hmac_key:
        print(
            "WARN: AUDIT_HMAC_KEY env var not set; sign-off row will "
            "be signed with empty key (verifier will flag).",
            file=sys.stderr,
        )
    signature = compute_signature_dict(
        payload, hmac_key.encode("utf-8") if hmac_key else b""
    )

    log_path = Path(args.log_path)
    try:
        _ensure_log(log_path)
        # Markdown table cells must escape pipes.
        safe_note = args.note.replace("|", "\\|")
        row = (
            f"| {timestamp} | `{args.gate_name}` | {args.operator} | "
            f"{safe_note} | `{_truncate(signature)}` |\n"
        )
        with log_path.open("a", encoding="utf-8") as f:
            f.write(row)
    except OSError as e:
        print(f"ERROR: failed to append to {log_path}: {e}", file=sys.stderr)
        return 1
    try:
        rendered_path: str = str(log_path.relative_to(_REPO_ROOT))
    except ValueError:
        # Log path is outside repo root (e.g. operator override or test
        # tmp dir). Show the absolute path instead.
        rendered_path = str(log_path)
    print(f"Appended gate '{args.gate_name}' to {rendered_path}")
    print(f"HMAC: {signature}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
