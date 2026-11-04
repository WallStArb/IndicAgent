-- Migration 564: APR seed for research S0's feature-read chunk size (phase 184-08).
--
-- Symbols per chunk when S0 reads stored feature columns or computes kernel members on a source
-- timeframe. It bounds the peak memory of a 5m read (a 5m column over ten years is about 196k rows
-- per symbol) and changes no value in any snapshot. [initial_estimate] 100; not an ML learning
-- target. Idempotent.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
    (
        'infra.research.snapshot_feature_chunk_symbols',
        'int', '100', 1, NULL,
        '[initial_estimate] Symbols per feature-read chunk in research S0 (phase 184-08). Bounds the peak memory of a 5m read (a 5m column over ten years is about 196k rows per symbol); changes no value in any snapshot. Read by src/intelligence/research/snapshot.py. Not an ML learning target.'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('infra.research.snapshot_feature_chunk_symbols', '100', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT now(), s.config_key, 1, s.config_value, 'migration_564',
       'seed: research S0 feature-read chunk size (phase 184-08)'
  FROM config_state s
 WHERE s.config_key = 'infra.research.snapshot_feature_chunk_symbols'
   AND NOT EXISTS (
       SELECT 1 FROM config_history h
        WHERE h.config_key = s.config_key AND h.changed_by = 'migration_564'
 );

COMMIT;
