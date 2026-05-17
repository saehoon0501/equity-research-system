---
description: DEPRECATED under BUILD_LOG.md decision 5. Weekly BUILD_LOG cadence has been removed. BUILD_LOG.md is now a step list maintained by direct edits, not a weekly journal.
argument-hint: (deprecated — no arguments)
---

# /weekly-buildlog (DEPRECATED)

**This command is deprecated as of BUILD_LOG.md decision 5 (step-driven, no timeline).**

The premise of this command — "end of every week, BUILD_LOG entry written before the week closes" — assumed a dated weekly cadence that decision 5 removed. There is no longer a "week N" in the operator's protocol; BUILD_LOG.md is now an ordered step list, not a journal.

## What replaces this command

- **To mark a step done:** edit `BUILD_LOG.md` directly. Change `- [ ]` to `- [x]` on the relevant step.
- **To capture a notable decision:** append to the `## Notes` section of `BUILD_LOG.md`.
- **To capture cost spent:** update the `## Cost` section in `BUILD_LOG.md`.
- **To produce a checkpoint artifact:** run `/checkpoint <1|2|3>` when the gating step boundary's criteria are demonstrably complete (no longer date-triggered).

## Why this isn't fully deleted

Kept as a stub so historical references don't break (e.g., `/run` may still mention this command in older docs being read; the deprecation notice is more useful than a missing-file error). If a step-progress-update slash command becomes useful later, this file is the natural place to put it.

## Reversal path

If decision 5 is reversed (dated cadence restored as a new architectural decision), restore this command from git history (`git log -- .claude/commands/weekly-buildlog.md`).
