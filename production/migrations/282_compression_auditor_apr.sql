-- Migration 282: CompressionAuditor APR keys (todo 233)
--
-- alpha_events/ensemble_alpha's compression policy jobs reported last_run_status =
-- 'Success' on every scheduled run for ~29 days while compressing zero chunks --
-- timescaledb_information.job_stats is the job scheduler's self-report, not ground
-- truth. services/compression_auditor.py is a new always-on daemon that instead
-- compares each hypertable's compress_after policy directly against
-- timescaledb_information.chunks.is_compressed and self-heals inline via
-- CALL run_job() for anything found overdue. These two keys govern its cadence.
--
-- check_interval_seconds: how often the (cheap, catalog-only) drift query runs.
-- 6h gives same-day detection without meaningful overhead.
--
-- grace_period_hours: how far past compress_after a chunk must be before it's
-- flagged, to avoid false positives from ordinary scheduling jitter. Must exceed
-- the longest compression policy schedule_interval in the DB (12h, uniform across
-- all policies as of this migration) with margin.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'infra.compression_auditor.check_interval_seconds',
    'int',
    '21600',
    600, 86400,
    '[initial_estimate] How often CompressionAuditor runs its ground-truth drift check '
    '(timescaledb_information.chunks vs. each hypertable''s compress_after policy). '
    '6h default: catalog-only query, cheap to run often; same-day detection of the '
    'todo-233 failure mode. Not an ML learning target.'
),
(
    'infra.compression_auditor.grace_period_hours',
    'int',
    '24',
    12, 168,
    '[initial_estimate] Extra time past compress_after before a chunk is flagged as '
    'overdue, absorbing ordinary compression-policy scheduling jitter (all policies '
    'run on a 12h schedule_interval as of this migration). Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('infra.compression_auditor.check_interval_seconds', '21600', 1),
    ('infra.compression_auditor.grace_period_hours', '24', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'infra.compression_auditor.check_interval_seconds', 1, '21600', 'migration_282',
     'Seed cadence for the new CompressionAuditor daemon (todo 233). [initial_estimate]'),
    (NOW(), 'infra.compression_auditor.grace_period_hours', 1, '24', 'migration_282',
     'Seed grace period for the new CompressionAuditor daemon (todo 233). [initial_estimate]')
ON CONFLICT DO NOTHING;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alert.lag.compression-auditor',
    'int',
    '1000',
    100, 10000,
    '[initial_estimate] Consumer lag threshold for indicagent-compression-auditor. This '
    'daemon consumes no Kafka topic (pure DB-only auditor) -- the threshold governs how '
    'stale agent_last_message_timestamp_seconds may get before service_auditor flags it, '
    'same mechanism as every other unit in _AGENT_ID_TO_UNIT. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alert.lag.compression-auditor', '1000', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'alert.lag.compression-auditor', 1, '1000', 'migration_282',
     'Seed lag/staleness threshold for the new CompressionAuditor systemd unit (todo 233). '
     '[initial_estimate]')
ON CONFLICT DO NOTHING;

COMMIT;
