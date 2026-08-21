# 293 - `test_migration_schema_sync.py` fails replaying migration 287: `mid_cycle` tag used before it's seeded

## Fixed 2026-08-20

Root cause confirmed: `_apply_baseline()`'s schema-only baseline dump doesn't carry data, so
`tag_vocabulary` rows seeded by migrations 220/221/229/230 (all `<= _BASELINE_MIGRATION_CUTOFF`,
so never replayed) never existed in the rebuilt `indicagent_test` at all -- any post-baseline
migration referencing a pre-cutoff tag (287's `mid_cycle`) hit `instrument_tags_tag_fkey`
immediately. Exactly the same shape of gap `instruments` already had and was already fixed for
(`seed_instruments_2026-07-18.sql`, same `_apply_baseline()` function) -- `tag_vocabulary` just
never got the equivalent treatment.

Fix mirrors the `instruments` pattern exactly: `tests/integration/fixtures/seed_tag_vocabulary_2026-07-18.sql`
(`pg_dump --data-only --table=tag_vocabulary` off live production, 74 rows) applied in
`_apply_baseline()` right after `_SEED_INSTRUMENTS_SQL`. Seeding the full *current* snapshot
(not a hand-curated pre-cutoff subset) is safe: the only 3 post-cutoff migrations that also insert
into `tag_vocabulary` (287/296/299) all carry `ON CONFLICT (tag) DO NOTHING`, so their own inserts
simply no-op against rows this seed already supplied.

**Verified**: `tests/integration/test_migration_schema_sync.py::test_migrated_schema_matches_production`
(the originally-failing test) now passes. Ran the **entire** `tests/integration/` suite --
previously unable to complete its session-scoped DB-rebuild fixture at all -- and it's fully green
(only expected `v2.x archived` skips). This had been silently broken for the whole suite, not just
this one test, since migration 287 landed; any integration-level correctness regression in that
window would have gone undetected.

Found and fixed one more pre-existing gap while re-running the now-unblocked suite: a fourth
`advance_shadow_counters_sync` call site in `tests/integration/test_concept_registry_sync_lifecycle.py`
(`test_cache_mutation_visible_to_is_promotion_eligible`) was missed when todo 337 added the
`expected_status` kwarg, since this whole test file couldn't run to catch it until now.

**Filed:** 2026-08-10
**Source:** Phase 170 Plan 08 Task 2, confirmed pre-existing (fails identically with the session's
changes stashed out, against committed `main`)
**Status:** pending, not blocking

## The gap

`tests/integration/test_migration_schema_sync.py::test_migrated_schema_matches_production` — the
check that committed migrations still reproduce production exactly (the exact failure mode
CLAUDE.md flags as previously caught only by manual git archaeology, Phase 160) — currently fails
during setup, before any real assertion runs:

```
RuntimeError: applying 287_single_name_equity_expansion.sql failed:
psql:.../287_single_name_equity_expansion.sql:189: ERROR:  insert or update on table
"instrument_tags" violates foreign key constraint "instrument_tags_tag_fkey"
DETAIL:  Key (tag)=(mid_cycle) is not present in table "tag_vocabulary".
```

Migration 287 inserts `instrument_tags` rows tagged `mid_cycle`, but in the pinned-baseline +
post-baseline-replay sequence (`tests/integration/conftest.py`), `tag_vocabulary` doesn't yet
have a `mid_cycle` row when 287 runs. Live production has `mid_cycle` in `tag_vocabulary` today
(confirmed), and `production/migrations/221_instrument_tag_vocabulary_v2.sql` does seed it — so
either 221 is baked into the pinned baseline fixture in a way that lost this specific row, or the
baseline/replay ordering doesn't actually replicate the live sequence for this table. Root cause
not diagnosed (out of scope for the phase this was found in).

## Why it matters

This is the exact test class of failure CLAUDE.md's `tests/integration/test_migration_schema_sync.py`
docstring exists to catch early. It currently can't run at all, so a real schema/data drift
between committed migrations and live production between now and whenever this is fixed would go
undetected by this safety net.

## Where

- `tests/integration/conftest.py` — pinned baseline (`fixtures/schema_baseline_2026-07-18.sql`) +
  post-baseline migration replay mechanism
- `production/migrations/221_instrument_tag_vocabulary_v2.sql` — where `mid_cycle` is seeded live
- `production/migrations/287_single_name_equity_expansion.sql:189` — where the replay fails
