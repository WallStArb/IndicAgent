-- 447: canonical_bar_lineage becomes a view derived on read; the tradeable view loses its
-- price_sanity_status predicate (phase 185 plan 185-38 Task 2; data layer integrity design
-- section 4, docs/plans/2026-10-06-data-layer-integrity-design.md).
--
-- Lineage cannot drift: for each canonical 1d bar in market_data_ohlcv the view returns the
-- latest non-test D1 observation of the bar's source route with equal open, high, low, close and
-- volume (IS NOT DISTINCT FROM). Routes: tradier -> TRADIER; ibkr_named and ibkr_fallback ->
-- SMART, then the LEGACY_IMPORT copy of the stored corpus as the lower rank (d2-v2 reads it the
-- same way; DAL's 2007 heads exist only there). TRADES only; callers 'test-%' never count.
-- rule_version, batch_id and derived_at come from the bar's month in bar_content_digest (the
-- latest row, as bar_content_digest_current). A bar with no equal observation, or of any other
-- source, returns NULL request_ids: the integrity report's lineage_missing (zero tolerance on
-- visible bars). The columns and their names are the dropped table's. No index is added:
-- idx_ohlcv_observation_symbol_date (symbol, bar_date, route, what_to_show, fetched_at DESC)
-- serves the lookup and bar_content_digest_pkey the month.
--
-- todo 500: market_data_ohlcv_tradeable stops filtering on price_sanity_status. The column has
-- no writer since 185-18; the only confirmed_corrupt rows without a quarantine flag on
-- 2026-10-07 were todo 500's ten clean Tradier bars (DBC, FXI, FXY, GLD, IWM, RSP, SPY, VWO
-- twice, XRT), which this makes visible. bar_quality_flag quarantine is the one visibility rule;
-- 185-43 drops the column.
--
-- Rollback: the table's rows are dumped before this runs (pg_dump -Fc -t canonical_bar_lineage
-- to data/backups/185-38/canonical_bar_lineage_<UTC date>.dump, kept 30 days; 185-43 deletes it).
-- Restore = DROP VIEW canonical_bar_lineage, then pg_restore the dump (table, pk, check, FK,
-- grants), and re-run migration 446's tradeable view.

BEGIN;

DROP TABLE canonical_bar_lineage;

CREATE VIEW canonical_bar_lineage AS
SELECT m.symbol,
       m.timeframe,
       m."timestamp",
       d.rule_version,
       o.request_ids,
       d.batch_id,
       d.computed_at AS derived_at
FROM market_data_ohlcv m
LEFT JOIN LATERAL (
    SELECT ARRAY[ob.request_id] AS request_ids
    FROM ohlcv_observation ob
    JOIN ohlcv_request q ON q.request_id = ob.request_id
    WHERE ob.symbol = m.symbol
      AND ob.timeframe = '1d'
      AND ob.bar_date = (m."timestamp" AT TIME ZONE 'UTC')::date
      AND ob.what_to_show = 'TRADES'
      AND ob.route = ANY (
          CASE
              WHEN m.source = 'tradier' THEN ARRAY['TRADIER']
              WHEN m.source IN ('ibkr_named', 'ibkr_fallback') THEN ARRAY['SMART', 'LEGACY_IMPORT']
          END
      )
      AND q.caller NOT LIKE 'test-%'
      AND ob.open IS NOT DISTINCT FROM m.open
      AND ob.high IS NOT DISTINCT FROM m.high
      AND ob.low IS NOT DISTINCT FROM m.low
      AND ob.close IS NOT DISTINCT FROM m.close
      AND ob.volume IS NOT DISTINCT FROM m.volume
    ORDER BY (ob.route = 'LEGACY_IMPORT'), ob.fetched_at DESC, ob.request_id DESC
    LIMIT 1
) o ON true
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

COMMENT ON VIEW canonical_bar_lineage IS 'Lineage derived on read (migration 447, plan 185-38): per canonical 1d bar the latest non-test TRADES observation of its source route (tradier: TRADIER; ibkr_named, ibkr_fallback: SMART then LEGACY_IMPORT) with equal OHLCV, and the rule_version and batch of the bar''s month digest. NULL request_ids = lineage_missing. No writer can exist.';

GRANT SELECT ON canonical_bar_lineage TO bar_derivation_writer;

CREATE OR REPLACE VIEW market_data_ohlcv_tradeable AS
SELECT "timestamp",
       symbol,
       timeframe,
       open,
       high,
       low,
       close,
       CASE WHEN source IN ('ibkr_venue', 'ibkr_fallback') THEN NULL ELSE volume END AS volume,
       source,
       base,
       price_sanity_status
FROM market_data_ohlcv
WHERE volume > 0
  AND NOT EXISTS (
      SELECT 1 FROM bar_quality_flag q
      WHERE q.quarantine
        AND q.symbol = market_data_ohlcv.symbol
        AND q.timeframe = market_data_ohlcv.timeframe
        AND q."timestamp" = market_data_ohlcv."timestamp"
  );

COMMENT ON VIEW market_data_ohlcv_tradeable IS 'Compute/measurement read boundary: traded bars (volume > 0), venue and admitted 1d fallback volume nulled (ibkr_venue, ibkr_fallback; migration 446), quarantine-flagged bars (bar_quality_flag) excluded; price_sanity_status is no longer a visibility rule (migration 447, todo 500). Raw-table access outside this needs a test_market_data_ohlcv_boundary.py allow-list entry.';

COMMIT;
