-- Migration 475: ohlcv_revision identity is (load, series, vendor, kind) (phase 191 plan 04)
--
-- Step 3 of docs/plans/2026-10-12-unified-raw-bar-table-design.md (todo 533), applied inside the
-- cutover window with every old-store writer stopped. Migration 472 added vendor, kind and
-- request_id as nullable columns and filled vendor and kind from old_source. This migration:
--
-- 1. repeats the same old_source mapping for any row the old fetcher wrote after 472 (idempotent);
-- 2. fails the transaction if a row still has no vendor or kind (an unmapped old_source is a
--    loud stop, never a guess);
-- 3. sets vendor and kind NOT NULL;
-- 4. widens the primary key to (load_id, symbol, timeframe, "timestamp", vendor, kind), so one
--    load that restates two kinds of the same vendor at one timestamp records both.
--
-- ohlcv_revision is an ordinary table, not a hypertable, so no decompress/recompress and no
-- VACUUM is owed. request_id stays nullable: legacy revisions never had one.

SET lock_timeout = '30s';

BEGIN;

UPDATE ohlcv_revision r
   SET vendor = m.vendor, kind = m.kind
  FROM (VALUES
    ('ibkr_named', 'ibkr', 'named'),
    ('ibkr_venue', 'ibkr', 'venue'),
    ('ibkr_continuous_adj', 'ibkr', 'continuous'),
    ('ibkr_official', 'ibkr', 'official'),
    ('ibkr', 'ibkr', 'generic'),
    ('ibkr_fallback', 'ibkr', 'fallback'),
    ('tradier', 'tradier', 'consolidated'),
    ('alpaca', 'alpaca', 'sip_rth'),
    ('derived_5m', 'derived', '5m_grid')
  ) AS m (label, vendor, kind)
 WHERE r.old_source = m.label AND (r.vendor IS NULL OR r.kind IS NULL);

DO $$
DECLARE
    n_null bigint;
BEGIN
    SELECT count(*) INTO n_null FROM ohlcv_revision WHERE vendor IS NULL OR kind IS NULL;
    IF n_null > 0 THEN
        RAISE EXCEPTION 'ohlcv_revision still has % rows without vendor or kind (unmapped old_source)', n_null;
    END IF;
END $$;

ALTER TABLE ohlcv_revision ALTER COLUMN vendor SET NOT NULL, ALTER COLUMN kind SET NOT NULL;

ALTER TABLE ohlcv_revision DROP CONSTRAINT ohlcv_revision_pkey;
ALTER TABLE ohlcv_revision
    ADD CONSTRAINT ohlcv_revision_pkey
    PRIMARY KEY (load_id, symbol, timeframe, "timestamp", vendor, kind);

COMMIT;
