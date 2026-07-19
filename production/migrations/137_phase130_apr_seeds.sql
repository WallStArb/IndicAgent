-- Migration 137: Seed Phase 130 APR keys into config_schema and config_state.
--
-- Covers all 22 operational/UX parameter keys required by the Phase 130 write-path
-- rewrite (signal_writer, lifecycle_writer, signal_tracker, signal_auditor, API routes).
-- Keys are seeded with initial estimates. None are ML learning targets — these are
-- operational parameters and UX preferences (batch sizes, window sizes, UI defaults).
--
-- All keys are idempotent: ON CONFLICT (config_key) DO NOTHING.
-- Safe to re-run; no DROP statements in this file (see migration 143 for DROP).
--
-- Prerequisite: OPS_PREFIXES in src/config/config_service.py must include "ui." and
-- "weights." before these keys can be written via ConfigService.set(). This is handled
-- by the corresponding code change in Phase 130 Plan 01.

-- -------------------------------------------------------------------------
-- config_schema entries
-- -------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
-- signal_writer operational parameters
('feature.signal_writer.batch_size', 'int', '100', 1, 10000,
 '[initial_estimate] Number of signal events to buffer before flushing to the database. Balances write latency against throughput. NOT ML target.'),
('feature.signal_writer.flush_interval_secs', 'float', '5.0', 0.1, 60.0,
 '[initial_estimate] Maximum seconds between signal_writer flushes regardless of batch fullness. Caps write latency under low signal volume. NOT ML target.'),
('feature.signal_writer.max_buffer_size', 'int', '10000', 100, 1000000,
 '[initial_estimate] Hard cap on in-memory signal buffer size. Prevents unbounded memory growth during burst periods. NOT ML target.'),

-- lifecycle_writer operational parameters
('feature.lifecycle_writer.batch_size', 'int', '100', 1, 10000,
 '[initial_estimate] Number of lifecycle events to buffer before flushing to signal_events status updates. NOT ML target.'),
('feature.lifecycle_writer.flush_interval_secs', 'float', '5.0', 0.1, 60.0,
 '[initial_estimate] Maximum seconds between lifecycle_writer flushes regardless of batch fullness. NOT ML target.'),
('feature.lifecycle_writer.max_buffer_size', 'int', '10000', 100, 1000000,
 '[initial_estimate] Hard cap on in-memory lifecycle event buffer size. Prevents unbounded memory growth during burst periods. NOT ML target.'),

-- signal_tracker bootstrap window parameters
('feature.signal_tracker.bootstrap_pending_window_days', 'int', '7', 1, 90,
 '[initial_estimate] Lookback window in days for bootstrapping pending signals from signal_events on service startup. NOT ML target.'),
('feature.signal_tracker.bootstrap_active_window_days', 'int', '30', 1, 365,
 '[initial_estimate] Lookback window in days for bootstrapping active signals from signal_events on service startup. NOT ML target.'),
('feature.signal_tracker.bootstrap_dedup_window_days', 'int', '3', 1, 30,
 '[initial_estimate] Deduplication window in days when bootstrapping signals — suppresses re-processing of recently seen signal_ids. NOT ML target.'),
('feature.signal_tracker.bootstrap_max_attempts', 'int', '3', 1, 10,
 '[initial_estimate] Maximum retry attempts for signal_tracker bootstrap DB queries on startup failure. NOT ML target.'),

-- signal_tracker staleness threshold
('threshold.signal_tracker.staleness_score', 'float', '0.5', 0.0, 1.0,
 '[initial_estimate] Staleness score threshold above which a signal is considered stale and eligible for expiry. Sourced from lifecycle_tracker.py. NOT ML target.'),

-- signal_auditor operational parameters
('feature.signal_auditor.audit_lookback_hours', 'int', '1', 1, 168,
 '[initial_estimate] Lookback window in hours for signal_auditor SQL queries (SQL INTERVAL). Controls how far back the auditor scans for anomalies per cycle. NOT ML target.'),

-- UI / API signals endpoint parameters
('ui.signals.recent_window_days', 'int', '90', 1, 365,
 '[initial_estimate] Default lookback window in days for the signals API recent endpoint. Drives the default date range shown in the dashboard. NOT ML target.'),
('ui.signals.min_confidence', 'float', '0.40', 0.0, 1.0,
 '[data-derived] Minimum raw_confidence threshold for signals returned by the API. Calibrated at 0.40 as the empirical breakeven confidence level. NOT ML target.'),
('ui.signals.min_cis_score', 'float', '0.35', 0.0, 1.0,
 '[initial_estimate] Minimum CIS (Composite Intelligence Score) for signals returned by filtered API endpoints. NOT ML target.'),
('ui.signals.today_window_hours', 'int', '24', 1, 72,
 '[initial_estimate] Lookback window in hours defining "today" signals in the API (used for same-day signal queries). NOT ML target.'),
('ui.signals.yesterday_window_hours', 'int', '48', 1, 168,
 '[initial_estimate] Lookback window in hours defining "yesterday" signals in the API (overlapping window — covers today + yesterday). NOT ML target.'),
('ui.signals.short_window_days', 'int', '7', 1, 30,
 '[initial_estimate] Short lookback window in days for dashboard 7-day signal performance views. NOT ML target.'),
('ui.signals.medium_window_days', 'int', '30', 1, 90,
 '[initial_estimate] Medium lookback window in days for dashboard 30-day signal performance views. NOT ML target.'),
('ui.signals.latency_threshold_minutes', 'int', '5', 1, 60,
 '[initial_estimate] Signal latency threshold in minutes — signals older than this from computed_at are flagged as high-latency in the dashboard. NOT ML target.'),
('ui.signals.max_results', 'int', '500', 1, 10000,
 '[initial_estimate] Maximum number of signal rows returned by unbounded API queries. Prevents runaway result sets. NOT ML target.'),
('ui.signals.top_n_results', 'int', '10', 1, 100,
 '[initial_estimate] Number of top signals returned by ranked/summary endpoints (e.g., top N by confidence). NOT ML target.')
ON CONFLICT (config_key) DO NOTHING;

-- -------------------------------------------------------------------------
-- config_state entries
-- -------------------------------------------------------------------------

INSERT INTO config_state (config_key, config_value, version) VALUES
-- signal_writer
('feature.signal_writer.batch_size',            '100',   1),
('feature.signal_writer.flush_interval_secs',   '5.0',   1),
('feature.signal_writer.max_buffer_size',       '10000', 1),
-- lifecycle_writer
('feature.lifecycle_writer.batch_size',         '100',   1),
('feature.lifecycle_writer.flush_interval_secs','5.0',   1),
('feature.lifecycle_writer.max_buffer_size',    '10000', 1),
-- signal_tracker bootstrap
('feature.signal_tracker.bootstrap_pending_window_days', '7',  1),
('feature.signal_tracker.bootstrap_active_window_days',  '30', 1),
('feature.signal_tracker.bootstrap_dedup_window_days',   '3',  1),
('feature.signal_tracker.bootstrap_max_attempts',        '3',  1),
-- signal_tracker threshold
('threshold.signal_tracker.staleness_score',    '0.5',  1),
-- signal_auditor
('feature.signal_auditor.audit_lookback_hours', '1',    1),
-- ui.signals
('ui.signals.recent_window_days',          '90',   1),
('ui.signals.min_confidence',              '0.40', 1),
('ui.signals.min_cis_score',               '0.35', 1),
('ui.signals.today_window_hours',          '24',   1),
('ui.signals.yesterday_window_hours',      '48',   1),
('ui.signals.short_window_days',           '7',    1),
('ui.signals.medium_window_days',          '30',   1),
('ui.signals.latency_threshold_minutes',   '5',    1),
('ui.signals.max_results',                 '500',  1),
('ui.signals.top_n_results',               '10',   1)
ON CONFLICT (config_key) DO NOTHING;

-- -------------------------------------------------------------------------
-- config_history seed
-- -------------------------------------------------------------------------

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason) VALUES
(NOW(), 'feature.signal_writer.batch_size',            1, '100',   'migration_142', 'Phase 130 APR seed — signal_writer operational parameter'),
(NOW(), 'feature.signal_writer.flush_interval_secs',   1, '5.0',   'migration_142', 'Phase 130 APR seed — signal_writer operational parameter'),
(NOW(), 'feature.signal_writer.max_buffer_size',       1, '10000', 'migration_142', 'Phase 130 APR seed — signal_writer operational parameter'),
(NOW(), 'feature.lifecycle_writer.batch_size',         1, '100',   'migration_142', 'Phase 130 APR seed — lifecycle_writer operational parameter'),
(NOW(), 'feature.lifecycle_writer.flush_interval_secs',1, '5.0',   'migration_142', 'Phase 130 APR seed — lifecycle_writer operational parameter'),
(NOW(), 'feature.lifecycle_writer.max_buffer_size',    1, '10000', 'migration_142', 'Phase 130 APR seed — lifecycle_writer operational parameter'),
(NOW(), 'feature.signal_tracker.bootstrap_pending_window_days', 1, '7',  'migration_142', 'Phase 130 APR seed — signal_tracker bootstrap window'),
(NOW(), 'feature.signal_tracker.bootstrap_active_window_days',  1, '30', 'migration_142', 'Phase 130 APR seed — signal_tracker bootstrap window'),
(NOW(), 'feature.signal_tracker.bootstrap_dedup_window_days',   1, '3',  'migration_142', 'Phase 130 APR seed — signal_tracker dedup window'),
(NOW(), 'feature.signal_tracker.bootstrap_max_attempts',        1, '3',  'migration_142', 'Phase 130 APR seed — signal_tracker bootstrap retry limit'),
(NOW(), 'threshold.signal_tracker.staleness_score',    1, '0.5',  'migration_142', 'Phase 130 APR seed — lifecycle_tracker staleness threshold'),
(NOW(), 'feature.signal_auditor.audit_lookback_hours', 1, '1',    'migration_142', 'Phase 130 APR seed — signal_auditor lookback window'),
(NOW(), 'ui.signals.recent_window_days',          1, '90',   'migration_142', 'Phase 130 APR seed — signals API default recent window'),
(NOW(), 'ui.signals.min_confidence',              1, '0.40', 'migration_142', 'Phase 130 APR seed — signals API minimum confidence (empirical breakeven)'),
(NOW(), 'ui.signals.min_cis_score',               1, '0.35', 'migration_142', 'Phase 130 APR seed — signals API minimum CIS score'),
(NOW(), 'ui.signals.today_window_hours',          1, '24',   'migration_142', 'Phase 130 APR seed — signals API today window'),
(NOW(), 'ui.signals.yesterday_window_hours',      1, '48',   'migration_142', 'Phase 130 APR seed — signals API yesterday window'),
(NOW(), 'ui.signals.short_window_days',           1, '7',    'migration_142', 'Phase 130 APR seed — signals API 7-day window'),
(NOW(), 'ui.signals.medium_window_days',          1, '30',   'migration_142', 'Phase 130 APR seed — signals API 30-day window'),
(NOW(), 'ui.signals.latency_threshold_minutes',   1, '5',    'migration_142', 'Phase 130 APR seed — signals dashboard latency alert threshold'),
(NOW(), 'ui.signals.max_results',                 1, '500',  'migration_142', 'Phase 130 APR seed — signals API max result cap'),
(NOW(), 'ui.signals.top_n_results',               1, '10',   'migration_142', 'Phase 130 APR seed — signals API top-N ranked endpoint');
