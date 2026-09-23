---
status: pending
priority: P3
filed: 2026-09-23
source: found closing todo 388 -- two files shared todo number 389 (one from this session's
  hygiene pass, one from the concurrent Phase 176 session filing 389-execute-short-horizon the
  same day) and nothing caught it until manual review
---

# Todo number uniqueness is not CI-enforced -- duplicate 389 slipped through `test_todo_priorities_link_integrity.py`

## What

`tests/unit/test_todo_priorities_link_integrity.py` (todo 305's guard) verifies that every
`[N](pending/...)` link in PRIORITIES.md resolves to an existing file, but does NOT verify that
todo numbers are unique across `pending/` (or that a link's display number matches its target
filename's number). Two failure modes observed 2026-09-23, both live:

1. **Duplicate numbers:** `389-backfill-status-error-msg-not-cleared-on-success.md` and
   `389-execute-short-horizon-ic-cell-deletion-prereg-post-176-08.md` coexisted in `pending/`
   for a day, filed independently by concurrent sessions. Fixed by renumbering the former to
   392; nothing would have flagged it otherwise.
2. **Mislabeled link text:** the renumbered todo's PRIORITIES.md row displayed `[391]` while
   linking `pending/389-...` (also colliding visually with the real 391) -- the integrity test
   passed because the target file existed.

Root cause both times: concurrent sessions pick the next number by `ls pending/` at file time
with no lock; the CI guard checks existence, not uniqueness or label-file agreement.

## Fix

Extend `test_todo_priorities_link_integrity.py` with two assertions:

1. No two files in `pending/` (and none against `completed/`+`deferred/` combined, since
   numbers must never be reused after closure either) share the same leading number.
2. Every `[N](pending/N-slug.md)` / `[N](completed/N-slug.md)` link's display `N` equals the
   target filename's number.

Both are cheap filesystem/parsing checks in the existing test's style; failure messages should
name the colliding pair. This is the same drift-class extension pattern as the guard's own
history (todo 305's original filing).

## Where

- `tests/unit/test_todo_priorities_link_integrity.py`
- Related: the guard's own origin (per CLAUDE.md: filed after the PRIORITIES drift class was
  caught by manual audit 5 times -- see the test file's docstring for its filing history),
  [392](392-backfill-status-error-msg-not-cleared-on-success.md) (renumbered from the
  duplicate 389), `feedback_todo_numbering_cleanup` memory
  ("continue pending sequence" rule -- this hardens it against concurrent sessions)
