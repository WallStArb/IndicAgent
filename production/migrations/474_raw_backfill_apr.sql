-- 474: raw backfill statement timeout APR key (phase 191 plan 03)
--
-- scripts/ops/bars/ops_raw_backfill.py sets this statement_timeout on its single serial
-- connection. A (symbol, year) window insert is well under a minute; two hours bounds a
-- pathological plan without killing a legitimate large-name window. The script and the key retire
-- together in plan 17.

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
    (
        'infra.raw_backfill.statement_timeout_s',
        'int',
        '7200',
        60,
        NULL,
        '[initial_estimate] Seconds a single ohlcv_raw backfill statement may run before the '
        'server cancels it. Not an ML learning target.'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('infra.raw_backfill.statement_timeout_s', '7200', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), s.config_key, s.version, s.config_value, 'migration:474',
       '[initial_estimate] bound for one backfill window statement (phase 191 plan 03)'
  FROM config_state s
 WHERE s.config_key = 'infra.raw_backfill.statement_timeout_s'
   AND NOT EXISTS (
       SELECT 1 FROM config_history h
        WHERE h.config_key = s.config_key AND h.version = s.version
          AND h.changed_by = 'migration:474'
   );
