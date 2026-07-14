---
status: pending
priority: P0
filed: 2026-07-14
source: Phase 160 shipped-code review (Sonnet + Fable second pass) — committed migrations
  233/234 had silently diverged from what was actually applied to the live DB; took a grep,
  an independent Fable pass, and manual git branch archaeology (`git for-each-ref --contains`)
  to surface. Not repeatable as ad hoc review; needs an automated gate.
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

Add a CI (or pre-push / pre-merge) check that:

1. Spins up a scratch Postgres/TimescaleDB instance (or a disposable schema in an existing test
   DB — see todo 064's test-DB-schema-sync work, which this can share infrastructure with).
2. Applies every migration in `production/migrations/` in order from empty.
3. Diffs the resulting schema (`\d` per table, or `information_schema` dump) against the live
   production schema (or against a pinned golden snapshot, refreshed each time a migration is
   verified applied).
4. Fails loudly on any mismatch — column type, CHECK constraint contents, missing/extra columns,
   index/PK differences.

This would have caught the Phase 160 drift immediately (fresh-apply of 233 errors on `CREATE
TABLE` idempotency / `create_hypertable` mismatch alone, before even reaching the deeper column
drift), rather than requiring a reviewer to notice the application code didn't match the schema
months later, potentially after real promotion data had been written against the wrong shape.

## Scope note

This is a project-wide migrations-pipeline gap, not Phase-160-specific — any future migration
regenerated-from-description instead of copied-from-applied-file can drift the same way. Worth
building once, applying to all future migrations.
