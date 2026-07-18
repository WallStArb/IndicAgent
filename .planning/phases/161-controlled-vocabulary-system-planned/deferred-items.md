# Deferred Items — Phase 161

Out-of-scope discoveries logged during plan execution, per the executor's scope-boundary
rule (only auto-fix issues directly caused by the current task's changes).

## 161-03: Duplicate migration number 239 on main

**Found during:** Task 1 (APR key migration), while confirming 239 was still free.

**Issue:** `production/migrations/` on `main` now has two distinct files both numbered 239:
- `239_controlled_vocabulary_schema.sql` (this phase's own 161-01 plan)
- `239_ic_engine_cross_sectional_bootstrap_threads.sql` (an unrelated, concurrently-landed
  migration)

Both applied cleanly (migration numbers are filenames only, not enforced-unique by any
runner in this codebase), but the collision is a latent footgun — a future migration
picking "239" as the next free number by `ls`-eyeballing would silently shadow one of
these two files' intent in code review, even though both already ran.

**Not fixed:** Neither file is in this plan's `files_modified` list, and renumbering an
already-applied migration file post-hoc is itself a footgun (breaks any tooling that
tracks "already ran" by filename). Out of scope for 161-03 — flagging for whoever next
touches migration numbering/tooling to decide whether a pre-commit check for duplicate
migration numbers is worth adding.

**Files:** `production/migrations/239_controlled_vocabulary_schema.sql`,
`production/migrations/239_ic_engine_cross_sectional_bootstrap_threads.sql`
