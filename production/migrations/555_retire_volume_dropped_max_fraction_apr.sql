-- Migration 555: retire feature.volume.dropped_max_fraction (todo 564 same-batch, todo 584 item 7).
--
-- Migration 541 seeded the key for the dropped-volume share rule of todo 560: a cumulative-VWAP
-- kernel was NaN while NULL-volume bars exceeded this share of the bars accumulated. Migration 543
-- stopped the tradeable view nulling kind `fallback` volume, and canonical holds no kind `venue`
-- row, so market_data_ohlcv_tradeable serves no NULL volume on any timeframe (checked 2026-11-01:
-- the only fallback/venue rows are 128,510 fallback 1d rows, all with volume). The rule, its
-- module (contract/dropped_volume.py) and its config field were deleted; a non-finite volume
-- reaching compute now raises (registry.require_finite_volume).
--
-- Reader check, 2026-11-01: grep -rn "dropped_max_fraction" src services scripts tests
-- --include=*.py -> no reader.
--
-- History, then state, then schema (the retirement order of migration 550), by literal key, in
-- one transaction. Idempotent: a rerun deletes nothing. Rollback: re-run migration 541.

BEGIN;

DELETE FROM config_history WHERE config_key = 'feature.volume.dropped_max_fraction';
DELETE FROM config_state WHERE config_key = 'feature.volume.dropped_max_fraction';
DELETE FROM config_schema WHERE config_key = 'feature.volume.dropped_max_fraction';

COMMIT;
