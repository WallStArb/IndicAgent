-- Migration 532: the ten remaining config_schema rows carry a value_type ConfigService rejects.
--
-- ConfigService._parse_value and validate_value know int, float, bool, str, string and json.
-- Seven keys were seeded as 'integer' and three as 'text', so ConfigService.set refused every
-- write to them ("Unknown value_type") and a change had to go in by direct SQL, which skips the
-- validation and the config_history outbox. Migration 531 fixed infra.backfill.fetch_concurrency
-- the same way.
--
-- Readers checked (todo 556): every reader casts or accepts the uncast form, so the corrected
-- types change no read. The seven integer keys are read with int() (select_books.py,
-- ops_bar_nightly.py) or have no reader (alpha.ic.min_obs_daily_features). The two write-method
-- keys are read with str(). rebuild_state_table is a JSON document read as a raw string and
-- passed to json.loads by ops_intraday_venue_recovery.py, so it becomes 'str', not 'json'
-- (a 'json' type would make ConfigService hand that reader a dict).

BEGIN;

UPDATE config_schema
   SET value_type = 'int'
 WHERE value_type = 'integer'
   AND config_key IN (
       'alpha.ic.min_obs_daily_features',
       'alpha.selection.stepm.reps',
       'alpha.selection.stepm.seed',
       'infra.alpaca.nightly_deadline_minutes',
       'infra.alpaca.nightly_max_requests',
       'infra.alpaca.nightly_window_days',
       'infra.alpaca.rate_limit_max_requests'
   );

UPDATE config_schema
   SET value_type = 'str'
 WHERE value_type = 'text'
   AND config_key IN (
       'infra.bar_derivation.daily_write_method',
       'infra.bar_derivation.grid_write_method',
       'infra.bar_derivation.rebuild_state_table'
   );

COMMIT;
