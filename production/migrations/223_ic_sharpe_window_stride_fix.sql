-- Migration 223: alpha.ic.sharpe_window_size_subsampled -- todo 096 ic_sharpe stride-bias fix
--
-- _compute_ic_rolling_metrics (src/intelligence/statistics/ic_math.py) computed its rolling
-- window size by floor-dividing alpha.ic.sharpe_window_size (a RAW-bar constant) by the
-- subsampling stride. That kept window COUNT roughly stride-invariant but let each window's
-- DATA DENSITY (subsampled point count) collapse as stride grew -- ~400 points/window at
-- fast/mid lookaheads, ~100 at slow, ~33 at extended. A Monte Carlo proof against the real
-- production function (scripts/analysis/ic_sharpe_stride_bias_check.py, fixed non-decaying
-- true Spearman rho) showed this mechanically deflates measured ic_sharpe at longer
-- lookaheads by ~sqrt(window_size_fast / window_size_slow) -- 3.4-3.6x at the extended scale
-- for a signal with ZERO real decay. This fed two corpus-wide consumers: (1)
-- feature_selector.py's quality_weight, which penalizes long-lookahead feature selection
-- 2-3.5x below its true strength, and (2) ensemble_ic_engine.py's decay-walk hold_max_bars
-- calibration, which systematically truncates hold_max_bars short. Full writeup, Monte Carlo
-- reproduction, and Fable sign-off: .planning/todos/pending/096-frame-hold-horizon-vs-feature-
-- lookahead-mismatch.md.
--
-- Fix: express the window size as a FIXED target in SUBSAMPLED bars (comparable per-window
-- statistical power at every stride) instead of deriving it from a raw-bar constant divided
-- by stride. New key rather than a redefinition of alpha.ic.sharpe_window_size -- avoids
-- silent code/config rollback skew (old code + new value, or vice versa, would silently
-- produce a wildly wrong window size) and preserves the old key's raw-bar provenance in
-- config_history. alpha.ic.sharpe_window_size is marked [deprecated] below; ic_math.py no
-- longer reads it as of this same commit.
--
-- Value 100 (not 400, which would preserve fast/mid numerics byte-for-byte): 400 requires
-- sharpe_min_windows(30) x 400 x stride raw bars per cell -- 240k raw bars at the slow scale
-- (stride 20) and 720k at extended (stride 60), which would NaN out those scales almost
-- everywhere, freezing hold_max_bars short via a different mechanism (data-insufficiency gate)
-- than the one this migration fixes. 100 keeps the slow scale (stride 20) byte-identical to
-- today's ~100-point windows, upgrades the extended scale honestly (33 -> 100 points; cells
-- lacking ~180k raw bars now correctly go NaN and are skipped in the decay walk rather than
-- false-truncating), and at fast/mid trades some per-window precision for 4x more windows
-- (which improves, not worsens, the sharpe estimate's own standard error).
--
-- Threshold rescale (mandatory, same migration): ic_sharpe ~= rho * sqrt(w) for weak signals,
-- so every sharpe-denominated threshold implicitly tuned at the old ~400-point fast/mid
-- window density must be halved (sqrt(400/100) = 2) to preserve its original meaning under
-- the new fixed w=100 window:
--   alpha.ensemble_ic.decay_threshold             0.1 -> 0.05  (EIC-02 hold_max_bars decay walk)
--   alpha.ensemble.sharpe_floor                    0.05 -> 0.025 (feature_selector quality_weight floor)
--   alpha.feature_registry.min_ic_sharpe_default   0.5 -> 0.25  (feature_registry_service floor)
-- Skipping this rescale would silently double the strictness of every sharpe-denominated
-- gate the moment the window-density bias is removed.
--
-- Every historical ic_sharpe / ic_sharpe_hac / hold_max_bars value computed under the old
-- raw-bar/stride formula is invalidated by this fix and needs re-derivation via a full
-- corpus re-run (ic_engine -> ensemble_trainer reweight -> ensemble_ic_engine decay walk, in
-- that order) -- out of scope for this migration, tracked as the next step in todo 096.

BEGIN;

-- -------------------------------------------------------------------------
-- Section 1: new key -- alpha.ic.sharpe_window_size_subsampled
-- -------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alpha.ic.sharpe_window_size_subsampled',
    'int',
    '100',
    1, NULL,
    '[rca_analysis] Fixed IC-Sharpe rolling window size expressed directly in SUBSAMPLED '
    'bars (todo 096), replacing the deprecated alpha.ic.sharpe_window_size (raw bars // '
    'stride) semantics that let per-window statistical power collapse at longer lookaheads '
    'and mechanically deflated ic_sharpe with zero real signal decay -- see '
    'scripts/analysis/ic_sharpe_stride_bias_check.py for the Monte Carlo proof. WARNING: '
    'changing this value changes the statistical meaning of every ic_sharpe/ic_sharpe_hac '
    'value and invalidates all downstream hold_max_bars calibration -- requires a full '
    'corpus re-run and a coordinated rescale of every sharpe-denominated threshold '
    '(alpha.ensemble_ic.decay_threshold, alpha.ensemble.sharpe_floor, '
    'alpha.feature_registry.min_ic_sharpe_default). NOT an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('alpha.ic.sharpe_window_size_subsampled', '100', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES (
    NOW(), 'alpha.ic.sharpe_window_size_subsampled', 1, '100', 'migration_230',
    'Todo 096 fix: fixed subsampled-bar window size replaces raw-bar/stride division. '
    '100 keeps the slow scale byte-identical to today and upgrades extended from ~33 to '
    '100 points/window without NaN-ing out the long scales (400 would have) '
    '[rca_analysis, Fable sign-off 2026-07-13].'
)
ON CONFLICT DO NOTHING;

-- -------------------------------------------------------------------------
-- Section 2: deprecate alpha.ic.sharpe_window_size (raw bars) -- no longer read
-- -------------------------------------------------------------------------

UPDATE config_schema
SET description = '[deprecated] ' || description
WHERE config_key = 'alpha.ic.sharpe_window_size'
  AND description NOT LIKE '[deprecated]%';

-- -------------------------------------------------------------------------
-- Section 3: rescale sharpe-denominated thresholds (halve -- sqrt(400/100) = 2)
-- -------------------------------------------------------------------------

UPDATE config_state
SET config_value = '0.05',
    version      = version + 1
WHERE config_key = 'alpha.ensemble_ic.decay_threshold';

UPDATE config_state
SET config_value = '0.025',
    version      = version + 1
WHERE config_key = 'alpha.ensemble.sharpe_floor';

UPDATE config_state
SET config_value = '0.25',
    version      = version + 1
WHERE config_key = 'alpha.feature_registry.min_ic_sharpe_default';

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), 'alpha.ensemble_ic.decay_threshold', version, '0.05', 'migration_230',
    'Todo 096: rescaled 0.1 -> 0.05 to preserve threshold meaning under the new fixed '
    'w=100 subsampled window (was implicitly tuned at ~w=400 fast/mid density; '
    'ic_sharpe ~= rho*sqrt(w) so halving the density requires halving the threshold).'
FROM config_state WHERE config_key = 'alpha.ensemble_ic.decay_threshold'
UNION ALL
SELECT NOW(), 'alpha.ensemble.sharpe_floor', version, '0.025', 'migration_230',
    'Todo 096: rescaled 0.05 -> 0.025, same rationale as decay_threshold above.'
FROM config_state WHERE config_key = 'alpha.ensemble.sharpe_floor'
UNION ALL
SELECT NOW(), 'alpha.feature_registry.min_ic_sharpe_default', version, '0.25', 'migration_230',
    'Todo 096: rescaled 0.5 -> 0.25, same rationale as decay_threshold above.'
FROM config_state WHERE config_key = 'alpha.feature_registry.min_ic_sharpe_default'
ON CONFLICT DO NOTHING;

COMMIT;
