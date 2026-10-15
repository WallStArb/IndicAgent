-- 492: ohlcv_venue_head reads ohlcv_raw, not ohlcv_observation (phase 191 plan 191-09 Task 2;
-- docs/plans/2026-10-12-unified-raw-bar-table-design.md step 6).
--
-- Same column list, order and meaning as migration 442, so CREATE OR REPLACE keeps the readers
-- (label_inputs, ops_data_bar_check, listing_venue_writer, ops_head_rerun, D7) unchanged.
-- A former IBKR listing-venue route is its own raw kind venue_<route lower case> (migration 476),
-- so route = upper(substr(kind, 7)). The SMART head is the earliest ibkr smart_trades 1d row a
-- SMART request served: the stored corpus's LEGACY_IMPORT rows were loaded into smart_trades by
-- their source and carry no route evidence, so they are excluded through ohlcv_request.route,
-- exactly as 442 excluded route LEGACY_IMPORT. Tradier is vendor tradier and never a venue kind.
-- n_bars counts raw rows (one per bar date); 442 counted observation rows, so a date answered by
-- several fetches counted more than once there. No reader uses n_bars.
-- View change only, no data change. Idempotent.
--
-- Rollback: re-run migration 442.

BEGIN;

CREATE OR REPLACE VIEW ohlcv_venue_head AS
WITH smart_head AS (
    SELECT r.symbol, min((r."timestamp" AT TIME ZONE 'UTC')::date) AS smart_head_date
    FROM ohlcv_raw r
    JOIN ohlcv_request q ON q.request_id = r.request_id
    WHERE r.timeframe = '1d' AND r.vendor = 'ibkr' AND r.kind = 'smart_trades'
      AND q.route = 'SMART'
    GROUP BY r.symbol
)
SELECT
    v.symbol,
    upper(substr(v.kind, 7)) AS route,
    min((v."timestamp" AT TIME ZONE 'UTC')::date) AS first_bar_date,
    max((v."timestamp" AT TIME ZONE 'UTC')::date) AS last_bar_date,
    count(*) AS n_bars,
    sh.smart_head_date,
    (max((v."timestamp" AT TIME ZONE 'UTC')::date) < sh.smart_head_date
        OR sh.smart_head_date IS NULL) AS pre_move
FROM ohlcv_raw v
LEFT JOIN smart_head sh ON sh.symbol = v.symbol
WHERE v.timeframe = '1d' AND v.vendor = 'ibkr' AND v.kind LIKE 'venue\_%'
GROUP BY v.symbol, v.kind, sh.smart_head_date;

COMMENT ON VIEW ohlcv_venue_head IS
    'Per (symbol, former IBKR venue route): first and last 1d bar date of the ibkr venue_<route> '
    'raw kind, raw row count, the symbol''s SMART head (earliest ibkr smart_trades 1d row a SMART '
    'request served; NULL if none), and pre_move = the route ends before the SMART head or there '
    'is no SMART head. The moved-name inventory (D-20 evidence, D-25 input). Over ohlcv_raw since '
    'migration 492 (plan 191-09).';

COMMIT;
