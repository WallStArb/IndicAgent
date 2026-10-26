-- Migration 504: retire what todo 509 item 1 orphaned (2026-10-26).
--
-- Trimming src/intelligence/pipeline to the three primitives feature_vector_pipeline runs on
-- deleted the v2.x executor, signal stages, trade framer, zone engine and plugin tier, and with
-- them the last readers of the names below. Nothing has written them since plan 185-45.
--
-- Tables: cis_weights and calibration_curves were read only by the deleted CacheManager. Both
-- are empty (0 rows, checked 2026-10-26) and both were dumped by plan 185-45
-- (data/backups/185-45/cis_weights.dump, calibration_curves.dump; SHA256 in that MANIFEST.md).
-- No view or foreign key depends on either.
--
-- APR keys: the 16 keys below were read only by the deleted trade framer, zone engine and
-- I1-I7 setup plugins. Retired in the order history, state, schema (the retirement order of
-- migrations 349, 431, 434, 457, 459, 499 and 502).
--
-- Reader check, 2026-10-26: tests/unit/test_table_and_apr_key_readers.py lists these names as
-- reader-less after the deletion. Keys the v2.x code read that feature_vector_pipeline also
-- prewarmed still counted as read here; migration 505 retires those. Rerun semantics: the DELETEs match nothing and the
-- DROPs are IF EXISTS. No compressed hypertable column is altered, so no VACUUM clause is owed.

BEGIN;

DROP TABLE IF EXISTS cis_weights;
DROP TABLE IF EXISTS calibration_curves;

DELETE FROM config_history
 WHERE config_key IN ('feature.trade_framer.target_max_atr',
                      'feature.trade_framer.target_max_atr_15m',
                      'feature.trade_framer.target_max_atr_1d',
                      'feature.trade_framer.target_max_atr_1h',
                      'feature.trade_framer.target_max_atr_1m',
                      'feature.trade_framer.target_max_atr_4h',
                      'feature.trade_framer.target_max_atr_5m',
                      'feature.zone_engine.min_stop_distance_atr',
                      'threshold.mean_reversion.trend_regime_max',
                      'threshold.ofi_continuation.acceleration_floor_fraction',
                      'threshold.ofi_continuation.ewma_min_history',
                      'threshold.ofi_continuation.upper_ref_multiplier',
                      'threshold.ofi_continuation.volume_spike_ratio',
                      'threshold.trend_following.consolidation_min_bars',
                      'threshold.trend_following.consolidation_range_pct',
                      'threshold.trend_following.pullback_min_bars');
DELETE FROM config_state
 WHERE config_key IN ('feature.trade_framer.target_max_atr',
                      'feature.trade_framer.target_max_atr_15m',
                      'feature.trade_framer.target_max_atr_1d',
                      'feature.trade_framer.target_max_atr_1h',
                      'feature.trade_framer.target_max_atr_1m',
                      'feature.trade_framer.target_max_atr_4h',
                      'feature.trade_framer.target_max_atr_5m',
                      'feature.zone_engine.min_stop_distance_atr',
                      'threshold.mean_reversion.trend_regime_max',
                      'threshold.ofi_continuation.acceleration_floor_fraction',
                      'threshold.ofi_continuation.ewma_min_history',
                      'threshold.ofi_continuation.upper_ref_multiplier',
                      'threshold.ofi_continuation.volume_spike_ratio',
                      'threshold.trend_following.consolidation_min_bars',
                      'threshold.trend_following.consolidation_range_pct',
                      'threshold.trend_following.pullback_min_bars');
DELETE FROM config_schema
 WHERE config_key IN ('feature.trade_framer.target_max_atr',
                      'feature.trade_framer.target_max_atr_15m',
                      'feature.trade_framer.target_max_atr_1d',
                      'feature.trade_framer.target_max_atr_1h',
                      'feature.trade_framer.target_max_atr_1m',
                      'feature.trade_framer.target_max_atr_4h',
                      'feature.trade_framer.target_max_atr_5m',
                      'feature.zone_engine.min_stop_distance_atr',
                      'threshold.mean_reversion.trend_regime_max',
                      'threshold.ofi_continuation.acceleration_floor_fraction',
                      'threshold.ofi_continuation.ewma_min_history',
                      'threshold.ofi_continuation.upper_ref_multiplier',
                      'threshold.ofi_continuation.volume_spike_ratio',
                      'threshold.trend_following.consolidation_min_bars',
                      'threshold.trend_following.consolidation_range_pct',
                      'threshold.trend_following.pullback_min_bars');

COMMIT;
