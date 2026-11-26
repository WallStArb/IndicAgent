-- Migration 619: listing_end row for BIPC (the migration is the sole writer of listing_end). Brookfield
-- Infrastructure Corp is merging into the new BIP Inc. in Brookfield's corporate simplification: BIPC shares
-- exchange one-for-one into BIP Inc. Class A shares and BIPC is delisted from NYSE and TSX (shareholder votes
-- 2026-10-14, completion expected Q4 2026; sources https://bip.brookfield.com/stock-information/proposed-simplification
-- and https://bip.brookfield.com/press-releases/bip/brookfield-infrastructure-announces-intention-simplify-corporate-structure,
-- Form 6-K, SEC CIK 1788348; the effective date is not recorded here). The BIPC ticker's last bar is 2026-11-20 on
-- alpaca sip_rth (massive sip_flat ends 2026-11-18); Alpaca answered no_data for BIPC 1d on the 2026-11-25 and
-- 2026-11-26 nightly requests (ohlcv_request); the last three sessions trade 6 to 10 M shares against about 1 M
-- normal, consistent with final trading days. Without the row the 1d verdict judges BIPC to the last completed
-- session, session_coverage fell 0.99940, 0.99880, 0.99821 (2026-11-24 to 2026-11-26) under the 0.999 floor and
-- proven_start_1d turned false, which refused corpus run 04db3930's data gate. Reason `merged` is the legal event.
-- BIP Inc. is a separate instrument and is not claimed as BIPC's continuation. Idempotent; no table is rewritten,
-- so no VACUUM clause is owed.

BEGIN;

INSERT INTO listing_end (symbol, last_session, reason, evidence)
SELECT 'BIPC', DATE '2026-11-20', 'merged',
       '{"source": "vendor tape, ohlcv_request and Brookfield investor pages", "note": "BIPC merges into BIP Inc. (one-for-one into Class A shares; BIPC delisted from NYSE and TSX); last alpaca 1d bar 2026-11-20, last massive 1d bar 2026-11-18, alpaca no_data for BIPC on the 2026-11-25 and 2026-11-26 requests; final-session volume 6 to 10 M against about 1 M normal; BIP Inc. is a separate instrument and is not claimed as BIPC continuation; the effective date and Form 25-NSE accession are not recorded; sources https://bip.brookfield.com/stock-information/proposed-simplification and https://bip.brookfield.com/press-releases/bip/brookfield-infrastructure-announces-intention-simplify-corporate-structure; lead ruling 2026-11-26"}'::jsonb
WHERE NOT EXISTS (SELECT 1 FROM listing_end le WHERE le.symbol = 'BIPC');

COMMIT;
