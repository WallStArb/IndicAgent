-- 455: the freshness_1d verdict's lag threshold (phase 185 plan 185-46 Task 3).
--
-- services/bar_reconciliation_audit.py (D7) judges every compute_1d name on freshness_1d: the
-- NYSE sessions after the name's latest canonical 1d bar, up to the last completed session, that no
-- answered-empty span covers. The verdict passes while that count is at most this key. It gates the
-- phase 186 rebuild only (verdict_gate.REBUILD_ONLY_CHECKS, services/rebuild_preconditions.py
-- REBUILD_EXTRA_CHECKS), never promotion, and it has its own Grafana rule (bar_freshness_1d_uid).
-- 451 and 452 are reserved by 189-10 and 185-43. Idempotent.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
('threshold.bar_integrity.freshness_max_lag_sessions_1d', 'int', '2', 0, 250,
 '[initial_estimate] Most NYSE sessions a compute_1d name''s latest canonical 1d bar may trail the last completed session (sessions inside an answered-empty span do not count) before the freshness_1d verdict fails. Two sessions absorbs one missed nightly run plus the next run''s timing. Not an ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('threshold.bar_integrity.freshness_max_lag_sessions_1d', '2', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), config_key, 1, config_value, 'migration_455',
       'Initial value for the freshness_1d verdict [initial_estimate]'
  FROM config_state
 WHERE config_key = 'threshold.bar_integrity.freshness_max_lag_sessions_1d'
   AND NOT EXISTS (SELECT 1 FROM config_history h
                   WHERE h.config_key = config_state.config_key
                     AND h.changed_by = 'migration_455');

COMMIT;
