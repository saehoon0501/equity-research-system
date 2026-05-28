"""Versioned, restart-surviving calibration buffer for the conformal wrapper (WS-3).

A self-contained calibration buffer. It holds (predicted_bin, true_label)
observations (or, more generally, the nonconformity inputs the scorer needs)
and persists them to disk as versioned JSON with an atomic write
(tmp file + ``os.replace``) so a partially-written file can never corrupt
state across a restart.

WS-4 (src/calibration/) owns the production calibration buffer/resolver and the
long-run coverage criterion. WS-3 deliberately keeps this buffer in-package so
the wrapper is self-contained until WS-4 lands; the persisted shape is
versioned so a future migration to the WS-4 store is explicit, not silent.

INV: the abstain-below-100 threshold (ABSTAIN_MIN_POINTS) is the single source
of truth for "insufficient calibration" and is consumed by ConformalWrapper.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# Locked decision: abstain wholesale below 100 calibration points.
ABSTAIN_MIN_POINTS = 100

# Bump on any incompatible change to the persisted JSON shape. Load rejects
# mismatches explicitly rather than silently degrading (see load()).
SCHEMA_VERSION = 1


@dataclass
class CalibrationBuffer:
    """In-memory + on-disk calibration buffer.

    Attributes:
        observations: ordered list of {"predicted": <label>, "label": <label>}
            dicts. Time-ordered (append-only); ordering is preserved on
            persist/load so a time-ordered replay is reproducible.
        alpha_target: the conformal miscoverage target (locked at 0.10 → 90%).
        current_alpha: the PID-adapted alpha (starts == alpha_target).
        pid_state: opaque serialisable PID controller state (integral / prev
            error), round-tripped verbatim through persist/load.
        path: optional persistence path. None => purely in-memory.
    """

    alpha_target: float = 0.10
    current_alpha: float = 0.10
    observations: list[dict[str, Any]] = field(default_factory=list)
    pid_state: dict[str, Any] = field(default_factory=dict)
    path: Optional[Path] = None

    # ---- size / readiness -------------------------------------------------

    def __len__(self) -> int:
        return len(self.observations)

    @property
    def is_ready(self) -> bool:
        """True iff there are enough points to leave abstain-wholesale mode."""
        return len(self.observations) >= ABSTAIN_MIN_POINTS

    # ---- mutation ---------------------------------------------------------

    def add(self, predicted: Any, label: Any) -> None:
        """Append one time-ordered (predicted, realised-label) observation."""
        self.observations.append({"predicted": predicted, "label": label})

    # ---- serialisation ----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "alpha_target": self.alpha_target,
            "current_alpha": self.current_alpha,
            "buffer": list(self.observations),
            "pid_state": dict(self.pid_state),
        }

    def persist(self, path: Optional[Path] = None) -> Path:
        """Atomically write the buffer to ``path`` (or self.path).

        Atomic = write to a temp file in the same directory, fsync, then
        ``os.replace`` over the target. A crash mid-write leaves either the
        old file or the temp file, never a half-written target.
        """
        target = Path(path) if path is not None else self.path
        if target is None:
            raise ValueError("no persistence path provided to persist()")
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.to_dict(), indent=2, sort_keys=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=str(target.parent), prefix=target.name + ".", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, target)
        except BaseException:
            # Best-effort cleanup of the temp file on any failure.
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass
            raise
        self.path = target
        return target

    @classmethod
    def load(cls, path: Path) -> "CalibrationBuffer":
        """Load a versioned buffer from disk.

        Raises ValueError on a schema_version mismatch — versioned state must
        fail loud, never silently degrade (locked decision: no silent skip).
        """
        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        ver = data.get("schema_version")
        if ver != SCHEMA_VERSION:
            raise ValueError(
                f"calibration buffer schema_version mismatch: file={ver!r} "
                f"expected={SCHEMA_VERSION!r} ({path})"
            )
        return cls(
            alpha_target=data.get("alpha_target", 0.10),
            current_alpha=data.get("current_alpha", data.get("alpha_target", 0.10)),
            observations=list(data.get("buffer", [])),
            pid_state=dict(data.get("pid_state", {})),
            path=path,
        )

    @classmethod
    def load_or_new(cls, path: Path, *, alpha_target: float = 0.10) -> "CalibrationBuffer":
        """Load if the file exists, else return a fresh empty buffer bound to path."""
        path = Path(path)
        if path.exists():
            return cls.load(path)
        return cls(alpha_target=alpha_target, current_alpha=alpha_target, path=path)


__all__ = ["ABSTAIN_MIN_POINTS", "SCHEMA_VERSION", "CalibrationBuffer"]
