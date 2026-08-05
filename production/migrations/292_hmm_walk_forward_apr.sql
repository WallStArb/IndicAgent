-- Migration 292: alpha.hmm.walk_forward.* -- APR keys for the walk-forward HMM
-- parameter-lookahead fix (todo 248).
--
-- regime_writer.py's _compute_symbol_tf fits each (symbol, tf) GaussianHMM ONCE on the
-- ENTIRE available history, then decodes causally -- the decode is causal, but the model
-- doing the deciding was estimated with knowledge of the whole series, including bars far
-- in the future relative to any early timestamp. Confirmed empirically to matter, not just
-- a theoretical concern: SPY/1h label agreement between the full-history fit and a
-- walk-forward refit was 24.9%, barely above the 21.7% chance baseline
-- (docs/analysis/hmm-parameter-lookahead-pilot-spy-1h.md). Decision (2026-08-04, recorded
-- in .planning/todos/pending/248-...md): this is a confirmed causal-law violation and ships
-- regardless of whether it improves downstream ordinal-IC (a separate, negative-result
-- pilot question that does not gate whether to fix an already-confirmed correctness bug).
--
-- alpha.hmm.walk_forward.enabled (default FALSE): landing the walk-forward CODE must not
-- itself change any existing regime label. Flipping this to true, then running
-- `regime_writer.py --refit`, is a separate, later, explicit deployment decision -- see
-- services/regime_writer.py's _compute_symbol_tf_walk_forward docstring for the
-- precondition that decision must satisfy (only run against a freshly-recomputed corpus,
-- never as a partial re-run over rows the single-fit path already populated -- doing so
-- would silently blend two different computation methods under one column).
--
-- alpha.hmm.walk_forward.refit_every_bars.<tf> / .initial_warmup_bars.<tf>: tf-calibrated
-- because bars-per-refit-window is the actionable variable behind the pilot's cross-tf
-- stability finding (higher bar density per refit window -> more stable labels, tracked,
-- not an unexplained instability). Per-tf provenance, from
-- docs/analysis/hmm-parameter-lookahead-pilot-spy-1h.md's broadened results table:
--   1h:  refit_every_bars=1650, initial_warmup_bars=3300  -- [rca_analysis] directly
--        measured by the pilot (SPY/1h, TLT/1h): ~1 trading year refit / ~2yr warmup.
--   15m: refit_every_bars=6600, initial_warmup_bars=13200 -- [rca_analysis] INDEPENDENTLY
--        RE-PILOTED and confirmed (SPY/15m: 56.8% label agreement vs 22.1% chance, +34.8
--        points above chance, 0 sign flips) -- same schedule scaled 4x by 15m's own
--        measured bar-density ratio vs 1h.
--   5m:  refit_every_bars=19800, initial_warmup_bars=39600 -- [initial_estimate] SAME
--        schedule scaled by 5m's bar-density ratio vs 1h (12x), following the SAME scaling
--        logic the 15m value already confirmed, but NOT independently re-piloted at 5m
--        itself. Re-pilot before trusting this tf's regime-stratified results as strongly
--        as 1h/15m's.
--   1d:  refit_every_bars=252, initial_warmup_bars=504 -- [initial_estimate] fresh,
--        UNPILOTED estimate (~1 trading year = 252 bars, ~2yr warmup = 504) at daily bar
--        density. The least-certain of the four; no broadened-pilot measurement exists at
--        this tf. Re-pilot before trusting.
-- None of these 4 keys are an ML learning target -- they calibrate a measurement
-- methodology (how much history a regime-fit window needs), not a model parameter that
-- should drift under online learning.

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
(
    'alpha.hmm.walk_forward.enabled',
    'bool',
    'false',
    NULL, NULL,
    '[user_preference] Gate for todo 248''s walk-forward HMM parameter-lookahead fix in '
    'services/regime_writer.py''s _compute_symbol_tf_walk_forward. Default false: landing '
    'the code must not itself change any existing feature_vectors.regime value. Flipping '
    'this true, then running regime_writer.py --refit, is a deliberate, separate deployment '
    'decision -- see _compute_symbol_tf_walk_forward''s docstring for the precondition '
    '(only run against a freshly-recomputed corpus, never a partial re-run over rows the '
    'single-fit path already populated). Not an ML learning target.'
),
(
    'alpha.hmm.walk_forward.refit_every_bars.5m',
    'int',
    '19800',
    100, 200000,
    '[initial_estimate] todo 248: bars between walk-forward HMM refits at 5m. Scaled from '
    'the 1h pilot''s directly-measured value by 5m''s bar-density ratio (12x), following '
    'the same scaling logic 15m''s value independently confirmed -- NOT itself re-piloted '
    'at 5m. See migration 292 header. Not an ML learning target (calibrates measurement '
    'methodology, not a model parameter).'
),
(
    'alpha.hmm.walk_forward.initial_warmup_bars.5m',
    'int',
    '39600',
    100, 400000,
    '[initial_estimate] todo 248: bars of history required before the first walk-forward '
    'HMM fit at 5m (~2yr at 5m density). See migration 292 header. Not an ML learning '
    'target.'
),
(
    'alpha.hmm.walk_forward.refit_every_bars.15m',
    'int',
    '6600',
    100, 100000,
    '[rca_analysis] todo 248: bars between walk-forward HMM refits at 15m. Independently '
    're-piloted and confirmed (SPY/15m: 56.8% label agreement vs 22.1% chance baseline, '
    '+34.8 points above chance, 0 sign flips) -- see '
    'docs/analysis/hmm-parameter-lookahead-pilot-spy-1h.md. Not an ML learning target.'
),
(
    'alpha.hmm.walk_forward.initial_warmup_bars.15m',
    'int',
    '13200',
    100, 200000,
    '[rca_analysis] todo 248: bars of history required before the first walk-forward HMM '
    'fit at 15m (~2yr at 15m density). Same pilot confirmation as '
    'refit_every_bars.15m. Not an ML learning target.'
),
(
    'alpha.hmm.walk_forward.refit_every_bars.1h',
    'int',
    '1650',
    100, 50000,
    '[rca_analysis] todo 248: bars between walk-forward HMM refits at 1h (~1 trading year). '
    'Directly measured by the Gate 4 pilot (SPY/1h, TLT/1h): full-history-vs-walk-forward '
    'label agreement 24.9% vs 21.7% chance baseline -- see '
    'docs/analysis/hmm-parameter-lookahead-pilot-spy-1h.md. Not an ML learning target.'
),
(
    'alpha.hmm.walk_forward.initial_warmup_bars.1h',
    'int',
    '3300',
    100, 100000,
    '[rca_analysis] todo 248: bars of history required before the first walk-forward HMM '
    'fit at 1h (~2 trading years). Same pilot as refit_every_bars.1h. Not an ML learning '
    'target.'
),
(
    'alpha.hmm.walk_forward.refit_every_bars.1d',
    'int',
    '252',
    20, 5000,
    '[initial_estimate] todo 248: bars between walk-forward HMM refits at 1d (~1 trading '
    'year at daily density). Fresh, UNPILOTED estimate -- no broadened-pilot measurement '
    'exists at this tf, the least-certain of the four calibrated tfs. See migration 292 '
    'header. Not an ML learning target.'
),
(
    'alpha.hmm.walk_forward.initial_warmup_bars.1d',
    'int',
    '504',
    20, 10000,
    '[initial_estimate] todo 248: bars of history required before the first walk-forward '
    'HMM fit at 1d (~2 trading years at daily density). Same unpiloted-estimate caveat as '
    'refit_every_bars.1d. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
('alpha.hmm.walk_forward.enabled', 'false', 1),
('alpha.hmm.walk_forward.refit_every_bars.5m', '19800', 1),
('alpha.hmm.walk_forward.initial_warmup_bars.5m', '39600', 1),
('alpha.hmm.walk_forward.refit_every_bars.15m', '6600', 1),
('alpha.hmm.walk_forward.initial_warmup_bars.15m', '13200', 1),
('alpha.hmm.walk_forward.refit_every_bars.1h', '1650', 1),
('alpha.hmm.walk_forward.initial_warmup_bars.1h', '3300', 1),
('alpha.hmm.walk_forward.refit_every_bars.1d', '252', 1),
('alpha.hmm.walk_forward.initial_warmup_bars.1d', '504', 1)
ON CONFLICT (config_key) DO NOTHING;
