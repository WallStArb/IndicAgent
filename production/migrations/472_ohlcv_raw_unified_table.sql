-- Migration 472: ohlcv_raw, the unified raw bar table (phase 191 plan 01)
--
-- Schema half of step 3 of docs/plans/2026-10-12-unified-raw-bar-table-design.md (todo 533).
-- Additive only: a new table, nullable columns, dropped CHECKs. It applies while the IBKR history
-- fetcher keeps running, because nothing the fetcher writes breaks (its ohlcv_revision inserts
-- omit the new nullable columns; ohlcv_load keeps accepting every value it accepted).
--
-- 1. ohlcv_raw: one row per (timestamp, symbol, timeframe, vendor, kind), last-wins. served_at,
--    request_id and load_id are nullable only for rows migrated from stores that never captured
--    them; no dummy ids and no now() stamps. No CHECK on vendor or kind: the writer validates
--    against the CVR namespaces below, so a new vendor needs no migration. Compression is
--    enabled with no policy; plan 03 adds the policy after the backfill.
-- 2. CVR namespaces bar_vendor and bar_kind (codes from src/intelligence/bars/vendor_kind.py).
-- 3. ohlcv_revision gains vendor, kind, request_id (all nullable until plan 04 widens the key
--    and sets NOT NULL) and its origin check admits 'raw'. Existing rows get vendor and kind from
--    old_source through the same label map as vendor_kind.LABEL_TO_VENDOR_KIND.
-- 4. ohlcv_load: source check dropped (the writer validates against CVR), destination admits raw.
-- 5. bar_source_policy: the single-column CHECKs on primary_source and fallback_source are
--    dropped (looked up by column, their names are generated); the distinctness and
--    derived-mode CHECKs stay.
--
-- No decompress/compress of an existing hypertable, so the bare-VACUUM rule does not apply.
-- Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS ohlcv_raw (
    "timestamp" timestamptz NOT NULL,
    symbol text NOT NULL REFERENCES instruments(symbol),
    timeframe text NOT NULL,
    vendor text NOT NULL,
    kind text NOT NULL,
    open double precision NOT NULL,
    high double precision NOT NULL,
    low double precision NOT NULL,
    close double precision NOT NULL,
    volume bigint,
    served_at timestamptz,
    request_id uuid,
    load_id uuid,
    PRIMARY KEY ("timestamp", symbol, timeframe, vendor, kind),
    CONSTRAINT ohlcv_raw_finite CHECK (
        open <> 'NaN'::double precision AND open <> 'Infinity'::double precision
        AND open <> '-Infinity'::double precision
        AND high <> 'NaN'::double precision AND high <> 'Infinity'::double precision
        AND high <> '-Infinity'::double precision
        AND low <> 'NaN'::double precision AND low <> 'Infinity'::double precision
        AND low <> '-Infinity'::double precision
        AND close <> 'NaN'::double precision AND close <> 'Infinity'::double precision
        AND close <> '-Infinity'::double precision
    )
);

SELECT create_hypertable('ohlcv_raw', 'timestamp',
                         chunk_time_interval => INTERVAL '30 days', if_not_exists => TRUE);

ALTER TABLE ohlcv_raw SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol, timeframe, vendor',
    timescaledb.compress_orderby = '"timestamp" ASC'
);

CREATE INDEX IF NOT EXISTS idx_ohlcv_raw_symbol_tf_ts
    ON ohlcv_raw (symbol, timeframe, "timestamp" DESC);

COMMENT ON TABLE ohlcv_raw IS
    'The one table of vendor answers (migration 472, phase 191): every bar a vendor served, at '
    'the timeframe it served, keyed by (vendor, kind), last-wins. Canonical market_data_ohlcv is '
    'a selection from here by bar_source_policy. A vendor changing its own answer is logged in '
    'ohlcv_revision; two vendors differing on a slot is a disagreement resolved by selection. '
    'No CHECK on vendor or kind: the writer validates against CVR bar_vendor and bar_kind.';
COMMENT ON COLUMN ohlcv_raw.served_at IS
    'When this value was first served; nullable only for rows migrated from stores that never '
    'captured it. No dummy ids and no now() stamps are allowed.';
COMMENT ON COLUMN ohlcv_raw.request_id IS
    'The ohlcv_request that first served this value; nullable only for migrated rows and '
    'loader-written rows. No dummy ids allowed.';
COMMENT ON COLUMN ohlcv_raw.load_id IS
    'The ohlcv_load write that set the row; nullable only for migrated rows that never had one. '
    'No dummy ids allowed.';

GRANT INSERT, SELECT, UPDATE ON ohlcv_raw TO bar_derivation_writer;

INSERT INTO controlled_vocabulary (namespace, code, label, description, sort_order)
VALUES
    ('bar_vendor', 'ibkr', 'Interactive Brokers', 'IBKR history and streaming bars', 1),
    ('bar_vendor', 'alpaca', 'Alpaca', 'Alpaca SIP aggregates (5m depth source)', 2),
    ('bar_vendor', 'tradier', 'Tradier', 'Tradier daily bars (stored history only; account unfunded, not fetched)', 3),
    ('bar_vendor', 'derived', 'Derived', 'Bars computed by the grid derivation from 5m, never served by a vendor', 4),
    ('bar_kind', 'named', 'named', 'IBKR named-contract direct fetch', 1),
    ('bar_kind', 'venue', 'venue', 'IBKR listing-venue route fetch (volume is not consolidated)', 2),
    ('bar_kind', 'continuous', 'continuous', 'IBKR continuous back-adjusted fetch', 3),
    ('bar_kind', 'official', 'official', 'IBKR official bars from TWS reconciliation', 4),
    ('bar_kind', 'generic', 'generic', 'IBKR generic fetch (real-time bars or fallback path)', 5),
    ('bar_kind', 'smart_trades', 'smart_trades', 'IBKR SMART-routed TRADES daily answer', 6),
    ('bar_kind', 'smart_adjusted', 'smart_adjusted', 'IBKR SMART-routed ADJUSTED_LAST daily answer (never canonical)', 7),
    ('bar_kind', 'fallback', 'fallback', 'IBKR 1d bar admitted by the daily rule where the primary has none (canonical only)', 8),
    ('bar_kind', 'consolidated', 'consolidated', 'Tradier consolidated-volume bar', 9),
    ('bar_kind', 'sip_rth', 'sip_rth', 'Alpaca SIP aggregate over the regular trading hours window', 10),
    ('bar_kind', '5m_grid', '5m_grid', '15m or 1h bar derived from 5m on the session-anchored grid', 11)
ON CONFLICT (namespace, code) DO NOTHING;

ALTER TABLE ohlcv_revision ADD COLUMN IF NOT EXISTS vendor text;
ALTER TABLE ohlcv_revision ADD COLUMN IF NOT EXISTS kind text;
ALTER TABLE ohlcv_revision ADD COLUMN IF NOT EXISTS request_id uuid;

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
 WHERE r.old_source = m.label AND r.vendor IS NULL;

ALTER TABLE ohlcv_revision DROP CONSTRAINT IF EXISTS ohlcv_revision_origin_check;
ALTER TABLE ohlcv_revision
    ADD CONSTRAINT ohlcv_revision_origin_check
    CHECK (origin IN ('load', 'archive_segment', 'raw'));

ALTER TABLE ohlcv_load DROP CONSTRAINT IF EXISTS ohlcv_load_source_check;
ALTER TABLE ohlcv_load DROP CONSTRAINT IF EXISTS ohlcv_load_destination_check;
ALTER TABLE ohlcv_load
    ADD CONSTRAINT ohlcv_load_destination_check
    CHECK (destination IN ('d1', 'market_data_ohlcv', 'archive', 'raw'));

DO $$
DECLARE
    c record;
BEGIN
    FOR c IN
        SELECT con.conname
          FROM pg_constraint con
          JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = con.conkey[1]
         WHERE con.conrelid = 'bar_source_policy'::regclass
           AND con.contype = 'c'
           AND array_length(con.conkey, 1) = 1
           AND a.attname IN ('primary_source', 'fallback_source')
    LOOP
        EXECUTE format('ALTER TABLE bar_source_policy DROP CONSTRAINT %I', c.conname);
    END LOOP;
END $$;

COMMIT;
