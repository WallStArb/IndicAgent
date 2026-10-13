-- 471: fetcher concurrency APR key (todo 534)
--
-- The fetch loop takes one queue item at a time with one request in flight. A 5m request answers
-- in a median 27.8 s (p90 52 s, 2026-10-12, ohlcv_request), so one in flight gives about 130
-- requests an hour against a limiter that allows 348. The key bounds how many items the loop
-- runs at once; 1 is the old serial behavior.

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
    (
        'infra.backfill.fetch_concurrency',
        'integer',
        '1',
        1,
        8,
        '[initial_estimate] Queue items the fetcher loop runs at once (one request in flight each). '
        '1 is serial. 5m answers in a median 28 s, so 3-4 reaches the 348/hour limiter ceiling; '
        'the shared sliding-window limiter still paces every request. ML learning target: '
        'recalibrate against measured pacing pushback (todo 505).'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('infra.backfill.fetch_concurrency', '1', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), s.config_key, s.version, s.config_value, 'migration:471',
       '[initial_estimate] serial until the concurrent loop is measured (todo 534)'
  FROM config_state s
 WHERE s.config_key = 'infra.backfill.fetch_concurrency'
   AND NOT EXISTS (
       SELECT 1 FROM config_history h
        WHERE h.config_key = s.config_key AND h.version = s.version
          AND h.changed_by = 'migration:471'
   );
