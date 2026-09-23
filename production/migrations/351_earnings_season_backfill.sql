-- Migration 351: backfill earnings_season_flag + days_since_quarter_end onto the
-- pre-existing feature_vectors corpus (Phase 176 plan 176-07, todo 353).
--
-- Migration 350 (plan 176-02) added both columns as NULL on every existing row;
-- plan 176-03 wired new-row compute. This migration fills the rows that already
-- existed -- with a direct two-column UPDATE in plain SQL date arithmetic instead
-- of a full feature-factory recompute (Fable review, 2026-09-23): both columns are
-- pure functions of bar_ts alone, and because the statement's SET list below names
-- exactly those two columns, collateral damage to any other column is structurally
-- impossible -- nothing else is addressable by this statement. That is the checked
-- replacement for the pre/post full-width checksums the previous --refresh
-- mechanism required (tests/unit/test_earnings_season_backfill_contract.py parses
-- the SET clause and asserts the two-assignment shape).
--
-- Window boundaries are APR-sourced per D-03's no-magic-numbers rule: both bounds
-- are read from config_state inside this file at run time (no window-bound literal
-- appears anywhere in the executable statements), and the step-0 guard RAISEs if
-- either key is missing, unordered, or not castable to int, rather than silently
-- writing NULL flags.
--
-- Idempotent: the UPDATE is scoped WHERE <stored> IS DISTINCT FROM <computed> per
-- column, so a second run (or a re-run after a partial failure) rewrites nothing.
-- Verified live in plan 176-07 Task 2 by re-running this file and asserting zero
-- rows updated.
--
-- Compressed-hypertable round trip per
-- docs/foundation/timescaledb-compressed-column-migration.md: decompress every
-- compressed chunk -> the scoped UPDATE -> recompress -> MANDATORY bare VACUUM
-- (step 4). compress_chunk() does not synchronously reclaim the heap pages
-- decompress_chunk() populated; skipping the final VACUUM is exactly what turned
-- migration 312 into a 768GB disk-full incident on 2026-08-13. CI-enforced by
-- tests/unit/test_compressed_hypertable_migration_vacuum_check.py.

BEGIN;

-- Step 0: APR guard -- abort before any decompression work if the window bounds
-- are missing, unordered, or not castable to int.
DO $$
DECLARE
  v_start_days int;
  v_end_days int;
BEGIN
  SELECT config_value::int INTO v_start_days
    FROM config_state
   WHERE config_key = 'feature.earnings_season.start_days';
  SELECT config_value::int INTO v_end_days
    FROM config_state
   WHERE config_key = 'feature.earnings_season.end_days';
  IF v_start_days IS NULL THEN
    RAISE EXCEPTION 'migration 351: config_state has no int-castable value for feature.earnings_season.start_days -- aborting rather than writing NULL flags';
  END IF;
  IF v_end_days IS NULL THEN
    RAISE EXCEPTION 'migration 351: config_state has no int-castable value for feature.earnings_season.end_days -- aborting rather than writing NULL flags';
  END IF;
  IF v_start_days > v_end_days THEN
    RAISE EXCEPTION 'migration 351: feature.earnings_season.start_days (%) is greater than end_days (%) -- empty window, aborting', v_start_days, v_end_days;
  END IF;
END $$;

-- The date expressions below mirror src/intelligence/feature_factory.py's
-- _days_since_quarter_end / _earnings_season_flag (plan 176-03) exactly: quarter
-- ends are Mar 31 / Jun 30 / Sep 30 / Dec 31, the quarter-end date itself returns
-- 0, and January dates count from the prior year's Dec 31 -- all taken in UTC
-- (DAG invariant 6; bar_ts is timestamptz). Expressed as temporary IMMUTABLE SQL
-- helpers so the window logic is written exactly once, then dropped at the end of
-- this migration's transaction. Agreement with the Python originals is verified
-- against 20 sampled persisted rows in plan 176-07 Task 3.
CREATE OR REPLACE FUNCTION _m351_days_since_quarter_end(p_bar_ts timestamptz)
RETURNS real
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $fn$
  SELECT CASE
           WHEN (p_bar_ts AT TIME ZONE 'UTC')::date
                = (date_trunc('quarter', (p_bar_ts AT TIME ZONE 'UTC')::date)
                   + interval '3 months' - interval '1 day')::date
             THEN 0::real
           ELSE ((p_bar_ts AT TIME ZONE 'UTC')::date
                 - (date_trunc('quarter', (p_bar_ts AT TIME ZONE 'UTC')::date)::date - 1))::real
         END
$fn$;

CREATE OR REPLACE FUNCTION _m351_earnings_season_flag(
  p_bar_ts timestamptz,
  p_start_days int,
  p_end_days int
)
RETURNS real
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $fn$
  SELECT CASE
           WHEN _m351_days_since_quarter_end(p_bar_ts) BETWEEN p_start_days AND p_end_days
             THEN 1.0::real
           ELSE 0.0::real
         END
$fn$;

-- Step 1: decompress every currently-compressed chunk.
DO $$
DECLARE
  c record;
BEGIN
  FOR c IN
    SELECT format('%I.%I', chunk_schema, chunk_name)::regclass AS chunk
    FROM timescaledb_information.chunks
    WHERE hypertable_name = 'feature_vectors' AND is_compressed
  LOOP
    PERFORM decompress_chunk(c.chunk, if_compressed => true);
  END LOOP;
END $$;

-- Step 2: the scoped two-column UPDATE. The SET list assigns exactly the two new
-- columns and nothing else; the window bounds come from config_state via the CTE;
-- the IS DISTINCT FROM scoping makes a re-run a genuine no-op rather than a full
-- rewrite (this is what makes the file idempotent and safe to re-run after a
-- partial failure).
WITH w AS (
  SELECT
    (SELECT config_value::int FROM config_state
      WHERE config_key = 'feature.earnings_season.start_days') AS start_days,
    (SELECT config_value::int FROM config_state
      WHERE config_key = 'feature.earnings_season.end_days')   AS end_days
)
UPDATE feature_vectors f
SET days_since_quarter_end = _m351_days_since_quarter_end(f.bar_ts),
    earnings_season_flag   = _m351_earnings_season_flag(f.bar_ts, w.start_days, w.end_days)
FROM w
WHERE f.days_since_quarter_end IS DISTINCT FROM _m351_days_since_quarter_end(f.bar_ts)
   OR f.earnings_season_flag   IS DISTINCT FROM _m351_earnings_season_flag(f.bar_ts, w.start_days, w.end_days);

DROP FUNCTION _m351_earnings_season_flag(timestamptz, int, int);
DROP FUNCTION _m351_days_since_quarter_end(timestamptz);

COMMIT;

-- Step 3: recompress every now-uncompressed chunk, as its own statement outside
-- the DDL transaction (compress_chunk() takes its own per-chunk locks; a failure
-- partway through recompression this way cannot roll back the already-committed
-- correct UPDATE).
DO $$
DECLARE
  c record;
BEGIN
  FOR c IN
    SELECT format('%I.%I', chunk_schema, chunk_name)::regclass AS chunk
    FROM timescaledb_information.chunks
    WHERE hypertable_name = 'feature_vectors' AND NOT is_compressed
  LOOP
    PERFORM compress_chunk(c.chunk);
  END LOOP;
END $$;

-- Step 4: MANDATORY, not optional. Reclaims the decompressed heap pages from
-- step 1 that compress_chunk() in step 3 does not synchronously free -- these
-- internal chunk tables are not guaranteed to be picked up promptly by
-- autovacuum, and omitting this statement is exactly what turned migration 312
-- into a 768GB disk-full incident on 2026-08-13. Cannot run inside a transaction
-- block, so this stays a bare top-level statement, never wrapped in BEGIN/COMMIT
-- or a DO block. Plain VACUUM, not FULL: the dead pages are fully dead, and FULL
-- would take an ACCESS EXCLUSIVE lock plus rewrite space for no benefit here.
VACUUM feature_vectors;
