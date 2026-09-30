-- Migration 414: APR keys for the fresh IC writer services/ic_measure.py (phase 186 plan 14)
--
-- The writer loads every MeasureParams field from APR. Existing keys it reuses (verified live
-- 2026-09-30): alpha.ic.subsample_min_stride, alpha.ic.bootstrap_block_size.<tf>,
-- alpha.ic.bootstrap_resamples, alpha.ic.bootstrap_seed, alpha.ic.fdr_alpha,
-- alpha.ic.min_reliable_n, alpha.ic.hac_max_lag, alpha.ic.feature_block_columns. It never reads
-- alpha.ic.lookahead.* (plan 186-23 deletes those keys). Five new keys are seeded here.
--
-- alpha.ic_measure.horizons lists, per tf, the stored feature_ic_scores lookaheads that fit inside
-- one session, so the 186-20 parity harness covers them; 1h 20 and 60 cross sessions and are
-- measured on the 1d clock instead (D-18).
-- Seeds use ON CONFLICT DO NOTHING (the 375 shape): a value already present is left alone.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
    ('alpha.ic_measure.degenerate_std', 'float', '1e-8', '0', NULL,
     '[conventional] Std below which a feature column is degenerate and its IC is NaN (services/ic_engine.py literal at 2348, the same value). Not an ML learning target.'),
    ('alpha.ic_measure.monitor_degenerate_std', 'float', '1e-10', '0', NULL,
     '[initial_estimate] Std floor of a member''s window-IC spread below which its IC Sharpe is 0.0 instead of a ratio to a near-zero denominator (the value the monitor used as a literal). A different quantity from alpha.ic_measure.degenerate_std. Not an ML learning target.'),
    ('alpha.ic_measure.horizons', 'json',
     '{"5m":[6,12,39],"15m":[2,5,10],"1h":[1,2],"1d":[1,2,5,10]}', NULL, NULL,
     '[initial_estimate] Per-tf in-session horizon lists (bars) the IC writer measures: the stored feature_ic_scores lookaheads that fit inside one session (1h 20 and 60 cross sessions and are dropped per D-18). The first entry of a tf is its proposer horizon (CI and FDR columns are filled there). Not an ML learning target.'),
    ('alpha.ic_measure.monitor_window_sessions', 'int', '63', '1', NULL,
     '[conventional] Whole sessions per monitoring window (one quarter of sessions). Not an ML learning target.'),
    ('infra.ic_measure.symbol_chunk_size', 'int', '50', '1', NULL,
     '[initial_estimate] Symbols per S0 panel chunk in the IC writer; a memory knob that never enters a value. Not an ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
    ('alpha.ic_measure.degenerate_std', '1e-8', 1),
    ('alpha.ic_measure.monitor_degenerate_std', '1e-10', 1),
    ('alpha.ic_measure.horizons', '{"5m":[6,12,39],"15m":[2,5,10],"1h":[1,2],"1d":[1,2,5,10]}', 1),
    ('alpha.ic_measure.monitor_window_sessions', '63', 1),
    ('infra.ic_measure.symbol_chunk_size', '50', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason) VALUES
    (NOW(), 'alpha.ic_measure.degenerate_std', 1, '1e-8', 'migration_414', 'Initial value [conventional]'),
    (NOW(), 'alpha.ic_measure.monitor_degenerate_std', 1, '1e-10', 'migration_414', 'Initial value [initial_estimate]'),
    (NOW(), 'alpha.ic_measure.horizons', 1, '{"5m":[6,12,39],"15m":[2,5,10],"1h":[1,2],"1d":[1,2,5,10]}', 'migration_414', 'Initial value [initial_estimate]'),
    (NOW(), 'alpha.ic_measure.monitor_window_sessions', 1, '63', 'migration_414', 'Initial value [conventional]'),
    (NOW(), 'infra.ic_measure.symbol_chunk_size', 1, '50', 'migration_414', 'Initial value [initial_estimate]')
ON CONFLICT DO NOTHING;

COMMIT;
