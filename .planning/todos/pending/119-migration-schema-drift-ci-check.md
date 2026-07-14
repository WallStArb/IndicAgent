---
status: pending
priority: P0
filed: 2026-07-14
source: Phase 160 shipped-code review (Sonnet + Fable second pass) — committed migrations
  233/234 had silently diverged from what was actually applied to the live DB; took a grep,
  an independent Fable pass, and manual git branch archaeology (`git for-each-ref --contains`)
  to surface. Not repeatable as ad hoc review; needs an automated gate. Merged 2026-07-14 with
  todo 064 (indicagent_test has no schema) — 064's fix is this todo's prerequisite
  infrastructure, not a separate task. 064 moved to completed/ as superseded.
---

# 119 — No automated check that committed migrations match the live/applied schema

## Problem

Phase 160's `production/migrations/233_concept_registry_mvp.sql` and
`234_concept_registry_seed_ensemble_strategy.sql` were **not** the SQL that was actually run
against the `indicagent` database. The real migrations were applied under numbers 231/232 on an
orphaned worktree branch (`worktree-agent-ac1f87e995097d3e9`); when that work was folded into
`main`, a migration-number collision (231 got claimed by an unrelated migration in the interim)
was resolved by **regenerating the SQL from scratch** rather than renaming/cherry-picking the
actually-applied files. The regenerated version diverged from production on: `concept_id` column
type (`BIGSERIAL` vs live `UUID`), missing eval-cache columns the application code queries
against, wrong CHECK constraint vocabulary, wrong APR config-key namespace, and a data typo.

Nothing caught this at commit time — the regenerated SQL "looked like" a plausible migration.
It surfaced only because a later code-review pass tried to explain why `concept_registry_service.py`'s
SQL didn't match the committed schema, then went looking for (and found) the orphaned branch
holding the real version. That's not a repeatable detection path — it depended on someone getting
suspicious enough to do git archaeology. Full incident + fix: commit `6f1b4257`, and
`feedback_gsd_worktree_venv_missing.md` in project memory (second pattern, 2026-07-14).

For a project whose stated principle is "instrument everything" and whose registries exist
specifically to be ten-year-auditable evidence, a migration file that silently misdescribes
production schema is close to the worst kind of latent defect: it doesn't announce itself, and
every future reader of the migrations directory is being lied to about what's actually running.

## Solution / Fix / What / Why

No new infrastructure needed — `indicagent_test` already exists for exactly this purpose and
already has `DATABASE_URL` wired to it at test-collection time (`tests/conftest.py`); it has just
never had the ~200 production migrations replayed against it (todo 064's finding: only 3 legacy
v2.x tables exist there today). Building this as one integration test does double duty: it fixes
064's gap (unblocks `tests/integration/*.py` files that assume a live-migrated schema, e.g.
`test_instrument_registry.py`) and closes 119's gap (catches migration/production drift) in the
same piece of work, because the check *is* the fix — the only way to know the migrations
reproduce production is to actually replay them somewhere and compare.

Concretely, a single integration test/CI step:

1. Drop and recreate `indicagent_test` (or truncate to empty) fresh.
2. Replay every migration in `production/migrations/` against it, in order
   (`for f in production/migrations/*.sql; do psql -U postgres -d indicagent_test -f "$f"; done`,
   the exact idiom `docs/reference/cheatsheet.md` already documents for `indicagent`).
3. Diff the resulting schema (`information_schema.columns` + `pg_constraint` per table, or raw
   `\d` output) against live `indicagent`'s schema.
4. Fail loudly on any mismatch — column type, CHECK constraint contents, missing/extra columns,
   index/PK differences.
5. Once schema parity is established, run 064's existing acceptance criteria against the same
   freshly-migrated `indicagent_test` (`pytest tests/integration/test_instrument_registry.py -m
   integration` passes with no code changes) as a second assertion in the same job — a schema
   that structurally matches production but still fails the integration suite is its own signal.

This would have caught the Phase 160 drift immediately (fresh-apply of 233 errors on `CREATE
TABLE` idempotency / `create_hypertable` mismatch alone, before even reaching the deeper column
drift), rather than requiring a reviewer to notice the application code didn't match the schema
months later, potentially after real promotion data had been written against the wrong shape.

## Scope note

This is a project-wide migrations-pipeline gap, not Phase-160-specific — any future migration
regenerated-from-description instead of copied-from-applied-file can drift the same way. Worth
building once, applying to all future migrations. Elevated from 064's original P3 ("workaround
exists") to P0 because the Phase 160 incident shows the actual cost of not having this: a
production-schema lie that survived a full plan review and unit tests undetected.
