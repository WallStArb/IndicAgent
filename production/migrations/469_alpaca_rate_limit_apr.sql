-- 469: Alpaca pacing APR key (todo 521 T4 leaf)
--
-- The capture leaf's native pacing model is one sustained request rate. The
-- measured value: 190 requests/minute sustained clean across the 2026-10-10
-- all-names scratch pull (1,529 names, ~119k requests, zero 429s), under the
-- documented Basic-tier cap of 200 -- a real margin, not the tested edge.

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
    (
        'infra.alpaca.rate_limit_max_requests',
        'integer',
        '190',
        1,
        200,
        '[measured 2026-10-10] Alpaca bars requests per minute, sustained (the capture '
        'leaf''s native pacing). 190/min clean across the 1,529-name scratch pull '
        '(~119k requests, zero 429s); documented Basic cap 200. ML learning target: '
        'recalibrate when the tier changes.'
    ),
    (
        'infra.alpaca.nightly_window_days',
        'integer',
        '5',
        1,
        30,
        '[conventional] The nightly capture leaf''s lookback window in calendar days: '
        '5 days of 5m tail covers weekends and a holiday Monday with margin at '
        '1-minute grain; the gap planner re-asks anything the window misses.'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value)
VALUES
    ('infra.alpaca.rate_limit_max_requests', '190'),
    ('infra.alpaca.nightly_window_days', '5')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), s.config_key, s.version, s.config_value, 'migration:469',
       CASE s.config_key
           WHEN 'infra.alpaca.rate_limit_max_requests' THEN
               '[measured 2026-10-10] 190/min clean across the 1,529-name scratch pull; '
               'documented Basic cap 200'
           ELSE '[conventional] 5-day nightly tail; the gap planner owns older spans'
       END
  FROM config_state s
 WHERE s.config_key IN ('infra.alpaca.rate_limit_max_requests',
                        'infra.alpaca.nightly_window_days')
   AND NOT EXISTS (
       SELECT 1 FROM config_history h
        WHERE h.config_key = s.config_key AND h.version = s.version
          AND h.changed_by = 'migration:469'
   );
