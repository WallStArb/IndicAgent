-- Migration 616: listing_end row for BKH (ledger 2026-11-24h; the migration is the sole writer of
-- listing_end). Black Hills Corp's merger with NorthWestern closed 2026-11-16 and the surviving
-- entity trades under a new ticker. The BKH ticker's last bar is 2026-11-13 on both vendors
-- (ohlcv_raw alpaca sip_rth and massive sip_flat); Alpaca answered no_data for BKH on the
-- 2026-11-22, 2026-11-23 and 2026-11-24 nightly requests (ohlcv_request); Massive holds nothing
-- after 2026-11-13. Without the row the 1d verdict judges BKH to the last completed session, and
-- proven_start_1d turned false at the 11-24 06:31 run (six trailing sessions missing), which
-- refused the corpus pilot's data gate. Reason `merged` is the legal event (the vocabulary has no
-- `renamed`; a later row may supersede it). The new ticker's series is a separate instrument and
-- is not claimed as BKH's continuation (todo 624). Idempotent; no table is rewritten, so no
-- VACUUM clause is owed.

BEGIN;

INSERT INTO listing_end (symbol, last_session, reason, evidence)
SELECT 'BKH', DATE '2026-11-13', 'merged',
       '{"source": "vendor tape and ohlcv_request", "note": "Black Hills Corp merger with NorthWestern closed 2026-11-16; the BKH ticker series ends: last alpaca 1d bar and last massive 1d bar 2026-11-13, alpaca no_data for BKH on the 2026-11-22, 2026-11-23 and 2026-11-24 requests; the new ticker is a separate instrument and is not claimed as BKH continuation; ledger 2026-11-24h; the Form 25-NSE accession is not recorded"}'::jsonb
WHERE NOT EXISTS (SELECT 1 FROM listing_end le WHERE le.symbol = 'BKH');

COMMIT;
