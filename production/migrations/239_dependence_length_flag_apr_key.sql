-- Migration 239: alpha.ic.dependence_length_flag_ratio APR key (todo 145)
--
-- Closes out todo 091's residual 21% bootstrap-CI SUSPECT rate: Fable 5's 2026-07-19
-- review confirmed every residual SUSPECT cell is a feature whose true autocorrelation
-- dependence length exceeds its timeframe's `alpha.ic.bootstrap_block_size.{5m,15m,1h,1d}`
-- (live 78/26/10/10 bars). ctf_momentum runs ~4x its block size across tfs (structural,
-- HTF-derived); flight_quality (a TLT/SPY macro-divergence feature) runs ~750x at 1h --
-- a months-scale decorrelation no feasible block size fixes.
--
-- Per this project's principles (resist overfitting, instrument everything): the fix is
-- standing instrumentation, not per-feature block-size tuning. This key is the flag
-- threshold `scripts/ops/alpha/ops_dependence_length_diagnostic.py` compares each
-- (feature, tf)'s measured decorrelation_lag / block_size ratio against, writing one
-- integrity_monitor row per (feature, tf) per run (monitor_type='ic_bootstrap').
--
-- Seed 2.0 is [conventional]: a factor-of-2 overshoot is a reasonable first trigger --
-- the live data measured by Fable 5's review clusters at ~4x and ~750x, well clear of a
-- 2x floor, so this threshold is not tuned to squeak either known case through.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alpha.ic.dependence_length_flag_ratio',
    'float',
    '2.0',
    1.0, 10.0,
    '[conventional] Flag threshold for ops_dependence_length_diagnostic.py (todo 145): '
    'a (feature, tf) cell is flagged lower-trust when its measured 1/e-decorrelation-lag '
    '/ bootstrap_block_size ratio exceeds this value. A factor-of-2 overshoot is a '
    'reasonable first trigger -- live cases (ctf_momentum ~4x, flight_quality ~750x) '
    'cluster well clear of this floor. Written to integrity_monitor as threshold_value, '
    'monitor_type=''ic_bootstrap''. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.ic.dependence_length_flag_ratio', '2.0', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'alpha.ic.dependence_length_flag_ratio', 1, '2.0', 'migration_239',
     'Seed dependence-length flag threshold, closes out todo 091 residual SUSPECT rate [conventional]')
ON CONFLICT DO NOTHING;

COMMIT;
