-- 444: market_data_ohlcv refuses synthetic_fill rows (plan 185-32).
--
-- The store holds real rows only since the 185-25 swap (sources ibkr_named, derived_5m and
-- tradier; zero synthetic_fill). Plan 185-32 deleted the last placeholder paths (the historical
-- pipeline's --normalize pass and its 4h fill; backfill_feature_factory's fetch-stage fill), and
-- tests/unit/test_market_data_ohlcv_no_synthetic_fill.py fences the code side. This constraint
-- makes the database refuse the row, so a path the scan misses fails loudly at insert or update.
--
-- A NULL source stays allowed (IS DISTINCT FROM): the swap treated a NULL-source row as real.
--
-- TimescaleDB 2.27.1 behavior, rehearsed on indicagent_test with a compressed scratch hypertable
-- shaped like this one (segmentby symbol, timeframe; orderby timestamp):
-- - ADD CONSTRAINT ... NOT VALID is accepted on a hypertable with compressed chunks, propagates
--   to every chunk, and still checks the existing chunk rows: with a synthetic_fill row in a
--   compressed chunk the ADD failed ("check constraint ... of relation _hyper_..._chunk is
--   violated by some row"). No rows are rewritten and no chunk is decompressed.
-- - Afterwards a synthetic_fill INSERT or UPDATE fails on a compressed chunk's range and on a new
--   chunk; real rows and NULL sources insert; compress_chunk and decompress_chunk still work.
-- - VALIDATE CONSTRAINT is refused ("operation not supported on hypertables that have
--   columnstore enabled"), so the parent's convalidated stays false. It is NOT VALID in name
--   only: the ADD checked every existing chunk row, and the live table held zero synthetic_fill
--   rows when this was applied.
--
-- No trigger fallback was needed. Idempotent.

BEGIN;

SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'market_data_ohlcv'::regclass
           AND conname = 'market_data_ohlcv_no_synthetic_fill'
    ) THEN
        ALTER TABLE market_data_ohlcv
            ADD CONSTRAINT market_data_ohlcv_no_synthetic_fill
            CHECK (source IS DISTINCT FROM 'synthetic_fill') NOT VALID;
    END IF;
END
$$;

COMMENT ON CONSTRAINT market_data_ohlcv_no_synthetic_fill ON market_data_ohlcv IS
    'Real rows only (plans 185-25, 185-32): a calendar-grid placeholder is never a bar. NOT VALID '
    'because TimescaleDB refuses VALIDATE on a columnstore hypertable; the ADD checked every chunk.';

COMMIT;
