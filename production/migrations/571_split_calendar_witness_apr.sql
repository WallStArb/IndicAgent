-- Migration 571: the split calendar audit's distribution veto and the unconfirmed_split quarantine
-- (todo 587).
--
-- ops_split_calendar_audit confirms a calendar split on the calendar's clean ratio on its date,
-- canonical's price step by that ratio and the calendar's continuity, then measures every raw 1d
-- series before the date on its own; the row names each series measured unadjusted and the daily
-- rule (d2-v5) rescales exactly those. A split is vetoed only when two independent witnesses agree
-- it is a distribution (lead ruling 2026-11-04): the share count is nearer no change than the split
-- (its statistic below 0.5, a definitional midpoint) and a spin-off witness is present. Volume
-- alone vetoed 27 price-confirmed splits and was right once (SNX 2020-12-01, Concentrix).
--
-- threshold.split_calendar.volume_windows: the session windows (each side of the date, truncated
-- at the neighbouring calendar events) of the log volume step on canonical's series; the
-- statistic is the median over the measurable windows of that step in units of log f. The
-- shortest window also bounds the per-series price medians. [conventional] [20, 60, 120]: one,
-- three and six months; a median over three windows, never one window tuned on one name.
-- threshold.split_calendar.spin_off_listing_sessions: the spin-off witness is an instrument whose
-- first canonical 1d session falls within this many of the name's sessions of effective_date.
-- [conventional] 5: one trading week, when-issued trading to regular way.
--
-- threshold.bar_scrub.quarantine_rules gains unconfirmed_split: the audit's
-- --quarantine-unconfirmed writes it (through bar_scrub.write_flags) on the first new-scale bar of
-- every candidate left unconfirmed, so no one-day fabricated return reaches research. The list
-- only decides the quarantine bit when a flag is written; no such flag exists before the run.
-- None is an ML learning target. Idempotent.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
    (
        'threshold.split_calendar.volume_windows',
        'json', '[20, 60, 120]', NULL, NULL,
        '[conventional] Session windows, each side of a calendar split date and truncated at the neighbouring calendar events, over which ops_split_calendar_audit measures the log volume step on canonical''s series; the share-count statistic is the median over the measurable windows of that step in units of log f (todo 587). The shortest window also bounds the per-series price medians. Not an ML learning target.'
    ),
    (
        'threshold.split_calendar.spin_off_listing_sessions',
        'int', '5', 1, 20,
        '[conventional] The spin-off witness of ops_split_calendar_audit: an instrument whose first canonical 1d session falls within this many of the candidate''s sessions of effective_date. A split is vetoed only with this witness and a share-count statistic below 0.5 (todo 587). Not an ML learning target.'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('threshold.split_calendar.volume_windows', '[20, 60, 120]', 1),
    ('threshold.split_calendar.spin_off_listing_sessions', '5', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT now(), s.config_key, 1, s.config_value, 'migration_571',
       'seed: split calendar distribution veto (todo 587)'
  FROM config_state s
 WHERE s.config_key IN ('threshold.split_calendar.volume_windows',
                        'threshold.split_calendar.spin_off_listing_sessions')
   AND NOT EXISTS (
       SELECT 1 FROM config_history h
        WHERE h.config_key = s.config_key AND h.changed_by = 'migration_571'
 );

UPDATE config_state
SET config_value = (config_value::jsonb || '["unconfirmed_split"]'::jsonb)::text,
    version = version + 1
WHERE config_key = 'threshold.bar_scrub.quarantine_rules'
  AND NOT (config_value::jsonb ? 'unconfirmed_split');

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT now(), cs.config_key, cs.version, cs.config_value, 'migration_571',
       'unconfirmed_split flags quarantine a 1d bar: the first new-scale bar of an unconfirmed calendar split (todo 587)'
  FROM config_state cs
 WHERE cs.config_key = 'threshold.bar_scrub.quarantine_rules'
   AND cs.config_value::jsonb ? 'unconfirmed_split'
   AND NOT EXISTS (
       SELECT 1 FROM config_history ch
        WHERE ch.config_key = cs.config_key AND ch.version = cs.version
          AND ch.changed_by = 'migration_571'
 );

COMMIT;
