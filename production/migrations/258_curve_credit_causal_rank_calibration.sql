-- Migration 258: recalibrate alpha.rates_regime.inverted_threshold/steep_threshold/
-- credit_tight_threshold (todo 092, rates regime_group)
--
-- ROOT CAUSE (measured directly, same session as migration 257's equity fix): curve_z/
-- credit_z (rolling z-scores of TLT-SHY / HYG-LQD log-return spreads) were bucketed against
-- fixed +-0.5 / 0.0 thresholds -- guessed round numbers (migration 222), never checked
-- against the real distribution. Measured via market_regimes population counts: "flat" (the
-- middle curve tier) alone accounted for ~86-87% of all intraday bars, vs. the ~38% a true
-- N(0,1) z-score would put in [-0.5, 0.5] -- max/min population ratio up to 30.8x, WORSE than
-- equity's original 12-17x imbalance this same todo already fixed.
--
-- FIX: src/intelligence/regime_signals/curve_credit.py now applies the same
-- causal_expanding_rank() transform already proven for equity's breadth signal (shared
-- helper, src/intelligence/regime_signals/causal_rank.py) to curve_z/credit_z too, before
-- bucketing. Self-calibrating by construction rather than a one-time replacement of one
-- guessed number for another. Since both signals are now [0,1] percentile ranks, the natural
-- cuts are 0.33/0.67 for curve's 3-tier split (mirroring vix_pct/breadth_pct) and 0.5 for
-- credit's 2-tier median split (mirroring a fair coin-flip population balance).
--
-- BLAST RADIUS, NOT A CASUAL CONFIG TWEAK: changing this value (and PROB_KEYS renaming
-- curve_z/credit_z -> curve_pct/credit_pct) changes every downstream market_regimes.
-- regime_label, feature_ic_scores regime stratum, and ensemble_weights/ensemble_alpha
-- regime assignment for regime_group='rates'. This migration seeds the corrected default; it
-- does NOT by itself recompute market_regimes historically -- that is a separate, explicit
-- corpus recompute, same as the equity fix (migration 257).

BEGIN;

UPDATE config_schema
SET description =
    '[rca_analysis] Percentile-rank threshold (matches vix_pct/breadth_pct''s tercile '
    'construction, not a raw z-score threshold) below which the curve is "inverted". '
    'Recalibrated 2026-07-24 (todo 092): curve_z is now itself a causal expanding '
    'percentile rank before bucketing, same as the equity breadth signal -- the old -0.5 '
    'was a guessed z-score cut, never checked against the real distribution (measured '
    '"flat" alone at ~86-87% of bars, vs. ~38% expected for a true N(0,1) z-score). '
    'Changing this value changes every downstream market_regimes label for '
    'regime_group=''rates'' -- requires a full historical regime recompute.'
WHERE config_key = 'alpha.rates_regime.inverted_threshold';

UPDATE config_schema
SET description =
    '[rca_analysis] Percentile-rank threshold (matches vix_pct/breadth_pct''s tercile '
    'construction, not a raw z-score threshold) above which the curve is "steep". '
    'Recalibrated 2026-07-24 (todo 092): curve_z is now itself a causal expanding '
    'percentile rank before bucketing, same as the equity breadth signal -- the old 0.5 '
    'was a guessed z-score cut, never checked against the real distribution (measured '
    '"flat" alone at ~86-87% of bars, vs. ~38% expected for a true N(0,1) z-score). '
    'Changing this value changes every downstream market_regimes label for '
    'regime_group=''rates'' -- requires a full historical regime recompute.'
WHERE config_key = 'alpha.rates_regime.steep_threshold';

UPDATE config_schema
SET description =
    '[rca_analysis] Percentile-rank median-split threshold (matches vix_pct/breadth_pct''s '
    'rank construction, not a raw z-score threshold) above which credit is "tight". '
    'Recalibrated 2026-07-24 (todo 092): credit_z is now itself a causal expanding '
    'percentile rank before bucketing -- the old 0.0 was a guessed z-score cut, never '
    'checked against the real distribution. Changing this value changes every downstream '
    'market_regimes label for regime_group=''rates'' -- requires a full historical regime '
    'recompute.'
WHERE config_key = 'alpha.rates_regime.credit_tight_threshold';

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.rates_regime.inverted_threshold', '0.33', 2),
    ('alpha.rates_regime.steep_threshold', '0.67', 2),
    ('alpha.rates_regime.credit_tight_threshold', '0.5', 2)
ON CONFLICT (config_key) DO UPDATE SET
    config_value = EXCLUDED.config_value,
    version = config_state.version + 1;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'alpha.rates_regime.inverted_threshold', 2, '0.33', 'migration_258',
     'todo 092: curve_z converted to a causal expanding percentile rank (matching '
     'vix_pct/breadth_pct); old -0.5 z-score cut caused measured up to 30.8x regime '
     'population imbalance'),
    (NOW(), 'alpha.rates_regime.steep_threshold', 2, '0.67', 'migration_258',
     'todo 092: curve_z converted to a causal expanding percentile rank (matching '
     'vix_pct/breadth_pct); old 0.5 z-score cut caused measured up to 30.8x regime '
     'population imbalance'),
    (NOW(), 'alpha.rates_regime.credit_tight_threshold', 2, '0.5', 'migration_258',
     'todo 092: credit_z converted to a causal expanding percentile rank; old 0.0 z-score '
     'cut was a guessed default never checked against the real distribution')
ON CONFLICT DO NOTHING;

COMMIT;
