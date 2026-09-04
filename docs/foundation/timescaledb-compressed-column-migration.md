# TimescaleDB Compressed-Column Migration Pattern

**Version:** 1.0
**Status:** current
**Last Updated:** 2026-09-04

## Why this doc exists

Migration 312 (`feature_vectors` float64→float32 drift fix, 2026-08-12) ran the standard
decompress→`ALTER COLUMN TYPE`→recompress sequence for changing a column type on a compressed
hypertable, copied from migration 201 (2026-07-09, the original version of this same fix).
Migration 202 (2026-07-09, `ALTER TABLE ... DROP COLUMN` on the same compressed hypertable)
independently did the identical decompress→DDL→recompress round trip the same day. All three
migrations assumed `compress_chunk()` would leave the chunk in its correct final size once it
finished. It doesn't: `compress_chunk()` moves rows into the compressed columnar store but does
not synchronously reclaim the decompressed heap pages `decompress_chunk()` populated earlier in
the same migration. That reclamation only happens when something `VACUUM`s the chunk afterward,
and TimescaleDB's internal chunk tables are not guaranteed to get picked up promptly by
autovacuum (confirmed 2026-08-13: every chunk this pattern touched showed 0 live tuples and
`last_vacuum`/`last_autovacuum` both `NULL` — never vacuumed, not even once).

None of the three migrations included that step. The result: `feature_vectors` grew from a
genuine ~57GB to 768GB on disk, root filesystem hit 100% full (8.1GB free on a 914GB disk), and
Postgres PANIC-crashed twice from `ENOSPC` before anyone noticed. Full incident writeup: see the
git history around 2026-08-13 disk-space investigation (todo/session notes) — the numbers above
are the confirmed post-mortem figures, not estimates.

**This is a load-bearing pattern for this codebase.** Migrations 216, 255, 266, 267, 288-293,
and 307 all drifted feature columns back to `double precision` after 201's original fix — the
project's own history shows this convention gets reused every few months as new feature waves
land and someone eventually re-applies the float32 convention. The next one of these migrations
should still copy from 201 or 312 as a template, but **the missing-VACUUM omission itself is
now enforced by CI** (todo 305, `tests/unit/test_compressed_hypertable_migration_vacuum_check.py`):
any migration in `production/migrations/*.sql` that calls both `decompress_chunk(` and
`compress_chunk(` without a bare `VACUUM <table>;` statement fails the build immediately, so a
fourth silent drop is structurally blocked rather than depending on copy-paste discipline alone.

## The correct pattern

```sql
BEGIN;

-- 1. Decompress every currently-compressed chunk.
DO $$
DECLARE
  c record;
BEGIN
  FOR c IN
    SELECT format('%I.%I', chunk_schema, chunk_name)::regclass AS chunk
    FROM timescaledb_information.chunks
    WHERE hypertable_name = '<hypertable>' AND is_compressed
  LOOP
    PERFORM decompress_chunk(c.chunk);
  END LOOP;
END $$;

-- 2. Do the actual ALTER TABLE / ALTER COLUMN TYPE work here.
ALTER TABLE <hypertable>
    ALTER COLUMN <col> TYPE <new_type> USING <col>::<new_type>,
    ...;

COMMIT;

-- 3. Recompress, as its own statement outside the DDL transaction (compress_chunk()
--    takes its own per-chunk locks; a failure partway through recompression this way
--    can't roll back the already-verified type change from step 2).
DO $$
DECLARE
  c record;
BEGIN
  FOR c IN
    SELECT format('%I.%I', chunk_schema, chunk_name)::regclass AS chunk
    FROM timescaledb_information.chunks
    WHERE hypertable_name = '<hypertable>' AND NOT is_compressed
  LOOP
    PERFORM compress_chunk(c.chunk);
  END LOOP;
END $$;

-- 4. MANDATORY. Reclaims the decompressed heap pages from step 1 that compress_chunk()
--    in step 3 does not synchronously free. Cannot run inside a transaction block --
--    must stay a bare top-level statement, never wrapped in BEGIN/COMMIT.
VACUUM <hypertable>;
```

Step 4 is the one that was missing in both 201 and 312. It is not optional and not
"nice to have" — skip it and the migration silently doubles-plus the table's disk footprint
until someone happens to investigate why the disk is full.

## Before running this against live data, verify — don't assume

Migration 312's original comment claimed it was "timed deliberately to run against the
now-truncated table... so the decompress/recompress dance is a no-op on an empty table."
That assumption was wrong at execution time (the intended prior `TRUNCATE` either didn't run
or didn't cover this data) and the migration had no way to detect the mismatch. If a future
migration is relying on a "this table will be empty/small when I run" assumption to justify
skipping cost analysis:

- Verify it with a row count query immediately before running, don't infer it from a plan
  written days earlier.
- Prefer making the migration correct regardless of table state (i.e., always include step 4)
  over making it fast under an assumption that might not hold. A `VACUUM` on a genuinely empty
  table costs almost nothing; skipping it when the table turns out not to be empty costs
  hundreds of GB.

## Other gotchas

- `decompress_chunk()`'s keyword flag is `if_compressed => true`, not `if_not_compressed`
  (the latter doesn't exist and will raise `function ... does not exist`).
- `VACUUM` (bare, not `FULL`) is sufficient and safe here — the chunk's dead pages are fully
  dead (0 live tuples), so a plain `VACUUM` can truncate them back to the OS. `VACUUM FULL` is
  unnecessary and requires holding an `ACCESS EXCLUSIVE` lock plus temporary extra disk space
  for the rewrite.
- Don't trust `pg_stat_user_tables.n_live_tup == 0` as proof a chunk is empty on its own —
  it can also mean "never analyzed." Confirmed 2026-08-13 on an unrelated `market_data_ohlcv`
  chunk: reported 0 live tuples, `VACUUM FULL` found 12.8M real, live, nonremovable rows. If a
  chunk looks empty, check `last_analyze`/`last_autoanalyze` before concluding it's actually
  bloat.

## Reference implementations

`production/migrations/201_feature_vectors_float32.sql`,
`production/migrations/202_drop_redundant_breakout_flags.sql`, and
`production/migrations/312_feature_vectors_float32_drift_fix.sql` were all retroactively
corrected 2026-08-13 to include step 4. Copy the pattern from any of the three as a starting
point for the next float-drift (or any other compressed-hypertable column type change or
`DROP COLUMN`) migration.

<!-- src: tests/unit/test_compressed_hypertable_migration_vacuum_check.py -->
CI enforcement (`tests/unit/test_compressed_hypertable_migration_vacuum_check.py`, todo 305)
confirms these are the only three migrations that ever did the real round trip: it swept all
migrations mentioning `decompress_chunk` and found 201/202/312 are the only ones that pair a
`decompress_chunk(` with a `compress_chunk(` call on the same table and actually execute (not
just describe the pattern in a comment). Migrations 216, 255, 266, 267, 288-293, and 307 that
drifted feature columns back to `double precision` did so via plain
`ADD COLUMN IF NOT EXISTS <col> DOUBLE PRECISION` on brand-new columns — never touching
`decompress_chunk`/`compress_chunk` at all — so they carry no compressed-heap-page bloat risk
and aren't in scope for this guard; they're a distinct, separate drift (new columns landing in
the wrong type from birth, not an existing compressed column round-tripped incorrectly) that
still needs its own float32-conversion cleanup migration eventually.
