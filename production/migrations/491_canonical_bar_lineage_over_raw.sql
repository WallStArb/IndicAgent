-- 491: canonical_bar_lineage reads ohlcv_raw, not ohlcv_observation (phase 191 plan 191-09
-- Task 1; docs/plans/2026-10-12-unified-raw-bar-table-design.md step 6).
--
-- Same columns, names and grant as migration 447. Per canonical 1d bar the view returns the
-- request of the raw row with the bar's key and the vendor and kind its source names, when that
-- row's OHLCV equals the bar exactly (IS NOT DISTINCT FROM): tradier -> tradier consolidated;
-- ibkr_named and ibkr_fallback -> ibkr smart_trades (the LEGACY_IMPORT corpus rows were loaded
-- into smart_trades by their source, vendor_kind.observation_kind); any other source returns NULL,
-- as in 447 (no canonical 1d row has another source). Raw keeps one current row
-- per key (D-191-N, last-wins) and an unchanged re-serve writes nothing, so the id is the request
-- that first served the current value, where 447 returned the latest equal observation. Callers
-- 'test-%' never count; a raw row with no ohlcv_request row returns NULL. A canonical bar whose
-- value is not raw's current value (canonical behind a restatement) returns NULL: the integrity
-- report's lineage_missing, which is the signal that the daily stage owes a re-derivation.
-- A set join, not a LATERAL probe: a per-bar probe into the compressed raw hypertable cannot
-- exclude chunks at plan time (measured 13 s for AAPL's 6,734 bars, about 4 hours for the view).
-- (vendor, kind) is fixed per source and the raw key is unique, so a bar joins at most one row.
--
-- Rollback: re-run the CREATE OR REPLACE VIEW of migration 447 (same column list).

BEGIN;

CREATE OR REPLACE VIEW canonical_bar_lineage AS
SELECT m.symbol,
       m.timeframe,
       m."timestamp",
       d.rule_version,
       o.request_ids,
       d.batch_id,
       d.computed_at AS derived_at
FROM market_data_ohlcv m
LEFT JOIN (
    SELECT r.symbol, r."timestamp", r.vendor, r.kind, r.open, r.high, r.low, r.close, r.volume,
           ARRAY[r.request_id] AS request_ids
    FROM ohlcv_raw r
    JOIN ohlcv_request q ON q.request_id = r.request_id
    WHERE r.timeframe = '1d'
      AND ((r.vendor = 'tradier' AND r.kind = 'consolidated')
           OR (r.vendor = 'ibkr' AND r.kind = 'smart_trades'))
      AND q.caller NOT LIKE 'test-%'
) o ON o.symbol = m.symbol
   AND o."timestamp" = m."timestamp"
   AND CASE
           WHEN m.source = 'tradier' THEN o.vendor = 'tradier' AND o.kind = 'consolidated'
           WHEN m.source IN ('ibkr_named', 'ibkr_fallback') THEN o.vendor = 'ibkr' AND o.kind = 'smart_trades'
           ELSE false
       END
   AND o.open IS NOT DISTINCT FROM m.open
   AND o.high IS NOT DISTINCT FROM m.high
   AND o.low IS NOT DISTINCT FROM m.low
   AND o.close IS NOT DISTINCT FROM m.close
   AND o.volume IS NOT DISTINCT FROM m.volume
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

COMMENT ON VIEW canonical_bar_lineage IS 'Lineage derived on read (migration 491, plan 191-09; 447 before): per canonical 1d bar the request of the raw row with its key and the vendor and kind of its source (tradier: tradier consolidated; ibkr_named, ibkr_fallback: ibkr smart_trades) with equal OHLCV and a non-test caller, and the rule_version and batch of the bar''s month digest. NULL request_ids = lineage_missing. No writer can exist.';

GRANT SELECT ON canonical_bar_lineage TO bar_derivation_writer;

COMMIT;
