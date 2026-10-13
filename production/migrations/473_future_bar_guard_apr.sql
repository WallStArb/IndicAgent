-- 473: future-bar tolerance APR key (phase 191 plan 02, todo 520 fold-in)
--
-- services/ohlcv_raw_writer.py refuses a bar whose timestamp is later than now plus this many
-- seconds, before any SQL. The IBKR forming-slot case is at most one bar, so one hour covers 1h
-- bars. The D7 condition for todo 520 is not built in phase 191.

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
    (
        'threshold.bar_integrity.future_bar_tolerance_s',
        'int',
        '3600',
        0,
        NULL,
        '[initial_estimate] Seconds past now a bar timestamp may lie before the raw writer refuses '
        'it. A forming IBKR slot is at most one bar ahead, so 3600 covers 1h bars. '
        'Not an ML learning target.'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('threshold.bar_integrity.future_bar_tolerance_s', '3600', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), s.config_key, s.version, s.config_value, 'migration:473',
       '[initial_estimate] one hour covers a forming 1h slot (todo 520 fold-in, phase 191)'
  FROM config_state s
 WHERE s.config_key = 'threshold.bar_integrity.future_bar_tolerance_s'
   AND NOT EXISTS (
       SELECT 1 FROM config_history h
        WHERE h.config_key = s.config_key AND h.version = s.version
          AND h.changed_by = 'migration:473'
   );
