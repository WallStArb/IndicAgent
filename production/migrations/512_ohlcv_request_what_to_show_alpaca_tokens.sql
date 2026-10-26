-- 512: ohlcv_request.what_to_show accepts the alpaca bars leaves' request tokens. Migration 380
-- built the table for IBKR's 1d request types (TRADES, ADJUSTED_LAST); the alpaca leaves record
-- what they actually asked, the timeframe parameter (1Min, 5Min, 1Day via _TF_TO_ALPACA), which
-- the nightly capture (scripts/ops/bars/ops_bar_nightly.py) writes as the first non-IBKR request
-- rows. First live nightly run 2026-10-26 raised CheckViolation on 5Min; the check widens rather
-- than the leaf lying about the request. Provenance [rca_analysis]. Idempotent by IF EXISTS.

BEGIN;

ALTER TABLE ohlcv_request DROP CONSTRAINT IF EXISTS ohlcv_request_what_to_show_check;

ALTER TABLE ohlcv_request ADD CONSTRAINT ohlcv_request_what_to_show_check
    CHECK (what_to_show = ANY (ARRAY['TRADES'::text, 'ADJUSTED_LAST'::text,
                                     '1Min'::text, '5Min'::text, '1Day'::text]));

COMMIT;
