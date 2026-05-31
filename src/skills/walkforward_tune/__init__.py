"""``walkforward_tune`` — the pure leaf-helper package for the
walkforward-tuning-loop slash command (P1).

The markdown orchestrator (`.claude/commands/walkforward-tune.md`) holds all
control flow; these leaves perform computation and bounded I/O and communicate
ONLY through the `types` dataclasses (the dependency-root barrier). Strict
left→right dependency: `types → {read, fit, cpcv, metric, gate, publish,
audit}`; no leaf imports another leaf; nothing imports a consumer spec
(design §"File Structure Plan → Dependency direction").
"""
