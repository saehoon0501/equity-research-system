"""On-disk LLM response-replay cache (P0-5).

The cache is a small JSON-backed key/value store. Keys are the canonical
5-tuple ``(model_version, prompt_sha, temperature, max_tokens,
sample_index)`` serialised to a stable hex digest; values are the raw
assistant *text* response (the call-sites parse JSON themselves, so we
cache the unparsed string — this keeps the cache representation identical
for both call-sites).

Modes
-----
* ``record``  — on a miss, compute the value (via the wrapped caller),
  store it, and return it.
* ``replay``  — on a miss, raise :class:`CacheMissError`. Hits are served
  from disk. This is the CI mode: a missing cassette fails the run.

The default (no env flag) is *disabled* — the wrappers never construct a
cache and call straight through to the underlying client.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Default location for the on-disk cassette store. Overridable via env so
# CI can point at a checked-in fixtures directory.
DEFAULT_CACHE_DIR = "tests/fixtures/llm_cassettes"


class CacheMissError(RuntimeError):
    """Raised in replay mode when a key is absent from the cache."""


def prompt_sha(system: str, user: str) -> str:
    """Stable SHA-256 over the (system, user) prompt pair.

    We hash a length-prefixed concatenation so that moving text between the
    system and user fields cannot collide.
    """
    h = hashlib.sha256()
    sys_b = (system or "").encode("utf-8")
    usr_b = (user or "").encode("utf-8")
    h.update(str(len(sys_b)).encode("ascii"))
    h.update(b"\x00")
    h.update(sys_b)
    h.update(b"\x00")
    h.update(str(len(usr_b)).encode("ascii"))
    h.update(b"\x00")
    h.update(usr_b)
    return h.hexdigest()


@dataclass(frozen=True)
class CacheKey:
    """The canonical 5-dimension cache key.

    ``sample_index`` is REQUIRED (not optional) so that N self-consistency
    samples at the same temperature each occupy a distinct slot. Two calls
    that differ ONLY in ``sample_index`` MUST produce different digests.
    """

    model_version: str
    prompt_sha: str
    temperature: float
    max_tokens: int
    sample_index: int

    def digest(self) -> str:
        # Canonical, order-stable serialisation. We normalise the float so
        # 0.7 and 0.70 collapse to the same key, but distinct sample_index
        # values never do.
        payload = json.dumps(
            {
                "model_version": self.model_version,
                "prompt_sha": self.prompt_sha,
                "temperature": float(self.temperature),
                "max_tokens": int(self.max_tokens),
                "sample_index": int(self.sample_index),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def make_cache_key(
    *,
    model_version: str,
    system: str,
    user: str,
    temperature: float,
    max_tokens: int,
    sample_index: int,
) -> CacheKey:
    """Build a :class:`CacheKey` from raw prompt parts (hashes the prompt)."""
    return CacheKey(
        model_version=model_version,
        prompt_sha=prompt_sha(system, user),
        temperature=temperature,
        max_tokens=max_tokens,
        sample_index=sample_index,
    )


class LLMCache:
    """JSON-file-backed replay cache.

    Thread-safe for the modest concurrency the scorers use (a process-local
    lock around the in-memory dict + atomic file rewrite).
    """

    def __init__(self, cache_dir: str | Path, mode: str = "record") -> None:
        if mode not in ("record", "replay"):
            raise ValueError(f"mode must be 'record' or 'replay', got {mode!r}")
        self.mode = mode
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._path = self.cache_dir / "cassettes.json"
        self._lock = threading.Lock()
        self._store: dict[str, str] = {}
        if self._path.is_file():
            try:
                self._store = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                # Corrupt/empty cassette file → start empty rather than crash.
                self._store = {}

    # -- low-level get/put ------------------------------------------------
    def get(self, key: CacheKey) -> Optional[str]:
        with self._lock:
            return self._store.get(key.digest())

    def put(self, key: CacheKey, value: str) -> None:
        with self._lock:
            self._store[key.digest()] = value
            self._flush_locked()

    def __contains__(self, key: CacheKey) -> bool:
        with self._lock:
            return key.digest() in self._store

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)

    def _flush_locked(self) -> None:
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(self._store, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self._path)

    # -- the record/replay seam ------------------------------------------
    def get_or_compute(self, key: CacheKey, compute) -> str:
        """Return the cached value, or compute+store it (record mode).

        In ``replay`` mode a miss raises :class:`CacheMissError` — the
        ``compute`` callable is never invoked. This is what makes a missing
        cassette fail the CI run.
        """
        hit = self.get(key)
        if hit is not None:
            return hit
        if self.mode == "replay":
            raise CacheMissError(
                f"LLM cache miss in replay mode for key digest "
                f"{key.digest()} (model={key.model_version}, "
                f"temp={key.temperature}, max_tokens={key.max_tokens}, "
                f"sample_index={key.sample_index}). A cassette is required "
                f"for every gating/scoring call in CI."
            )
        value = compute()
        self.put(key, value)
        return value


def cache_from_env(env: Optional[dict] = None) -> Optional[LLMCache]:
    """Construct an :class:`LLMCache` from environment flags, or ``None``.

    Returns ``None`` (the default) unless ``LLM_CACHE_ENABLED`` is truthy,
    keeping the wrappers as pure pass-throughs at normal runtime.

    Env vars:
      * ``LLM_CACHE_ENABLED``  — ``1/true/yes/on`` to enable.
      * ``LLM_CACHE_MODE``     — ``record`` (default) or ``replay``.
      * ``LLM_CACHE_DIR``      — cassette directory (default
        :data:`DEFAULT_CACHE_DIR`).
    """
    env = os.environ if env is None else env
    flag = str(env.get("LLM_CACHE_ENABLED", "")).strip().lower()
    if flag not in ("1", "true", "yes", "on"):
        return None
    mode = str(env.get("LLM_CACHE_MODE", "record")).strip().lower() or "record"
    cache_dir = env.get("LLM_CACHE_DIR", DEFAULT_CACHE_DIR)
    return LLMCache(cache_dir=cache_dir, mode=mode)
