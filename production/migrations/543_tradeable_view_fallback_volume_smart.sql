-- 543: the tradeable view stops nulling volume for kind 'fallback'.
--
-- Migration 497 nulled volume for kinds venue and fallback as "not consolidated". Every canonical
-- (ibkr, fallback) 1d bar (128,510 rows, 147 names, 2013-02-07 to 2026-09-24, checked 2026-10-30)
-- equals its raw (ibkr, smart_trades) row on close and volume: it is SMART TRADES volume, the same
-- basis (ibkr, named) carries and the view already serves. Nulling it dropped usable volume and
-- tripped the volume guard (masking, regime STATUS_INPUT_GAP). Kind venue stays NULL: those rows
-- are single-listing-venue volume. The volume basis of fallback becomes SMART in
-- bars/vendor_kind.py, so rolling statistics segment at the Alpaca seam instead of reading NULL.
--
-- Feature rows built over the nulled volume (1d, the fallback names) are stale until rebuilt.

BEGIN;

CREATE OR REPLACE VIEW market_data_ohlcv_tradeable AS
SELECT "timestamp", symbol, timeframe, open, high, low, close,
       CASE WHEN kind = 'venue' THEN NULL::bigint ELSE volume END AS volume,
       vendor, kind, base, price_sanity_status
FROM market_data_ohlcv
WHERE volume > 0
  AND NOT EXISTS (
      SELECT 1 FROM bar_quality_flag q
      WHERE q.quarantine
        AND q.symbol = market_data_ohlcv.symbol
        AND q.timeframe = market_data_ohlcv.timeframe
        AND q."timestamp" = market_data_ohlcv."timestamp"
  );

COMMENT ON VIEW market_data_ohlcv_tradeable IS 'Compute/measurement read boundary: traded bars (volume > 0), volume nulled for kind venue only (single-venue volume; fallback is SMART TRADES volume since migration 543, 497 before it nulled both), quarantine-flagged bars (bar_quality_flag) excluded; price_sanity_status is no longer a visibility rule (migration 447, todo 500). Raw-table access outside this needs a test_market_data_ohlcv_boundary.py allow-list entry.';

COMMIT;
