-- 588: canonical_bar_lineage follows canonical 1d bars the daily rule serves from Massive (todo
-- 600, todo 608 before step 7; rule d2-v6, commit 97671ac77).
--
-- d2-v6 serves a Massive primary's day bar as (massive, sip_flat_adj) from raw (massive,
-- sip_flat), served unadjusted and stamped at midnight New York (window_start). Its prices are
-- divided, and its volume multiplied and rounded floor(x + 0.5), by the product of the factors of
-- every market split dated on or after the bar (corporate_actions.is_market_split: every current
-- split row except a calendar_audit row written from a todo 592 operator rows file, which corrects
-- one incumbent route and never the market's split), folded in effective-date order, the order
-- of daily_rule.split_scale. Without this migration every Massive canonical bar would read
-- lineage_missing.
--
-- Three changes to migration 568's view, nothing else:
--   1. the source map gains (massive, sip_flat_adj) -> raw (massive, sip_flat);
--   2. the scale lateral takes the market-split product for the Massive pair and keeps 568's
--      calendar_audit route product for every other pair (so every existing row matches as
--      before);
--   3. the load-keyed raw branch (Alpaca's: the raw row's ohlcv_load with a non-test caller, on
--      the New York session date) also reads (massive, sip_flat).
-- Same columns, order and grant. A view only: no bar row is read for writing or written; no
-- compressed hypertable is touched (no VACUUM owed).
--
-- Rollback: re-run migration 568's CREATE OR REPLACE VIEW and its COMMENT.

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
-- The raw series behind each canonical (vendor, kind); any other pair matches nothing.
LEFT JOIN (VALUES ('tradier', 'consolidated', 'tradier', 'consolidated'),
                  ('ibkr', 'named', 'ibkr', 'smart_trades'),
                  ('ibkr', 'fallback', 'ibkr', 'smart_trades'),
                  ('alpaca', 'sip_rth', 'alpaca', 'sip_rth'),
                  ('massive', 'sip_flat_adj', 'massive', 'sip_flat'))
    AS src(vendor, kind, raw_vendor, raw_kind)
  ON src.vendor = m.vendor AND src.kind = m.kind
CROSS JOIN LATERAL (
    SELECT COALESCE(split_factor_product(c.factor ORDER BY c.effective_date), 1::float8) AS scale
    FROM corporate_action_current c
    WHERE c.symbol = m.symbol
      AND c.action_type IN ('split', 'reverse_split')
      AND (m."timestamp" AT TIME ZONE 'UTC')::date <= c.effective_date
      AND CASE
          -- d2-v6: the unadjusted Massive series is divided by every market split
          -- (corporate_actions.is_market_split: all but an incumbent route correction).
          WHEN src.raw_vendor = 'massive'
          THEN NOT (c.inferred_by = 'calendar_audit' AND c.detail ? 'rows_file')
          -- d2-v5: an incumbent series by the calendar_audit splits naming it.
          ELSE c.inferred_by = 'calendar_audit'
               AND c.detail->'unadjusted_routes'
                   @> jsonb_build_array(jsonb_build_object('vendor', src.raw_vendor,
                                                           'kind', src.raw_kind))
      END
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
      AND ((r.vendor = 'alpaca' AND r.kind = 'sip_rth')
           OR (r.vendor = 'massive' AND r.kind = 'sip_flat'))
      AND l.caller NOT LIKE 'test-%'
) o ON o.symbol = m.symbol
   AND o.session_ts = m."timestamp"
   AND o.vendor = src.raw_vendor
   AND o.kind = src.raw_kind
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

COMMENT ON VIEW canonical_bar_lineage IS 'Lineage derived on read (migration 588; 568, 537, 491, 447 before): per canonical 1d bar the request of the raw row with its key and the vendor and kind of its source (tradier consolidated and ibkr named/fallback: the raw row''s ohlcv_request with a non-test caller; alpaca sip_rth and massive sip_flat: the raw row''s ohlcv_load with a non-test caller, on the New York session date) with equal OHLCV after dividing by the split product over the bar''s span: for massive sip_flat_adj every market split (all current split rows except a calendar_audit row from a todo 592 operator rows file; d2-v6, todo 600), for every other pair the calendar_audit splits whose unadjusted_routes name the bar''s raw series (d2-v5, todo 587); 1 when none applies; and the rule_version and batch of the bar''s month digest. NULL request_ids = lineage_missing. No writer can exist.';

GRANT SELECT ON canonical_bar_lineage TO bar_derivation_writer;

COMMIT;
