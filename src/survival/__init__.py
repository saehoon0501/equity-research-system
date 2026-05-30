"""survival — the account-aware deterministic Survival Gate (inner-ring leaf).

The Survival Gate is the mandatory, account-aware, deterministic hard-rule gate
at the top of the reactive CFD layer's lexicographic value chain
(Survive ⊳ Preserve ⊳ Edge ⊳ Return). It is the highest-blast-radius node in
the repo and must be proven green on the inner ring (P14) before any live
cutover.

Module layout (strict left→right dependency direction):

  * ``types``  — input/output dataclasses + fixed-vocabulary ``Literal`` aliases
                 (this module; imports nothing from ``params``/``gate``).
  * ``params`` — pinned ``SurvivalParameters`` + tighten-only resolver (task 1.2).
  * ``gate``   — ``admit`` veto + ``assess`` monitor + ``check_capitalization``
                 + the shared lexicographic check library (later tasks).

Pure stdlib only — no LLM / MCP / DB imports (P14, R11.2). The core performs no
I/O; the caller persists what it emits.
"""

from __future__ import annotations
