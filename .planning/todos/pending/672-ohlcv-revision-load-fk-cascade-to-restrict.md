---
status: pending
priority: P3
filed: 2026-11-24
source: todo 535 item 52 (plan 191-20 simplify review, 2026-10-27), re-verified live 2026-11-24 in the deferred todo re-check
---

# ohlcv_revision.load_id cascades on delete of an ohlcv_load row

## What

`ohlcv_revision_load_id_fkey` is still `ON DELETE CASCADE` (verified 2026-11-24, `pg_constraint.confdeltype = 'c'`, 28,696,694 revision rows). Deleting any `ohlcv_load` row silently deletes the revision rows under it, including another vendor's evidence (3,179,829 IBKR revision rows sat under Tradier loads when this was found). No current tool deletes loads, so nothing is exposed today; the schema should still refuse it for any future deleter.

## Fix

Switch the FK to `ON DELETE RESTRICT`, as `ohlcv_restatement_flag` already does: add the new constraint `NOT VALID`, then `VALIDATE`, outside any fetch or corpus run, in a migration committed in the same breath as the live apply. The table is 28.7M rows, so run it in a quiet window and follow `docs/foundation/timescaledb-compressed-column-migration.md` only if the table is compressed (check first).

## Gate

Quiet window (no heavy job). Independent of the corpus rerun; not on the critical path.
