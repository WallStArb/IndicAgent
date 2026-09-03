---
status: closed
priority: P3
found_during: phase-151-plan-09
found_date: 2026-08-05
closed_date: 2026-08-07
closed_reason: verified moot -- migration 279 never applied live
---

## Closed 2026-08-07

Checked the live DB before acting, per this project's "verify then delete, don't flag"
discipline: `feature.cross_asset.role_symbols` has **zero rows** in both `config_schema` and
`config_state`, and zero rows in `config_history` for that key (`config_history` itself has
928 rows total, so the table isn't broken/empty -- this key specifically was never written).
Migration 279's file exists on disk
(`production/migrations/279_feature_vector_pipeline_cross_asset_role_symbols_apr.sql`) but was
never executed against this database -- there is no migration-runner tracking table in this
project (migrations are applied by hand), so nothing enforces that a written migration file
actually ran.

This todo's own premise ("still exist in the live DB") doesn't hold: there is no live orphaned
row to delete or mark-retired. Nothing to clean up. The migration file itself stays in place
(migrations are an append-only historical record here, not something to delete after the fact)
-- a future reader who greps `production/migrations/` will still see 279, but `/config/parameters`
has nothing to show for it, so the "confuses a future reader" risk this todo raised doesn't
materialize either.

# `feature.cross_asset.role_symbols` APR key (migration 279) is now orphaned

## What

Plan 151-09 Task 2 removed `services/feature_vector_pipeline.py`'s only reader of the
`feature.cross_asset.role_symbols` config key (`config_schema`/`config_state`, migration
279). That key let an operator swap which 3 ETFs played the equity/long_bond/short_bond
roles in todo 221/222's per-timeframe `CrossAssetState` mechanism -- a mechanism Plan 151-09
replaced with a daily-grain builder (`build_cross_asset_series`) over a FIXED symbol tuple
(`CROSS_ASSET_SYMBOLS` = SPY/TLT/SHY/TIP/HYG/LQD, `src/intelligence/features/
cross_asset_series.py`).

Worth noting: the batch/corpus path (`services/backfill_feature_factory.py`) never read this
APR key either -- its call site always hardcoded `_SPY`/`_TLT`/`_SHY` (now `SPY`/`TLT`/`SHY`
after Plan 151-09 Task 1's move). So this key was ALREADY partially dead (batch-path-inert)
before this plan; Task 2 completed the orphaning by removing the live path's read too.

## What remains

The `config_schema`/`config_state` rows for `feature.cross_asset.role_symbols` still exist in
the live DB (migration 279) but nothing reads them anymore. Not urgent -- an unread config row
is inert, not actively harmful -- but it will confuse a future reader who finds it in
`/config/parameters` and assumes it still does something. Consider a follow-up migration to
either (a) delete the row outright, or (b) leave it with an updated `description` noting it is
retired and why, linking back to this todo. Not resolved by this todo; posing the question
rather than answering it unilaterally (DB schema changes deserve their own migration + review,
not a drive-by deletion inside an unrelated plan).

## References

- `services/feature_vector_pipeline.py` -- `_prewarm_threshold_config()`'s removed role-symbols block (Plan 151-09 Task 2)
- `services/backfill_feature_factory.py` -- batch path's own hardcoded `SPY`/`TLT`/`SHY` call site, never read this key
- migration 279 -- original `feature.cross_asset.role_symbols` seed
- `.planning/milestones/v3.1-phases/151-feature-primitives-expansion-theory-motivated-interaction-la/151-09-SUMMARY.md`
