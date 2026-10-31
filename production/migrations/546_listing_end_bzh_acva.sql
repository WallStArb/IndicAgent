-- Migration 546: listing_end seed rows for BZH and ACVA (todo 567 item 3, the migration is the
-- sole writer of listing_end). Evidence checked against SEC EDGAR and ohlcv_raw 2026-10-31:
--   BZH  acquired by Dream Finders Homes for $33.50/share cash, closed 2026-10-20; NYSE halted
--        trading before the open that day and filed Form 25-NSE 2026-10-20 (accession
--        0000876661-26-000851); last alpaca 1d bar 2026-10-19 (close 33.48).
--   ACVA acquired by Copart for $10.50/share cash, completed 2026-10-16; the tender offer
--        expired 5pm ET 2026-10-15 and NYSE suspended trading; Form 25-NSE 2026-10-16 (accession
--        0000876661-26-000841); last alpaca 1d bar 2026-10-15 (close 10.50, the deal price;
--        ohlcv_raw's 2026-10-16 row is a zero-volume placeholder the tradeable view excludes).

BEGIN;

INSERT INTO listing_end (symbol, last_session, reason, evidence)
SELECT 'BZH', DATE '2026-10-19', 'acquired',
       '{"source": "SEC EDGAR", "form": "25-NSE", "filed": "2026-10-20",
         "accession": "0000876661-26-000851",
         "note": "Dream Finders Homes cash merger ($33.50/share) closed 2026-10-20; NYSE trading halted before the open that day; last alpaca 1d bar 2026-10-19"}'::jsonb
WHERE NOT EXISTS (SELECT 1 FROM listing_end le WHERE le.symbol = 'BZH');

INSERT INTO listing_end (symbol, last_session, reason, evidence)
SELECT 'ACVA', DATE '2026-10-15', 'acquired',
       '{"source": "SEC EDGAR", "form": "25-NSE", "filed": "2026-10-16",
         "accession": "0000876661-26-000841",
         "note": "Copart cash acquisition ($10.50/share) completed 2026-10-16; tender offer expired 2026-10-15; last alpaca 1d bar 2026-10-15"}'::jsonb
WHERE NOT EXISTS (SELECT 1 FROM listing_end le WHERE le.symbol = 'ACVA');

COMMIT;
