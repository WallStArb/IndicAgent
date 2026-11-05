-- 579: APR seeds for the corpus rerun (phase 186 plan 186-32 Task 1, todo 593).
--
-- services/corpus_rerun_apr.py load_corpus_rerun_apr reads all nine keys into one snapshot; the
-- data gate (services/corpus_rerun_data_gate.py, 186-32) judges with the three data_gate keys
-- and the step runner (services/corpus_rerun.py, 186-31) budgets disk with the five disk keys
-- and refuses to start while a blocking timer can move bars under the run.
-- stored_bytes_per_spool_byte is 1379 stored bytes per feature_vectors row over 3747 spool
-- bytes of one fully populated row as _spool_line writes it (306 numeric columns), rounded up
-- to two decimals (tests/unit/test_corpus_rerun_apr_migration_contract.py recomputes it).
-- Idempotent; no table is rewritten, so no VACUUM clause is owed.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
('infra.corpus_rerun.max_disk_fraction', 'float', '0.70', 0.05, 0.95,
 '[user_preference, lead 2026-11-05] Largest share of the free bytes at launch (corpus_run.free_bytes_at_launch) the rerun''s projected peak may use; the span count is the smallest whose peak fits. Not an ML learning target.'),
('infra.corpus_rerun.disk_reserve_bytes', 'int', '50000000000', 0, 1000000000000,
 '[user_preference] Free bytes the per-unit disk guard never lets the volume drop below during the rerun. Not an ML learning target.'),
('infra.corpus_rerun.bytes_per_row_uncompressed', 'int', '1379', 1, 100000,
 '[rca_analysis] Stored bytes per uncompressed feature_vectors row, indexes included (186-26 1d pilot). Not an ML learning target.'),
('infra.corpus_rerun.compression_ratio', 'float', '6.0', 1, 100,
 '[rca_analysis] Uncompressed over compressed feature_vectors bytes (old table, about 230 bytes per compressed row). Not an ML learning target.'),
('infra.corpus_rerun.stored_bytes_per_spool_byte', 'float', '0.37', 0.01, 10,
 '[initial_estimate] Stored table bytes per spool byte: 1379 over the 3747 spool bytes of one fully populated feature_vectors row as _spool_line writes it, rounded up. The guard uses the larger of this seed and every measured ratio. Not an ML learning target.'),
('infra.corpus_rerun.data_gate.max_missing_session_fraction', 'float', '0.01', 0, 1,
 '[initial_estimate] Largest share of a name-year''s exchange-calendar sessions that may lack 5m coverage (partial or missing, no empty-history answer) for the data gate to pass; the lead may tighten it. Not an ML learning target.'),
('infra.corpus_rerun.data_gate.max_missing_1d_session_fraction', 'float', '0.01', 0, 1,
 '[initial_estimate] Largest share of a name-year''s exchange-calendar sessions that may lack a tradeable 1d bar for the data gate to pass. Not an ML learning target.'),
('infra.corpus_rerun.data_gate.min_session_bar_fraction', 'float', '0.9', 0, 1,
 '[initial_estimate] Share of a session''s expected 5m slots (its own open to close, so half days are shorter) its 5m bars must reach for the session to count as covered; fewer bars is a partial session. Not an ML learning target.'),
('infra.corpus_rerun.blocking_timers', 'str',
 '["indicagent-ibkr-history-fetcher.timer", "indicagent-alpaca-nightly.timer", "indicagent-bar-derivation-daily.timer", "indicagent-bar-derivation-grid.timer"]',
 NULL, NULL,
 '[user_preference] JSON list (read with json.loads) of systemd timers that move bars; the rerun refuses to start while any is enabled or its service is active. Not an ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('infra.corpus_rerun.max_disk_fraction', '0.70', 1),
    ('infra.corpus_rerun.disk_reserve_bytes', '50000000000', 1),
    ('infra.corpus_rerun.bytes_per_row_uncompressed', '1379', 1),
    ('infra.corpus_rerun.compression_ratio', '6.0', 1),
    ('infra.corpus_rerun.stored_bytes_per_spool_byte', '0.37', 1),
    ('infra.corpus_rerun.data_gate.max_missing_session_fraction', '0.01', 1),
    ('infra.corpus_rerun.data_gate.max_missing_1d_session_fraction', '0.01', 1),
    ('infra.corpus_rerun.data_gate.min_session_bar_fraction', '0.9', 1),
    ('infra.corpus_rerun.blocking_timers',
     '["indicagent-ibkr-history-fetcher.timer", "indicagent-alpaca-nightly.timer", "indicagent-bar-derivation-daily.timer", "indicagent-bar-derivation-grid.timer"]',
     1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), config_key, 1, config_value, 'migration_579',
       'Initial value for the corpus rerun (186-32)'
  FROM config_state
 WHERE config_key LIKE 'infra.corpus_rerun.%'
   AND NOT EXISTS (SELECT 1 FROM config_history h
                   WHERE h.config_key = config_state.config_key
                     AND h.changed_by = 'migration_579');

COMMIT;
