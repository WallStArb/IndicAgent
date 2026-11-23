-- Migration 612: split feed auditor APR keys (todo 649)
--
-- After the Massive archive seam (2026-11-16) a split on an active name reaches corporate_action
-- only through the nightly restatement flag and a hand-written row (SNDK, VIXM). The split feed
-- auditor reads the Alpaca corporate-actions feed once a day, ignores inactive names, and fails
-- when a feed split has no recorded row and no matching flag, or has had no row for too long. It
-- proposes candidate rows and never writes corporate_action.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'infra.split_feed_auditor.lookback_days', 'int', '14', 1, 60,
    '[initial_estimate] Calendar days of ex-dates the split feed auditor asks the feed for each '
    'run, so a missed run or a late row is re-judged. Not an ML learning target.'
),
(
    'infra.split_feed_auditor.record_lookback_days', 'int', '7', 0, 60,
    '[initial_estimate] A corporate_action row counts for a feed split when it names the same '
    'symbol and factor and was recorded no earlier than this many days before the ex-date. '
    'Not an ML learning target.'
),
(
    'infra.split_feed_auditor.row_grace_days', 'int', '2', 0, 30,
    '[initial_estimate] Days after the ex-date a flagged split may stay without a corporate_action '
    'row before the auditor fails. Measured 2026-11-23: both post-seam splits were recorded '
    'within 1 to 1.5 days. Not an ML learning target.'
),
(
    'infra.split_feed_auditor.earliest_ex_date', 'str', '2026-11-16', NULL, NULL,
    '[rca_analysis] Earliest ex-date the split feed auditor judges: the Massive archive seam. '
    'A split before it is already adjusted in the archive and gets no row or flag. Not an ML '
    'learning target.'
),
(
    'infra.split_feed_auditor.factor_rel_tol', 'float', '0.02', 0.0001, 0.2,
    '[conventional] Relative tolerance when matching a feed split factor (new_rate / old_rate) to '
    'a recorded factor or to a restatement flag price ratio (either direction). Not an ML '
    'learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
SELECT config_key, default_value, 1
FROM config_schema
WHERE config_key LIKE 'infra.split_feed_auditor.%'
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), c.config_key, 1, c.config_value, 'migration_612',
       'Initial seed for the split feed auditor (todo 649)'
FROM config_state c
WHERE c.config_key LIKE 'infra.split_feed_auditor.%'
  AND NOT EXISTS (
    SELECT 1 FROM config_history h
    WHERE h.config_key = c.config_key AND h.changed_by = 'migration_612'
);

COMMIT;
