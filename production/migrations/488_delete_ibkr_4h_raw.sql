-- Migration 488: written data-quality delete of the IBKR 4h bars (owner 2026-10-15, todo 512 record)
--
-- Rule (written 2026-10-15, before it is applied): 4h is no timeframe of the data layer's end
-- state (raw 5m and 1d per vendor; 15m and 1h derived from 5m). The only 4h bars are 2,184 IBKR
-- named rows on two names (LLY 432 from 2025-11-17, MSFT 1,752 from 2023-08-08, last bar
-- 2026-08-06), a leftover of an old lane: nothing fetches, derives or reads them
-- (bar_source_policy: "kept, not fetched and not derived"). They and everything derived from
-- them are deleted: ohlcv_raw, the canonical copies in market_data_ohlcv (equal to raw on all
-- 2,184 keys, checked below) and the two ohlcv_coverage rows; the 4h source policy is closed.
-- Every raw value is logged to ohlcv_revision first (origin raw, under one ohlcv_load per name,
-- caller dq-delete-191-10), so the delete is recoverable. Instruments are untouched (both names
-- stay active; only the 4h series goes).

BEGIN;
SET LOCAL lock_timeout = '30s';

DO $$
DECLARE
    n_raw int;
    n_equal int;
BEGIN
    SELECT count(*) INTO n_raw FROM ohlcv_raw WHERE timeframe = '4h';
    SELECT count(*) INTO n_equal
      FROM ohlcv_raw r JOIN market_data_ohlcv m USING (symbol, timeframe, "timestamp")
     WHERE r.timeframe = '4h'
       AND (r.open, r.high, r.low, r.close, r.volume)
           IS NOT DISTINCT FROM (m.open, m.high, m.low, m.close, m.volume::bigint);
    IF n_raw <> 2184 OR n_equal <> 2184
       OR (SELECT count(*) FROM market_data_ohlcv WHERE timeframe = '4h') <> 2184
       OR EXISTS (SELECT 1 FROM ohlcv_raw WHERE timeframe = '4h'
                   AND (vendor, kind) <> ('ibkr', 'named')) THEN
        RAISE EXCEPTION '4h footprint changed: raw %, canonical equal %', n_raw, n_equal;
    END IF;
END $$;

CREATE TEMP TABLE dq_4h_load ON COMMIT DROP AS
SELECT gen_random_uuid() AS load_id, symbol, count(*)::int AS n,
       (min("timestamp") AT TIME ZONE 'UTC')::date AS first_bar,
       (max("timestamp") AT TIME ZONE 'UTC')::date AS last_bar
  FROM ohlcv_raw WHERE timeframe = '4h' GROUP BY symbol;

INSERT INTO ohlcv_load (load_id, symbol, timeframe, source, requested_start, requested_end,
                        outcome, n_bars, n_removed, first_bar, last_bar, detail, caller,
                        destination)
SELECT load_id, symbol, '4h', 'ibkr', first_bar, last_bar, 'applied', n, n, first_bar,
       last_bar,
       'written data-quality delete (migration 488, owner 2026-10-15, todo 512): 4h is no '
       'timeframe of the data layer; every value logged to ohlcv_revision first',
       'dq-delete-191-10', 'raw'
  FROM dq_4h_load;

INSERT INTO ohlcv_revision (load_id, symbol, timeframe, "timestamp", old_open, old_high,
                            old_low, old_close, old_volume, old_source, origin, vendor, kind,
                            request_id)
SELECT l.load_id, r.symbol, r.timeframe, r."timestamp", r.open, r.high, r.low, r.close,
       r.volume, 'ibkr_named', 'raw', r.vendor, r.kind, r.request_id
  FROM ohlcv_raw r JOIN dq_4h_load l USING (symbol)
 WHERE r.timeframe = '4h';

DELETE FROM market_data_ohlcv WHERE timeframe = '4h';
DELETE FROM ohlcv_raw WHERE timeframe = '4h';
DELETE FROM ohlcv_coverage WHERE timeframe = '4h';
UPDATE bar_source_policy SET valid_to = CURRENT_DATE
 WHERE timeframe = '4h' AND valid_to IS NULL;

DO $$
BEGIN
    IF (SELECT count(*) FROM ohlcv_revision v JOIN ohlcv_load l USING (load_id)
         WHERE l.caller = 'dq-delete-191-10') <> 2184
       OR EXISTS (SELECT 1 FROM ohlcv_raw WHERE timeframe = '4h')
       OR EXISTS (SELECT 1 FROM market_data_ohlcv WHERE timeframe = '4h') THEN
        RAISE EXCEPTION '4h delete did not balance';
    END IF;
END $$;

COMMIT;
