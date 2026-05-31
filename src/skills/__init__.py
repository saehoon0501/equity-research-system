"""``src.skills`` — Claude Code skill-helper packages (P1).

Per CLAUDE.md P1, Python lives in two places only: MCP server implementations
and **skill helpers** (`src/skills/<command>/`, created when first needed).
`walkforward_tune` is the first resident (design §"Existing Architecture
Analysis": "the first resident of `src/skills/`").

This package marker is intentional: `src` itself is a namespace package (no
`src/__init__.py`), and adding this marker does NOT add one for `src`, so
`src.reactive` / `src.calibration` namespace resolution is unaffected.
"""
