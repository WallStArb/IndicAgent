-- Migration 219: alpha.ic.staleness_alert_days APR key — Phase 143 Plan 03
--
-- LIFECYCLE-05: days since the last successful ic_engine run above which the hook's
-- ic_engine_last_run_age_days gauge + IC_ENGINE_STALE log alert fire. Documented as an
-- in-run diagnostic (Fable N6) -- it only evaluates during a run of the oneshot batch
-- process, so it detects a too-long gap retroactively at the start of the next run, not
-- while the gap is ongoing. A true absence alert needs a live process evaluating
-- `time() - ` the last job_completed_total{job="ic-engine..."} sample (D-06 contract
-- ic_engine already emits) -- out of scope for this plan.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alpha.ic.staleness_alert_days',
    'int',
    '5',
    1, 90,
    '[initial_estimate] Days since the last successful ic_engine run above which '
    'IC_ENGINE_STALE fires. Documented as an in-run diagnostic (evaluated at the start '
    'of the NEXT run, not continuously) -- not an absence detector. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('alpha.ic.staleness_alert_days', '5', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES (
    NOW(), 'alpha.ic.staleness_alert_days', 1, '5', 'migration_219',
    'Initial estimate: IC engine staleness alert threshold [initial_estimate]'
)
ON CONFLICT DO NOTHING;

COMMIT;
