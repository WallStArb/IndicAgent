-- Migration 374: former-venue history recovery (todo 433)
--
-- A SMART-routed IBKR history request serves bars only from a stock's current primary
-- listing on: ADI (NYSE to Nasdaq 2012), UAL (2018), PEP (2017) and the iShares bond funds
-- (2017) looked listed at their move, and ohlcv_empty_history recorded the earlier years as
-- verified empty. The same contract routed to its former venue serves those years with the
-- official open and close (the listing venue's auctions) but only that venue's volume, 38-54%
-- of consolidated for JPM in June 2025 and varying daily.
--
-- src/providers/ibkr.py now requests the uncovered head of a 1d stock walk from each former
-- venue candidate and keeps the one with the most volume, stored with source 'ibkr_venue'
-- (src/core/bar_normalizer.py SOURCE_IBKR_VENUE) once store_bars is switched on. This migration:
--
-- 1. Seeds the four infra.ibkr.venue_fallback.* APR keys the backfill overlays onto ibkr.py
--    (defaults match the module constants exactly). store_bars starts false (verify-only):
--    former venues are asked so a span with history there is never recorded empty, but their
--    bars are not stored until the listing-venue validation study passes (owner decision
--    2026-09-26; docs/plans/2026-09-26-daily-data-foundation.md, D3 and D4).
-- 2. Makes market_data_ohlcv_tradeable report NULL volume on ibkr_venue rows. Every compute
--    and research read goes through this view, so one rule keeps venue-only volume from being
--    read as consolidated anywhere: prices and returns are exact across the seam, volume is
--    unknown before it. The WHERE clause still filters on the stored volume, so those rows stay
--    visible. Column list and order match the SELECT * the view expanded to (migration 242).
-- 3. Deletes every 1d ohlcv_empty_history row. Each was recorded after SMART alone answered
--    "no data", which is not evidence for a name that changed venue (AMD, CSX, PEP, TLT, IEF
--    and others were recorded empty for years they traded). The next 1d backfill re-asks each
--    head with former-venue recovery; genuine late listings are re-recorded when every venue
--    also answers "no data". Apply after any 1d backfill in flight has finished, so it cannot
--    write a row this deletes without re-asking.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'infra.ibkr.venue_fallback.exchanges',
    'json',
    '["NYSE", "ARCA", "ISLAND", "AMEX", "BATS"]',
    NULL, NULL,
    '[rca_analysis] IBKR routing codes asked for a stock''s history before its first SMART bar (todo 433); the one with the most volume is kept. ISLAND is Nasdaq. The contract''s current primary is skipped. Not an ML learning target.'
),
(
    'infra.ibkr.venue_fallback.timeframes',
    'json',
    '["1d"]',
    NULL, NULL,
    '[initial_estimate] Timeframes whose pre-venue-move history is recovered (todo 433). Intraday history depth is capped by IBKR regardless, so recovery there is untested. Not an ML learning target.'
),
(
    'infra.ibkr.venue_fallback.min_gap_days',
    'int',
    '7',
    1, 3650,
    '[conventional] Minimum days between the requested start and the first SMART bar before former venues are asked; smaller gaps are weekends and holidays, not venue moves. Not an ML learning target.'
),
(
    'infra.ibkr.venue_fallback.store_bars',
    'bool',
    'false',
    NULL, NULL,
    '[user_preference] Operator switch. false: former venues only verify (history found there blocks an empty-history record and is logged). true: the highest-volume venue''s bars are stored as source ibkr_venue. Set true only after the D3 listing-venue validation study passes. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('infra.ibkr.venue_fallback.exchanges', '["NYSE", "ARCA", "ISLAND", "AMEX", "BATS"]', 1),
    ('infra.ibkr.venue_fallback.timeframes', '["1d"]', 1),
    ('infra.ibkr.venue_fallback.min_gap_days', '7', 1),
    ('infra.ibkr.venue_fallback.store_bars', 'false', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'infra.ibkr.venue_fallback.exchanges', 1, '["NYSE", "ARCA", "ISLAND", "AMEX", "BATS"]', 'migration_374', 'Initial value: matches ibkr.py _VENUE_FALLBACK_EXCHANGES [rca_analysis]'),
    (NOW(), 'infra.ibkr.venue_fallback.timeframes', 1, '["1d"]', 'migration_374', 'Initial value: matches ibkr.py _VENUE_FALLBACK_TIMEFRAMES [initial_estimate]'),
    (NOW(), 'infra.ibkr.venue_fallback.min_gap_days', 1, '7', 'migration_374', 'Initial value: matches ibkr.py _VENUE_FALLBACK_MIN_GAP_DAYS [conventional]'),
    (NOW(), 'infra.ibkr.venue_fallback.store_bars', 1, 'false', 'migration_374', 'Verify-only until the D3 validation study passes (owner decision 2026-09-26) [user_preference]')
ON CONFLICT DO NOTHING;

CREATE OR REPLACE VIEW market_data_ohlcv_tradeable AS
SELECT "timestamp",
       symbol,
       timeframe,
       open,
       high,
       low,
       close,
       CASE WHEN source = 'ibkr_venue' THEN NULL ELSE volume END AS volume,
       source,
       base,
       price_sanity_status
FROM market_data_ohlcv
WHERE volume > 0
  AND price_sanity_status IS DISTINCT FROM 'confirmed_corrupt';

DELETE FROM ohlcv_empty_history WHERE timeframe = '1d' AND provider = 'ibkr';

COMMIT;
