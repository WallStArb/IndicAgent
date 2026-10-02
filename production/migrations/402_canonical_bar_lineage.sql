-- 402: canonical_bar_lineage, the D2 daily-stage APR keys and the
-- pre_split_unrefetched quarantine rule (phase 185 plan 17, D-06/D-07/D-21).
--
-- Lineage lives in a side table, never a provenance column on
-- market_data_ohlcv (unified design 12.1). Plain table: about 3.9M rows for
-- the full 1d corpus, upserted by bar_derivation --stage daily under the
-- bar_derivation_writer role (185-01 A7: the role CAN DML; no hypertable
-- needed, the PK (symbol, timeframe, "timestamp") answers point lookups).
-- The 1d write method is native upsert (185-01 measurement b: 65.5k rows/s,
-- the nightly changed set is far below the full-corpus pass).
--
-- The quarantine_rules list gains pre_split_unrefetched: a pre-split bar the
-- rule had to emit on the old scale (no post-recording fetch exists) is
-- quarantined out of research until a re-fetch lands (D-21), never silently
-- mixed. Idempotent: re-running appends nothing.

BEGIN;

CREATE TABLE IF NOT EXISTS canonical_bar_lineage (
    symbol text NOT NULL,
    timeframe text NOT NULL CHECK (timeframe = '1d'),
    "timestamp" timestamptz NOT NULL,
    rule_version text NOT NULL,
    request_ids uuid[] NOT NULL,
    batch_id uuid REFERENCES bar_derivation_batch(batch_id),
    derived_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, timeframe, "timestamp")
);

GRANT SELECT, INSERT, UPDATE, DELETE ON canonical_bar_lineage TO bar_derivation_writer;

INSERT INTO config_schema (config_key, value_type, default_value, description) VALUES
    (
        'infra.bar_derivation.daily_symbol_batch',
        'int',
        '25',
        '[initial_estimate] Symbols per chunk in the bar_derivation daily stage loop. Not an ML learning target.'
    ),
    (
        'infra.bar_derivation.daily_write_method',
        'text',
        'upsert',
        '[rca_analysis] 1d write method: native upsert per 185-01 measurement b (65.5k rows/s); only differing or missing rows are written. Not an ML learning target.'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
    ('infra.bar_derivation.daily_symbol_batch', '25', 1),
    ('infra.bar_derivation.daily_write_method', 'upsert', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'infra.bar_derivation.daily_symbol_batch', 1, '25', 'migration_402', 'Initial value [initial_estimate]'),
    (NOW(), 'infra.bar_derivation.daily_write_method', 1, 'upsert', 'migration_402', 'Initial value [rca_analysis] 185-01 measurement b')
ON CONFLICT DO NOTHING;

UPDATE config_state
SET config_value = (config_value::jsonb || '["pre_split_unrefetched"]'::jsonb)::text,
    version = version + 1
WHERE config_key = 'threshold.bar_scrub.quarantine_rules'
  AND NOT (config_value::jsonb ? 'pre_split_unrefetched');

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), 'threshold.bar_scrub.quarantine_rules', cs.version, cs.config_value,
       'migration_402', 'Added pre_split_unrefetched (D-21): pre-split bars emitted on the old scale are quarantined until a post-split re-fetch lands'
FROM config_state cs
WHERE cs.config_key = 'threshold.bar_scrub.quarantine_rules'
  AND cs.config_value::jsonb ? 'pre_split_unrefetched'
  AND NOT EXISTS (
      SELECT 1 FROM config_history ch
      WHERE ch.config_key = 'threshold.bar_scrub.quarantine_rules'
        AND ch.reason LIKE 'Added pre_split_unrefetched%'
  );

COMMIT;
