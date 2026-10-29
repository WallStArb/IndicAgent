-- Migration 541: feature.volume.dropped_max_fraction (todo 560)
--
-- A cumulative volume statistic with no reset anchor (vwap_dev_sigma, ctf_source, the higher-
-- timeframe ctf_vwap_align series) is missing a NULL-volume bar's weight, so its error grows with
-- the share of dropped bars among the bars accumulated since the first bar that has volume. A row is
-- NaN while that share exceeds this value. Read through FeatureFactoryConfig.dropped_volume_max_fraction
-- (contract/dropped_volume.py). A rebuild of those outputs follows a change. Idempotent.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
    (
        'feature.volume.dropped_max_fraction',
        'float',
        '0.05',
        0.0, 1.0,
        '[initial_estimate] Cumulative-VWAP kernels without a reset anchor (vwap_dev_sigma, ctf_source, the higher-timeframe ctf_vwap_align) are NaN while NULL-volume bars exceed this share of the bars accumulated since the first bar with volume; at 5% the VWAP deviation error stays below about 0.1 sigma on the probe series (todo 560). Not an ML learning target.'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
    ('feature.volume.dropped_max_fraction', '0.05', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT now(), 'feature.volume.dropped_max_fraction', 1, '0.05', 'migration_541',
       'seed: dropped-volume share bound for cumulative volume kernels (todo 560)'
WHERE NOT EXISTS (
    SELECT 1 FROM config_history h
    WHERE h.config_key = 'feature.volume.dropped_max_fraction'
);

COMMIT;
