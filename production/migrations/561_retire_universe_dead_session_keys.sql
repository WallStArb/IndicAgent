-- Migration 561: retire the APR keys of the universe-dead session columns (todo 584 item 6, D5).
--
-- The 11 columns D5 retires (in_london_kz; amd_phase, amd_manipulation_detected,
-- amd_distribution_direction, manip_strength; the five session_levels overnight and Asian
-- columns; ret_div_1m_5m) cannot carry information on a US-equity regular-hours universe. Their
-- kernels, FeatureCache state and FeatureFactoryConfig fields are deleted in the same commit, so
-- the seven APR keys below have no reader left (tests/unit/test_table_and_apr_key_readers.py).
-- Retired in the order history, state, schema (as migrations 499, 502, 504 and 505).
--
-- feature_vectors and feature_vectors_v2 keep the physical columns: they are derived cache, the
-- writers stop populating them, and the DROP waits for the rebuild's summary card (data policy).
-- The concept_registry rows move to deprecated through
-- scripts/ops/alpha/ops_concept_registry_override.py, the only sanctioned path.
--
-- Rerun semantics: the DELETEs match nothing. No table is rewritten, so no VACUUM clause is owed.

BEGIN;

DELETE FROM config_history
 WHERE config_key IN ('feature.session.london_kz_start_utc_hour',
                      'feature.session.london_kz_end_utc_hour',
                      'feature.session_levels.asia_start_et_hour',
                      'feature.session_levels.asia_end_et_hour',
                      'feature.smc.amd.accum_start_utc_hour',
                      'feature.smc.amd.manip_end_utc_hour',
                      'feature.smc.amd.dist_end_utc_hour');

DELETE FROM config_state
 WHERE config_key IN ('feature.session.london_kz_start_utc_hour',
                      'feature.session.london_kz_end_utc_hour',
                      'feature.session_levels.asia_start_et_hour',
                      'feature.session_levels.asia_end_et_hour',
                      'feature.smc.amd.accum_start_utc_hour',
                      'feature.smc.amd.manip_end_utc_hour',
                      'feature.smc.amd.dist_end_utc_hour');

DELETE FROM config_schema
 WHERE config_key IN ('feature.session.london_kz_start_utc_hour',
                      'feature.session.london_kz_end_utc_hour',
                      'feature.session_levels.asia_start_et_hour',
                      'feature.session_levels.asia_end_et_hour',
                      'feature.smc.amd.accum_start_utc_hour',
                      'feature.smc.amd.manip_end_utc_hour',
                      'feature.smc.amd.dist_end_utc_hour');

COMMIT;
