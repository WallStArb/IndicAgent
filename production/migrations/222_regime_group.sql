-- Migration 222: regime_group
--
-- Rename market_regimes.asset_class -> regime_group.
--
-- Rationale: 'asset_class' was an implementation assumption encoding a specific taxonomy.
-- 'regime_group' is the correct abstraction: any named peer group with a shared,
-- pluggable cross-sectional regime signal (breadth_vol for equity, curve_credit for rates,
-- commodity_momentum_ts for commodities, fx_dollar_carry for fx). Adds APR key
-- alpha.regime.groups (JSON array of group configs) and the per-group signal-threshold
-- APR namespaces (alpha.equity_regime.*, alpha.rates_regime.*,
-- alpha.commodity_{energy,metals,agri}_regime.*, alpha.fx_regime.*).
--
-- This migration is schema/APR foundation only — no code in this repo reads
-- regime_group or the new APR keys yet (Plan 04's dispatcher and Plan 05's ic_engine
-- routing land in later Wave 1/2 plans of Phase 144). alpha.regime.equity_model_enabled
-- is NOT retired here; its retirement is decided in Plan 05 after a project-wide grep
-- confirms ic_engine is the sole consumer.

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Rename column + index
-- ---------------------------------------------------------------------------

ALTER TABLE market_regimes RENAME COLUMN asset_class TO regime_group;

ALTER INDEX market_regimes_equity_tf_ts RENAME TO market_regimes_regime_group_tf_ts;

COMMENT ON TABLE market_regimes IS
    'Cross-sectional regime label per (regime_group, tf, ts). '
    'One row per (regime_group, tf, bar_timestamp) — not per symbol. '
    'IC engine joins here for regime segmentation when the group is enabled in alpha.regime.groups. '
    'Per-symbol HMM labels remain in feature_vectors.regime for per-symbol IC.';

COMMENT ON COLUMN market_regimes.regime_group IS
    'Named peer group whose regime is being labeled. '
    'Examples: equity, rates, commodity_energy, commodity_metals, commodity_agri, fx. '
    'Matches the "name" field in the alpha.regime.groups APR JSON config.';

-- ---------------------------------------------------------------------------
-- 2. alpha.regime.groups JSON config
-- ---------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, description)
VALUES (
    'alpha.regime.groups',
    'json',
    '[initial_estimate] JSON array of regime group configs. Each entry: '
    '{"name": str, "tag_filter": [str], "signal_type": str, "params_prefix": str, "enabled": bool}. '
    'tag_filter patterns match instrument_tags.tag values (prefix match, trailing * stripped). '
    'signal_type maps to a module in src/intelligence/regime_signals/. '
    'params_prefix is the APR namespace for that signal''s thresholds. '
    'Groups are checked in order; symbols matching more than one enabled group raise '
    'AmbiguousRegimeGroupError (fail loud). Symbols matching no enabled group are '
    'OMITTED from regime-stratified IC this run (pooled IC still covers them) with a '
    'loud startup warning — never silently defaulted to "equity".'
) ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES (
    'alpha.regime.groups',
    '[{"name":"equity","tag_filter":["eq_*","intl_*"],"signal_type":"breadth_vol","params_prefix":"alpha.equity_regime","enabled":true},{"name":"rates","tag_filter":["fi_*"],"signal_type":"curve_credit","params_prefix":"alpha.rates_regime","enabled":true},{"name":"commodity_energy","tag_filter":["commodity_energy_crude","commodity_energy_natgas","commodity_energy_pipeline"],"signal_type":"commodity_momentum_ts","params_prefix":"alpha.commodity_energy_regime","enabled":false},{"name":"commodity_metals","tag_filter":["commodity_metals_precious","commodity_metals_industrial"],"signal_type":"commodity_momentum_ts","params_prefix":"alpha.commodity_metals_regime","enabled":false},{"name":"commodity_agri","tag_filter":["commodity_agri"],"signal_type":"commodity_momentum_ts","params_prefix":"alpha.commodity_agri_regime","enabled":false},{"name":"fx","tag_filter":["fx_*","crypto"],"signal_type":"fx_dollar_carry","params_prefix":"alpha.fx_regime","enabled":false}]',
    1
) ON CONFLICT (config_key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 3. alpha.rates_regime.* APR keys
-- ---------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, min_value, max_value, description)
VALUES
    ('alpha.rates_regime.curve_window',
     'int', 5, 500,
     '[conventional] Rolling window, in DAILY bars, for TLT-SHY log-return spread z-score '
     'normalization (mean and std both computed over this window). Scaled to the target TF '
     'via _tf_window(daily, tf) at compute time (Plan 04 dispatcher pre-scales ALL group '
     'window params this way). Warmup = 2*window bars.'),
    ('alpha.rates_regime.credit_window',
     'int', 5, 500,
     '[conventional] Rolling window, in DAILY bars, for HYG-LQD log-return spread z-score '
     'normalization. Scaled to the target TF via _tf_window(daily, tf) at compute time.'),
    ('alpha.rates_regime.steep_threshold',
     'float', 0.0, 5.0,
     '[conventional] Curve z-score above which regime tier is "steep" (long-end outperforms). '
     'Candidate ML learning target.'),
    ('alpha.rates_regime.inverted_threshold',
     'float', -5.0, 0.0,
     '[conventional] Curve z-score below which regime tier is "inverted" (short-end outperforms). '
     'Candidate ML learning target.'),
    ('alpha.rates_regime.credit_tight_threshold',
     'float', -5.0, 5.0,
     '[conventional] Credit z-score above which regime tier is "tight" (HY outperforms IG). '
     'Candidate ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.rates_regime.curve_window',           '60',   1),
    ('alpha.rates_regime.credit_window',          '60',   1),
    ('alpha.rates_regime.steep_threshold',        '0.5',  1),
    ('alpha.rates_regime.inverted_threshold',     '-0.5', 1),
    ('alpha.rates_regime.credit_tight_threshold', '0.0',  1)
ON CONFLICT (config_key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 4. alpha.equity_regime.* APR keys
-- ---------------------------------------------------------------------------
--
-- Rename equity_regime APR namespace from alpha.regime.* to alpha.equity_regime.*
-- The old keys (alpha.regime.vix_low_pct etc., migration 174) remain for backward compat
-- but are now read via params_prefix='alpha.equity_regime' in the groups config above, so
-- we add aliased keys under the new namespace rather than migrating the old ones in place.

INSERT INTO config_schema (config_key, value_type, min_value, max_value, description)
VALUES
    ('alpha.equity_regime.vix_low_pct',
     'float', 0.0, 1.0,
     '[initial_estimate] VIX percentile below which vol regime is "low". '
     'Same calibration as alpha.regime.vix_low_pct. Candidate ML learning target.'),
    ('alpha.equity_regime.vix_high_pct',
     'float', 0.0, 1.0,
     '[initial_estimate] VIX percentile above which vol regime is "high". '
     'Candidate ML learning target.'),
    ('alpha.equity_regime.breadth_bear',
     'float', 0.0, 1.0,
     '[initial_estimate] Fraction of ETFs above 200MA below which breadth is "bear". '
     'Candidate ML learning target.'),
    ('alpha.equity_regime.breadth_bull',
     'float', 0.0, 1.0,
     '[initial_estimate] Fraction of ETFs above 200MA above which breadth is "bull". '
     'Candidate ML learning target.'),
    ('alpha.equity_regime.realized_vol_window',
     'int', 5, 500,
     '[conventional] Rolling window, in DAILY bars, for SPY realized-vol computation '
     '(log-return std). Scaled to the target TF via _tf_window(daily, tf) at compute time. '
     'Warmup requires realized_vol_window + vix_z_window bars before any valid signal.'),
    ('alpha.equity_regime.vix_z_window',
     'int', 20, 1000,
     '[conventional] Rolling window, in DAILY bars, for VIX-proxy z-score normalization '
     '(mean and std). 252 = 1 trading year. Scaled via _tf_window(daily, tf) at compute time. '
     'Candidate ML learning target.'),
    ('alpha.equity_regime.ma_window',
     'int', 20, 500,
     '[conventional] Moving-average window, in DAILY bars, for 200MA breadth signal. '
     '200 = conventional long-term MA. Scaled via _tf_window(daily, tf) at compute time. '
     'Candidate ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.equity_regime.vix_low_pct',            '0.33', 1),
    ('alpha.equity_regime.vix_high_pct',           '0.67', 1),
    ('alpha.equity_regime.breadth_bear',           '0.40', 1),
    ('alpha.equity_regime.breadth_bull',           '0.60', 1),
    ('alpha.equity_regime.realized_vol_window',    '20',   1),
    ('alpha.equity_regime.vix_z_window',           '252',  1),
    ('alpha.equity_regime.ma_window',              '200',  1)
ON CONFLICT (config_key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 5. alpha.commodity_{energy,metals,agri}_regime.* APR keys
-- ---------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, min_value, max_value, description)
VALUES
    ('alpha.commodity_energy_regime.momentum_window', 'int', 5, 500,
     '[conventional] Rolling window, in DAILY bars, for per-symbol log-return z-score in the '
     'energy group. Scaled to the target TF via _tf_window(daily, tf) at compute time.'),
    ('alpha.commodity_energy_regime.primary_threshold', 'float', 0.0, 5.0,
     '[initial_estimate] Median z-score above which momentum tier is "up_primary". Candidate ML target.'),
    ('alpha.commodity_metals_regime.momentum_window', 'int', 5, 500,
     '[conventional] Rolling window, in DAILY bars, for metals group momentum z-score. '
     'Scaled to the target TF via _tf_window(daily, tf) at compute time.'),
    ('alpha.commodity_metals_regime.primary_threshold', 'float', 0.0, 5.0,
     '[initial_estimate] Metals group up_primary/down_primary threshold.'),
    ('alpha.commodity_agri_regime.momentum_window', 'int', 5, 500,
     '[conventional] Rolling window, in DAILY bars, for agri group momentum z-score. '
     'Scaled to the target TF via _tf_window(daily, tf) at compute time.'),
    ('alpha.commodity_agri_regime.primary_threshold', 'float', 0.0, 5.0,
     '[initial_estimate] Agri group up_primary/down_primary threshold.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.commodity_energy_regime.momentum_window', '60', 1),
    ('alpha.commodity_energy_regime.primary_threshold', '0.75', 1),
    ('alpha.commodity_metals_regime.momentum_window', '60', 1),
    ('alpha.commodity_metals_regime.primary_threshold', '0.75', 1),
    ('alpha.commodity_agri_regime.momentum_window', '60', 1),
    ('alpha.commodity_agri_regime.primary_threshold', '0.75', 1)
ON CONFLICT (config_key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 6. alpha.fx_regime.* APR keys
-- ---------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, min_value, max_value, description)
VALUES
    ('alpha.fx_regime.momentum_window', 'int', 5, 500,
     '[conventional] Rolling window, in DAILY bars, for UUP and HYG log-return z-score. '
     'Scaled to the target TF via _tf_window(daily, tf) at compute time.'),
    ('alpha.fx_regime.dollar_strong_threshold', 'float', 0.0, 5.0,
     '[initial_estimate] UUP z-score above which dollar regime is "strong". Candidate ML target.'),
    ('alpha.fx_regime.carry_risk_on_threshold', 'float', -5.0, 5.0,
     '[initial_estimate] HYG z-score above which carry environment is "risk_on".')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.fx_regime.momentum_window',          '60',   1),
    ('alpha.fx_regime.dollar_strong_threshold',  '0.5',  1),
    ('alpha.fx_regime.carry_risk_on_threshold',  '0.0',  1)
ON CONFLICT (config_key) DO NOTHING;

COMMIT;
