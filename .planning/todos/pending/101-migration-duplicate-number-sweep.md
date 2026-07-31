---
status: pending
priority: P2
filed: 2026-07-12
source: todo 095 resolution — discovered while fixing the db/migrations/ vs production/migrations/ split
---

**Narrowed 2026-07-31** — pre-flight duplicate-number check added
(`tests/unit/test_migration_number_uniqueness.py`). Verifying current state before building the
guard turned up a bigger update than expected: the 14 groups this file originally documented were
**already resolved** by commit `18551320` (2026-07-18, "renumber to close 14 duplicate
leading-number collisions") — a full, verified renumber of `production/migrations/` to a clean
001-234 sequence, done as its own dedicated session exactly as this file's "Not in scope" section
called for. That work is DONE; do not repeat it.

What's still open: while confirming the current state, the new guard found **one brand-new
collision at `240`** (`240_counterfactual_tracker_chunk_size.sql` and
`240_cross_symbol_corroboration_apr_key.sql`) that appeared *after* the 18551320 renumbering —
two concurrent worktree sessions again independently picking the same "next free" number. This is
exactly the regrowth this file's "Update (2026-07-17)" section predicted would happen without a
preflight check. The new test allow-lists this single group (with reason) so it passes clean
today, and will fail on any further NEW collision going forward. Resolving the `240` pair itself
(renumbering, confirming no filename references) remains open and is deliberately deferred to its
own session per this file's original scope note — same live-DB-adjacent risk profile, just one
pair now instead of fourteen groups — do not attempt it in a follow-up without an explicit
go-ahead.

# `production/migrations/` has 13 duplicate-number groups, not just the one todo 095 flagged

## Finding

While resolving todo 095 (the `db/migrations/` vs `production/migrations/` canonical-location
doc collision), the fix required moving `db/migrations/`'s two live files into
`production/migrations/` (as 227/228) and confirming there was no OTHER collision at those
numbers. That check surfaced a much bigger pre-existing problem: `production/migrations/` itself
has **13 numbers each claimed by 2-3 files**:

```
001 (2 files), 031 (2), 038 (2), 050 (3), 051 (2), 052 (3), 064 (2),
138 (2), 152 (2), 168 (2), 178 (2), 214 (2), 215 (2)
```

Todo 095 only knew about the `001` pair (`001_create_features_intelligence.sql` /
`001_timescale_schema.sql`) and asked to "confirm both are still needed and renumber one if so."
This todo's scope stopped there — it did not attempt to renumber anything, given the newly
discovered scale changes the risk profile substantially (renumbering an already-applied
migration file, at scale, on a live production database, the same night as an unrelated resource
incident, is not a "quick fix in passing" task).

## Why this wasn't fixed inline

Per `docs/foundation/naming-system.md` §11's own rule ("Duplicate numbers are a violation... must
be resolved"), these are real violations. But renumbering already-applied migration files carries
real risk if anything tracks "which migrations have run" by filename/number, and touching 15+
files across the full migration history in one pass is a much larger, higher-blast-radius
undertaking than todo 095's original 3-doc-correction scope. This needs its own deliberately
scoped effort, not an improvised expansion of todo 095.

## Update (2026-07-17): 14th group found — `239`

Phase 161-01's executor renumbered its Controlled Vocabulary schema migration from the plan's
target 237/238 to 239/240 (237/238 had been claimed same-day by Phase 146). It didn't know that
`239_ic_engine_cross_sectional_bootstrap_threads.sql` (commit `28fe12ac`, already on `main` before
that renumbering happened) had already claimed 239. Both files are applied and idempotent — no
migration-tracking table exists in this project (confirmed via `\dt` — no `schema_migrations` or
equivalent), so this is purely a filename-hygiene violation, not a functional conflict. Adds a
14th group to the list above: `239 (2 files: 239_controlled_vocabulary_schema.sql /
239_ic_engine_cross_sectional_bootstrap_threads.sql)`.

161-03 independently hit the same problem and self-corrected by taking the next free number (241)
for its own migration rather than colliding again — logged in that plan's own
`deferred-items.md`.

This confirms the recommended approach below should include a **pre-flight duplicate check as
part of migration numbering itself** (e.g. a `find production/migrations -name "${N}_*"` check
before an executor picks a number), not just a one-time retroactive sweep — the sweep will
immediately regrow if nothing prevents new collisions going forward.

## Recommended approach

1. For each of the 13 groups, confirm both/all files are genuinely independent (different
   concerns that happened to be numbered the same during parallel development) rather than one
   superseding the other.
2. Renumber the later-created file in each pair/triple to the next available number at the END
   of the sequence (append-only renumbering — do not renumber into a gap that could itself
   collide with something not yet discovered).
3. Confirm nothing references the old number by filename (grep the full repo, not just docs —
   check scripts, tests, and any migration-tracking mechanism).
4. Since files are "applied once; never modified after apply" per convention, renumbering an
   already-applied file is a rename only — it does not need to be re-run against the live DB.
   Verify this assumption holds before doing it (check whether any migration-tracking table
   records applied migrations by number/filename, which a rename could desync).

## Not in scope for this todo

Actually performing the renumbering — this todo is the finding + recommended approach; execution
should be its own scoped session given the file-count and live-DB-adjacent risk.

## References

- `.planning/todos/completed/095-migrations-directory-split-collision.md` (or wherever 095 lands
  once resolved) — the fix that surfaced this
- `docs/foundation/naming-system.md` §11 — the rule these violate
