-- Migration 237: stratified, self-calibrating regime-shift guard (todo 144)
--
-- Replaces the single flat alpha.decay.regime_shift_fraction threshold (0.60,
-- [initial_estimate], never empirically validated) with per-(tf, regime_group)
-- stratified rails + an empirical band that self-calibrates once history exists.
--
-- The RCA (2026-07-19 session) found the old 0.60 threshold sits ~35 points below
-- this corpus's own known-normal failure rate: EIC-04 already established a 2-4%
-- pass rate (35/1585=2.21%, 54/1425=3.79%) as this corpus's steady state under
-- proper FDR correction, i.e. 96-98% failure is NORMAL, not a regime shift. The old
-- threshold trips on effectively every run.
--
-- guard_fail_rate_max/guard_fail_rate_min are [rca_analysis], not [initial_estimate]
-- -- deliberately not repeating the mistake being fixed. guard_band_z/min_cells/
-- min_history/history_window are [conventional] statistical constants.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alpha.decay.guard_fail_rate_max',
    'float',
    '0.995',
    0.5, 1.0,
    '[rca_analysis] Upper rail for the per-(tf, regime_group) lifecycle regime-shift '
    'guard (todo 144). Above this fraction of active cells failing simultaneously, '
    'even historical survivors are dying together -- hold all lifecycle transitions. '
    'Grounded in the 2026-07-19 RCA against EIC-04''s established 96-98% normal '
    'failure-rate base (35/1585=2.21%, 54/1425=3.79% pass rates). Not an ML '
    'learning target.'
),
(
    'alpha.decay.guard_fail_rate_min',
    'float',
    '0.85',
    0.0, 0.99,
    '[rca_analysis] Lower rail for the per-(tf, regime_group) lifecycle regime-shift '
    'guard (todo 144). Below this fraction failing (i.e. a suspiciously HIGH pass '
    'rate, 4-7x the known ~2-4% base), alert (do not hold) -- likely CI '
    'overconfidence (see todo 091, _fisher_z_ci may be too narrow) or a measurement '
    'bug, not genuine mass recovery. Not an ML learning target.'
),
(
    'alpha.decay.guard_band_z',
    'float',
    '3.0',
    1.0, 6.0,
    '[conventional] Z-multiplier (three-sigma) on the robust-scaled (1.4826*MAD) '
    'empirical band for the regime-shift guard (todo 144), once a stratum has '
    'enough history (see guard_min_history). Not an ML learning target.'
),
(
    'alpha.decay.guard_min_cells',
    'int',
    '100',
    10, 10000,
    '[conventional] Minimum active POOLED cells a (tf, regime_group) stratum needs '
    'before its fail-fraction is trusted as hold-authoritative (todo 144). Binomial '
    'standard error of a fraction at p~0.9, n=100 is ~0.03 -- tight enough to trust. '
    'Below this floor the stratum is diagnostic-only. Not an ML learning target.'
),
(
    'alpha.decay.guard_min_history',
    'int',
    '8',
    3, 100,
    '[conventional] Minimum prior evaluations a (tf, regime_group) stratum needs '
    'before the empirical median/MAD band takes over from the seeded rails (todo '
    '144) -- minimum sane N for a robust scale estimate. Not an ML learning target.'
),
(
    'alpha.decay.guard_history_window',
    'int',
    '20',
    5, 500,
    '[conventional] Rolling window (most recent evaluations) used to compute each '
    'stratum''s empirical median/MAD band for the regime-shift guard (todo 144). '
    'Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.decay.guard_fail_rate_max', '0.995', 1),
    ('alpha.decay.guard_fail_rate_min', '0.85', 1),
    ('alpha.decay.guard_band_z', '3.0', 1),
    ('alpha.decay.guard_min_cells', '100', 1),
    ('alpha.decay.guard_min_history', '8', 1),
    ('alpha.decay.guard_history_window', '20', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'alpha.decay.guard_fail_rate_max', 1, '0.995', 'migration_237',
     'RCA-grounded upper rail replacing the miscalibrated flat regime_shift_fraction threshold [rca_analysis]'),
    (NOW(), 'alpha.decay.guard_fail_rate_min', 1, '0.85', 'migration_237',
     'RCA-grounded lower rail, new two-sided guard tail [rca_analysis]'),
    (NOW(), 'alpha.decay.guard_band_z', 1, '3.0', 'migration_237',
     'Three-sigma robust band multiplier [conventional]'),
    (NOW(), 'alpha.decay.guard_min_cells', 1, '100', 'migration_237',
     'Minimum active cells for hold authority, binomial SE argument [conventional]'),
    (NOW(), 'alpha.decay.guard_min_history', 1, '8', 'migration_237',
     'Minimum history before empirical band activates [conventional]'),
    (NOW(), 'alpha.decay.guard_history_window', 1, '20', 'migration_237',
     'Rolling window for empirical band calculation [conventional]')
ON CONFLICT DO NOTHING;

-- Retire the broken flat threshold. Keep the config_state/config_history rows for
-- provenance/lineage (per todo 144's explicit instruction) -- only mark the schema
-- description as superseded so a future reader doesn't mistake it for live.
UPDATE config_schema
SET description = '[SUPERSEDED by todo 144, migration 237 -- see alpha.decay.guard_* '
    'keys] Was: fraction of (feature, symbol, tf) cells simultaneously showing decay '
    'that classifies an event as a market regime shift. No longer read by '
    'ic_engine.py as of migration 237 -- the flat 0.60 threshold sat ~35 points '
    'below this corpus''s known-normal 96-98% failure rate and tripped on '
    'effectively every run.'
WHERE config_key = 'alpha.decay.regime_shift_fraction';

COMMIT;
