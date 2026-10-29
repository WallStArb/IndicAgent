-- 537: canonical_bar_lineage follows canonical 1d bars sourced from Alpaca SIP (todo 545,
-- D-191-Q). The 2026-10-28 plan 191-20 D7 run failed lineage_missing for 1,501 of 1,502 names.
--
-- Migration 491 mapped only tradier consolidated and ibkr named/fallback bars to a raw request;
-- an alpaca sip_rth bar fell to ELSE false and returned NULL request_ids. Extending that branch
-- alone does not help: the Alpaca 1d history (loaded 2026-10-27 by alpaca-nightly-1d-raw) has
-- raw.request_id values with no ohlcv_request row, and its provenance is the ohlcv_load row named
-- by raw.load_id. So an alpaca sip_rth bar now joins the alpaca sip_rth raw row with its session
-- and equal OHLCV, and counts as traced when that raw row's ohlcv_load row exists with a non-test
-- caller; request_ids then carries the raw row's own request_id (the request that served the
-- value, whether or not a request row was kept). The tradier and ibkr branches are unchanged.
-- Alpaca stamps a 1d bar at the New York session open (04:00 or 05:00 UTC) while canonical sits
-- at 00:00 UTC (daily_rule.py RAW_DAILY_SESSION_ZONE), so the raw subselect carries a session_ts:
-- the New York session date at 00:00 UTC for alpaca, the raw stamp for the others. Same columns,
-- order and grant as 491.
--
-- Rollback: re-run the CREATE OR REPLACE VIEW of migration 491 with the live vendor and kind
-- column names (m.vendor, m.kind) and without the alpaca branches.

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
    SELECT r.symbol, r."timestamp" AS session_ts, r.vendor, r.kind,
           r.open, r.high, r.low, r.close, r.volume,
           ARRAY[r.request_id] AS request_ids
    FROM ohlcv_raw r
    JOIN ohlcv_request q ON q.request_id = r.request_id
    WHERE r.timeframe = '1d'
      AND ((r.vendor = 'tradier' AND r.kind = 'consolidated')
           OR (r.vendor = 'ibkr' AND r.kind = 'smart_trades'))
      AND q.caller NOT LIKE 'test-%'
    UNION ALL
    SELECT r.symbol,
           ((r."timestamp" AT TIME ZONE 'America/New_York')::date)::timestamp AT TIME ZONE 'UTC',
           r.vendor, r.kind, r.open, r.high, r.low, r.close, r.volume,
           ARRAY[r.request_id]
    FROM ohlcv_raw r
    JOIN ohlcv_load l ON l.load_id = r.load_id
    WHERE r.timeframe = '1d'
      AND r.vendor = 'alpaca' AND r.kind = 'sip_rth'
      AND l.caller NOT LIKE 'test-%'
) o ON o.symbol = m.symbol
   AND o.session_ts = m."timestamp"
   AND CASE
           WHEN m.vendor = 'tradier' AND m.kind = 'consolidated'
               THEN o.vendor = 'tradier' AND o.kind = 'consolidated'
           WHEN m.vendor = 'ibkr' AND m.kind IN ('named', 'fallback')
               THEN o.vendor = 'ibkr' AND o.kind = 'smart_trades'
           WHEN m.vendor = 'alpaca' AND m.kind = 'sip_rth'
               THEN o.vendor = 'alpaca' AND o.kind = 'sip_rth'
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

COMMENT ON VIEW canonical_bar_lineage IS 'Lineage derived on read (migration 537; 491, 447 before): per canonical 1d bar the request of the raw row with its key and the vendor and kind of its source (tradier consolidated and ibkr named/fallback: the raw row''s ohlcv_request with a non-test caller; alpaca sip_rth: the raw row''s ohlcv_load with a non-test caller, on the New York session date) with equal OHLCV, and the rule_version and batch of the bar''s month digest. NULL request_ids = lineage_missing. No writer can exist.';

GRANT SELECT ON canonical_bar_lineage TO bar_derivation_writer;

COMMIT;
