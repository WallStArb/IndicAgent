-- Migration 317: CVR timeframe namespace was missing 4h (todo 327/D-07 investigation)
--
-- migration 233 seeded `timeframe` with 5 codes (1m/5m/15m/1h/1d) and was never updated.
-- market_data_ohlcv_tradeable has had live 4h data since 2023-08-08 (2,184 rows as of
-- 2026-08-15, most recent bar 2026-08-06) that the registry never registered -- confirmed
-- directly against the DB. This is a real drift bug in CVR's own registry, independent of
-- the Python-side scatter todo 327 otherwise fixes, and must land first: several live call
-- sites hardcode all 6 timeframes including 4h, and repointing them at
-- VocabularyService.active_codes("timeframe") before this migration would silently drop
-- 4h from their behavior.

BEGIN;

-- Bump 1d out of the way first so 4h can take sort_order=5, keeping duration order
-- (1m < 5m < 15m < 1h < 4h < 1d) intact for display purposes.
UPDATE controlled_vocabulary
SET sort_order = 6
WHERE namespace = 'timeframe' AND code = '1d';

INSERT INTO controlled_vocabulary (namespace, code, label, description, sort_order)
VALUES ('timeframe', '4h', '4 Hour', 'Four-hour bar timeframe', 5)
ON CONFLICT (namespace, code) DO NOTHING;

COMMIT;
