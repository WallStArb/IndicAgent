-- 468: raw archive holds every vendor: source joins the primary key (todo 528)
--
-- ohlcv_intraday_raw_archive archived only ibkr_named 15m/1h rows so far; its
-- PK (timestamp, symbol, timeframe) made a second vendor's row for an
-- already-keyed slot unrepresentable, which is what let the load engine's
-- drops look harmless. Widen the key with source, make source NOT NULL
-- (verified 2026-10-10: 0 NULLs across 95.67M rows), keep the compression
-- config (segmentby symbol, timeframe; orderby timestamp) as is.
--
-- Template: docs/foundation/timescaledb-compressed-column-migration.md
-- (decompress -> DDL -> recompress -> bare VACUUM; CI-enforced). 86 of 87
-- chunks compressed at write time; the DO loops handle any state at run time.
-- Table state verified immediately before execution: 95,666,499 rows, none
-- NULL-sourced (the template's "verify, don't assume" rule).

BEGIN;

-- 1. Decompress every currently-compressed chunk.
DO $$
DECLARE
  c record;
BEGIN
  FOR c IN
    SELECT format('%I.%I', chunk_schema, chunk_name)::regclass AS chunk
    FROM timescaledb_information.chunks
    WHERE hypertable_name = 'ohlcv_intraday_raw_archive' AND is_compressed
  LOOP
    PERFORM decompress_chunk(c.chunk);
  END LOOP;
END $$;

-- 2. Widen the key with source; source becomes NOT NULL.
ALTER TABLE ohlcv_intraday_raw_archive
    DROP CONSTRAINT ohlcv_intraday_raw_archive_pkey,
    ALTER COLUMN source SET NOT NULL,
    ADD CONSTRAINT ohlcv_intraday_raw_archive_pkey
        PRIMARY KEY ("timestamp", symbol, timeframe, source);

COMMIT;

-- 3. Recompress, outside the DDL transaction (per-chunk locks; a partway
--    failure can't roll back the verified key change).
DO $$
DECLARE
  c record;
BEGIN
  FOR c IN
    SELECT format('%I.%I', chunk_schema, chunk_name)::regclass AS chunk
    FROM timescaledb_information.chunks
    WHERE hypertable_name = 'ohlcv_intraday_raw_archive' AND NOT is_compressed
  LOOP
    PERFORM compress_chunk(c.chunk);
  END LOOP;
END $$;

-- 4. MANDATORY: reclaims the decompressed heap pages from step 1 that
--    compress_chunk() does not synchronously free. Bare top-level statement,
--    never inside a transaction (the migration-312 lesson, CI-enforced).
VACUUM ohlcv_intraday_raw_archive;
