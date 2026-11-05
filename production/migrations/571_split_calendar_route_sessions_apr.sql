-- Migration 571: the split calendar audit's per-series window and the unconfirmed_split quarantine
-- (todo 587).
--
-- ops_split_calendar_audit confirms a calendar split on the calendar's clean ratio on its date,
-- canonical's price step by that ratio and the calendar's continuity, then measures every raw 1d
-- series before the date on its own (its close over the calendar's split-adjusted close across the
-- date); the row names each series measured unadjusted and the daily rule (d2-v5) rescales exactly
-- those. There is no automatic veto (lead ruling 2026-11-04): a volume statistic and a new-listing
-- witness were measured and rejected; spin-offs are the operator's explicit exclusions
-- (config/corporate_actions/spin_off_exclusions.csv).
--
-- threshold.split_calendar.route_sessions: the sessions on each side of the date (inside the
-- neighbouring calendar events) the per-series price medians run over. [conventional] 20, one
-- month; the ratio to the calendar's close is precise to basis points, so a month is ample.
--
-- threshold.bar_scrub.quarantine_rules gains unconfirmed_split and operator_bad_bar: the audit's
-- --quarantine-unconfirmed writes them (through bar_scrub.write_flags) on the first new-scale bar of
-- every candidate left unconfirmed, so no one-day fabricated return reaches research, and on every
-- bar of config/corporate_actions/operator_bad_bars.csv. The list only decides the quarantine bit
-- when a flag is written; no such flag exists before the run.
-- Not an ML learning target. Idempotent.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES (
    'threshold.split_calendar.route_sessions',
    'int', '20', 1, 250,
    '[conventional] Sessions on each side of a calendar split date, inside the neighbouring calendar events, over which ops_split_calendar_audit takes the median of each raw 1d series'' close over the calendar''s split-adjusted close (the per-series scale, todo 587). Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('threshold.split_calendar.route_sessions', '20', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT now(), s.config_key, 1, s.config_value, 'migration_571',
       'seed: split calendar per-series window (todo 587)'
  FROM config_state s
 WHERE s.config_key = 'threshold.split_calendar.route_sessions'
   AND NOT EXISTS (
       SELECT 1 FROM config_history h
        WHERE h.config_key = s.config_key AND h.changed_by = 'migration_571'
 );

UPDATE config_state
SET config_value = (
        config_value::jsonb
        || (SELECT COALESCE(jsonb_agg(r), '[]'::jsonb)
              FROM jsonb_array_elements_text('["unconfirmed_split", "operator_bad_bar"]'::jsonb) r
             WHERE NOT (config_value::jsonb ? r))
    )::text,
    version = version + 1
WHERE config_key = 'threshold.bar_scrub.quarantine_rules'
  AND NOT (config_value::jsonb ?& ARRAY['unconfirmed_split', 'operator_bad_bar']);

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT now(), cs.config_key, cs.version, cs.config_value, 'migration_571',
       'unconfirmed_split and operator_bad_bar flags quarantine a 1d bar: the first new-scale bar of an unconfirmed calendar split, and an operator-listed bad bar (todo 587)'
  FROM config_state cs
 WHERE cs.config_key = 'threshold.bar_scrub.quarantine_rules'
   AND cs.config_value::jsonb ?& ARRAY['unconfirmed_split', 'operator_bad_bar']
   AND NOT EXISTS (
       SELECT 1 FROM config_history ch
        WHERE ch.config_key = cs.config_key AND ch.version = cs.version
          AND ch.changed_by = 'migration_571'
 );

COMMIT;
