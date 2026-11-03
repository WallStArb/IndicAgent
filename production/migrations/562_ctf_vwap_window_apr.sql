-- Migration 562: APR seed for the rolling VWAP window behind ctf_vwap_align (todo 584 item 6b).
--
-- ctf_vwap_align was sign(close - VWAP anchored at the start of the higher-timeframe series).
-- An inception-anchored VWAP is absorbing: on the 1h rows (HTF 1d, history from 2006) 84 names sit
-- at +1 and 5 at -1 for the whole span (ADI is above its cumulative VWAP on 98% of daily bars).
-- The VWAP now covers the last N higher-timeframe bars, NaN until N exist and NaN on a window
-- with no volume. N is [initial_estimate] 20 HTF bars, the HMM return buffer's length; the first
-- pilot run reads the sign-flip rate per timeframe and the lead recalibrates. Idempotent.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
    (
        'feature.ctf.vwap_window',
        'int', '20', 2, 500,
        '[initial_estimate] Rolling VWAP window, in higher-timeframe bars, behind ctf_vwap_align (todo 584 6b): sign(HTF close - VWAP of the last N HTF bars), NaN until N bars exist and on a window with no volume. Replaces a VWAP anchored at the series start, which sat on one side for years on trending names. Read via FeatureFactoryConfig.ctf_vwap_window by services/backfill_feature_factory.py and services/feature_vector_pipeline.py. Not an ML learning target.'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('feature.ctf.vwap_window', '20', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT now(), s.config_key, 1, s.config_value, 'migration_562',
       'seed: rolling VWAP window for ctf_vwap_align (todo 584 6b)'
  FROM config_state s
 WHERE s.config_key = 'feature.ctf.vwap_window'
   AND NOT EXISTS (
       SELECT 1 FROM config_history h
        WHERE h.config_key = s.config_key AND h.changed_by = 'migration_562'
 );

COMMIT;
