-- 442: ohlcv_venue_head lists IBKR venue routes only (phase 185 plan 28, VERIFICATION gap 4).
--
-- Migration 380 built the moved-name inventory from every route other than SMART and
-- LEGACY_IMPORT. The Tradier loader (migration 438) records its answers in ohlcv_observation
-- under route TRADIER, so every Tradier-loaded name appeared as a "venue" whose consolidated
-- history starts before the IBKR SMART head: 1,529 TRADIER rows, 492 of them pre_move
-- (2026-10-06). TRADIER is a vendor, not a former IBKR listing venue, and a Tradier span says
-- nothing about where IBKR's SMART history is truncated (todo 433).
--
-- Same column list and order, so CREATE OR REPLACE keeps the readers (label_inputs,
-- ops_data_bar_check D7, listing_venue_writer, bar_reconciliation_audit) unchanged.
-- View change only, no data change. Idempotent.

BEGIN;

CREATE OR REPLACE VIEW ohlcv_venue_head AS
WITH smart_head AS (
    SELECT symbol, min(bar_date) AS smart_head_date
    FROM ohlcv_observation
    WHERE route = 'SMART' AND what_to_show = 'TRADES'
    GROUP BY symbol
)
SELECT
    o.symbol,
    o.route,
    min(o.bar_date) AS first_bar_date,
    max(o.bar_date) AS last_bar_date,
    count(*) AS n_bars,
    sh.smart_head_date,
    (max(o.bar_date) < sh.smart_head_date OR sh.smart_head_date IS NULL) AS pre_move
FROM ohlcv_observation o
LEFT JOIN smart_head sh ON sh.symbol = o.symbol
WHERE o.route <> 'SMART'
  AND o.route <> 'LEGACY_IMPORT'
  AND o.route <> 'TRADIER'
  AND o.what_to_show = 'TRADES'
GROUP BY o.symbol, o.route, sh.smart_head_date;

COMMENT ON VIEW ohlcv_venue_head IS
    'Per (symbol, former IBKR venue route): first and last TRADES 1d bar date, observation '
    'count, the symbol''s SMART TRADES head date (NULL if none), and pre_move = the '
    'route ends before the SMART head or there is no SMART head. The moved-name '
    'inventory (D-20 evidence, D-25 input). SMART, LEGACY_IMPORT and TRADIER (a vendor, '
    'not a venue; migration 442) are excluded.';

COMMIT;
