-- Migration 172: Feature Registry — Phase 140.5
--
-- Creates feature_registry and feature_transition_log with cascade trigger.
-- Seeds all 61 FeatureVector fields (status='active', added_phase='140.5').
-- Adds feature_status_at_eval column to feature_ic_scores.
-- Inserts APR keys for feature governance and ensemble weight aging.
--
-- Tier counts after seed:
--   tier='0_atomic'  → 49 rows
--   tier='2_theory'  → 12 rows (poc_dist_atr, va_position, sr_support_dist,
--                                sr_resist_dist, hmm_regime_prob, hmm_entropy,
--                                hmm_duration, garch_ratio, flight_quality,
--                                ctf_momentum, ctf_vwap_align, ctf_regime_align)
-- No tier='1_interaction' rows yet — reclassification follows after parent
-- relationships are mapped in a later phase.

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. feature_registry table
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS feature_registry (
    feature_name      TEXT PRIMARY KEY,
    group_name        TEXT NOT NULL
        CHECK (group_name IN (
            'momentum', 'volume', 'volatility', 'structure',
            'session', 'oscillator', 'calendar', 'cross_tf',
            'macro', 'regime'
        )),
    tier              TEXT NOT NULL
        CHECK (tier IN ('0_atomic', '1_interaction', '2_theory')),
    formula_short     TEXT NOT NULL,
    normalization     TEXT NOT NULL,
    linear_ready      BOOLEAN NOT NULL,
    source_dims       TEXT[],
    requires_htf      BOOLEAN NOT NULL DEFAULT false,
    window_apr_keys   TEXT[],
    parent_features   TEXT[],
    status            TEXT NOT NULL DEFAULT 'candidate'
        CHECK (status IN ('candidate', 'active', 'shadow_only', 'deprecated')),
    min_ic_sharpe     FLOAT,
    min_ic_n          INTEGER NOT NULL DEFAULT 100,
    fdr_required      BOOLEAN NOT NULL DEFAULT true,
    fdr_alpha         FLOAT NOT NULL DEFAULT 0.05,
    last_ic_value     FLOAT,
    last_ic_sharpe    FLOAT,
    last_ic_n         INTEGER,
    last_eval_at      TIMESTAMPTZ,
    added_phase       TEXT,
    notes             TEXT,
    added_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE feature_registry IS
    'Governance catalog for all FeatureVector fields. One row per feature. '
    'Alignment gate in ic_engine and ensemble_trainer enforces registry row count '
    '= FeatureVector dataclass field count at startup.';

COMMENT ON COLUMN feature_registry.feature_name IS
    'Exact match to FeatureVector dataclass field name. Primary key.';
COMMENT ON COLUMN feature_registry.tier IS
    '0_atomic: single OHLCV dimension, fixed window. '
    '1_interaction: deterministic combination of two tier-0 features. '
    '2_theory: encodes market structure, regime, or cross-asset model.';
COMMENT ON COLUMN feature_registry.min_ic_sharpe IS
    'Per-feature IC Sharpe floor. NULL = use APR global floor '
    '(alpha.feature_registry.min_ic_sharpe_default).';
COMMENT ON COLUMN feature_registry.source_dims IS
    'INFORMATIONAL ONLY, NOT ENFORCED — which of O/H/L/C/V the feature uses.';

-- ---------------------------------------------------------------------------
-- 2. feature_transition_log table
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS feature_transition_log (
    id               BIGSERIAL PRIMARY KEY,
    feature_name     TEXT NOT NULL,
    from_status      TEXT NOT NULL,
    to_status        TEXT NOT NULL,
    triggered_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    trigger_reason   TEXT NOT NULL
        CHECK (trigger_reason IN (
            'ic_promotion', 'ic_demotion', 'parent_cascade', 'operator_override'
        )),
    ic_value         FLOAT,
    ic_sharpe        FLOAT,
    ic_n             INTEGER
);

COMMENT ON TABLE feature_transition_log IS
    'Immutable append-only log of feature lifecycle state transitions. '
    'Tier-1 child demotions on parent deprecation are written by the '
    'trg_cascade_parent_deprecation trigger, not application code.';

-- ---------------------------------------------------------------------------
-- 3. Cascade trigger: tier-1 children auto-deprecate on parent deprecation
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION fn_cascade_parent_deprecation()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status = 'deprecated' AND OLD.status != 'deprecated' THEN
        UPDATE feature_registry
        SET status = 'deprecated'
        WHERE tier = '1_interaction'
          AND status != 'deprecated'
          AND NEW.feature_name = ANY(parent_features);

        INSERT INTO feature_transition_log (feature_name, from_status, to_status, trigger_reason)
        SELECT feature_name, 'active', 'deprecated', 'parent_cascade'
        FROM feature_registry
        WHERE tier = '1_interaction'
          AND NEW.feature_name = ANY(parent_features);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_cascade_parent_deprecation ON feature_registry;
CREATE TRIGGER trg_cascade_parent_deprecation
AFTER UPDATE OF status ON feature_registry
FOR EACH ROW EXECUTE FUNCTION fn_cascade_parent_deprecation();

-- ---------------------------------------------------------------------------
-- 4. Indexes
-- ---------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS feature_registry_tier_idx    ON feature_registry (tier);
CREATE INDEX IF NOT EXISTS feature_registry_status_idx  ON feature_registry (status);
CREATE INDEX IF NOT EXISTS feature_registry_group_idx   ON feature_registry (group_name);

-- ---------------------------------------------------------------------------
-- 5. feature_ic_scores — add feature_status_at_eval column
-- ---------------------------------------------------------------------------

ALTER TABLE feature_ic_scores
    ADD COLUMN IF NOT EXISTS feature_status_at_eval TEXT NOT NULL DEFAULT 'unknown';

COMMENT ON COLUMN feature_ic_scores.feature_status_at_eval IS
    'Status of this feature in feature_registry at the time IC was evaluated. '
    'ensemble_trainer filters WHERE feature_status_at_eval = ''active'' to exclude '
    'IC scores from periods when the feature was not yet active.';

-- ---------------------------------------------------------------------------
-- 6. APR keys
-- ---------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
(
    'alpha.feature_registry.min_ic_sharpe_default',
    'float',
    '0.5',
    0.0, NULL,
    '[initial_estimate] Global IC Sharpe floor for feature promotion. Per-feature override if min_ic_sharpe is set in feature_registry row. Calibrate from Phase 141 IC distribution before setting final value.'
),
(
    'alpha.feature_registry.fdr_alpha',
    'float',
    '0.05',
    0.0, 1.0,
    '[conventional] Benjamini-Hochberg FDR threshold for IC significance gate.'
),
(
    'alpha.feature_registry.demotion_periods',
    'int',
    '3',
    1, NULL,
    '[initial_estimate] Consecutive eval periods below IC Sharpe gate before auto-demotion. Candidate ML learning target.'
),
(
    'alpha.ensemble.weight_half_life_days',
    'float',
    '30',
    1.0, NULL,
    '[initial_estimate] Half-life in days for ensemble weight decay between IC engine runs. effective_weight = ic_weight * exp(-days_since / half_life). At 30 days half-life, weights decay 2.3%/day. Reverts to equal-weight at 90 days stale. Candidate ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
('alpha.feature_registry.min_ic_sharpe_default', '0.5',  1),
('alpha.feature_registry.fdr_alpha',             '0.05', 1),
('alpha.feature_registry.demotion_periods',      '3',    1),
('alpha.ensemble.weight_half_life_days',         '30',   1)
ON CONFLICT (config_key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 7. Seed: all 61 FeatureVector fields
--    (feature_name, group_name, tier, formula_short, normalization, linear_ready,
--     requires_htf, status, added_phase)
-- ---------------------------------------------------------------------------

INSERT INTO feature_registry
    (feature_name, group_name, tier, formula_short, normalization, linear_ready,
     requires_htf, status, added_phase)
VALUES
-- Momentum (6 features)
('momentum_z_fast',      'momentum', '0_atomic', 'Fast-scale return z-score',              'z_scored',          true,  false, 'active', '140.5'),
('momentum_z_mid',       'momentum', '0_atomic', 'Mid-scale return z-score',               'z_scored',          true,  false, 'active', '140.5'),
('momentum_z_slow',      'momentum', '0_atomic', 'Slow-scale return z-score',              'z_scored',          true,  false, 'active', '140.5'),
('momentum_reversal_z',  'momentum', '0_atomic', '1-bar return z-score (reversal signal)', 'z_scored',          true,  false, 'active', '140.5'),
('ret_acf1_z',           'momentum', '0_atomic', 'Return autocorrelation z-score',         'z_scored',          true,  false, 'active', '140.5'),
('momentum_rank_z',      'momentum', '0_atomic', 'Cross-sectional momentum rank z-score',  'z_scored',          true,  false, 'active', '140.5'),
-- Structure (4 features)
('range_position',       'structure', '0_atomic', 'Price position within bar range',        'bounded_signed',    true,  false, 'active', '140.5'),
('bar_close_pos',        'structure', '0_atomic', 'Intra-bar close position anatomy',       'bounded_signed',    true,  false, 'active', '140.5'),
('gap_z',                'structure', '0_atomic', 'Open gap z-score',                       'z_scored',          true,  false, 'active', '140.5'),
('high_52w_dist',        'structure', '0_atomic', 'Distance from 52-week high',             'z_scored',          true,  false, 'active', '140.5'),
-- Volume and order flow (10 features)
('informed_flow',        'volume', '0_atomic', 'Informed order flow proxy',                 'bounded_signed',    true,  false, 'active', '140.5'),
('volume_z',             'volume', '0_atomic', 'Volume z-score',                            'z_scored',          true,  false, 'active', '140.5'),
('ofi_z',                'volume', '0_atomic', 'Order flow imbalance z-score',              'z_scored',          true,  false, 'active', '140.5'),
('ofi_div',              'volume', '0_atomic', 'OFI divergence from price',                 'bounded_signed',    true,  false, 'active', '140.5'),
('cvd_slope_z',          'volume', '0_atomic', 'Cumulative volume delta slope z-score',     'z_scored',          true,  false, 'active', '140.5'),
('cmf',                  'volume', '0_atomic', 'Chaikin money flow',                        'bounded_signed',    true,  false, 'active', '140.5'),
('rel_volume',           'volume', '0_atomic', 'Relative volume vs rolling mean',           'z_scored',          true,  false, 'active', '140.5'),
('vwap_dev_sigma',       'volume', '0_atomic', 'VWAP deviation in sigma units',             'z_scored',          true,  false, 'active', '140.5'),
('amihud_illiq_z',       'volume', '0_atomic', 'Amihud illiquidity z-score',                'z_scored',          true,  false, 'active', '140.5'),
('volume_rank_z',        'volume', '0_atomic', 'Cross-sectional volume rank z-score',       'z_scored',          true,  false, 'active', '140.5'),
-- Volatility (4 features)
('atr_z',                'volatility', '0_atomic', 'ATR z-score',                            'z_scored',          true,  false, 'active', '140.5'),
('vol_ratio',            'volatility', '0_atomic', 'Short/long volatility ratio',            'unbounded_ratio',   false, false, 'active', '140.5'),
('ret_skew_z',           'volatility', '0_atomic', 'Return distribution skewness z-score',  'z_scored',          true,  false, 'active', '140.5'),
('volatility_rank_z',    'volatility', '0_atomic', 'Cross-sectional volatility rank z-score','z_scored',         true,  false, 'active', '140.5'),
-- Session-level / volume profile (4 features — tier 2_theory)
('poc_dist_atr',         'session', '2_theory', 'Distance from volume POC in ATR units',   'z_scored',          false, false, 'active', '140.5'),
('va_position',          'session', '2_theory', 'Position within value area',               'bounded_signed',    false, false, 'active', '140.5'),
('sr_support_dist',      'session', '2_theory', 'Distance to nearest support zone',        'z_scored',          false, false, 'active', '140.5'),
('sr_resist_dist',       'session', '2_theory', 'Distance to nearest resistance zone',     'z_scored',          false, false, 'active', '140.5'),
-- Oscillators (6 features)
('rsi_fast',             'oscillator', '0_atomic', 'RSI at fast scale',                      'bounded_unsigned',  true,  false, 'active', '140.5'),
('rsi_mid',              'oscillator', '0_atomic', 'RSI at mid scale',                       'bounded_unsigned',  true,  false, 'active', '140.5'),
('rsi_slow',             'oscillator', '0_atomic', 'RSI at slow scale',                      'bounded_unsigned',  true,  false, 'active', '140.5'),
('cci_fast',             'oscillator', '0_atomic', 'CCI at fast scale',                      'z_scored',          true,  false, 'active', '140.5'),
('cci_mid',              'oscillator', '0_atomic', 'CCI at mid scale',                       'z_scored',          true,  false, 'active', '140.5'),
('cci_slow',             'oscillator', '0_atomic', 'CCI at slow scale',                      'z_scored',          true,  false, 'active', '140.5'),
-- Regime (10 features — 4 atomic + 3 theory; counted separately)
('hmm_regime_prob',      'regime', '2_theory', 'HMM forward-filtered regime probability',  'bounded_unsigned',  false, false, 'active', '140.5'),
('hmm_entropy',          'regime', '2_theory', 'HMM state distribution entropy',           'z_scored',          false, false, 'active', '140.5'),
('hmm_duration',         'regime', '2_theory', 'Bars in current HMM regime',               'z_scored',          false, false, 'active', '140.5'),
('hurst',                'regime', '0_atomic', 'Hurst exponent (raw)',                      'bounded_unsigned',  false, false, 'active', '140.5'),
('shannon',              'regime', '0_atomic', 'Shannon entropy of return distribution',   'z_scored',          true,  false, 'active', '140.5'),
('garch_ratio',          'regime', '2_theory', 'GARCH conditional vol to long-run ratio',  'unbounded_ratio',   false, false, 'active', '140.5'),
('hma_slope_z',          'regime', '0_atomic', 'Hull moving average slope z-score',        'z_scored',          true,  false, 'active', '140.5'),
('adx',                  'regime', '0_atomic', 'Average directional index (raw)',           'bounded_unsigned',  false, false, 'active', '140.5'),
('aroon_fast',           'regime', '0_atomic', 'Aroon oscillator at fast scale',            'bounded_signed',    true,  false, 'active', '140.5'),
('aroon_slow',           'regime', '0_atomic', 'Aroon oscillator at slow scale',            'bounded_signed',    true,  false, 'active', '140.5'),
-- Cross-asset / macro (3 features — 2 atomic + 1 theory)
('vix_z',                'macro', '0_atomic', 'VIX z-score',                               'z_scored',          true,  false, 'active', '140.5'),
('flight_quality',       'macro', '2_theory', 'Flight-to-quality composite (cross-asset)', 'bounded_signed',    false, false, 'active', '140.5'),
('yield_slope_z',        'macro', '0_atomic', 'Yield curve slope z-score',                 'z_scored',          true,  false, 'active', '140.5'),
-- Calendar (11 features)
('in_ny_session',        'calendar', '0_atomic', 'In NY regular session flag',              'bounded_unsigned',  true,  false, 'active', '140.5'),
('in_london_kz',         'calendar', '0_atomic', 'In London/kill-zone session flag',        'bounded_unsigned',  true,  false, 'active', '140.5'),
('in_overlap',           'calendar', '0_atomic', 'In NY/London session overlap flag',       'bounded_unsigned',  true,  false, 'active', '140.5'),
('power_hour',           'calendar', '0_atomic', 'In power hour flag',                      'bounded_unsigned',  true,  false, 'active', '140.5'),
('opening_range',        'calendar', '0_atomic', 'In opening range period flag',            'bounded_unsigned',  true,  false, 'active', '140.5'),
('above_wk_vwap',        'calendar', '0_atomic', 'Price above weekly VWAP flag',            'bounded_unsigned',  true,  false, 'active', '140.5'),
('dow_sin',              'calendar', '0_atomic', 'Day-of-week sine encoding',               'bounded_signed',    true,  false, 'active', '140.5'),
('dow_cos',              'calendar', '0_atomic', 'Day-of-week cosine encoding',             'bounded_signed',    true,  false, 'active', '140.5'),
('month_position',       'calendar', '0_atomic', 'Position within calendar month [0,1]',   'bounded_unsigned',  true,  false, 'active', '140.5'),
('quarter_position',     'calendar', '0_atomic', 'Position within calendar quarter [0,1]', 'bounded_unsigned',  true,  false, 'active', '140.5'),
('days_to_month_end',    'calendar', '0_atomic', 'Days remaining to month end / days in month [0,1]', 'bounded_unsigned', true, false, 'active', '140.5'),
-- Cross-timeframe (3 features — all tier 2_theory, requires_htf=true)
('ctf_momentum',         'cross_tf', '2_theory', 'HTF momentum alignment signal',           'bounded_signed',    false, true,  'active', '140.5'),
('ctf_vwap_align',       'cross_tf', '2_theory', 'HTF VWAP alignment signal',               'bounded_signed',    false, true,  'active', '140.5'),
('ctf_regime_align',     'cross_tf', '2_theory', 'HTF regime alignment signal',             'bounded_signed',    false, true,  'active', '140.5')
ON CONFLICT (feature_name) DO NOTHING;

COMMIT;
