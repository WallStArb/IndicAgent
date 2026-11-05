-- Migration 580: the isolated_wick and busted_trade_window scrub rules (todo 594).
--
-- isolated_wick flags a bar whose wick (high / max(open, close) or min(open, close) / low) reaches
-- min_ratio while the adjacent traded bars plus the bar's own body span less than
-- max_neighbour_span: a print its neighbourhood never traded near (decimal shifts, stub and
-- fat-finger quotes). Base rate measured 2026-11-05 over every canonical bar on 1d, 1h, 15m and
-- 5m (todo 594 holds the table): the span axis is a plateau from 1.25 to 2.0; every
-- narrow-neighbour bar inspected between 2.5x and 3x is a bad print; real crash and split days
-- appear below 2.5x (2008-09, 2015-08-24, NVDA 2024-06-10), held out by the ratio and the span.
--
-- busted_trade_window flags every bar inside an exchange-broken window
-- (config/bars/busted_trade_windows.csv; the 2010-05-06 flash crash) whose high or low lies
-- beyond the window's deviation from its reference close.
--
-- Both rules join threshold.bar_scrub.quarantine_rules, so the tradeable view hides their bars.
-- Not ML learning targets. Idempotent; no table is rewritten, so no VACUUM clause is owed.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
('threshold.bar_scrub.isolated_wick.min_ratio', 'float', '2.5', 1.5, 100,
 '[rca_analysis, todo 594, 2026-11-05] Smallest wick ratio (high / max(open, close) or min(open, close) / low) isolated_wick judges. Grid evidence: every narrow-neighbour bar between 2.5x and 3x on 1d/1h/15m/5m is a bad print (46 inspected, none real); real crash and split days appear below 2.5x. Not an ML learning target.'),
('threshold.bar_scrub.isolated_wick.max_neighbour_span', 'float', '1.5', 1.01, 10,
 '[rca_analysis, todo 594, 2026-11-05] isolated_wick flags only when the adjacent traded bars plus the bar''s body span (max high / min low) less than this: a real wide day moves its neighbours too. Flag counts are a plateau from 1.25 to 2.0; above 1.5 microcaps (BMNR, PATK) enter. Not an ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('threshold.bar_scrub.isolated_wick.min_ratio', '2.5', 1),
       ('threshold.bar_scrub.isolated_wick.max_neighbour_span', '1.5', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT now(), s.config_key, 1, s.config_value, 'migration_580',
       'seed: isolated_wick scrub rule (todo 594)'
  FROM config_state s
 WHERE s.config_key IN ('threshold.bar_scrub.isolated_wick.min_ratio',
                        'threshold.bar_scrub.isolated_wick.max_neighbour_span')
   AND NOT EXISTS (
       SELECT 1 FROM config_history h
        WHERE h.config_key = s.config_key AND h.changed_by = 'migration_580'
 );

UPDATE config_state
SET config_value = (
        config_value::jsonb
        || (SELECT COALESCE(jsonb_agg(r), '[]'::jsonb)
              FROM jsonb_array_elements_text('["isolated_wick", "busted_trade_window"]'::jsonb) r
             WHERE NOT (config_value::jsonb ? r))
    )::text,
    version = version + 1
WHERE config_key = 'threshold.bar_scrub.quarantine_rules'
  AND NOT (config_value::jsonb ?& ARRAY['isolated_wick', 'busted_trade_window']);

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT now(), cs.config_key, cs.version, cs.config_value, 'migration_580',
       'isolated_wick and busted_trade_window flags quarantine a bar: a print its neighbourhood never traded near, and a print inside an exchange-broken window (todo 594)'
  FROM config_state cs
 WHERE cs.config_key = 'threshold.bar_scrub.quarantine_rules'
   AND cs.config_value::jsonb ?& ARRAY['isolated_wick', 'busted_trade_window']
   AND NOT EXISTS (
       SELECT 1 FROM config_history ch
        WHERE ch.config_key = cs.config_key AND ch.version = cs.version
          AND ch.changed_by = 'migration_580'
 );

COMMIT;
