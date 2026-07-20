-- Migration 238: forward_returns price-sanity guard (todo 148)
--
-- A single corrupt IBKR print (UUP 5m 2007-06-20 19:00: open=1000 on a ~$25 ETF,
-- volume=200 so it passes market_data_ohlcv_tradeable) fabricated a 3.686 "executable"
-- forward return that single-handedly produced the largest number in the first EM-CAL
-- sweep report -- a mean-return stratum whose true value was near zero. Every mean-based
-- consumer (EM-CAL sweep, future FRAME-04 counterfactual PnL, Kelly sizing) is exposed
-- to an unbounded distortion from one bad print. Rank-based IC (Spearman) is immune to
-- the outlier's magnitude but not its presence -- a corrupted return can still seize an
-- artificial extreme rank, bounded to a single displacement rather than unbounded like a
-- raw mean; ensemble_ic_engine.py masks suspect values out of its rank-IC path too.
--
-- Per Renaissance data-retention principle: do NOT silently drop the row. Add a
-- per-scale suspect flag (return_entry and return_{scale} share the same T+1 entry
-- price within a row, but each scale's exit price is independent, so a corrupt print
-- can taint one scale's return without tainting the others -- flags are per-scale,
-- not one flag for the whole row) and let mean-based consumers filter on it, exactly
-- as they already filter on complete_{scale}.
--
-- These four keys seed the 1-bar (fast) baseline ceiling ONLY. A flat ceiling applied
-- uniformly across scales false-flags genuine multi-month commodity/EM-ETF moves at
-- slow/extended horizons (real 60-bar 1d EWZ/XOP/OIH moves during 2008/2020/2022
-- commonly exceed 50%) -- forward_return_writer.py's scale_max_abs_return() sqrt(n)-
-- scales this baseline per scale (random-walk volatility scales with sqrt(time)),
-- never applies it flat. Verified live: the flat form flagged 2,102 real 1d-extended
-- rows as false positives (EWZ/XOP/OIH/GDX/AMLP -- genuine commodity/EM cycles), while
-- sqrt-scaling isolates exactly the known UUP-2007-06/ITA-2010-05 corrupt-print
-- cluster with zero false positives.
--
-- Ceilings are [initial_estimate], generous enough to keep every real crisis single-bar
-- move -- the corrupt population measured live sits at 0.5-3.7 magnitude; real
-- single-bar ETF moves at these timeframes do not approach that range even in
-- 2008/2020 crisis bars.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alpha.quant.max_abs_return.5m',
    'float',
    '0.25',
    0.05, 1.0,
    '[initial_estimate] 1-bar (fast-scale) plausibility ceiling on |return_fast| for 5m '
    'forward returns (todo 148). sqrt(lookahead_bars)-scaled per scale by '
    'forward_return_writer.py:scale_max_abs_return() before being applied to mid/slow/'
    'extended -- NEVER applied flat across scales (a flat ceiling false-flags genuine '
    'multi-month commodity/EM-ETF moves at slow/extended horizons). Above the scaled '
    'ceiling, return_{scale}_suspect is set true and the row is excluded from '
    'mean-based consumers (rank-IC layers are unaffected -- Spearman is robust to '
    'outlier magnitude). Not an ML learning target.'
),
(
    'alpha.quant.max_abs_return.15m',
    'float',
    '0.30',
    0.05, 1.0,
    '[initial_estimate] 1-bar (fast-scale) plausibility ceiling on |return_fast| for 15m '
    'forward returns (todo 148). See alpha.quant.max_abs_return.5m for full rationale '
    'including the sqrt-scaling requirement. Not an ML learning target.'
),
(
    'alpha.quant.max_abs_return.1h',
    'float',
    '0.40',
    0.05, 1.5,
    '[initial_estimate] 1-bar (fast-scale) plausibility ceiling on |return_fast| for 1h '
    'forward returns (todo 148). See alpha.quant.max_abs_return.5m for full rationale '
    'including the sqrt-scaling requirement. Not an ML learning target.'
),
(
    'alpha.quant.max_abs_return.1d',
    'float',
    '0.50',
    0.05, 2.0,
    '[initial_estimate] 1-bar (fast-scale) plausibility ceiling on |return_fast| for 1d '
    'forward returns (todo 148). Wider than intraday tfs to accommodate genuine large '
    'single-day moves (earnings gaps, crisis days) that are real signal, not corruption. '
    'See alpha.quant.max_abs_return.5m for full rationale including the sqrt-scaling '
    'requirement. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.quant.max_abs_return.5m', '0.25', 1),
    ('alpha.quant.max_abs_return.15m', '0.30', 1),
    ('alpha.quant.max_abs_return.1h', '0.40', 1),
    ('alpha.quant.max_abs_return.1d', '0.50', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'alpha.quant.max_abs_return.5m', 1, '0.25', 'migration_238',
     'Seed price-sanity ceiling, corrupt-print guard [initial_estimate]'),
    (NOW(), 'alpha.quant.max_abs_return.15m', 1, '0.30', 'migration_238',
     'Seed price-sanity ceiling, corrupt-print guard [initial_estimate]'),
    (NOW(), 'alpha.quant.max_abs_return.1h', 1, '0.40', 'migration_238',
     'Seed price-sanity ceiling, corrupt-print guard [initial_estimate]'),
    (NOW(), 'alpha.quant.max_abs_return.1d', 1, '0.50', 'migration_238',
     'Seed price-sanity ceiling, corrupt-print guard [initial_estimate]')
ON CONFLICT DO NOTHING;

ALTER TABLE forward_returns
    ADD COLUMN IF NOT EXISTS return_fast_suspect boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS return_mid_suspect boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS return_slow_suspect boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS return_extended_suspect boolean NOT NULL DEFAULT false;

COMMIT;
