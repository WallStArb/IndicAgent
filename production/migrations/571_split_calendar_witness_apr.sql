-- Migration 571: the split calendar audit's share-count veto (todo 587).
--
-- ops_split_calendar_audit confirms a calendar split on the calendar's clean ratio on its date,
-- canonical's price step by that ratio and the calendar's continuity, then measures every raw 1d
-- series before the date on its own; the row names each series measured unadjusted and the daily
-- rule (d2-v5) rescales exactly those. The share count can only veto (lead ruling 2026-11-04): a
-- false veto leaves a fabricated split-day return in canonical, as wrong as a false confirm.
--
-- threshold.split_calendar.volume_windows: the session windows (each side of the date, truncated
-- at the neighbouring calendar events) of the log volume step on canonical's series; the
-- statistic is the median over the measurable windows of that step in units of log f. The
-- shortest window also bounds the per-series price medians. [conventional] [20, 60, 120]: one,
-- three and six months; a median over three windows, never one window tuned on one name.
-- threshold.split_calendar.volume_veto_below: the statistic below which the share count robustly
-- did not change (much nearer 0, no change, than 1, a split). [conventional] 0.25; 0.25 to 0.5
-- is ambiguous and confirms with the statistic recorded. Not tuned on any name.
-- Neither is an ML learning target. Idempotent.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
    (
        'threshold.split_calendar.volume_windows',
        'json', '[20, 60, 120]', NULL, NULL,
        '[conventional] Session windows, each side of a calendar split date and truncated at the neighbouring calendar events, over which ops_split_calendar_audit measures the log volume step on canonical''s series; the share-count statistic is the median over the measurable windows of that step in units of log f (todo 587). The shortest window also bounds the per-series price medians. Not an ML learning target.'
    ),
    (
        'threshold.split_calendar.volume_veto_below',
        'float', '0.25', 0.0, 0.5,
        '[conventional] A calendar split is vetoed (no row, review) only when its share-count statistic is below this: robust evidence the share count did not change, a spin-off or stock distribution (todo 587). Missing or ambiguous evidence never vetoes. Not an ML learning target.'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('threshold.split_calendar.volume_windows', '[20, 60, 120]', 1),
    ('threshold.split_calendar.volume_veto_below', '0.25', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT now(), s.config_key, 1, s.config_value, 'migration_571',
       'seed: split calendar share-count veto (todo 587)'
  FROM config_state s
 WHERE s.config_key IN ('threshold.split_calendar.volume_windows',
                        'threshold.split_calendar.volume_veto_below')
   AND NOT EXISTS (
       SELECT 1 FROM config_history h
        WHERE h.config_key = s.config_key AND h.changed_by = 'migration_571'
 );

COMMIT;
