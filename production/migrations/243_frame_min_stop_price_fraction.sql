-- Migration 243: alpha.frame.min_stop_price_fraction APR key (todo 162)
--
-- compute_frame_geometry() (services/alpha_frame_writer.py) derives stop_distance as
-- stop_atr_mult * atr, guarding only atr <= 0. A small-but-positive ATR on a thin-
-- absolute-volatility instrument (observed: FX/commodity ETFs at 5m -- FXY, FXE, DBB,
-- DBC, GLD, SLV, EWT, MCHI, INDA) passes that guard but still produces an economically
-- meaningless stop -- ordinary price noise then blows through it by dozens of
-- stop-distances, producing counterfactual_pnl_r far beyond a normal stop-out (observed
-- down to -926.87R in-sample, -57.27R in the 143.1-08 OOS window).
--
-- This key adds a second guard: if stop_distance falls below min_stop_price_fraction of
-- entry_price, compute_frame_geometry raises the same ValueError as the atr<=0 case, and
-- the frame is skipped (left open, not scored) via the existing degenerate_atr_skip_count
-- mechanism -- not widened to an artificial floor, which would also widen target_price
-- (derived from stop_distance) and fabricate a trading rule real ATR-based sizing never
-- specified.
--
-- Seed 0.001 (0.10% of price) is [initial_estimate]: the extreme-frame rate is a smooth,
-- continuous gradient against stop-distance% (no clean bimodal cutoff exists in the live
-- corpus -- checked directly, 0.30%-wide buckets from 0% to 0.30% show extreme-frame rate
-- declining from 0.27% to 0.07% with no natural knee), so 0.10% is a conservative,
-- deliberately non-overfit starting point sitting past the steepest part of that curve,
-- not a value tuned to any specific outlier. Flagged for future empirical recalibration
-- once more corpus runs exist to characterize the tradeoff (rejected-frame count vs.
-- residual extreme-tail rate) properly.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alpha.frame.min_stop_price_fraction',
    'float',
    '0.001',
    0.0, 0.05,
    '[initial_estimate] FRAME-01/counterfactual_tracker: minimum stop_distance as a '
    'fraction of entry_price (todo 162). A stop_atr_mult * atr-derived stop below this '
    'fraction is treated as degenerate (same ValueError/skip path as atr <= 0) rather than '
    'scored -- prevents razor-thin ATR-derived stops on thin-absolute-volatility '
    'instruments from producing extreme counterfactual_pnl_r outliers (observed down to '
    '-926.87R). 0.10% seed is a conservative starting point against a smooth, non-bimodal '
    'extreme-frame-rate-vs-stop-distance% curve in the live corpus -- not overfit to a '
    'specific instrument. NOT an ML learning target (yet) -- candidate for future '
    'empirical recalibration once more corpus runs exist.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.frame.min_stop_price_fraction', '0.001', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'alpha.frame.min_stop_price_fraction', 1, '0.001', 'migration_243',
     'Seed minimum stop-distance-as-fraction-of-price floor, todo 162 (extreme R-multiple '
     'outliers on thin-absolute-volatility ATR stops) [initial_estimate]')
ON CONFLICT DO NOTHING;

COMMIT;
