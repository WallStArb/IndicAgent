-- Migration 294: feature.atr_normalization.min_atr_pct APR key (todo 237)
--
-- Closes todo 237: `feature_factory.py`'s shared ATR-normalization validity guard
-- (`_is_valid_atr`, used by every ATR-normalized distance feature -- 15+ columns spanning
-- session VP, S/R, swing/trend structure, Fibonacci zones, session levels, and all 6 SMC
-- compute functions) gated only on `atr_val > 0`, not on atr_val being non-negligibly small
-- relative to price. A legitimately-positive but numerically-tiny ATR (confirmed live: BIL,
-- an ultra-short-duration T-bill ETF, during a genuinely flat period) makes
-- `(level - close_) / atr_val` blow up to an implausible magnitude -- confirmed up to 96,512
-- for weekly_r1_dist_atr -- with no separate check ever catching it.
--
-- This key is a floor on atr_val as a fraction of close_ (relative, not absolute, so it
-- holds across instruments at any price scale): when atr_val < min_atr_pct * abs(close_),
-- `_is_valid_atr` now treats it the same as atr_val <= 0 -- the existing per-function
-- fallback (0.0/None/neutral default, matching each function's pre-existing atr_val<=0
-- convention), never a new failure mode.
--
-- Seed 0.0001 (1 basis point of price) is [conventional]: real traded assets essentially
-- never show a true ATR below 1bp of price under normal conditions, so this floor should
-- only ever trip during genuinely degenerate flat periods (todo 237's own measured scale:
-- 9 rows out of 25.4M in the 5m equity corpus cross even the much coarser float16 ceiling
-- that motivated the original investigation) -- not tuned to squeak any known case through.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'feature.atr_normalization.min_atr_pct',
    'float',
    '0.0001',
    0.0, 0.01,
    '[conventional] Floor on atr_val as a fraction of close_ for every ATR-normalized '
    'distance feature in feature_factory.py (_is_valid_atr, todo 237). atr_val below '
    'min_atr_pct * abs(close_) is treated as invalid, same as atr_val <= 0, preventing a '
    'legitimately-positive but numerically-tiny ATR from exploding a normalized distance '
    '(confirmed live: weekly_r1_dist_atr up to 96,512 during a genuinely flat BIL period). '
    'Relative (not absolute), so it holds across instruments at any price scale. ML '
    'learning target: yes -- an ML tuner may find a higher floor better separates real '
    'flat-period degeneracy from ordinary low-volatility bars.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('feature.atr_normalization.min_atr_pct', '0.0001', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'feature.atr_normalization.min_atr_pct', 1, '0.0001', 'migration_294',
     'Seed ATR-normalization relative floor, closes todo 237 [conventional]')
ON CONFLICT DO NOTHING;

COMMIT;
