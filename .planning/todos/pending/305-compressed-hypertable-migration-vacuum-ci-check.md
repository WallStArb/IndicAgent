# 305 - No automated check that compressed-hypertable migrations include the mandatory VACUUM

**Filed:** 2026-08-13
**Source:** `/simplify`'s altitude-angle review of the migration 201/312 VACUUM retrofit
(itself a fix for the 2026-08-13 768GB disk-full incident, see
`project_disk_full_incident_2026_08_13` memory and
`docs/foundation/timescaledb-compressed-column-migration.md`).

## The gap

`compress_chunk()` doesn't synchronously reclaim the decompressed heap pages a prior
`decompress_chunk()` populated -- any migration that does
decompress→DDL(`ALTER COLUMN TYPE` / `DROP COLUMN`)→recompress on a compressed hypertable
without a trailing bare `VACUUM <table>;` leaves the full pre-migration footprint on disk under
the new compressed data. Confirmed **three separate times** on `feature_vectors` alone:
migration 201, migration 312 (this one turned into the 768GB incident), and migration 202
(`202_drop_redundant_breakout_flags.sql` -- found and retroactively fixed in the same
`/simplify` pass that filed this todo; it had already run in production, `new_high_flag`/
`new_low_flag` confirmed absent from the live schema).

The remediation plan documented so far is human copy-paste discipline (`docs/foundation/
timescaledb-compressed-column-migration.md`: "the next one of these migrations will copy from
201 or 312 as a template") -- the same mechanism that let 312 repeat 201's omission in the first
place, and let 202 slip through even though it predates 201/312 chronologically. This project
already has the general-mechanism pattern for exactly this class of problem:
`tests/unit/test_market_data_ohlcv_boundary.py` is a CI-enforced allow-list that fails the build
on a new violation of a documented raw-table-access rule.

## Fix direction (not yet designed)

A CI check (likely a new `tests/unit/` test, mirroring `test_market_data_ohlcv_boundary.py`'s
shape) that scans `production/migrations/*.sql` for a `decompress_chunk(` call followed by a
`compress_chunk(` call on the same table without an intervening bare `VACUUM <table>;` statement
between them, and fails the build on any new offender. Needs to handle: multiple decompress/
recompress round-trips in one file (201/312 both do the full compressed-chunk sweep once, not
per-column), the loop-based `DO $$ ... PERFORM decompress_chunk(c.chunk) ... $$` idiom this repo
always uses (not a literal `decompress_chunk(table_name)` call), and an allow-list for the
already-applied, now-fixed migrations (201, 202, 312) plus any pre-201 migration that used this
pattern before the gotcha was known (not yet swept -- check migrations before 201 for the same
shape before assuming only these three exist).

## Where

- New test file (pattern: `tests/unit/test_market_data_ohlcv_boundary.py`)
- `production/migrations/*.sql` -- full sweep needed, not just the 3 known instances
- `docs/foundation/timescaledb-compressed-column-migration.md` -- update once the CI check lands
  to say "enforced by CI" instead of "copy from 201/312 as a template"
