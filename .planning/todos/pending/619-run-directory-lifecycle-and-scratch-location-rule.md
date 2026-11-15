---
status: pending
priority: P3
filed: 2026-11-15
amended: 2026-11-15
source: owner request 2026-11-15 ("clean like Renaissance requires"), after a manual sweep freed about 25 MB and found the rest protected
---

# Run-directory lifecycle and scratch location rule (no GC leaf)

## What

Measured 2026-11-15 (read-only dry run of the proposed GC rules): rotated logs 5.6 MB (0 MB over 7 days), `data/scratch` 5.1 MB (4.5 MB over 7 days), `.mypy_cache` 34 MB, against 2,175 MB in named run directories under `logs/` (`phase179`, `phase181`, `massive_step7*`), all of them protected evidence. Ordinary clutter is about 10 MB, far under the 100 MB a month exit threshold, so the scheduled GC leaf in the first draft is deleted (Musk step 1: the requirement does not hold). The volume that matters is run directories with no end of life, and that needs a convention, not a deleter.

## Scope

1. Scratch location rule in `docs/reference/gotchas.md`: scratch for a todo lives only under `data/scratch/<todo-id>`; nothing under `cache/`, `.planning/tmp` or `/tmp`; the closing commit of the todo deletes its scratch dir.
2. Run-directory lifecycle rule in the same section: a named run dir under `logs/` carries a one-line owner and end-of-life trigger in its README (the todo or step that closes it); at close, write the summary card, keep only the sha256 files and the evidence the card cites, delete the rest. Run dirs that a script reads (`repro_frozen` reads `logs/phase179/rerun_e14` and `logs/phase181`) say so in that README.
3. The two concrete collapses are separate todos: 620 (shrink the `phase181` snapshot) and 621 (collapse `logs/massive_step7` after Part F).
4. Reopen the GC leaf only if a later measurement shows removable clutter over 100 MB a month.

## Gates

- Docs only: `tests/unit/test_todo_priorities_link_integrity.py` and the glossary check pass.

## Boundaries

Never deletes tracked files, raw data, backups or anything under `data/massive`. Tracked-file cleanup stays with the repo-simplify lane.
