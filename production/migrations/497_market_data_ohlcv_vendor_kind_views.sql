-- 497: swap the proven market_data_ohlcv_v2 into place as market_data_ohlcv (phase 191 plan 14).
--
-- Executed by scripts/ops/bars/ops_canonical_vendor_kind_swap.py --swap as a single unit inside
-- the swap transaction, after the ACCESS EXCLUSIVE locks on both tables, the lock_timeout and the
-- write-counter stability check; never applied by hand and never re-run. The two RENAME
-- statements are literal text at the top of this file so tests/unit/_migration_catalog.py (which
-- parses CREATE, DROP and ALTER RENAME in migration text only) resolves the final names: the live
-- table renames away first, then v2 takes the canonical name.
--
-- The old table is kept as market_data_ohlcv_old; plan 191-17 drops it after one nightly cycle.
-- The four dependent views are dropped and recreated over the new table (CREATE OR REPLACE cannot
-- change the column list source -> vendor, kind), in the order tradeable, scrub_input,
-- market_data_5m, canonical_bar_lineage; none of them reads another (checked with pg_depend at
-- execution time). ohlcv_venue_head is NOT touched here: plan 09 redefined it over ohlcv_raw.
--
-- Nothing in this file decompresses chunks (the 768 GB incident class,
-- docs/foundation/timescaledb-compressed-column-migration.md); the swap runbook's bare
-- VACUUM market_data_ohlcv closes the table swap.

ALTER TABLE market_data_ohlcv RENAME TO market_data_ohlcv_old;
ALTER TABLE market_data_ohlcv_v2 RENAME TO market_data_ohlcv;

-- Index names follow their tables: the outgoing table's take the _old names, the incoming's drop
-- the _rebuilt suffix migration 496 gave them.
ALTER INDEX market_data_ohlcv_pkey_idx RENAME TO market_data_ohlcv_old_pkey_idx;
ALTER INDEX idx_ohlcv_symbol_tf_time RENAME TO idx_ohlcv_old_symbol_tf_time;
ALTER INDEX market_data_ohlcv_pkey_idx_rebuilt RENAME TO market_data_ohlcv_pkey_idx;
ALTER INDEX idx_ohlcv_symbol_tf_time_rebuilt RENAME TO idx_ohlcv_symbol_tf_time;

COMMENT ON TABLE market_data_ohlcv IS 'vendor_kind_swap_497: canonical market_data_ohlcv, the proven rebuild (built as market_data_ohlcv_v2 by migration 496, plan 191-12; swapped in by plan 191-14). Volume is not consolidated for kind venue and fallback; readers null it through market_data_ohlcv_tradeable.';
COMMENT ON TABLE market_data_ohlcv_old IS 'vendor_kind_swap_497: the pre-swap label-column table (the real_rows_swap_439 rebuild before it), kept for one nightly cycle; dropped by plan 191-17.';

DROP VIEW market_data_ohlcv_tradeable;
DROP VIEW market_data_ohlcv_scrub_input;
DROP VIEW market_data_5m;
DROP VIEW canonical_bar_lineage;

-- Column order unchanged from migration 446's list: source in place is exchanged for vendor and
-- kind; volume nulling follows kind (venue and admitted 1d fallback are not consolidated).
CREATE VIEW market_data_ohlcv_tradeable AS
SELECT "timestamp", symbol, timeframe, open, high, low, close,
       CASE WHEN kind IN ('venue', 'fallback') THEN NULL::bigint ELSE volume END AS volume,
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
COMMENT ON VIEW market_data_ohlcv_tradeable IS 'Compute/measurement read boundary: traded bars (volume > 0), volume not consolidated nulled by kind (venue, fallback; recreated over vendor and kind by migration 497, 446 before it), quarantine-flagged bars (bar_quality_flag) excluded; price_sanity_status is no longer a visibility rule (migration 447, todo 500). Raw-table access outside this needs a test_market_data_ohlcv_boundary.py allow-list entry.';

CREATE VIEW market_data_ohlcv_scrub_input AS
SELECT "timestamp", symbol, timeframe, open, high, low, close, volume, vendor, kind
FROM market_data_ohlcv
WHERE volume > 0;
COMMENT ON VIEW market_data_ohlcv_scrub_input IS 'For the D2a scrub and D5 seam stages only: every traded bar (volume > 0, all vendors and kinds, quarantined bars included). Every other reader uses market_data_ohlcv_tradeable.';

CREATE VIEW market_data_5m AS
SELECT "timestamp", symbol, base, timeframe, open, high, low, close, volume, vendor, kind
FROM market_data_ohlcv
WHERE timeframe = '5m';

-- The plan 09 definition (migration 491) with m.vendor and m.kind in place of m.source: the raw
-- join key a canonical row matches is its own (vendor, kind) identity, spelled out per branch.
CREATE VIEW canonical_bar_lineage AS
SELECT m.symbol,
       m.timeframe,
       m."timestamp",
       d.rule_version,
       o.request_ids,
       d.batch_id,
       d.computed_at AS derived_at
FROM market_data_ohlcv m
LEFT JOIN (
    SELECT r.symbol, r."timestamp", r.vendor, r.kind,
           r.open, r.high, r.low, r.close, r.volume,
           ARRAY[r.request_id] AS request_ids
    FROM ohlcv_raw r
    JOIN ohlcv_request q ON q.request_id = r.request_id
    WHERE r.timeframe = '1d'
      AND ((r.vendor = 'tradier' AND r.kind = 'consolidated')
           OR (r.vendor = 'ibkr' AND r.kind = 'smart_trades'))
      AND q.caller !~~ 'test-%'
) o ON o.symbol = m.symbol
   AND o."timestamp" = m."timestamp"
   AND CASE
           WHEN m.vendor = 'tradier' AND m.kind = 'consolidated'
               THEN o.vendor = 'tradier' AND o.kind = 'consolidated'
           WHEN m.vendor = 'ibkr' AND m.kind IN ('named', 'fallback')
               THEN o.vendor = 'ibkr' AND o.kind = 'smart_trades'
           ELSE false
       END
   AND NOT o.open IS DISTINCT FROM m.open
   AND NOT o.high IS DISTINCT FROM m.high
   AND NOT o.low IS DISTINCT FROM m.low
   AND NOT o.close IS DISTINCT FROM m.close
   AND NOT o.volume IS DISTINCT FROM m.volume
LEFT JOIN LATERAL (
    SELECT c.rule_version, c.batch_id, c.computed_at
    FROM bar_content_digest c
    WHERE c.symbol = m.symbol
      AND c.timeframe = '1d'
      AND c.range_start <= m."timestamp"
      AND m."timestamp" < c.range_end
    ORDER BY c.range_start DESC, c.computed_at DESC
    LIMIT 1
) d ON true
WHERE m.timeframe = '1d';
COMMENT ON VIEW canonical_bar_lineage IS 'Lineage derived on read (migration 491, plan 191-09; 447 before; recreated over vendor and kind by 497, plan 191-14): per canonical 1d bar the request of the raw row with its key and the vendor and kind of its source (tradier consolidated; ibkr named and fallback: ibkr smart_trades) with equal OHLCV and a non-test caller, and the rule_version and batch of the bar''s month digest. NULL request_ids = lineage_missing. No writer can exist.';

-- The original grants ride with the recreated views; market_data_5m carries none (relacl empty
-- before the swap) and gains none.
GRANT SELECT ON market_data_ohlcv_tradeable, market_data_ohlcv_scrub_input, canonical_bar_lineage TO bar_derivation_writer;

-- The compression policy moves with the name: the outgoing table's job is unscheduled, the
-- incoming gets the same compress_after and schedule_interval it had.
DO $$
DECLARE
    outgoing_job integer;
    outgoing_after interval;
    outgoing_schedule interval;
BEGIN
    SELECT job_id, (config->>'compress_after')::interval, schedule_interval
      INTO outgoing_job, outgoing_after, outgoing_schedule
    FROM timescaledb_information.jobs
    WHERE proc_name = 'policy_compression'
      AND hypertable_schema = 'public' AND hypertable_name = 'market_data_ohlcv_old'
    ORDER BY job_id
    LIMIT 1;
    IF outgoing_after IS NULL OR outgoing_schedule IS NULL THEN
        RAISE EXCEPTION 'no compression policy found on market_data_ohlcv_old to move';
    END IF;
    PERFORM alter_job(outgoing_job, scheduled => false);
    IF NOT EXISTS (
        SELECT 1 FROM timescaledb_information.jobs
        WHERE proc_name = 'policy_compression'
          AND hypertable_schema = 'public' AND hypertable_name = 'market_data_ohlcv'
    ) THEN
        PERFORM add_compression_policy(
            'public.market_data_ohlcv'::regclass,
            compress_after => outgoing_after,
            schedule_interval => outgoing_schedule
        );
    END IF;
END $$;
