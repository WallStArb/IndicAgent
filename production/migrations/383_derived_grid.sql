-- Migration 383: D2b schema -- the intraday raw archive and the bar content digest
-- (phase 185 plan 11; D-02, D-07, D-15; 186 D-23/D-24 read what this creates).
--
-- Write method (from 185-01-MEASUREMENTS.md, methods c/d): segment_delete_copy.
-- The grid stage works one (symbol, 15m/1h) segment per transaction: archive the
-- stored rows, verify count and value checksums against the archive inside the
-- same transaction, DELETE the segment (synthetic placeholders included), then
-- reinsert the derived rows. Measured 90,575-111,180 rows/s with every chunk
-- left compressed (0 chunks decompressed: TimescaleDB 2.27.1 serves compressed
-- DML through the batch merge path), so the whole-universe rewrite in plan 12 is
-- minutes-scale with per-symbol transactions bounding blast radius. Native
-- upsert measured worst on disk (+16.6 MB vs +4.5 MB for a comparable segment)
-- and is not used here.
--
-- Role result (185-01 A7): a NOLOGIN role holding only table grants CAN run
-- DML against compressed chunks on this build (COPY insert plus a full-segment
-- DELETE under SET LOCAL ROLE succeeded in one transaction). So the grants on
-- market_data_ohlcv below are live, bar_derivation.py writes under
-- SET LOCAL ROLE bar_derivation_writer, and tests/unit/test_market_data_ohlcv_
-- writer_boundary.py (the single-writer CI guard created beside this migration)
-- is the second fence naming the only permanent 15m/1h/1d writer.
--
-- ohlcv_intraday_raw_archive is a hypertable with market_data_ohlcv's own
-- settings, read from timescaledb_information on 2026-09-28: chunk_time_interval
-- '3 months', compression segmentby (symbol, timeframe), orderby "timestamp"
-- ASC, policy compress_after '30 days'. No decompress_chunk anywhere in this
-- migration, so the compressed-hypertable migration VACUUM rule does not apply.
--
-- bar_content_digest is append-only with the rule version beside each digest:
-- a digest rewrite is a new row, never an UPDATE (T-185-11-04), and
-- bar_content_digest_current is the DISTINCT ON view phase 186's COPY primitive
-- reads. The digest algorithm itself lives in src/intelligence/bars/digest.py
-- (sha256-bars-v1); this table stores what it computes.

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. The intraday raw archive (D-15): stored IBKR 15m/1h rows become raw
--    observations here the moment the derived grid replaces them.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ohlcv_intraday_raw_archive (
    "timestamp" timestamptz NOT NULL,
    symbol text NOT NULL,
    timeframe text NOT NULL,
    open double precision NOT NULL,
    high double precision NOT NULL,
    low double precision NOT NULL,
    close double precision NOT NULL,
    volume bigint NOT NULL,
    source text,
    base text,
    price_sanity_status text,
    archived_at timestamptz NOT NULL DEFAULT now(),
    batch_id uuid REFERENCES bar_derivation_batch(batch_id),
    PRIMARY KEY ("timestamp", symbol, timeframe)
);

COMMENT ON TABLE ohlcv_intraday_raw_archive IS
    'Append-only archive of stored IBKR 15m/1h bars replaced by the derived grid '
    '(migration 383, D-15): the raw observations the derivation re-derives from 5m. '
    'Same columns as market_data_ohlcv plus archived_at and the replacing batch_id. '
    'Synthetic-fill placeholders are never archived (they are not observations). '
    'Permanent: UPDATE, DELETE and TRUNCATE raise.';

SELECT create_hypertable(
    'ohlcv_intraday_raw_archive',
    'timestamp',
    chunk_time_interval => INTERVAL '3 months',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_ohlcv_intraday_raw_archive_symbol_tf_time
    ON ohlcv_intraday_raw_archive (symbol, timeframe, "timestamp" DESC);

ALTER TABLE ohlcv_intraday_raw_archive SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol, timeframe',
    timescaledb.compress_orderby = '"timestamp" ASC'
);

SELECT add_compression_policy('ohlcv_intraday_raw_archive', INTERVAL '30 days', if_not_exists => TRUE);

-- ---------------------------------------------------------------------------
-- 2. The bar content digest (D-07): one append-only row per (symbol, tf,
--    calendar month) computation, with the rule version beside it.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS bar_content_digest (
    symbol text NOT NULL,
    timeframe text NOT NULL,
    range_start timestamptz NOT NULL,
    range_end timestamptz NOT NULL,
    digest text NOT NULL,
    algorithm text NOT NULL,
    rule_version text NOT NULL,
    n_rows integer NOT NULL CHECK (n_rows >= 0),
    batch_id uuid REFERENCES bar_derivation_batch(batch_id),
    computed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, timeframe, range_start, computed_at)
);

COMMENT ON TABLE bar_content_digest IS
    'Append-only bar content digests per (symbol, timeframe, calendar month) for '
    '5m, 15m and 1h (migration 383, D-07): sha256-bars-v1 over values plus flag '
    'state, computed by src/intelligence/bars/digest.py. The rule version sits '
    'beside the digest and is deliberately not an input to it. Phase 186 revision '
    'detection reads bar_content_digest_current, never this table directly. '
    'Permanent: UPDATE, DELETE and TRUNCATE raise.';

-- ---------------------------------------------------------------------------
-- 3. Append-only enforcement, one function per D1's shape (migration 380):
--    row UPDATE/DELETE plus statement TRUNCATE raise for every role.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION bar_derivation_append_only()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION '% is append-only: % is not allowed', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'check_violation';
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION bar_derivation_append_only() IS
    'Refuses UPDATE, DELETE (row triggers) and TRUNCATE (statement triggers) on '
    'ohlcv_intraday_raw_archive and bar_content_digest (migration 383): archived '
    'observations and recorded digests are permanent, a revision is a new row.';

DROP TRIGGER IF EXISTS trg_ohlcv_intraday_raw_archive_append_only ON ohlcv_intraday_raw_archive;
CREATE TRIGGER trg_ohlcv_intraday_raw_archive_append_only
    BEFORE UPDATE OR DELETE ON ohlcv_intraday_raw_archive
    FOR EACH ROW
    EXECUTE FUNCTION bar_derivation_append_only();

DROP TRIGGER IF EXISTS trg_ohlcv_intraday_raw_archive_no_truncate ON ohlcv_intraday_raw_archive;
CREATE TRIGGER trg_ohlcv_intraday_raw_archive_no_truncate
    BEFORE TRUNCATE ON ohlcv_intraday_raw_archive
    FOR EACH STATEMENT
    EXECUTE FUNCTION bar_derivation_append_only();

DROP TRIGGER IF EXISTS trg_bar_content_digest_append_only ON bar_content_digest;
CREATE TRIGGER trg_bar_content_digest_append_only
    BEFORE UPDATE OR DELETE ON bar_content_digest
    FOR EACH ROW
    EXECUTE FUNCTION bar_derivation_append_only();

DROP TRIGGER IF EXISTS trg_bar_content_digest_no_truncate ON bar_content_digest;
CREATE TRIGGER trg_bar_content_digest_no_truncate
    BEFORE TRUNCATE ON bar_content_digest
    FOR EACH STATEMENT
    EXECUTE FUNCTION bar_derivation_append_only();

-- ---------------------------------------------------------------------------
-- 4. The current view (D-07): latest computed digest per (symbol, tf, month).
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW bar_content_digest_current AS
SELECT DISTINCT ON (symbol, timeframe, range_start)
    symbol,
    timeframe,
    range_start,
    range_end,
    digest,
    algorithm,
    rule_version,
    n_rows,
    batch_id,
    computed_at
FROM bar_content_digest
ORDER BY symbol, timeframe, range_start, computed_at DESC;

COMMENT ON VIEW bar_content_digest_current IS
    'Latest bar_content_digest row per (symbol, timeframe, range_start): the '
    'revision-detection surface phase 186 consumes and bar_derivation --stage '
    'grid --changed-only compares against.';

-- ---------------------------------------------------------------------------
-- 5. Grants (185-01 A7: the NOLOGIN role CAN DML compressed chunks).
-- ---------------------------------------------------------------------------

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bar_derivation_writer') THEN
        CREATE ROLE bar_derivation_writer NOLOGIN;
    END IF;
END
$$;

GRANT INSERT, SELECT ON ohlcv_intraday_raw_archive, bar_content_digest TO bar_derivation_writer;
GRANT SELECT ON bar_content_digest_current TO bar_derivation_writer;
GRANT SELECT, INSERT, DELETE ON market_data_ohlcv TO bar_derivation_writer;

-- ---------------------------------------------------------------------------
-- 6. APR seeds (infra.bar_derivation.*).
-- ---------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
    (
        'infra.bar_derivation.grid_symbol_batch',
        'int',
        '10',
        '1', '10000',
        '[initial_estimate] Symbols per progress chunk in the D2b grid stage (phase 185 plan 11). Bounded to keep the per-symbol 5m arrays and the chunk progress log cadence small. Not an ML learning target.'
    ),
    (
        'infra.bar_derivation.grid_write_method',
        'text',
        'segment_delete_copy',
        NULL, NULL,
        '[rca_analysis] Write method the grid stage uses to replace a (symbol, 15m/1h) segment: segment_delete_copy (archive, verify, DELETE, reinsert in one transaction) per 185-01 measurements c/d; native upsert measured worse on disk and is not implemented. Changing this key does not switch code paths; it records the measured choice. Not an ML learning target.'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('infra.bar_derivation.grid_symbol_batch', '10', 1),
    ('infra.bar_derivation.grid_write_method', 'segment_delete_copy', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'infra.bar_derivation.grid_symbol_batch', 1, '10', 'migration_383', 'Initial value [initial_estimate]'),
    (NOW(), 'infra.bar_derivation.grid_write_method', 1, 'segment_delete_copy', 'migration_383', 'Initial value [rca_analysis]')
ON CONFLICT DO NOTHING;

COMMIT;
