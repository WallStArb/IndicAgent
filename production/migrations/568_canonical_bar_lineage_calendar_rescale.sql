-- 568: canonical_bar_lineage follows canonical 1d bars the daily rule rescales for a calendar_audit
-- split (todo 587, rule d2-v5).
--
-- d2-v5 divides the prices of an observation dated on or before a calendar_audit split's
-- effective_date (the last day on the old scale), on the split's recorded unadjusted span, by the
-- product of those splits' factors multiplied in effective-date order, and multiplies its volume,
-- rounded floor(x + 0.5). Migration 537 matched canonical to raw by equality, so every rescaled bar
-- would read lineage_missing. The view now divides the raw row by the same product before the
-- equality: split_factor_product is float8mul folded in ORDER BY effective_date, the same sequence
-- of IEEE multiplications as daily_rule.split_scale, and one division, so the match stays exact
-- (a dry run over five names matched 1,834 of 1,834 rescaled bars). A bar with no such split has
-- product 1, and x / 1 and floor(v * 1 + 0.5) are x and v: every other row matches exactly as in
-- 537. Same columns, order and grant.
--
-- Rollback: re-run migration 537's CREATE OR REPLACE VIEW, then DROP AGGREGATE
-- split_factor_product(float8).

BEGIN;

CREATE OR REPLACE AGGREGATE split_factor_product(float8) (
    SFUNC = float8mul,
    STYPE = float8,
    INITCOND = '1'
);

COMMENT ON AGGREGATE split_factor_product(float8) IS 'Product of split factors, folded in the caller''s ORDER BY (migration 568, todo 587): use with ORDER BY effective_date to reproduce daily_rule.split_scale bit for bit.';

CREATE OR REPLACE VIEW canonical_bar_lineage AS
SELECT m.symbol,
       m.timeframe,
       m."timestamp",
       d.rule_version,
       o.request_ids,
       d.batch_id,
       d.computed_at AS derived_at
FROM market_data_ohlcv m
CROSS JOIN LATERAL (
    SELECT COALESCE(split_factor_product(c.factor ORDER BY c.effective_date), 1::float8) AS scale
    FROM corporate_action_current c
    WHERE c.symbol = m.symbol
      AND c.inferred_by = 'calendar_audit'
      AND c.action_type IN ('split', 'reverse_split')
      AND m."timestamp"::date <= c.effective_date
      AND c.detail->'unadjusted_span'->>'vendor' = m.vendor
) s
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
   AND o.open / s.scale IS NOT DISTINCT FROM m.open
   AND o.high / s.scale IS NOT DISTINCT FROM m.high
   AND o.low / s.scale IS NOT DISTINCT FROM m.low
   AND o.close / s.scale IS NOT DISTINCT FROM m.close
   AND floor(o.volume * s.scale + 0.5)::bigint IS NOT DISTINCT FROM m.volume
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

COMMENT ON VIEW canonical_bar_lineage IS 'Lineage derived on read (migration 568; 537, 491, 447 before): per canonical 1d bar the request of the raw row with its key and the vendor and kind of its source (tradier consolidated and ibkr named/fallback: the raw row''s ohlcv_request with a non-test caller; alpaca sip_rth: the raw row''s ohlcv_load with a non-test caller, on the New York session date) with equal OHLCV after dividing by the product of the calendar_audit split factors over the bar''s span (1 for every other bar; d2-v5, todo 587), and the rule_version and batch of the bar''s month digest. NULL request_ids = lineage_missing. No writer can exist.';

COMMIT;
