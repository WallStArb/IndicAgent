-- 448: ingress write contract (plan 185-39).
--
-- Data layer integrity design (docs/plans/2026-10-06-data-layer-integrity-design.md) sections 3
-- and 4. Three changes:
--
-- 1. ohlcv_request.content_digest: the content digest of the answer a chunk stored (direct
--    ingress mode provenance for 5m and 1m: the stored row is the raw answer, this is the
--    record of which answer). NULL on a request that stored nothing. A plain nullable column on
--    a small uncompressed table; no hypertable column is touched.
-- 2. The archive accepts UPDATE of a changed row (the latest answer wins and the old values go
--    to ohlcv_revision) and still refuses DELETE. The append-only row trigger (UPDATE or
--    DELETE) is replaced by one that refuses DELETE only; the TRUNCATE trigger stays.
-- 3. UPDATE on the archive for bar_derivation_writer, the role the persist helper writes under.
--
-- Number: 448 is free (449 landed first; 450 to 452 are claimed by plans 185-40, 189-10 and
-- 185-43). Idempotent. No compressed column type changes, so no VACUUM is owed.

SET lock_timeout = '10s';

BEGIN;

ALTER TABLE ohlcv_request ADD COLUMN IF NOT EXISTS content_digest text;
ALTER TABLE ohlcv_request DROP CONSTRAINT IF EXISTS ohlcv_request_content_digest_check;
ALTER TABLE ohlcv_request
    ADD CONSTRAINT ohlcv_request_content_digest_check
    CHECK (content_digest IS NULL OR content_digest ~ '^[0-9a-f]{64}$');
COMMENT ON COLUMN ohlcv_request.content_digest IS
    'sha256-bars-v1 digest (src/intelligence/bars/digest.py) of the rows the request''s chunk '
    'stored; NULL when the request stored nothing (plan 185-39, design section 3).';

CREATE OR REPLACE FUNCTION ohlcv_archive_no_delete()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION '% refuses % (an archived observation is replaced, never removed)',
        TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'check_violation';
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION ohlcv_archive_no_delete() IS
    'Refuses DELETE on ohlcv_intraday_raw_archive (migration 448). UPDATE is allowed: the '
    'ingress write contract rewrites a changed row and records its old values in ohlcv_revision.';

DROP TRIGGER IF EXISTS trg_ohlcv_intraday_raw_archive_append_only ON ohlcv_intraday_raw_archive;
DROP TRIGGER IF EXISTS trg_ohlcv_intraday_raw_archive_no_delete ON ohlcv_intraday_raw_archive;
CREATE TRIGGER trg_ohlcv_intraday_raw_archive_no_delete
    BEFORE DELETE ON ohlcv_intraday_raw_archive
    FOR EACH ROW
    EXECUTE FUNCTION ohlcv_archive_no_delete();

GRANT UPDATE ON ohlcv_intraday_raw_archive TO bar_derivation_writer;

COMMIT;
